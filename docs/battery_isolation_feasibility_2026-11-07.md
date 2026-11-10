# Battery isolation with the Ag105 kept: feasibility study (2026-11-07)

**Scope.** This is the single authoritative decision document for the question whether the battery pack can be switched,
under Teensy control, between its terminals and the PCB (J-BT / J-BL) so that the Silvertel Ag105 charger (BOM `CHG`) is
kept and the battery is isolated during charging. The board is revision 20260622 (manufactured); the firmware baseline is
fw v37 rev 2 (`AG105_VBATN_ISOLATED 0`: no regen charging). The study answers the requirements of
`docs/charger_replacement_evaluation_2026-11-05.md` sections 0.1 (operator rulings 1-10) and 1.1 (HR1-HR5), and applies
the two operator rulings of 2026-11-08 on fuel-cell purges (section 0.1). The replacement of the Ag105 by another charger
is outside the scope of this document; that path is the subject of the charger replacement evaluation. The purge
predictor is the operator's design and is outside the scope of this document; it is taken as ideal, and this document
states only the interface that it must satisfy.

**Motivation.** On board revision 20260622 the Ag105 VBat- pins 14/15 are tied to PCB GND. The Ag105 internal current
sense sits between VBat- and Vin-/VLoad- (Ag105 DS V1.1 Fig. 1 p.3), and Table 2 p.4 forbids the GND tie. On 2026-11-04
(log `logs/ML0227.BLG`) the GND pour paralleled the sense: the bus current rose at about 10.6 A/s to about 11.4 A in
1.02 s while reg 0x06 read 0.011-0.033 A, and the estimated module output was 11-13 A against a 2.5 A setting
(`facts_prior.md` section 4.1; `docs/boost-bringup-debug.md`, 2026-11-04 entry). The root cause is UNCONFIRMED by direct
measurement but fits every observation. The operator confirmed that the GND tie is by design (pack V- = PCB ground).

**Evidence base.**

- **Board side (primary, local):** `references/Scale_Car_Board_20260624.sch`, `references/Scale Car Board PCB
  20260625.brd`, the BOM, `references/Scale Car Teensy IO - IO.csv`, `teensy_controller/teensy_controller.ino` (fw v37
  rev 2), `logs/ML0227.BLG` (decoded with `tools/decode_benchlog.py`), the datasheets in `references/Datasheets/`
  (Ag105 DS V1.1, RT1987 DS-00, TPS61288 SLVSFP3C, BQ29200 SLUSA52C, LM1084 SNVS037H) and the Ag105 JSON Tables 3-7.
- **New-part primaries:** vendor PDFs read from the TI site and not saved in the repository, among them TPS2663x
  SLVSE94G, TLV3011B SBOS300C, INA240 SBOS662C and SN74LVC1G74 SCES794G. Each figure is cited in the working material
  with literature number and section.
- **Working material:** `docs/reviews/battery_isolation_2026-11-07/` (cited below as **[STUDY]**): four fact sheets
  (`facts_board.md`, `facts_ag105.md`, `facts_firmware.md`, `facts_prior.md`), three purge fact sheets of 2026-11-08
  (`facts_purge_sequencing.md`, `facts_purge_collapse.md`, `facts_purge_demand.md`), the brainstorm (`brainstorm.md`),
  seven concept dossiers (`concept_IC1` to `concept_IC7`), the seven FMEA reports in `battletest/`, the detailed design
  `detailed_design_IC1.md` revision 12 (cited as **[DD]**) and the calculation scripts in `calc/` with their output
  files.
- **Evidence tags.** **PROVEN_CALC**: shown by a cited calculation from primary values. **BENCH**: no primary gives the
  value; a named bench gate measures it. **TODO(verify: source)**: a primary exists but was not read. **UNCONFIRMED**: an
  inference that no primary states directly. Search snippets and recollection are not used as evidence.

**Status of the hardware.** Nothing has been ordered, built, cut, soldered or flashed. fw v37 rev 2 stays on the bench
board. Only this file and files in [STUDY] were written by the study.

---

## 0. Status, verdict and rulings

### 0.1 Status

The study ran in four stages. Stage 1 wrote four fact sheets, clustered 21 raw concepts into seven **isolation
concepts** (IC1 to IC7) plus four drops, developed each concept into a reviewed dossier and asked three independent
judges to rank them. All three judges selected IC1. Stage 2 developed IC1 into a detailed design. Stage 3 subjected that
design to five battle-test rounds (seven lenses in rounds 1-3, five lenses in rounds 4 and 5) with 180 confirmed
findings and none refuted, and to a completeness critic (33 gaps) after round 3. After the operator rulings of
2026-11-08, revision 9 added FC windows between H-20 purges, and two further battle-test rounds (rounds 6 and 7, four
lenses each) attacked that purge package with 21 confirmed findings and none refuted. Round 8 (five lenses) attacked
revision 11 as a whole design, aimed at the revision-8 hardware that no earlier round had attacked and at the
revision 9-11 firmware rules, with 14 confirmed findings and none refuted. Stage 4 is this document.

The battle-testing did not converge to a clean round. Rounds 4 and 5 found no blocker, but each found majors (9 and 8),
and the adjudication attributes 7 of 9 and 7 of 8 of them to the preceding revision's own fixes. Rounds 6 and 7 found no
blocker and 3 majors each, all in content that revision 9 added. Round 8 found no blocker and 3 majors; on this
document's reading, 2 of the 3 lie in content that the revisions-8 and -11 fixes added (section 3). The design after
round 8 is revision 12, which no round has attacked (section 0.3 item 1).

The selected design is **IC1, commanded low-side return changeover, revision 12** ([DD]). Revisions 9-12 add no
electrical component to revision 8; revision 12 adds one harness routing rule (SHDN_EF in a sleeve of its own), and every
other change is a firmware rule, a part-selection requirement, a gate, a ruling or a statement. Pack negative moves off PCB GND
onto an off-board node (**PACK-**). A three-MOSFET changeover transfers PACK- between PCB GND (the **bonded mode**, the
fail-safe default) and the Ag105 VBat- pins (the **charge mode**). In the charge mode the pack return passes only through
the Ag105 internal sense, which restores the module's own charge-current regulation. A **window** is an interval in the
charge mode with the charger input fed: a **regen window** (fed from V-MOT through D-BC-RG during braking, State 2) or an
**FC window** (fed from VBUS through D-BC-FC). An FC window opens parked in State 1 or State 98 (**variant P**) or, from
revision 9, in State 2 at standstill (**variant D-s**); an FC window in motion is **variant D** ([DD] section 9.11.7).

**Operator rulings of 2026-11-08.** The operator ruled as follows (verbatim):

1. "Regarding the fuel cell purges, those would be handled in firmware by not allowing fuel cell charging during and
   leading up to a purge, and by shifting the share ratio back towards battery power preemptively. Fuel cell charging
   would occur between purges if requested by the EMS."
2. "An unpredicted purge causing the bus to collapse and the system to shut down without any damage to components is
   acceptable. That will be on me to design the purge predictor appropriately. The purge predictor is not within scope
   of this session- assume it works perfectly as far as designing the isolation circuitry goes."

This document applies them as follows ([DD] section 17, Appendix G):

- **OR-P is decided.** A purge predictor exists, is the operator's design and is taken as ideal. This document does not
  design, model or criticise it. The purge figures used are those of `facts_prior.md` section 7 only: period 10.34 s,
  duration 100-140 ms, floor about 1 V. The predictor permit replaces the fw v33b FC-only lockout as the purge gate of
  every FC-fed session; the lockout keeps refusing FC-only source selection. The design states the interface that the
  predictor must satisfy (section 0.2, Table 1b).
- **OR-SC is decided (new).** For an unpredicted purge the design guarantees only a safe collapse: the bus may collapse
  and the firmware latches State 99, but no component may be damaged on the collapse, on the recovery of the fuel cell
  or at the next power-up, and the pack may not be left in a hazardous configuration. A ride-through is not designed.
- **OR-O is replaced by OR-O'.** Ruling (1) asks for FC charging between purges when the EMS requests it, and the EMS
  design places charge requests inside drive cycles (`charge_goal`, the SDP charge cells, MPC charge commits). This
  reverses OR-O, which limited FC windows to State 1 and State 98. The interpretation adopted is: variants P and D-s are evaluated and proposed;
  variant D is evaluated and not adopted (ruling OR-DM, section 0.2).

**Operator rulings of 2026-11-09.** The operator answered the open rulings of [DD] revision 12 through the chat question
dialog: OR-AC option (d) for the first build, acceptance of the two round-8 residuals (row F66 and sleeve segregation),
and every other ruling at the answer that the design proposes or recommends. Section 0.4 gives the answers verbatim and
the resulting status of each ruling. After them, 30 of the 36 rulings are decided and 6 remain open; no open ruling
blocks a motherboard change directly. The design revision number is unchanged.

### 0.2 Feasibility verdict

The operator's literal goal is feasible by calculation, as a standstill charger, subject to the bench gates of section 4.
Under the rulings of 2026-11-08, fuel-cell charging from the H-20 between predicted purges is shown by sequence
calculation, parked and in State 2 at standstill. The research requirement of ruling 1 is still not met: regen
harvesting fails as specified, and fuel-cell charging during a drive cycle is bounded to the stops and is undetermined
against the requests of an EMS. Table 1 gives the verdict per requirement.

Table 1. Feasibility verdict per requirement (IC1 revision 12).

| Requirement | Verdict | Basis | Evidence class |
|---|---|---|---|
| Operator goal (a): the Ag105 is kept | **Met** | The module stays soldered. Pins 14/15 and pin 10 are cut above the board (modifications M1, M2) and rerouted to the changeover and to an eFuse. | Design; buildability BENCH (gate D-2: module standoff and cut gap) |
| Operator goal (b): the battery is isolated during charging | **Met as return isolation**, which ruling OR-S accepts (2026-11-09) | The pack return is isolated from PCB GND in every window, so the ML0227 sense bypass is absent. Pack positive stays on VBT in every mode, so the pack keeps supplying the Teensy LM1084 and the BT boost through the sense in reverse. The literal two-leg transfer (IC6) fails HR1 by construction (section 1.3). | PROVEN_CALC for the topology; the absence of any hidden pack-negative bond is BENCH (gates C-1, C-1b, C-1c) |
| Operator goal (c): the switching is Teensy-controlled | **Met** | Every window is entered by a Teensy pin-33 edge that sets a permit latch (FF1). The eFuse on the charger input needs FF1 AND a pumped arm toggled from `loop()` AND a source term. The bonded mode is the hardware default in reset, hang, brownout and power loss. | PROVEN_CALC (section 0.2 row HR5) |
| HR1 regen harvesting | **Fails as stated**; a relaxed criterion is BENCH | The 23 W input criterion is unreachable: the module output is limited to 2.5 A including the VBT load, which gives at most 22.73 W at the 8.0 V entry gate ([DD] section 7.1, `calc/ic1_rev4_calcs.py` section 12). The regen profile (1.75 A) reaches 19.8-22.4 W, which meets the 18.9 W peak only with the unverified 0.88 efficiency, and only up to 45 C module ambient (Ag105 DS p.17 Table 9). Every pulse needs a cold Ag105 start. On the 19 ms pulse the hardware chain leaves 5.3-6.4 ms, of which the eFuse uses 4.4-5.6 ms (`calc/ic1_rev4_calcs.py` section 11); at the prior 65-170 ms cold start the rise of no pulse is captured. Revision 8 states the powered interval of a pulse as the rise plus the VESC-stop tail, during which VOK stays asserted for 84-416 ms; a start inside the tail can capture tail energy, which is BENCH (V2-4; [DD] section 7.8, finding BT5-TR-04). The Stage-3 hold-up, the remaining hardware lever, was withdrawn in revision 7 ([DD] section 14.4). On the 23 recorded Pi sessions, 12 admit regen windows under the revision-6 preconditions (`calc/bt3_bag_scan_plaus.py`, `calc/bt3_bag_scan_vstart.py`). The design itself states the Stage-2 harvesting value as near zero on present evidence ([DD] section 14.3). | FAILS by calculation; capture per pulse family, including the tail, is BENCH (S0-6, V2-0, V2-4) |
| HR2 fuel-cell charging | **Met by sequence calculation under rulings OR-P and OR-SC**, conditional on ruling 9 (R_KA), gate S0-6 and the Pi round of ruling OR-RQ. **Parked (P): 1.17-1.19 A mean net pack current. Drive cycle (D-s): at most 1.9-31.9 mAh per cycle (upper bound). Against EMS FC-charge requests: undetermined.** | An FC window holds BT_BUS open, so the bus is FC-only and an H-20 purge would collapse it. The ideal predictor announces each onset at least 80 ms ahead; the window then drops its feed, drains the module, bonds the pack and re-closes BT_BUS, which conducts 33.6-47.0 ms after the prediction (61.7 ms on the deadline chain), before the onset ([DD] Tables 20-21). Charge current resumes 0.37-0.49 s after the onset, so 94.5-95.6 % of each 10.34 s period carries charge ([DD] Table 22, `calc/ic1_rev10_calcs.py` section 2). The parked figure is net pack current: 1.18-1.20 A of charger output less the pack supply of an ASSUMED VBT load I_L of 0.2-0.3 A in the dead time (revision 12, `calc/ic1_rev12_calcs.py` section 6). Revision 12 also removes a deadlock in which a standing parked request aborted the Idle-entry self-test and its deferred result then refused every P window (BT8-LS-01). The window input is 0.82-0.93 A of bus current at the 1.25 A FC profile, inside the 1.25 A governor, the 1.247 A P_MAX and the 1.4 A `OC_FC` (0.245-0.261 A of `OC_FC` margin after the INA253A1 zero error at the revision-11 fixed window split; `calc/purge_demand_budget.py` output s1, `calc/ic1_rev11_calcs.py` section 2). Variant D-s gives 9-53 % of the cycle time on the plant drive cycles with a request at every stop (Table 1a). The recorded Pi sessions carry 0 s of FC-charge request: their `charge_goal` is the regen latch of the deployed SDP nodes (`calc/bt7_req_origin_output.txt`). Without R_KA a Bring-Up of 8.4-11.7 s per cold start leaves 0-0.19 A mean. An unpredicted purge latches State 99 with no damage path found (safe collapse, ruling OR-SC). | PROVEN_CALC by sequence; window value and chain timing BENCH (S0-6, W1, W2, W2a-W2e); no damage on a collapse UNCONFIRMED until W2c |
| HR3 no circular loop | **Met against single faults by calculation**, conditional on detectors and gates | Bonded mode: the charger input is unfed and the eFuse needs FF1; a fed input with both feeds LOW latches `ERR_VCHG_FED`. Regen window: a two-out-of-two V-MOT-over-VBUS detector (**VOK**) acts on two diverse elements, and `ERR_VOK_STUCK` latches on a channel that permits below the healthy ratio. FC window: a hardware clamp (Q_X1) holds BT_BUS open, and a hardware BT-loop detector (D5) cuts a shorted D-BT-EN. A D-BC-FC or D-BC-RG power-stage short is a one-fault loop path that only `ERR_VCHG_FED` closes before a window opens. The eFuse-bypass case counts as two failures only after the injected-bypass gate (C-2b, S0-14) has qualified the module-node probe. | PROVEN_CALC with conditions ([DD] section 13 Table 17, section 11); gates C-2, C-2b, B10, S0-2, S0-14, V2-1, V2-2 |
| HR4 no runaway | **Bounded by calculation** far below the ML0227 current | Pack charge current: comparator U_C2, 2.65-3.64 A. Charger input: comparator U_IM, 1.51-1.98 A, below the eFuse I_OL minimum of 2.06 A (R_ILIM 8.06 kOhm, SLVSE94G IMON gain range; `calc/ic1_rev6_calcs.py` section 5). eFuse I_OL 2.06-2.41 A. Profile networks at or below 1.75 A for every open or short fault. Two pack-direct paths that bypassed every bound are closed: a VBATN_X chafe clears the fuse F_VX (revision 6), and the balance midpoint reaches GND only through RB3 (clamped by D_VC1) or RB1A 4.7 kOhm, at most 16.2 mA and 0.83 mA (revision 7, rows F34b and F47). A dump stuck on is caught by the pin-32-LOW dump check before the first window of each power cycle, or by U_IM at that eFuse start; a dump that sticks later is ended by `OC_FC` and U_IM while the module charges (revision 8, row F50; `OC_FC` acts on BENCH_TEST 0 builds only). For a chafed or shorted signal lead the protection is segregation (two insulation failures), not the revision-8 LB-entry resistors: those resistors limit only the current on the LB side, the TLV3011B inputs and the LVC outputs have no positive clamp, the i.MX RT1062 pad has no injection rating, and the CB-end pins of the same leads are unprotected (revision 12, rows F54b, F54c, F66; BT8-DS-01, BT8-DS-02). An open R_SH element exposes both INA240 inputs to about -8.4 V against the -6 V absolute maximum (row F34c, ruling OR-AB). The Ag105's own regulation is credited only after S0-2 and D-3. | PROVEN_CALC; per-unit trim BENCH (S0-12b); lead faults rest on segregation (gates C-1, C-4); pin-20 pad injection TODO(verify), [DD] open item 29 |
| HR5 fail-safe Teensy-commanded inhibit | **Met by calculation for absent rails**; two cases bench-gated | Bonded mode, D-BT-SQ disabled and the eFuse off with the Teensy unpowered, in reset (FF1 clears at once through the buffered pin-33 path), hung (the pump clears FF1 in 43-76 ms; the RTWDOG resets the MCU) or with 3V3 or 5V absent. WDOG1_B is no longer used, because pin 20 carries the VC1 tap since revision 7. No autonomous re-arm: FF1 needs a pin-33 edge. A chafed signal lead reaches a pack or bus voltage, or the trip logic's 3V3 rail, only after two insulation failures: the low-voltage leads run in segregated sleeves, and since revision 12 SHDN_EF runs in a sleeve of its own, because a single MD_G-SHDN_EF short parked the eFuse SHDN pin and the Q_MD gate at 1.55-1.68 V in both EF_EN states (BT8-FM-01, row F66; `calc/ic1_rev12_calcs.py` section 1). The double fault may destroy Q_MD if its V_GS(th) range covers 1.55-1.68 V; the operator accepted this residual on 2026-11-09 (section 0.4). A slow 3V3 collapse and a logic-board-only 3V3 loss with the Teensy running are not proven. | PROVEN_CALC; gates B11, B11b-e, B16, C-1 and C-4 (sleeve and lead-to-lead insulation), C-2a, C-2b (h) |

