#!/usr/bin/env python3
"""h2_map.py — the H-20 stack's hydrogen consumption map (the SCORED estimator).

⚠️ THIS MODULE REPLACES THE Gfc DC GAIN AS THE HYDROGEN ESTIMATOR ⚠️

    Every hydrogen number this repository scores a strategy on — the plant's
    `h2_rate_gps`/`h2_cum_g` columns, the DP table's stage cost, the SDP
    solver's `W_H2`, the offline walk's `h2_g`, and the MPC's stage cost —
    comes from HERE from 2026-09-08 onward.  The full-size Gfc transfer
    function (`hil_plant_sim.H2_GFC_*`) is still integrated and still logged,
    but as a DOCUMENTED comparison column, not as the scored axis.  See
    `docs/modeling/h20_hydrogen_map_20260908.md`.

WHY THE CHANGE.  Gfc is a 106 kW stack's consumption model taken verbatim from
the PhD student's FCHEV study.  It is LINEAR (one DC gain, 1.7638e-05 g/s/W),
it was never identified against THIS stack, and a linear map cannot express the
one thing an energy-management strategy trades on at this scale: the fuel cell's
efficiency is NOT constant, it PEAKS, and the rig's median operating point sits
far below that peak.  The map below is built from the stack that is actually on
the rig.

THE SOURCE.  references/H20-Small-Stacks-Brochure.pdf, the H-20 block:
    13 cells, rated 20 W, 7.8 V @ 2.6 A at rated output,
    hydrogen flow 0.28 L/min at maximum output,
    "efficiency of system 40 % at full power",
    blower 5 V, purge valve 6 V,
    a printed U-I polarization curve (digitized below).

THE MODEL, in three pieces:

  1. FARADAY'S LAW gives the hydrogen the ELECTROCHEMISTRY consumes, and it is
     exact — no fit, no rig constant:
         K_FARADAY_GPS_PER_A = N_CELLS * M_H2 / (2 * F)
     A stack of `N_CELLS` cells in SERIES passes one current through every
     cell, so each cell's half-reaction consumes its own hydrogen: the cell
     count multiplies, it does not divide.

  2. A CONSTANT OFFSET carries everything Faraday does not: the periodic purge
     valve venting unreacted hydrogen, the stack-fed blower, and the module's
     own controller.  The brochure gives the TOTAL flow at rated output and
     nothing that splits it, so the offset is what is left over:
         A0_OFFSET_GPS = FLOW_RATED_GPS - K_FARADAY_GPS_PER_A * I_RATED_A
     This is a MODELLING DECISION (operator, 2026-09-08): a constant offset,
     not a purge duty cycle and not a load-dependent parasitic.  It is the only
     split the brochure supports.
     TODO(bench): time the purge valve's interval and duration, and measure the
     blower + controller draw, then re-derive the offset as the sum of measured
     terms rather than as a residual.

  3. THE POLARIZATION CURVE turns a POWER request into the current Faraday's
     law needs, and it is where the convexity comes from.  P(I) = V(I)*I with
     V(I) falling means a watt at 20 W costs more hydrogen than a watt at 3 W.

WHAT IS AND IS NOT MEASURED HERE.  The polarization coefficients are fitted to
the BROCHURE's printed curve for the H-20 block, which is the right STACK but
not THIS stack's individual sample, and not this stack after ageing.  That is a
far smaller extrapolation than Gfc's (a different stack, 5300x the power), but
it is still an extrapolation: TODO(calibrate) — a load-sweep of the fitted
stack (terminal V against I at 8-10 points) replaces the digitized curve
outright, and a flow-meter reading at two currents separates the offset from
Faraday directly.

INPUT CONVENTION.  Every entry point takes STACK-SIDE power in watts: the
fuel cell's own terminal voltage times its own current.  Bus-side callers
divide by `hil_plant_sim.ETA_BOOST` first, exactly as they do today.  Negative
power is CLAMPED AT ZERO (reverse power into the stack is not a physical
operating point on this rig and a negative rate would be an unphysical
hydrogen CREDIT).

RUNTIME CONTRACT.  The scalar path runs inside the simulator's 1 kHz tick, so
it is STDLIB-ONLY and allocation-free: `math` and `bisect` against a table
built once at import.  numpy is imported LAZILY, inside the vectorized and the
fitting helpers only, so importing this module from the plant costs nothing.
"""

import bisect
import math

