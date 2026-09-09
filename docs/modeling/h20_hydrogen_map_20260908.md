# The H-20 hydrogen consumption map (2026-09-08)

Design record for `tools/h2_map.py`, the convex hydrogen map that replaces the full-size
`Gfc` DC gain as the bench tooling's scored fuel estimator.

Scope of this note: the derivation, the decisions taken, what changes for the energy
manager, and the work explicitly held to a later phase. It does not re-derive `alpha`,
re-fit the electrical fuel-cell source, or move any suite expectation band.

---

## 1. Why the linear map was replaced

The tooling scored every strategy on `Gfc`, a 106 kW fuel-cell consumption transfer
function taken verbatim from the PhD student's FCHEV dynamic-programming study, reduced
to its DC gain `H2_GFC_DC_GAIN_GPS_PER_W = 1.7637602179836514e-05` g/s/W for the DP, the
SDP and the walk. Two problems, and the second is decisive.

1. It was never identified against this stack. The `TODO(calibrate)` had stood since the
   model was ported, and the extrapolation is 5300x in rated power.
2. It is linear, and the decision is not. A constant g/s per W states that a watt costs
   the same hydrogen wherever the stack is running. The real stack's lower-heating-value
   efficiency peaks and then falls, so the central question an energy manager answers,
   where on the curve to run the stack, was invisible to the objective. Under a linear
   cost the split decision is degenerate: the hydrogen term is proportional to the
   fuel-cell share, so the only lever with structure is the state-of-charge term.

The H-20 map is derived from the brochure of the stack that is actually fitted. It is the
right part; it is not yet this individual sample.

## 2. Source

`references/H20-Small-Stacks-Brochure.pdf`, the H-20 block:

| Quantity | Value |
|---|---|
| Cells in series | 13 |
| Rated power | 20 W |
| Rated operating point | 7.8 V at 2.6 A (20.28 W) |
| Hydrogen flow at maximum output | 0.28 L/min |
| System efficiency at full power | 40 % |
| Blower supply | 5 V |
| Purge valve supply | 6 V |
| Polarization curve | printed U-I plot, digitized below |

## 3. Derivation

### 3.1 Faraday's law

    K_FARADAY_GPS_PER_A = N_CELLS * M_H2 / (2 * F)
                        = 13 * 2.016 / (2 * 96485.33)
                        = 1.3581339256444477e-04 g/s per A

The stack is a series string, so one current passes through every cell and each cell
consumes its own hydrogen: the cell count multiplies. No fit and no rig constant enters
this term.

### 3.2 The reference state: STP, not NTP

The brochure quotes flow in L/min without naming a reference state, and the two
candidates differ by 7 %. The brochure's own efficiency figure settles it:

| Density | Value | Implied efficiency at rated output |
|---|---|---|
| STP, 0 C / 1 atm | 0.08988 g/L | `20.28 / (0.28 * 0.08988 / 60 * 120000)` = **0.403** |
| NTP, 20 C / 1 atm | 0.08375 g/L | 0.432 |

0.403 reproduces the printed 40 %; 0.432 does not. The map therefore uses
`RHO_H2_G_PER_L = 0.08988` and `Q_LHV_J_PER_G = 120000` (the same heating value the
student's proxies use, so an efficiency quoted here and one quoted there are on one
basis). `h2_map.check_rated_efficiency()` recomputes the ratio on demand.

This is the most leveraged single assumption in the map, because it scales the offset
term directly.

### 3.3 The constant offset

    FLOW_RATED_GPS = 0.28 * 0.08988 / 60          = 4.1944e-04 g/s
    A0_OFFSET_GPS  = FLOW_RATED_GPS - K * 2.6     = 6.632517933244359e-05 g/s

The offset carries the periodic purge valve venting unreacted hydrogen, the stack-fed
blower, and the module's own controller. The brochure gives the total flow at rated
output and nothing that splits it, so the offset is a residual.

**Decision (operator, 2026-09-08): a constant offset.** Not a purge duty cycle, not a
load-dependent parasitic. It is the only split the brochure supports, and inventing a
duty cycle would be exactly the class of unsourced constant this repository has had to
retract before.

`TODO(bench)`: time the purge valve's interval and duration, measure the blower and
controller draw, then re-derive the offset as a sum of measured terms rather than as a
residual. That measurement also tests the STP assumption independently.

### 3.4 The polarization curve

