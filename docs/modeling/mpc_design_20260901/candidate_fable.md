# Governor-aware model-predictive EMS: design document (Fable candidate)

Date: 2026-09-01. Scope: a deterministic receding-horizon energy-management strategy
with drive-cycle preview, and a stochastic variant driven by the demand TPM, both
registered as EMS strategies in the HIL suite beside `soc-band`, `sdp-v3` and
`dp-replay`. This document is a design; no repository file was changed. Every number
cited below was recomputed from the sources named beside it.

## 0. Summary of design choices

1. **State** is the pack SoC (plant truth, sim-only as for `soc-band`/`sdp-v3`) plus a
   **shadow governor**: a `governor_model.GovernorModel` instance ticked at 1 kHz inside
   the strategy and corrected each 50 Hz feedback tick from the observed MDAC ratio.
2. **Controls** are the 15-point share ladder {0.15, 0.20, ..., 0.85} (the SDP's 21-point
   ladder clipped to the hardware envelope) and a binary `charge_goal` under the 8 s
   minimum-dwell latch. Decisions are taken at 1 Hz over a 20-stage horizon.
3. **Prediction model** is two-timescale: the actual `GovernorModel` is rolled at 1 kHz for
   the first stage of every first-move candidate and across every mode-transition stage
   of the preview; a **stage map** derived from the same constants covers the remaining
   stages. The pack, demand and hydrogen terms are stdlib ports of
   `gen_dp_ems_table.build_demand()`, `step_discharge()` and `step_charge()` (η_chg era).
4. **Optimizer** is a horizon dynamic program on a local SoC grid (61 nodes, 1e-4 SoC) with
   the charge control enumerated as three window candidates; the first move is then
   re-scored by the exact 1 kHz roll. Measured cost: 65 ms typical, 350 ms worst case, on
   this machine in pure Python.
5. **Terminal cost** is a Huber penalty on SoC deviation whose linear slope is the SDP's own
   shadow price α/(1−γ) converted to the proxy basis (4.793 g/SoC); the SDP value
   function is a flagged option that needs a solver change.
6. **Real time** is met by computing the plan in a worker process; the 50 Hz strategy call
   applies the next move of the latest plan in O(1) and never blocks the 1 kHz loop.
7. **Stochastic variant** replaces the preview with the TPM's conditional-mean demand
   path (certainty-equivalent) and tightens the OC constraint with the TPM row's 90 %
   quantile; scenario trees are an offline-only option.
8. **Evaluation** adds two frontier tuples (`cycle61-mpc`, `ftp75-mpc`), phase-free
   checks only, and states up front that under the linear hydrogen proxy the eq-H2 metric
   cannot separate charge-free strategies by more than the pack-loss and governor-clip
   residuals; the convex fuel-cell map is the only route to a non-degenerate ranking.

## 1. Problem statement

### 1.1 State, controls, decision rate

The controlled state is the pack state of charge, `soc`, read from `fb["soc"]` (plant
truth; not in `FB_TELEMETRY_EQUIV_KEYS`, `tools/hil_plant_sim.py:2504`). The strategy is
therefore sim-only for exactly the reason `soc-band` and `sdp-v3` are, and a Pi port
needs the same V_batt SoC estimator they need.

The delivery state is the firmware share governor's memory: applied ratio `r_prev`,
`closed_loop_mode`/`closed_loop_run`, the load filter `filt_total`, the two dark-channel
flags, the handoff dwell, the isolation and setpoint-cut claims, and the two switch
rise stamps (`GovernorState`, `tools/governor_model.py:234-279`). This state is what
makes a commanded share and a delivered share differ, and it is carried explicitly.

The controls are the two energy fields of the 22-byte command packet:
`power_share_setpoint` on the ladder `S = {0.15 + 0.05 k, k = 0..14}` and `charge_goal`
in {0, 1}. The ladder is the SDP's 21-step 0.05 ladder (`SHARE_LADDER_N = 21`,
`tools/sdp_ems_solver.py:448`) restricted to `[SOC_BAND_SHARE_MIN, SOC_BAND_SHARE_MAX]`
= [0.15, 0.85] (`tools/hil_plant_sim.py:2964-2965`), so the MPC and `sdp-v3` command the
same envelope and the comparison between them is like for like. `mode_cmd` and
`v_setpoint` are host-side script exactly as in every registered strategy.

Decisions are taken every `DECISION_DT_S = 1.0` s, the SDP's own stage length and the
TPM's `dt`. The 50 Hz `PiCommander` call holds the two energy fields between decisions
as `SdpStrategy.__call__` does (`tools/hil_plant_sim.py:4907-4920`).

### 1.2 Preview source

In the simulator the demand is a deterministic function of the scenario's
`ems_v_profile` and its drain schedule. The strategy obtains the profile in
`bind_scenario(scenario, meta)`, the same hook `DpReplayStrategy` and `SdpStrategy`
implement (`tools/hil_plant_sim.py:3404`, `:4590`), and builds the preview arrays once
with a stdlib port of `gen_dp_ems_table.build_demand()` at the DP stage length
`DP_STAGE_DT_S = 0.1` s. The preview is then indexed by the run clock `t`. The strategy
reads no future from the plant; it reads the scenario script, which is host-side data
and not feedback (the MODE A block, `tools/hil_plant_sim.py:2326`).

Two preview qualities are distinguished. The **exact preview** is the scenario's own
profile, which is the deterministic-MPC assumption. The **biased preview** multiplies the
modelled demand by a slowly filtered ratio of measured to modelled bus power,
`c = P_meas/P_model` with a 10 s EMA, where `P_meas = V_bus (I_fc + I_batt) − V_bus I_charge`
subtracts the charger's own draw as `SdpStrategy.decide()` does. The FTP-75 measurement
runs +2.6 % hot against the model (`tools/hil_plant_sim.py:6290` block), so the bias
observer is expected to settle near 1.026. It ships default-off (`preview_bias: false`)
so the first campaign attributes every deviation to the model, not to an adaptive term.