# ═════════════════════════════════════════════════════════════════════════════
# THE MAP'S IDENTITY.  Bumped whenever any constant below moves; it is what the
# DP table headers, the SDP artifact and the DP results database record, so a
# table solved against an older map is not silently read as a baseline for this
# one.
# ═════════════════════════════════════════════════════════════════════════════
# ⚠️ MAP_ID IS A STRING AND `SHUTDOWN_ENABLED` BELOW IS A BOOL, SO NEITHER IS
# SWEPT BY `hil_plant_sim.collect_model_constants()` — that helper records
# NUMERIC module constants only, and a run's `constants_hash` therefore does NOT
# move when the map id is bumped or the shutdown policy is flipped.
# `fingerprint()` / `fingerprint_str()` are the COMPLETE record of the map and
# both carry them; the constants hash is only the numeric half.  Anything that
# needs to tell two maps apart must compare the fingerprint, never the hash.
# ═════════════════════════════════════════════════════════════════════════════
MAP_ID = "h20-brochure-v1"

# ── Physical constants ───────────────────────────────────────────────────────
M_H2_G_PER_MOL = 2.016          # g/mol   molar mass of H2
F_C_PER_MOL = 96485.33          # C/mol   Faraday constant
Q_LHV_J_PER_G = 120000.0        # J/g     H2 lower heating value; the SAME
                                #         number the student's proxies use
                                #         (SDP_EnergyManagement2.m:13), kept
                                #         identical so an efficiency quoted
                                #         here and one quoted there are on one
                                #         basis.

# ── H-20 block nameplate (brochure) ──────────────────────────────────────────
N_CELLS = 13                    # cells in series
P_RATED_W = 20.0                # W       "rated power"
V_RATED_V = 7.8                 # V       at rated output
I_RATED_A = 2.6                 # A       at rated output (7.8 V * 2.6 A =
                                #         20.28 W, the brochure's own pair)
FLOW_RATED_L_PER_MIN = 0.28     # L/min   "hydrogen flow at max output"
ETA_SYSTEM_RATED = 0.40         # -       "efficiency of system 40 % at full
                                #         power"

# ── STP, NOT NTP — and the brochure settles it ───────────────────────────────
# The brochure quotes flow in L/min without naming the reference state, and the
# two candidates differ by 7 %.  Its OWN 40 % efficiency figure picks one:
#     STP (0 C, 1 atm), 0.08988 g/L:
#         20.28 W / (0.28 L/min * 0.08988 g/L / 60 s * 120000 J/g) = 0.403
#     NTP (20 C, 1 atm), 0.08375 g/L:
#         the same ratio = 0.432
# 0.403 reproduces the printed 40 %; 0.432 does not.  STP it is.  This is the
# single most leveraged assumption in the whole map (it scales A0_OFFSET_GPS
# directly), so it is derived rather than asserted, and `check_rated_efficiency`
# below recomputes it on demand.
RHO_H2_G_PER_L = 0.08988        # g/L at STP (0 C, 1 atm)

# ── Piece 1: Faraday ─────────────────────────────────────────────────────────
K_FARADAY_GPS_PER_A = N_CELLS * M_H2_G_PER_MOL / (2.0 * F_C_PER_MOL)
# = 1.3581339256444477e-04 g/s per A

# ── Piece 2: the constant offset ─────────────────────────────────────────────
FLOW_RATED_GPS = FLOW_RATED_L_PER_MIN * RHO_H2_G_PER_L / 60.0
# = 4.1944e-04 g/s
A0_OFFSET_GPS = FLOW_RATED_GPS - K_FARADAY_GPS_PER_A * I_RATED_A
# = 6.632517933244359e-05 g/s
#
# ⚠️ SIGN SANITY, asserted at import: a NEGATIVE offset would mean the brochure's
# flow is below what Faraday alone demands at the rated current, i.e. the
# density assumption or the cell count is wrong.  The margin today is 16 % of
# the rated flow, so this assertion is not tight — it is a tripwire for a
# hand-edit of RHO_H2_G_PER_L or N_CELLS.
# ⚠️ AN EXPLICIT `raise`, NOT AN `assert`: `python -O` strips assert statements,
# and a tripwire that disappears under an optimisation flag is not a tripwire.
if not (A0_OFFSET_GPS > 0.0):
    raise ValueError(
        "A0_OFFSET_GPS = %.6g g/s is not positive: the brochure's rated flow "
        "(%.6g g/s) is below Faraday's demand at %.2f A (%.6g g/s). Check "
        "RHO_H2_G_PER_L, N_CELLS or FLOW_RATED_L_PER_MIN."
        % (A0_OFFSET_GPS, FLOW_RATED_GPS, I_RATED_A,
           K_FARADAY_GPS_PER_A * I_RATED_A))