Digitized from the brochure's printed U-I plot, plus the nameplate anchor (a printed
number rather than a read off the plot) weighted 4x:

| I [A] | V [V] | weight |
|---|---|---|
| 0.00 | 12.2 | 1 |
| 0.25 | 11.3 | 1 |
| 0.50 | 10.7 | 1 |
| 1.00 | 10.0 | 1 |
| 1.50 | 9.5 | 1 |
| 2.00 | 9.1 | 1 |
| 2.50 | 8.5 | 1 |
| 3.00 | 7.9 | 1 |
| 3.40 | 7.0 | 1 |
| 2.60 | 7.8 | **4** (nameplate) |

Fitted form and shipped coefficients:

    V(I) = V0 - b * ln(1 + I/i0) - R * I
    V0 = 12.200 V,  b = 0.258 V,  i0 = 0.023 A,  R = 1.183 ohm

with `V(2.6 A) = 7.902 V` against the nameplate 7.8 V, and an unweighted RMS of 0.268 V
over the ten points. Reading points off a printed curve is worth about +/-0.15 V, so the
residual is the curve's own shape rather than the digitizing.

**Concentration losses are not given a term.** The curve ends at 3.4 A and shows the
mass-transport knee only in its last point, so a fourth parameter would be fitted to one
datum. The map therefore under-reads consumption near 3.4 A, which is the optimistic
direction there. It does not matter on this rig: 3.4 A is 2.7x the fw v26 fuel-cell
ceiling of 1.25 A.

**The refit does not return the shipped coefficients, and that is expected.**
`h2_map.refit_polarization()` re-runs the weighted least-squares fit with scipy. From
three different starting points, including the shipped set itself, it converges to
`(12.2006, 0.1972, 0.008295, 1.16702)` with an unweighted RMS of 0.2085 V. The residual
surface has a long flat valley in `(b, i0)`: the activation term trades curvature against
scale almost exactly, so many pairs fit the ten points about equally well. The two curves
differ by at most **0.159 V** anywhere on [0, 3.4] A and the resulting hydrogen rates by
under **2.2 %** across [0.1, 20.28] W. A test should assert the functional agreement, not
the individual coefficients: pinning `b` and `i0` pins a point in a flat valley, and a
scipy version bump could move it without anything physical changing.

