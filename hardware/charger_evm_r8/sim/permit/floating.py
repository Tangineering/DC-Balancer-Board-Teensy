"""Static floating-input scan of the permit path, per scenario.

An input (a CMOS gate input, a comparator input, a MOSFET gate, a BQ25798 /CE or ILIM_HIZ pin, the RT1987
FC_CHARGE EN pin, the U101 EN/MODE pins) is 'floating' in a scenario when its net has no resistive path (through
resistors of either board, the W5 wires, the J-TAP and J1 joints and the off-board resistors of deck.EXTERNAL) to a
node that something drives in that scenario. Driven nodes: GND/AGND, the VBUS/V-MOT/REGN/Teensy-3V3 sources, a Teensy
pin that is driven, and a push-pull output whose supply is present. Open-drain outputs do not count as drivers.
Inputs reached only through >= 1 MOhm are reported as 'weak'.
"""
from deck import CR, EIB, CR_EXCLUDE, EIB_EXCLUDE, GATE_KIND, _gate_sections
from netparse import parse_value


class UF:
    def __init__(self):
        self.p = {}

    def f(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def u(self, a, b):
        self.p[self.f(a)] = self.f(b)


def _board_edges(nl, side, exclude, rmax):
    e = []
    for ref, c in nl.comps.items():
        if ref in exclude or not ref.startswith("R"):
            continue
        a, b = nl.two_term(ref)
        if a is None or b is None:
            continue
        if parse_value(c["value"]) <= rmax:
            e.append(("%s:%s" % (side, a), "%s:%s" % (side, b)))
    return e


def _inputs():
    ins = []
    for nl, side in ((CR, "c"), (EIB, "e")):
        for ref, c in nl.comps.items():
            kind = GATE_KIND.get(c["value"])
            if kind:
                secs, vcc, gnd = _gate_sections(nl, ref)
                for k, (ii, y) in enumerate(secs):
                    for x in ii:
                        ins.append(("%s %s sect %d input" % (ref, c["value"], k + 1), "%s:%s" % (side, x),
                                    "cr" if side == "c" else "eib"))
            if c["value"] == "TLV3012B" and ref not in EIB_EXCLUDE:
                pm = nl.pins_of(ref)
                ins.append(("%s IN+" % ref, "%s:%s" % (side, pm["3"]), "cr"))
                ins.append(("%s IN-" % ref, "%s:%s" % (side, pm["4"]), "cr"))
            if ref.startswith("Q"):
                ins.append(("%s gate" % ref, "%s:%s" % (side, nl.pins_of(ref)["1"]), "always"))
    ins.append(("BQ25798 /CE (TP36, via E5)", "x:CE_PIN", "always"))
    ins.append(("BQ25798 ILIM_HIZ (TP33, via E3)", "x:ILIM_PIN", "always"))
    ins.append(("RT1987 D-BC-FC EN (MB FC_CHARGE EN net)", "m:T5", "always"))
    return ins


def _drivers(sc):
    """Driven nodes for scenario dict sc."""
    d = {"c:GND", "e:AGND", "m:GND", "m:VBUS", "m:VMOT", "x:REGN"}
    if sc["teensy3v3"]:
        d.add("m:3V3")
    for p, nd in (("p5", "m:P5"), ("p31", "m:T5"), ("p33", "m:T10")):
        if sc["pins_driven"]:
            d.add(nd)
    cr_pow = sc["teensy3v3"] and sc["jtap"]
    if cr_pow:
        for ref, c in CR.comps.items():
            if GATE_KIND.get(c["value"]) or c["value"] == "TLV3012B":
                if ref in CR_EXCLUDE:
                    continue
                if GATE_KIND.get(c["value"]):
                    secs, _, _ = _gate_sections(CR, ref)
                    for ii, y in secs:
                        if y is not None:
                            d.add("c:%s" % y)
                else:
                    d.add("c:%s" % CR.pins_of(ref)["1"])
                    if CR.pins_of(ref).get("5"):
                        d.add("c:%s" % CR.pins_of(ref)["5"])   # the comparator's own REF output
    return d


SCENARIOS = [
    dict(name="normal (Teensy running, all leads on)", teensy3v3=True, pins_driven=True, jtap=True, w5=True, e1=True,
         e3=True, e5=True, j1=True),
    dict(name="Teensy reset (pins high-Z)", teensy3v3=True, pins_driven=False, jtap=True, w5=True, e1=True, e3=True,
         e5=True, j1=True),
    dict(name="J-TAP unplugged", teensy3v3=True, pins_driven=True, jtap=False, w5=True, e1=True, e3=True, e5=True,
         j1=True),
    dict(name="W5 all nine wires open", teensy3v3=True, pins_driven=True, jtap=True, w5=False, e1=True, e3=True,
         e5=True, j1=True),
    dict(name="E1 lead off (EVM REGN not at the EIB)", teensy3v3=True, pins_driven=True, jtap=True, w5=True, e1=False,
         e3=True, e5=True, j1=True),
    dict(name="E5 lead off", teensy3v3=True, pins_driven=True, jtap=True, w5=True, e1=True, e3=True, e5=False,
         j1=True),
    dict(name="E3 and E2 leads off", teensy3v3=True, pins_driven=True, jtap=True, w5=True, e1=True, e3=False,
         e5=True, j1=True),
    dict(name="CR lifted off the MB J1 (CHG_ARM not connected)", teensy3v3=True, pins_driven=True, jtap=True,
         w5=True, e1=True, e3=True, e5=True, j1=False),
]


def analyse():
    ins = _inputs()
    rows = []
    for sc in SCENARIOS:
        for rmax, tag in ((1e8, "floating"), (0.99e6, "weak (>= 1 MOhm only)")):
            uf = UF()
            edges = _board_edges(CR, "c", CR_EXCLUDE, rmax) + _board_edges(EIB, "e", EIB_EXCLUDE, rmax)
            # off-board links
            ext = [("m:VMOT", "m:T1"), ("m:VBUS", "m:T2"), ("m:T5", "m:GND"),   # R170, R171, bodge + REN_PD
                   ("x:CE_PIN", "x:REGN"),                                       # R272 / R272b on the EVM
                   ("x:ILIM_PIN", "e:AGND"), ("e:AGND", "c:GND"), ("m:GND", "c:GND")]  # R23/R256, returns
            if sc["e1"]:
                ext.append(("x:REGN", "e:REGN_E1"))
            if sc["e5"]:
                ext.append(("e:nCE_DRV", "x:CE_PIN"))
            if sc["e3"]:
                ext += [("e:ILIM_HOLD", "x:ILIM_PIN"), ("e:ILIM_FEED", "x:ILIM_PIN")]
            if sc["j1"]:
                ext.append(("m:P5", "c:%s" % CR.pin[("J1", "11")]))
            if sc["jtap"]:
                for p, mb in (("1", "m:T2"), ("4", "m:T5"), ("5", "m:T13"), ("6", "m:3V3"), ("7", "m:T1"),
                              ("10", "m:T10")):
                    ext.append((mb, "c:%s" % CR.pin[("J102", p)]))
            if sc["w5"]:
                for p in ("1", "2", "3", "4", "5", "7", "8", "9", "10"):
                    ext.append(("c:%s" % CR.pin[("J101", p)], "e:%s" % EIB.pin[("J201", p)]))
            for a, b in edges + ext:
                uf.u(a, b)
            drv = _drivers(sc)
            droots = {uf.f(x) for x in drv}
            cr_pow = sc["teensy3v3"] and sc["jtap"]
            pw = dict(cr=cr_pow, eib=cr_pow and sc["w5"], always=True)
            for label, nd, dom in ins:
                if not pw[dom]:
                    continue      # input of an unpowered device: no logic decision is taken
                if uf.f(nd) not in droots:
                    rows.append(dict(scenario=sc["name"], class_=tag, input=label, net=nd))
        # by-design no-connects on U101 (internal pulls; TCKE1401NM DS Rev. 3.0 Table 6.1, REVIEW PWR-4)
        for pnum, pname in (("12", "EN"), ("11", "MODE")):
            if CR.pin.get(("U101", pnum)) is None:
                rows.append(dict(scenario=sc["name"], class_="no-connect by design (internal pull)",
                                 input="U101 %s (pin %s)" % (pname, pnum), net="nc"))
    # de-duplicate 'weak' rows that are already 'floating'
    seen = {(r["scenario"], r["input"]) for r in rows if r["class_"] == "floating"}
    return [r for r in rows if not (r["class_"].startswith("weak") and (r["scenario"], r["input"]) in seen)]


if __name__ == "__main__":
    for r in analyse():
        print(r)
