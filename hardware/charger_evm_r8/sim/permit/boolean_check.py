"""Exhaustive Boolean check of the CR permit gate and the EIB channel polarities, evaluated from the captured netlists.

The gate network is not typed in here: every LVC section (inputs, output, function) is read from cr.net / eib.net
(pinfunction names and the part value), and the logic is evaluated by repeated passes until the nets settle. The
result is compared with the B.1 equations (the intended truth table) and with the F.2 / B.7 mode rows.
"""
import itertools

from deck import CR, EIB, GATE_KIND, _gate_sections

PRIMARY = ["CHG_ARM", "QUAL", "H1", "UVB", "FCCN", "FCC_ON"]   # Teensy P5, Teensy QUAL, four comparator outputs
OUTPUTS = ["P5N", "FCCNN", "H1U", "FCCP", "QF", "GATE", "ILIM_REL", "CE_DRV", "RFC_OFF"]

# CR -> EIB signal chain; every link is asserted against the netlists before it is used.
CHAIN = [  # (CR driver net, CR series R, CR wire-pad net, J101 pin, EIB series R, EIB gate input net)
    ("CE_DRV", "R130", "CE_DRV_J", "5", "R250", "N_CEIN"),
    ("ILIM_REL", "R131A", "ILIM_REL_A", "7", "R251", "N_RAIN"),
    ("ILIM_REL", "R131B", "ILIM_REL_B", "8", "R266", "N_RBIN"),
    ("RFC_OFF", "R132", "RFC_OFF_J", "10", "R253", "N_RFIN"),
]
EIB_PULLDOWN = {"N_CEIN": "R267", "N_RAIN": "R268", "N_RBIN": "R270", "N_RFIN": "R269"}


def check_chain():
    rows = []
    for drv, rcr, pad, jp, reib, gin in CHAIN:
        ok1 = CR.connects(rcr, drv, pad)
        ok2 = CR.pin[("J101", jp)] == pad and EIB.pin[("J201", jp)] == pad
        ok3 = EIB.connects(reib, pad, gin)
        ok4 = EIB.connects(EIB_PULLDOWN[gin], gin, "AGND")
        rows.append((drv, rcr, pad, jp, reib, gin, ok1 and ok2 and ok3 and ok4))
        assert ok1 and ok2 and ok3 and ok4, (drv, rcr, pad, jp, reib, gin)
    return rows


def _sections(nl):
    out = []
    for ref, c in sorted(nl.comps.items()):
        kind = GATE_KIND.get(c["value"])
        if kind is None:
            continue
        secs, vcc, gnd = _gate_sections(nl, ref)
        for ins, y in secs:
            out.append((ref, kind, ins, y))
    return out


CR_SECTIONS = _sections(CR)
EIB_SECTIONS = _sections(EIB)


def eval_cr(inp):
    """inp: dict over PRIMARY -> 0/1. Returns dict net -> 0/1 for every gate output net."""
    v = dict(inp)
    v["GND"] = 0
    v["3V3"] = 1
    for _ in range(10):
        changed = False
        for ref, kind, ins, y in CR_SECTIONS:
            if y is None:
                continue
            if any(i not in v for i in ins):
                continue
            a = [v[i] for i in ins]
            r = {"inv": lambda a: 1 - a[0], "or2": lambda a: a[0] | a[1], "and2": lambda a: a[0] & a[1],
                 "and3": lambda a: a[0] & a[1] & a[2]}[kind](a)
            if v.get(y) != r:
                v[y] = r
                changed = True
        if not changed:
            break
    return v


def eval_eib(cr):
    """EIB open-drain channels and the EVM end state, REGN present. Returns dict."""
    gin = {gi: cr[drv] for drv, _, _, _, _, gi in CHAIN}
    sink = {}
    for ref, kind, ins, y in EIB_SECTIONS:
        assert kind == "inv_od"
        sink[y] = gin[ins[0]] == 1          # output sinks when its input is HIGH
    nce = 0 if sink["nCE_DRV"] else 1         # R272/R272b pull /CE to REGN when not sunk
    q203_on = sink["Q203_G"]                   # P-FET gate pulled to its source (REGN) by R271 unless sunk
    q201_on = not sink["Q201_G"]               # N-FET gate pulled to REGN by R252 unless sunk
    q202_on = not sink["Q202_G"]               # N-FET gate pulled to REGN by R254 unless sunk
    if q201_on:
        ilim = "HELD"
    elif q203_on:
        ilim = "REL_FC" if q202_on else "REL_REGEN"
    else:
        ilim = "HELD_NOFEED"
    return dict(nCE=nce, Q201=int(q201_on), Q202=int(q202_on), Q203=int(q203_on), ILIM=ilim)