# ── Piece 3: the polarization curve ──────────────────────────────────────────
# DIGITIZED from the brochure's printed U-I curve for the H-20 block, plus the
# nameplate anchor (2.6 A, 7.8 V) which is a PRINTED NUMBER rather than a read
# off the plot and is therefore weighted 4x.  Reading points off a printed
# curve is worth about +/-0.15 V; the fit's UNWEIGHTED RMS over the ten points
# below is 0.27 V, so the RESIDUAL
# is the curve's own shape, not the digitizing.
POLARIZATION_POINTS_A_V = (
    (0.00, 12.2),
    (0.25, 11.3),
    (0.50, 10.7),
    (1.00, 10.0),
    (1.50, 9.5),
    (2.00, 9.1),
    (2.50, 8.5),
    (3.00, 7.9),
    (3.40, 7.0),
    (2.60, 7.8),          # the NAMEPLATE anchor
)
POLARIZATION_WEIGHTS = (1.0,) * 9 + (4.0,)

# The fitted form.  Three named loss mechanisms, in the order they dominate:
#     V(I) = V0 - b*ln(1 + I/i0) - R*I
#   V0  open-circuit voltage of the 13-cell stack     [V]
#   b   Tafel slope, the ACTIVATION loss              [V/decade-ish, natural log]
#   i0  the exchange-current scale that keeps the log finite at I = 0   [A]
#   R   the lumped OHMIC resistance (membrane + contact + plate)        [ohm]
# Concentration (mass-transport) losses are NOT given their own term: the
# brochure's curve ends at 3.4 A and shows the knee only in its last point, so a
# fourth parameter would be fitted to one datum.  The consequence is stated
# rather than hidden — the map UNDER-reads consumption near 3.4 A, which is the
# optimistic direction there, and 3.4 A is 2.7x the rig's own fw v26 fuel-cell
# ceiling (1.25 A) so no scored operating point is near it.
POLARIZATION_V0_V = 12.200
POLARIZATION_B_V = 0.258
POLARIZATION_I0_A = 0.023
POLARIZATION_R_OHM = 1.183
# Fit quality: UNWEIGHTED RMS 0.268 V OVER THE TEN FIT POINTS above (the 4x
# nameplate weight steers the FIT; it does not weight this RMS), and
# V(2.6 A) = 7.902 V against the nameplate's 7.8 V (+1.3 %).
# `refit_polarization()` re-runs the fit from the stored points; read ITS
# docstring before treating a mismatch as an error.

# The current at which P(I) = V(I)*I stops rising.  The brochure's curve ends at
# 3.4 A and P is still monotone there, so this is the CURVE's endpoint, not a
# turning point of the fitted parabola-like power law: the map does not
# extrapolate past the last digitized datum.
I_PMAX_A = 3.40


def polarization_v(i_a):
    """Stack terminal voltage [V] at stack current `i_a` [A].

    Clamped to a non-negative current.  No upper clamp: the caller decides
    whether an above-curve current is an error or a saturation."""
    i = i_a if i_a > 0.0 else 0.0
    return (POLARIZATION_V0_V
            - POLARIZATION_B_V * math.log(1.0 + i / POLARIZATION_I0_A)
            - POLARIZATION_R_OHM * i)


def stack_power_w(i_a):
    """Stack electrical power [W] at stack current `i_a` [A]: V(I)*I."""
    i = i_a if i_a > 0.0 else 0.0
    return polarization_v(i) * i


P_MAX_W = stack_power_w(I_PMAX_A)     # = 23.416082767694366 W

# ═════════════════════════════════════════════════════════════════════════════
# THE INVERSE I(P), and why it is a TABLE rather than a bisection
# ═════════════════════════════════════════════════════════════════════════════
# The 1 kHz plant tick calls this once per tick for the whole run.  A 40-step
# bisection is ~40 logs and ~40 branches per tick; a table lookup is one
# `bisect` (11 comparisons over 2049 entries) and one linear interpolation, and
# it allocates nothing.  The table is built ONCE at import with stdlib only.
#
# ACCURACY.  P(I) is smooth and its curvature is mild, so linear interpolation
# of the inverse on a 2048-interval grid errs by < 3e-6 A, i.e. < 4e-10 g/s on
# the rate — six orders below the offset term.  `_INV_TABLE_N` is the knob; it
# is not a physical constant.
#
# ⚠️ BUT IT IS IN `fingerprint()` (2026-09-08 review, item A8).  Raising it
# MOVES EVERY NUMBER THE MAP RETURNS, by ~4e-10 g/s — small, and not zero.  A
# DP table is the argmin of the map that was actually evaluated, so the grid
# the inverse was interpolated on is part of that map's identity even though it
# is not part of its physics.  Raise it freely; expect every cached table and
# every dp_db record to be re-keyed when you do.
_INV_TABLE_N = 2049
_I_TABLE = [I_PMAX_A * k / (_INV_TABLE_N - 1) for k in range(_INV_TABLE_N)]
_P_TABLE = [stack_power_w(i) for i in _I_TABLE]
# Strict monotonicity is what makes the inverse well defined AND what makes
# `bisect` correct.  Asserted at import for the same reason the offset's sign
# is: a hand-edit of a polarization coefficient that pushed the peak below
# I_PMAX_A would otherwise produce a silently multivalued map.
# ⚠️ An explicit `raise`, not an `assert`, for the same `python -O` reason the
# offset's sign check gives.
if not all(_P_TABLE[k + 1] > _P_TABLE[k] for k in range(_INV_TABLE_N - 1)):
    raise ValueError(
        "stack_power_w() is not strictly increasing on [0, %.3f] A: the "
        "polarization coefficients put the power peak inside the curve's "
        "range, so I(P) is not single-valued. Lower I_PMAX_A to the peak."
        % I_PMAX_A)


