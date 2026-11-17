"""Minimal parser for KiCad 'export (version E)' netlists (cr/cr.net, eib/eib.net).

Returns the components (ref -> value, footprint) and the node list (ref, pin) -> (net, pinfunction), so that every
connection used by the permit simulation is read from the captured netlist, not typed by hand.
"""
import re

_TOK = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+')


def _parse_sexpr(text):
    stack, cur = [], []
    for m in _TOK.finditer(text):
        t = m.group(0)
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done = cur
            cur = stack.pop()
            cur.append(done)
        else:
            cur.append(t[1:-1] if t.startswith('"') else t)
    return cur[0]


def _find(lst, key):
    return [x for x in lst if isinstance(x, list) and x and x[0] == key]


class Netlist:
    def __init__(self, path):
        self.path = path
        with open(path, "r", encoding="utf-8") as fh:
            root = _parse_sexpr(fh.read())
        self.comps = {}      # ref -> dict(value=, footprint=)
        self.pin = {}        # (ref, pin) -> net name (leading '/' stripped), None for a no-connect
        self.pinfunc = {}    # (ref, pin) -> pinfunction
        self.nets = {}       # net -> [(ref, pin)]
        comps = _find(root, "components")[0]
        for c in _find(comps, "comp"):
            ref = _find(c, "ref")[0][1]
            val = _find(c, "value")[0][1]
            fp = _find(c, "footprint")
            self.comps[ref] = dict(value=val, footprint=fp[0][1] if fp else "")
        nets = _find(root, "nets")[0]
        for n in _find(nets, "net"):
            name = _find(n, "name")[0][1].lstrip("/")
            if name.startswith("unconnected-"):
                name = None   # KiCad's single-pin no-connect nets
            for node in _find(n, "node"):
                ref = _find(node, "ref")[0][1]
                pn = _find(node, "pin")[0][1]
                pf = _find(node, "pinfunction")
                self.pin[(ref, pn)] = name
                self.pinfunc[(ref, pn)] = pf[0][1] if pf else ""
                if name is not None:
                    self.nets.setdefault(name, []).append((ref, pn))

    def pins_of(self, ref):
        return {p: n for (r, p), n in self.pin.items() if r == ref}

    def func_map(self, ref):
        """pinfunction -> net for one part."""
        return {self.pinfunc[(r, p)]: n for (r, p), n in self.pin.items() if r == ref}

    def two_term(self, ref):
        p = self.pins_of(ref)
        return p.get("1"), p.get("2")

    def connects(self, ref, a, b):
        n1, n2 = self.two_term(ref)
        return {n1, n2} == {a, b}


def parse_value(s):
    """'47.0k 1%' -> 47000.0 ; '100nF 50V X7R' -> 1e-7 ; '6.49M 1%' -> 6.49e6 ; '68.0 1% 0.25W' -> 68.0"""
    tok = s.split()[0]
    m = re.match(r'^([0-9.]+)([pnumkMG]?)(F|H)?$', tok)
    if not m:
        raise ValueError("cannot parse value %r" % s)
    mult = dict(p=1e-12, n=1e-9, u=1e-6, m=1e-3, k=1e3, M=1e6, G=1e9).get(m.group(2), 1.0)
    return float(m.group(1)) * mult


if __name__ == "__main__":
    import sys
    nl = Netlist(sys.argv[1])
    for ref in sys.argv[2:]:
        print(ref, nl.comps.get(ref),
              sorted(((p, nl.pinfunc[(ref, p)], n) for (r, p), n in nl.pin.items() if r == ref)))
