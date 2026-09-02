# Governor-aware MPC — design adjudication (2026-09-01, overnight round)

This document records the synthesis of two independent design candidates
(`candidate_opus.md`, `candidate_fable.md`; identical brief in `brief.md`) into the design
the implementer executes. The implemented design is documented in
`docs/modeling/mpc_design_20260901.md` (written by the implementer from this adjudication).
Every number below is taken from the candidate that measured it and is cited by section.

## 1. Points of agreement (adopted without change)

- Decisions at 1 Hz, horizon N = 20 stages, no discount inside the horizon; `soc0`-relative
  regulation; the proxy stage cost `P_fc,stack/(0.4 · Q_LHV)` with `P_fc,stack = P_fc,bus/ETA_BOOST`
  (both §1); the convex fuel-cell map as a refused-unless-supplied option (Fable §2.6).
- Preview from the scenario profile via `bind_scenario()` through a stdlib port of
  `build_demand()`, `charge_mask()`, `scenario_drain_a()`, equality-tested against the numpy
  originals (Opus §2.1, Fable §2.1). The strategy is labelled PREVIEW, never causal (Opus §1.3).
- Pack/charge steps are scalar ports of `step_discharge()`/`step_charge()` in the η_chg era,
  using tonight's charger-power helper (Fable §2.5).
- Constraints: FC 1.19 A / BT 2.55 A delivered margins, charge admissible only where the DP
  mask admits, the 8 s dwell latch reproduced from `SdpStrategy.charge_hold_status()`, soft SoC
  window (Opus §1.4, Fable Table 1).
- Two frontier tuples `cycle61-mpc` and `ftp75-mpc` with the sibling tuples' provisional
  values (Opus §5.5, Fable §5.3); phase-free checks only; `provisional_note` on every band.
- Both candidates independently recompute that the η-era charge lever (0.3964 SoC/g at 7.4 V)
  exceeds sdp_policy_v3's admission threshold 0.30682 SoC/g, so the v3 α admits charging in the
  η era (Opus §2.5, Fable §2.5). Both state that under a linear proxy charge-free strategies
  tie the DP bound within pack-loss and clip residuals (Fable §1.4, Opus §5.6).
- Stochastic variant second; scenario trees are not enumerable at out-degree 17 (Opus §4.2).

## 2. Disagreements and rulings

### 2.1 Prediction model

Opus: control-independent precompute (the load filter retains 0.95^1000 of its state across a
stage, so mode and clip bound are functions of the preview alone; 240/240 mode matches), an
algebraic surrogate on closed stages (mean error 8.2e-4, max 1.49e-2), carry-through on open
stages (max error 0.2484 — every large error an `open_hold` stage), one exact 1 kHz commit
roll per decision. Fable: a stage map plus exact 1 kHz rolls on the first stage of every
candidate AND on every mode-transition stage (the ratio at drop-out depends on the EMA/slew
history, which no closed form reproduces), plus a shadow governor corrected from the observed
MDAC ratio at 50 Hz.

**Ruling: hybrid of both.** Opus's precompute and closed-stage surrogate are the search model.
Fable's transition-stage exact rolls replace Opus's carry-through on open stages: per decision,
each previewed mode-transition stage (0.60 A upward, 0.55 A downward, charge-window open/close)
is rolled at 1 kHz once per ladder point to produce `r_hold[s]`, and open stages carry that
value. Fable's shadow governor with MDAC correction is adopted as the state estimate (3.3 ms/s;
it is the observer whose absence made earlier walks open-loop). Opus's commit roll is retained
(the shadow governor IS the committed state). Opus's Gate 1 acceptance test remains the
implementation gate; Fable's inverse-crime caveat (the walk cannot score the MPC) is stated in
the evaluation section.

Reason: the 0.2484 open-stage error Opus measured is exactly the class of error the transition
rolls remove, and their cost is bounded (≤ 4 transitions × 7 ladder points × 2.7 ms ≈ 76 ms
per decision, sliced — see 2.2).

### 2.2 Real-time architecture

Opus: the whole decision inside one 50 Hz callback (8.63 ms measured budget, 116× margin at
1 Hz, 2.3× inside the 20 ms callback), anytime branch-and-bound with a hard `mpc_budget_ms`,
slicing across callbacks for the stochastic fan. Fable: a worker process, because its design
costs 65–350 ms per decision and `HIL_STALE_MS` is 50 ms.

