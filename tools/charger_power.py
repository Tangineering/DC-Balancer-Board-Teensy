"""charger_power.py - the ONE charger bus-power model the offline EMS tools share.

WHY THIS FILE EXISTS
--------------------
The Ag105's bus-side draw is priced in five offline tools (the DP generator,
the SDP solver, the offline walk, the DP results database and the alpha
sweep).  Until 2026-09-01 each of them wrote the same expression by hand,
``V_bus * i_chg`` - the 1:1 CURRENT-TRANSFER model the simulator's hi-fi
electrical engine then stamped (``J[N_CHG] -= i_charge``: the pack received
exactly the current the bus supplied).  That model destroys
``i_chg * (V_chg - V_batt)`` of power and over-bills the bus by ~1.7x against
a real buck stage.

The plant is being corrected to an energy-conserving converter at a STATIC
charge efficiency (AG105_Silvertel.pdf, DC Electrical Characteristics item 1:
88 % typ at 25 C / 12 V in / 3S; the operator ruled a static 0.88 for this
rig's 15-16 V in / 2S operating point).  Delivering ``i_chg`` into a pack at
``V_pack`` then costs the bus

    P_in = V_pack * i_chg / eta_chg          [W]

which is NOT the old expression with eta = 1: the old one billed at the BUS
voltage, the new one at the PACK voltage.  The two eras are therefore
selected by an EXPLICIT era switch and never by an efficiency value:

    eta_chg is None  ->  OLD (1:1 current-transfer) era, P_in = V_bus * i_chg
    eta_chg is a float -> NEW era,                     P_in = V_pack * i_chg / eta

ERA RESOLUTION
--------------
A run sidecar's ``meta`` carries ``eta_chg`` from the era in which the run
executed; ``resolve_eta_chg()`` maps an absent key onto None, i.e. onto the
old era.  Every offline tool that prices a charge stage must resolve the era
through this function rather than defaulting an efficiency, so that a table or
a walk solved for an archived run reproduces the accounting that run actually
saw.

This module is STDLIB ONLY and imports nothing from the repository.  That is
deliberate: ``tools/sdp_ems_solver.py`` declares that it imports nothing from
its own consumer (``tools/hil_plant_sim.py``), and the DP generator's numpy
import must not be forced on the stdlib-only walk harness.  Every function
here is pure arithmetic and works elementwise on numpy arrays.
"""

# Static charge efficiency, AG105_Silvertel.pdf DC Electrical Characteristics
# item 1 (88 % typ, 25 C, 12 V in, 3S).  Operator ruling 2026-09-01: a STATIC
# 0.88 is used at this rig's 15-16 V in / 2S point rather than a modelled
# curve.  TODO(verify: Silvertel) - the datasheet figure is quoted at a
# different input voltage and cell count than this board runs.
ETA_CHG_DEFAULT = 0.88


def resolve_eta_chg(meta, default=None):
    """The charge efficiency a run's metadata declares, or `default`.

    `meta` is a run sidecar's meta block (or a scenario meta, or any mapping).
    A MISSING key means the OLD 1:1 current-transfer era and resolves to
    `default`, which is None unless a caller deliberately asks otherwise.
    An explicit None in the mapping means the same thing.
    """
    if not meta:
        return default
    val = meta.get("eta_chg")
    return default if val is None else float(val)


def check_eta_chg(eta_chg):
    """Validate an era value.  None (old era) passes; returns the value."""
    if eta_chg is None:
        return None
    eta = float(eta_chg)
    if not 0.0 < eta <= 1.0:
        raise ValueError("eta_chg must lie in (0, 1] or be None for the "
                         "1:1 current-transfer era, got %r" % (eta_chg,))
    return eta


def charger_billing_voltage_v(v_bus, v_pack, eta_chg):
    """Bus WATTS per AMP of charge current - the era's whole difference.

    Old era: the bus is billed at its own voltage (the charger moved current,
    not energy).  New era: at the pack voltage, divided by the converter
    efficiency.  Every other function here is this one times a current.
    """
    if check_eta_chg(eta_chg) is None:
        return v_bus
    return v_pack / float(eta_chg)


def charger_bus_power_w(i_chg_a, v_bus, v_pack, eta_chg):
    """Bus-side power [W] the fuel cell must supply for `i_chg_a` of charge.

    Sign-transparent: a zero charge current costs zero in both eras, and a
    negative one is not clamped (no caller passes one, and silently flooring
    it would hide a sign defect rather than surface it).
    """
    return i_chg_a * charger_billing_voltage_v(v_bus, v_pack, eta_chg)


def charger_bus_current_a(i_chg_a, v_bus, v_pack, eta_chg):
    """Bus-side CURRENT [A] the charger draws - the FC-budget quantity.

    In the old era this is `i_chg_a` itself (1:1 current transfer), which is
    why every FC-budget test in these tools used to add the charge ceiling
    directly.  In the new era it is the power divided by the bus voltage, and
    it is SMALLER (a 0.8 A charge into a 7.9 V pack at eta 0.88 draws 0.45 A
    from a 15.9 V bus), so a budget that was binding can stop binding.

    The old era returns `i_chg_a` ITSELF rather than `V_bus*i/V_bus`: the two
    differ by a rounding ulp on some bus voltages, and the committed DP tables
    are byte-identity artifacts whose charge mask is computed from this value.
    """
    if check_eta_chg(eta_chg) is None:
        return i_chg_a
    return charger_bus_power_w(i_chg_a, v_bus, v_pack, eta_chg) / v_bus


def era_label(eta_chg):
    """A short, printable name for the era - for headers and manifests."""
    if eta_chg is None:
        return "1:1 current transfer (pre-2026-09-01 plant)"
    return "buck/boost at eta_chg = %r" % float(eta_chg)
