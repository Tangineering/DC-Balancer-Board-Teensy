# Software/system blast radius: Ag105 replacement (Path A) vs bidirectional re-spin (Path B)

Scope: repo at HEAD (fw v37 rev 2, `teensy_controller/teensy_controller.ino`, 17 212 lines). Line numbers are HEAD.
Path B is the alternate path (not a fallback). Effort is in engineer-days (ed), including host tests. It does not include bench time or HIL campaign wall time.
The charger-specific behaviour in Path A (watchdog, VINDPM, inverted off-pin, volatile registers) comes from docs/bq25713_charger_replacement_2026-11-04.md. It is used here as the representative candidate and is UNVERIFIED by me against TI primary sources.

## 0. Headline
- **Path A is a driver swap behind an existing seam.** All charger I/O goes through about 10 functions: `pollAg105`, `ag105IsReady`, `initAg105Charger`, `ag105Read/WriteConfigReg*`, the MPPT manager, the `J` session and `chargingControl`. Two cached outputs feed the rest of the system: `I_charge` (f32) and `ag105_status_raw` (u8).
  - **No telemetry bump is forced** if the new driver synthesizes a Table-6-compatible status byte. In that case the HIL injection frame, the Pi bridge and the suite scoring are untouched.
  - A bump is still recommended: fold it into the already approved v5 (fw37_planning section 4). Add `charger_flags` and a charger-type id so the Pi can tell the old byte meaning from the new one.
- **Path B deletes the charger subsystem and the FC_CHARGE / REGEN switch semantics.** It also redesigns the share loop (now an I_fc current command), MOT_PWR / pre-charge, battery protection (CC/CV in firmware) and current sensing (bipolar). Telemetry (v5 or v6), the HIL plant topology, DP/SDP/governor/walk and the Pi EMS all change.
  - The share-loop change touches the CLAUDE.md "What NOT to change" list, so it needs an operator exception.

## 1. Firmware touchpoints (teensy_controller.ino)

