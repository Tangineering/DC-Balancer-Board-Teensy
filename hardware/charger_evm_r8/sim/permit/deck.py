"""Deck builder for the CR + EIB permit-logic simulation.

Every CR and EIB part that belongs to the permit path is read from the captured netlists
(../../cr/cr.net, ../../eib/eib.net) with its value and pin-to-net map. The script adds only the elements that are
not on either board, each listed in EXTERNAL below with its source:
  - the Teensy 3V3 rail and GPIO pads, the MB tap resistors R170/R171, the FC_CHARGE EN net with its 10 kOhm bodge
    pull-down and the RT1987 EN pull-down, V-MOT and VBUS;
  - the J-TAP and J1 joints (switchable, for the unplug cases) and the nine W5 wires;
  - the BQ25798EVM side: REGN, the /CE pull-ups R272/R272b, the ILIM_HIZ network (R21 0 ohm link, R23 49.9k,
    R256 200k, C252 2.2 nF) and the AGND return.
Comparator outputs may be replaced by ideal sources (logic-only mode) for the exhaustive cross-check.
"""
import os
import re

from netparse import Netlist, parse_value

HERE = os.path.dirname(os.path.abspath(__file__))
DESIGN = os.path.abspath(os.path.join(HERE, "..", ".."))
CR_NET = os.path.join(DESIGN, "cr", "cr.net")
EIB_NET = os.path.join(DESIGN, "eib", "eib.net")
LIB = os.path.abspath(os.path.join(HERE, "..", "models", "permit_behavioural.lib"))

CR = Netlist(CR_NET)
EIB = Netlist(EIB_NET)

# CR parts outside the permit path (eFuse power section, its IMON/FLAG outputs and the header/pads): not modelled.
CR_EXCLUDE = {"U101", "R101", "R102", "R103", "R104", "R105", "R106s", "C101", "C102a", "C102b", "C102c", "C103",
              "D103", "D107", "R129", "C129"}
# EIB DNP set (gen/netlist.py dnp=True; dec2-eib decision 2, r9-2)
EIB_EXCLUDE = {"U203", "U204", "C203", "C204", "R258", "R259", "R260", "R261", "R262", "R263", "R264", "R265"}

# External (off-board) elements and their sources; values used by build()
EXTERNAL = dict(
    R170=(10.0e3, "MB V-MOT tap joint series resistor, design doc r1-17 (line 219) and B.2"),
    R171=(10.0e3, "MB VBUS tap joint series resistor, design doc r1-17 (line 219) and B.2"),
    R_BODGE=(10.0e3, "MB 10 kOhm EN-to-GND bodge on every RT1987 EN (CLAUDE.md section 2 note)"),
    REN_PD=(730e3, "RT1987 internal EN pull-down 475/730/985 kOhm (RT1987_DS-00 p.7, as quoted in REVIEW LOG-1)"),
    C_EN=(100e-12, "ASSUMPTION: FC_CHARGE EN net capacitance (RT1987 EN pin + MB trace)"),
    C_MBPIN=(20e-12, "ASSUMPTION: MB trace + J1/J-TAP conductor capacitance on each Teensy-driven net"),
    R_HARN=(0.1, "ASSUMPTION: J-TAP T6 conductor + crimp resistance"),
    R_W5=(0.064, "ASSUMPTION: one 0.3 m 28 AWG W5 wire (0.213 ohm/m)"),
    L_W5=(0.3e-6, "ASSUMPTION: 1 uH/m for a free W5 wire, 0.3 m"),
    R_W5D=(100.0, "ASSUMPTION: damping across L_W5 (lets a wire open without an infinite dI/dt; tau 3 ns)"),
    R_REGN=(2.0, "ASSUMPTION: BQ25798 REGN LDO output resistance"),
    R272=(47.0e3, "EVM /CE pull-up to REGN, design doc B.6 row R272/R272b"),
    R272b=(47.0e3, "EVM /CE pull-up to REGN, design doc B.6 row R272/R272b"),
    R23=(49.9e3, "EVM R23 replaced by 49.9 kOhm 1 %, design doc B.6 EVM-side list"),
    R256=(200e3, "R256 200 kOhm across the JP21 posts (ILIM_HIZ to AGND), design doc B.6"),
    C252=(2.2e-9, "C252 2.2 nF across the JP21 posts, design doc B.6"),
    R21=(1e-3, "EVM R21 replaced by a 0 ohm link (E2 -> JP14 pin 2 -> ILIM_HIZ), design doc B.6 / EM3"),
    R_AGND=(0.01, "ASSUMPTION: EVM AGND (E8/TP49) to system GND return"),
    C_PIN_CE=(10e-12, "ASSUMPTION: BQ25798 /CE pin + EVM trace capacitance"),
)