On a vehicle the exact preview maps to a route preview: a speed profile from map data,
speed limits and traffic state, passed through the same mechanics
(`M_EFF`, `F_COULOMB`, `B_EFF`, `tools/hil_plant_sim.py:301-305`). Where no route preview
exists the TPM supplies the demand statistics instead, which is the stochastic variant
of Section 4.

### 1.3 Constraints

Table 1 lists the constraints the optimizer enforces and where each comes from.

| Constraint | Form in the optimizer | Source |
|---|---|---|
| FC overcurrent | delivered `I_fc,k ≤ 0.85 × 1.4 A = 1.19 A` at every previewed stage | `LIMIT_I_FC_MAX 1.4f` (`.ino:1375`); headroom `DP_CHARGE_FC_MARGIN = 0.85` reused for the share axis (`gen_dp_ems_table.py:291`) |
| BT overcurrent | delivered `I_batt,k ≤ 0.85 × 3.0 A = 2.55 A` | `LIMIT_I_BT_MAX 3.0f` (`.ino:1426`); never binds at rig loads (peak source total 1.61 A on FTP-75) |
| SoC window | grid clamp to `[target − 0.05, target + 0.05]` with a clamp counter | `SOC_GRID_MIN/MAX` 0.55/0.65 about target 0.60 (`sdp_ems_solver.py:435-437`), applied SoC0-relative |
| Charge forbidden under acceleration | charge admissible only where cruise ∧ FC budget ∧ Run window, all on the preview | operator ruling (b) 2026-08-30 as encoded by `charge_mask()` (`gen_dp_ems_table.py:547-560`) and `charge_forbidden_bins()` (`sdp_ems_solver.py:714`) |
| FC_CHARGE / REGEN mutual exclusion | never assert `charge_goal` on a braking stage; braking stages have `p_mech = 0` in the preview and fail the cruise test | firmware `assertFcChargeEnable()` and `chargingControl()`; the cruise mask makes the exclusion hold by construction |
| Charge minimum dwell | a rising edge commits 8 stages; early drop on fault or on `|v − v_ref| > 0.10 m/s` | `SDP_CHG_MIN_DWELL_S = 8.0`, `SDP_CHG_CRUISE_DELTA_MPS = 0.10`, `SDP_CHG_ABORT_FAULT_MASK` (`hil_plant_sim.py:3982-3999`) |
| Share cut band | commanded share never outside [0.15, 0.85] | `updateShareSetpointCutoff()` opens a bus switch for an out-of-band setpoint; the ladder excludes both rails |

The charge admissibility test is the union of the DP's per-stage mask and the SDP's
bin rule. The bin rule forbids bins 11-24 of the 0-25 W consumer map, i.e. modelled
demand above 11.0 W, from the TPM's dwell quantile (`CHARGE_QUANTILE = 0.90`,
`sdp_ems_solver.py:468`, row occupancy in `TPM_dt1_hil.mat.provenance.json`). The DP mask
adds the cruise slope test and the single-source FC budget
`P_dem/V_bus + i_chg,bus ≤ 1.19 A`, where `i_chg,bus` is the η-era bus draw of Section 2.5.

### 1.4 Objective, and what a linear proxy can and cannot rank

The stage cost is the student's online proxy applied to stack power, as ruled. With
`P_fc,bus` the fuel-cell channel's bus power, the hydrogen rate is

    W_H2 = (P_fc,bus / ETA_BOOST) / (η_fc Q_LHV),   η_fc = 0.4, Q_LHV = 120000 J/g,

which is `ems_walk.h2_proxy_gps()` (`tools/ems_walk.py:91-102`) evaluated on
`p_fc_bus / sim.ETA_BOOST` as the walk does (`:502`). The proxy constant is
`k_p = 1/(0.85 × 0.4 × 120000) = 2.451e-5 g/J` of bus energy. The plant's own
`H2_GFC_DC_GAIN_GPS_PER_W = 1.7638e-5 g/J` of stack energy implies η_fc = 0.4725, so the
proxy over-reads the plant metric by 2.0833/1.7638 = 1.181 at steady state. That ratio is
a constant and does not move any argmin.

The PhD student's own governor script states the consequence of a linear map in one
sentence: with a constant-efficiency map the SoC-corrected fuel is an algebraic identity
and no strategy can differ from another on fuel economy
(`references/EMS/SDP_EnergyManagement_Governor2.m`, `h2_coefficients()`, lines 529-540).
On this rig the identity is broken only by three residuals: the pack series-resistance
loss (`BATT_RS_NOM = 0.040 Ω` per cell, `hil_electrical.py:815`; at 1.7 A pack current
the loss is 0.23 W against 13 W delivered, 1.8 %), the governor's delivery clip (the
minority floor `SHARE_MINORITY_I_MIN_A = 0.30 A` pins the delivered split toward 0.5 as
the source total falls to the 0.60 A entry threshold), and the charge lever, which prices
SoC differently from share shifting. Campaign evidence agrees: `sdp-v3`, which never
charges, landed within 0.99 % of the ΔSoC-matched DP bound while `soc-band`, which
charges through a 13 s window, landed 10.80 % above it (CLAUDE.md addendum 2026-09-01e).

Two consequences bind this design. First, the deterministic MPC's expected eq-H2 result
against `sdp-v3` is a tie within the λ band unless charging is admitted; Section 5.4
states this before any campaign reads a 1.0000. Second, the objective needs a non-linear
term for the preview to be worth anything on the hydrogen axis; the convex map of
Section 2.6 is that term and is the flagged option. Both are design facts about the
metric, and neither is a defect of the controller.

## 2. Prediction model

