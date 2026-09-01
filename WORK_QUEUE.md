# Work queue — updated post fw v25 round (commits b262e98 + 89fbad6), 2026-09-01

## 0. NEW — flash fw v25 + first-campaign triple validation

1. **Flash fw v25.** Edit `HIL_SIM` 0→1 on the bench machine for the HIL flash — never
   commit that edit (repo defaults stay `BENCH_TEST 1` / `HIL_SIM 0`).
2. **Triple validation on the first post-flash campaign:**
   - Guard end-to-end: the fw v25 r-based bus-cutoff guard fix (extended
     `|I_doomed| ≤ 0.5 A` guard + survivor-HIGH blanking term) exercises cleanly —
     watch `ems-sdp-braking` complete without the FC_BUS/BT_BUS handoff fault that
     drove the fw v24 candidate.
   - Regen-model baseline RECALIBRATION: the regen-fidelity plant model (WP-C,
     2026-09-01) removed the zero-regen floor, so every regen-bearing scenario needs
     fresh baselines — `ems-y` quartet, `charge-regen`, the `mppt-tracking`
     regen-capture windows, and `regen-harvest-true` are **not comparable** to any
     run at or before campaign 080905.
   - 18 B observation-frame `error_code` attribution: confirm PI_TIMEOUT vs
     HIL_LINK now discriminate directly off the wire (offset 16) rather than by
     inference.

## 1. EMS test-program goals (operator directive, 2026-09-01 — supersedes the
##    FTP75 preload ruling)

1. **Remove the auxiliary preload entirely — `aux_preload_a` → 0 for ALL
   scenarios.** Keep the mechanism in the code; zero every scenario's value
   (incl. `FTP75_PRELOAD_A` 0.65/0.45). Rationale (operator): part of what is
   under test is how the actual firmware behaves against the simulated ACTUAL
   load when the Pi commands drive cycles + EMS strategies — including the
   sub-0.55 A open-loop-hold stretches the preload was masking; those are now
   test content, not a nuisance. Consequences to handle: (a) this RESOLVES the
   FTP75 preload split by construction (all legs at 0 — the frontier
   stimulus-coherence check passes); (b) every closed-loop-gated expectation
   calibrated under a preload (FTP75 legs, ems-soc-band/-sdp entries, the
   closed-loop-fraction checks) must be re-derived for gate-dropout stretches —
   a baseline-era boundary for preloaded scenarios; (c) offline walks must
   model the open-loop hold (the standing walk rule). SCOPE NOTE for the
   implementer: this ruling names `aux_preload_a`; scenario-specific STIMULUS
   drains (the soc-band/soc-depletion drains, share-staircase loads,
   Y_AUX_LOAD_A) are a different mechanism — confirm with the operator before
   touching those.
2. **ΔSoC-matched post-hoc DP in the run analysis.** For each HIL run that
   executes a drive cycle, the analysis pipeline runs (or looks up) a DP solve
   on the SAME cycle constrained to the run's own measured ΔSoC
   (`gen_dp_ems_table.py --match-terminal-soc` bisection exists), giving a
   direct ΔSoC-matched hydrogen comparison per run. Mind the documented
   boundaries: the DP demand model has no regen term and (post item 1) no
   preload; accounting mode must match the run's electrical mode.
3. **α-sweep for the SDP strategies.** The full-scale SDP study used
   α ∈ [100, 1000]; scale by the Round-B coulombic-energy factor
   (500 → 0.2569444, i.e. ×5.139e-4) → bench bounds ≈ [0.0514, 0.514]. Solve
   20 log-spaced points (log spacing already densifies the low end; the
   current lever-calibrated α = 0.16296 falls inside the range and should be
   one anchor point). Deliverable: 20 policy artifacts + an offline
   walk/selected-run evaluation of h2-vs-ΔSoC across the sweep.
4. **EMS strategy comparison deliverable.** Primary metric: percent deviation
   from the corresponding ΔSoC-matched DP (item 2 is the prerequisite), across
   all strategies and cycles (61 s, FTP75, the braking/interior scenarios).