def intended(inp):
    """B.1 equations (design doc :1708-1720)."""
    P5, QUAL, H1, UVB, FCCN, FCC_ON = (inp[k] for k in PRIMARY)
    H1U = H1 & UVB
    FCCP = FCC_ON & (1 - FCCN)
    QF = QUAL & FCCN & (1 - P5)
    GATE = H1U | FCCP
    return dict(P5N=1 - P5, FCCNN=1 - FCCN, H1U=H1U, FCCP=FCCP, QF=QF, GATE=GATE, ILIM_REL=GATE | QF, CE_DRV=P5,
                RFC_OFF=FCCN | H1U)


def truth_table():
    rows = []
    for bits in itertools.product((0, 1), repeat=len(PRIMARY)):
        inp = dict(zip(PRIMARY, bits))
        v = eval_cr(inp)
        want = intended(inp)
        e = eval_eib(v)
        match = all(v[k] == want[k] for k in OUTPUTS)
        physical = not (inp["FCCN"] == 1 and inp["FCC_ON"] == 1)
        rows.append(dict(inp, **{k: v[k] for k in OUTPUTS}, **e, match_B1=int(match), physical=int(physical)))
    return rows


# T5 (FC_CHARGE EN) level classes -> (FCC_OFF = FCCN, FCC_ON), design doc B.1/B.2 and H.22(h)
T5 = {"LOW": (1, 0), "HIGH": (0, 1), "MID": (0, 0)}

# F.2 / B.7 mode rows that carry a GATE claim: (mode, P5, QUAL, T5 class, F.2 GATE claim, B.7 claim or '')
MODES = [
    ("Init (State 0)", 0, 0, "LOW", "0", ""),
    ("Idle (State 1)", 0, 0, "LOW", "0", ""),
    ("Run entry (qualification)", 0, 1, "LOW", "0 (ILIM released by QF)", ""),
    ("Run cruise, regen armed", 1, 0, "LOW", "H1U", ""),
    ("FC window", 1, 0, "HIGH", "FCCP = 1", ""),
    ("Finish (State 3)", 0, 0, "LOW", "0", ""),
    ("State 99", 0, 0, "LOW", "0", ""),
    ("Charger trip in FC window (T10)", 0, 0, "LOW", "0", ""),
    ("Teensy reset (pins high-Z)", 0, 0, "LOW", "0", "H1U only (FCC = 0, so FCCP = 0)"),
    ("EN net intermediate (INPUT_PULLUP)", 1, 0, "MID", "-", "FCCP = 0 and QF = 0, GATE = H1U only"),
]


def mode_table():
    rows = []
    for mode, p5, q, t5, f2, b7 in MODES:
        fccn, fccon = T5[t5]
        for h1, uvb in ((0, 1), (1, 1), (1, 0)):
            inp = dict(CHG_ARM=p5, QUAL=q, H1=h1, UVB=uvb, FCCN=fccn, FCC_ON=fccon)
            v = eval_cr(inp)
            e = eval_eib(v)
            f2_num = {"0": 0, "0 (ILIM released by QF)": 0, "FCCP = 1": 1}.get(f2)
            if f2 == "H1U":
                f2_num = h1 & uvb
            agree = "" if f2_num is None else ("yes" if f2_num == v["GATE"] else "NO")
            rows.append(dict(mode=mode, P5=p5, QUAL=q, T5=t5, H1=h1, UVB=uvb, GATE=v["GATE"], ILIM_REL=v["ILIM_REL"],
                             CE_DRV=v["CE_DRV"], RFC_OFF=v["RFC_OFF"], nCE=e["nCE"], ILIM=e["ILIM"],
                             F2_GATE_claim=f2, F2_agrees=agree, B7_claim=b7))
    return rows


if __name__ == "__main__":
    print(check_chain())
    tt = truth_table()
    print("rows", len(tt), "mismatches", sum(1 - r["match_B1"] for r in tt))
    for r in mode_table():
        print(r)