The verdict therefore separates three questions. The operator's literal goal, a Teensy-controlled isolation that keeps
the Ag105 and prevents a recurrence of ML0227, is feasible on paper as Stage 0 followed by Stage 1 (section 2.3). FC
charging from the H-20 is feasible by sequence between predicted purges, parked and at drive-cycle stops, under the
rulings of 2026-11-08. However, IC1 does not deliver the regen charging that ruling 1 makes a hard requirement, and its
FC charging during a drive cycle is limited to the stops. The HR1 shortfall is structural to the Ag105 at 2S (2.5 A
output ceiling, slow cold start); no switch topology in the study changes it. The former HR2 block came from the FC-only
bus across H-20 purges; the rulings move that block from the isolation design to the operator's predictor.

**FC-window variants.** Table 1a compares the three variants against HR2 ([DD] section 9.11.7, Tables 26 and 27). The
drive-cycle figures come from the plant demand model with R_KA fitted at a 7.4 V pack, with a charge request assumed at
every stop and no standstill dwell T_still; they are upper bounds (`calc/ic1_rev9_calcs.py` section 4,
`calc/ic1_rev10_calcs.py` section 6).

Table 1a. FC-window variants under rulings OR-P and OR-SC (IC1 revision 12).

| Item | P (parked, State 1 or 98) | D-s (State 2 at standstill) | D (State 2 in motion) |
|---|---|---|---|
| Status | Proposed (OR-O') | Proposed (OR-O'), behind `IC1_FC_RUN_STANDSTILL` after gate W2b | Not adopted (OR-DM) |
| Predictor lead time | T_lead,min 80 ms | T_lead,min 80 ms | 290 ms (T_lead,nom, upper bound) for the share override |
| Share shift of ruling (1) | The BT_BUS re-close; no share loop runs in State 1 or 98 | The BT_BUS re-close; below the 0.25 A gate the share loop freezes or holds its split, so an override would move no MDAC code ([DD] section 9.11.3 step 5) | A share override toward the battery |
| FC load at the onset | Auxiliary load only (0.09-0.15 A HIL, 0.016-0.024 A in the bags) | Auxiliary load only | Traction plus auxiliary, up to 1.25 A; a two-source purge above a pre-purge I_fc of 0.712 A is not recorded (172 recorded purges, `calc/purge_seq_bags_output.txt` section 5) |
| Charge value | 1.17-1.19 A mean net pack current with R_KA (1.18-1.20 A of charger output; revision 12), at an ASSUMED dead-time VBT load of 0.2-0.3 A; 0-0.19 A without it | 9-53 % of the cycle time at 1.25 A, 1.9-31.9 mAh per cycle (61 s cycle 1.9 mAh, FTP-75 slice 23.3 mAh, ftp75c 12.4 mAh, UDDS 19.3 mAh, the two regen test cycles 28.0-31.9 mAh) | 19.8-63.2 mAh per cycle nominal, 3.5-34.3 mAh pessimistic; D (pessimistic) is 1.2-1.8x D-s |
| Against recorded EMS FC-charge requests | 0 in Run | 0 s: the recorded sessions carry no FC-charge request | 0 s |
| Traction allowance in the window | None | None: the window ends on the traction command before current flows; torque resumes after BT_BUS has conducted (43-47 ms healthy, at most 61.7 ms) | 0.06-0.33 A bus-side, the size of the INA253A1 zero error (up to 0.1 A per channel) and of the 24-48 % plant-to-rig traction error; 0.03-0.08 A of voltage headroom at a drooped split (`calc/bt7_transient_sim.py` section 5) |
| Unpredicted purge | Safe collapse | Safe collapse | Safe collapse; the VESC browns out and the vehicle coasts |

Variant D is not unsafe by the safe-collapse analysis below. However, its worth cannot be shown. The recorded sessions
carry 0 s of FC-charge request, so they give D no value over D-s. Its traction allowance is consumed by the
current-sense error, and a purge at a pre-purge I_fc of 1.0-1.25 A lies outside the recorded evidence. Its
in-motion increment over D-s on the plant cycles rests on that allowance. This document therefore recommends P and D-s
and does not recommend in-motion charging. D is re-evaluated after gates B8-1 and W1 and the EMS walk of [DD] open item
40. In-drive charging at stops (D-s) is recommended only behind gate W2b, and its value against a real EMS is
undetermined: the deployed Pi nodes use `charge_goal` as their regen gate and make no FC-charge request
(`sdp_ems_node_2026-10-28B.py`:293-319; `calc/bt7_req_origin_output.txt`: 446.6 s of `charge_goal`, of which 419.3 s
is the regen latch, 0.0 s the FC-charge branch and 27.3 s unclassified). From revision 11 a window request is
therefore an explicit flag (command byte 20 = 0xA5 with `charge_goal` above `CHG_GOAL_MIN`), which needs a Pi round
(ruling OR-RQ).

**Predictor interface.** The predictor delivers `purge_tto` (the predicted time to the next onset, or UNKNOWN) and
`purge_active` (TRUE from the onset to the declared end) to the mode manager in every loop iteration. Table 1b states
the requirements that the operator's predictor must meet ([DD] section 9.11.2, requirements PI-1 to PI-7).

Table 1b. Requirements on the operator's purge predictor (IC1 revision 12).

| ID | Requirement | Value | Basis |
|---|---|---|---|
| PI-1 | Minimum lead time from "purge predicted" to the onset, whenever an FC-fed session can be open (P, D-s, the dump check, the configuration check, the probe) | **T_lead,min = 80 ms** | The exit chain (feed drop, module drain, bond, BT_BUS re-close, D-BT-EN conduction) conducts 33.6-34.7 ms typical, 47.0 ms worst healthy and 61.7 ms on the deadline chain after the prediction; 80 ms is the late threshold plus one 9.76 ms loop gap, rounded up (`calc/ic1_rev10_calcs.py` section 1) |
| PI-1 | Lead time in State 2 in closed loop with no FC-fed session (the share override of ruling (1)) | T_lead,nom = 290 ms, an upper bound | Share-loop handoff slew at the p99 loop; a shorter lead leaves the shift incomplete with both source pairs closed and no fault ([DD] Table 20) |
| PI-1 | Late threshold: a prediction first observed with `purge_tto` below it, inside a session that holds BT_BUS open, latches State 99 | T_late = 61 ms | Deadline chain from the observing iteration, 60.6 ms ([DD] section 9.11.2) |
| PI-2 | End of purge: the predictor declares it; firmware also requires V_fc at or above 7.0 V on two settled iterations | Design figure: onset + 160 ms | Charge current resumes 0.37-0.49 s after the onset, because VCHG-IN must decay below 11 V (365.6 ms after the feed drop) ([DD] section 9.11.4) |
| PI-3 | Horizon: `purge_tto` valid up to at least | 1.282 s | A window must carry 1.0 s of charge current before the next lead time (entry 201.8 ms + 1.0 s + lead) |
| PI-4 | Fail closed: UNKNOWN from an H-20 start or a reset until the first tracked purge; UNKNOWN refuses every FC-fed session; an UNKNOWN transition or `purge_active` rising inside a session that holds BT_BUS open latches State 99 | - | The bt6 grid gives OPEN in 4860 of 4860 cases with this latch, against 15 HAZARD cases when UNKNOWN closed a session like a prediction (`calc/ic1_rev10_calcs.py` section 5) |
| PI-5 | A source without purges (a bench supply on J-FC) is reported as "no onset inside the horizon" | - | Gates C-2b and W1 run with the same firmware |
| PI-6 | The predictor runs in `loop()` and does not block | - | A stall of about 40 ms stops the pump and clears FF1 in hardware |
| PI-7 | The values above contain no allowance for prediction error; the operator adds the predictor's own error band to T_lead,min, T_lead,nom and the declared end | - | Ruling OR-P |

Two conditions bind the interface figures. First, the 80 ms and 61 ms figures hold only while the maximum loop
iteration of the production build stays at or below 19.0 ms; gates W1 and W2b require 15 ms or less, and any excess
over 19.0 ms raises T_lead,min and T_late by the same amount (`calc/ic1_rev11_calcs.py` section 3; the only
measurement is 9.76 ms on a State-98, USE_ETHERNET 0 build). Second, they assume an RT1987 turn-on delay t_D_ON of
12 ms or less, for which DS-00 gives no maximum; each millisecond above 12 ms, measured at gate W2a, adds one
millisecond to both. Either result is a requirement change on the operator's predictor.

**Safe collapse on an unpredicted purge.** Inside every session that holds BT_BUS open, the new fault
`ERR_FC_ONLY_COLLAPSE` latches State 99 with no dwell on V_chg below 13.0 V with EF_EN H, or on V_bus below 12.0 V, or
on a late or UNKNOWN predictor event (policy E2, [DD] section 9.11.5). No bus switch re-closes after the latch. On the
collapse grid the latch comes 1.4-50.3 ms after the onset, and FC_BUS is LOW before the earliest FC recovery at 80 ms in
every case except 12, which all have the bus at 12.04 V or more (`calc/purge_collapse_sim.py` section 3b). Eleven
damage mechanisms were examined, among them the Death-5 hot-plug on the FC recovery, the TPS61288 body-diode back-feed,
RT1987 stress, the pack left in the charge mode and the next power-up; no damage path was found ([DD] Table 24). At the
next power-up no window state is stored, the Teensy reset clears FF1, VCHG-IN is below 11 V within about 0.35 s, and a
window again needs the boot self-test and a dump-check pass. A pack below 7.4 V is refused a window (refusal code 14).
"No damage" is UNCONFIRMED until gate W2c, because the only bench record of an FC-window collapse (2026-10-28,
pre-IC1 topology) has no damage inspection. The latched State 99 keeps the Teensy on the pack at about 0.2-0.25 A
(UNCONFIRMED), which can over-discharge the pack in 8-25 h; this is an operating exposure of any powered board, and
ruling OR-PK makes a parked H-20 window attended, with a Pi alert on any State 99.

**WARNING:** After any State-99 latch, power-cycle the board or disconnect the pack. If the board stays latched, the
logic load can over-discharge the pack in 8-25 h.

Battle-test rounds 4 and 5 did not change any verdict in kind. They changed three bases: HR1 lost the Stage-3 hold-up
and gained the VESC-stop tail as a BENCH capture interval; HR4 gained the stuck-dump detection, the 16.2 mA balance-lead
bound and the signal-lead injection bound, and records the open-R_SH amplifier exposure; HR5 now rests on the RTWDOG
and the pump alone, and on the LB-entry resistors for a chafed lead. The rulings of 2026-11-08 changed the HR2 verdict
in kind, from blocked to met by sequence calculation. Rounds 6 and 7 then changed its bases: one lead time of 80 ms for
every FC window, a fail-closed UNKNOWN, the explicit EMS request, the dump check admitted in State 2 at standstill and a
fixed MDAC split inside every window; they withdrew the revision-10 figure of D-s against the recorded requests.
Round 8 changed no verdict in kind. It restated the HR2 parked figure as net pack current (1.17-1.19 A), removed a
P-window deadlock, and moved the HR4 and HR5 basis for a chafed or shorted signal lead from the LB-entry resistors to
segregation (two insulation failures).

### 0.3 Conditions on the verdict

The verdict holds only under the following conditions.

