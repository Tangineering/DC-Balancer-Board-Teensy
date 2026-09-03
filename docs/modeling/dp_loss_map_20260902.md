# The DP demand model's static-loss map

**Date:** 2026-09-02 · **Scope:** the offline DP/SDP demand model · **Status:** shipped.
This document records two defects in the demand model that `tools/gen_dp_ems_table.py`
solves against, the static-loss map that corrects both, the probe that fitted the map, and
the re-priced table-versus-run deviations that verify it. The map is a property of the
hi-fi electrical engine under `--droop design --asymmetry measured`; it is not a board
measurement.

Related records: `docs/HIL_PLANT.md` §4.8 (the per-node bleed change this map is fitted
against) and §9.4.1 (the map as the bound's demand model).

---

## 1. The two defects

A term-by-term decomposition of the two `dp-replay` legs of campaign
`hil_report_20260902_041414` separates the measured deviation into two named causes. Table 1
gives that decomposition, with each term expressed as its contribution to the run's hydrogen
relative to the table's.

| Term | FTP-75 | 61 s cycle |
|---|---|---|
| Node bleed on `N_BUS` and `N_MOT`, billed to the sources but absent from the DP | +4.90 % | +2.58 % |
| Droop-mode mismatch in the DP's bus law | −0.67 % | −2.73 % |
| Measured deviation of the run against the DP | +4.346 % | −0.198 % |

Table 1 shows that the two terms carry opposite signs and partially cancel. On the 61 s
cycle they very nearly cancel outright, which is why the deviation there reads −0.198 % and
appeared healthy while both defects were present.

**Defect 1: the DP does not bill the node bleed.** `tools/hil_electrical.py` bleeds every
node to ground, and the sources carry that current. `N_BUS` is billed for the whole run.
`N_MOT` is billed for the whole run as well, because `MOT_PWR` is closed from the
low-voltage bring-up through Idle and Run (`CLAUDE.md` §2, Death 5). `N_OFC` and `N_OBT` are
**not** billed, because `ElectricalSim._source_current` refers the stack current at
`v[N_BUS]`. `N_CHG` is billed only while `FC_CHARGE_ENABLE` or `REGEN_ENABLE` is closed.

**Defect 2: the DP solves the wrong droop mode.** The DP's bus law is
`V_BUS_DROOP_V0 − K_DROOP_BUS_SHARED · I` = 15.95 − 0.074 I, which is the `--droop measured`
realization. Every campaign runs `--droop design`, whose realized bus law regresses at
15.8652 − 0.3015 I over 343 001 Run-state rows of `ems-ftp75-dp`.

**The two defects are fixed together, not separately.** Their opposite signs mean that
correcting either one alone increases the deviation on at least one leg; §6 measures that
directly.

## 2. The shipped map

The map replaces the DP's single-term bus law with a five-constant static model of the
boost pair plus the node bleed. Table 2 lists the constants, which live in
`tools/hil_plant_sim.py` under the block titled "THE DP DEMAND MODEL'S STATIC-LOSS MAP".

| Constant | Value | Unit | Meaning |
|---|---|---|---|
| `DP_BUS_V0_EFF` | 15.871722 | V | no-load bus intercept of the boost pair |
| `DP_BUS_R_FIX` | 0.017986 | Ω | share-independent series resistance |
| `DP_BUS_K_G` | 1.95079 | Ω/unit | parallel droop code to source resistance |
| `DP_DROOP_G_PAR` | 0.148922 | – | the firmware-held parallel droop code |
| `DP_LOSS_MAP_PICARD_ITERS` | 30 | – | fixed-point iterations of the demand solve |

Two node conductances and two switch constants complete the model. The bleed conductances
are `g_node_bus` = 1/30 kΩ = 3.3333333333333335e-05 S and `g_node_other` = 1/60 kΩ =
1.6666666666666667e-05 S. The `MOT_PWR` switch drop uses `rt_v_fwd` = 0.035 V and
`rt_r_on` = 0.021 Ω, both taken from `tools/hil_electrical.py`.

The demand solve is a Picard iteration, run `DP_LOSS_MAP_PICARD_ITERS` times inside
`gen_dp_ems_table.build_demand()`:

```
i_motor = p_mech / (ETA_BOOST * V_bus)
V_MOT   = (V_bus - rt_v_fwd - rt_r_on*i_motor) / (1 + rt_r_on*g_node_other)
i_par   = V_bus*g_node_bus + V_MOT*g_node_other
I_total = i_motor + i_aux + i_par
V_bus   = v0_eff - (r_fix + k_g*g_par) * I_total
p_dem   = V_bus * I_total
```

`V_MOT` carries no switch indicator, because `MOT_PWR` is closed over the whole DP horizon.

## 3. The probe that fitted the map

### 3.1 Procedure

The fit is taken from the hi-fi `ElectricalSim` itself, not from a board trace. The engine
runs at `droop_mode="design"`, `asymmetry_mode="measured"`, `c_vesc_f=0.5e-3` and a substep
count pinned at 20 through the new `substep_pin` constructor argument, with battery SoC 0.7,
the switches `FC_BUS`, `BT_BUS`, `MOT_PWR` and `BT_SEQ` closed, and both boosts enabled.
Each point is a 1500-tick warm-up at zero motor current, then the operating point applied,
then a second 1500-tick settle, then 400 ticks averaged.

The grid sweeps `i_motor` over {0, 0.1, 0.2, 0.35, 0.5, 0.8, 1.1} A, `i_aux` over
{0.15, 0.61, 1.0} A and the droop code pair (g_fc, g_bt) over {(0.20, 0.20), (0.34, 0.34),
(0.50, 0.50), (0.22, 0.46), (0.46, 0.22)}, giving 105 main-arm points. A separate 15-point
charger arm is described in §5.

### 3.2 Identity checks

Three identities hold on the main arm to numerical precision, and each is pinned by a test.

- The excess source current `dI = i_fc + i_bt − i_motor − i_aux` equals
  `V_bus*g_node_bus + V_MOT*g_node_other` to a maximum residual of 4.09e-13 A.
- The `V_MOT` law of §2 holds to a maximum residual of 3.06e-13 V.
- Per code pair, `V_bus` is affine in `I_total` to a maximum residual of 1.9e-13 V.

The first identity establishes that the node bleed is the whole of the unaccounted source
current. The third establishes that a single slope per code pair is exact, so the only
modelling question left is how that slope depends on the codes.

### 3.3 Per-code-pair slopes

Table 3 gives the affine fit `V_bus = V0 − K·I_total` for each of the five code pairs,
ordered by the parallel droop code `g_par = g_fc·g_bt/(g_fc + g_bt)`.

| Code fc/bt | g_par | V0 (V) | K (V/A) |
|---|---|---|---|
| 0.20/0.20 | 0.100000 | 15.871792 | 0.212009 |
| 0.22/0.46 | 0.148824 | 15.873997 | 0.306732 |
| 0.34/0.34 | 0.170000 | 15.871725 | 0.348855 |
| 0.46/0.22 | 0.148824 | 15.869451 | 0.312147 |
| 0.50/0.50 | 0.250000 | 15.871645 | 0.505249 |

Table 3 shows that `V0` is constant to about 2 mV across the whole grid, and that `K` rises
monotonically with `g_par`, which is the structure the two-parameter form `r_fix + k_g·g_par`
assumes.

### 3.4 The global fit and its residual

The three-parameter fit over all 105 main-arm points gives the `v0_eff`, `r_fix` and `k_g`
of Table 2, with a residual of 3.478e-03 V rms and 1.033e-02 V maximum, which is 0.067 % of
`V_bus`. At the firmware-held `g_par` the map's effective slope is
`K_EFF = r_fix + k_g·g_par` = 0.308502 V/A, against the board's regressed 0.3015 to
0.3057 V/A.

**Stated approximation.** Under `--asymmetry measured` the realized slope is not a pure
function of `g_par`. Table 3's two mirror-image pairs 0.22/0.46 and 0.46/0.22 share
`g_par` = 0.148824 and realize K = 0.30673 and 0.31215, a ±0.9 % share dependence that the
map does not represent. The map is adopted with that dependence unmodelled, because
representing it would make `p_dem` a function of the share command, which §4 shows is the
one property the stage cost cannot give up.

## 4. The separability argument

**`p_dem` must not depend on the control, or the DP's stage cost is not separable.** It does
not, because the firmware holds the parallel droop code constant while it trades the split
between the channels. Table 4 measures that constancy over campaign `20260902_041414`, with
`g_par = g_fc·g_bt/(g_fc + g_bt)` and the codes recovered through
`hil_plant_sim.mdac_fraction()` from the CSV's `mdac_fc`/`mdac_bt` columns on Run-state rows.

| Scenario | Rows | g_fc range | g_bt range | g_par mean | g_par σ |
|---|---|---|---|---|---|
| `ems-dp-replay` | 54 999 | 0.2010–0.5958 | 0.1985–0.5756 | 0.148946 | 2.29e-05 |
| `ems-ftp75-dp` | 343 001 | 0.1983–0.5182 | 0.2090–0.5983 | 0.148922 | 2.79e-05 |
| `ems-soc-band` | 55 013 | 0.2010–0.9932 | 0.1751–0.5756 | 0.148922 | 4.76e-05 |
| `ems-sdp` | 55 006 | 0.1751–0.3477 | 0.2606–0.9932 | 0.148903 | 6.37e-05 |

Table 4 shows the individual codes moving over a factor of three while `g_par` holds to
better than 1e-04 across four scenarios and half a million rows.

**That constancy is STRUCTURAL, not empirical, and the distinction matters.** The droop gain
map the firmware writes is

```
    g_FC = K_DROOP / (RE_MAX · r)          g_BT = K_DROOP / (RE_MAX · (1 − r))
```

(`teensy_controller.ino`:10534–10535, mirrored in `governor_model._out`), where `r` is the
applied droop ratio. Their parallel combination is then

```
    g_par = g_FC·g_BT / (g_FC + g_BT)
          = [K_DROOP² / (RE_MAX²·r·(1−r))] / [K_DROOP/RE_MAX · (1/r + 1/(1−r))]
          = K_DROOP / RE_MAX
```

with `r` cancelling EXACTLY. The parallel code is therefore a constant of the firmware's
gain map rather than a fortunate property of the four traces above, and the residual σ of
2.79e-05 is the 12-bit MDAC quantization plus the [0, 1] clamp at the extreme ratios, not
model error. `K_DROOP / RE_MAX` = 0.30 / 2.013619 = 0.1489855 against the shipped
`DP_DROOP_G_PAR` = 0.148922 measured off the board, a 0.04 % agreement that is itself the
quantization.

A tripwire test in `tools/test_gen_dp_ems_table.py` pins the identity through the MDAC words
the firmware actually writes, so it asserts the mechanism and not a remembered number. If a
firmware or governor change ever breaks the cancellation and lets `g_par` move with the
share, the map's control-independence is gone and the DP must be re-derived rather than
re-fitted.

## 5. The charger arm, probed and not applied

The charger arm was probed with `FC_CHARGE_ENABLE` closed and `i_charge` swept over
{0, 0.5, 1.0, 1.5, 2.0} A at `i_motor` in {0, 0.35, 0.8} A. The `N_CHG` bleed adds
`V_CHG*g_node_other` to `i_par`, and `V_CHG` follows `V_bus − rt_v_fwd − rt_r_on·i_chg_in`
to 4.8e-06 V, where `i_chg_in = i_charge·V_pack/(ETA_CHG·V_chg)`. The full `i_par` identity
including the charger term holds to 2.3e-04 A.

**The charger term is deliberately not applied to the charge stage cost in this round, and
the reason is round scope rather than separability.** The distinction matters because the
separability argument of §4 is the load-bearing one. A charge-gated term is *not* a
separability blocker: the charge control is already a column of the DP's control set, so a
cost that depends on it is priced inside `step_charge()` exactly as the charger's own bus
draw already is, and the stage cost stays separable. What defers the term is that it belongs
with the regen term, which is the next round's work, and that landing half of a two-term
correction is how the two defects of §1 came to cancel in the first place. Omitting it
understates a charge stage by about 0.26 mA of bus current, which is 0.02 % of a charging
stage's demand.

## 6. Verification: the re-priced deviations

The verification re-prices both sides of the table-versus-run comparison. On the board side,
campaign `20260902_041414`'s traces are re-priced with the bleed energy that the new
per-node conductances no longer burn removed and share-weighted onto the two sources. On the
DP side, the demand is rebuilt with the shipped map. Table 5 gives the three configurations
per leg, and Table 6 the fourth, partial configuration that settles why both defects are
fixed together.

| Leg | Configuration | E_dem (J) | h2_dp (g) | h2_run (g) | Deviation |
|---|---|---|---|---|---|
| `ems-ftp75-dp` | today (no map, 2 kΩ bleed) | 2707.43 | 0.0364618 | 0.0380466 | +4.3463 % |
| `ems-ftp75-dp` | no map, new bleed | 2707.43 | 0.0370397 | 0.0369286 | −0.2999 % |
| `ems-ftp75-dp` | **shipped map, new bleed** | 2701.55 | 0.0369177 | 0.0369286 | **+0.0294 %** |
| `ems-dp-replay` | today (no map, 2 kΩ bleed) | 804.61 | 0.0118184 | 0.0117951 | −0.1979 % |
| `ems-dp-replay` | no map, new bleed | 804.61 | 0.0119031 | 0.0115904 | −2.6273 % |
| `ems-dp-replay` | **shipped map, new bleed** | 791.24 | 0.0116256 | 0.0115904 | **−0.3031 %** |

### 6.1 Why both defects are fixed together

The claim that fixing either defect alone makes the deviation worse is **not literally
true**, and the corrected statement is worth having because the argument for the round rests
on it. Table 6 adds the fourth configuration: the realized bus law with **no bleed term in
the demand**, against the plant at the shipped per-node bleed.

| Configuration | `ems-dp-replay` | `ems-ftp75-dp` |
|---|---|---|
| today (no map, 2 kΩ bleed) | −0.1979 % | +4.3463 % |
| bleed only (no map, per-node bleed) | −2.6273 % | −0.2999 % |
| bus law only (no bleed term, per-node bleed) | −0.1723 % | +0.2722 % |
| **both, the shipped map** | **−0.3031 %** | **+0.0294 %** |

The bleed-only row is the one that makes the case: it is worse than today on `ems-dp-replay`
by an order of magnitude. The bus-law-only row is **not** worse on that leg, and is in fact
the best of the four there (−0.1723 % against −0.1979 %); it is worse than the full map on
`ems-ftp75-dp` (+0.2722 % against +0.0294 %), so no single partial wins on both legs.

**The justification for shipping both is therefore bleed-invariance rather than deviation
alone.** With only the bus law corrected, the bound still bills no node bleed, so every
future bleed retune moves the run without moving its bound and the deviation becomes a
function of a `TODO(calibrate)` constant. With both corrected the two move together, which
is the property the round exists to establish and the one a second bleed move will test.

Table 5 confirms the joint fix. Both legs land inside ±0.31 % with the map applied, against
+4.35 % and −0.20 % before. The middle row of each pair is the argument against a partial
fix: the bleed change alone moves the 61 s cycle from −0.198 % to −2.627 %, because it
removes the cancellation Table 1 identifies without correcting the droop-mode term.

The bleed energy removed is 86.03 J to 4.31 J on FTP-75 at an FC energy share of 0.6592, and
14.68 J to 0.73 J on the 61 s cycle at 0.7073.

## 7. Era plumbing

The map is carried as a demand-model era, on the `eta_chg` precedent, so that every stored
artefact keeps its meaning.

- `hil_plant_sim.dp_loss_map(meta)` resolves the era. An **absent** `loss_map` key means the
  pre-2026-09-02 demand model and is named `None`.
- `hil_plant_sim.loss_map_for_config(electrical, droop_mode, asymmetry_mode)` returns the map
  only for `("hifi", "design", "measured")` and `None` otherwise. An `--electrical simple`
  run resolves to `None`, because the simple engine has no node network to bill and its bus
  law is deliberately unmoved.
- `hil_plant_sim.plant_loss_map()` mirrors `plant_eta_chg()`.
- `loss_map` joins `DP_FINGERPRINT_META_KEYS` and `DP_FINGERPRINT_OPTIONAL_KEYS`, so it is
  written as an **omitted line** in the old era. Verified: `ems-dp-replay` still fingerprints
  `02683031…` and `ems-ftp75-dp` still `403c5e71…`, unchanged; with the map they become
  `5adcfa78…` and `1295c5df…`. All 30 stored `tools/dp_db` records remain key-stable.
- `loss_map` joins `dp_results_db.KEY_FIELDS` and `OPTIONAL_KEY_FIELDS`, carried as the
  canonical string from `hil_plant_sim.loss_map_canonical()`.
- `hil_report_analysis.matched_dp_for_run()` resolves the map from the run's own
  `config.electrical` / `config.droop_mode` / `config.asymmetry`, exactly as it resolves
  `accounting` and `eta_chg`, and adds a `notes` entry naming the demand era on every run.
- New flags, all defaulting to `none`: `gen_dp_ems_table.py --loss-map {none,plant}`,
  `ems_walk.py --loss-map {none,plant}` and `dp_results_db.py prefill --loss-map {none,plant}`.
  The library defaults are `None`, so every pre-round regression anchor is preserved
  byte-identically. Campaign-facing callers pass the map explicitly.
- The three committed tables in `tools/dp_tables/` are regenerated as loss-map-era solves and
  carry a new `# loss_map:` header line. A loss-map-free table regenerates byte-identically.

## 8. Two pre-existing defects this round's re-measurement exposed

Neither belongs to the static-loss map. Both are recorded here because the round's
re-measurement of the MPC legs is what surfaced them, and both were already present at
commit `8dc180d`, before any change described above.

**The `ems-mpc-cross` share-motion floor was unsatisfiable.** The leg shipped
`share_range_min` = 0.12 against a plan whose commanded share spans 0.0833, over
[0.2500, 0.3333]. The check could therefore only ever have failed a correct run. It is 0.05
now, at about 0.6× the measured walk, which is the shape every other leg's floor uses.

**The `ems-mpc-cross` walk figure was stale by +29 %.** The leg shipped `walk_h2` = 0.014134
against a true pre-round walk of 0.010942, so its ±25 % band was centred 29 % high. It is
0.010835 now, re-measured under the shipped bindings and the loss-map demand era.

**The wide walk the cross stimulus was built for is not available from either law.** Both
`mpc-det` and `mpc-sto` command exactly 0.0833 of share on that stimulus, in both demand
eras, with bit-identical hydrogen (0.010942 loss-map-free, 0.010835 under the map). It
reproduces on the pre-round tree at `8dc180d`, where the leg still bound `mpc-det`, so it is
a consequence of neither the `mpc-sto` promotion nor the map. An `ems-mpc-det-cross`
ablation leg was built to keep the observable and then withdrawn: `mpc-det` reproduces
`ems-mpc-cross`'s trace bit for bit, so the leg would have spent about 200 s of every
campaign restating a known-null comparison under a description promising a walk it does not
produce. Recovering the wide walk is a question about the MPC's candidate ladder and its
terminal economics on a two-level cruise — the ladder coarsening that landed in `8dc180d` is
the first place to look — and it is not recoverable by registering a scenario.
`tools/test_run_hil_suite.py` pins the 0.0833 coincidence, so a ladder change that widens
the walk fails that test rather than passing unnoticed.

## 9. TODO

- `TODO(calibrate)` — the two bleed resistances the map is fitted against, `R_NODE_BLEED_BUS`
  = 30 kΩ and `R_NODE_BLEED_OTHER` = 60 kΩ, are uncalibrated. The bench procedure is the
  dark-node decay capture recorded at their definition site and in `docs/HIL_PLANT.md` §4.8.
  A second bleed move re-fits every constant in Table 2.
- `TODO` — the charger and regen terms of `i_par` (§5) are control-dependent and are deferred
  to the next round, together with the stage-cost treatment they need.
- `TODO(verify)` — the ±0.9 % share dependence of the realized slope (§3.4) is unmodelled and
  is the map's largest stated approximation.

---

## Addendum: the single-source bus law (2026-09-02, the MPC 0/1 round)

The bus law fitted above is a **two-source** law. Its `g_par` is the parallel droop code
`g_fc*g_bt/(g_fc+g_bt)`, and with one channel off the bus that parallel combination does
not exist. The MPC gains single-source candidates (share 0 and 1), which take one channel
off the bus through the setpoint latch, so it needs a law for that topology.

### Measurement

The hi-fi engine was probed at `--droop design --asymmetry measured` by sweeping the
auxiliary load over 0.15 to 1.6 A with the motor idle and regressing `V_bus` against the
source total. The engine solves a linear network at steady state, so the fit is exact to
the printed precision, with a maximum residual under 0.005 mV over four points. The probe
was repeated at three droop codes to establish that the result is a property of the
topology rather than of the operating point. Table A.1 gives the measurement.

| Droop code | `K` both (ohm) | `K` FC only (ohm) | ratio | `K` BT only (ohm) | ratio |
|---|---|---|---|---|---|
| 0.3499 | 0.35857 | 0.69775 | 1.9459 | 0.73764 | 2.0572 |
| 0.4999 | 0.50513 | 0.98258 | 1.9452 | 1.03955 | 2.0580 |
| 0.6999 | 0.70062 | 1.36249 | 1.9447 | 1.44225 | 2.0585 |

The no-load intercepts are 15.87821 V for FC only and 15.86468 V for BT only, against
15.87172 V for the two-source law.

### The law

The ratios hold to within 0.03 % over a factor-of-two code range, so the single-source
law is the two-source law with one scale factor on its slope and its own intercept.
`hil_plant_sim.single_source_bus_law()` is the single implementation.

```
    K_single = (R_FIX + K_G * g_par) * scale_mode
    V0_single = V0_mode
    scale_fc = 1.9453   V0_fc = 15.87821 V
    scale_bt = 2.0579   V0_bt = 15.86468 V
```

The two ratios are not both 2.000 because the two channels are not identical under
`--asymmetry measured`. That asymmetry is the whole 5.8 % spread between them, and using
a nominal 2.0 for both would misprice the BT-only arm by 2.9 %.

### Scope, and why these are not in the loss map

⚠️ **The four constants are MPC-only and are deliberately outside the loss map.** The map
is a fingerprinted era key (`hil_plant_sim.DP_FINGERPRINT_OPTIONAL_KEYS`), so adding
fields to it would move `loss_map_canonical()` and orphan every committed DP table and
every stored `dp_db` record. The DP and the SDP do not receive single-source candidates
(operator ruling, 2026-09-02), so nothing that consumes the map needs them.

The consequence at the operating point is not small: on the 61 s cycle the peak bus
voltage falls from 15.42 V two-source to 14.99 V FC-only and 14.92 V BT-only, so a
single-source stage planned on the two-source law would over-state the bus by roughly
0.45 V and under-state the source current correspondingly.