def _finite(p_stack_w):
    """`float(p_stack_w)`, REFUSING NaN.

    NaN is refused rather than propagated because every consumer of this module
    integrates its output: one NaN tick poisons a whole run's `h2_cum_g`, a
    whole DP stage column, or a whole SDP sweep, and it does so SILENTLY — the
    comparisons in `current_a()` are all False against NaN, so a NaN would fall
    straight through the clamps into `bisect`, whose result on a NaN is
    unspecified.  Raising at the boundary names the caller instead.  Infinity is
    NOT refused: +inf clamps to `I_PMAX_A` and -inf to 0.0, which are the
    physically right answers at the two ends of the curve."""
    p = float(p_stack_w)
    if p != p:
        raise ValueError(
            "h2_map: stack power is NaN. The map integrates its own output, so "
            "a NaN here would poison a whole run/table rather than one sample. "
            "Fix the caller's power computation.")
    return p


def current_a(p_stack_w):
    """Stack current [A] that develops `p_stack_w` [W]. Stdlib, allocation-free.

    Clamped at BOTH ends: a negative power returns 0.0 A, and a power above
    `P_MAX_W` returns `I_PMAX_A` (the request is beyond the brochure's curve —
    `is_saturated()` reports it, and `rate_gps()` is the caller that decides
    what to do about it).

    A NaN power RAISES ValueError — see `_finite()`."""
    p = _finite(p_stack_w)
    if p <= 0.0:
        return 0.0
    if p >= P_MAX_W:
        return I_PMAX_A
    k = bisect.bisect_right(_P_TABLE, p)
    # `k` is in [1, N-1] here: p is strictly inside (_P_TABLE[0], _P_TABLE[-1]).
    p0 = _P_TABLE[k - 1]
    p1 = _P_TABLE[k]
    i0 = _I_TABLE[k - 1]
    i1 = _I_TABLE[k]
    return i0 + (i1 - i0) * (p - p0) / (p1 - p0)


def is_saturated(p_stack_w):
    """True when the request exceeds the brochure curve's last point.

    A saturated call is NOT an error and does not raise: the map returns the
    consumption at `I_PMAX_A` and the caller keeps running.  It IS a statement
    that the number is a floor rather than an estimate, because the real stack
    past its curve either sags further (costing more hydrogen for the same
    power) or simply cannot deliver.  Any scored path that reports saturation
    should be re-read before its hydrogen total is quoted.

    A NaN power RAISES ValueError, on the same terms as `current_a()`: a
    saturation predicate that answered False for a NaN would let a poisoned
    sample past the one check that exists to catch an out-of-range one."""
    return _finite(p_stack_w) > P_MAX_W


# ═════════════════════════════════════════════════════════════════════════════
# THE SHUTDOWN HOOK (operator decision, 2026-09-08: CARRY IT, DO NOT USE IT)
# ═════════════════════════════════════════════════════════════════════════════
# A real H-20 module can be commanded off, and a stopped stack consumes nothing
# — no purge, no blower.  Whether the rig's EMS is ALLOWED to stop the stack is
# a separate question (restart time, membrane hydration, and the board's own
# FC_REG_ENABLE sequencing all bear on it), and the answer today is NO: there is
# no stack-shutdown state in the firmware and none is planned this round.
#
# So the hook exists in two forms and both DEFAULT TO THE STACK RUNNING:
#   * `stack_on` — a PER-CALL fact, wired to the board's FC_REG_ENABLE mirror
#     (observation-frame aux bit 0).  A stack whose regulator the firmware has
#     not enabled is not making power and is not being fed; the plant passes
#     False there and the map returns 0.
#   * `SHUTDOWN_ENABLED` — a MODULE-LEVEL POLICY switch for the future EMS
#     action "command the stack off at zero demand".  While it is False, a
#     stack that is on but idling still burns `A0_OFFSET_GPS` (purge + blower +
#     controller), which is the physically honest cost of leaving it running
#     and the reason an idle-heavy cycle is not free.
# Nothing in the tree sets `SHUTDOWN_ENABLED` today.  Flipping it is a MODELLING
# CHANGE, not a tuning knob: it changes every idle stage's cost, so it belongs
# in the fingerprint (it is there) and it needs its own campaign.
SHUTDOWN_ENABLED = False


