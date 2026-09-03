"""regen_power.py - the ONE regenerative-braking chain the offline EMS tools share.

WHY THIS FILE EXISTS
--------------------
Until 2026-09-02 the regen chain existed in exactly one place, the live plant
(``hil_plant_sim.Plant.step()`` and the charger branch below it).  The offline
demand model had NO regen term at all, and ``gen_dp_ems_table.py`` recorded the
obligation that created:

    "⚠️ If a future generator ever gives the demand model a regen term, BOTH
     [ETA_REGEN and VESC_REGEN_I_MAX_A] must move into this header and into
     the guard."

This module discharges the other half of that contract - the half about
DUPLICATION rather than about drift.  Four consumers now price braking energy:
the plant, the DP generator, the offline walk and the MPC's prediction model.
Writing the same five-line chain four times is how ``V_bus * i_chg`` came to be
written five times before ``charger_power.py`` existed, and the failure mode is
identical: a correction lands in one copy, the four totals stop being
comparable, and nothing refuses.

THE CHAIN, in the order the energy actually flows
-------------------------------------------------
    f_regen  = max(force, -K_F * i_clip)      the VESC's Battery Regen Max, as
                                              a FORCE.  Applied BEFORE the
                                              force becomes motion, so braking
                                              force and electrical return come
                                              from ONE number.
    p_brake  = max(0.0, -(f_regen * v))       shaft power available to return
    p_regen  = eta_regen * p_brake            electrical, at the V-MOT node
    i_pack   = min(eta_chg * p_regen / V_pack, i_max)
                                              the Ag105's OUTPUT-REFERRED share

The last line is output-referred and is DELIBERATELY NOT NETTED against the
braking chopper: the TL431/BSP170P clamp on V-MOT is a residual absorber, not a
prior claimant, and netting it was measured and rejected (docs/HIL_PLANT.md,
the un-netted-cap ruling).  What the chopper burns is whatever this chain does
not take.

ERA RESOLUTION
--------------
``eta_regen`` is an ERA SWITCH in exactly the sense ``charger_power.eta_chg``
is, and it follows that module's convention verbatim:

    eta_regen is None   ->  the PRE-REGEN demand era, p_mech = max(0, F*v) and
                            no credit at all.  This is what every DP table,
                            SDP policy and dp_db record committed before
                            2026-09-02 was solved against.
    eta_regen is a float -> the regen era, the chain above.

An ABSENT ``eta_regen`` key in a run sidecar, a scenario meta or a table header
therefore means the old era, and ``resolve_eta_regen()`` maps it onto None.  A
consumer must resolve the era through this function rather than defaulting an
efficiency, or a table solved for an archived run will price a credit that run
never earned.

⚠️ THE ERA IS NOT THE DRAG PROFILE.  ``eta_regen`` and ``drag`` are two
independent optional keys (hil_plant_sim.DP_FINGERPRINT_OPTIONAL_KEYS): a
rig-drag run in the regen era is legitimate and simply earns zero credit,
because the rig road load exceeds the inertial force at every deceleration the
registered cycles contain.  A compensated run in the pre-regen era is a
defined, if pointless, configuration.

This module is STDLIB ONLY and imports nothing from the repository, on
``charger_power.py``'s reasoning term for term: ``ems_walk.py`` and
``mpc_ems.py`` must import it without numpy.  Every function is pure arithmetic
and works elementwise on numpy arrays.

CONSTANTS ARE NOT DEFINED HERE.  ``ETA_REGEN`` and ``VESC_REGEN_I_MAX_A`` live
in ``hil_plant_sim.py`` with their ``TODO(verify)`` provenance, and the
defaults below are re-exports for stdlib-only callers that cannot import it.
They are pinned equal by test.
"""

# ── Re-exported defaults, pinned to hil_plant_sim by test ───────────────────
# TODO(verify) on BOTH, inherited verbatim from hil_plant_sim's own block: the
# VESC's Battery Regen Max is a BATTERY-referred bench setting applied here to a
# MOTOR-referred command, and 0.80 is a modelling choice rather than a
# measurement.  The whole harvest column of any regen prediction is linear in
# ETA_REGEN_DEFAULT and roughly linear in VESC_REGEN_I_MAX_A_DEFAULT.
ETA_REGEN_DEFAULT = 0.80
VESC_REGEN_I_MAX_A_DEFAULT = 1.5