### 3.5 The map

    P(I)    = V(I) * I,  strictly increasing on [0, 3.40 A]
    I_PMAX  = 3.40 A     (the curve's last digitized point, not a turning point)
    P_MAX   = 23.4161 W
    rate(P) = A0 + K * I(P)

`I(P)` is the inverse, evaluated on a 2049-point monotone table built once at import.
The 1 kHz plant path bisects it (stdlib, allocation-free); the DP, SDP and MPC table
builds interpolate the **same** table with `np.interp`, so the two paths cannot price a
stage differently. Linear interpolation of the inverse on that grid errs by under 3e-6 A,
six orders below the offset term.

Negative power is clamped at zero. Power above `P_MAX` is clamped to `I_PMAX` and flagged
`saturated`: the returned rate is then a **floor**, not an estimate, because the real
stack past its curve either sags further or cannot deliver.

**Above `P_MAX` the offline solvers treat the control as INFEASIBLE, not merely
expensive** (2026-09-08, review item A1). The reason is an argmin hole rather than a
modelling nicety: where the map is flat the marginal hydrogen cost of extra fuel-cell
power is exactly zero, while the state-of-charge term keeps rewarding it, so an argmin
walks straight to a control the stack cannot deliver. `gen_dp_ems_table.solve_dp()`
refuses such cells on **both** arms (split and charge) and `sdp_ems_solver.build_stage()`
does the same. The census each prints is therefore a **ceiling-disagreement tripwire**,
not a "should be zero" check: it counts only cells the current limits would have
admitted, so a non-zero count states that the map's ceiling bound before the firmware's.

**Which ceiling binds, in numbers.** `P_MAX` = 23.416 W of stack power is 19.90 W on the
bus through `ETA_BOOST` = 0.85, i.e. **1.247 A** of bus current at 15.95 V. Against it:

| Ceiling | Bus current | Stack power | Binds first? |
|---|---|---|---|
| H-20 `P_MAX_W` | 1.247 A | 23.416 W | **yes** |
| fw v26 clamp `SHARE_GOV_I_FC_CEIL_A` | 1.250 A | 23.46 W | no, by 0.04 W |
| firmware `LIMIT_I_FC_MAX_A` | 1.400 A | 26.27 W | no, by 12 % |

So the `fw26-clamp-*` legs sit **on** the boundary by design, and the firmware's own
current limit does **not** keep a solve inside the brochure curve. A saturation count on
a clamp leg is an ordinary reading; anywhere else it is a statement about the demand
model. The plant does not refuse — `H2Consumption.saturated_ticks` counts and keeps
running, because a plant reports what happened rather than choosing a control — and the
offline walk does not refuse either, for the same reason (`WalkResult.h2_saturated_stages`
and a note on the result).

## 4. What the map says

| P_stack [W] | I [A] | rate [g/s] | eta_LHV | d(rate)/dP [g/s/W] |
|---|---|---|---|---|
| 0 | 0.0000 | 6.6325e-05 | idle offset | 1.115e-05 |
| 1 | 0.0855 | 7.7934e-05 | 0.107 | 1.192e-05 |
| **3 (rig median)** | 0.2671 | 1.0261e-04 | **0.244** | 1.272e-05 |
| 5 | 0.4600 | 1.2879e-04 | 0.324 | 1.348e-05 |
| 10 | 0.9956 | 2.0154e-04 | 0.414 | 1.577e-05 |
| **14.75 (eta peak)** | 1.6022 | 2.8393e-04 | **0.433** | 1.925e-05 |
| 20.28 (rated) | 2.5428 | 4.1167e-04 | 0.411 | 2.882e-05 |
| 23.4161 (`P_MAX`) | 3.4000 | 5.2809e-04 | 0.370 | 5.202e-05 |
| 25 | 3.4000 (clamped) | 5.2809e-04 | saturated | saturated |

Quadratic summary over [0, 20.28] W, uniform in P, 2001 points, unweighted:

    a0 = 6.9843e-05,  a1 = 9.8004e-06,  a2 = 3.3062e-07,  max relative error 5.30 %

`h2_map.quadratic_fit()` returns it and `h2_map.student_form()` packages
`(a0, p_peak, eta_peak) = (6.9843e-05, 14.752 W, 0.4329)` for the MPC's `convex` branch.
The fit is a reporting and handoff form only. Nothing minimises it, its worst error is at
low power where the rig lives, and it is grid-dependent at the 2 % level (a grid uniform
in current moves `a1` by about 3 %), so a quoted coefficient triple is only reproducible
with its grid.

## 5. Decisions taken this round

| # | Decision | Rationale |
|---|---|---|
| 1 | **Constant-offset loss model** | the only split the brochure supports (section 3.3) |
| 2 | **No stack-shutdown state; the tooling carries a hook** | the firmware has none and none is planned. `stack_on` is per-call and wired to the board's `FC_REG_ENABLE` mirror (observation aux bit 0); `h2_map.SHUTDOWN_ENABLED` is a module policy, `False`, set nowhere. Both default to *running*, so an idling stack still burns `A0` |
| 3 | **`Gfc` kept and documented, dropped as the scored estimator** | it is the only *dynamic* consumption model available and it is every archived campaign's headline number. It is logged as `h2_gfc_cum_g` so the two eras stay cross-readable |
| 4 | **The eta 0.5 SDP proxy column is untouched** | `h2_sdp_cum_g` is the axis the student's own work is stated on |
| 5 | ~~The SDP's stage cost stays bus-side for one round~~ **REVERSED the same day** (review item A3): `build_stage()` bills **stack-side** `P_fc/ETA_BOOST`, matching the DP, the plant and the MPC | the bus-side argmin-neutrality argument is void under a convex map, and phase B re-solves the SDP against a re-derived alpha regardless, so keeping a knowingly wrong basis for one round bought nothing. See section 7 item 2 |
| 6 | **Both offline solvers carry a hydrogen-law selector** (review item A4): `gen_dp_ems_table --h2-map {h20, gfc-linear}` and `sdp_ems_solver --h2-map {h20, eta-proxy}` | the same era-switch pattern `--eta-chg` and `--drag` use. The legacy branches reproduce the pre-2026-09-08 stage costs **expression for expression**, so an archived table or policy regenerates byte-for-byte instead of being reproduced from memory |

## 6. What changes for the EMS

**The rig operates far below the efficiency peak.** The median stack-side power is about
3.2 W, where the map says 24 % efficiency; the peak is 43.3 % at 14.75 W. Under the old
linear cost that gap did not exist. It is now the first-order structure of the problem,
and it is what makes the split decision non-degenerate.

**The marginal rate spans 2.4x** across the operating range (1.19e-05 g/s/W at 1 W to
2.88e-05 at 20.28 W). Every downstream constant that was a ratio against a constant
`k = 1/(eta * Q_LHV)` now has to answer for that, which is most of the phase-B list.

**The idle offset is real cost.** A run that leaves the stack running for 340 s vents
about 22 mg whatever the split does. It cannot move a stage's argmin (it is identical on
every control of a stage) but it belongs in the totals, and a strategy that idles the
vehicle a lot is no longer free.