def rate_gps(p_stack_w, stack_on=True, shutdown_enabled=None):
    """Hydrogen mass rate [g/s] for a STACK-side power [W].

        rate = 0                              if the stack is off
        rate = 0                              if shutdown is enabled and P <= 0
        rate = A0_OFFSET + K_FARADAY * I(P)   otherwise

    `p_stack_w` is CLAMPED AT ZERO inside `current_a()`, so a negative power
    costs the idle offset and never a negative (credit) rate.

    `shutdown_enabled=None` reads the module policy `SHUTDOWN_ENABLED`; pass a
    bool to override it for one call (a what-if study, or a test).

    A NaN power RAISES ValueError (see `_finite()`) — EVEN WITH THE STACK OFF,
    so that the refusal does not depend on an unrelated flag.

    Stdlib only and allocation-free: this is the 1 kHz path."""
    p = _finite(p_stack_w)
    if not stack_on:
        return 0.0
    sd = SHUTDOWN_ENABLED if shutdown_enabled is None else bool(shutdown_enabled)
    if sd and p <= 0.0:
        return 0.0
    return A0_OFFSET_GPS + K_FARADAY_GPS_PER_A * current_a(p)


# ═════════════════════════════════════════════════════════════════════════════
# THE VECTORIZED PATH — DP / SDP / MPC table builds
# ═════════════════════════════════════════════════════════════════════════════
# numpy is imported LAZILY so the plant's import of this module stays stdlib.
# The table it interpolates on is THE SAME `_P_TABLE`/`_I_TABLE` the scalar path
# bisects, so the two paths cannot drift: a DP stage cost and the plant column
# it is scored against are one map by construction, not by agreement.
def _finite_array(p_stack_w):
    """`np.asarray(..., float)`, REFUSING NaN — the array mirror of `_finite`.

    The scalar and vectorized paths must agree on what they REFUSE as well as
    on what they return, or a DP table build would silently absorb a NaN stage
    that the forward walk raises on.  `np.interp` would otherwise propagate the
    NaN into one cell of a whole stage column."""
    import numpy as np
    p = np.asarray(p_stack_w, dtype=float)
    if np.isnan(p).any():
        raise ValueError(
            "h2_map: %d of %d stack powers are NaN. The map integrates its own "
            "output, so a NaN here would poison a whole table rather than one "
            "cell. Fix the caller's power computation."
            % (int(np.isnan(p).sum()), p.size))
    return p


def current_a_array(p_stack_w):
    """Vectorized `current_a`: numpy array in, numpy array out.

    `np.interp` clamps at both ends of the table, which is exactly the scalar
    function's clamp (0 A below, `I_PMAX_A` above).  NaN RAISES, exactly as the
    scalar path does."""
    import numpy as np
    return np.interp(_finite_array(p_stack_w), _P_TABLE, _I_TABLE)


def rate_gps_array(p_stack_w, stack_on=True, shutdown_enabled=None):
    """Vectorized `rate_gps`: numpy array in, g/s array out.

    `stack_on` is a scalar bool or an array broadcastable against
    `p_stack_w` — a stage-wise mirror of the board's FC_REG_ENABLE.

    NaN RAISES ValueError, as in the scalar path."""
    import numpy as np
    p = _finite_array(p_stack_w)
    out = A0_OFFSET_GPS + K_FARADAY_GPS_PER_A * current_a_array(p)
    sd = SHUTDOWN_ENABLED if shutdown_enabled is None else bool(shutdown_enabled)
    if sd:
        out = np.where(p <= 0.0, 0.0, out)
    on = np.asarray(stack_on, dtype=bool)
    if not on.all():
        out = np.where(on, out, 0.0)
    return out


# ═════════════════════════════════════════════════════════════════════════════
# DERIVED READINGS — none of these is on the scoring path
# ═════════════════════════════════════════════════════════════════════════════
def eta_lhv(p_stack_w, stack_on=True):
    """Lower-heating-value efficiency P / (rate * Q_LHV), dimensionless.

    Zero at or below zero power (the stack burns the offset and delivers
    nothing) and zero with the stack off.

    ⚠️ ABOVE `P_MAX_W` this OVER-READS: the numerator is the power ASKED FOR
    while the denominator is the consumption at `I_PMAX_A`, so the ratio keeps
    climbing past a point the stack cannot reach.  Check `is_saturated()`
    before quoting an efficiency.  NaN RAISES, as everywhere else."""
    p = _finite(p_stack_w)
    if p <= 0.0 or not stack_on:
        return 0.0
    r = rate_gps(p, stack_on=True)
    if r <= 0.0:
        return 0.0
    return p / (r * Q_LHV_J_PER_G)