### 2.1 Reused functions

Table 2 lists what is reused verbatim, what is ported to stdlib, and why.

| Need | Reused as | Notes |
|---|---|---|
| Governor tick | `governor_model.GovernorModel.step()`, `.delivered_share()`, `.reset()` | stdlib; the authority for every per-tick constant (`GOV_CONST`, `:163-192`) |
| Governor seed from observation | `governor_model.r_from_codes()` | the replay harness's `seed_from_first_codes` precedent (`:1051-1058`) |
| Demand preview | stdlib port of `gen_dp_ems_table.build_demand()` (`:476-544`) and `scenario_drain_a()` (`:442-473`) | numpy is not allowed in the runtime path; a test asserts equality to the numpy original at 1e-12 on every registered `ems-*` scenario |
| Pack model | `hil_electrical.BatterySource.ocv()`/`.rs()` (stdlib, `:858-861`) via a scalar port of `pack_current_from_bus_power()` (`gen_dp_ems_table.py:410-425`) and `pack_charge_voltage()` (working tree, D12) | the same terms the DP bound and the walk use, so the MPC's SoC prediction is comparable with theirs |
| Charger bus draw | `tools/charger_power.py` (working tree, tonight's WP-1B1) | `charger_bus_current_a()`, `charger_bus_power_w()`; `eta_chg = 0.88` selects the new era |
| Hydrogen proxy | `ems_walk.h2_proxy_gps()` | imported; `ems_walk` imports only `governor_model` at module level (`:61`) |
| Charge dwell semantics | re-implemented with the `SDP_CHG_*` constants imported from `hil_plant_sim` | a test drives both `SdpStrategy.charge_hold_status()` and the MPC latch through one scripted sequence and asserts identical exits |
| Offline evaluation | `ems_walk.walk()` with the MPC in inline mode; `gen_dp_ems_table.prepare_problem()`/`solve_matched()` | Section 5 |
| Stochastic demand | `sdp_ems_solver.load_tpm()`/`load_sidecar()` are numpy; the MPC reads the TPM matrix from the SDP artifact's carried `tpm` block or a stdlib `.json` export | Section 4 |

### 2.2 Two-timescale structure

A 1 Hz decision cannot enumerate control sequences with a 1 kHz roll inside every
transition: one 20 s roll costs 20 000 ticks × 3.28 µs = 66 ms (measured, Section 2.7),
and an exhaustive 3-block search over 15 ladder points is 3375 sequences, or 223 s. The
governor's memory matters only at mode transitions, so the model is split.

1. **Exact roll, first stage.** For each first-move candidate the shadow governor is
   copied and stepped for 1000 ticks against the 0.1 s preview held as a zero-order hold,
   with the switch states the firmware's other owners would write (the `ems_walk.walk()`
   re-assertion rule, `:443-471`). The stage-averaged delivered share, the delivered
   currents and the end-of-stage `GovernorState` are the result.
2. **Exact roll, transition stages.** The preview is scanned once per decision for
   stages in which the source total crosses 0.60 A upward or 0.55 A downward, or in which
   a candidate charge window opens or closes. For each such stage the roll is run once
   per ladder point with `r_prev` set to the closed-loop delivered ratio for that point,
   which assumes the command is held across the transition. The result is a per-stage
   table `r_hold[s]`, the ratio the governor leaves at drop-out under command `s`.
3. **Stage map, all other stages.** A closed-form map replaces the roll where the
   governor has no transient (Section 2.3).

The transition roll is what the walks lacked. The `ems-sdp-cross` limit cycle was walked
5.7× wrong because the walk applied the closed-loop clip at a 0.355 A cruise where the
firmware holds its last split (`docs/HIL_SCENARIOS.md`, "THE RETIRED CHECK"). The
measured held split there was 0.1656 against a commanded 0.85, which no closed-form clip
reproduces because the ratio's value at drop-out depends on how fast the load fell
through the 5 %-per-tick EMA and the 0.02-per-tick slew. Only the tick model carries that.

### 2.3 Stage map

Let `I_k` be the previewed source total at stage k and `s` the commanded share. The
delivered share `d_k(s)` is defined by mode:

- **Closed loop** (`I_k ≥ 0.60 A` after entry, until `< 0.55 A`): `d_k = clip(s, lo_k, 1 − lo_k)`
  with `lo_k = min(0.5, 0.30 / I_k)`, the minority governor clip (`governor_model.py:847-854`).
  The slew (0.02 per tick in full mode) traverses the whole band in 35 ms, and the
  handoff mode's 0.002 per tick traverses it in 350 ms; both are shorter than a stage and
  are absorbed by the exact roll at the transition stage.
- **Open-loop hold** (`I_k < 0.55 A`, below `SHARE_I_TOT_MIN_A` excluded): `d_k = r_hold`,
  the ratio the transition roll produced; the command is inert (`MODE_OPEN_HOLD`,
  `governor_model.py:811-817`).
- **Minimum-load freeze** (`I_k < 0.075 A`): as hold; unreachable with `I_AUX_A = 0.15 A`.
- **FC-charge window**: BT is off the bus, the traction share delivered is 1.0, the FC
  channel also carries the charger, and the ratio winds onto `DROOP_R_MIN = 0.15`
  (topology-pinned integrator, `governor_model.py:882-892`). The window-close stage is a
  transition stage and is rolled exactly, which is where the post-window recovery from
  0.15 lives. `ems-sdp-braking` is outside the governor model's licensed fidelity
  (`governor_model.py:112-118`); the MPC therefore carries a `TODO(calibrate)` note that
  its post-window prediction is unvalidated on braking profiles, and Section 5 keeps the
  first MPC scenarios off braking stimuli.