| # | Location (line) | What it is | Path A change | Path B change |
|---|---|---|---|---|
| F1 | 1-30, 755-830, 962-969 | changelog / fw v37 rev2 header | new changelog block, FW_VERSION 38 (4281) | same |
| F2 | 1984-1985 | `MPPT_DISABLE` (5, active-LOW inhibit), `CHARGER_STAT` (6) | Pin polarity and meaning change. On the BQ25713 EVM, ILIM/Hi-Z is HIGH = disable, so it is not fail-safe (note section 5.1). CHRG_OK means "input present", not Table 5 STAT. The CSV Code Name is authoritative, so a rename needs a CSV amendment plus a new never-rotated bodge record in CLAUDE.md. Pin tests break. 0.5 ed | Pins become free or are reassigned to converter EN / fault lines. CSV re-done for the new rev |
| F3 | 2013-2014, 2030-2032 | `CHG_VOLTAGE`/`RGN_VOLTAGE`, `SCALE_V_CHG/RGN` (78.7k/10k) | unchanged (same pads, same divider) | V_chg is gone; V_rgn becomes the motor-node / bus-side regen sense. New divider |
| F4 | 2053, 2055; 7435-7449 | `FAULT_OV_CHG`, `FAULT_CHARGER_STAT` = GENSTAT 5/6/7 latch (`!BENCH_TEST`) | Remap to the new chip's fault bits (or the synthesized GENSTAT). `ERR_CHARGER_STAT` kept. 0.5 ed | Replace with converter fault, CC/CV-limit and pack-OV faults. The fault bit layout changes (16-bit fault_flags) |
| F5 | 2453-2484 | Ag105 constants (addr 0x30, reg 0x00/0x01/0x06, GENSTAT codes, `AG105_SETTLE_MS` 500) | New register map (BQ25713 0x6B per note; volatile registers, so rewrite after every charger power-up). Settle time is TODO(calibrate). 1 ed | delete |
| F6 | 2487-2580, 3827-3877, 15683-16062 | **MPPT threshold manager** (reg 0x02 EPROM ratchet, 8 writes/boot, reg 0x07 cross-check) about 400 lines + state vars | Replace with an input-voltage-limit (VINDPM-class) setter. It is a single volatile write per power-up, so the EPROM-endurance budget and ratchet machinery disappear. The concept is reused: threshold above the bus (R3 layer 2), set from V_chg (pin 38). 2 ed | delete. The R3 problem disappears with the topology |
| F7 | 2597-2655 | FC-charge UV backoff (12.8/13.6 V, 15 ms), `FC_CHARGE_ALLOWED 0`, `MPPT_RELEASE_HOLDOFF_MS`, static_asserts tied to MPPT counts | Keep the backoff. Re-derive the static_asserts against the new threshold constants. 0.5 ed | delete. A converter current limit replaces them |
| F8 | 2659, 7637-7700 | Telemetry v4, 58 B; offset 19 `I_charge`, offset 51 `charger_status` | **Not forced** if `I_charge` = the new chip's charge current (battery-side, A) and offset 51 = a synthesized Table-6 byte. Recommended: v5 (approved, R4) adds `charger_flags` + charger id. Use the protocol-bump skill. 1 ed (shim) / +1 ed (v5 fields) | **Forced.** `I_charge` gets a new meaning (converter battery current, bipolar). `charger_status` becomes converter status. `switch_state` loses SW_REGEN / SW_FC_CHARGE meanings. Add an I_fc command echo plus CV/foldback flags (respin note section 4.4). 2 ed |
| F9 | 3803-3822 | `I_charge`, `ag105_status_raw`, `ag105DataValid`, `ag105Configured`, `ag105MeasUnavailable` | Rename optional. The lazy-configure semantics are kept (re-arm on power loss). 0.25 ed | Replaced by converter state |
| F10 | 4294-4490, 4613-4721 | HIL injection frame (40 B): offset 34 `I_charge`, offset 38 `ag105_status`; obs frame (18 B) offset 15 `mppt_thresh_count`; pollAg105 HIL bypass 16081-16105 | Unchanged if the status shim is used. Repurpose obs byte 15 as the input-threshold code, or keep it at 0xFF. 0.5 ed | Frame redesign (converter current / mode, I_fc reference). Both frames bump. 2 ed |
| F11 | 4961-5183 | **fw v37 rev2 J-session constants**: G1 Isrc 1.0 A/5 ms, G2 Punacct 3 W/20 ms (eta_min 0.75, P_chg credit 21 W), G3 GENSTAT, trip codes, `AG105_VBATN_ISOLATED` gate (5070-5083) | **REUSE G1/G2/G4 verbatim.** G3 is remapped to the new fault bits. The G5 gate flips meaning: rename to e.g. `CHARGER_RETURN_COMMON_GND_OK` and default it OPEN only once the replacement is fitted and bench-proven. Keep the runtime flag pattern. 1 ed | G1/G2 concept reused for converter bring-up. The gate becomes irrelevant |
| F12 | 5505-5631 | prototypes | follow the renames | follow |
| F13 | 6706-6955 | State-0/HIL wait, pollAg105 at 50 Hz, `S` dump (6883) | update the print fields. 0.25 ed | update |
| F14 | 8170-8211 | State-99 / Idle clears of charger caches | keep the pattern. Add an explicit charger hard-off (Hi-Z / inhibit) in State 99. 0.25 ed | converter discharge-only / charge limit 0 in State 99 |
| F15 | 8581-8864 | State-98 keys `4` (MPPT toggle), `5` (FC_CHARGE via `assertFcChargeEnable`), `N` (MPPT threshold), `J` (commissioning) | `4` becomes the charger enable toggle (new polarity), `N` the input-threshold set, `J` re-targeted (see F17). `5` unchanged. 0.5 ed | `J/N/4/5` retired. New keys for converter charge-limit, I_fc reference and mode |
| F16 | 11011-11200 | `printMpptStatus`, `parseMpptLine` | rewrite for the input threshold. 0.5 ed | delete |
| F17 | 11204-12110 | **J commissioning session** (start/stop/abandon/tick/trip/summary, as-found latch, profile write, NAK backoff, `ag105ChargerFeedRefused`) about 900 lines | Keep the skeleton: preconditions, stops (V_bus low 20 ms, 120 s cap, X/Q/fault, pin dropped), G1/G2 tick, trip latch, refusal helper. Replace the register round robin, as-found latch, 3S-guard and profile write with the new chip's equivalents. Add a watchdog keepalive (note section 5.2: 5 s watchdog so a stalled Teensy stops charging) and host-terminated charging (taper / CV criteria in firmware). **This is the "minimal bench driver".** 3 ed | replaced by a converter bring-up session |
| F18 | 12743- | `assertFcChargeEnable()` (FC_CHARGE guard: BT_BUS/REGEN LOW first) | unchanged | delete or replace. The FC_CHARGE switch no longer exists as a charger feed |
| F19 | 15289-15557 | **`chargingControl()`**: UV backoff, MPPT_DISABLE regen/cruise strategy, bootstrap-on-intent, readiness gate (`ag105IsReady`, GENSTAT), F1 disarm-before-open, regen branch gated by the G5/G4 latch, `FC_CHARGE_ALLOWED` | Structure kept. Changes: polarity of the enable pin; readiness = the new chip's status (input present + configured + not faulted); bootstrap-on-intent still needed (VIN-powered chip, same deadlock). Charge-current ceiling from `charge_goal` becomes a real current register (the Ag105 has only profiles), which is a gain. Add the v38 R3 interlock (REGEN only while V_rgn > V_bus + margin, planning section 3.3). 3 ed | **Rewrite.** Becomes the charge-budget allocator (respin note section 2.1): regen priority, FC surplus fills headroom, CC/CV taper at 8.4 V |
| F20 | 15598-15682 | `ag105Read/WriteConfigRegVerified`, `initAg105Charger` (status byte prepended to every read) | New I2C transport: standard register-pointer reads, 16-bit little-endian registers on BQ257xx (UNVERIFIED). Verified-write pattern reused. 1 ed | delete |
| F21 | 16064-16230 | **`pollAg105()`** 50 Hz: power gate, settle window, lazy config, 0x06 read, stale-clear (fw P2-1), HIL bypass | Rewrite the transport. Keep the gating / lazy-config / stale-clear logic verbatim. Re-scale the charge-current ADC/register. The synthesized status byte is produced here. 1.5 ed | delete; converter telemetry poll instead |
| F22 | 16232-16260 | `ag105IsReady()`, **`chargerHasPower()`** (FC_CHARGE HIGH, or REGEN+MOT_PWR HIGH), `fcChargePathIsPowering()`; 16 call sites | `chargerHasPower()` reused unchanged (same pads, same RT1987 feeds). `ag105IsReady` decodes the new status. 0.25 ed | delete |
| F23 | share loop / governor / selector (fw v26-v30) | F1 sequencing, k_d hold in charge windows (topology-keyed), selector disarm | unchanged (the switch topology is identical) | **Rewrite.** Two-boost droop share becomes an I_fc current command. Needs an operator exception to "What NOT to change". The Youla-H coefficients and regen-coeffs flow are retired or redone |
| F24 | detectFaults OC/UV, MOT_PWR hot-plug guard (`assertMotPwrEnable`) | | unchanged | MOT_PWR becomes a bidirectional / back-to-back switch, so the Death-5 pre-charge logic is redesigned. INA253 battery channel becomes bipolar (SCALE_I offset, REF pins). `LIMIT_*` re-derived |