def marginal_gps_per_w(p_stack_w, dp_w=1e-3):
    """d(rate)/dP [g/s per W] at `p_stack_w`, by central difference.

    THIS IS THE NUMBER THE OLD LINEAR MODEL PRETENDED WAS CONSTANT.  It is the
    exchange rate an optimizer actually trades on — the SDP's alpha derivation,
    the MPC's terminal price and the eq-H2 lever prices are all ratios against
    it — and it now depends on WHERE the stack is operating.  Central
    difference rather than an analytic derivative because the table
    interpolation is what the scored path uses, and the derivative of the
    thing that runs is the honest one.

    Clamped to a one-sided difference at P = 0 and inside the saturation
    region, where the two-sided form would straddle a kink.  NaN RAISES."""
    p = _finite(p_stack_w)
    h = _finite(dp_w)
    lo = p - h
    hi = p + h
    if lo < 0.0:
        lo, hi = 0.0, h
    if hi > P_MAX_W:
        lo, hi = max(0.0, P_MAX_W - h), P_MAX_W
    if hi <= lo:
        return 0.0
    return (rate_gps(hi) - rate_gps(lo)) / (hi - lo)


# The DEFAULT upper limit of the quadratic fit below: the brochure's own rated
# operating point, 7.8 V * 2.6 A.  Not `P_MAX_W` — the fit exists to summarise
# the map over the range the rig can plausibly reach, and the last stretch of
# the curve (where the un-modelled concentration knee lives) would dominate a
# least-squares residual it does not deserve.
QUADRATIC_FIT_P_HI_W = V_RATED_V * I_RATED_A     # 20.28 W
QUADRATIC_FIT_N = 2001


def quadratic_fit(p_hi=QUADRATIC_FIT_P_HI_W, n=QUADRATIC_FIT_N):
    """Least-squares `rate ~ a0 + a1*P + a2*P^2` over [0, p_hi].

    Returns ``(a0, a1, a2, max_rel_err)``.

    WHAT IT IS FOR.  It is a REPORTING and HANDOFF form, not a scoring one:
    nothing in the tree minimises the quadratic, and the DP/SDP/MPC all call
    the table map directly.  It exists because (a) the student-facing
    `a0 + a1*P + a2*P^2` shape is how fuel-cell consumption is stated in the
    EMS literature this work sits in, and (b) a downstream solver that needs a
    closed-form convex stage cost can take these three numbers instead of a
    table.

    ⚠️ IT IS NOT THE MAP.  `max_rel_err` is ~5 % and it is worst at LOW power,
    where the rig actually lives — the true map's curvature near zero comes
    from the activation log, which a parabola cannot follow.  Do not substitute
    the quadratic for `rate_gps()` on a scored path.

    THE GRID IS UNIFORM IN P, `n` points on [0, p_hi], unweighted.  Stated
    because the fit is grid-dependent at the 2 % level (a grid uniform in
    CURRENT weights the low-power end differently and moves a1 by ~3 %), so a
    quoted coefficient triple is only reproducible with its grid."""
    import numpy as np
    p = np.linspace(0.0, float(p_hi), int(n))
    r = rate_gps_array(p)
    a = np.vstack([np.ones_like(p), p, p * p]).T
    coef, _res, _rank, _sv = np.linalg.lstsq(a, r, rcond=None)
    fit = a @ coef
    rel = np.abs(fit - r) / np.maximum(r, 1e-12)
    return float(coef[0]), float(coef[1]), float(coef[2]), float(rel.max())


def efficiency_peak(n=400001):
    """``(p_peak_w, eta_peak)`` — the maximum of `eta_lhv` over the curve.

    Scanned on a fine current grid rather than solved analytically: the
    stationarity condition mixes the log and the linear term and has no closed
    form, and the scan is the same table the map runs on."""
    import numpy as np
    i = np.linspace(1e-9, I_PMAX_A, int(n))
    v = (POLARIZATION_V0_V
         - POLARIZATION_B_V * np.log1p(i / POLARIZATION_I0_A)
         - POLARIZATION_R_OHM * i)
    p = v * i
    eta = p / ((A0_OFFSET_GPS + K_FARADAY_GPS_PER_A * i) * Q_LHV_J_PER_G)
    k = int(np.argmax(eta))
    return float(p[k]), float(eta[k])