Two properties of the closed-loop clip are worth stating because they shape the results.
At `I_k = 0.60 A` the clip is `[0.5, 0.5]`: every in-band command delivers 0.5 at the
entry threshold, so a slow ramp-out always leaves `r_hold ≈ 0.5` and a fast load step is
the only way to hold a biased split. On the `ems-sdp` plateau (`I_tot` 1.4866 A measured)
the clip is `[0.202, 0.798]`, which is why the commanded 0.85 delivers 1.1866 A rather
than 1.264 A. The stage map reproduces both; a test compares the map against the 1 kHz
roll on every registered `ems-*` scenario's governed walk trace and requires a
stage-averaged delivered-share RMS below 0.01 outside transition stages.

### 2.4 Shadow governor

The strategy owns one `GovernorModel` ticked at 1 kHz between feedback samples, with the
50 Hz feedback held. Each feedback sample corrects it: `r_prev` is overwritten by
`r_from_codes(obs.mdac_fc, obs.mdac_bt)` when both words are present (they are in the
observation frame and the CSV, `tools/hil_plant_sim.py:905`, `:8647`), the switch beliefs
by the `switch` word, and `filt_total` is left to its own dynamics because the feedback
currents drive it. The mode flags are not observable and are left to the model; a
disagreement between the model's mode and the observed ratio motion is counted as a
`shadow_mode_mismatch` diagnostic and reported in the exit summary. This is the observer
whose absence made the earlier walks open-loop.

Cost: 1000 ticks/s × 2.45-3.28 µs = 2.5-3.3 ms per second of run, in the strategy
process. That is 0.3 % of the loop budget and needs no worker.

### 2.5 Pack, charger and SoC model

The discharge step per stage of length Δt is the DP's D6(a) referral, scalar:

    P_bt = (1 − d) P_dem,   i_pack = P_bt / (ETA_BOOST · v1),   v1 = max(OCV(soc) − i0 rs(soc), 1),
    soc' = soc − i_pack Δt / C_As,   C_As = 5.0 Ah × 3600 = 18000 A·s.

The charge step delivers `chg_a` into the pack and bills the fuel cell for the bus draw

    P_in = V_pack(soc, chg_a) · chg_a / η_chg,   η_chg = 0.88,   V_pack = OCV + chg_a · rs,

which is D12 of the working-tree `gen_dp_ems_table.py` and `charger_power.py`. The pack
receives `chg_a` in both eras; only the fuel cell's bill moves. `chg_a` is the scenario's
`chg_i_ceiling_a` through `sim.dp_chg_ceiling_a(meta)` (0.8 A on every EMS leg that
declares it).

The η-era lever arithmetic follows. The SDP's model levers are `L_share = 0.4505` and
`L_chg = 0.2090` SoC/g (`sdp_policy_v3.json`, `alpha.levers_soc_per_g`). With the charger
billed at `V_pack/η_chg` instead of `V_bus`, the charge lever becomes
`L_chg' = L_chg × V_bus × η_chg / V_pack = 0.2090 × 15.95 × 0.88 / 7.4 = 0.3964` SoC/g at the
flat 7.4 V, or 0.3732 SoC/g at the 7.86 V terminal voltage the D12 note quotes for SoC 0.7.
Both exceed the v3 artifact's admission threshold 0.30682 SoC/g, so an η-era SDP solved
with the v3 α admits charging; the two-sided re-derivation gives
`α = 0.05/sqrt(0.4505 × 0.3964) = 0.1183`. Tonight's parallel solve owns that decision;
the MPC does not depend on it because its charge decision is priced per stage (Section 3.4).

### 2.6 Hydrogen proxy and the convex option

The default stage cost is the linear proxy of Section 1.4. The flagged option is the
student's convex map `W_H2(P) = a0 + a1 P + a2 P²` with `a2 = a0/P_peak²` and
`a1 = (P_peak/(η_peak Q_LHV) − 2 a0)/P_peak`
(`SDP_EnergyManagement_Governor2.m:529-580`). The three parameters are stack quantities
this rig has not measured: `a0` (balance-of-plant draw at idle), `P_peak`, `η_peak`. The
option ships with the structure, a `TODO(calibrate)` on all three, and a refusal to run
unless a scenario or CLI supplies them; no rig-scale defaults are invented. Under the
convex map the optimizer of Section 3 is unchanged, since it evaluates the stage cost
per (node, control) and does not assume linearity.

### 2.7 Cost per decision, measured

Timings were measured in `.venv_hil` (Python 3.14.5) with a scratchpad script:

- `GovernorModel.step()` + `delivered_share()`: **3.28 µs** per closed-loop tick, **2.45 µs**
  per hold tick; a 1000-tick stage roll is **3.3 ms**.
- One tail-DP stage evaluation (pack referral with OCV interpolation, stage cost, linear
  interpolation of the cost-to-go): **0.71 µs**.
- `copy.deepcopy(GovernorState)`: 7.6 µs; `dataclasses.replace` snapshot: 4.7 µs.

Section 3.6 assembles these into the per-decision budget.

## 3. Optimizer

### 3.1 Horizon

`N = 20` stages of 1 s. The SDP's discount `γ = 0.95` per 1 s stage gives an effective
horizon `1/(1 − γ) = 20 s`, so the deterministic MPC looks exactly as far as the SDP
weights. The horizon also covers one full 8 s charge dwell plus 12 s of consequence.
Over 20 s at the `ems-sdp` plateau the SoC moves at most
`1.71 A × 20 s / 18000 A·s = 1.9e-3`, and a 0.8 A charge window adds 8.9e-4; the local
SoC grid of Section 3.3 spans ±3e-3 with margin. The tail is not discounted inside the
horizon; the terminal cost carries `γ^N = 0.358` only in the `sdp-j` mode where it must.

### 3.2 Control parametrization

Share: the 15-point ladder at every stage, no move blocking. The tail DP makes blocking
unnecessary at this cost (Section 3.6), and blocking would hide the preview's value at
segment boundaries, which is the one place a preview matters.