**Ruling: Opus's in-callback anytime search, no worker process.** The transition rolls of 2.1
are computed control-independently once per decision and SLICED across callbacks at a
per-call budget (default 2.0 ms), exactly Opus's mechanism for the stochastic fan; the search
uses the previous decision's `r_hold` table until the new one completes. A multiprocessing
worker inside the 1 kHz simulator loop (spawn re-import, GIL contention with the adaptive
hi-fi substeps, pickling per decision) is a risk the budget arithmetic does not require.
Budget expiry returns the shifted incumbent and increments a counter reported in the exit
summary and as a CSV column.

### 2.3 Optimizer and ladder

Opus: move-blocked enumeration (blocks 2/6/12, 7-level ladder over the DP band [0.25, 0.75],
charge binary on block 1 → 686 candidates), warm-started, branch-and-bound. Fable: tail DP on
a 61-node local SoC grid with the 15-point ladder over [0.15, 0.85] and three charge-window
candidates.

**Ruling: Opus's enumeration** (it carries the governor state exactly along each candidate,
which a state-space DP cannot without an 882-state governor axis). Ladder band default
[0.25, 0.75] (the DP bound's authority; the setpoint cutoff can never fire), with
`--mpc-share-band` to widen to the SDP envelope [0.15, 0.85] for a like-for-like SDP leg.
Fable's three-window charge enumeration is adopted in place of Opus's block-1 binary: (i) no
charge, (ii) charge now for 8 stages, (iii) charge now until the admissible segment ends —
it costs 3× on the charge axis only where the mask admits. Ties resolve to the smaller share
and no charge (SDP D8).

### 2.4 Terminal cost

Opus: linear `λ_T·|x_N − x_ref|` with `λ_T = 1/0.41 = 2.439 g/SoC`, the suite's own eq-H2
exchange rate, so the horizon objective is the scored metric. Fable: Huber with the SDP shadow
price in the proxy basis (`κ = 1.4706`, `ρ = 4.793 g/SoC`) and `soc-band`'s half-width
0.0015 as the dead band, to avoid 1 Hz bang-bang about the target.

**Ruling: Huber shape (Fable) at the metric price (Opus), converted to the proxy basis.**
`ρ_metric = 1.181 × 2.439 = 2.881 g/SoC` in proxy grams (the proxy over-reads Gfc by
2.0833e-5/1.7638e-5 = 1.181, both candidates); `δ = 0.0015`. Modes: `metric` (default),
`sdp-shadow` (4.793), explicit value. The SDP value-function terminal (`sdp-j`) is a
follow-on requiring a schema-additive solver change; not in this round.

### 2.5 Stochastic variant

Opus: sampled scenario fan (M = 8, common random numbers, CVaR option), ~50 ms, sliced.
Fable: certainty-equivalent conditional-mean path with the OC constraint tightened to the
90 % quantile of the k-step demand distribution.

**Ruling: Fable's certainty-equivalent + quantile OC tightening is `mpc-sto`'s default**
(the constraint axis is where the TPM's information is worth most on this rig; cost equals the
deterministic variant). Opus's CRN fan ships behind `--mpc-risk fan` if time permits, sliced.
Both candidates' caveat stands: the TPM is a vehicle's, the 0.762 diagonal makes short-horizon
prediction near-persistence, and no simulator stimulus is a TPM draw.

### 2.6 Scenarios and columns

First round: `ems-mpc` (the `ems-soc-band` stimulus object, 0.8 A ceiling), `ems-ftp75-mpc`
(behind `--with-ftp75`, preload 0), and `ems-mpc-cross` (Opus's switching-surface stimulus;
phase-free checks only). No braking stimulus until the post-window prediction is validated
(Fable §2.3). `ems-mpc-sto` in the stochastic round. Append-only CSV columns AFTER
`p_chg_loss_w`: `mpc_solve_ms`, `mpc_share_pred_err`, `mpc_budget_hit`. Sidecar `config.mpc`
per Fable §6.2 plus Opus's `preview_source`/`terminal_price_mode`. Fable's preview-bias
observer is deferred (default-off would still be untested code in a first campaign).

## 3. Reversal path

One commit: the new module and test, the additive registry/scenario/expectation/frontier
entries, the three CSV columns and the sidecar block (both candidates §7). No firmware, wire,
artifact, table or constant changes.