def student_form(p_hi=QUADRATIC_FIT_P_HI_W):
    """The three-number handoff the MPC's `convex` map has always asked for.

    Returns ``dict(a0, p_peak, eta_peak)``:
      * ``a0``       the quadratic fit's constant term — the idle consumption
                     the parabola sees (NOT `A0_OFFSET_GPS`, which is the
                     PHYSICAL offset; the fit trades a little of the offset
                     against its curvature).
      * ``p_peak``   the power at which the PHYSICAL map's LHV efficiency peaks.
      * ``eta_peak`` that peak efficiency.
    The last two come from `efficiency_peak()`, i.e. from the real map, NOT
    from the parabola's own vertex — the parabola's curvature is fitted, its
    peak is not a measurement.  `mpc_ems.Planner.h2_rate_gps`'s `convex` branch
    reconstructs a1 and a2 from exactly these three, which is why they are
    served together."""
    a0, _a1, _a2, _err = quadratic_fit(p_hi)
    p_peak, eta_peak = efficiency_peak()
    return {"a0": a0, "p_peak": p_peak, "eta_peak": eta_peak}


def check_rated_efficiency():
    """Recompute the brochure's 40 %: ``P_rated / (flow_rated * Q_LHV)``.

    Returns the dimensionless ratio.  This is the STP-versus-NTP argument in
    executable form — see the `RHO_H2_G_PER_L` block."""
    return (V_RATED_V * I_RATED_A) / (FLOW_RATED_GPS * Q_LHV_J_PER_G)


def fingerprint():
    """The map's identity, for a table header / artifact / database key.

    Every quantity that MOVES THE MAP is in here and nothing else is: the two
    derived scalars (`k_faraday_gps_per_a`, `a0_offset_gps`) are functions of
    the nameplate and the density, and the four polarization coefficients are
    the curve.  `shutdown_enabled` is in because it changes every idle stage's
    cost.  `i_pmax_a` is in because it is where the map saturates.

    `inv_table_n` (added 2026-09-08, review item A8) is in for a DIFFERENT
    reason from the rest: it is not physics, it is the grid the inverse I(P) is
    interpolated on.  Raising it moves every returned rate by ~4e-10 g/s, and a
    DP table is the argmin of the map that was EVALUATED, not of the map that
    was intended - so a table solved on one grid is, strictly, the optimum of a
    different (if barely different) objective.  It is cheap to record and it
    removes the one way this fingerprint could have claimed identity between
    two numerically different maps.

    A table solved under one fingerprint is NOT a baseline for a run under
    another — that is the whole point of recording it."""
    return {
        "map_id": MAP_ID,
        "v0_v": POLARIZATION_V0_V,
        "b_v": POLARIZATION_B_V,
        "i0_a": POLARIZATION_I0_A,
        "r_ohm": POLARIZATION_R_OHM,
        "i_pmax_a": I_PMAX_A,
        "inv_table_n": _INV_TABLE_N,
        "k_faraday_gps_per_a": K_FARADAY_GPS_PER_A,
        "a0_offset_gps": A0_OFFSET_GPS,
        "rho_h2_g_per_l": RHO_H2_G_PER_L,
        "q_lhv_j_per_g": Q_LHV_J_PER_G,
        "shutdown_enabled": bool(SHUTDOWN_ENABLED),
    }


def fingerprint_str():
    """`fingerprint()` as one short, stable, sortable string.

    For key fields and CSV headers, which want a scalar rather than a nested
    dict.  Fixed field order, `%r` on the floats so nothing is rounded away."""
    fp = fingerprint()
    return "%s|%r|%r|%r|%r|%r|%d|%r|%r|%r" % (
        fp["map_id"], fp["v0_v"], fp["b_v"], fp["i0_a"], fp["r_ohm"],
        fp["i_pmax_a"], fp["inv_table_n"], fp["k_faraday_gps_per_a"],
        fp["a0_offset_gps"], fp["shutdown_enabled"])


