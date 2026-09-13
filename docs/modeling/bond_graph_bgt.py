#!/usr/bin/env python3
"""Bond graph of the Scale Car DC Balancer Board (rev 20260622) in BondGraphTools.

Revamp of docs/modeling/bond-graph.md (the hand-drawn first pass) as an executable
model built with the ``BondGraphTools`` library (https://pypi.org/project/BondGraphTools/),
rendered through the library's own ``BondGraphTools.draw()``.

The model is hierarchical: the top level carries the power-path topology (sources,
boosts, the six RT1987 switches, VBUS / V-MOT / charger nodes, drivetrain, chopper,
charger, battery hub); each block is a compound sub-model with exposed ports and is
drawn on its own sheet.  Library limitations and the substitutions made for them are
listed in docs/modeling/bond-graph-bgt.md.

Run:  python3 docs/modeling/bond_graph_bgt.py [outdir]
Needs: pip install BondGraphTools  (matplotlib + networkx; no Julia / scikit.odes needed
for drawing).
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import BondGraphTools as bgt  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "bond-graph-bgt"

# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
_SE_NAMES = set()  # names of Se components, so the drawn "SS:" glyph can be relabelled


def Se(name):
    _SE_NAMES.add(name)
    return bgt.new("Se", name=name)


def R(name, **v):
    return bgt.new("R", name=name, value=v or None)


def C(name, **v):
    return bgt.new("C", name=name, value=v or None)


def I(name, **v):
    return bgt.new("I", name=name, value=v or None)


def TF(name, modulus):
    # BondGraphTools has no modulated transformer (MTF).  A TF with a *symbolic* modulus
    # is the closest acausal equivalent: the firmware / analog droop loop sets the symbol.
    return bgt.new("TF", name=name, value={"r": modulus})


def GY(name, modulus):
    return bgt.new("GY", name=name, value={"r": modulus})


def J0(name):
    return bgt.new("0", name=name)


def J1(name):
    return bgt.new("1", name=name)


def port(model, label):
    """Create + expose an external port on a compound model."""
    p = bgt.new("SS", name=label)
    bgt.add(model, p)
    bgt.expose(p, label)
    return p


def chain(*items):
    """connect(items[i], items[i+1]) for each consecutive pair (tuples allowed)."""
    for a, b in zip(items, items[1:]):
        bgt.connect(a, b)


# --------------------------------------------------------------------------------------
# sub-models  (element values/sources: docs/modeling/bond-graph.md §8)
# --------------------------------------------------------------------------------------
def fc_source_and_boost():
    """Fuel cell (Se + nonlinear R) -> input cap -> L/DCR -> TPS61288 boost -> output cap."""
    m = bgt.new(name="FC src+boost")
    v_oc = Se("V_fc,oc")                      # H-20 U-I curve, ~12 V OC
    r_int = R("R_fc,int ≈1.6Ω (nonlinear)")   # TODO(calibrate): fit to H-20 U-I data
    j_src = J1("fc,int")
    j_in = J0("fc,in")
    c_in = C("C_in 12.3µF")                   # BOM C1/C2/C3
    j_l = J1("L_fc")
    l_fc = I("L_fc 2.2µH")                    # BOM L-FC, Eaton HCM1A1305V3-2R2
    dcr = R("DCR 4.65mΩ + 2mΩ INA253")        # inductor DCR + INA253A1 shunt
    tf = TF("boost (1−D_fc)", "1-D_fc")       # averaged boost; D_fc trimmed by droop/MDAC
    j_out = J0("fc,out")
    c_out = C("C_out 3×22µF (≈30µF derated)")
    bgt.add(m, v_oc, r_int, j_src, j_in, c_in, j_l, l_fc, dcr, tf, j_out, c_out)
    out = port(m, "out")
    chain(v_oc, j_src, j_in, j_l, (tf, 0))
    chain(j_src, r_int)
    chain(j_in, c_in)
    chain(j_l, l_fc)
    chain(j_l, dcr)
    chain((tf, 1), j_out, out)
    chain(j_out, c_out)
    return m


def bt_boost():
    """Battery boost branch: input cap -> L/DCR -> TPS61288 boost -> output cap."""
    m = bgt.new(name="BT boost")
    j_in = J0("bt,in")
    c_in = C("C_in 12.3µF")
    j_l = J1("L_bt")
    l_bt = I("L_bt 2.2µH")
    dcr = R("DCR 4.65mΩ + 2mΩ INA253")
    tf = TF("boost (1−D_bt)", "1-D_bt")
    j_out = J0("bt,out")
    c_out = C("C_out 3×22µF (≈30µF derated)")
    bgt.add(m, j_in, c_in, j_l, l_bt, dcr, tf, j_out, c_out)
    p_in = port(m, "in")
    p_out = port(m, "out")
    chain(p_in, j_in, j_l, (tf, 0))
    chain(j_in, c_in)
    chain(j_l, l_bt)
    chain(j_l, dcr)
    chain((tf, 1), j_out, p_out)
    chain(j_out, c_out)
    return m


def battery_pack():
    """2S pack as a Thevenin source with a slow charge store (SoC) in series."""
    m = bgt.new(name="Battery 2S")
    v_oc = Se("V_bat,oc(SOC)")
    r_int = R("R_bat,int (tens of mΩ)")       # TODO(calibrate)
    q_soc = C("Q_soc (pack capacity)")        # TODO(calibrate); slow state
    j = J1("bat,int")
    bgt.add(m, v_oc, r_int, q_soc, j)
    p = port(m, "term")
    chain(v_oc, j, p)
    chain(j, r_int)
    chain(j, q_soc)
    return m


def rt1987_switch(label):
    """One RT1987 ideal-diode path switch: series 1-junction with Rds(on) (open = bond removed).

    BondGraphTools has no modulated resistor / switch element, so the switch is drawn as a
    fixed R; the GPIO listed in the name is what opens/closes it (see §6 of bond-graph.md).
    """
    m = bgt.new(name=label)
    j = J1("sw")
    r = R("Rds(on) | open")
    bgt.add(m, j, r)
    a = port(m, "a")
    b = port(m, "b")
    chain(a, j, b)
    chain(j, r)
    return m


def brake_chopper():
    """TL431 + BSP170P + 47 Ω 20 W: voltage-triggered dump, NOT under MCU control."""
    m = bgt.new(name="Chopper (hw)")
    j = J1("chop")
    q = R("BSP170P (TL431-triggered)")
    r = R("R_SNT 47Ω 20W")
    bgt.add(m, j, q, r)
    p = port(m, "in")
    chain(p, j)
    chain(j, q)
    chain(j, r)
    return m


def ag105_charger():
    """Ag105 MPPT buck charger as an averaged transformer with a loss element."""
    m = bgt.new(name="Ag105 chg")
    tf = TF("Ag105 (D_chg)", "D_chg")         # MPPT_DISABLE (GPIO 5, active-LOW) gates it
    j = J1("chg,out")
    r = R("R_chg,loss (η≈0.88)")
    bgt.add(m, tf, j, r)
    p_in = port(m, "in")
    p_out = port(m, "out")
    chain(p_in, (tf, 0))
    chain((tf, 1), j, p_out)
    chain(j, r)
    return m


def drivetrain(bench=False):
    """VESC inverter -> armature -> motor gyrator -> rotor -> (gearbox -> wheel -> vehicle | flywheel)."""
    name = "Drivetrain (bench)" if bench else "Drivetrain"
    m = bgt.new(name=name)
    tf_vesc = TF("VESC (D_m), bidirectional", "D_m")
    j_arm = J1("arm")
    r_a = R("R_a (winding)")                  # TODO(calibrate)
    l_a = I("L_a (winding, ≈0)")              # TODO(calibrate); may be dropped
    gy = GY("motor k_t", "k_t")               # TODO(calibrate)
    j_w = J1("ω")
    j_rot = I("J_rotor")                      # TODO(calibrate)
    b = R("b_visc")                           # TODO(calibrate)
    bgt.add(m, tf_vesc, j_arm, r_a, l_a, gy, j_w, j_rot, b)
    p_in = port(m, "in")
    chain(p_in, (tf_vesc, 0))
    chain((tf_vesc, 1), j_arm, (gy, 0))
    chain(j_arm, r_a)
    chain(j_arm, l_a)
    chain((gy, 1), j_w)
    chain(j_w, j_rot)
    chain(j_w, b)
    if bench:
        fly = I("J_flywheel (encoder here)")  # TODO(calibrate)
        bgt.add(m, fly)
        chain(j_w, fly)
    else:
        tf_g = TF("gearbox N_gear", "N_gear")  # TODO(calibrate)
        tf_r = TF("wheel r_wheel", "r_wheel")  # TODO(calibrate)
        j_v = J1("v")
        m_veh = I("m_veh")                     # TODO(calibrate)
        r_roll = R("R_roll")
        r_aero = R("R_aero(v) ∝ v²")
        f_grade = Se("F_grade")
        bgt.add(m, tf_g, tf_r, j_v, m_veh, r_roll, r_aero, f_grade)
        chain(j_w, (tf_g, 0))
        chain((tf_g, 1), (tf_r, 0))
        chain((tf_r, 1), j_v)
        chain(j_v, m_veh)
        chain(j_v, r_roll)
        chain(j_v, r_aero)
        chain(f_grade, j_v)
    return m


# --------------------------------------------------------------------------------------
# top level
# --------------------------------------------------------------------------------------
def board(bench=False):
    top = bgt.new(name="DC Balancer Board 20260622")

    fc = fc_source_and_boost()
    bt = bt_boost()
    bat = battery_pack()
    drv = drivetrain(bench=bench)
    chop = brake_chopper()
    chg = ag105_charger()

    sw_fc_bus = rt1987_switch("SW FC_BUS ·27")
    sw_bt_bus = rt1987_switch("SW BT_BUS ·28")
    sw_mot = rt1987_switch("SW MOT_PWR ·29")
    sw_regen = rt1987_switch("SW REGEN ·30")
    sw_fc_chg = rt1987_switch("SW FC_CHARGE ·31")
    sw_bt_seq = rt1987_switch("SW BT_SEQ ·32")

    vbus = J0("VBUS 16.0V")
    c_bus = C("C_bus 30–40µF")
    vmot = J0("V-MOT")
    c_mot = C("C_mot 470µF")        # ⚠ placement vs CAL: bond-graph.md §9
    chg_node = J0("CHG")
    c_cal = C("CAL (chg in)")          # ⚠ may be the same 470 µF — §9
    bat_node = J0("BAT")
    r_logic = R("R_logic LDO")
    ovp = R("BQ29200 OVP ·9")

    bgt.add(top, fc, bt, bat, drv, chop, chg,
            sw_fc_bus, sw_bt_bus, sw_mot, sw_regen, sw_fc_chg, sw_bt_seq,
            vbus, c_bus, vmot, c_mot, chg_node, c_cal, bat_node, r_logic, ovp)

    # --- sources -> VBUS -------------------------------------------------------------
    chain((fc, "out"), (sw_fc_bus, "a"))
    chain((sw_fc_bus, "b"), vbus)
    chain((bat, "term"), bat_node)
    chain(bat_node, (sw_bt_seq, "a"))
    chain((sw_bt_seq, "b"), (bt, "in"))
    chain((bt, "out"), (sw_bt_bus, "a"))
    chain((sw_bt_bus, "b"), vbus)
    chain(vbus, c_bus)
    # --- battery hub side loads ----------------------------------------------------------
    chain(bat_node, r_logic)
    chain(bat_node, ovp)
    # --- VBUS -> motor / regen node -----------------------------------------------------
    chain(vbus, (sw_mot, "a"))
    chain((sw_mot, "b"), vmot)
    chain(vmot, c_mot)
    chain(vmot, (drv, "in"))        # bidirectional: traction (->) / regen (<-)
    chain(vmot, (chop, "in"))
    # --- charger node: fed by FC_CHARGE (from VBUS) XOR REGEN (from V-MOT) ---------------
    chain(vbus, (sw_fc_chg, "a"))
    chain((sw_fc_chg, "b"), chg_node)
    chain(vmot, (sw_regen, "a"))
    chain((sw_regen, "b"), chg_node)
    chain(chg_node, c_cal)
    chain(chg_node, (chg, "in"))
    chain((chg, "out"), bat_node)   # charge return into the pack
    return top


# --------------------------------------------------------------------------------------
# drawing (through BondGraphTools.draw; only the glyph text is post-fixed)
# --------------------------------------------------------------------------------------
TITLES = {
    "DC Balancer Board 20260622": "Scale Car DC Balancer Board rev 20260622 — power bond graph (top level)",
    "FC src+boost": "FC source + boost (H-20 stack → TPS61288 BST-FC)",
    "BT boost": "Battery boost (TPS61288 BST-BT)",
    "Battery 2S": "Battery pack (2S, 7.4–8.4 V; Thevenin + SoC store)",
    "SW FC_BUS ·27": "RT1987 ideal-diode path switch (one of six; GPIO in name)",
    "Drivetrain": "Drivetrain — VESC inverter / motor / gearbox / vehicle",
    "Drivetrain (bench)": "Drivetrain — bench flywheel load (encoder at flywheel)",
    "Chopper (hw)": "Brake chopper — TL431 / BSP170P / 47 Ω 20 W (hardware-only, not MCU-controlled)",
    "Ag105 chg": "Ag105 MPPT charger (2S / 8.4 V, ≤ 2.5 A; MPPT_DISABLE GPIO 5)",
}


def render(model, filename):
    plt.close("all")
    bgt.draw(model)                 # library layout + glyphs; draws on the current figure
    fig = plt.gcf()
    ax = fig.gca()
    ax.set_title(TITLES.get(model.name, model.name), fontsize=13)
    x0, x1, y0, y1 = ax.axis()      # widen the library's 10 % margin so labels are not clipped
    mx, my = 0.30 * (x1 - x0), 0.12 * (y1 - y0)
    ax.axis([x0 - mx, x1 + mx, y0 - my, y1 + my])
    for t in ax.texts:              # the library draws Se as its internal SS glyph
        s = t.get_text()
        if s.startswith("SS: ") and s[4:] in _SE_NAMES:
            t.set_text("Se: " + s[4:])
        elif s.startswith("BG: "):  # compound sub-model
            t.set_text("[" + s[4:] + "]")
            t.set_fontweight("bold")
    fig.set_size_inches(16, 12)
    fig.tight_layout()
    path = OUT / filename
    fig.savefig(path, dpi=110)
    return path


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    top = board()
    paths = [
        render(top, "00_top_level.png"),
        render(next(c for c in top.components if c.name.startswith("FC src")), "01_fc_source_boost.png"),
        render(next(c for c in top.components if c.name.startswith("BT boost")), "02_bt_boost.png"),
        render(next(c for c in top.components if c.name.startswith("Battery")), "03_battery_pack.png"),
        render(next(c for c in top.components if c.name.startswith("SW FC_BUS")), "04_rt1987_switch.png"),
        render(next(c for c in top.components if c.name == "Drivetrain"), "05_drivetrain_vehicle.png"),
        render(drivetrain(bench=True), "06_drivetrain_bench.png"),
        render(next(c for c in top.components if c.name.startswith("Chopper")), "07_brake_chopper.png"),
        render(next(c for c in top.components if c.name.startswith("Ag105")), "08_ag105_charger.png"),
    ]
    # topology summary
    print(f"top level: {len(top.components)} components, {len(top.bonds)} bonds")
    for p in paths:
        print("wrote", p)


if __name__ == "__main__":
    main()