1. **The battle-testing has not converged, and revision 12 is not battle-tested.** Rounds 4 and 5 (on revisions 6 and
   7) found no blocker but 9 and 8 majors, most of them in the preceding revision's fixes (section 3.2). Rounds 6 and 7
   attacked only the purge package and found 3 majors each, all in content that revision 9 added. Round 8 attacked
   revision 11 as a whole design through five lenses (FMEA, logic, datasheet, transient, requirements), aimed at the
   revision-8 hardware (R_VC1c, R_MS3, R_BL3/R_BL2, R_PGL and the D_VC1 selection: [DD] Appendix F later-review items
   1-4) and at the revision 9-11 rules. It found 3 majors and 11 minors and refuted none; the verifiers lowered five
   findings from major to minor. On this document's reading, two of the three majors lie in earlier fixes: the
   revision-8 sleeve rule (BT8-FM-01) and the revision-11 parked request form (BT8-LS-01). Revision 12 answers all 14
   findings with no new electrical component. Three sets of items remain unattacked. The first is the set of
   revision-12 changes, on which [DD] Appendix J lists seven items: the SHDN_EF sleeve route and its connector pin-out,
   the C-2b item (h) injection, the self-test re-run rule, the dump-check retry, the J-FC setting, OR-AC option (d) and
   the C_DV rule. The second is [DD] Appendix I items 2-6 (the byte-20 request flag and a missing flag inside a window,
   the fixed split and the held share-loop state after a long frozen window, the guarded FC_BUS release in Idle, the
   boost-enable entry condition, the 15 ms iteration criterion), on which round 8 did not report. The third is [DD]
   Appendix F items 5-8 (the per-power-cycle dump check, the exit hold check precondition, `OC_FC` as the FC-window
   stuck-dump detector and the I_NB,cal measurement); Appendix J states coverage of items 1-4 only, and BT8-LS-02 bears
   on item 5. On the record of rounds 2-8, a revision that has not been attacked is expected to carry majors in its own
   fixes. This document therefore recommends one further round on revision 12 before any motherboard change, with the
   FMEA, logic, transient, requirements and buildability lenses aimed at the three sets above. The buildability lens has not
   run since round 5, and the SHDN_EF sleeve and connector pin-out are buildability questions. Stage 0 needs no board
   change and may run first.
2. **Stage 0 must pass its decisive gates:** S0-2 (the restored sense regulates in every reachable sub-state, with a
   positive control), S0-12b (per-unit U_IM trim below the eFuse I_OL), S0-11 (module input capacitance between 47 and
   221 uF, and the dump timing) and S0-14 (the module-node probe detects an injected eFuse bypass). S0-6 decides HR1 and,
   with ruling 9 (R_KA), whether FC windows between purges deliver charge at all: the HR2 figures of Table 1a hold only
   if the Ag105 starts in 65-170 ms at every window.
3. **The board gates must pass:** D-2 (the Ag105 standoff admits the pin cuts), D-3 (the vehicle Ag105, overstressed in
   ML0227, is qualified or replaced), BG-17a before the rework and BG-17b after it (the BQ29200 OUT pin is reachable and
   the cell-1 trip holds with D_VC1 and RB1A 4.7 kOhm fitted; charging is not enabled without it), P8 (nothing drives the
   old ENC_B net on pin 8, which may still carry the encoder pull-up) and B-PKN (D_VC1 holds VC1 above -0.3 V; run on the
   vehicle board with RB1A.2 lifted until TI rates the VC1_CB pin). From revision 12, B-FPK and B-PKN run before C-2b,
   and B-PKN has a NO-GO clause for the provisional D_VC1 of OR-AC option (d).
4. **The MCU watchdog round is complete before the first charge** (ruling 5, OR-K; RTWDOG only, since pin 20 is no
   longer available for WDOG1_B).
5. **The part selections are made.** The clamp D_VC1 must meet V_F at most 0.25 V at 16.2 mA at T_min and I_R at most
   40 uA at 4.2 V at T_M16,max. Revision 12 has identified no passive part that meets both: a real low-V_F Schottky leaks
   about 10 times its saturation current, so the 40 uA budget holds only to a T_M16,max of about 44 C even at T_min 25 C, and
   the lowest-V_F candidate found (onsemi NSR0320MW2) fails the 0.25 V limit on its 25 C maximum row (0.283 V) and sits
   17 mV inside the -0.3 V requirement (`calc/ic1_rev12_calcs.py` section 8; BT8-DS-04). The ordering gap noted in
   earlier versions of this document (gate B8 measures T_M16,max but needs a fitted D_VC1) was confirmed by round 8
   (BT8-REQ-02). Revision 12 splits B8 into B8-1 (Stage 1, an FC window after W1, with the M16 temperature) and B8-2
   (Stage 2, regen window, the HR1 hold condition I_L at most 0.75 A), and adds OR-AC option (d): a provisional part for
   the bench-attended first build at T_min 25 C, replaced after B8-1 by option (a), option (c) or a confirmed passive
   part; the operator chose option (d) for the first build on 2026-11-09 (section 0.4). The dump FET Q_MD is not selected; its selection must now record the V_GS(th) range and the
   transfer characteristic near 1.55-1.68 V, a linear-mode SOA and V_GSS, because row F66 depends on them (CC-B7,
   BT8-FM-01). The fuse F_VX (candidate Littelfuse Nano2 451/453 4 A, re-read at order) and R_MD, rated on the
   continuous-pulse curve for the repetitive dump, are also unselected. The pin-20 pad of the VC1 tap has no injection
   rating ([DD] open item 29, narrowed in revision 12 to that pad); the other leads rely on segregation, which the
   operator accepted on 2026-11-09 as their only protection.
6. **The FC-window gates pass and the interfaces exist** (HR2 only). Gate W1 (first window from a bench supply) must
   meet the revision-11 criteria: in-window V_chg at or above the measured S0-4 threshold plus 0.3 V and at or above
   14.0 V, and a maximum production-build iteration of 15 ms or less. From revision 12, W1 is two 30 s windows (the
   window cap is 30 s) requested from a new State-98 window-request key, and every bench-supply session on J-FC uses
   12.0 V with a 1.5 A limit for commissioning and a 2.0 A limit thereafter; the revision-11 setting of 16 V put 4.28 V
   on Teensy pin 24 against its 3.6 V absolute maximum and held the FC boost out of regulation (BT8-REQ-01,
   `calc/ic1_rev12_calcs.py` section 2). Gate W2a must show a BT_BUS and FC_BUS conduction
   onset at or below 31.8 ms on a live bus. Gates W2 (parked H-20 windows for at least 30 min between predicted purges),
   W2c (unpredicted collapse from a bench supply, with the damage inspection and the State-99 drain), W2d (false-latch
   count) and, for D-s, W2b must pass. Gate W2e must show that the deployed Pi node never opens a window and that the
   updated node opens one only on an FC-charge decision; this needs the Pi round of ruling OR-RQ (request flag 0xA5 in
   command byte 20, the parked form with `mode_cmd` 4, the Table 25 refusal codes) in lockstep with telemetry protocol
   v6. The gate order is W1, B8-1, W2a, W2e, W2, W2c, W2b, W2d (revision 12). The operator's predictor must meet
   Table 1b with its own error band added (PI-7). A timing NO-GO at W1 or W2a
   raises T_lead,min and T_late, which is a requirement change on the predictor.
7. **The operator rulings of section 0.4 are taken.** On 2026-11-09 the operator decided 28 of the 34 rulings that were
   open (two of them by a named bench gate: OR-I by S0-2 and ruling 9 by S0-6) and accepted the two round-8 residuals.
   Six rulings remain open: OR-J (needed before gate S0-10 in Stage 0), OR-L, OR-R and OR-X (needed before the Stage-1
   firmware round), OR-B (Stage 2) and OR-F (Stage 3).

### 0.4 Operator rulings

**Operator rulings 2026-11-09.** The operator answered the open rulings on 2026-11-09 through the chat question dialog.
The answers were as follows (verbatim):

1. "OR-AC: option (d) chosen for the first build - provisional D_VC1 (candidate NSR0320MW2) at T_min 25 C,
   bench-attended Stage-1 sessions only, so C-1, BG-17b, B-PKN at 25 C and B8-1 can run; choose (a) or (c) after B8-1
   unless B8-1 shows T_M16,max below about 44 C."
2. "Row F66 double-insulation residual (Q_MD may be destroyed if both the SHDN_EF and CB-LB sleeve insulation fail and
   its V_GS(th) covers 1.55-1.68 V): ACCEPTED. Q_MD selection must still record V_GS(th), SOA and V_GSS."
3. "Sleeve segregation accepted as the only protection of SHDN_EF, MD_G, PROFILE, IMON, MS, EF_FLT_N and the VC1 tap at
   both lead ends (BT8-DS-01/02); no clamps added."
4. "Accept as proposed": every other open ruling is recorded at the answer the design proposes or recommends.

A ruling whose proposal names one answer is recorded at that answer; a ruling whose proposal leaves the answer to a
named bench gate is recorded as decided by that gate; a ruling that offers two or more options without a
recommendation, or asks a question without a proposed answer, stays open ([DD] section 17, Status column).

The detailed design lists 36 rulings ([DD] section 17, revision 12). Two were decided on 2026-11-08 (OR-P and OR-SC,
section 0.1) and 28 on 2026-11-09, of which OR-I and ruling 9 are decided by gates S0-2 and S0-6; 6 remain open (OR-B,
OR-F, OR-J, OR-L, OR-R and OR-X). Table 2 lists the decisive rulings with their status; the rest are listed after it.

The three round-8 acceptances (OR-AC option (d), the row F66 residual and sleeve segregation) no longer block a
motherboard change, and no open ruling blocks it directly; OR-J is needed within Stage 0. Before a motherboard change
the following items still block:

- the Q_MD selection, which records the V_GS(th) range, the linear-mode SOA and V_GSS on which row F66 depends;
- Stage 0, with ruling 9 decided at S0-6 and OR-J before S0-10;
- the board gates of section 4.3 ([DD] section 15.2);
- a further battle-test round on revision 12 with the FMEA, logic, transient, requirements and buildability lenses
  (section 0.3 item 1).

Table 2. Decided and decisive operator rulings.

| ID | Decision | Consequence |
|---|---|---|
| OR-P | **Decided 2026-11-08** (section 0.1): a purge predictor exists, is the operator's design, is out of scope and is taken as ideal; its permit replaces the fw v33b lockout for every FC-fed session | FC windows run from the H-20 between predicted purges. The operator's predictor must meet Table 1b; a W1 or W2a timing NO-GO raises its lead time |
| OR-SC | **Decided 2026-11-08** (section 0.1): an unpredicted purge may collapse the bus and latch State 99 if no component is damaged | No ride-through is designed; `ERR_FC_ONLY_COLLAPSE` latches with no bus re-close (policy E2). A ride-through policy (E3: FC_BUS LOW at the trigger and a bus-recovery deadline of about 40 ms) is recorded for a later ruling, not specified |
| Path | **IC1 is pursued**, which follows from OR-A as accepted on 2026-11-09; whether the charger replacement is also pursued is not ruled. Pursue IC1 (this document), the charger replacement (`docs/charger_replacement_evaluation_2026-11-05.md`, BQ25798EVM), or neither | IC1 keeps the Ag105 at about USD 115-210 for Stage 1 against USD 505-540 for the BQ25798 design (`facts_prior.md` section 11), but it does not meet ruling 1 (HR1 fails; HR2 in Run is limited to stops) |
| OR-A | **Accepted as proposed 2026-11-09.** Adopt IC1 revision 12 as staged, with Stage 0 plus Stage 1 as the first build and its end state until Stage-2 evidence exists | Stage 0 may start. No motherboard change before the Q_MD selection, Stage 0, the board gates and the further battle-test round on revision 12 with a buildability lens (section 0.3 item 1) |
| OR-O' | **Accepted as proposed 2026-11-09.** Replaces OR-O. FC windows parked in State 1 or 98 (variant P) and in State 2 at standstill (variant D-s, behind `IC1_FC_RUN_STANDSTILL` after gate W2b), each on an explicit EMS request; the dump check also runs in State 2 at standstill | Applies ruling (1) at drive-cycle stops: at most 1.9-31.9 mAh per cycle (Table 1a, upper bound); against EMS requests undetermined |
| OR-DM | **Accepted as proposed 2026-11-09.** Variant D (in motion) not adopted; re-evaluate after gates B8-1 and W1 and [DD] open items 40-41 | Gives up an in-motion increment of 1.2-1.8x D-s on the plant cycles, which rests on a traction allowance the size of the current-sense error. Adoption would need the fixed window split, a demand-budget exit keyed on the commanded current and a two-source purge gate at I_fc 1.0-1.25 A |
| OR-RQ | **Accepted as proposed 2026-11-09.** The explicit flag is adopted; the version-byte alternative is not. New in revision 11. The FC-window request is explicit: command byte 20 = 0xA5 with `charge_goal` above `CHG_GOAL_MIN`; a parked request carries `mode_cmd` 4. The Pi round is a Stage-1 prerequisite. Alternative: a command-protocol version byte (a 23-byte packet) | Without it, the deployed nodes, whose `charge_goal` is a regen latch, would open windows that the EMS never requested; with it they are refused (code 15) until the Pi round lands |
| OR-PK | **Accepted as proposed 2026-11-09.** Operating rule: a parked FC window on the H-20 is attended, and the Pi alerts the operator on any State 99 | Bounds the State-99 pack drain after a safe collapse (8-25 h to over-discharge, UNCONFIRMED). Alternatives: a confirmed pack PCM cut-off, or a low-power State 99 |
| OR-AC | **Decided 2026-11-09: option (d) for the first build** (section 0.4, answer 1). D_VC1 temperature endpoints (new in revision 8, restated in revision 12). The revision-8 windows (T_M16,max at most about 44-59 C at T_min -20 C, or 63-76 C at T_min 20 C) assume ideal saturation-current leakage. A real low-V_F Schottky leaks about 10 times that, so the 40 uA budget holds only to about 44 C even at T_min 25 C, and no passive part has been identified that meets both endpoints; the NSR0320MW2 fails the 0.25 V limit on its 25 C maximum row (`calc/ic1_rev12_calcs.py` section 8). Option (d) for the first build: a provisional part with a 25 C maximum V_F below 0.3 V at 16.2 mA (candidate NSR0320MW2), T_min 25 C, bench-attended Stage-1 sessions only, so that C-1, BG-17b, B-PKN at 25 C and B8-1 can run. After B8-1, choose (a) a TI written rating for VC1 injection below -0.3 V or (c) an active clamp (a new circuit and its own review round), unless B8-1 shows T_M16,max below about 44 C. Option (b), a wider leakage budget with matching BG-17b and `ERR_CELL_MISMATCH` limits, remains listed | With (d), Stage 1 can be built and gates C-1, BG-17b, B-PKN at 25 C and B8-1 can run; OR-AC no longer blocks a motherboard change. Until (a), (c) or a confirmed passive part replaces the provisional D_VC1 after B8-1, charging is limited to bench-attended Stage-1 sessions at 25 C or above. Feasibility of a passive clamp is UNCONFIRMED and, on present evidence, unlikely |
| OR-S | **Accepted as proposed 2026-11-09.** Accept return isolation as "battery isolated during charging" | Without it, only IC6 (fails HR1) meets the literal wording |
| OR-B | **Open** (two options without a recommendation; Stage 2 only). Relax HR1 from 23 W to the 18.9 W peak, or record HR1 as failed; set the V2-4 captured-charge fraction | Decides whether Stage 2 has a pass criterion |
| OR-E | **Accepted as proposed 2026-11-09.** Per-fault response: State 99 for the traction and isolation hazards (from revision 9 including `ERR_FC_ONLY_COLLAPSE`); window inhibit with a telemetry flag for the charge-subsystem health faults | Prevents health checks with TODO(calibrate) thresholds from halting a drive |
| OR-X | **Open** (no single proposed form: OV_BATT takes a charge-mode threshold or a compensation after S0-1 and the F_VX selection; UV_BATT takes an offset or a dwell exemption; needed before the Stage-1 firmware round). Charge-mode OV_BATT and UV_BATT limits | Reverses the fw v30 limits of CLAUDE.md section 6 inside windows |
| OR-H | **Accepted as proposed 2026-11-09.** Protocol v6 is adopted; the alternative of appending the IC1 fields to the R4 v5 round is not. Telemetry protocol v6 (the R4 v5 layout plus the IC1 fields), Pi bridge in lockstep | Protocol change; see section 5 |
| OR-G | **Accepted as proposed 2026-11-09.** The CSV, the bodge records and CLAUDE.md change in the firmware round. IO CSV amendment (pin 5 open-drain, pin 8 as `CHG_MOD_COLD_N`, changed meaning of rows 28, 30, 31, 32, pin 20 as the analog input `CELL1_V` since revision 7) and bodge records M1-M16 (M16 now includes the CBL2 replacement) | The CSV remains authoritative; firmware and CSV change together |
| Ruling 9 | **Accepted as proposed 2026-11-09: decided by S0-6 per the proposal.** R_KA keep-alive fitted or not, decided with S0-6 | Decides whether FC windows between purges deliver charge at all: every window starts the Ag105 cold, so with R_KA the parked rate is 1.17-1.19 A mean net pack current (1.18-1.20 A of charger output); without it a Bring-Up of 8.4-11.7 s per cold start leaves 0-0.19 A (`calc/ic1_rev9_calcs.py` section 2). Weighed against ruling 9's "last resort" status |