Path A firmware net: about 1 900 lines touched. Of those, about 900 are the J session (mostly kept skeleton) and about 500 the MPPT manager (mostly deleted). Path B: about 3 500+ lines removed or rewritten, plus the share-loop core.

## 2. Host tests (test/)
- `test_main.cpp` (28 354 lines, 499 test functions). 60 functions are charger/MPPT/J-named and about 1 340 lines reference Ag105 symbols. Build checks at HEAD: 5238 / 210 / 5549 / 51.
- `mock_wire.h`: the injectable byte queue assumes the Ag105 "status byte first" framing. It needs a register-addressed responder (0.5 ed) for either path.
- **Breaks under Path A** (rewrite or re-pin):
  - `test_ag105_constants`, `test_init_ag105_charger`, `test_poll_ag105`, `test_ag105_config_read_verify`
  - `test_genstat_fault`, `test_charging_control_mppt_polarity`
  - the 6 `test_hil_wiring_pollag105_*` tests
  - `test_pollag105_state_gate`, `test_pollag105_unpowered_never_faults`, `test_pollag105_settle_window_suppresses_fault`
  - all 26 `test_mppt_*` tests (deleted or ported to the input threshold)
  - `test_j_mppt_threshold_write`, `test_j_mppt_toggle`, `test_j_g3_charger_error`, plus the G1/G2/latch/gate tests (kept with renamed symbols)
  - pin-map tests for pins 5/6
  - `FW_VERSION` pin
  - `test_charger_has_power` survives unchanged.
  - Estimate: 35-45 functions rewritten, 6-10 ed to bring all three targets green.
  - Note: v35/v36 had pre-existing FC-charge-path failures; v37 rev2 is green.