def resolve_eta_regen(meta, default=None):
    """The regen efficiency a run's metadata declares, or `default`.

    `meta` is a run sidecar's meta block (or a scenario meta, a DP table
    header, or any mapping).  A MISSING key means the PRE-REGEN era and
    resolves to `default`, which is None unless a caller deliberately asks
    otherwise.  An explicit None in the mapping means the same thing."""
    if not meta:
        return default
    val = meta.get("eta_regen")
    return default if val is None else float(val)


def check_eta_regen(eta_regen):
    """Validate an era value.  None (pre-regen era) passes; returns the value."""
    if eta_regen is None:
        return None
    eta = float(eta_regen)
    if not 0.0 < eta <= 1.0:
        raise ValueError("eta_regen must lie in (0, 1] or be None for the "
                         "pre-regen demand era, got %r" % (eta_regen,))
    return eta


def clip_regen_force_n(force_n, k_f, i_clip_a):
    """The braking force after the VESC's regen-side current clip [N].

    The clip is defined on the CURRENT command (`Plant.step()` applies it to
    `i_cmd` before the force is developed), and `force = K_F * i_cmd`, so
    clipping the command at `i_clip_a` is exactly clipping the force at
    `K_F * i_clip_a`.  The two forms are pinned equal by test; this one exists
    because the offline models carry a force and never a command.

    Positive (motoring) forces pass through untouched - `max()` against a
    negative bound cannot touch them - which is what keeps every pre-regen
    traction figure bit-identical."""
    return max(force_n, -abs(float(k_f) * float(i_clip_a)))


def regen_shaft_power_w(force_n, v_mps, k_f, i_clip_a):
    """Shaft power available to return [W], >= 0, after the clip."""
    f_regen = clip_regen_force_n(force_n, k_f, i_clip_a)
    return max(0.0, -(f_regen * float(v_mps)))


def regen_node_power_w(force_n, v_mps, eta_regen, k_f, i_clip_a):
    """Electrical power arriving at the V-MOT node [W], >= 0.

    Returns 0.0 in the PRE-REGEN era (`eta_regen is None`), which is what makes
    every old-era total bit-identical: the credit is the absence of the term,
    not a term multiplied by zero."""
    eta = check_eta_regen(eta_regen)
    if eta is None:
        return 0.0
    return eta * regen_shaft_power_w(force_n, v_mps, k_f, i_clip_a)


def regen_pack_current_a(p_regen_w, v_pack_v, eta_chg, i_max_a):
    """The Ag105's OUTPUT-REFERRED charge current from regen node power [A].

    `eta_chg` is `charger_power.py`'s era value.  A float is the
    energy-conserving converter and the pack receives `eta_chg * p_regen /
    V_pack`.  `None` is the 1:1 current-transfer era, in which the charger
    moved current rather than energy, so the pack received `p_regen / V_pack`;
    that is the `eta_chg = 1.0` arithmetic and is written as such.

    Never netted against the chopper - see the module docstring."""
    if v_pack_v <= 0.0:
        return 0.0
    eta = 1.0 if eta_chg is None else float(eta_chg)
    return min(eta * float(p_regen_w) / float(v_pack_v), float(i_max_a))


def regen_pack_current_from_force_a(force_n, v_mps, *, eta_regen, eta_chg,
                                    v_pack_v, k_f, i_clip_a, i_max_a):
    """THE WHOLE CHAIN in one call - what the DP, the walk and the MPC use.

    Returns the pack charge current [A] a braking stage delivers, 0.0 in the
    pre-regen era and 0.0 on any stage whose required force is not braking."""
    p_regen = regen_node_power_w(force_n, v_mps, eta_regen, k_f, i_clip_a)
    if p_regen <= 0.0:
        return 0.0
    return regen_pack_current_a(p_regen, v_pack_v, eta_chg, i_max_a)


def era_label(eta_regen):
    """A short, printable name for the era - for headers and manifests."""
    if eta_regen is None:
        return "no regen term (pre-2026-09-02 demand model)"
    return "regen credited at eta_regen = %r" % float(eta_regen)
