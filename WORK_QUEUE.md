# Work queue — updated 2026-09-01 (post-overnight)

Overnight progress (see OVERNIGHT_LOG.md for the full decision log): §1's S1/S2/S3
SHIPPED and hardware-calibrated (campaign 024231); §2's fw v24 PREPARED (commit
128dc40, NOT flashed); the FTP75 DP table BAKED (drive-cycle-scale DP≈soc-band tie);
sdp_policy_v3 shipped after the charge-economics finding (charging is loss-making at
rig scale — see the 2026-09-01b CLAUDE.md addendum); the EMS frontier check is live.
Four campaigns run, zero board defects.

## 0. NEW since the original queue (do these first)

- **fw v24 tooling-lockstep round (BLOCKS the fw v24 flash):** the simulator still
  emulates the fixed 18 V MPPT threshold and does not parse the 17 B observation
  frame. Needed: frame length-detection (16 B legacy fallback + flag),
  mppt_emulation consuming the observed threshold count, mppt-tracking expectation
  flip (≤6 toggles, threshold-band checks, the released-and-refusing prohibition),
  charger-figure threshold trace. Then: flash fw v24 (edit HIL_SIM 0→1 as usual)
  and run the acceptance sequence in the fw v24 design docs (first-write ~21/22
  counts, power-cycle zero-write, hunt-gone).
- **Bench steps fw v24 wants:** R1 MPPTSEL inspection (documentation-grade now);
  the MPPTD-disabled-charge behavior verification (the two designers read the
  datasheet oppositely; gates the ag105ReleaseOk() upgrade); Silvertel EPROM
  endurance query.
- **S4 solver feasibility masking** (demand above FC max) — still tabled; the v3
  solver's action-mask machinery (--forbid-charge) is a partial precedent.

## 1. SDP interior scenario round — ✅ SHIPPED overnight (calibrated, campaign 024231)

Goal: move the SDP strategy off the FC rail so the commanded share itself varies on
the wire. Builds on the `sdp_policy_v2.json` artifact.

| Item | Design | Status |
|---|---|---|
| S1: FTP75, SoC above target | New `soc_ref` offset parameter (`soc_ref = soc0 − δ`, δ ≈ 0.015–0.02) — the strategy is soc0-relative, so a bare `--soc0` cannot start above target. Expected mid-run flip 0.15 → 0.85 as SoC crosses target (~0.019 SoC drain over 340 s). | Approved, build |
| S2: charge-and-cross limit cycle | Low-demand cruise, light/no aux drain: the policy's own charge decision raises SoC across target (~11–22 s of net 0.8 A per grid node), the table flips to the battery-heavy side, SoC falls back — a charge-sustaining bang-bang that exercises both rails and the charge action repeatedly. | Approved, build |
| S3 (partial): braking-heavy modified cycle | Decel windows are low-demand bins, so the policy charges during braking. Caption honestly: SoC rise is FC-fed via `FC_CHARGE`; the plant floors regen power at zero, so braking energy does not reach the pack. | Approved, build with caveat |
| S3 (full): true regen harvest | Requires the regen-fidelity plant model round (remove the regen power floor). | Tabled |
| S4: demand above FC maximum | Requires per-bin action-feasibility masking in the solver (forbid shares whose FC power exceeds the 1.4 A budget) — an EMS change. Firmware has no FC-current governor ceiling; `LIMIT_I_FC_MAX` is a fault, not a control limit. | Tabled (operator rule) |

Also derive expectations that score the flips (share-step edges, charge windows, SoC
crossing), with offline walks to predict flip times.

## 2. fw v24 firmware round — ✅ PREPARED overnight (commit 128dc40, NOT flashed; see §0 for the tooling-lockstep prerequisite)

- Manage reg 0x02 (11–33 V, ~0.088 V/count, default 18 V) **dynamically**: droop sags
  the bus (TP0178 reached 12.15 V; hifi charge windows ~13.4 V), so a static
  near-nominal threshold re-creates the release/re-assert hunt.
- Design constraints for the spec: Ag105 register writes persist to EPROM — establish
  a write-rate budget from the datasheet endurance figure; multi-count hysteresis
  deadband (~0.2–0.3 V); writes through the power-gated `pollAg105()` lazy-config
  path only. Recommended shape: track V_bus (or V_chg) minus a margin, floored at
  ~12.3 V (just above `LIMIT_V_BUS_MIN`) so the charger self-throttles before a UV
  latch.
- Same round: correct the two stale perturb-and-observe comments in the `.ino`
  (~:10029, :10047).