**And the offset is LARGE relative to the differences strategies produce.** At the rig's
median stack power of 3.2 W the map's rate is 1.03e-04 g/s, of which the constant
`A0_OFFSET_GPS` = 6.633e-05 g/s is **63 %**; over an FTP-75 walk the offset is about
**56 %** of the whole hydrogen total. Two consequences, and both bear on how a campaign
is read:

* Inter-strategy hydrogen differences — which have historically been fractions of a
  percent — are now differences in the *minority* term of the total. A 1 % gap between
  two strategies on the old linear axis is roughly a 0.44 % gap on this one, because
  more than half of each total is a constant neither strategy can move.
* **The frontier noise floor must therefore be re-measured on this axis** before any
  ranking is quoted. The same-configuration reproducibility floor recorded for the linear
  era (~65 ppm within a campaign, ~250 ppm typical across campaigns) is a floor on a
  different quantity. Phase B.

**⚠️ THE PLANT AND THE OFFLINE MODELS BILL DIFFERENT WINDOWS.** `Plant.step()` calls the
map from **State 0** onward — `FC_REG_ENABLE` is raised in Init and stays up through Idle
and Run — so a run's `h2_cum_g` is a **whole-run** total that includes
`A0 * t_run_entry` of Init/Idle idling: about **1.7 mg of a 16.5 mg `ems-sdp` run**,
i.e. ~10 %. The DP generator, the SDP solver and the offline walk bill the **Run window
only**. A comparison between a run's `h2_cum_g` and a DP bound, and every suite
expectation band, must therefore use the **Run-window figure** (`h2_cum_g` at the run
exit minus `h2_cum_g` at run entry), never the final value. Re-deriving the suite's bands
on that basis is phase B; nothing in this round moved a band.

**`FC_REG_ENABLE` is a PROXY for "the stack is in service", not a measurement of it.**
Physically the H-20 module's blower and purge valve keep running whenever the module is
powered: disabling the boost regulator stops the stack *delivering*, not the stack
*breathing*. The firmware has no stack-shutdown line at all (decision 2 in section 5), so
the honest reading of the gate is "the EMS is not drawing from the stack", and billing
`A0` through such a span would be the other kind of wrong. The choice touches **only
ticks outside Run**: `FC_REG_ENABLE` is raised in State 0 and lowered in State 99
phase 2, so Init, Idle and Run all bill `A0` and only a latched-error tail does not.

**The charge action got relatively more expensive.** The charger's bus draw sits on top of
the traction demand, so it is priced at a higher point on the curve than the traction
watts underneath it. Under the linear proxy the two had identical marginal prices.

**The ceiling is close to the rig's own demand.** `P_MAX` is 23.416 W and the fw26 clamp
legs demand roughly 23.5 W stack-side at their peak. Those legs will touch saturation;
the census printed after a DP solve and `H2Consumption.saturated_ticks` in the run banner
are the evidence to check before quoting such a run's total.

**The electrical `FuelCellSource` was NOT refitted.** It keeps its own polarization
constants, so the plant's electrical fuel cell and its hydrogen map are presently two
curves for one stack. Reconciling them is a **separate follow-up round** and is
deliberately not in this change: it moves plant behaviour (currents, bus voltages, every
anchor), whereas this change moves only an observer column and the offline objectives.

**The two-curve gap, and why the map inverts P(I) instead of using the plant's own
current.** `Plant.step()` hands `H2Consumption` the product
`fuel_cell.v_terminal * fuel_cell.i`, and the map then inverts *its own* brochure curve
to recover the current Faraday's law needs. That looks like a detour — the plant already
has a current — and billing `A0 + K_FARADAY * fuel_cell.i` directly was proposed in
review and **rejected**, on two grounds:

1. **`FuelCellSource` is the less accurate curve.** It carries 12 cells and about
   0.45 ohm, fitted before this round and against nothing in particular; Faraday's law on
   its current would under-read the real H-20 by roughly **20 % at 1 A**. Faraday is exact,
   but only on the *right* current.
2. **It would break the one property the matched-DP bounds rest on.** The plant, the DP
   generator, the offline walk and the MPC all bill **one function of stack power**. A
   plant that billed its own current while the DP billed a power map would make every
   run-versus-bound deviation a mixture of policy and of two curves disagreeing, which is
   exactly the confound the shared `h2_map` module exists to remove.

The `P -> I` inversion is therefore deliberate. The follow-up that closes the gap
properly is the `FuelCellSource` refit (section 7, item 8), after which the plant's
electrical current and the map's inverted current are the same number and the choice
stops mattering.

## 7. Held to phase B

None of the following was done in this round, by decision: doing any of them in the same
change would make the resulting policy shift unattributable.

1. **The SDP's `alpha`.** The whole derivation in `sdp_ems_solver.ALPHA_DERIVATION`
   rests on a constant marginal rate `k = 1/(eta_fc * Q_LHV)`. The stage cost's marginal
   rate is now operating-point dependent, so every shipped `sdp_policy_*.json` alpha is a
   pre-convex-map number used against a convex objective. The solver prints a one-line
   warning on every k-dependent `--alpha-mode`. Phase B: re-derive against a marginal
   rate evaluated at the policy's own mean (or demand-bin-weighted) operating point.
2. ~~**The SDP's bus-side basis.**~~ **DONE 2026-09-08** (review item A3): the solver
   bills `P_fc/ETA_BOOST`, stack-side, like everything else. The recorded argument for
   leaving it bus-side was that a uniform `1/ETA_BOOST` factor cannot move the argmin,
   which holds **only for a linear map** — under a convex one the division selects the
   operating point. What remains outstanding is the **alpha** half of the pair (item 1),
   and the size and direction of that mismatch are now stated rather than merely flagged:
   alpha is calibrated at `k = 1/(eta_fc*Q_LHV)` = 1.667e-05 g/s/W while the map's
   marginal rate at the solver's own operating point (~3 W stack) is 1.272e-05, so **k is
   ~31 % high and the state-of-charge term is ~30 % over-weighted** relative to the fuel
   term. The bias is toward less discharge and more charge admission than a re-derived
   alpha would give. The **D12 admission-window tripwire is likewise in the retired
   basis** — its lever prices are grams of the old linear law — so a "window: INSIDE" line
   on a post-2026-09-08 artifact says nothing about charging under the current objective.
3. **The eq-H2 lever prices.** `L_share`, `L_chg` and the suite's
   `EMS_EQ_H2_LAMBDA_SOC_PER_G` are all grams-per-SoC exchange rates against the old
   linear gram.
4. **Matched-DP re-solves.** Every record in `tools/dp_db/` is keyed on the hydrogen law
   (`model_fields()` now records `h2_map`), so all of them are unreachable by a current
   lookup. That is intended — a baseline solved on a linear cost is not a baseline for a
   convex one — but it means the whole store needs re-solving.
5. **The committed DP tables.** `tools/dp_tables/*.csv` have no `h2_map` header line and
   `hil_plant_sim.load_dp_table()`'s drift guard now refuses them. They must be
   regenerated before any `dp-replay` leg runs.
6. **The suite's hydrogen expectation bands.** `tools/run_hil_suite.py` was deliberately
   not touched; every `h2_cum_g` band in it is stated against the retired map. They must
   also be restated on the **Run-window** figure rather than the whole-run one (section 6).
7. **`H2_BASIS_REF_P_STACK_W`.** The MPC's basis conversions — the `sdp-shadow` terminal
   mode's, and `RHO_METRIC_G_PER_SOC_H20`'s (see item 9) — are referred to a 3.2 W design
   estimate of the rig's median stack power. `TODO(calibrate)`: re-derive it from a
   campaign's own `p_fc_w` column median. `sdp_ems_solver.ALPHA_MISMATCH_REF_P_STACK_W`
   carries the same TODO for the reporting reference it quotes the alpha mismatch at.

