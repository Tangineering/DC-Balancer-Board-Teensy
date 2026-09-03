# The static split law of the offline governor model (2026-09-03)

## 1. Scope

This note records the static law that maps an applied droop ratio to a delivered
fuel-cell share in the offline models of this repository, and the correction
applied to it on 2026-09-03. The law governs `tools/governor_model.py`
(`GovernorModel.delivered_share()` and its inverse) and the simple-mode plant
(`hil_plant_sim.Plant._apply_simple_asymmetry()`). The correction implements
findings PLANT-R2-F3, PLANT-R2-N1 and PLANT-R2-N2 of the adversarial physics
review of `docs/HIL_PLANT.md`, run 002
(`docs/reviews/hil-plant/run-002-2026-09-03.md`).

The firmware is not affected. The board's droop mathematics is correct; what was
wrong is the offline PREDICTION of what the board's droop network delivers. No
firmware file, no controller coefficient and no wire protocol changes.

## 2. The law

Each source is a Thevenin voltage behind its own realized droop resistance, and
each branch carries a series resistance that no droop command can scale. With
`r` the applied droop ratio (the fuel-cell fraction the firmware commands
through the two AD5443 gain codes), `k_d` the firmware droop constant
`K_DROOP` = 0.30 ohm, `rho` the fuel-cell channel's droop-resistance multiplier
and `R_f` the common series resistance:

    R_FC  = rho * k_d / r     + R_f
    R_BT  =       k_d / (1-r) + R_f
    alpha = (dV0 / I_tot + R_BT) / (R_FC + R_BT)

`alpha` is the delivered fuel-cell fraction of the source total `I_tot`, and
`dV0 = V_0F - V_0B` is the static no-load voltage mismatch between the two boost
chains. The three parameters carry the plant's values:

| symbol | source | value |
|---|---|---|
| `dV0` | `hil_electrical.ASYM_DV0_V` | 0.013522 V (0 with `--asymmetry off`) |
| `rho` | `ASYM_DROOP_SCALE_FC / ASYM_DROOP_SCALE_BT` | 0.9434 (1.0 with `--asymmetry off`) |
| `R_f` | `hil_electrical.DROOP_FIXED_SERIES_OHM` | 0.033 ohm (BOTH modes) |

`R_f` = 0.010 (boost Thevenin term) + 0.021 (RT1987 pass FET) + 0.002 (INA253
shunt). `dV0` and `rho` are the two parameters of ONE fit, the M2 consistent
pair of `docs/modeling/converter_asymmetry_20260901.md` section 9, and must move
together. `R_f` is not part of that fit: it is physics present on every board in
every configuration.

`rho` is a RATIO of the two channels' droop-resistance multipliers, not the
fuel-cell multiplier alone. `ASYM_DROOP_SCALE_BT` is 1.000 in the present fit,
so the two readings coincide numerically; the resolvers and the simple-mode
plant nevertheless compute the quotient, so that a later fit which moves the
battery channel cannot give the split law a rho the engine does not realize.

At `dV0 = 0`, `rho = 1` and `R_f = 0` the law reduces to `alpha = r` exactly.
Those are the constructor defaults, so every caller that predates the two new
parameters is bit-identical.

## 3. The inverse

The closed loop's integral action finds the ratio that delivers a commanded
share, so the model needs the inverse. Multiplying
`alpha*(R_FC + R_BT) = dV0/I_tot + R_BT` through by `r*(1-r)` gives a quadratic
`A*r^2 + B*r + C = 0` with

    P = (2*alpha - 1) * R_f - dV0 / I_tot
    A = -P
    B =  P + k_d * (alpha * (1 - rho) - 1)
    C =  alpha * rho * k_d

At the trivial parameters `A -> 0`, `B -> -k_d` and `C -> alpha*k_d`, so the
physical root is the one tending to `-C/B = alpha`. It is evaluated through the
stable pairing `q = -(B + sign(B)*sqrt(B^2 - 4AC))/2`, `r = C/q`. The textbook
`(-B + sqrt(D))/(2A)` form cancels catastrophically as `A -> 0`, and `A` is
small on every physical parameter set (`|A| <= 0.05` over the whole operating
range, against `|B|` of about 0.3). The degenerate branches are handled as the pre-2026-09-03 code handled
them: a negative discriminant or a vanishing leading pair returns `alpha`
rather than raising.

## 4. What was wrong, and by how much