def node(side, net):
    if net is None:
        return None
    if side == "c" and net == "GND":
        return "0"
    s = re.sub(r"[^A-Za-z0-9_]", "_", net).lower()
    return "%s_%s" % (side, s)


def pwl(points):
    if len(points) == 1:
        points = [points[0], (1.0, points[0][1])]
    return "PWL(" + " ".join("%.9g %.9g" % (t, v) for t, v in points) + ")"


DEFAULT_LVC = dict(f=0.5, va=0.8, rs=1.0)
DEFAULT_CMP = dict(vos=0.0, vhys=6e-3, vref=1.242, vpor=1.65, tpor=1.9e-3, tpd=2e-6, va=0.8, tref=1e-6, refhd=0.2,
                   tpd100=None)
# tpd100 = None: fixed propagation delay tpd (tlv3012b); a number: overdrive-dependent delay with that value at VOD 100 mV
# (tlv3012b_od, fitted to SBOS300C Figures 8-12 and 8-13; see od_check.py)

# Supply currents of the CR and EIB parts that the deck does not otherwise draw (r9_calc.py rail_load(), R9.H15 rows,
# docs/reviews/charger_eval_2026-11-05/round4/calc/r9_calc.py:241-257). The resistive loads of that list (REF divider
# R184/R185, R274 bleed, the four ribbon input paths, R113/R116/R187) are part of the netlist and need no addition.
#   'parts' (default): 5 CR LVC packages x ICC 10 uA max + 4 TLV3012B x (IQ 5 uA max - 3.6 uA already in the model)
#                      on the CR rail; 2 EIB LVC packages x 10 uA on the EIB rail.
#   'max'  : 'parts' plus the two state-dependent rows of R9.H15: STAT held LOW by the BQ25798 open drain (R107 +
#            W5 4 + R275, about 0.30 mA; modelled as a 50 ohm switch from the EVM STAT pad E7 to AGND) and the H1
#            readback into Teensy pin 34 configured INPUT_PULLDOWN (100 kOhm ASSUMPTION as in r9_calc.py R_PD_IMX,
#            through R126; 33 uA while H1 is HIGH). This is the R9.H24(a)/(d) worst static base load.
#   'none' : no addition (the model of the first run, 2026-11-14; used to bound the T6-open rail decay).
# The constant ICC/IQ currents are scaled by min(1, V/1.65 V) below the LVC minimum supply (ASSUMPTION; keeps a dead rail
# from being driven negative).
BASE_LOAD = dict(cr_icc=5 * 10e-6 + 4 * (5e-6 - 3.6e-6), eib_icc=2 * 10e-6, r_stat_od=50.0, r_pd34=100e3)