- Gated by R1 (item 3): a fitted MPPTS resistor changes the baseline threshold.

## 3. Operator bench actions

1. **R1 (standing):** inspect the MPPTSEL header. Unfitted (or > ~15.9 V) → the real
   charger hunts and fw v24 is required; fitted ≤ ~12–15 V → no firmware change,
   update the simulator's emulated threshold instead.
2. `drive` scenario has never run (operator-gated): run one campaign with
   `--with-operator` when present at the bench.

## 4. Pi bridge v4 parser audit → Mode B (BLOCKED overnight: bridge source not in repo)

Audit the Raspberry Pi bridge's v4 telemetry parser (58-byte layout, offset table in
PLAN.md §6b) — the single blocker for Mode B. The bridge source lives on the Pi, not
in this repo, so the audit needs the Pi's filesystem (operator: pull the bridge code
into the repo or run the audit on the Pi). Then the first `--pi-live` campaign
re-running the EMS set through the real Pi.

## 5. First v2 campaign (after the in-flight round lands)

- Calibrate the re-derived `ems-sdp` thresholds (first campaign turns offline
  predictions into measured facts).
- Observe the predicted ~1 Hz `FC_CHARGE` chatter (memoryless policy, no hysteresis;
  charger draw pushes demand into a forbidden bin). If undesirable → operator
  decision on a consumer-side dwell/hysteresis wrapper (soc-band's dual-gate
  pattern).
- Score the now-deliverable ems-y b30 high bound (Y_AUX_LOAD_A 0.85 makes it
  reachable for the first time; threshold unmeasured).
- Re-measure the three-way EMS ranking on v2 — the campaign-191509 sdp-v1 totals
  (0.0125424 g / −0.00166 SoC) are a different decision law and must not be quoted
  against v2 results.

## 6. Model and tooling improvements (unordered within section)

- **Measured-droop sim mode**: an `--electrical` variant using the bench-fitted
  `K_DROOP_BUS` 0.074/0.16 V/A — makes sag/handoff/UV-margin predictions
  bench-transferable (hifi currently runs the design chain, ~4×).
- **Gfc fuel-cell stack identification** (bench + model round): converts H2 rankings
  into absolute predictions; current DC gain implies η 47.25 % vs the DP's 55 %
  static proxy.
- **FTP75 DP table** (~21 min offline solve): extends the offline-optimal benchmark
  to drive-cycle scale for the `--with-ftp75` legs.
- **SDP smoother stage cost** (optional design idea): an FC efficiency curve instead
  of constant η would give interior share optima rather than bang-bang — worth
  considering for the thesis narrative.
- `hil_report_analysis.py`: plot `cmd_share_sp_raw` (raw vs emitted share, clamp band
  shaded) so the clamp erasure is visible per run.
- `signal_series_verdict()`: native two-sided (min+max) spec support (currently
  guarded by an import assert that refuses the combined form).
- TPM generator contract text: the sidecar `normalization` block is now documentation
  for the SDP path, not its input — update the generator's wording.
- Reconcile the ems-y b00-v3 gate-fraction discrepancy (campaign 20.6 % vs model walk
  12.7 % — recorded as unreconciled).
- `ems-ftp75-socband` h2 floor stays loose until its OC_FC allowance is retired or
  the entry grows a completed-run-only branch.

## 7. Operator decisions outstanding

- **F2** replay coverage-variance policy: the conservative doc option was taken this
  round (cutoff coverage lives in share-staircase / ems-y-b00-*); a scored band needs
  a multi-campaign transition-count distribution first.
- **UV-dwell objective home** (2026-08-30d): unreachable on the BT rail behind OC_BT —
  retire from handoff-sag or move to a `v_bus_sense_offset` scenario.
- **Ag105 policy on real hardware** (2026-08-30d): lazy-re-config behaviour and the
  `FC_CHARGE` open-through-loss policy need a hardware ruling.

## 8. Standing housekeeping and older items

- Rebuild the benchlog analyzer exe (pending since fw v18).
- `.venv_benchlog` still lacks pandas/scipy; no committed venv holds
  numpy + matplotlib + pytest together.
- Rs(SOC) calibration against a real 2S pack (sets the soc-depletion latch point).
- Chopper coverage: needs a scenario that puts real energy into the motor node.
- `error_code` on the observation frame (protocol work — frozen until a protocol
  round).
- hifi M1 re-arm branch live coverage; early-exit guard (minor).
- `PSCAD/` remains untracked — provenance unconfirmed, deliberately not committed.