8. **The electrical `FuelCellSource` refit.** Cross-referencing section 6: the plant's
   electrical fuel cell (12 cells, ~0.45 ohm) and the map's brochure curve are two curves
   for one stack, and the review's proposal to bill Faraday on `fuel_cell.i` directly was
   rejected precisely because that curve is the less accurate one. The refit is the
   follow-up that closes the gap. It is **not** a documentation change: it moves plant
   behaviour — currents, bus voltages, every anchor — so it needs its own round, its own
   campaign, and a re-pin of the anchor set. Until it lands, the `P -> I` inversion is
   the deliberate answer and the two curves are a documented, quantified gap (~20 % at
   1 A).

9. **`RHO_METRIC_G_PER_SOC_H20`.** The MPC's terminal price in H-20 grams is
   `(1/lambda) * marginal_h20(3.2 W) / H2_GFC_DC_GAIN` ~= 1.77 g/SoC, **not** `1/lambda`
   = 2.439: `EQ_H2_LAMBDA_SOC_PER_G` = 0.41 was **measured in Gfc grams** (campaign
   191509, re-measured 0.4163 across C-F), so it is an exchange rate in the retired unit
   and needs converting at a named operating point. It retires when the eq-H2 lever is
   re-measured on an H-20-scored campaign (phase B, and the same measurement item 3
   names).

## 8. Where it is used

| Consumer | Call | Note |
|---|---|---|
| `hil_plant_sim.H2Consumption.step()` | `h2_map.rate_gps(u, stack_on=...)` | the scored `h2_rate_gps`/`h2_cum_g` columns; Gfc moves to `gfc_*` and the new `h2_gfc_cum_g` column |
| `gen_dp_ems_table.step_discharge/step_charge` | `h2_map.rate_gps(P/ETA_BOOST)` | scalar forward pass |
| `gen_dp_ems_table.solve_dp` | `h2_map.rate_gps_array(...)` | vectorized backward pass, plus the saturation census |
| `sdp_ems_solver.build_stage` | `h2_map.rate_gps_array / rate_gps` | **stack-side** `P_fc/ETA_BOOST` since 2026-09-08 (review item A3); `--h2-map eta-proxy` restores the retired bus-side linear law |
| `mpc_ems._dp_step_*`, `Planner.h2_rate_gps` | `h2_map.rate_gps` | `h2_map="h20"` is the **default**; `proxy` and `convex` stay selectable |
| `ems_walk` | inherited through `gen_dp_ems_table` | no code change, labels updated |
| `dp_results_db.model_fields` | `h2_map.fingerprint_str()` | a key field, so every record's key moves |

The fingerprint is one opaque token carrying the map id, the four polarization
coefficients, the saturation current, **the inverse table's grid size**, the Faraday
gain, the offset and the shutdown policy:

    h20-brochure-v1|12.2|0.258|0.023|1.183|3.4|2049|0.00013581339256444477|6.632517933244359e-05|False

`_INV_TABLE_N` joined it on 2026-09-08 (review item A8). It is not physics — it is the
grid `I(P)` is interpolated on — but raising it moves every returned rate by ~4e-10 g/s,
and a DP table is the argmin of the map that was **evaluated**, not of the map that was
intended. Recording it is cheap and it removes the one way the fingerprint could have
claimed identity between two numerically different maps.

**A legacy-law solve records a different token.** Under `--h2-map gfc-linear` the DP
table header's `# h2_map:` line carries
`gfc-linear-legacy|1.7637602179836514e-05`, and under `--h2-map eta-proxy` the SDP
artifact's `h2.law_token` carries `eta-proxy-legacy|1.6666666666666667e-05`.
`hil_plant_sim.load_dp_table()`'s drift guard recognises the legacy token as a
**deliberate old-era artifact** rather than as a missing line, so the refusal message
names what the table is instead of claiming the guard field is absent.

It is written into the DP table header as `# h2_map:`, into the SDP artifact's `h2.map`
block, into the MPC sidecar's `h2_map_fingerprint`, and into the DP results database key.
`hil_plant_sim.load_dp_table()` compares it for **exact equality** — a hydrogen law has no
"close enough", because any change to it makes a table the optimum of a different problem.
`h2_map`'s numeric module constants also join `collect_model_constants()`, so a
coefficient edit moves a run's `constants_hash`.