class Case:
    """Simulation case description; every field has a default that represents the healthy board."""

    def __init__(self, name, t_stop, **kw):
        self.name = name
        self.t_stop = t_stop
        self.t_max = kw.pop("t_max", min(2e-6, t_stop / 2000))
        self.v3 = kw.pop("v3", [(0, 3.3)])             # Teensy 3V3 rail (PWL points)
        self.vbus = kw.pop("vbus", [(0, 15.9)])
        self.vmot = kw.pop("vmot", [(0, 15.9)])
        self.regn = kw.pop("regn", [(0, 0.0)])          # BQ25798 REGN (0 = absent)
        # Teensy pads: {pin: dict(en=[pts], lvl=[pts], ikeep=A)}; pins 5 (CHG_ARM), 31 (FCC EN), 33 (QUAL), 34 (H1_RB)
        self.pins = {5: dict(en=[(0, 0)], lvl=[(0, 0)]), 31: dict(en=[(0, 0)], lvl=[(0, 0)]),
                     33: dict(en=[(0, 0)], lvl=[(0, 0)]), 34: dict(en=[(0, 0)], lvl=[(0, 0)])}
        self.pins.update(kw.pop("pins", {}))
        self.jtap = kw.pop("jtap", {})                  # {J102 pin str: [pts]} 1 = connected
        self.w5 = kw.pop("w5", {})                      # {J101 pin str: [pts]} 1 = connected
        self.bridges = kw.pop("bridges", [])            # [(side 'c'|'e', padA, padB, R_ohm, t_on)]
        self.overrides = kw.pop("overrides", {})        # {ref: value | None (removed)} on either board
        self.ext = kw.pop("ext", {})                    # overrides of EXTERNAL values
        self.lvc = dict(DEFAULT_LVC, **kw.pop("lvc", {}))
        self.lvc_per = kw.pop("lvc_per", {})            # {ref: dict}
        self.cmp = dict(DEFAULT_CMP, **kw.pop("cmp", {}))
        self.cmp_per = kw.pop("cmp_per", {})            # {ref: dict}
        self.vtn = kw.pop("vtn", 1.6)
        self.vtp = kw.pop("vtp", 1.4)
        self.logic_only = kw.pop("logic_only", None)    # {comparator ref: [pts]} replaces the comparator by a source
        self.base_load = kw.pop("base_load", "parts")   # 'parts', 'max' or 'none' (see BASE_LOAD)
        self.extra = kw.pop("extra", [])
        self.meta = kw.pop("meta", {})
        # warm start: the deck first ramps the Teensy 3V3 from 0 V in 20 us and lets the CR rail (R175/C125,
        # tau 0.7 ms) and the comparator POR (<= 1.9 ms) settle for 'preroll' seconds; every event time of the case
        # is shifted by preroll. This avoids a metastable DC operating point (comparators at the POR threshold with
        # their push-pull stages half on), which ngspice otherwise finds for a deck that starts at 3.3 V.
        self.preroll = kw.pop("preroll", 0.0)
        if kw:
            raise TypeError("unknown case fields %s" % list(kw))

    def ev(self, key):
        return self.ext.get(key, EXTERNAL[key][0])


GATE_KIND = {"SN74LVC3G04": "inv", "LVC2G32": "or2", "LVC2G08": "and2", "SN74LVC1G11": "and3",
             "SN74LVC3G06": "inv_od", "SN74LVC1G06": "inv_od"}


def _gate_sections(nl, ref):
    """From pinfunctions: list of (inputs[], output) per section."""
    fm = {nl.pinfunc[(r, p)]: n for (r, p), n in nl.pin.items() if r == ref}
    secs = []
    if "Y" in fm:   # single gate
        ins = [fm[k] for k in ("A", "B", "C") if k in fm]
        secs.append((ins, fm["Y"]))
    else:
        for s in "123":
            if s + "Y" in fm:
                ins = [fm[s + k] for k in ("A", "B") if s + k in fm]
                secs.append((ins, fm[s + "Y"]))
    return secs, fm.get("VCC"), fm.get("GND")