- `test/mppt_assert_probes.sh`: delete or port.
- **Path B**: all 60 charger functions plus the share-loop / governor tests (gov_ceiling_harness, gov_fw28_harness, fw28 selector tests) and the hot-plug tests. Effectively a new suite for the power path. 15-25 ed.

## 3. HIL / EMS tooling (tools/)

| File (Ag105 / charge mentions) | Content | Path A | Path B |
|---|---|---|---|
| `hil_plant_sim.py` (449): AG105_* consts 240-318, Plant charger state machine 1720-1805, 2362-2498, `ag105_mppt_volts` 1226, `ems_mppt_harvest` 4028, `RegenManager` 3666 | Status-byte state machine, 0.5 s settle, 0.4 s tau, 2.5 A ceiling, MPPT threshold behaviour | Re-parameterize: settle, tau, I ceiling (now continuous), input-threshold law. Status-byte emission stays if the shim is used. The constants hash changes, so era fingerprint. 3 ed | Replace the charger with a bidirectional battery-converter model plus a current-commanded FC source plus a reversible motor node. 8-12 ed |
| `hil_electrical.py` 543 `ETA_CHG = 0.88`; `charger_power.py` 50 `ETA_CHG_DEFAULT = 0.88` | charger efficiency | New eta (TODO(calibrate) from the bench round). Era key `eta_chg` already exists, so the change is parametric. 0.5 ed | converter eta map |
| `run_hil_suite.py` (301), 278 `AG105_GENSTAT_MASK`; legs: charge-cruise, charge-to-full, charge-regen, charge-fault, mppt-tracking, regen-harvest-true, ems-ftp75c-{sdp,mpc,dp,socband,5050}, alpha legs, `charge_edges_safe` | charge-window scoring | Re-pin bands from a campaign. mppt-tracking re-specced. charge-fault needs the new fault injection. 3 ed + 1 campaign | Most charge / regen / share legs re-specced. 8 ed + campaigns |
| `gen_dp_ems_table.py` (`step_charge`, `charge_mask`, eta header), `sdp_ems_solver.py` (`ETA_CHG_MODEL`, `CHARGE_I_CEILING_A` 0.8, `alpha_charge_edge`), `mpc_ems.py`, `sdp_alpha_sweep.py` (`_walk_csv_ag105_status`), `ems_walk.py` (no settle/ramp), `governor_model.py` (F1 charge gate mirror), `dp_results_db.py` (eta_chg era key) | charge economics | New eta + ceiling, then re-solve tables / policies (sdp_policy_v6+), dp_db re-solves, alpha. Mostly parametric. 3-4 ed + compute | New topology in DP/SDP/governor (one bus former + one current source; charge = I_fc surplus). 10-15 ed |
| tests: `test_hil_plant_sim.py` (401 mentions), `test_run_hil_suite.py` (236), `test_sdp_ems_solver.py`, `test_gen_dp_ems_table.py`, `test_dp_results_db.py`, `test_ems_walk.py`, `test_mpc_ems.py`, `test_governor_*_equivalence.py` | | re-pin. 2-3 ed | large rewrite |
| `decode_benchlog.py` / BLG v9 | **no charger field in the BLG** | none | BLG v10 for converter fields |
| `rosbag_analysis/check_regen.py`, `check_sdp.py` | charger_status prints / Ag105 text | text only. 0.25 ed | rewrite |
| docs: PLAN.md section 3 (232-406), 6b, 9b; HIL_PLANT.md 4.6 (1528-1760, 91 Ag105 mentions); HIL_MODE.md frames; HIL_SCENARIOS.md (54); HIL_USER_MANUAL.md (37); CLAUDE.md sections 1/3 + a new bodge record | | 1.5 ed | 3 ed + CLAUDE.md sections 2/3/7 rewritten |

