# Alpha-sweep figures: provenance and fidelity

## 1. What these figures are

Each folder under `<scenario>/alpha_<idx>_<value>/` holds two standard report
figures and the CSV they were rendered from, for one point of the SDP alpha
sweep. **No board run exists behind any of them.** The traces come from the
offline governor walk of `tools/ems_walk.py`, which drives the sweep point's
solved policy through the reduced demand, pack, bus and hydrogen model of
`tools/gen_dp_ems_table.py` with `tools/governor_model.GovernorModel` in the
delivery path. Every figure's suptitle states this:

    OFFLINE GOVERNOR WALK - alpha_<idx>_<value> - not a board run (<scenario>)

## 2. How a folder is produced

    C:/Users/ricky/miniforge3/python.exe tools/sdp_alpha_sweep.py plots \
        --scenario ems-sdp --include all

The `plots` subcommand walks the point, writes `walk_trace.csv` in the live
HIL CSV schema (`tools/sdp_alpha_sweep.HIL_CSV_COLUMNS`, taken verbatim from
the simulated hi-fi writer's `header_row` construction at
`tools/hil_plant_sim.py:8512-8611`, including the six-column power-balance tail
appended 2026-09-01f), and pushes that file through the ordinary analysis path:

    hil_report_analysis.load_hil_csv -> attach_derived -> adapt_to_benchlog
    benchlog_analysis.figures.currents_and_share(data, cfg)
    hil_report_analysis.hil_charger_and_soc(hil, cfg)

The PNGs are saved under a `walk_` prefix (`walk_currents_and_share.png`,
`walk_hil_charger_and_soc.png`) so a glob for a board-run figure name cannot
ingest an offline walk as if it were a run.

The builders are the same ones a campaign report uses, called with the same
`cfg` shape, so a sweep figure is directly comparable with a campaign figure of
the same name.

## 3. Which columns are real

The walk produces `t`, `V_bus`, `I_fc`, `I_batt`, `I_charge`, `soc`,
`mdac_fc`, `mdac_bt`, `cmd_share_sp`, `h2_rate_gps` and `h2_cum_g`. The
velocity columns `v_actual` and `cmd_v_sp` are the scenario's own
`ems_v_profile`, so `v_actual` is the COMMANDED velocity, not a tracked one.

Three columns are documented constants rather than model output: `state` is 2
(Run) for the whole window, `aux` asserts both regulator enables, and
`fault_flags` and `error_code` are 0 because the offline model raises no fault.
The `switch` word holds FC_BUS, MOT_PWR and BT_SEQ throughout, and swaps BT_BUS
for FC_CHARGE inside a charge window, which is what `chargingControl()` does.
The `ag105_status` byte is the plausible Table-6 value for the condition
(`0x42`, charging in constant current, inside a window; `0x00` outside), not a
simulated charger state.

Every remaining column is written BLANK, which `load_hil_csv` reads as NaN:
`V_fc`, `V_batt`, `V_chg`, `V_rgn`, `current`, `elec_substep_hz`,
`elec_events`, `h2_sdp_cum_g`, `cmd_share_sp_raw`, `mppt_thresh_cnt` and the
six power-balance columns `p_mot_w` through `p_bal_w`. A
figure that depends on one of them declines rather than plotting a fabricated
trace. This is why the `hil_charger_and_soc` panels for `V_chg` and
`elec_substep_hz` are empty.

## 4. Fidelity boundaries

These are the walk's own boundaries, restated so no figure is over-read.

1. **No Youla dynamics.** The share controller is modelled as a slew-limited
   walk to the governed reference (`tools/governor_model.py`). A share
   transient in these figures carries the governor's rate limit and its mode
   logic, not the synthesised controller's closed-loop response.
2. **The DP demand model.** Demand, bus voltage and source total come from
   `gen_dp_ems_table.build_demand()`, which has no regen term and therefore
   over-states demand on every decelerating stage. The bus voltage is the
   shared-droop value even inside a charge window.
3. **Charge admission is by the DP mask.** A window opens only where
   `gen_dp_ems_table.charge_mask()` admits it, so a window the DP forbids can
   never appear here even if the strategy asks for one. The Ag105's own settle
   time and current ramp are not modelled: `I_charge` steps.
4. **The stage is 0.1 s.** The trace is the DP stage grid, not the 1 kHz
   observation stream a campaign CSV carries.
5. **The strategy binding is `sdp-v2`**, the non-frontier role. No sweep
   artifact can bind the frontier-scored `sdp-v3` strategy, because every one
   of them is solved with an explicit alpha. A figure here is a dynamics
   demonstration, and its hydrogen and SoC pair must not be placed on the EMS
   frontier.

## 5. Coverage

`ems-sdp` is rendered for all 41 points. `ems-ftp75-sdp` is rendered for the 20
refined points only, which are the two transition neighbourhoods.

The `ems-ftp75-sdp` folders are from the **zero-preload era**:
`FTP75_SDP_PRELOAD_A` is 0.0 as of commit 88e11f0, and campaign 151156 was the
last run of the preloaded era. Their traces must not be compared with any
preloaded-era drive-cycle figure, including the historical table at
Section 8.2.1 of `../../sdp_alpha_sweep_20260901.md`. The `ems-sdp` folders are
unaffected by the preload change.