def _passives(lines, nl, side, exclude, overrides):
    nnc = [0]

    def nn(net):
        n = node(side, net)
        if n is None:
            nnc[0] += 1
            n = "%s_nc%d" % (side, nnc[0])
        return n
    for ref, c in sorted(nl.comps.items()):
        if ref in exclude:
            continue
        if ref in overrides and overrides[ref] is None:
            lines.append("* %s removed by case override" % ref)
            continue
        kind = ref.rstrip("0123456789abs")[:1]
        if ref.startswith("R") or (ref.startswith("C") and not ref.startswith("CH")):
            a, b = nl.two_term(ref)
            if a is None or b is None:
                continue
            val = overrides.get(ref, parse_value(c["value"]))
            lines.append("%s_%s %s %s %.6g" % (ref[0], side + ref, nn(a), nn(b), val))
        elif c["value"] == "BAV199":
            p = nl.pins_of(ref)
            lines.append("D%slo %s %s DBAV199" % (side + ref, nn(p["1"]), nn(p["3"])))
            lines.append("D%sup %s %s DBAV199" % (side + ref, nn(p["3"]), nn(p["2"])))
    return nn


def _shift(points, pre):
    if not pre:
        return points
    return [(0.0, points[0][1])] + [(t + pre, v) for t, v in points]