Charge: three candidates per decision, evaluated as separate tail DPs with the charge
stages fixed: (i) no charge in the horizon; (ii) charge from the first stage for exactly
8 stages; (iii) charge from the first stage until the admissible segment ends. A window
that starts later in the horizon is not enumerated; the receding horizon re-evaluates
"start now" every second, so a later start is reached when its time comes. While a latch
is in force the charge stages are fixed by the latch and only candidate (i) with the
latched prefix is solved. A candidate whose first stage is inadmissible is skipped.

### 3.3 Solver

The tail is a backward dynamic program over stages 2..N on a local SoC grid of 61 nodes
at 1e-4 SoC centred on the current SoC. Each stage evaluates 15 share controls per node
with the stage map of Section 2.3, interpolates the cost-to-go linearly at the continuous
successor (the D1 rule of both existing solvers), and clamps a successor outside the
window to the edge with a counter. Infeasible controls (Table 1) carry `+inf`. The
result is `J_2(soc)` on the grid for each charge candidate.

The first stage is then scored exactly: for each ladder point and each live charge
candidate the shadow governor copy is rolled for 1000 ticks (Section 2.2), the stage cost
is evaluated on the delivered currents, and `J_2` is interpolated at the rolled SoC. The
argmin over (share, charge candidate) is the decision. Ties resolve to the smallest share
and to no charge, the SDP's D8 rule, so an indifferent state never charges by accident.

The full plan (the argmin path through the tail DP) is retained for the shifted-plan
fallback of Section 3.5 and for the `mpc_share_delivered_pred` column of Section 6.

### 3.4 Terminal cost

Three modes, selected by `terminal`:

- `huber` (default). With `Δ = soc_N − soc_target`, `δ = SOC_BAND_HALF = 0.0015` and slope
  `ρ`, the cost is `ρ Δ²/(2δ)` for `|Δ| ≤ δ` and `ρ(|Δ| − δ/2)` outside. The slope is the
  SDP's shadow price converted to the proxy basis:
  `ρ = κ α/(1 − γ) = 1.4706 × 0.1629624/0.05 = 4.793 g/SoC`, where
  `κ = (1/(0.85 × 0.4))/(1/0.5) = 1.4706` converts the SDP's bus-side η 0.5 basis to the
  stack-side η 0.4 proxy. Inside the band the marginal price falls below the share
  lever's cost (3.265 g/SoC in the proxy basis, `κ/L_share`) at `|Δ| < 0.68 δ`, so the plan
  lets SoC drift inside the band and rails outside it; the band constant is `soc-band`'s
  own, and the price is the SDP's own. A linear penalty alone makes the plan bang-bang
  about the target at 1 Hz, which is the SDP's behaviour with its grid dead band removed.
- `linear`: the SDP's `α|Δ|/(1 − γ)` scaled by κ, for a like-for-like check against the SDP.
- `sdp-j`: `κ γ^N EJ(soc_N, b_N)` with `EJ = J · TPMᵀ` interpolated on SoC, `b_N` the last
  previewed bin. This requires the artifact to carry `J`, which `render_policy_json()`
  does not emit (`sdp_ems_solver.py`, the `solver` block holds only convergence fields).
  Emitting a `value` block outside the `policy` block leaves the policy sha unchanged and
  moves the file sha; it is listed as an optional step. Its payoff is a regression anchor:
  with `N = 1`, the SDP's stage model and the current bin in place of the preview, the
  MPC's argmin equals `greedy_policy()` cell for cell.

The SoC target is the captured `soc0` (SoC0-relative regulation, the `SdpStrategy`
convention), so every EMS leg regulates about the same point.

### 3.5 Warm start, fallback and the real-time argument

The 1 kHz plant loop cannot absorb a 65-350 ms synchronous call. `HIL_STALE_MS` is 50 ms
and `HIL_ZERO_MS` is 250 ms (`tools/hil_plant_sim.py:801`, `:2467`): a stall between them
freezes the board's injected sensors for its duration, and the loop's drift correction
spins catch-up ticks below a 0.25 s overrun (`:9538-9547`). A 150 ms decision inside the
50 Hz call would therefore corrupt every stage boundary of every MPC run.

The plan is computed in a worker (`multiprocessing`, spawn; a `threading` mode exists
for environments without a second core, at the cost of GIL contention with the hi-fi
engine's wall-clock-adaptive substeps; an `inline` mode exists for the offline walk and
for tests). At each decision boundary the strategy sends a picklable snapshot (SoC, the
`GovernorState`, the decision index, the latch state, the preview bias) and applies the
next move of the most recent plan it holds. If the worker's reply for the current
boundary has not arrived, the shifted plan from the previous boundary supplies the move
and `mpc_plan_age_s` records the age; a plan older than `MPC_PLAN_MAX_AGE_S = 3.0 s`
falls back to the SDP-parity rule (rail toward FC below target, battery rail above) and
counts a `late_decision`. Warm start is the shifted plan as the enumeration order's
first candidate; the DP itself needs none.

### 3.6 Budget arithmetic

Per decision, worst case, from the Section 2.7 timings:

- Tail DP: 61 nodes × 19 stages × 16 controls = 18 544 evaluations × 0.71 µs = **13.2 ms**
  per charge candidate; three candidates = **40 ms**.
- First-stage exact roll: 15 ladder points × 2 charge states × 3.3 ms = **99 ms**.
- Transition rolls: ≤ 4 transition stages × 15 ladder points × 3.3 ms = **198 ms**.
- Snapshot, pickling and pipe: < 5 ms.