The shipped law was `alpha = r + dV0*r*(1-r)/(k_d*I_tot)`, i.e. the `dV0` half
of the M2 fit with `rho` pinned at 1 and no series term. The simple-mode plant
carried the identical expression and described itself as "the M1 model with
rho = 1" while being fed M2's `dV0`, which is the pairing the fit document
explicitly rejects (M1's `dV0` is 0.0444 V, not 0.013522 V).

Two consequences, both measured:

1. The inverse mis-predicted the droop ratio by up to +10.5 % at low share.
   Every walk-derived MDAC pin was an output of that law.
2. The map was wrong with the asymmetry OFF as well, by up to 0.0096 of share at
   the droop band's rails, because `R_f` is era-independent and the old law had
   no term for it at all.

## 5. Validation

### 5.1 The board (campaign F, `hil_report_20260903_063659`)

Converged windows of `fw26-clamp-sweep` and `fw26-clamp-cruise`, scored over
each region's settled window. `r` is derived from the two MDAC command words as
`g_BT/(g_FC + g_BT)`; `alpha` is `I_fc / (I_fc + I_batt)`.

| window | `alpha` | `I_tot` [A] | board `r` | full law `r` | error | dV0-only `r` | error |
|---|---|---|---|---|---|---|---|
| sweep region 12 | 0.500005 | 1.2008 | 0.475805 | 0.475808 | +3.5e-06 | 0.490624 | +3.11 % |
| sweep region 5 | 0.399996 | 1.8417 | 0.374986 | 0.374953 | -3.3e-05 | 0.394152 | +5.11 % |
| sweep region 7 | 0.200010 | 2.0362 | 0.177878 | 0.177817 | -6.1e-05 | 0.196515 | +10.48 % |
| sweep region 1 | 0.750162 | 1.2008 | 0.742468 | 0.742577 | +1.1e-04 | 0.742994 | +0.07 % |
| sweep region 10 | 0.500001 | 1.2869 | 0.476448 | 0.476448 | -2.6e-07 | 0.491247 | +3.11 % |

The two laws converge near `r = 0.74`, where the `rho` and `R_f` terms cancel;
that is why regions 1 and 8 passed their pins under the old law and region 12
did not.

### 5.2 CAL-1

`docs/modeling/converter_asymmetry_20260901.md`, delivered share at a commanded
ratio of 0.5 at three totals (0.452 / 0.935 / 1.346 A giving 0.5354 / 0.5262 /
0.5327). RMS share error: **0.006414** for the full law at the plant's
constants, against **0.0063** for the fit that produced them and **0.0173** for
the `dV0`-only pairing.

### 5.3 The hi-fi engine's DC solve

`hil_electrical.ElectricalSim` settled at three commanded ratios with both
channels live, asymmetry measured, droop design, at a 1.65 A total: the closed
form agrees with the network solve to **9.3e-05** of share (r 0.20 / 0.50 / 0.80
give engine 0.224142 / 0.520435 / 0.802891 against model 0.224229 / 0.520431 /
0.802798). The acceptance is 1e-3.

### 5.4 The inverse

Against a bisection of the forward law at 49 points spanning the droop band and
0.3-4.0 A: maximum |dr| **3.3e-16**. Round-tripping the forward law over the
same grid: maximum |dr| **2.2e-16**.

## 6. The open question: `--droop measured`

The hi-fi engine realizes each channel's droop resistance as
`DROOP_SCALE[mode] * k_d`, while `R_f` is deliberately NOT scaled by the mode
(that is the reason `DROOP_SCALE["measured"]` = 0.21171 is derived with the
floor subtracted from both sides). The engine also scales the injected `dV0` by
the same mode scale. The model, by contrast, carries the FIRMWARE's design
`k_d` = 0.30 ohm, because the same attribute maps the MDAC gain codes and must
stay at the value the board commands.

Consequently the model and the plant agree EXACTLY under `--droop design`
(scale 1.0), which is what every campaign on record runs, and diverge under
`--droop measured`. The exact resolution is algebraic and is recorded here
rather than shipped: dividing numerator and denominator of the law by the mode
scale `s` shows that the plant's law is reproduced by the model at

    r_series_ohm = R_f / s,   dv0_v = dV0_injected / s

that is, at 0.1559 ohm and the unscaled fit value 0.013522 V for
`s` = 0.21171. It is not shipped because `dv0_v` has one owner
(`resolve_asymmetry_dv0_v()`), whose contract is "the DeltaV0 the run actually
injects" and which the run banner and the sidecar also read; changing that
quantity to a per-consumer scaled value would give one number two meanings.
`TODO(verify)`: settle whether the resolver should return a droop-mode-scaled
pair to the governor model specifically, or whether `GovernorModel` should
accept a fourth, law-only `k_droop_realized`. Until then, a `--droop measured`
walk or MPC run carries a known split-law error and must not be compared with a
`--droop design` one on delivered share.

The unresolved state is announced rather than left silent. `hil_plant_sim`'s
`main()` prints one ASCII `[hil] WARNING:` line beside the asymmetry banner
whenever `droop_mode` is not `design`, stating that the offline governor map is
exact only under `--droop design`, quoting the 16 % relative error at `r` 0.20
and 1.5 A, and citing this section. `ems_walk.py` exposes no droop mode at all,
so its `--r-series` help carries the same statement. Two tests pin the
presence of the warning under `measured` and its absence under `design`.

## 7. Committed numbers that moved

| number | old | new | why |
|---|---|---|---|
| `run_hil_suite._FW26_SWEEP_MDAC_PIN[1]`, `[8]` | (4917, 6468) | (4917, 6464) | re-walked; board 4917 / 6463 |
| `run_hil_suite._FW26_SWEEP_MDAC_PIN[12]` | (5339, 5293) | (5378, 5259) | re-walked; board 5378 / 5260. The old pair was 3.1 % away on a 2 % band and FAILED in campaign F |
| `run_hil_suite._FW26_SWEEP_MDAC_PIN[10]` | absent | (5376, 5261) | ADDED; board 5376 / 5261 (exact). The only sub-threshold region commanded at share 0.50, where the correction is largest |
| `run_hil_suite._FW26_SWEEP_MDAC_CLAMPED_PIN[2]` | ((5088, 5679), (4824, 7837)) | ((5100, 5648), (4822, 7895)) | re-walked; board 5110 / 5626, so the error falls from 2.2 % / 3.5 % to 1.0 % / 1.4 % |
| the walked 12-region table in the `fw26-clamp-sweep` entry | — | regenerated | every `mdac` column moved; no current moved |
| `fw26-clamp-cruise` phase-A `r_applied` (test pin) | 0.6197 | 0.6125 | board 0.612185; the old value was +1.2 % away |
| the UNBRIDGED region-6 peak in `hil_plant_sim` | 1.7223 A | 1.7120 A | re-walked; every bridged figure is unchanged to four decimals |
| simple-mode delivered share | — | up to +0.021 | see section 8 |

Region 10's pin takes a 5 % code band rather than the standstill 2 %, because
its total carries a 0.0844 A drive-loop term at 0.5 m/s. The walk reproduces the
board's region-10 pair exactly and the neighbouring 0.5 m/s region 3 to within
two codes, so the band is roughly 150 times the observed model error.

## 8. What did NOT move, and why

- **The DP bus law `DP_BUS_K_G` and the DP tables.** `K_G` was fitted on a
  120-point probe of the HI-FI engine with the asymmetry on. The governor's
  static law is nowhere on that path, so it cannot move the fit. The review
  adjudication rejected re-deriving it; `tools/gen_dp_ems_table.py` is
  byte-identical and its `delivered_share()` at line 324 is the fw v26 CEILING
  helper, a different function with the same name.
- **The h2 bound bias.** Bounded at 0.05 % on `ems-sdp` (interior) and 0.2 % on
  a rail-pinned leg, inside the +/-0.8 % comparison tolerance.
- **The fw v26 safety condition.** The necessary two-source total for the
  clamp's step-transient race recomputes from 1.647 A to 1.645 A, a 1.7 mA
  move. No registered stimulus approaches either.
- **The 1.2500 A cruise calibration and every clamp current.** The clamp pins a
  CURRENT; the split law moves only the RATIO that delivers it. Every current
  in the sweep's region table is unchanged to four decimals.
- **The firmware, its tests, `share_controller_coeffs.h` and the wire
  protocol.**

## 9. The MPC's Gate 1

Gate 1 (`docs/modeling/mpc_design_20260901.md` section 7.1) accepts a mean
absolute delivered-share prediction error of 5e-03 over the `ems-soc-band`
walk. Measured on this host, in one session, with the harness
`ems_walk.walk(strategy, "ems-soc-band", soc0=0.7, governor=True)`:

| plant law | strategy map | strategy | mean | maximum | verdict |
|---|---|---|---|---|---|
| full | full (matched) | `mpc-det` | **0.000740** | 0.026648 | PASS |
| full | full (matched) | `mpc-sto` | 0.007603 | 0.118589 | FAIL |
| full | none (inert) | `mpc-det` | 0.020045 | 0.071309 | FAIL |
| full | none (inert) | `mpc-sto` | 0.023318 | 0.121932 | FAIL |
| full | dV0 only (the pre-fix campaign) | `mpc-det` | 0.008927 | 0.032414 | FAIL |
| full | dV0 only (the pre-fix campaign) | `mpc-sto` | 0.016006 | 0.118463 | FAIL |
| dV0 only | dV0 only (both) | `mpc-det` | 0.000779 | 0.028885 | PASS |
| dV0 only | dV0 only (both) | `mpc-sto` | 0.007528 | 0.118574 | FAIL |

The threshold was not changed. Two readings:

1. **The fifth row is the exposure this round closes.** A campaign whose plant
   carries the full law while the planner carries only `dV0` reads 0.008927 for
   `mpc-det` — a Gate-1 FAIL — where the matched configuration reads 0.000740.
2. **`mpc-sto` still fails**, at 0.007603 against 0.007528 before the change.
   The residual is unchanged in kind: one `open_hold` stage carrying 0.1186,
   which is the stochastic variant's conditional-mean demand forecast on a
   deterministic stimulus, not a delivery-model residual. This reproduces the
   0.009019 recorded in `mpc_design_20260902_nonlinearities.md`; the walk is
   wall-clock budgeted, so absolute values differ between hosts and only rows
   measured in one session are comparable with each other.

Gate 1 as harnessed compares the strategy's map against a walk whose plant IS
`GovernorModel`, so it cannot by itself detect an error in the law they share.
The board comparison of section 5.1 is what detects that, and it is why the
campaign-F MDAC pins are the discriminating evidence for this round.
