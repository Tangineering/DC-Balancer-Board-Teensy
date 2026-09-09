#!/usr/bin/env python3
"""RT1987 soft-start ramp shape A/B: `legacy` vs `constant-slew`.

THE FINDING THIS ROUND SETTLES.  RT1987 DS 17.1/17.3 define tON as the
10 %-90 % RISE TIME, so the part's true output slew is

    dVOUT/dt = 0.8 * VIN / tON = 0.8 * 35 / ((CSS_nF/0.0023 - 100) * 1e-6)

which is INDEPENDENT of VIN and of the start voltage -- 645.5 V/s at CSS
100 nF, 11992.6 V/s at 5.6 nF.  The `legacy` model ramps v_ss_start -> v_ref
OVER tON, so its slope scales with the gap still to travel: 806.9 V/s on a
cold start (+25.0 %) and 581.9 V/s on a 4.4 V warm re-close (-9.8 %).

WHY A PROBE AND NOT A SUITE RUN.  Every scored anchor named in the A/B brief
lives in a scenario that drives a REAL BOARD over UDP; none of them can be
re-run offline.  What CAN be reproduced offline is the soft-start EPISODE each
anchor's number is measured on -- which is the only part of any of those runs
the ramp shape can reach.  Each driver below therefore reproduces one episode
against the REAL `ElectricalSim`, at the substep count this repo's tests pin,
and reports the same quantity the anchor names.  A driver is NOT the scenario:
it carries no firmware, no commander and no fault logic, so it bounds the move
rather than predicting the campaign value.  That scope is stated per driver.

ASCII output only (the bench console is cp1252).

    python tools/probes/probe_rt1987_ramp_ab.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

import hil_electrical as he  # noqa: E402

SW_FC_BUS, SW_BT_BUS, SW_MOT_PWR = he.SW_FC_BUS, he.SW_BT_BUS, he.SW_MOT_PWR
SW_REGEN, SW_FC_CHARGE, SW_BT_SEQ = he.SW_REGEN, he.SW_FC_CHARGE, he.SW_BT_SEQ
AUX_FC_REG, AUX_BT_REG = he.AUX_FC_REG, he.AUX_BT_REG

#: Substep count pinned exactly as test_hil_electrical.py pins it: the engine's
#: budgeter is wall-clock adaptive, so an unpinned A/B would compare two
#: different discretizations rather than two ramp shapes.
N_SUB = 8


def _act(sw=0, aux=0, i_motor_a=0.0, code_fc=0.5, code_bt=0.5, i_charge_a=0.0):
    return {"sw": sw, "aux": aux, "i_motor_a": i_motor_a,
            "code_fc": code_fc, "code_bt": code_bt, "i_charge_a": i_charge_a}


def _step(e, actuators, dt=1e-3, n_sub=N_SUB):
    e._n_sub = n_sub
    return e.step(dt, actuators)


def _sim(shape, **kw):
    return he.ElectricalSim(trace_config="short", ramp_shape=shape, **kw)


# ---------------------------------------------------------------------------
# drivers.  each returns {metric_name: value}
# ---------------------------------------------------------------------------

def drv_bringup(shape):
    """`bringup` P0 and P3 peaks -- the hardware-corroborated cold pins.

    Byte-for-byte the shape of test_soft_start_cold_start_bringup_peaks_
    preserved(), including `asymmetry_mode="off"` (these two anchors are
    SYMMETRIC-ERA numbers).  Both SOFT episodes are COLD (v_ss_start == 0.0),
    which is where the two shapes disagree by the full +25 %.
    """
    e = _sim(shape, asymmetry_mode="off")
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ
    p0 = 0.0
    for _ in range(50):
        r = _step(e, _act(sw=sw, aux=0))
        p0 = max(p0, abs(r["I_fc"]))
    aux = AUX_FC_REG | AUX_BT_REG
    for _ in range(400):
        _step(e, _act(sw=sw, aux=aux))
    sw |= SW_MOT_PWR
    p3_fc = p3_bt = 0.0
    for _ in range(400):
        r = _step(e, _act(sw=sw, aux=aux))
        p3_fc = max(p3_fc, abs(r["I_fc"]))
        p3_bt = max(p3_bt, abs(r["I_batt"]))
    return {"bringup P0 peak I_fc [A]": p0,
            "bringup P3 peak I_fc [A]": p3_fc,
            "bringup P3 peak I_bt [A]": p3_bt}


def drv_bringup_era(shape):
    """The same bring-up in the CAMPAIGN configuration (asymmetry default-on).

    The two pins above are symmetric-era records; every campaign since C1 runs
    `--asymmetry measured`, so this is the number a campaign actually reads.
    """
    e = _sim(shape)
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ
    p0 = 0.0
    for _ in range(50):
        r = _step(e, _act(sw=sw, aux=0))
        p0 = max(p0, abs(r["I_fc"]))
    aux = AUX_FC_REG | AUX_BT_REG
    for _ in range(400):
        _step(e, _act(sw=sw, aux=aux))
    sw |= SW_MOT_PWR
    p3 = 0.0
    for _ in range(400):
        r = _step(e, _act(sw=sw, aux=aux))
        p3 = max(p3, abs(r["I_fc"]))
    return {"bringup P0 peak I_fc, asym era [A]": p0,
            "bringup P3 peak I_fc, asym era [A]": p3}


def drv_scp_inrush(shape):
    """`scp-inrush`: MOT_PWR closes into the 0.9 mF VESC envelope under load.

    The scenario's own `vesc_cap_f` is used.  The cut current is the foldback
    clamp value at the instant the 250 us blank expires, so what the ramp shape
    moves is WHETHER and WHEN the fold binds, not the clamp level itself.
    """
    ARM_V, FOLD_A = 1.2, 6.5            # SCP_INRUSH_ARM_V / _FOLD_LOAD_A
    e = _sim(shape, c_vesc_f=0.9e-3)
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ
    for _ in range(50):
        _step(e, _act(sw=sw, aux=0))
    aux = AUX_FC_REG | AUX_BT_REG
    for _ in range(400):
        _step(e, _act(sw=sw, aux=aux))
    sw |= SW_MOT_PWR
    cuts = []
    armed = False
    v_step = float("nan")
    for _ in range(300):
        # apply_scenario()'s three-phase stimulus: the pulse arms on the
        # PREVIOUS tick's V-MOT, one-shot, withdrawn on the next call.
        i_mot = 0.0
        if not armed and e.node_voltage("MOT") >= ARM_V:
            i_mot, armed = FOLD_A, True
            v_step = e.node_voltage("MOT")
        _step(e, _act(sw=sw, aux=aux, i_motor_a=i_mot))
        cuts += [ev for ev in e.events if ev["kind"] == "scp_cut"]
        e.events = []
    return {"scp-inrush cuts": float(len(cuts)),
            "scp-inrush v_step [V]": v_step,
            "scp-inrush i_cut [A]": cuts[0]["i_cut"] if cuts else float("nan")}


def drv_handoff_sag(shape):
    """`handoff-sag`: the sw_ring cut current when the share latch opens FC_BUS.

    CONTROL DRIVER.  The cut happens from state ON, not from SOFT, so the ramp
    shape can only reach it through the DC operating point the switch was
    carrying -- which no ramp shape touches.  A non-zero delta here would mean
    the change had leaked outside the ramp.
    """
    e = _sim(shape)
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ
    aux = AUX_FC_REG | AUX_BT_REG
    for _ in range(50):
        _step(e, _act(sw=sw, aux=0))
    for _ in range(1500):
        _step(e, _act(sw=sw, aux=aux, i_motor_a=0.40))
    e.events = []
    rings = []
    for _ in range(50):                       # open FC_BUS: the share-cut latch
        _step(e, _act(sw=SW_BT_BUS | SW_BT_SEQ, aux=aux, i_motor_a=0.40))
        rings += [ev for ev in e.events
                  if ev["kind"] == "sw_ring" and ev["switch"] == "FC_BUS"]
        e.events = []
    return {"handoff-sag FC_BUS cut i [A]":
            rings[0]["i_cut"] if rings else float("nan")}


def drv_comm_loss(shape):
    """`comm-loss` warm re-close: FC_BUS + BT_BUS onto a bus bled to 0.4366 V.

    Byte-for-byte the shape of test_comm_loss_warm_reclose_from_0p44v_does_not_
    circulate(), the campaign-G reproduction.  THE TARGET OF THIS ROUND: the
    model residual is 3.7476 A against a board reading of 1.66 A (campaign H) /
    1.79 A (campaign G).
    """
    e = _sim(shape)
    e.v[he.N_BUS] = 0.4366
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ
    pk_fc = pk_bt = 0.0
    for _ in range(60):
        r = _step(e, _act(sw=sw, aux=0))
        pk_fc = max(pk_fc, abs(r["I_fc"]))
        pk_bt = max(pk_bt, abs(r["I_batt"]))
    return {"comm-loss re-close peak I_fc [A]": pk_fc,
            "comm-loss re-close peak I_bt [A]": pk_bt}


def drv_reentry(shape):
    """F7: the fw v27 battery-only re-entry -- FC_BUS re-closes onto a LIVE bus.

    The pre-charged episode with the SMALLEST span: v_ss_start is the live bus
    (~15.8 V) and v_ref is the FC boost output, so the two shapes disagree not
    on slope but on how long the switch sits in SOFT before completing.
    """
    e = _sim(shape)
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ
    aux = AUX_FC_REG | AUX_BT_REG
    for _ in range(50):
        _step(e, _act(sw=sw, aux=0))
    for _ in range(1500):
        _step(e, _act(sw=sw, aux=aux, i_motor_a=0.40))
    for _ in range(300):                       # the battery-only cut
        _step(e, _act(sw=SW_BT_BUS | SW_BT_SEQ, aux=aux, i_motor_a=0.40))
    fc = e.switches["FC_BUS"]
    pk = 0.0
    t_soft = None
    for i in range(200):                       # the re-entry
        r = _step(e, _act(sw=sw, aux=aux, i_motor_a=0.40))
        pk = max(pk, abs(r["I_fc"]))
        if t_soft is None and fc.state == "ON" and i > 8:
            t_soft = i
    return {"re-entry peak I_fc [A]": pk,
            "re-entry v_ss_start [V]": fc.v_ss_start,
            "re-entry ticks to ON [ms]":
                float(t_soft) if t_soft is not None else float("nan")}


def drv_fc_charge(shape):
    """`charge-to-full` / the F1 window entry: FC_CHARGE closes onto N_CHG.

    A 5.6 nF switch (~1.07 ms legacy ramp, 11992.6 V/s constant-slew) turning
    on from a live 15.9 V bus into the 10 uF charger node.  The fw v28
    conduction gate waits out a 30 ms blanking window, so what matters here is
    how much of that window the turn-on itself consumes and what the charger
    node's inrush peaks at.
    """
    e = _sim(shape)
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ
    aux = AUX_FC_REG | AUX_BT_REG
    for _ in range(50):
        _step(e, _act(sw=sw, aux=0))
    for _ in range(1000):
        _step(e, _act(sw=sw, aux=aux, i_motor_a=0.30))
    e.events = []
    chg = e.switches["FC_CHARGE"]
    pk = 0.0
    t_on = None
    for i in range(120):
        r = _step(e, _act(sw=sw | SW_FC_CHARGE, aux=aux,
                          i_motor_a=0.30, i_charge_a=0.30))
        pk = max(pk, abs(r["I_fc"]))
        if t_on is None and chg.state == "ON":
            t_on = i
    return {"FC_CHARGE turn-on peak I_fc [A]": pk,
            "FC_CHARGE ticks to ON [ms]":
                float(t_on) if t_on is not None else float("nan"),
            "FC_CHARGE cuts": float(chg.cut_count)}


def drv_regen(shape):
    """The ftp75c FC-charge / regen handoff: REGEN closes onto N_CHG.

    The other 5.6 nF charger-path switch, entered from a V-MOT node the regen
    event has lifted -- so, unlike FC_CHARGE above, the source node is the one
    the ramp has to track.
    """
    e = _sim(shape)
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ | SW_MOT_PWR
    aux = AUX_FC_REG | AUX_BT_REG
    for _ in range(50):
        _step(e, _act(sw=sw & ~SW_MOT_PWR, aux=0))
    for _ in range(1200):
        _step(e, _act(sw=sw, aux=aux, i_motor_a=0.30))
    rgn = e.switches["REGEN"]
    pk = 0.0
    t_on = None
    for i in range(120):
        r = _step(e, _act(sw=sw | SW_REGEN, aux=aux, i_motor_a=-1.5))
        pk = max(pk, abs(r["I_fc"]))
        if t_on is None and rgn.state == "ON":
            t_on = i
    return {"REGEN turn-on peak I_fc [A]": pk,
            "REGEN ticks to ON [ms]":
                float(t_on) if t_on is not None else float("nan"),
            "REGEN cuts": float(rgn.cut_count)}


def drv_clamp_cruise(shape):
    """The fw26-clamp legs: a settled two-source cruise, NO switch turn-on.

    CONTROL DRIVER.  Every switch reaches ON long before the clamp's stimulus
    arrives, so both delivered currents must be bit-identical across shapes.
    """
    e = _sim(shape)
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ | SW_MOT_PWR
    aux = AUX_FC_REG | AUX_BT_REG
    for _ in range(50):
        _step(e, _act(sw=sw & ~SW_MOT_PWR, aux=0))
    r = None
    for _ in range(2500):
        r = _step(e, _act(sw=sw, aux=aux, i_motor_a=2.0,
                          code_fc=0.75, code_bt=0.25))
    return {"clamp-cruise settled I_fc [A]": abs(r["I_fc"]),
            "clamp-cruise settled I_bt [A]": abs(r["I_batt"])}


DRIVERS = [
    ("bringup", drv_bringup),
    ("bringup (asym era)", drv_bringup_era),
    ("scp-inrush", drv_scp_inrush),
    ("handoff-sag [control]", drv_handoff_sag),
    ("comm-loss", drv_comm_loss),
    ("re-entry (F7)", drv_reentry),
    ("FC_CHARGE entry (F1)", drv_fc_charge),
    ("REGEN entry (ftp75c)", drv_regen),
    ("fw26-clamp [control]", drv_clamp_cruise),
]


def main():
    print("RT1987 ramp-shape A/B  (n_sub pinned at %d)" % N_SUB)
    print("datasheet slew: %.4f V/s at CSS 100 nF, %.4f V/s at CSS 5.6 nF"
          % (he.rt1987_slew_v_s(100.0), he.rt1987_slew_v_s(5.6)))
    print("")
    w = 40
    print("%-*s %16s %16s %12s" % (w, "metric", "legacy", "constant-slew", "delta %"))
    print("-" * (w + 48))
    for name, fn in DRIVERS:
        a = fn("legacy")
        b = fn("constant-slew")
        for k in a:
            va, vb = a[k], b[k]
            if va != va or vb != vb:               # NaN
                d = float("nan")
            elif va == 0.0:
                d = 0.0 if vb == 0.0 else float("inf")
            else:
                d = 100.0 * (vb - va) / va
            print("%-*s %16.6f %16.6f %12.3f" % (w, k[:w], va, vb, d))
    print("")
    print("NOTE: drivers reproduce each anchor's soft-start EPISODE, not its "
          "scenario. No firmware, no commander, no fault logic.")


if __name__ == "__main__":
    main()