⚠️ `MAP_ID` (a string) and `SHUTDOWN_ENABLED` (a bool) are **not** swept by
`collect_model_constants()`, which records numeric constants only. A run's `constants_hash`
therefore does not move when the map id is bumped or the shutdown policy is flipped. The
fingerprint is the complete record of the map; the hash is only its numeric half.

## 9. What the fix round measured

Numbers established while implementing the review's accepted items. They are stated here
because each one is a claim a later reader will want to check rather than re-derive.

### 9.1 The ceiling is reachable, and it is the tightest one

`P_MAX` = 23.416 W of stack power corresponds to **1.247 A of bus current**, which sits
**below** both the fw v26 clamp (1.250 A) and `LIMIT_I_FC_MAX_A` (1.400 A). The table in
section 3.5 gives the three side by side. Consequences measured:

* On `ems-dp-replay` the peak demand is 22.215 W of bus power, i.e. 26.136 W stack-side at
  share 1.0 — above the ceiling. It is nonetheless **inert on that scenario**, because the
  shipped share band stops at 0.85 and 0.85 x 22.215 = 18.88 W bus is under the 19.90 W
  bus equivalent of `P_MAX`. The split-arm ceiling only binds above share 0.896 there.
* The **charge arm** is where it bites, its stack power being the largest either solver
  evaluates. In the SDP's default grid **1010 of 2525 control cells** are refused by it —
  the TPM's upper demand bins simply exceed what the stack can supply while also feeding
  the charger.
* The DP's charge arm on `ems-dp-replay` at `eta_chg` 0.88 is **not** affected: zero
  admitted charge stages exceed the ceiling on any state-of-charge row.

### 9.2 The convex map flips a sign the linear map guaranteed

`test_ems_walk.test_single_source_demand_is_no_longer_inert_on_any_walk` asserts that the
measured single-source bus law bills **more** hydrogen than the two-source law, never less.
On `soc-band`/`ems-soc-band` that assertion now fails by 1.3e-07 g on 1.3e-02 g (1e-05
relative). It is **not** saturation (zero saturated stages on either walk) and **not** the
inverse table's resolution (a 32x finer grid reproduces the deficit to five figures). It is
convexity, and the decomposition is exact:

| Stages | Count | Sum of bus-power delta | Mean stack power | Marginal rate | Hydrogen delta |
|---|---|---|---|---|---|
| single-source law bills MORE | 125 | +0.965 W | 13.47 W | 1.810e-05 g/s/W | +1.324e-06 g |
| single-source law bills LESS | 113 | -0.589 W | 16.40 W | 2.109e-05 g/s/W | -1.455e-06 g |
| **net** | 238 | **+0.376 W** | | | **-1.314e-07 g** |

The single-source law raises bus power at **low** operating points and lowers it at **high**
ones. The bus-energy total is positive, so the linear map billed **+7.80e-07 g** and the
invariant held identically. Under a convex map the reductions are priced at a 16 % higher
marginal rate than the increases, and the sign flips. **The invariant is a property of a
linear cost, not of the bus law**: restated on bus energy (the sum of `p_fc_bus_w`, which
is +0.376 W-stage here) it still holds, and is what the test was really about.

### 9.3 The state-of-charge/fuel weighting is measurably off

Solving `sdp_policy_v6`'s configuration (`--eta-chg measured --alpha-mode lever-measured`)
under the three candidate laws:

| Stage cost | Charge cells of 2525 |
|---|---|
| retired `eta-proxy`, bus-side (what v6 shipped) | **0** |
| H-20 map, bus-side (the first implementation pass) | 334 |
| H-20 map, **stack-side** (shipped, review item A3) | **46** |

The shipped v6 invariant "0 charge cells" is a property of the **retired** law, and
`--h2-map eta-proxy` reproduces it exactly. Under the current objective, with alpha still
calibrated at the constant `k`, charging is admitted on 46 cells — which is the direction
section 7 item 2 predicts from a state-of-charge term weighted ~30 % too heavily. Re-basing
to the stack cut the admission by 86 % against the bus-side draft; re-deriving alpha is what
closes the rest. Both `sdp_policy_v3` and `sdp_policy_v6` regenerate **bit-identically**
under `--h2-map eta-proxy`, and `gen_dp_ems_table --h2-map gfc-linear` reproduces the
pre-2026-09-08 `ems-dp-replay` table byte for byte apart from the new `# h2_map:` line.