# ═════════════════════════════════════════════════════════════════════════════
# THE REFIT — a CHECK on the stored coefficients, not a runtime path
# ═════════════════════════════════════════════════════════════════════════════
def refit_polarization(x0=None):
    """Re-run the weighted least-squares fit of V(I) from the stored points.

    Returns ``dict(v0_v, b_v, i0_a, r_ohm, rms_v, cost)``.  Needs scipy; it is
    imported here and NOWHERE at module level, so the runtime map has no scipy
    dependency.

    ⚠️ IT DOES NOT REPRODUCE THE STORED COEFFICIENTS TO 1e-2, AND THAT IS
    EXPECTED (2026-09-08).  The residual surface has a long flat valley in
    ``(b, i0)``: the activation term ``b*ln(1 + I/i0)`` trades curvature
    against scale almost exactly, so many ``(b, i0)`` pairs fit the ten points
    equally well.  From three different starting points (including the stored
    coefficients themselves) the unconstrained optimum lands at
    ``(12.2006, 0.1972, 0.008295, 1.16702)`` with an unweighted RMS of
    0.2085 V, while the SHIPPED coefficients ``(12.200, 0.258, 0.023, 1.183)``
    give 0.2676 V.  ⚠️ THE STORED SET IS NOT THE LEAST-SQUARES OPTIMUM: it is
    the round's fitted set, it reproduces the NAMEPLATE better
    (``V(2.6 A) = 7.902 V`` against the printed 7.8 V) and it is what the map
    runs on, but a refit does not return it.  The two curves differ by AT MOST
    0.159 V anywhere on [0, 3.4] A, and the resulting hydrogen rates differ by
    under 2.2 % across [0.1, 20.28] W.

    SO WHAT A TEST SHOULD ASSERT is the FUNCTIONAL agreement, not the
    coefficients:
      * ``max |V_stored(I) - V_refit(I)|`` under ~0.2 V on [0, I_PMAX_A], and
      * ``stored_polarization_rms_v()`` under ~0.3 V.
    Both hold today.  Pinning ``b`` and ``i0`` individually would pin a point
    in a flat valley, and a scipy version bump could move it without anything
    physical changing.
    TODO(calibrate): when a real load sweep of the fitted stack exists, refit
    against IT and ship the optimum — at that point the stored set and the
    refit SHOULD coincide, and this note retires."""
    import numpy as np
    from scipy.optimize import least_squares

    i = np.array([p[0] for p in POLARIZATION_POINTS_A_V], dtype=float)
    v = np.array([p[1] for p in POLARIZATION_POINTS_A_V], dtype=float)
    w = np.sqrt(np.array(POLARIZATION_WEIGHTS, dtype=float))

    def resid(c):
        v0, b, i0, r = c
        return w * (v0 - b * np.log1p(i / i0) - r * i - v)

    if x0 is None:
        x0 = [POLARIZATION_V0_V, POLARIZATION_B_V,
              POLARIZATION_I0_A, POLARIZATION_R_OHM]
    sol = least_squares(resid, x0,
                        bounds=([10.0, 1e-4, 1e-6, 0.0],
                                [14.0, 5.0, 5.0, 5.0]))
    v0, b, i0, r = (float(x) for x in sol.x)
    pred = v0 - b * np.log1p(i / i0) - r * i
    return {"v0_v": v0, "b_v": b, "i0_a": i0, "r_ohm": r,
            "rms_v": float(np.sqrt(np.mean((pred - v) ** 2))),
            "cost": float(sol.cost)}


def stored_polarization_rms_v():
    """UNWEIGHTED RMS of the SHIPPED coefficients OVER THE TEN FIT POINTS.

    UNWEIGHTED despite `POLARIZATION_WEIGHTS`: the nameplate anchor's 4x weight
    steers the FIT and is deliberately not applied here, so this number and
    `refit_polarization()['rms_v']` (also unweighted) are directly comparable.
    Stdlib only.

    The comparison partner for `refit_polarization()['rms_v']`, computed
    without scipy so a test can call it on any interpreter."""
    n = len(POLARIZATION_POINTS_A_V)
    s = 0.0
    for i_a, v_meas in POLARIZATION_POINTS_A_V:
        d = polarization_v(i_a) - v_meas
        s += d * d
    return math.sqrt(s / n)


if __name__ == "__main__":          # pragma: no cover - operator convenience
    print("MAP_ID                  %s" % MAP_ID)
    print("K_FARADAY_GPS_PER_A     %.6e g/s/A" % K_FARADAY_GPS_PER_A)
    print("FLOW_RATED_GPS          %.6e g/s" % FLOW_RATED_GPS)
    print("A0_OFFSET_GPS           %.6e g/s" % A0_OFFSET_GPS)
    print("rated efficiency check  %.4f (brochure prints 0.40)"
          % check_rated_efficiency())
    print("P_MAX_W                 %.4f W at %.2f A" % (P_MAX_W, I_PMAX_A))
    print("V(2.6 A)                %.4f V (nameplate 7.8)" % polarization_v(2.6))
    print("stored RMS              %.4f V" % stored_polarization_rms_v())
    print()
    print("   P [W]      I [A]     rate [g/s]     eta      d(rate)/dP")
    # P_MAX_W EXACTLY is in the row list (2026-09-08, review item A8): it is
    # the boundary `is_saturated()` tests with a STRICT `>`, so the demo shows
    # that the ceiling itself is NOT saturated while 25 W is.
    for _p in (0.0, 1.0, 3.0, 5.0, 10.0, 14.75, 20.28, P_MAX_W, 25.0):
        print("  %7.2f  %7.4f   %.6e   %.4f   %.4e"
              % (_p, current_a(_p), rate_gps(_p), eta_lhv(_p),
                 marginal_gps_per_w(_p))
              + ("   SATURATED" if is_saturated(_p) else ""))
    print()
    _pk = efficiency_peak()
    print("efficiency peak         %.4f at %.4f W" % (_pk[1], _pk[0]))
    print("quadratic fit           a0=%.6e a1=%.6e a2=%.6e maxrel=%.4f"
          % quadratic_fit())