## 4. Pi bridge / EMS (references/EMS/Pi_2026-11-03)
- `teensy_bridge_node_2026-10-31A.py`: `T2P_SIZE == 58` assert (line 86). It passes `charger_status` through as `/vehicle_state[12]` (line 53) and `I_charge` as [3]. The EKF SoC treats I_charge as BATTERY-side (lines 217-244, `soc_i_charge_bus_side`).
  - Path A with shim: 0 changes, but verify the new chip's current is battery-side (BQ257xx IBAT is battery-side per the note's framing; UNVERIFIED).
  - With v5: about 1 ed (planned anyway for v38).
- EMS nodes (`simple_ems_node_*`, `sdp_ems_node_*`) only index `[12]`; they make no Table-6 decode. `charge_goal` stays the intent.
- Path B: bridge v6 decode (2 ed). The EMS output changes from share + charge_goal to an I_fc reference + charge budget, and the SDP policy and nodes are redone (5-8 ed).

## 5. Reusable (both paths unless noted)
- **G1** source-current stop, **G2** unaccounted-power stop (bus-side INA253 sum vs credited charge power), **G4** reboot-only trip latch, and the "drop REGEN first, no serial before pins" ordering: reuse verbatim (Path A); concept only (Path B bring-up).
- **G5 `AG105_VBATN_ISOLATED` gate** plus its runtime flag: reuse as a "replacement fitted and bench-proven" gate that defaults CLOSED on real boards. It still holds REGEN LOW in Run until opened.
- **`chargerHasPower()` / lazy power-gated config / `ag105Configured` re-arm / stale-clear on power loss** (Path A). Even more necessary with volatile registers.
- **FC_CHARGE guard `assertFcChargeEnable()`, F1 disarm-before-open, conduction gate, UV backoff** (Path A, unchanged topology).
- **MPPT threshold manager concept**: set the input threshold from the observed V_chg minimum, then verify by readback. Path A ports it to a single volatile VINDPM-class write. The EPROM budget and ratchet are deleted.
- J-session skeleton: preconditions, stops, status/summary prints, refusal helper, X/Q/fault abandon (Path A).
- Pin 38 V_chg / pin 39 V_rgn dividers, the HIL injection-frame slots, the eta_chg era-key plumbing in tooling.

## 6. Effort summary (engineer-days; bench / HIL wall time excluded)

| Work package | Path A (new charger IC on Ag105 pads) | Path B (re-spin, bidirectional converter) |
|---|---|---|
| Minimal bench driver (State-98 session, I2C driver, guards, watchdog keepalive, tests) | **4-6** | **6-10** (converter bring-up session, bipolar sense) |
| Full Run-state integration (chargingControl, readiness, faults, R3 interlock v38, State 99, all 3 test targets green) | **8-12** | **25-40** (share loop to I_fc command with operator exception, charge-budget allocator, MOT_PWR redesign, CC/CV, faults, new suite) |
| HIL / EMS model update (plant, eta, suite re-pins, DP/SDP/MPC re-solve, docs) | **7-10** + 1 campaign | **25-35** + several campaigns |
| Pi bridge | **0** (status shim) / **1** (v5, already planned) | **7-10** (v6 decode + EMS command redesign) |
| **Total** | **~20-29** | **~63-95** |

## 7. Decision-relevant notes
- **Protocol:** Path A forces no bump. I recommend shipping the approved v5 with a `charger_type` and `charger_flags` byte so bags self-identify the charger era; otherwise offset 51 silently changes source. Path B forces a bump.
- **Polarity hazard (Path A):** pin 5's EN polarity on the candidate EVM is not fail-safe (note section 5.1). The firmware default in `setup()` and the 10k pull-down bodge must yield "charger off" during MCU reset. Add a pull-up or a jumper change. Firmware cannot fix a high-Z window alone.
- **Unchanged hazards (Path A):** the bus can still feed the charger through D-MT-EN + D-BC-RG, so R3 and the 3-layer interlock (planning section 3.3) remain mandatory. Path B removes R3 by construction.
- **Pre-existing tooling failures unrelated to this work:** `test_dp_results_db` (75 vs 101) and `hil_replay_suite.TARGET_FW_VERSION` still at 28.