def build(case, save=None):
    pre = case.preroll
    sh = lambda pts: _shift(pts, pre)
    L = ["* permit simulation deck: case %s (preroll %g s: event times below are shifted by it)" % (case.name, pre),
         "* generated by sim/permit/deck.py from %s and %s" % (os.path.relpath(CR_NET, HERE), os.path.relpath(EIB_NET, HERE)),
         ".include '%s'" % LIB.replace("\\", "/"),
         ".options method=gear rshunt=1e10 reltol=1e-4 abstol=1e-11 vntol=1e-6 itl4=200",
         ".model SWJ SW(VT=0.5 VH=0.05 RON=0.05 ROFF=1e12)"]
    ov = case.overrides
    nnc = _passives(L, CR, "c", CR_EXCLUDE, ov)
    nne = _passives(L, EIB, "e", EIB_EXCLUDE, ov)
    lv = case.lvc
    # ---- gates
    for nl, side, nn in ((CR, "c", nnc), (EIB, "e", nne)):
        for ref, c in sorted(nl.comps.items()):
            kind = GATE_KIND.get(c["value"])
            if kind is None:
                continue
            secs, vcc, gnd = _gate_sections(nl, ref)
            p = dict(lv, **case.lvc_per.get(ref, {}))
            for i, (ins, out) in enumerate(secs):
                sub = "lvc_" + kind
                L.append("X%s_%s_%d %s %s %s %s %s f=%g va=%g rs=%g" % (
                    side, ref, i + 1, " ".join(nn(x) for x in ins), nn(out), nn(vcc), nn(gnd), sub,
                    p["f"], p["va"], p["rs"]))
    # ---- comparators
    for ref, c in sorted(CR.comps.items()):
        if c["value"] != "TLV3012B":
            continue
        pm = CR.pins_of(ref)
        if case.logic_only and ref in case.logic_only:
            L.append("V%s_src %s_s 0 %s" % (ref, ref.lower(), pwl(sh(case.logic_only[ref]))))
            L.append("R%s_src %s_s %s 40" % (ref, ref.lower(), nnc(pm["1"])))
            continue
        p = dict(case.cmp, **case.cmp_per.get(ref, {}))
        if p.get("tpd100"):
            L.append("X%s %s %s %s %s %s %s tlv3012b_od vos=%g vhys=%g vref=%g vpor=%g tpor=%g tpd100=%g va=%g tref=%g "
                     "refhd=%g" % (ref, nnc(pm["1"]), nnc(pm["2"]), nnc(pm["3"]), nnc(pm["4"]), nnc(pm["5"]), nnc(pm["6"]),
                                   p["vos"], p["vhys"], p["vref"], p["vpor"], p["tpor"], p["tpd100"], p["va"], p["tref"],
                                   p["refhd"]))
            continue
        L.append("X%s %s %s %s %s %s %s tlv3012b vos=%g vhys=%g vref=%g vpor=%g tpor=%g tpd=%g va=%g tref=%g refhd=%g"
                 % (ref, nnc(pm["1"]), nnc(pm["2"]), nnc(pm["3"]), nnc(pm["4"]), nnc(pm["5"]), nnc(pm["6"]),
                    p["vos"], p["vhys"], p["vref"], p["vpor"], p["tpor"], p["tpd"], p["va"], p["tref"], p["refhd"]))
    # ---- EIB MOSFETs
    for ref, c in sorted(EIB.comps.items()):
        if not ref.startswith("Q"):
            continue
        pm = EIB.pins_of(ref)
        g, s, d = nne(pm["1"]), nne(pm["2"]), nne(pm["3"])
        if c["value"] == "BSS84":
            L.append("X%s %s %s %s pmbss84 vtp=%g" % (ref, d, g, s, case.vtp))
        else:
            L.append("X%s %s %s %s nm2n7002 vtn=%g" % (ref, d, g, s, case.vtn))
    # ---- MB / Teensy side
    L.append("* ---- MB and Teensy side (EXTERNAL)")
    v3 = case.v3 if not pre else [(0.0, 0.0), (20e-6, case.v3[0][1])] + [(t + pre, v) for t, v in case.v3]
    L.append("V3 m_t3v3 0 %s" % pwl(v3))
    L.append("Vbus m_vbus 0 %s" % pwl(sh(case.vbus)))
    L.append("Vmot m_vmot 0 %s" % pwl(sh(case.vmot)))
    L.append("R170 m_vmot m_t1 %g" % case.ev("R170"))
    L.append("R171 m_vbus m_t2 %g" % case.ev("R171"))
    pad_node = {5: "m_p5", 31: "m_t5", 33: "m_t10", 34: "m_t13"}
    for pin, nd in pad_node.items():
        d = case.pins[pin]
        L.append("Ven%d m_en%d 0 %s" % (pin, pin, pwl(sh(d["en"]))))
        L.append("Vlv%d m_lv%d 0 %s" % (pin, pin, pwl(sh(d["lvl"]))))
        L.append("Xpad%d %s m_en%d m_lv%d m_t3v3 tpad ikeep=%g" % (pin, nd, pin, pin, d.get("ikeep", 0.0)))
        L.append("Cmb%d %s 0 %g" % (pin, nd, case.ev("C_MBPIN")))
    L.append("Rbodge m_t5 0 %g" % case.ev("R_BODGE"))
    L.append("Renpd m_t5 0 %g" % case.ev("REN_PD"))
    L.append("Cen m_t5 0 %g" % case.ev("C_EN"))
    # J1 pin 11 (CHG_ARM) is a fixed joint (Samtec header): MB pin-5 net -> CR CHG_ARM
    L.append("Rj1_11 m_p5 %s 0.05" % node("c", CR.pin[("J1", "11")]))
    # J1 pin 3 (STAT) -> MB -> Teensy pin 6 input: a pad with no driver (10 pF)
    L.append("Cj1_3 %s 0 10p" % node("c", CR.pin[("J1", "3")]))
    # J-TAP joints (switchable)
    mb_of = {"1": "m_t2", "4": "m_t5", "5": "m_t13", "6": "m_t3v3h", "7": "m_t1", "10": "m_t10"}
    L.append("Rharn m_t3v3 m_t3v3h %g" % case.ev("R_HARN"))
    for pin, mb in mb_of.items():
        crn = node("c", CR.pin[("J102", pin)])
        pts = case.jtap.get(pin, [(0, 1)])
        L.append("Vjt%s m_jt%s 0 %s" % (pin, pin, pwl(sh(pts))))
        L.append("Sjt%s %s %s m_jt%s 0 SWJ" % (pin, mb, crn, pin))
    # ---- W5 wires J101.n <-> J201.n
    L.append("* ---- W5 wires (EXTERNAL)")
    for pin in ("1", "2", "3", "4", "5", "7", "8", "9", "10"):
        a = node("c", CR.pin[("J101", pin)])
        b = node("e", EIB.pin[("J201", pin)])
        pts = case.w5.get(pin, [(0, 1)])
        L.append("Vw%s m_w%s 0 %s" % (pin, pin, pwl(sh(pts))))
        L.append("Sw%s %s w%s_m m_w%s 0 SWJ" % (pin, a, pin, pin))
        L.append("Rw%s w%s_m w%s_l %g" % (pin, pin, pin, case.ev("R_W5")))
        L.append("Lw%s w%s_l %s %g" % (pin, pin, b, case.ev("L_W5")))
        L.append("Rwd%s w%s_l %s %g" % (pin, pin, b, case.ev("R_W5D")))
    # ---- bridges (solder bridges between wire pads)
    for i, (side, pa, pb, rb, ton) in enumerate(case.bridges):
        nl = CR if side == "c" else EIB
        jref = "J101" if side == "c" else "J201"
        na = node(side, nl.pin[(jref, pa)])
        nb = node(side, nl.pin[(jref, pb)])
        L.append(".model SWB%d SW(VT=0.5 VH=0.05 RON=%g ROFF=1e12)" % (i, rb))
        if ton is None:      # bridge present from power-up (a solder bridge left at assembly)
            L.append("Vbr%d m_br%d 0 PWL(0 1 1 1)" % (i, i))
        else:
            L.append("Vbr%d m_br%d 0 PWL(0 0 %g 0 %g 1)" % (i, i, ton + pre, ton + pre + 1e-7))
        L.append("Sbr%d %s %s m_br%d 0 SWB%d" % (i, na, nb, i, i))
    # ---- EVM side
    L.append("* ---- BQ25798EVM side (EXTERNAL)")
    L.append("Vregn m_regn 0 %s" % pwl(sh(case.regn)))
    L.append("Rregn m_regn e_regn_e1 %g" % case.ev("R_REGN"))
    L.append("R272 e_regn_e1 e_nce_drv %g" % case.ev("R272"))
    L.append("R272b e_regn_e1 e_nce_drv %g" % case.ev("R272b"))
    L.append("Cce e_nce_drv e_agnd %g" % case.ev("C_PIN_CE"))
    L.append("R21 e_ilim_feed e_ilim_hold %g" % case.ev("R21"))
    L.append("R23 e_ilim_hold e_agnd %g" % case.ev("R23"))
    L.append("R256 e_ilim_hold e_agnd %g" % case.ev("R256"))
    L.append("C252 e_ilim_hold e_agnd %g" % case.ev("C252"))
    L.append("Ragnd e_agnd 0 %g" % case.ev("R_AGND"))
    # ---- base loads (BASE_LOAD)
    c3, e3 = "c_3v3", node("e", EIB.pin[("J201", "1")])   # CR rail node (net 3V3 behind R175) and EIB rail node
    if case.base_load != "none":
        L.append("* ---- part supply currents not drawn by the models (BASE_LOAD, r9_calc.py R9.H15)")
        L.append("Bicc_cr %s 0 I = %g*min(1, max(V(%s),0)/1.65)" % (c3, BASE_LOAD["cr_icc"], c3))
        L.append("Bicc_eib %s 0 I = %g*min(1, max(V(%s),0)/1.65)" % (e3, BASE_LOAD["eib_icc"], e3))
    if case.base_load == "max":
        L.append("* ---- R9.H15 worst static: STAT held LOW by the BQ25798, pin 34 INPUT_PULLDOWN")
        L.append("Rstat_od %s e_agnd %g" % (node("e", EIB.pin[("E7", "1")]), BASE_LOAD["r_stat_od"]))
        L.append("Rpd34 m_t13 0 %g" % BASE_LOAD["r_pd34"])
    elif case.base_load not in ("parts", "none"):
        raise ValueError(case.base_load)
    L.extend(case.extra)
    if save:
        L.append(".save " + " ".join("v(%s)" % s if not s.startswith("@") and not s.startswith("i(") else s
                                     for s in save))
    L.append(".tran %g %g 0 %g" % (case.t_max, case.t_stop + pre, case.t_max))
    L.append(".end")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    c = Case("smoke", 2e-3)
    print(build(c))