The remaining rulings were accepted as proposed on 2026-11-09, except where stated: OR-C (restatement of ruling 3),
OR-2' (a window ends on any traction request; the drive-law state is not changed during the 0 A hold, the stated
default), OR-4 (MPPTD released in every window, open-drain, written only by the mode manager), OR-5' (three one-time
commissioning writes; per-window writes only if S0-4 fails), OR-7 (regen and FC windows kept exclusive), OR-D (the
BQ29200 OUT tap is mandatory), OR-I (decided by S0-2 per the proposal: U_C2, U_IM and the eFuse are the sole current
bounds only if S0-2 fails), OR-K (MCU watchdog), OR-M (the FC profile stays at 1.25 A, the value on which the design is
specified; code 4 remains a recorded option subject to a bench efficiency gate), OR-T (full Stage 1, as recommended;
"Stage 1-lite" is not adopted), OR-V' (regen arm on the command step; the rate-conditioned arm is decided after the
fw v37 re-derivation, as the proposal states), OR-W (doctrine reversals, among them `FC_CHARGE_ALLOWED` 1 for standstill
FC windows), **OR-AA** (cell balancing falls from up to 15 mA to 0.5-1 mA because RB1A becomes 4.7 kOhm and D_VCB is
deleted, revision 7), **OR-AB** (the -8.4 V INA240 input exposure on an R_SH element open is accepted with a repair
rule; no input-protection round), **OR-Z** (the configuration check starts at the first Idle dwell after a self-test
pass, CC-B1; Stage 2 only), **OR-Y** (no regen window during the State-98 D/Y/W profiles, CC-B2) and **OR-VC**
(revision 9: the re-entry condition "V_chg below 11 V" takes the literal reading on two settled iterations, not the
1.0 s `ERR_VCHG_FED` blanking, which would cost 0.5-0.6 s per purge period). The following remain **open**, because
each offers two or more options without a recommendation or asks a question without a proposed answer: OR-F (whether a
re-specification round for the Stage-3 hold-up runs; Stage 3 was withdrawn in revision 7), OR-J (a sacrificial module
for S0-10, or acceptance of the mis-sequence residual; needed before S0-10), OR-L (retire or redefine
`AG105_VBATN_ISOLATED`) and OR-R (switch_state bits or the new status word); OR-L and OR-R are needed before the Stage-1
firmware round. OR-B and OR-X are open in Table 2.

Revision 12 also asked the operator to accept two residuals that [DD] records without a ruling ID (Appendix J, Table
J1); the operator accepted both on 2026-11-09 (answers 2 and 3 above). First, row F66: if the selected Q_MD has a
V_GS(th) range that covers 1.55-1.68 V, a double insulation failure (SHDN_EF and the CB-LB sleeve) can destroy Q_MD in
linear mode, at up to 4.0-5.1 W; this is the acceptance class of row F54c and of EF_FLT_N. The Q_MD selection still
records V_GS(th), the linear-mode SOA and V_GSS. Second, segregation is the only protection of the SHDN_EF, MD_G,
PROFILE, IMON, MS and EF_FLT_N leads and of the VC1 tap at both lead ends (BT8-DS-01, BT8-DS-02); no input clamps are
added, because a Schottky clamp brings back the rail injection and adds hot leakage to the U_MS and U_IM thresholds.

---

## 1. The design space

### 1.1 Brainstorm and clustering

The brainstorm produced 21 raw concepts ([STUDY] `brainstorm.md` Table 1). They were clustered along three axes that
change the safety argument: which pack leg moves, what breaks the circulating loop, and how the transition is
commanded. Nine cross-cutting findings (X1-X9) apply to every cluster. The most consequential are the following:

- **X2:** a blocked sense return is not an inhibit. With the sense return open and the Ag105 powered, the module reads
  zero battery current and ramps its output into whatever loads VBT carries, which is the ML0227 mechanism.
- **X3:** return-only concepts restore the sense but do not break the loop bus to charger to VBT to BT boost to bus;
  they need a hardware gate on the D-BT-EN enable in addition to switch rules.
- **X5:** a 2.5 A, 2S charge needs about 23.9 W of input, about 1.5 A at 16 V, above the 1.25 A governor and the
  1.247 A H-20 P_MAX. Every concept needs a lower charge current in FC windows.
- **X6:** a cold Ag105 (65-170 ms plus a 500 ms settle) misses the first regen pulse in every concept. A fast switch
  removes the switch from the critical path; it does not remove the charger limit.
- **X9:** no concept is acceptable without an MCU watchdog or an external watchdog that removes charger input power on
  a hung loop.

### 1.2 Concepts dropped at the brainstorm

Table 3 lists the four drops ([STUDY] `brainstorm.md` Table 3). A drop was recorded only for a concept that is
physically incapable on the facts or strictly dominated by a kept concept.

Table 3. Dropped concepts.

| Dropped item | Reason |
|---|---|
| DS-3, the whole board on the Ag105 VLoad output | Physically incapable: VLoad is rated 4 A continuous with no overcurrent protection (Ag105 DS p.19, p.20 row 6), which limits the BT channel to at most 1.85 A of bus current at 7.4 V, against a TPS61288 switch limit of 12 A minimum. Its interlock idea survives as a permit in IC4. |
| The HS-2 firmware-only regen alternative (BT_SEQ held HIGH, reg 0x02 threshold as the only barrier) | Violates HR3 between regen pulses and contradicts the IC3 hardware veto. |
| The T4/C3 VBUS-fed logic with a 4.4 mF hold-up | Strictly dominated inside IC6 by a pack-side LM1084 feed ahead of the relay, which does not depend on an FC-only bus that purges to about 1 V. |
| Concept A's uncommanded-hang behaviour (bypass held OFF with no watchdog) | Superseded inside IC1 by the T2 gate arrangement (S_GND pulled ON by default) plus the X9 watchdog. |

### 1.3 The seven kept concepts and the judges' ranking

Each kept concept was developed into a dossier and revised after one adversarial review round of three lenses (fault,
electrical, system). Three judges then scored the revised dossiers independently. Table 4 gives the concepts, the score
range of the three judges (out of 10) and the reason each concept lost. The scores are those recorded by the stage-1
judging; the reasons are taken from the post-review status section of each dossier.

Table 4. Kept concepts, judge scores and outcome.

| ID | Concept | Judge scores | Outcome and reason |
|---|---|---|---|
| IC1 | Commanded low-side return changeover: pack positive stays on VBT; PACK- moves between GND and VBat- | 7 / 6.5 / 7 (selected by all three) | **Selected.** It keeps the Teensy on the pack in every mode, makes the bonded mode the hardware default, transfers the return only on an explicit Teensy command, and admits Run-time regen windows. Its dossier states HR1 fails as specified and HR2 stays blocked at system level (`concept_IC1` section 0); the judges selected it as the best position, not as a requirement-meeting design. |
| IC2 | Autonomous direction-steered return (ideal-diode charge and bypass legs) | 5.5-6 | HR1 fails; only a warm variant (IC2-W) could improve it and that needs a ruling under ruling 3. HR2 closes with about 0.09 A of margin at a 1.5 A setting. The hardware grew to a splitter board, an interposer, three pin cuts and a mandatory eFuse (`concept_IC2` section 10). It survived as an FC-only, standstill-weighted design. |
| IC5 | Isolated DC-DC brick ahead of the Ag105, Vin- lifted; the pack never moves | 4.5-5 | Adds no switch at the battery terminals, so it does not answer the request literally. No mode meets HR1, HR2 and HR3 together: warm regen capture needs the Ag105 at CC through the whole of Run, because the brick removes the reg 0x02 threshold discriminator; Mode C fails HR3 by construction (`concept_IC5` section 0). |
| IC4 | Pack on the Ag105 battery port with a new high-current high-side switch (LM74800-Q1) and hardware permits | 3.5-4.5 | HR3 holds by topology against sensing faults. HR1 fails: the entry cannot beat the first VESC pulse and the code-4 ceiling is 14.3 W. HR2 holds only at standstill with purge prediction and a verified watchdog (`concept_IC4` section 10.3). |
| IC3 | Pack on the Ag105 battery port, D-BT-SQ promoted to the pack-to-board switch | 3-3.5 | HR1 fails structurally: the charger can never be warm while the pack feeds the bus. D-BT-SQ would carry the whole BT input current, about 7.6 A at the `OC_BT` limit, 95 % of its 8 A rating, with no thermal copper under its pad; gate G-T1 is a kill gate (`concept_IC3` section 10.2). |
| IC6 | Literal two-leg relay transfer to the Ag105 battery port, standstill only | 2-2.5 | The operator's literal request. Withdrawn as a requirement-meeting design: HR1 fails by construction (a hardware interlock forbids charging while the motor path is live), and the FC charge rate misses the H5 floor of 1.5 A at 8.4 V within the FC budget (`concept_IC6` section 0, section 10.6). Retained only as a fallback (IC6-R1) if ruling 1 is relaxed to FC charging only. |
| IC7 | Control: no isolation; external bounding (eFuse, loop breaker, OVP trip, watchdog) | Killed | Variant a cannot charge: with the sense shorted, every attempt is a Bring-Up ramp that ends at the eFuse trip, so HR1, HR2 and HR4 fail. Variant b's CV behaviour with a blind sense is UNCONFIRMED and it corrupts the BQ29200 bottom-cell reading (`concept_IC7` section 0). Retained as the source of the common safety layers (X4), which IC1 absorbed. |

No concept in the study meets HR1 as specified. The ranking therefore rewards the design that keeps the most
requirements open with the smallest structural penalty. IC1 keeps the pack on VBT (no Teensy brownout, no change to
pack buffering of the bus) and adds no series element in the BT power path. IC3, IC4 and IC6 forbid a powered charger
while the pack feeds the bus, so a Run-time regen window is structurally impossible in them. IC2 shares the IC1 topology
but replaces the explicit command by autonomous steering, at a larger hardware count. IC5 does not isolate the pack.

---

## 2. The selected design: IC1 revision 12

### 2.1 Topology

[DD] is the build-level document; it gives the netlist, ASCII schematics, component table with primaries, logic
equations, timing budget, mode table, fail-safe table and single-fault table (rows F1-F66; rows F57-F65 cover the
purge package of revisions 9-11, and row F66 the MD_G-SHDN_EF short of revision 12). This section summarises it. The
electrical hardware is that of revision 8: revisions 9-12 add no circuit, and revision 12 adds one harness routing rule.

IC1 adds three assemblies and a reworked balance network to the manufactured board ([DD] section 4.1 Table 3):

- **SB, the pack switch board,** in the pack harness between a keyed pack connector and J-BT. It carries two parallel
  bonding MOSFETs S_GND1/S_GND2 (PACK- to PCB GND), the charge-leg MOSFET S_CHG (PACK- to the Ag105 VBat- lead
  VBATN_X), the pack shunt R_SH with fused Kelvin leads, and the gate drive. SB reaches PCB GND only through two return
  leads; no ground conductor runs in the signal bundle.
- **The pack fuse F_PK (20 A)** at the pack terminal, upstream of every SB conductor.
- **LB, the logic board,** on PCB GND. It carries the permit latch FF1, the pumped arm, two independent INA240A3
  pack-current channels with trip comparators U_C1 (discharge, forces the bonded mode) and U_C2 (charge, removes the
  charger input), the eFuse-input comparator U_IM, the module-node comparator U_MS, the D-BT-SQ cross-lock, the BT_BUS
  clamp Q_X1, the BT-loop detector D5, two 5-bit R-2R status ladders, the receiving half of the VC1 tap and, in Stage 2
  only, the two VOK channels. The low-voltage flying signal leads run in segregated sleeves that carry no conductor
  above 3.6 V, and from revision 12 SHDN_EF runs in a sleeve of its own. The LB-entry series resistors of revision 8
  (R_VC1c, R_MS3, R_BL3, R_PGL) limit only the current on the LB side; they protect neither an unclamped input nor the
  CB-end pin of the same lead, so segregation is the protection against a chafed lead (revision 12, BT8-DS-01,
  BT8-DS-02).
- **CB, the charger adapter,** at the Ag105. It carries the TPS26631 eFuse (TPS26636 approved alternate) in the cut
  Ag105 pin 10, the Teensy-switched resistor networks that select the charge profile (1.75 A / 18 V regen, 1.25 A /
  13.8 V FC) in Ag105 resistor mode, the LD tie, the fast fuse F_VX (4 A) in VBATN_X, and the module-node dump Q_MD/R_MD
  (gate resistor R_MDS) with the bleed R_MB.