Worst case ≈ **350 ms**; typical (one transition, charge inadmissible) ≈ 13 + 49 + 50 =
**112 ms**; a steady closed-loop stage with no transition ≈ **65 ms**. All are under the
1 s decision period and the 0.5 s assertion the timing test carries. The shadow governor
adds 3.3 ms per second in the strategy process. The worker process imports
`hil_plant_sim` once at bind (no I/O at import, `:4436`), about 0.5 s before the run's
first decision at `EMS_RUN_ENTRY_S = 3.0 s`.

### 3.7 Regression anchors

1. Stdlib demand preview equals `gen_dp_ems_table.build_demand()` to 1e-12 on every
   registered `ems-*` scenario, era overrides included.
2. Stdlib pack step equals `step_discharge()`/`step_charge()` to 1e-12, both charger eras.
3. Stage map versus 1 kHz roll: RMS < 0.01 outside transition stages, on the governed walk
   traces of every `ems-*` scenario.
4. MPC latch equals `SdpStrategy.charge_hold_status()` on a scripted sequence covering
   active, expired, fault drop and cruise-exit drop.
5. Monotonicity: raising `ρ` never lowers the first-move share; charge chosen only where
   the mask admits; no plan violates Table 1; a plan under `linear` with `N = 1` and a
   constant preview reproduces the SDP's bang-bang branch on both sides of the target.
6. Timing: median decision < 0.2 s and maximum < 0.5 s over a 61 s inline walk.
7. Optional (`sdp-j` with the emitted `J`): cell-for-cell equality with `sdp_policy_v3.json`.

## 4. Stochastic variant

The TPM `TPM_dt1_hil.mat` is 25 × 25 at 1 s (`--hil` preset: truncated native spans,
boundary transitions excluded, self-transition for empty rows; diagonal mass 0.762,
211 non-zeros, sidecar `results`). It is unitless; the consumer map is the SDP's
`[0, 25] W` (D11). The variant replaces the exact preview with the TPM's conditional-mean
path: with `b0` the current bin from the self-load-subtracted measured demand and `p` the
bin-centre power vector,

    P̂_k = e_{b0} · TPM^k · p,   k = 1..N,

a 25-vector times a 25 × 25 matrix twenty times, under 10 ms in pure Python. The
deterministic solver then runs unchanged on `P̂`; this is certainty-equivalent MPC.

The constraint side is not certainty-equivalent. The OC bound at stage k is evaluated
against the 90 % quantile of the k-step conditional demand distribution, so the plan
keeps the FC channel under 1.19 A with 90 % probability rather than in the mean; the
quantile is read off the same power vector. This is the cheap part of a chance
constraint and is where the TPM's information is worth most on this rig, because
`LIMIT_I_FC_MAX` is the binding limit at cycle peaks and an OC latch ends a run.

A scenario tree (branching over the three most probable successor bins at stages 1 and
2, nine leaves, nine tail DPs) is implemented behind `--mpc-tree` for offline study only:
at 9 × 40 ms it fits the worker budget, but it has no live stimulus to be evaluated on,
because every simulator scenario is a deterministic profile and not a draw from the TPM.
Min-max is not implemented; the 90 % quantile bound is the robust element.

What changes against the deterministic variant: the preview source and the OC
tightening; nothing in the optimizer, the stage map, the latch or the terminal cost. The
live evaluation of the variant therefore measures the loss of replacing an exact preview
by a Markov mean on a deterministic cycle, not stochastic performance, and Section 5.4
says so. The stochastic variant is second in order, as ruled, and ships after the
deterministic variant's first campaign.

## 5. Evaluation plan

### 5.1 Offline walk

`ems_walk.walk("mpc-det", scenario, strategy_kwargs={"worker": "inline"})` on `ems-sdp`,
`ems-ftp75-sdp`'s stimulus (a derived `ems-ftp75-mpc` entry) and `ems-soc-band`, against
`soc-band`, `sdp-v3`, an `sdp-v4` if tonight's η-era artifact ships, and `dp-replay`.
The walk's numbers are reported as h2 (Gfc, physical), h2 proxy, ΔSoC and eq-H2 at
λ = 0.41, and as the governor mode census per segment.

One structural caveat is stated with the numbers. The MPC's prediction model is the
walk's own plant, so the walk cannot evaluate the MPC; it can only check that the
strategy is plumbed and that its plan is self-consistent (the inverse-crime condition).
The live campaign against the hi-fi plant is the evaluation. The walk still supplies the
provisional bands every new scenario needs.

### 5.2 Live scenarios and checks

Two scenarios in the first round, both derived entries sharing an existing stimulus
object, so the frontier's stimulus-coherence precondition passes by construction:

- `ems-mpc` (61 s, `electrical: any`, `ems: "mpc-det"`): `ems-soc-band`'s
  `ems_v_profile` object, drain and `chg_i_ceiling_a` 0.8, the three-way comparison's
  bit-identical load (the `SOC_BAND_DRAIN_SCENARIOS` rule needs the new name added to
  both the simulator's branch and `gen_dp_ems_table.SOC_BAND_DRAIN_SCENARIOS`).
- `ems-ftp75-mpc` (350 s, gated behind `--with-ftp75`): `FTP75_PROFILE`, preload 0.0,
  `chg_i_ceiling_a` 0.8, `ems_run_exit_s` 346.0.

The stochastic variant gets `ems-mpc-sto` on the 61 s stimulus in the second round.
Braking stimuli (`ems-sdp-braking`'s profile) are deliberately excluded until the
post-window prediction is validated, per Section 2.3.

Checks are phase-free per the overnight skill's rule (max continuous hold, fractions,
counts, bands on levels); Table 3 lists the `ems-mpc` entry. Every band carries a
`provisional_note` until the first campaign pins it.

| Check | Kind | Value | Rationale |
|---|---|---|---|
| fault-free | `allow_only: 0` | — | mirrors the three sibling legs |
| survive to the low cruise | `survive_to` | t = 50 in {2, 3} | as `ems-sdp` |
| EMS commanded the profile | `cmd_v_sp` `min_value` 1.45 in (12, 30) | — | as `ems-sdp` |
| envelope respected | `cmd_share_sp` `floor_min_value` 0.149 and `max_value` 0.851, whole run | — | the ladder excludes the cut rails; a rail on the wire is a plumbing defect |
| OC tripwire | `I_fc` `max_value` 1.32 A, whole run | — | the suite's tightest asserted margin (`sdpb_fc_peak_bounded`); never raise to pass |
| the plan was delivered | `I_fc` `min_value` ≥ 1.00 A in (20, 38) | provisional | the plateau rail the terminal price implies below target; re-derive from the walk before the campaign |
| charge admission | `SW_FC_CHARGE` `max_continuous_ticks` ≤ 9000 and `edge_count_between` in [0, 3] over (3, 58) | provisional | the dwell plus one stage; count bounded, not positioned |
| accounting ran | `h2_cum_g` `min_value` 1e-3 g; a two-sided band from the walk ±25 % | provisional | as the sibling legs |
| real time held | `mpc_plan_age_s` `max_value` 2.0 s, whole run; `mpc_solve_ms` `max_value` 500 | — | the Section 3.5 contract on the wire, phase-free |
| governor awareness | `mpc_share_pred_err` (predicted minus delivered stage share) `max_value` 0.10 outside charge windows | provisional | the claim the design makes, asserted as a level band |

### 5.3 Frontier tuples and the ΔSoC-matched DP

Two registry entries are added to `run_hil_suite.EMS_FRONTIERS`, each with the mandatory
three roles: `cycle61-mpc` = (`ems-soc-band`, `ems-mpc`, `ems-dp-replay`) with
`vs_reference_max` 0.98 and `vs_bound_max` 1.06, and `ftp75-mpc` =
(`ems-ftp75-socband`, `ems-ftp75-mpc`, `ems-ftp75-dp`) with 1.02 and 1.06. Both carry the
`sdp` tuples' provisional notes and `stimulus_mismatch_exit_affecting: False` for one
campaign. `EMS_STRATEGY_META["mpc-det"]` is `frontier_eligible: True`; `mpc-sto` is
`False` with a role note until it has a stimulus it is a candidate on.

`hil_report_analysis.py --matched-dp lookup` applies to the new runs unchanged: the key
is the scenario fingerprint plus the run's terminal SoC, and a miss records
`no_cached_solve`. The prefill for `ems-mpc` is seconds; for `ems-ftp75-mpc` it is the
usual tens of minutes and is scheduled before the campaign's analysis pass. The η-era
tables and database records are tonight's WP-1B1 work and are the ones to prefill against.

### 5.4 What the metric structurally cannot distinguish

1. **Charge-free candidates tie.** Under the linear proxy and the plant's Gfc DC gain,
   eq-H2 at matched ΔSoC differs between charge-free strategies only by the pack loss
   (≤ 1.8 % of battery power at the plateau, second order in the split) and the delivery
   clip residual. `sdp-v3` at −0.99 % of the bound is that residual. An MPC reading of
   1.00 ± 0.02 against the bound is the expected outcome, not evidence of optimality or of
   its absence; the `vs_bound` arm is documented as a lever-class detector (CLAUDE.md
   2026-09-01b) and this design does not change that.
2. **The η-era charge lever is a knife-edge against λ.** In the plant's Gfc basis the
   η-era model charge lever is `1/((7.86/0.88) × 18000/0.85 × 1.7638e-5) = 0.300 SoC/g`,
   27 % below λ = 0.41; the measured-lever projection is `0.2364 × 1.786 = 0.422 SoC/g`,
   3 % above it. Which side the board lands on decides whether an MPC that charges gains
   or loses on eq-H2, and the frontier will report KNIFE-EDGE inside [0.409, 0.415] when
   it is close. A charging MPC result must be read with the matched-DP table beside it.
3. **The walk cannot score the MPC** (Section 5.1).
4. **Timing gains do not show on hydrogen.** The preview's value on this rig is on the
   constraint axis (fault-free completion, OC margin, charge windows placed inside
   cruise) and on prediction accuracy (terminal SoC hit, plan-versus-delivered share).
   Those are the checks in Table 3 that carry the design's claim; the eq-H2 figure does
   not.
5. **A convex map changes the ranking basis.** With `--mpc-h2 convex` the MPC minimises a
   quantity the plant does not log (the plant logs Gfc); the comparison then needs the
   same map applied to every leg's logged `P_fc` in post-processing, which is a report
   change and is out of scope for this round.

## 6. Registration and plumbing

### 6.1 Names, files, flags

- Strategy names: `mpc-det`, `mpc-sto`.
- New files: `tools/mpc_ems.py` (stdlib; the strategy class, the stage map, the stdlib
  demand/pack ports, the tail DP, the worker protocol), `tools/test_mpc_ems.py`
  (stdlib-runnable under `.venv_hil` with `pytest.importorskip("numpy")` guarding the
  equality-to-numpy tests, the `test_ems_walk.py` precedent).
- `hil_plant_sim.py`: register lazy proxies `EMS_STRATEGIES["mpc-det"]`/`["mpc-sto"]`
  that import `mpc_ems` inside `bind_scenario()`/`__call__()` (no import cycle, no I/O at
  import); `EMS_STRATEGY_META` entries; the two scenario entries; `SOC_BAND_DRAIN_SCENARIOS`
  extended; `config.mpc` provenance written from the strategy's `provenance` attribute the
  way `config.sdp_policy` is (`:8840`); three append-only CSV columns
  `mpc_plan_age_s`, `mpc_solve_ms`, `mpc_share_pred_err` read by `getattr` the way
  `cmd_share_sp_raw` is, blank for every other strategy.
- CLI flags on `hil_plant_sim.py`, all defaulting to the values above so a scenario's
  `ems` key alone reproduces the shipped design: `--mpc-horizon 20`, `--mpc-terminal
  {huber,linear,sdp-j}`, `--mpc-h2 {proxy,convex}`, `--mpc-worker {process,thread,inline}`,
  `--mpc-preview-bias`, `--mpc-tree` (sto only). `run_hil_suite.py` forwards nothing new;
  the defaults are the campaign configuration.
- `ems_walk._instantiate()`: one branch for the MPC proxy that re-instantiates with
  `strategy_kwargs` and forces `worker="inline"`.
- `gen_dp_ems_table.SOC_BAND_DRAIN_SCENARIOS`: add `ems-mpc` (the B2 defect was exactly
  this omission for `ems-sdp`).

### 6.2 Sidecar `config.mpc` fields

`variant`, `horizon_n`, `decision_dt_s`, `ladder`, `terminal` (mode, `rho_g_per_soc`,
`delta_soc`, `kappa`), `h2_model` (and coefficients when convex), `eta_fc_proxy`,
`eta_chg`, `governor_const_sha256` (over `GOV_CONST`), `stage_map_version`,
`preview_fingerprint` (= `dp_profile_fingerprint(scenario, meta)`), `preview_bias`,
`worker`, `tpm_sha256` (sto), and at finalize the timing statistics
(`solve_ms_median`, `solve_ms_max`, `late_decisions`, `plan_age_max_s`,
`shadow_mode_mismatch`, `soc_clamp_count`).

### 6.3 Step list for the implementer

1. Read `tools/governor_model.py` (all), `tools/ems_walk.py` (all), the `SdpStrategy` class
   and the MODE A block of `tools/hil_plant_sim.py`, `gen_dp_ems_table.py` lines 395-680
   in the working tree (D12 included), and `tools/charger_power.py`.
2. Write `tools/mpc_ems.py` in this order, each part with its test before the next:
   (a) stdlib `demand_preview()` and `drain_a()`; (b) stdlib `PackModel` with discharge
   and η-era charge steps; (c) `StageMap` per Section 2.3; (d) `ShadowGovernor` per
   Section 2.4; (e) `TailDP` per Section 3.3 with `TerminalCost` per Section 3.4;
   (f) `ChargeLatch` per Table 1; (g) `Planner.decide(snapshot) -> Plan`; (h) `Worker`
   with the three modes; (i) `MpcStrategy` with `bind_scenario()`, `reset()`,
   `__call__()`, `summary_line()`, `provenance`.
3. Register in `hil_plant_sim.py` per Section 6.1; add the two scenarios; extend the
   drain whitelist in both modules; add the CSV columns and the sidecar block.
4. Add the two `FAULT_EXPECTATIONS` entries (Table 3) and the two `EMS_FRONTIERS` entries
   to `run_hil_suite.py`; add `ems-ftp75-mpc` to `FTP75_SCENARIOS`.
5. Run the offline walk on `ems-sdp`'s stimulus through `mpc-det` and through the three
   siblings; write the provisional bands from it; record the governor mode census.
6. Run the tests: `.venv_hil` `pytest tools/ --ignore=tools/test_figures.py`, then the
   miniforge numpy suites including `test_mpc_ems.py`, `test_ems_walk.py`,
   `test_hil_plant_sim.py`, `test_run_hil_suite.py`.
7. Prefill `dp_results_db` for `ems-mpc` at the walk's terminal SoC (seconds) so the first
   campaign's matched-DP row is a lookup hit.
8. Campaign 1 (61 s legs only): run, analyse under `hil-agent-analysis`, pin the bands,
   delete the notes; verify the timing statistics in `config.mpc`.
9. Campaign 2 (`--with-ftp75`): the FTP-75 leg and the `ftp75-mpc` frontier's first
   evaluation; flip `stimulus_mismatch_exit_affecting` afterwards.
10. Then `mpc-sto` (Section 4), then the convex-map option once stack coefficients exist.

## 7. Risks and the reversal path

- **Post-window ratio recovery is unvalidated** (governor fidelity boundary on braking).
  Mitigation: no braking stimulus in the first two campaigns; the `mpc_share_pred_err`
  band measures the residual where windows do open.
- **Worker-process behaviour on this host.** Spawn re-imports `hil_plant_sim` in the
  child; a 0.5 s import is inside the 3 s before the first decision, but a slower host
  would start the run on the fallback rule. Mitigation: the worker is started in
  `bind_scenario()` and its first reply is awaited there with a 5 s timeout that refuses
  the run rather than starting it degraded.
- **The stage map disagrees with the board beyond the roll's coverage** (a transition the
  preview does not predict, e.g. a load the drain schedule does not model). Mitigation:
  the shadow governor's observation correction bounds the error to one stage; the
  mismatch counter is reported.
- **Knife-edge charge economics in the η era** (Section 5.4). Mitigation: the design does
  not decide it; the matched-DP row and the frontier's KNIFE-EDGE verdict carry it.
- **Degenerate hydrogen ranking** (Section 1.4). Mitigation: the constraint- and
  prediction-axis checks are the deliverable of the first campaign; the convex map is the
  documented route to a hydrogen result.
- **Scope creep into the SDP solver** (the `sdp-j` terminal). Mitigation: optional, listed
  last, policy sha unaffected.

Reversal is one commit: delete `tools/mpc_ems.py` and `tools/test_mpc_ems.py`, remove the
two registry entries, the two scenarios, the two expectation entries, the two frontier
tuples, the `FTP75_SCENARIOS` member, the drain-whitelist additions, the three CSV
columns and the `config.mpc` block. No existing strategy, artifact, table, constant,
fingerprint or CSV offset moves in the forward change, so the reverse leaves every
earlier campaign's comparability intact.