5. **Experimental MPC / stochastic-MPC EMS that models the GOVERNOR.** The SDP
   family ignores the firmware's delivery nonlinearities (the 0.55 A open-loop
   hold — newly exposed by item 1, the minority-current governor clip, share
   slew, cut latches). Build an MPC (deterministic first, then stochastic via
   the TPM demand model) whose prediction model includes the governor's
   share-delivery map. Source material: references/EMS/
   SDP_EnergyManagement_Governor2.m + main_SDP_governor_convexfc.m (the PhD
   student's governor/convex-FC formulation, committed 567a3ed) and the TPM
   toolchain (tools/tpm_generator.py, TPM_dt1_hil.mat).

## 2. Pi bridge v4 parser audit — UNBLOCKED

Bridge source is committed at `references/EMS/Pi_2026-09-01/`
(`teensy_bridge_node_2026-08-17A.py` + ROS2 nodes + SDP material, commit
567a3ed). Remaining item: the v4-parser audit itself (58 B layout, checksum XOR
bytes 1–56, `charger_status` at offset 51) → gates the first `--pi-live`
campaign.

## 3. Bench items feeding new TODO(verify)s

- VESC regen commanded-vs-delivered mapping (`VESC_REGEN_I_MAX_A` + `ETA_REGEN`) —
  uncharacterized on real hardware.
- 30 ms blanking calibration — asymmetric failure direction; never shorten the
  blanking window on the model alone.
- Boost-OR `strict_forward` A/B comparison.
- MPPTD-disabled-charge semantics (the two fw v24 designers read the datasheet
  oppositely; still needs a bench ruling).
- Silvertel EPROM endurance figure — not in the datasheet, `TODO(verify: Silvertel)`.

## 4. Protocol flags

- `sw_ring` state field — not on the observation frame.
- Refused-cut counters — not on the observation frame.
- `error_code` — now ON the observation frame (offset 16, fw v25) but not yet
  plumbed into the analysis figures.

## 5. OPEN ANALYSIS QUESTION

Does the charger lever now clear the 0.31 SoC/g `sdp` charge-revisit condition
under the regen model? Measured 0.156 SoC/g under the (now-retired) floored plant —
the floor is gone as of WP-C. Run this before the next SDP re-solve.

## 6. Untracked operator decisions — RESOLVED 2026-09-01 (commit 567a3ed)

- `PSCAD/`, `references/EMS/Pi_2026-09-01/` and the two SDP `.m` files are now
  TRACKED (operator-approved). The worktree deliberately keeps exactly one thing
  uncommitted: the two `.ino` build-flag lines (`BENCH_TEST 0` / `HIL_SIM 1`).

## 7. Housekeeping

- Campaign ledgers live in gitignored `HIL Results/` — decide whether to promote
  the newest campaign to a committed skill exemplar
  (`.claude/skills/hil-agent-analysis/references/`).
- Rebuild the benchlog analyzer exe (pending since fw v18).
- `.venv_benchlog` still lacks pandas/scipy; no committed venv holds
  numpy + matplotlib + pytest together.
- Rs(SOC) calibration against a real 2S pack (sets the soc-depletion latch point).
- hifi M1 re-arm branch live coverage; early-exit guard (minor).

## 8. Model and tooling improvements (unordered within section, still open)

- **Gfc fuel-cell stack identification** (bench + model round): converts H2
  rankings into absolute predictions; current DC gain implies η 47.25 % vs the
  DP's 55 % static proxy.
- **SDP smoother stage cost** (optional design idea): an FC efficiency curve
  instead of constant η would give interior share optima rather than bang-bang —
  worth considering for the thesis narrative.
- `signal_series_verdict()`: native two-sided (min+max) spec support (currently
  guarded by an import assert that refuses the combined form).
- TPM generator contract text: the sidecar `normalization` block is now
  documentation for the SDP path, not its input — update the generator's wording.
- Reconcile the ems-y b00-v3 gate-fraction discrepancy (campaign 20.6 % vs model
  walk 12.7 % — recorded as unreconciled).
- **Ag105 policy on real hardware**: lazy-re-config behaviour and the
  `FC_CHARGE` open-through-loss policy need a hardware ruling.

## Shipped this round (commits b262e98 + 89fbad6)

- **fw v25** — shipped, NOT flashed (see §0 to flash and validate): the r-based
  bus-cutoff guard fix (both branches of `applyShareRatio()`) with the
  survivor-HIGH blanking term; the `.ino:32` changelog 60→15 ms dwell correction;
  the last perturb-and-observe comment leftovers cleared; observation frame
  17 B → 18 B with `error_code` at offset 16.
- **Suite fix batch** — F1 (mppt `threshold_written` phase-free column-motion
  check), R-MED-1 (TP0010 `i_bt_clamp_a` 2.8 A ordering assertion), the LOW batch
  (mppt-tracking calibration pins, F2 floor-check min-over-window semantics, F3
  comment fix, F4 `I_fc ≤ 1.30` tripwire, R-LOW-1 ML0151 OC-margin pin, R-LOW-3
  `replay_source` fw/sha stamp, the sw_ring en_low tripwire, F5 hil-conventions.md
  hazard-signature/i_cut-observable/HIL-mirror-write-policy additions,
  FW_DELTA_NOTES backoff-unreachable wording).
- **Regen model (WP-C)** — the S3-full braking-heavy regen scenario un-tabled and
  shipped; chopper coverage enabled (a scenario now puts real energy into the
  motor node).
- **Measured droop** — the bench-fitted `K_DROOP_BUS` (0.074/0.16 V/A) sim mode
  shipped; sag/handoff/UV-margin predictions are now bench-transferable.
- **FTP75 DP table** — the offline-optimal benchmark now extends to drive-cycle
  scale for the `--with-ftp75` legs.
- **`cmd_share_sp_raw` figure** and the new **`hil_h2_and_soc`** figure — both
  shipped in `hil_report_analysis.py`.
- **All six §6b rulings implemented**: UV-dwell objective moved to the new
  `v_bus_sense_offset` scenario; `ems-ftp75-socband` OC_FC allowance retired
  (two-sided h2 floor); observation frame grown 17→18 B with `error_code`;
  FTP75 DP leg + measured-droop hifi mode shipped; regen-fidelity plant model
  shipped (un-tables S3-full and chopper coverage); Pi bridge source now
  available (§2).
- **UV-dwell home** — resolved onto `v_bus_sense_offset` (see above).
- **`error_code` on the observation frame** — shipped (protocol work, no longer
  frozen pending a round).