- **The balance-network rework (M16)** at the BQ29200: the clamp D_VC1 behind RB3, RB1A raised from 100 Ohm to
  4.7 kOhm, and a 200 kOhm VC1 tap resistor that feeds Teensy pin 20, on which `ERR_CELL_MISMATCH` compares the two cell
  voltages independently of the BQ29200. Revision 7 deleted the second clamp D_VCB, because its short let the balancer's
  top-cell switch pull the BQ29200 VDD to ground (FM4-1).

The motherboard modifications are M1-M16 ([DD] section 5.5 Table 6). Four are made inside the Ag105 outline: M1 cuts
VBat- pins 14/15, M2 cuts Vin+ pin 10, and M9 and M10 wire the LD, CSEL and MPPTSEL pads. The others cut the D-BT-SQ,
D-BT-EN and (Stage 2) D-BC-RG enable traces, add a fly-wire to the BQ29200 OUT pin (mandatory), remove J-BL position 3
(the second pack-negative bond), add a soldered second return lead, and tap ten spare Teensy pins, pin 8 and several
existing nets at the J1/J2 receptacles (M6).
Each modification is a hardware bodge record (ruling OR-G).

### 2.2 Operating principle

Table 5 summarises the modes ([DD] section 9.1 Table 12).

Table 5. Mode summary.

| Mode | FF1 | PACK- | D-BT-SQ | Charger input | Ag105 |
|---|---|---|---|---|---|
| Unpowered, reset, hung, boot | clear | GND (bonded) | off | off | unpowered |
| Idle, Run traction, Finish | clear | GND (bonded) | off (cross-lock) | off; a fed input latches `ERR_VCHG_FED` | unpowered |
| FC window (State 1 or 98; State 2 at standstill), between predicted purges | set | VBat- (charge mode) | on after about 13 ms | eFuse on, BT_BUS held open by Q_X1; MDAC split fixed at r 0.85, code 717 (revisions 11, 12) | FC profile 1.25 A, cold start per window |
| Regen window (Stage 2, State 2) | set | VBat- | on | eFuse and D-BC-RG on only while VOK (V-MOT above VBUS by a margin) | regen profile 1.75 A, cold start per pulse |
| State 99 | clear | GND | off | off | unpowered |

Every commanded exit drops the charger feed, waits until U_MS reads the module input node cold (measured drain; the
deadline is the later of 10 ms and 4 loop iterations, capped at 30 ms, revision 7), and only then re-bonds. The module therefore stops converting with its sense still in the return path. A traction
request inside a window resumes torque after 4.7-6.3 ms at the median loop and 5.3-6.9 ms at the p99 loop
(`calc/ic1_rev6_calcs.py` section 9). The Ag105 is configured once at commissioning (three EPROM writes with pin 32 LOW);
runtime EPROM writes fall to zero.

Section 2.4 gives the FC-window sequence around an H-20 purge.

### 2.3 Staging

The design is staged ([DD] section 14):

- **Stage 0** is a bench rig around two spare Ag105 modules (a stress unit X and a qualification unit Q) that
  reproduces the vehicle charge-mode topology. It needs no board change and measures every Ag105 unknown.
- **Stage 1** is standstill charge isolation: SB, CB and LB without the VOK channels and without the D-BC-RG cut. A
  bench supply on J-FC serves commissioning, gate C-2b and the first windows (W1). Stage 1 then delivers FC charging
  from the H-20 between predicted purges, parked (variant P, gates W2a, W2 and W2c) and, behind
  `IC1_FC_RUN_STANDSTILL`, in State 2 at standstill (variant D-s, gate W2b), with the pack return isolated. It meets the
  operator's literal goal and is the recommended first build and end state.
- **Stage 2** is Run-time regen: the VOK channels, the D-BC-RG cut and `IC1_STAGE` 2. It is held until S0-6 shows a cold
  start inside the per-family allowance and V2-4 shows captured charge.
- **Stage 3**, an optional hold-up capacitor (C_HU) on the eFuse output, is **withdrawn** in revision 7: its dump keyed
  to FF1./Q deadlocked every commanded exit into `ERR_MOD_DRAIN` and then `ERR_MOD_FED` (State 99) (BT4-TR-01,
  `calc/verify_stage3_exit_drain.py`). [DD] section 14.4 lists the conditions of a re-specification, which ruling OR-F
  decides. With Stage 3 withdrawn, HR1 has no remaining hardware lever on the fast-decel pulse family.

### 2.4 FC windows between purges

The order of the pre-purge sequence is fixed by the isolation ([DD] section 9.11.1). In an FC window the clamp Q_X1
holds BT_BUS open, because in the charge mode the BT boost would draw from the pack through the Ag105 sense in reverse
and recreate the loop bus, charger, pack, BT boost, bus. The share shift toward the battery that ruling (1) asks for
therefore cannot start inside a window. On a timely prediction the mode manager runs the following steps ([DD] section
9.11.3, Table 21):

1. Drop the charger feed (FC_CHARGE LOW) at 1.13-1.34 ms after the prediction.
2. Wait until U_MS reads the module input node cold (0.83-2.01 ms after the drop; `ERR_MOD_DRAIN` at the deadline).
3. Bond the pack (pin 33 LOW; both S_GND on at 3.84-12.89 ms).
4. After the bonded confirmation, write BT_BUS HIGH through the guarded path (5.81-15.27 ms); D-BT-EN conducts after
   t_D_ON plus its 19.77 ms soft-start, at 33.6-34.7 ms typical and 47.0 ms worst healthy.
5. In P and D-s, the BT_BUS re-close is the whole share shift: the share loop does not run in State 1 or 98 and freezes
   or holds its split below the 0.25 A gate in State 2. Restore the pre-session MDAC split after the BT_BUS write.
6. After the declared end of the purge, re-enter the window once V_fc reads at or above 7.0 V and V_chg reads below
   11 V, each on two settled iterations, and the purge permit holds (time to the next onset at or above 1.282 s); the
   Ag105 starts cold (65-170 ms with R_KA).

A chain that misses a deadline ends in a defined state: a failed bonded confirmation latches `ERR_CHG_EXIT` and enters
State 99 without a BT_BUS re-close. From the BT_BUS write of a prediction exit until the declared purge end, the
V_bus reading of `ERR_FC_ONLY_COLLAPSE` stays armed, so a BT_BUS that never conducts (row F63) latches before the FC
recovers in all cases of the fault sweep except one at 11.74 V, which is the class that Table 23 of [DD] already accepts.
The bus does not need the share shift to survive the purge: in 172 recorded purges with both bus switches closed,
V_bus stayed at 15.29-15.93 V at a pre-purge I_fc of up to 0.712 A (`calc/purge_seq_bags_output.txt` section 5); in P
and D-s the feed drop leaves the FC with the auxiliary load only at the onset.

The window then charges at a fixed MDAC split (r = 0.85 at k_d = `K_DROOP`, revision 11; MDAC code 717 as computed
through `setDroopMdac()`, revision 12, `calc/ic1_rev12_calcs.py` section 4). The FC-only bus sits at
15.52-15.82 V, 1.70-1.98 V above the 13.82 V FC-profile threshold, and the module input power is fully deliverable on
both the design-chain and the bench-scaled droop resistance; at the closed-loop clamp split of revision 10 the
design-chain droop would have given 13.50-13.99 V and 65-100 % (`calc/ic1_rev11_calcs.py` section 2). The in-window
droop resistance is TODO(calibrate) at W1 ([DD] open item 41).

A window request is explicit (ruling OR-RQ): command byte 20 equal to 0xA5 together with `charge_goal` above
`CHG_GOAL_MIN`; a parked request also carries `mode_cmd` 4, because any `mode_cmd` 0-3 packet in State 1 starts Run
(ino:7533-7535). Every purge prediction closes the window whatever the request, and the window re-opens after the purge
while the request stands. Telemetry protocol v6 carries an 8-bit refusal code (codes 0-15, [DD] Table 25).

---

## 3. Battle-test record

### 3.1 Rounds and finding counts

The detailed design passed through eight battle-test rounds. Rounds 1-3 applied seven lenses: FMEA (exhaustive
component-by-mode enumeration), transient, logic and sequencing, datasheet, Ag105 behaviour, buildability and
measurement, and requirements and operability. Rounds 4 and 5 applied five of them: FMEA, logic, transient, datasheet
and buildability; the Ag105-behaviour and requirements lenses were not run. Revision 9 was not a battle-test round: it
applied the operator rulings of 2026-11-08 ([DD] Appendix G). Rounds 6 and 7 applied four lenses (FMEA, logic,
transient and requirements) to the purge package of revisions 9 and 10 only, under the rulings: the predictor was not
attacked, and a bare collapse to State 99 was not a finding. Round 8 applied five lenses (FMEA, logic, datasheet,
transient and requirements) to revision 11 as a whole design, aimed at the revision-8 hardware that no earlier round had
attacked and at the revision 9-11 rules, under the same rulings. Every blocker and major finding was verified
independently against the primaries, with recomputed bounds. Table 6 gives the counts at verified severity
(`calc/feasibility_battletest_tally.py`, output `calc/feasibility_battletest_tally_output.txt`; cross-checked against
[DD] Appendices B-F and H-J).

Table 6. Battle-test finding counts (verified severity).

| Round | Design under test | Lenses | Blocker | Major | Minor | Total | Refuted | Blocker or major from the preceding fixes |
|---|---|---|---|---|---|---|---|---|
| 1 | Revision 3 | 7 | 1 | 20 | 41 | 62 | 0 | - |
| 2 | Revision 4 | 7 | 1 | 16 | 25 | 42 | 0 | the blocker |
| 3 | Revision 5 | 7 | 2 | 12 | 11 | 25 | 0 | both blockers |
| 4 | Revision 6 | 5 | 0 | 9 | 20 | 29 | 0 | 7 of 9 |
| 5 | Revision 7 | 5 | 0 | 8 | 14 | 22 | 0 | 7 of 8 |
| 6 | Revision 9, purge package | 4 | 0 | 3 | 10 | 13 | 0 | 2 of 3 (introduced by revision 9) |
| 7 | Revision 10, purge package | 4 | 0 | 3 | 5 | 8 | 0 | 0 of 3 attributed; all 3 lie in revision-9 content |
| 8 | Revision 11, whole design (aimed at the revision-8 hardware and the revision 9-11 rules) | 5 | 0 | 3 | 11 | 14 | 0 | 2 of 3 (this document's reading) |
| Total | | | 4 | 74 | 137 | 215 | 0 | |

The last column counts the findings that the adjudication appendix attributes to the preceding revision's own fixes;
for rounds 2 and 3 only the blockers were attributed. For round 7, [DD] Appendix I attributes no major to the
revision-10 fixes; the three majors concern the D-s reachability (revision-9 content combined with the revision-8 dump
check) and the meaning of `charge_goal` (revision-9 content), which is this document's reading of [DD] Table 0f.
For round 8, [DD] Appendix J makes no attribution statement. This document reads BT8-FM-01 as a defect of the
revision-8 sleeve rule R8-3 (the fix of FM5-2) and BT8-LS-01 as a defect that arises where the self-test "deferred"
rule meets the revision-11 parked request form R11-2 (the fix of BT7-REQ-01); [DD] does not state when the 16 V J-FC
setpoint of BT8-REQ-01 was introduced, so it is not counted. Six of the 14 round-8 findings, of any severity, lie in
revision-8 hardware or ruling content, and the verifiers lowered five findings from major to minor.
Several lenses filed the same defect: the 9 round-4 majors are 8 distinct defects, the 8 round-5 majors are 5 distinct
defects, the 3 round-7 majors are 2 distinct defects (FM7-1 and BT7-LS-01 are one), and the 3 round-8 majors are 3
distinct defects.

The trend is mixed. The blocker-plus-major count fell from 21 to 17, 14, 9 and 8 over rounds 1-5, and rounds 4 and 5
found no blocker. However, the total rose by 16 % in round 4 before it fell by 24 % in round 5, and rounds 4 and 5 ran
two fewer lenses, so their counts are not directly comparable with rounds 1-3. Rounds 6 and 7 found 3 majors each, but
they attacked only the purge package, so their counts are not comparable with rounds 1-5 either. Round 8 widened the
scope again to the whole design; its total rose by 75 % over round 7, and it also found 3 majors. The blocker-plus-major
count has therefore stood at 3 for three rounds, with the scope widening in the third. No round has yet returned zero
majors, and in each of rounds 4-8 at least two thirds of the majors were defects in content that a preceding revision had
added (rounds 7 and 8 on this document's reading). No finding was refuted in full in any round.
After round 3 a completeness critic found 33 gaps; 18 were closed in [DD] at once (CC-1 to CC-18). Of the 15 left open
(CC-B1 to CC-B15), revision 7 closed seven and turned two into rulings, revision 8 closed one, and five remain open
(section 7.2).

### 3.2 What changed in each round

Round 1 (revision 3 to 4) found the architecture sound but its implementation unfinished. The blocker FM-1 was that the
Kelvin leads were unfused pack-negative conductors in a signal cable; fusible 2.2 Ohm resistors were added. The majors
covered four themes:

- the status-ladder RC (tau 2 ms) could not meet 1-2 ms confirmation windows, so every window entry would false-trip;
  tau fell to 20 us;
- with pin 33 high-Z, FF1 sat in the undefined logic band, so a reset did not clear it; pin 33 was buffered;
- one capacitor or fuse removed the gate supply of both S_GND channels, and the VOK detector failed toward OK on a
  VBUS-side open; the supplies and taps were split per channel;
- the design reused the ML0227-overstressed Ag105 with no qualification and the Stage-0 rig omitted the vehicle
  topology; gate D-3 and a vehicle-topology rig were added.

Round 2 (revision 4 to 5) found that the revision-4 fuse move left SB pack-positive copper unfused (blocker FM2-1); F_PK
moved to the pack terminal. The majors included a State-99 code skip that would have disabled the boosts under closed
bus switches, an FC window still reachable in Run cruise, an eFuse that runs in thermal regulation for up to 2.9 s with
FLT not asserted on a start into overload (new comparator U_IM), and a shared Kelvin pair that blinds both current
channels (new fault `ERR_IPACK_PLAUS`). A D-BC-FC power-stage short was shown to be a one-fault loop path, closed only
by the new `ERR_VCHG_FED`.

Round 3 (revision 5 to 6) found that the revision-5 balance-lead clamp D_VM was an unfused short of cell 1 (blockers
FM3-1 and BT3-BM-01, 34-71 A); D_VM was replaced by two clamps at the BQ29200 pins behind the existing resistors (at most
58 mA). The majors included an unfused VBATN_X chafe path (17-164 A through the module sense; fuse F_VX added), a
module that stays powered from its input capacitance after an eFuse cut (dump and comparator U_MS added), an eFuse-bypass
probe that was structurally blind because the Ag105 reports 0xFF in the probe state (probe re-based on U_MS), a U_IM
trip that could exceed the eFuse I_OL minimum (R_ILIM 8.06 kOhm), and `chargingControl()` left as a second writer of
pins 5 and 30 (chokepoint setters).

Round 4 (revision 6 to 7) attacked the revision-6 additions and found majors in most of them ([DD] Appendix E):

- a short of the new clamp D_VCB drained cell 1 undetected and let the balancer's top-cell switch pull the BQ29200 VDD
  to ground (FM4-1); D_VCB was deleted and RB1A raised to 4.7 kOhm, which cuts cell balancing to 0.5-1 mA (ruling
  OR-AA);
- a short or reversed D_VC1 put the pack voltage across the BQ29200 VC2-VC1 pins, rated 8 V absolute maximum
  (BT4-DS-02); a VC1 tap on Teensy pin 20 with `ERR_CELL_MISMATCH` was added, and WDOG1_B gave up pin 20;
- a dump FET Q_MD stuck on escaped U_IM and `OC_FC` and overloaded R_MD, latent in regen windows (FM4-3, BT4-1), and
  the planned U_MS threshold test overloaded R_MD (BT4-3); a new FC-current-step fault `ERR_MOD_DUMP_ON` was added;
- the Stage-3 re-key of Q_MD deadlocked every commanded exit into State 99 (BT4-TR-01); Stage 3 was withdrawn;
- two firmware rules false-latched on healthy boards: the Idle-entry self-test inside a regen tail (BT4-LS-01) and the
  `ERR_MOD_SENSE` (b) anchor from the second regen pulse on (BT4-LS-02);
- an open R_SH element drove KS+ to about -8.4 V, beyond the INA240 -6 V absolute maximum (BT4-TR-02); the exposure is
  stated, `ERR_IPACK_PLAUS` gained a two-sided band and a repair rule was added (ruling OR-AB).

Round 5 (revision 7 to 8) attacked the revision-7 fixes and again found majors in them ([DD] Appendix F):

- the new exit hold check `ERR_MOD_SENSE` (c) false-latched on healthy regen exits taken between VOK pulses and on the
  probe feed drop (FM5-1, BT5-LS-01, BT5-TR-01); it now runs only on a fresh same-iteration read with EF_EN H, pin 8 HIGH
  for at least 2 ms and V_chg at or above 13.5 V;
- the new `ERR_MOD_DUMP_ON` sample false-latched every FC window when the Ag105 starts fast (BT5-LS-02); it now runs
  only in sessions with pin 32 LOW, in a new per-power-cycle dump check that precedes every window;
- the new VC1 tap lead landed on pin 20 with no LB-side series element, so a chafe onto a positive conductor put the
  full voltage on the MCU pin and the 3V3 rail (FM5-2, BT5-BO-02); four LB-entry series resistors and two segregated
  sleeves were added;
- the revision-7 D_VC1 specification was physically unsatisfiable, because the cold forward-voltage limit forces hot
  leakage above the 40 uA budget (BT5-DS-01); the conflict is now stated and handed to ruling OR-AC;
- the rewritten gate C-2a item 5 injected the BQ29200 overstress with no pack-voltage limit (BT5-BO-03); it now runs
  at 7.4 V and injects the short at the tap junction on LB.

Round 6 (revision 9 to 10) attacked the purge package and found three majors, two of them introduced by revision 9
itself ([DD] Appendix H):

- the predictor-interface sentence that let an UNKNOWN close an open session "as a prediction does" re-entered the
  rejected exit policy E1 on an unpredicted purge (BT_BUS written after the onset in 886 of 2430 grid cases, 15
  HAZARD cases; BT6-LS-01); an UNKNOWN transition, `purge_active` rising or a late prediction inside a BT-open session
  now latches `ERR_FC_ONLY_COLLAPSE`, and the grid gives OPEN in 4860 of 4860 cases (`calc/ic1_rev10_calcs.py`
  section 5);
- the State-2 standstill window left the share latch able to cut FC_BUS during entry steps 1-4, so step 5 dropped
  BT_BUS onto a bus with no source and tripped State 99 on a healthy board (BT6-LS-02); the mode manager now owns pins
  27 and 28 from the first entry write until BT_BUS has conducted after the exit;
- the share override that set a 290 ms lead time for D-s moves no MDAC code at a standstill load (BT6-TR-01); in P
  and D-s the BT_BUS re-close is now the whole shift, and one lead time of 80 ms applies to every FC window.

The round-6 minors added the V_bus reading of `ERR_FC_ONLY_COLLAPSE` through the purge interval (row F63), the
traction hold until BT_BUS conducts, the 7.4 V window-entry floor and the State-99 drain warning with ruling OR-PK.

Round 7 (revision 10 to 11) found three majors (two distinct defects) and five minors ([DD] Appendix I):

- every D-s window needed a dump-check pass that only State 1 or 98 could produce, so D-s delivered 0 s on every
  recorded session (FM7-1, BT7-LS-01); the dump check now also runs in State 2 at standstill at the first request of a
  power cycle;
- the deployed Pi nodes use `charge_goal` as their regen gate, so revision 10 would have opened FC windows that the
  EMS never requested (BT7-REQ-01); the request is now explicit (ruling OR-RQ), and the revision-10 figure of D-s
  "against the recorded requests" (107.3 s of 446.6 s) is withdrawn as an HR2 value (BT7-REQ-02);
- among the minors, the closed-loop share split drooped the FC-only window bus to 13.50-13.99 V on the design chain,
  near the 13.82 V module threshold (BT7-TR-01), so the MDAC split is now fixed inside every window; and the late
  threshold rested on a loop gap measured only on a State-98 build without Ethernet (FM7-2), which is now a W1 and W2b
  criterion.

Round 8 (revision 11 to 12) found three majors and eleven minors ([DD] Appendix J):

- an MD_G-SHDN_EF short inside the revision-8 CB-LB sleeve joined two LVC outputs of opposite level through equal
  1 kOhm resistors and held the eFuse SHDN pin and the Q_MD gate at 1.55-1.68 V in both EF_EN states, where the eFuse
  state is unspecified and Q_MD can dissipate up to 4.0-5.1 W in linear mode (BT8-FM-01); SHDN_EF now runs in a sleeve
  of its own, gates C-1 and C-4 add lead-to-lead insulation tests, C-2b item (h) injects the short, and the Q_MD
  selection must record its V_GS(th) range, SOA and V_GSS;
- a standing parked request aborted the Idle-entry self-test, and the deferred result then refused every P window of
  that Idle with no later Idle entry able to pass; a Run command within 357.7-457.5 ms of the boot Idle entry refused
  every D-s window of that Run (BT8-LS-01); a window request now waits for the self-test (at most 457.5 ms), and a
  deferred result refuses windows with the new code 16 until a re-run passes;
- the 16 V J-FC commissioning setpoint put 4.28 V on Teensy pin 24 against its 3.6 V absolute maximum and held the FC
  boost out of regulation, and the later bench-supply gates named no setting (BT8-REQ-01); every bench-supply session
  now runs at 12.0 V with a 1.5 A or 2.0 A limit, under a WARNING against more than 12.3 V.

Among the minors, the verifiers lowered five datasheet and requirements findings from major. Their substance is that
the revision-8 LB-entry resistors protect no unclamped input and no CB-end pin (the protection is segregation), that
the pin-20 pad leakage limit in the primary is 12.7 times the `ERR_CELL_MISMATCH` allowance, that D_VC1 is not
buildable from stock, and that gate B8 could not run before D_VC1 was fitted (OR-AC option (d), B8 split). The other
minors corrected the dump-check retry, the C_DV inrush rule, the fixed-split MDAC code (717, not 718), the R_BL2 range,
the W1 duration and gate order, and the HR2 parked figure (net pack current).

Three patterns in the record bear on confidence. First, every round from round 2 on found its blockers or most of its
majors in the preceding round's fixes: FM2-1 in the revision-4 fuse move, FM3-1 in the revision-5 clamp, D_VCB, the
dump, the Stage-3 re-key and two firmware anchors in round 4, the exit hold check, the dump sample, the VC1 tap and
the D_VC1 specification in round 5, and the revision-8 sleeve and the revision-11 parked request form in round 8.
Second, the eFuse-bypass detector was redesigned in rounds 1-3 (an I2C ACK test, then reg 0x07, then the module-node comparator), and the module-node supervision then needed corrections in rounds 4
and 5. Third, revisions 7 and 8 deliberately preferred firmware rules, gate rewrites, value changes and deletions to new
circuitry; the severity fell from blockers to majors under that policy, but the majors did not reach zero. Revisions
9-11 continued that policy for the purge package (no circuit added), and rounds 6 and 7 still found majors in it: mostly
availability defects (a healthy-board State 99, a window that never opens, a window the EMS did not request) and one
safety defect on the unpredicted-purge path (BT6-LS-01). Round 8, the first attack on the revision-8 hardware, found one
damage-class defect in it (BT8-FM-01) and showed that two revision-8 protections (the LB-entry resistors as input
protection, a buildable D_VC1) did not hold as stated; revision 12 answers them with a routing rule, a restated basis
and a ruling option rather than new circuitry. Revision 12 has not been reviewed; a further round is therefore
recommended (section 0.3 item 1).

### 3.3 What survived

The architecture of revision 3 survived all eight rounds without a structural change: the commanded changeover with a
bonded default, the eFuse charger gate enabled only by FF1 AND the pumped arm AND a source term, the two independent
pack-current channels, the resistor-mode Ag105 profiles, and the three-assembly partition with no ground conductor in
the pack-side signal bundle. The peripheral circuits did change: the balance-lead clamp moved twice (D_VM, then
D_VC1/D_VCB, then D_VC1 alone), WDOG1_B and the Stage-3 hold-up were removed, and the module-node dump gained its own
check, and from revision 12 SHDN_EF runs in a sleeve of its own. HR1 failed at the start of round 1 and remains
so. HR2 was blocked through round 5; the operator rulings of 2026-11-08,
not a battle-test result, changed it to met by sequence calculation, and rounds 6-8 narrowed its bases without
refuting it. HR3, HR4 and HR5 gained conditions and bench gates but were never refuted. The purge package added no
circuit: its safety rests on the existing Q_X1 clamp, the commanded exit and one new fault, `ERR_FC_ONLY_COLLAPSE`. The withdrawal of Stage 3 removes the last hardware
lever for HR1 on the fast-decel pulses; the VESC-stop tail is now the only identified capture interval, and it is BENCH.

---

## 4. Staged bench plan and go/no-go gates

### 4.1 Order of work

The gates run in the order below; a NO-GO stops the stage and names the fallback ([DD] section 15). No gate has been
executed. Two warnings apply to every gate. Do not connect an earth-referenced instrument, supply or charger to pack(-),
the Kelvin leads, PACK-, VBATN_X or an SB node while the pack is installed, or the earth path bypasses the Ag105 sense.
Connect the pack connector before the balance plug and disconnect the balance plug first, or the BQ29200 inputs become
the board return.

### 4.2 Stage 0 (bench rig, spare modules, no board change)

Table 7 lists the decisive Stage-0 gates. The full set (S0-1 to S0-14) is in [DD] section 15.1.

Table 7. Decisive Stage-0 gates.

| Gate | Question | GO | NO-GO consequence |
|---|---|---|---|
| S0-1 | Ag105 sense resistance R_s; S_CHG body-diode drop | Values recorded (inputs to OV_BATT, the BQ29200 margin and the return checks) | - |
| S0-12, S0-12b | eFuse latch-off and per-unit U_IM trim at 25 C and hot soak, including a start into overload at the regen cadence | U_IM trip below the unit's I_OL minus 0.05 A at every temperature; U_IM clears FF1 within 5 ms | No charge session until it passes; choose another eFuse |
| S0-2 | Does the restored sense regulate the pack current in every reachable sub-state? A sense-bypassed positive control must be flagged first | Pack current at or below I_set + 0.2 A at every start; steady agreement with an external shunt within max(0.05 A, 10 %) | The Ag105 regulation layer is not credited; U_C2, U_IM and the eFuse are the sole current bounds (OR-I, accepted 2026-11-09) |
| S0-6 | Cold start from eFuse enable to 63 % of I_set, both profiles, with and without R_KA | HR1 GO per pulse family only if the window-open latency plus the hardware chain plus the cold start fit before V-MOT reaches 21.35 V (at most 5.3 ms on the 19 ms pulse, 26.4 ms on the 47 ms pulse); HR2 GO at about 1 s or less | HR1: no Stage-2 capture for that family (Stage 3 is withdrawn); HR2: FC windows have little value |
| S0-11 | Module input capacitance, eFuse inrush, dumped and undumped drain times | Inrush at most 0.6 A; dumped node below 9 V within 3 ms; C_mod between 47 and 221 uF (the lower bound keeps the exit hold check's 150 us sample valid, revision 8); above 103.6 uF, C_DV at least 10 nF x C_mod / 103.6 uF (revision 12) | Re-size C_DV, R_MD and R_MB; below 47 uF, measure the hold at C-2b (g) and drop the 150 us sample if the hold is under 200 us; a raised C_DV moves the `ERR_MOD_DUMP_ON` sample to the measured ramp plus 2 ms ([DD] open item 46) |
| S0-14 | Does the module-node probe detect a deliberate eFuse bypass? | The probe latches in every injected case and passes without the injection | No Stage 2 |
| S0-7, S0-8b | Back-powering through MPPTD and I2C; released MPPTD reads enabled; power-up near full charge | Recorded | Pin 5 push-pull through 10 kOhm; if Fully Charged is reported above 8.0 V, IC1 charges only to about 8.0 V at rest |

Before Stage-2 firmware is written, Stage 0 also records a fw v37 decel BLG with a target steeper than coast-down, to
re-derive the regen-arm latency under the flashed drive law.

### 4.3 Pre-rework gates and Stage 1

The board gates decide whether the board can take the modifications ([DD] section 15.2). Before any rework: D-1 (damage
checks after ML0227), D-2 (Ag105 standoff and cut gap; NO-GO falls back to a module carrier), B2 (bodge pull-down
positions), BG-17a (BQ29200 OUT reachable, its drive level, the CD delay and the open-wire fail-safe; NO-GO means no
charging), B13, P8 (the pin-8 net: no 5 V path, no encoder chain continuity, no transitions while the wheel turns;
the fallback pin 2 shares the same encoder history) and JBL (J-BL position-3 screw removable). After the modifications:
P-M1 (4-wire resistance after the pin cut), D-3 (vehicle Ag105 qualification, after the last heated modification;
NO-GO replaces the module; a later reverse sense current above 3.5 A voids D-3(a)) and BG-17b (the cell-1 trip with D_VC1
and RB1A 4.7 kOhm fitted, at 25 C and hot soak, and OUT with pin 9 in either state; repeated after any F34b or F47 event).

The Stage-1 assembly and commissioning gates follow ([DD] section 15.3): C-1 (harness audit, clamp orientation, VBATN_X
and signal-sleeve insulation, lead-to-lead insulation inside the CB-LB sleeve and of SHDN_EF against it from revision
12, VC1 to GND resistance in both polarities), B-FPK and B-PKN (fuse and pack-negative opens; B-PKN on the vehicle board
with RB1A.2 lifted, and with a NO-GO clause for a provisional D_VC1; ahead of C-2b from revision 12), C-1b and C-1c
(no earth or pack-internal path parallel to the sense), C-1d (pad joints), C-2a (charger unpowered: mode toggles, ladder calibration, every forced fault,
the pin-25 calibration and the cell-mismatch injection at a 7.4 V pack, the non-boost load constant I_NB,cal; one GO per
sub-item), C-2b (fed, after commissioning: injected eFuse bypass, stuck dump, exit hold check and, from revision 12,
item (h), the MD_G-SHDN_EF short injected from J-FC at 12.0 V with a 0.5 A limit for at most 1 s), B10 and B11-B11e (clamp
strength, hang, watchdog, warm reset, slow and partial 3V3 loss), ST (self-test fault injection), T1 and T2 (trip
thresholds with real current), C-3 (eFuse turn-on in an FC window, at the largest fitted C_mod, with FC_CURRENT below
1.3 A), W0 (BQ29200 reading at CV entry), W1 (first FC window from a bench supply, two 30 s windows, 1.25 A +/- 10 %),
B8-1 (the VBT load I_L and T_M16,max in an FC window after W1, followed by the re-verification or replacement of D_VC1
and repeats of the C-1 D_VC1 items, BG-17b and B-PKN) and C-4 (inspection after the first drive, with the lead-to-lead
insulation test). From revision 12 every bench-supply session on J-FC runs at 12.0 V, with a 1.5 A limit for
commissioning and a 2.0 A limit thereafter.

**WARNING:** Do not set the bench supply on J-FC above 12.3 V. Teensy pin 24 reaches its 3.6 V absolute maximum at
13.46 V, and above the 15.95 V bus target the FC boost cannot regulate ([DD] section 9.2, `calc/ic1_rev12_calcs.py`
section 2).

Commissioning from the bench supply ends with W1 and then B8-1, which revision 12 places after W1 so that the
provisional D_VC1 is re-verified or replaced before the H-20 gates.

From revision 9 the FC windows between purges rewrite W2, add W2a-W2e and tighten W1 ([DD] section 15.3). Table 7a
lists them.
They need the predictor in service (ruling OR-P) except W1 and W2c, which run from a bench supply on J-FC.

Table 7a. FC-window gates between purges (revisions 9-12).

| Gate | Question | GO | NO-GO consequence |
|---|---|---|---|
| W1 (R11 and R12 criteria) | First FC window from a bench supply on J-FC at 12.0 V with a 2.0 A limit, two 30 s windows separated by `FC_CHG_COOLDOWN_MS`, requested from the State-98 window-request key, on the production build | Pack current 1.25 A +/- 10 %; I_PACK1 within 10 % of reg 0x06; MDAC codes equal to the fixed split through the window; in-window V_chg at or above the measured S0-4 threshold + 0.3 V and at or above 14.0 V; maximum loop iteration at or below 15 ms | Stop. On the iteration criterion, raise T_lead,min and T_late by the excess over 19.0 ms (a predictor requirement change); on V_chg, measure the droop block before W2 |
| W2a | BT_BUS and FC_BUS re-closed onto the live bus 20 times each, the FC carrying the auxiliary load | Conduction onset at or below 31.8 ms every time | Raise T_lead,min, T_late, T_lead,nom and the traction-release bound by the excess (a predictor requirement change) |
| W2 | Parked H-20 windows between predicted purges, at least 30 min (about 170 purges) | No UV_BUS, no `ERR_FC_ONLY_COLLAPSE`, no `PURGE_LEAD_SHORT`; BT_BUS HIGH for at least 31.8 ms at every onset; V_bus at or above 13.5 V across every purge; charge time per period against 94.5-95.6 % | FC windows stay on the bench supply |
| W2b | As W2 in State 2 at standstill (D-s) inside drive sessions, with rail share commands, traction steps at random phase and a first request issued in Run | As W2; no `OC_FC`; no pin-27 or pin-28 write from the share latch or the selector during a session; traction released at most 61.7 ms after the command; the State-2 dump check runs at the first stop | `IC1_FC_RUN_STANDSTILL` stays 0 |
| W2c | Unpredicted collapse from a bench supply inside a window: supply off and back on after 80 and 140 ms; each `ERR_FC_ONLY_COLLAPSE` reading alone; predictor-stub UNKNOWN and late events; BT_BUS unable to conduct; the State-99 pack drain for 10 min | `ERR_FC_ONLY_COLLAPSE` latches; FC_BUS LOW before the source returns; no BT_BUS write after the latch; after a power cycle the self-test, a dump check and W1 pass and both boosts regulate; drain recorded against 0.2-0.25 A | Stop; revise the teardown |
| W2d | False latches over every W1, W2 and W2b session and the C-4 drives | No `ERR_FC_ONLY_COLLAPSE` without a source loss | Re-derive the 13.0 V and 12.0 V thresholds |
| W2e | The deployed Pi node, then the updated node, over a recorded stop, a Run exit and a parked request | Deployed: FC_CHARGE never HIGH, code 15 reported; updated: a window opens only on an FC-charge decision | FC windows refused on the vehicle until the OR-RQ Pi round passes |

The order of commissioning is a bench supply on J-FC (C-2b, W1, B8-1), then W2a, W2e, W2, W2c, W2b and W2d (revision
12, BT8-REQ-03); W2d counts false latches over every session, and W2e precedes the first window on the vehicle. Before
the W2e Pi round, the State-98 window-request key is the request source for C-2b, W1 and W2. W2
decides whether Stage 1 charges from the H-20; W2b decides whether it charges at drive-cycle stops.

### 4.4 Stage 2

Stage 2 needs the Stage-1 gates, the pin-39 calibration M-R2 and gates V2-0 (D-BC-RG turn-on delay), B8-2 (the VBT load I_L in a regen window; the HR1 hold
condition I_L at most 0.75 A), V2-1 (VOK channels,
including tap-open, tail and plateau cases), V2-2 (release race), V2-3 (does the VESC keep braking with V-MOT near 18 V),
V2-4 (captured charge per decel against the OR-B fraction, including any charge captured in the VESC-stop tail), V2-5
(traction request inside a window) and V2-6 (configuration check and probe from the H-20 between predicted purges,
after W2). A firmware stop is not evidence of capture. On present
evidence (65-170 ms cold start, UDDS braking no steeper than coast-down, no Stage-3 hold-up) the expected Stage-2 harvest
is near zero.

---

## 5. Firmware, telemetry and HIL work

The firmware change is large. [DD] section 12.12 lists nine separate orchestrated rounds:

1. a watchdog round (RTWDOG; WDOG1_B is not used since revision 7; removal of blocking operations from armed states, the `Ethernet.begin()` ordering),
   which is the Stage-1 entry gate;
2. the mode manager and self-test (`chgModeTick()`, the non-blocking boot and Idle self-test with the revision-12
   re-run rule and refusal code 16, the ladder decode, the dump check with its revision-12 retry rule, 27 new fault conditions, the per-board calibration record in EEPROM bytes 0-511 with State-98 key `7`);
3. the Ag105 policy, the FC window, the configuration check, the eFuse-blocking probe and the purge interface: the
   predictor inputs (`purge_tto`, `purge_active`, the permit and UNKNOWN), the pre-purge sequence, the re-entry gates,
   `ERR_FC_ONLY_COLLAPSE`, the State-2 standstill window behind `IC1_FC_RUN_STANDSTILL` with the State-2 dump check,
   the fixed window split (MDAC code 717) and the traction hold, the State-98 window-request key, and the removal of the fw v33b lockout from the charge path (the
   FC-only share-selection lockout is unchanged); the predictor itself is the operator's (ruling OR-P), and the round
   tests the interface against an ideal-predictor stub;
4. telemetry protocol v6 and BLG, with the Pi bridge;
5. the HIL plant, the observation frame and the injection-frame extension; IC1 has no HIL coverage until this
   extension lands (revision 12);
6. the Pi EMS round, a Stage-1 prerequisite (ruling OR-RQ): the deployed nodes use `charge_goal` as a regen gate, so
   the Pi must set the request flag 0xA5 in command byte 20 from an FC-charge decision only, add the parked form
   (`mode_cmd` 4), decode the refusal codes, and land in lockstep with protocol v6 (gate W2e);
7. the HIL suite and the tool mirrors (`tools/run_hil_suite.py`, `tools/hil_plant_sim.py`, `governor_model`,
   `ems_walk`);
8. the reconciliation with the fw v38 plan, whose three-layer regen interlock is superseded by the VOK hardware, the
   eFuse source term and `ERR_VCHG_FED`;
9. documentation (PLAN.md, the CLAUDE.md doctrine text, the IO CSV).

Revision 10 re-derived the size per package against the fw v28 package and the fw v37 `J` session: about
7,100-11,300 `.ino` lines and 1,450-2,300 host test checks, plus 1,000-2,000 lines of tool, HIL and Pi changes; about
90 % is Stage 1, and the purge package alone is 1,000-1,900 lines (estimate, UNCONFIRMED; [DD] section 12.12,
`calc/ic1_rev10_calcs.py` section 9). The revision-5 estimate of 4,000-7,000 lines predates the purge package. For
scale, the fw v28 feature package added 1,916 lines and 389 checks. The estimate has not been re-derived for the
revision-11 and revision-12 items or the injection-frame extension ([DD] open item 43).

Telemetry needs `I_PACK1`, `V_PACKN` and a 16-bit hardware status word. [DD] names the layout protocol v6, built on the
R4 v5 layout (73 bytes, scheduled with fw v38) with the IC1 fields appended; the byte count and checksum span are not
yet defined, and `fault_flags` has no free bit for the new fault conditions (CC-B3, open). From revision 9, protocol v6
also carries the window-request bit, the window state, the purge-permit state (permit, prediction, UNKNOWN, purge
active), the share-override bit, a `PURGE_LEAD_SHORT` counter and the 8-bit refusal code; the BLG records the loop
iteration that precedes each prediction observation. The command packet keeps its 22-byte length and checksum span,
but byte 20 changes meaning (the request flag, ruling OR-RQ). The protocol-bump procedure and the Pi bridge lockstep
apply to both packets (OR-H).

The HIL can test the sequencing, the faults and the switch states once the plant gains a PACK- node, the sense in the
return, the three switches, the eFuse and the VOK channels. It cannot test HR1 or HR2, because the status-level Ag105
model has no Bring-Up, start latency or threshold behaviour; the bench gates decide them. The share-override duration
in closed-loop State 2 is firmware-only and measurable on the existing HIL plant once the `static_assert` below is
lifted. A `HIL_SIM` build has no source
for the ladders, pin 8 or the new analog channels and would latch `ERR_CHG_LADDER`; [DD] section 12.10 specifies a
`static_assert` that refuses that build until the injection frame is extended (CC-B5, closed in revision 7).

---

## 6. Parts, cost and schedule

Table 8 gives the cost estimate by assembly ([DD] section 16 Table 18). Prices are budget estimates and UNCONFIRMED.

Table 8. Cost estimate (USD).

| Item | Main parts | Estimate |
|---|---|---|
| SB | 3 x CSD18510Q5BT (+1 spare), R_SH, fusible R_K, BSS138/BSS84, Zeners, fuses, 2-layer board, enclosure | 35-60 |
| LB | SN74LVC1G74 and about 20 LVC/AHCT gates and buffers, 2 x INA240A3, 9 x TLV3011B, 15 x BSS138, 13 x BAT54, about 36 x 0.1 % resistors (VC1 tap included), R_MDS, C_VC1, the four LB-entry series resistors of revision 8, 2-layer board | 60-95 |
| CB | TPS26631PWPR or TPS26636PWPR, Q_MD, R_MD rated on the continuous-pulse curve (candidate Vishay CRCW2512-HP 15 Ohm), R_MB, F_VX 4 A (candidate Littelfuse Nano2 451/453) and holder, networks, small board | 12-25 |
| Balance network (M16) | 1 x low-leakage Schottky D_VC1 (first build: provisional part under OR-AC option (d), candidate NSR0320MW2; final part after gate B8-1), RB1A 4.7 kOhm, R_VC1a 200 kOhm 0.1 %, a replacement CBL2 | 1-2 |
| Harness | F_PK 20 A and holder, keyed 30 A pack connector, keyed 7-way and Kelvin connectors, wire, the signal sleeves (a third sleeve for SHDN_EF from revision 12), staking adhesive | 20-30 |
| Stage 0 rig | 2 x Ag105 (a third if OR-J selects S0-10), external shunt, RT1987, electronic load, pack simulator access, capacitor bank | 60-100 plus two or three module prices TODO(verify: distributor) |
| Stage 3 | Withdrawn in revision 7 ([DD] section 14.4) | - |

Stage 1 costs about USD 115-210; Stage 2 adds about USD 10-20. The connectors, the fuse holders, the SB enclosure and
the three boards have no part number yet (CC-B11). Revisions 9-12 add no electrical part: the FC windows between purges are
firmware, gates and rulings on the revision-8 hardware, and revision 12 adds one harness sleeve, so the estimate is
unchanged.

The availability read of 2026-11-07 is UNCONFIRMED and must be repeated at order. The TPS26631PWPR had zero stock and a
26-week lead; the pin-compatible TPS26636PWPR (1,218 in stock) is the approved alternate. The INA240A3PWR had zero
stock; the INA240A3D (SOIC-8) is specified instead. The CSD18510Q5B is ordered as the CSD18510Q5BT reel. In battle-test
round 4, TI.com showed the TPS26631PWPR out of stock while cached distributor pages disagreed; stock must be confirmed
live, with the date recorded, before any order ([DD] open item 28).

No calendar schedule exists in the study. The work is ordered as Stage 0 (no board change), the recommended further
battle-test round on revision 12 (section 0.3 item 1), the provisional D_VC1 of OR-AC option (d) (ruled 2026-11-09), the Q_MD selection, the watchdog round, the pre-rework gates, the Stage-1 build with firmware rounds 2-4 and the Pi round of
OR-RQ, commissioning from a bench supply, and then the H-20 gates of Table 7a. The operator's purge predictor must
exist before gate W2.
Board fabrication and assembly times are TODO(verify: board house); a labour estimate is TODO(estimate: operator).

---

## 7. Open questions and missing primaries

### 7.1 Open items gated on a bench result or a part selection

No design blocker is open in revision 12 ([DD] Appendices F and H-J), and every major of rounds 5-8 is dispositioned.
However, revision 12 has not been battle-tested, and Appendix I items 2-6 and Appendix F items 5-8 have not been
reported on (section 0.3 item 1), so this statement covers the findings raised so far. The following items are gated:

1. the clamp D_VC1 against the two-endpoint specification (V_F at most 0.25 V at 16.2 mA at T_min, I_R at most 40 uA at
   4.2 V at T_M16,max), which no identified passive part meets (`calc/ic1_rev12_calcs.py` section 8); a provisional
   part under OR-AC option (d) for the first build (chosen on 2026-11-09; candidate NSR0320MW2 at T_min 25 C), then option (a) or (c) after gate B8-1 unless T_M16,max is below
   about 44 C ([DD] open item 13); the BQ29200 VC1_CB absolute maximum is TODO(verify: TI);
2. the F_VX part (candidate Littelfuse Nano2 451/453 4 A: 16.0 mOhm, 2.469 A2s, 400 A at 32 VDC, as read in round 5),
   its cold resistance (which sets the charge-mode OV_BATT and BQ29200 boundaries) and its I2t against the Ag105 sense
   rating (re-read at order; TODO(verify: Silvertel));
3. pin 8 as an input, only if the rewritten gate P8 confirms that nothing drives the old ENC_B net (fallbacks: pin 2,
   which shares the encoder history, then the RENC2-removal bodge or a sixth ladder bit, by operator choice);
4. the eFuse-bypass probe, which is not a qualified detector until C-2b and S0-14 pass;
5. whether a released open-drain MPPTD reads as MPPT enabled (S0-7);
6. the regen-arm latency under the fw v37 drive law (`tools/drive_ripple.py` plus a v37 decel BLG);
7. the pin-39 two-point calibration (M-R2) and the ratio noise check at V2-1;
8. the Q_MD part and the R_MD rating: 1.71 J in 100 ms on the single-pulse curve, the repetitive dump on the
   continuous-pulse curve (TODO(verify: Vishay doc 20043)); the Q_MD selection records the V_GS(th) range near
   1.55-1.68 V, a linear-mode SOA and V_GSS, on which row F66 depends ([DD] open item 17, revision 12); the operator
   accepted the row F66 residual on 2026-11-09, and the Q_MD selection still blocks a motherboard change;
9. the pin-20 input leakage against the 122 kOhm tap source (0.488 V of mismatch per uA, 79 nA allowed): the
   datasheet pad-leakage bound of 1 uA gives 488 mV, 12.7 times the allowance, so the 80 mV `ERR_CELL_MISMATCH`
   threshold rests on the C-2a hot and cold record; the detection of row F47 does not depend on it (at least 7.5 V of
   signal against 0.53 V of worst healthy error; `calc/ic1_rev12_calcs.py` section 7); a CMOS follower on LB is the
   recorded fallback, a new circuit ([DD] open item 24, gate C-2a item 5);
10. the injection rating of the pin-20 pad, TODO(verify: IMXRT1060CEC) ([DD] open item 29, narrowed in revision 12);
    the TLV3011B inputs and the LVC outputs have no positive clamp (SBOS300C section 6.2 note 2 and section 9.4.4;
    SCES214AF section 5.1), so the other leads rely on segregation, not on a rated clamp current (accepted by the
    operator on 2026-11-09, with no clamps added);
11. the Ag105 input capacitance (at least 47 uF for the exit hold check; above 103.6 uF, C_DV is raised and the
    `ERR_MOD_DUMP_ON` sample re-keyed; S0-11), and the TPS26631 UVLO-to-ramp delay and whether it scales with C_DV
    (TODO(verify: SLVSE94G), [DD] open item 46);
12. the D-BT-EN and D-FC-EN conduction onset after a re-close onto a live bus (t_D_ON plus the 19.77 ms soft-start), on
    which T_lead,min and T_late rest; the 30 ms `SHARE_CUT_SURVIVOR_BLANK_MS` covers it only at t_D_ON 10.23 ms or less
    (gate W2a; [DD] open item 32);
13. the maximum loop iteration of the production build (USE_ETHERNET 1, State 2, the Ag105 poll, the SD drain) against
    the 19.0 ms bound of the late rule (gates W1 and W2b; [DD] open item 42);
14. the in-window FC droop resistance at the fixed split (0.094-0.353 Ohm) and the 4x gap between the design-chain and
    bench-scaled droop, which needs the DMM measurement of the AD5443/OPA197 block (gate W1; [DD] open item 41);
15. the standstill constants I_still, T_still and the speed threshold of variant D-s, and the request threshold
    `CHG_GOAL_MIN` (gate W2b; [DD] open item 38), and the standstill auxiliary load, 0.016-0.024 A in the bags against
    0.09-0.15 A in the HIL;
16. "no damage" on an unpredicted collapse, the TPS61288 restart after a VIN UVLO with EN held HIGH, and the State-99
    pack drain of about 0.2-0.25 A (gate W2c; [DD] open items 33 and 39), with the pack PCM under-voltage cut-off
    (pack datasheet missing);
17. the H-20 open-circuit voltage against the 12.34 V full scale of the pin-24 divider: an unloaded stack above 13.46 V
    would overstress pin 24 in W2 and W2a (TODO(verify: Horizon H-20 OCV), [DD] open item 44); fw v37 rev 2 has no V_fc
    overvoltage fault, so a saturated reading goes undetected ([DD] open item 45). Both exist on board revision 20260622
    independently of IC1.

The following items are analyses that this study has not run:

18. HR2 in Run against an EMS that requests FC charge: walk the SDP v7 policy and the J_charge table of the 2026-10-28B
    Pi node over the drive cycles in `tools/ems_walk.py` with the IC1 admission rules (standstill, the 8.0 V gate, the
    1.282 s admission horizon, a 0.450-0.569 s dead time per purge period, the State-2 dump check at the first stop),
    and compare D-s with D ([DD] open item 40). Until it runs, HR2 in Run against EMS requests is undetermined, and
    ruling OR-DM rests only on the traction-allowance, sense-error and uncovered-purge argument.
19. The firmware-size estimate for the revision-11 and revision-12 items and the HIL injection-frame extension ([DD] open
    item 43).

The predictor itself is not an open item of this study (ruling OR-P); its interface is a requirement on the operator
(Table 1b).

### 7.2 Gaps left open by the completeness critic

The completeness critic left 15 gaps open after round 3 ([DD] section "Completeness critic", Table CC-B). Revision 7
closed seven of them by design (CC-B5 `HIL_SIM` refusal, CC-B9 one GO per C-2a sub-item, CC-B10 the B13 consumer and the
S0-8 criterion, CC-B12 `CHARGER_STAT` logged only, CC-B13 the State-99 pin-8 wait, CC-B14 a gate for row F53, CC-B15
`PI_TIMEOUT` does not act in State 1 or 98) and listed two as rulings (CC-B1 as OR-Z, CC-B2 as OR-Y, both accepted as
proposed on 2026-11-09). Revision 8 closed
CC-B4 (the calibration record in EEPROM bytes 0-511, written by State-98 key `7`). Five remain open:

- CC-B3: the protocol v6 layout, byte count, checksum span and a fault word for the 27 new fault conditions (uint32);
- CC-B6: the 3V3 load budget against the 250 mA PJRC limit (TODO(verify: SBOS662C, SBOS300C, TI LVC datasheets));
- CC-B7: the Q_MD and R_MD part selection (the rating basis is now named);
- CC-B8: `ERR_VCHG_SENSE` rule (b) false-latches if the RT1987 turn-on delay exceeds 19 ms, for which RT1987 DS-00 gives
  no maximum, and the `ERR_MOD_SENSE` (b) crossing anchor depends on the same delay (V2-0);
- CC-B11: part numbers for the connectors, holders, enclosure and boards.

### 7.3 Missing primaries

The following values have no primary in the repository or in the vendor documents read ([DD] section 18):

1. Ag105: cold-start and restart timing, threshold tolerance, MPPTS law accuracy, the function of the internal switch
   across the sense and the effect of LD, input capacitance, EPROM endurance, whether resistor mode is read at power-up
   only, behaviour at power-up within 0.2 V/cell of CV, whether the module back-feeds its input, and efficiency at 2S
   with a 16-21 V input. TODO(verify: Silvertel).
2. RT1987: turn-off time after EN falls and the t_D_ON maximum. TODO(verify: RT1987 DS-00). From revision 9 the
   t_D_ON maximum also sets the predictor lead time: each millisecond above 12 ms adds one millisecond to T_lead,min
   and T_late (gate W2a).
3. TPS26631: SHDN-to-FET-on delay, IMON gain tolerance row, FLT behaviour on UVLO with SHDN low, and the TPS26636
   fast-trip multiple. TODO(verify: SLVSE94G).
4. i.MX RT1062 pad figures: analog-input leakage on pin 20 over temperature (the datasheet bound of 1 uA is 12.7 times
   the allowance) and an input-injection rating for pin 20. TODO(verify: IMXRT1060CEC). The revision-6 question of WDOG1_B on pin 20 is moot, because
   revision 7 gave pin 20 to the VC1 tap.
5. The pack datasheet: maximum charge current and the PCM short-circuit trip, which bound the unfused leads between the
   cells and F_PK. TODO(verify: pack datasheet).
6. Logic and passive figures: LVC and LVC244A thresholds and input leakage at 3.3 V (the BAL_OK margin at R_BL2
   100 kOhm 1 %, threshold 7.0 V at the worst corner, revision 12), the TLV3011B open-drain fall delay, INA240 bias mismatch and behaviour beyond the
   -6 V common-mode absolute maximum, the BQ29200 VC1_CB absolute maximum, and the shunt, fusible-resistor and fuse
   datasheets. TODO(verify: TI, vendor datasheets). (Closed: the TLV3011B output when unpowered is Hi-Z, SBOS300C
   section 9.4.5; the TLV3011B inputs and the LVC outputs have no positive clamp, revision 12.)
7. A low-leakage Schottky for D_VC1 that meets both temperature endpoints; none identified (revision 12, ruling OR-AC).
   TODO(select).
8. V_rgn reads 0.85 x true (pin 39), to be corrected by M-R2.
9. The purge-collapse inputs (revision 9): the H-20 fall time at a purge onset (no primary; policy E2 removes the
   dependence), the TPS61288 soft-start after a VIN-UVLO recovery with EN held HIGH (SLVSFP3C section 8.3.1 covers an EN
   edge only; TODO(verify: TI)), the TPS26631 reverse current from OUT to IN (TODO(verify: SLVSE94G)), the Ag105
   lockout tolerance, MPPT loop speed and restart after a brown-out (TODO(verify: Silvertel)), the V-MOT capacitance and
   the VESC cut-off voltage (8 V ASSUMED; TODO(verify: VESC)) ([DD] open items 33-35).
10. The H-20 purge figures beyond `facts_prior.md` section 7 (period 10.34 s, duration 100-140 ms, floor about 1 V). The
    predictor and its error band are the operator's (ruling OR-P) and are not measured by this study.

---

## 8. Sources

**Requirements and prior work.**

- `docs/charger_replacement_evaluation_2026-11-05.md` sections 0.1 and 1.1 (rulings 1-10, HR1-HR5, H1-H12).
- `docs/boost-bringup-debug.md`, 2026-11-04 entry (the ML0227 incident); `logs/ML0227.BLG`.
- `docs/fw37_planning_2026-11-04.md` sections 3.3 and 4 (the fw v38 regen interlock and telemetry v5).
- The operator rulings of 2026-11-08 on fuel-cell purges (quoted in section 0.1; recorded in [DD] section 17 as OR-P and
  OR-SC, and in [DD] Appendix G).
- `docs/fw30_fc_purge_uv.md` (the H-20 purge behaviour and the UV_FC rules); `references/EMS/Pi_2026-11-03/EMS/ROS2/` (the Pi
  EMS nodes and bridge, among them `sdp_ems_node_2026-10-28B.py` and `teensy_bridge_node_2026-10-31A.py`);
  `logs/rosbags/` (the Pi sessions).

**Board and firmware primaries.**

- `references/Scale_Car_Board_20260624.sch`; `references/Scale Car Board PCB 20260625.brd`; the BOM CSV;
  `references/Scale Car Teensy IO - IO.csv`; `teensy_controller/teensy_controller.ino` (fw v37 rev 2).
- Silvertel Ag105 DS V1.1 (November 2021), `references/Datasheets/AG105_Silvertel.pdf`, and
  `references/Datasheets/Ag105_Table3`-`Table7` JSON extracts.
- Richtek RT1987 DS-00; TI TPS61288 SLVSFP3C; TI BQ29200 SLUSA52C; TI LM1084 SNVS037H (repository copies).

**New-part primaries (vendor PDFs, TI site, not saved in the repository).**

- TI TPS2663x SLVSE94G (September 2018, revised June 2024).
- TI TLV3011/TLV3011B SBOS300C (February 2004, revised April 2023).
- TI INA240 SBOS662C (July 2016, revised December 2021).
- TI SN74LVC1G74 SCES794G section 6.3.
- TI CSD18510Q5B SLPS632; the further dossier primaries listed in each concept dossier's citation table.

**Study material ([STUDY] = `docs/reviews/battery_isolation_2026-11-07/`).**

- Fact sheets: `facts_board.md`, `facts_ag105.md`, `facts_firmware.md`, `facts_prior.md`; the purge fact sheets of
  2026-11-08, `facts_purge_sequencing.md`, `facts_purge_collapse.md` and `facts_purge_demand.md`.
- `brainstorm.md` (21 raw concepts, clustering, X1-X9, drops).
- Concept dossiers: `concept_IC1-commanded-return-changeover.md` (revision 2, kept as design history),
  `concept_IC2-autonomous-steered-return.md`, `concept_IC3-dbtsq-pack-switch-battery-port.md`,
  `concept_IC4-highside-pack-switch-module-permit.md`, `concept_IC5-isolated-charger-input.md`,
  `concept_IC6-literal-two-leg-relay-transfer.md`, `concept_IC7-control-external-bounding.md`.
- `detailed_design_IC1.md` revision 12 with Appendices B-F (battle-test adjudications of rounds 1-5, including the
  Appendix F list of what a later review must check on the revision-8 changes), Appendix G (the operator rulings of
  2026-11-08 and the reconciliation of the purge fact sheets), Appendices H and I (adjudications of rounds 6 and 7,
  including the Appendix I list for the revision-11 changes), Appendix J (adjudication of round 8, including the list
  for the revision-12 changes) and the completeness critic tables CC-A and CC-B.
- `battletest/fmea_round1.md` to `battletest/fmea_round8.md`.
- Calculation scripts and outputs in `calc/`: `ic1_rev3_calcs.py` to `ic1_rev12_calcs.py`, the `bt1_*` to `bt8_*`,
  `fmea_round1_calcs.py` to `fmea_round7_calcs.py`, `purge_sequencing_timeline.py`, `purge_collapse_sim.py`,
  `purge_demand_budget.py`, `purge_seq_bags.py`, `verify_*.py` (among them `verify_stage3_exit_drain.py`,
  `verify_dvc1_two_endpoint.py` and `verify_hr2_cooldown.py`) and `cc_completeness_calcs.py` scripts, and
  `feasibility_battletest_tally.py` (the finding counts of section 3.1, rounds 1-8).
