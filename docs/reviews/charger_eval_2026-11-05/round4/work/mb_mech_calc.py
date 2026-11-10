#!/usr/bin/env python3
"""Round 4 work: mechanical / copper / thermal map for a CHG carrier (CR) that extends past the 31 x 33 mm footprint.

Coordinates: Eagle .brd board coordinates, top view, origin = MB origin, +x right, +y UP, mm.
Inputs : references/Scale Car Board PCB 20260625.brd (via ../calc/mb_neighbours.py), the height table below (each row
         carries its source), the zone rectangles below.
Outputs: mb_mech_calc_out.txt (stdout), mb_mech_map.png (plan view), mb_mech_calc_out.json.
Run    : /c/Users/ricky/miniforge3/python.exe -I mb_mech_calc.py   (from this folder; needs numpy, scipy, matplotlib)

Every height is either sourced (IPC-7351 package name, local datasheet, manufacturer page) or TODO(measure).
The thermal and pin-load sections are labelled estimates; the inputs are printed with them.
"""
import json
import math
import os
import sys
import xml.etree.ElementTree as ET

import numpy as np
from scipy import special

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "calc")))
sys.path.insert(0, HERE)
import mb_neighbours as mbn  # noqa: E402

# ----------------------------------------------------------------------------------------------------------------------
# 1. Heights. (h_mm or None, source). IPC-7351 names carry the maximum body height in hundredths of a mm (X135 = 1.35).
# ----------------------------------------------------------------------------------------------------------------------
IPC = "IPC-7351 package name"
PKG_H = {
    "CAPC1005X60": (0.60, IPC), "CAPC1608X85": (0.85, IPC), "CAPC2012X110": (1.10, IPC),
    "CAPC3216X135": (1.35, IPC), "CAPC3225X135": (1.35, IPC), "CAPM3528X210": (2.10, IPC),
    "RESC1005X40": (0.40, IPC), "RESC1608X60": (0.60, IPC), "SOP65P640X120-20N": (1.20, IPC + "; INA253 DS 'TSSOP - 1.2 mm max height'"),
    "TO254P1524X483-4N": (4.83, IPC + " (LM1084 KTT TO-263)"), "SOT230P700X170-4N": (1.70, IPC),
    "SOD3716X145N": (1.45, IPC),
    "D0008A-IPC_A": (1.75, "OPA197IDR.pdf, D0008A 'SOIC - 1.75 mm max height'"),
    "RM_10_ADI": (1.10, "ad5426_5432_5443.pdf, RM-10 MSOP outline '1.10 MAX'"),
    "IC_RT1987N-A": (1.00, "RT1987_DS-00.pdf section 19, dimension A 0.800-1.000"),
    "CONV_TPS61288LRQQR": (1.00, "TPS61288LRQQR.pdf, 'VQFN-HR - 1 mm max height'"),
    "DRB8_1P6X2P4": (1.00, "BQ29200_TI.pdf, 'VSON - 1 mm max height'"),
    "DBZ0003A_N": (None, "TODO(verify: TL431 DBZ outline); 66 mm away, not used"),
    "HCM1A1305V3-2R2-R": (5.00, "Eaton catalogue listing 13.8 x 12.9 x 5.0 mm (web); TODO(verify: Eaton ELX1488 datasheet, fetch failed)"),
    "CUI_TB005_-762-03BE": (21.70, "TB005-762_CUI.pdf p.2, body height 21.70"),
    "CUI_TB005-762-02BE": (21.70, "TB005-762_CUI.pdf p.2, body height 21.70"),
    "691411410002": (13.90, "Wurth 691411410002 DS rev 001.004 p.1: 13.9 +-0.1 to the push-button top, body 9.2 +-0.1"),
    "AMPHENOL_87606-324LF": (None, "TODO(measure): Amphenol 87606-324LF body height (vendor drawing not retrievable, 403)"),
    "TEENSY41": (None, "TODO(measure): Teensy 4.1 on PREC024SAAN-RC headers, seated top height"),
    "2X10": (None, "TODO(verify: Wurth 61302021821 drawing) receptacle height"),
    "CAP_FN_G_PAN": (None, "TODO(verify: Panasonic EEE-FN1V471UP, FN G case); 53 mm away"),
    "RES_SQP20A_YAG": (None, "TODO(verify: Yageo SQP20A drawing); 68 mm away"),
}


def height_of(el):
    return PKG_H.get(el["package"], (None, "TODO(measure): package %s not in table" % el["package"]))


# ----------------------------------------------------------------------------------------------------------------------
# 2. Board data
# ----------------------------------------------------------------------------------------------------------------------
board = ET.parse(mbn.DEF_BRD).getroot().find("drawing/board")
ELS = {e["name"]: e for e in mbn.element_records(board)}
OUTLINE = [0.0, 0.0, 131.064, 98.044]
HOLES = [(3.3, 3.3, 3.7973), (3.3, 94.74, 3.7973)]
CR = [17.70, 34.14, 48.70, 67.14]  # round-3 CR outline (A.7)

POLYS = []  # (net, layer, [(x, y)], width)
WIRES = []  # (net, layer, x1, y1, x2, y2, width)
VIAS = []  # (net, x, y, drill)
for sig in board.find("signals"):
    for g in sig:
        if g.tag == "polygon" and g.get("layer") in ("1", "16"):
            POLYS.append((sig.get("name"), g.get("layer"),
                          [(float(v.get("x")), float(v.get("y"))) for v in g.findall("vertex")], float(g.get("width"))))
        elif g.tag == "wire" and g.get("layer") in ("1", "16"):
            WIRES.append((sig.get("name"), g.get("layer"), *(float(g.get(k)) for k in ("x1", "y1", "x2", "y2")),
                          float(g.get("width"))))
        elif g.tag == "via":
            VIAS.append((sig.get("name"), float(g.get("x")), float(g.get("y")), float(g.get("drill"))))

# Unconnected through-hole pads (candidate extra anchor holes): THT pads whose element pad has no contactref.
CONNECTED = set()
for sig in board.find("signals"):
    for c in sig.findall("contactref"):
        CONNECTED.add((c.get("element"), c.get("pad")))
FREE_TH = []
for e in ELS.values():
    for (pn, px, py, dr) in e["pads"]:
        if dr > 0 and (e["name"], pn) not in CONNECTED:
            FREE_TH.append((e["name"], pn, px, py, dr))

# Design rule: vias with drill <= mlViaStopLimit get no stop-mask opening (tented).
VIA_STOP_LIMIT = None
for p in board.find("designrules").findall("param"):
    if p.get("name") == "mlViaStopLimit":
        VIA_STOP_LIMIT = p.get("value")

POWER_NETS = {"VBUS", "V-MOT", "VCHG-IN", "VCHG", "VBT", "5V", "VFC", "VSW-FC", "VSW-BT", "VOUT-FC", "VOUT-BT",
              "VBUS-FC", "VBUS-BT", "VBAL+", "N$39"}
SWITCH_NETS = {"VSW-FC", "VSW-BT"}
SWITCH_PARTS = ["L-FC", "L-BT", "REG-FC", "REG-BT"]


def rect_dist(a, b):
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


# Raster helpers (0.1 mm) for polygon-in-zone areas.
RES = 0.1


def poly_mask(pts, rect, grow=0.0):
    from matplotlib.path import Path
    x0, y0, x1, y1 = rect
    xs = np.arange(x0 + RES / 2, x1, RES)
    ys = np.arange(y0 + RES / 2, y1, RES)
    X, Y = np.meshgrid(xs, ys)
    pth = Path(pts)
    return pth.contains_points(np.c_[X.ravel(), Y.ravel()], radius=2 * grow).reshape(X.shape)


def rect_mask(r, rect):
    x0, y0, x1, y1 = rect
    xs = np.arange(x0 + RES / 2, x1, RES)
    ys = np.arange(y0 + RES / 2, y1, RES)
    X, Y = np.meshgrid(xs, ys)
    return (X >= r[0]) & (X <= r[2]) & (Y >= r[1]) & (Y <= r[3])


# ----------------------------------------------------------------------------------------------------------------------
# 3. Candidate zones (board mm). Each is the largest rectangle the zone could add on that side; the analysis reports
#    what lies under it. A zone is an extension band adjacent to the CR outline unless stated.
# ----------------------------------------------------------------------------------------------------------------------
ZONES = {
    # raw zones named in the round-4 brief
    "+x raw (brief: x 48.7-82, y 55-69)": [48.70, 55.00, 82.00, 69.00],
    "+y raw (brief: x 17.7-40, y 67.6-77)": [17.70, 67.60, 40.00, 77.00],
    "-y raw (y 26-34.14)": [17.70, 26.00, 48.70, 34.14],
    "-x (over J-BL / J-NTC)": [3.28, 26.42, 17.70, 67.35],
    "off-board past x=0": [-20.0, 26.42, 0.0, 67.35],
    # usable rectangles after 0.5 mm plan clearance to every part the zone must not cover
    "+x usable": [48.70, 55.01, 80.23, 68.30],
    "+x core (no VBUS pour, x <= 65.0)": [48.70, 55.01, 65.00, 67.14],
    "+y usable (TSW 2.54 body)": [17.70, 67.14, 39.72, 76.51],
    "+y wide (over OP-FC, MDAC-FC)": [17.70, 67.14, 48.70, 76.51],
    "-y usable (to y 26.0)": [17.70, 26.00, 48.70, 34.14],
    # off-board via the long sides (over the boost inductors)
    "+y to MB edge (over L-FC)": [17.70, 67.14, 48.70, 98.04],
    "-y to MB edge (over L-BT)": [17.70, 0.00, 48.70, 34.14],
}

# Tap points (A.4) and the current tap-field centroid.
TAPS = {
    "T1 C-D6 pad1 (V-MOT)": (97.79, 19.80), "T2 C-D2 pad1 (VBUS)": (67.705, 69.85),
    "T3 J1.39": (87.122, 42.926), "T4 J1.43": (87.122, 37.846), "T5 J1.45": (87.122, 35.306),
    "T6 J1.29": (87.122, 55.626), "T22 BAL pad8": (25.86, 30.44), "T8 J2.31": (109.982, 53.086),
    "T9 SNS-BT GND/REF": (55.118, 23.622), "T10 J1.23": (87.122, 63.246), "T11 J2.19": (109.982, 68.326),
    "T12 J2.47": (109.982, 32.766), "T13 J2.45": (109.982, 35.306), "T14 J2.21": (109.982, 65.786),
    "T15 J2.07": (109.982, 83.566), "T16 J2.43": (109.982, 37.846), "T17 J2.09": (109.982, 81.026),
    "T17r J2.29": (109.982, 55.626), "T20 ROS pad2": (81.534, 69.797), "T21 J2.11": (109.982, 78.486),
}
TAPFIELD_R3 = (32.79, 38.34)  # centre of the r3 field x 23.15-42.43, y 35.05-41.63

# Tap-field position if the field moves onto each extension (centre of a 3 x 8 field, 20.3 x 6.6 mm, placed at the
# zone end nearest J1/J2; a judgement placement, stated in the report).
TAPFIELD_ALT = {
    "+x usable": (70.0, 62.0),
    "+x core (no VBUS pour, x <= 65.0)": (56.0, 61.0),
    "+y usable (TSW 2.54 body)": (28.0, 72.0),
    "-y usable (to y 26.0)": (33.0, 30.0),
}


def zone_report(name, z):
    out = {"zone": name, "rect": z}
    area = (z[2] - z[0]) * (z[3] - z[1])
    zc = [max(z[0], OUTLINE[0]), max(z[1], OUTLINE[1]), min(z[2], OUTLINE[2]), min(z[3], OUTLINE[3])]
    out["area_mm2"] = round(area, 1)
    out["on_board_area_mm2"] = round(max(0, zc[2] - zc[0]) * max(0, zc[3] - zc[1]), 1)
    parts = []
    occ = None
    if zc[2] > zc[0] and zc[3] > zc[1]:
        occ = np.zeros_like(rect_mask([0, 0, 0, 0], zc), dtype=bool)
    for e in ELS.values():
        if e["name"] == "CHG":
            continue
        if overlaps(e["bbox"], z):
            h, src = height_of(e)
            parts.append((e["name"], e["package"], h, src, [round(v, 2) for v in e["bbox"]]))
            if occ is not None:
                occ |= rect_mask(e["bbox"], zc)
    out["parts"] = sorted(parts, key=lambda p: -(p[2] if p[2] is not None else 99))
    out["part_free_area_mm2"] = round(float((~occ).sum()) * RES * RES, 1) if occ is not None else 0.0
    hs = [p[2] for p in parts if p[2] is not None]
    unknown = [p[0] for p in parts if p[2] is None]
    out["tallest_mm"] = max(hs) if hs else 0.0
    out["unknown_height_parts"] = unknown
    out["body_needed_mm"] = round(out["tallest_mm"] + 1.0, 2)
    # copper by net
    cu = {}
    if occ is not None:
        for (net, lay, pts, w) in POLYS:
            if net == "GND":
                continue
            msk = poly_mask(pts, zc, grow=w / 2)
            a = float(msk.sum()) * RES * RES
            if a > 0:
                cu.setdefault((net, "L" + lay, "pour"), 0.0)
                cu[(net, "L" + lay, "pour")] += a
        for (net, lay, x1, y1, x2, y2, w) in WIRES:
            # clip the segment length to the zone by sampling
            n = max(2, int(math.hypot(x2 - x1, y2 - y1) / 0.05))
            t = np.linspace(0, 1, n)
            xs, ys = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
            inside = (xs >= zc[0]) & (xs <= zc[2]) & (ys >= zc[1]) & (ys <= zc[3])
            L = float(inside.mean()) * math.hypot(x2 - x1, y2 - y1)
            if L > 0:
                key = (net, "L" + lay, "trace w%.3f" % w)
                cu[key] = cu.get(key, 0.0) + L
    out["copper"] = {"%s %s %s" % k: round(v, 1) for k, v in sorted(cu.items())}
    out["vias"] = [(n, round(x, 2), round(y, 2)) for (n, x, y, d) in VIAS
                   if zc[0] <= x <= zc[2] and zc[1] <= y <= zc[3]] if occ is not None else []
    out["free_th_holes"] = [f for f in FREE_TH if z[0] <= f[2] <= z[2] and z[1] <= f[3] <= z[3]]
    # switching nodes
    sw = {}
    for p in SWITCH_PARTS:
        sw[p] = round(rect_dist(ELS[p]["bbox"], z), 2)
    for (net, lay, pts, w) in POLYS:
        if net in SWITCH_NETS:
            xs = [q[0] for q in pts]
            ys = [q[1] for q in pts]
            sw[net + " pour L" + lay] = round(rect_dist([min(xs), min(ys), max(xs), max(ys)], z), 2)
    out["switch_dist_mm"] = sw
    # LM1084 tab / 5V pour distance
    p5 = [p for p in POLYS if p[0] == "5V"][0]
    xs = [q[0] for q in p5[2]]
    ys = [q[1] for q in p5[2]]
    pour = [min(xs) - p5[3] / 2, min(ys) - p5[3] / 2, max(xs) + p5[3] / 2, max(ys) + p5[3] / 2]
    out["dist_5V_pour_mm"] = round(rect_dist(pour, z), 2)
    out["dist_REG5V_mm"] = round(rect_dist(ELS["REG-5V"]["bbox"], z), 2)
    # nearest MB edge (from the zone's outer extent; negative = past the edge)
    out["edge_margin_mm"] = round(min(z[0] - OUTLINE[0], z[1] - OUTLINE[1], OUTLINE[2] - z[2], OUTLINE[3] - z[3]), 2)
    out["dist_mount_holes_mm"] = [round(math.hypot(max(z[0] - hx, hx - z[2], 0), max(z[1] - hy, hy - z[3], 0)), 1)
                                  for (hx, hy, d) in HOLES]
    return out


def tap_lengths(field):
    return {k: round(math.hypot(field[0] - v[0], field[1] - v[1]), 1) for k, v in TAPS.items()}


# ----------------------------------------------------------------------------------------------------------------------
# 4. LM1084 dissipation and board-temperature estimate (ESTIMATE; labelled).
# ----------------------------------------------------------------------------------------------------------------------
def lm1084():
    res = {}
    # Loads on the 5V net (.sch): U$1 VIN (Teensy 4.1 + its 3V3 loads), OP-FC/OP-BT V+, J2.01/02 (= Teensy VIN breakout).
    # Repo figure: "Teensy + Ethernet PHY ~150-250 mA" (AGENTS.md; docs/modeling/bond-graph.md; bench manual ~0.25 A).
    i_logic = (0.150, 0.250)
    i_opa = 2 * 1.3e-3  # OPA197 IQ max 1.3 mA per channel (OPA197IDR.pdf EC), x2
    i_enc = (0.0, 0.040)  # OPB829DZ emitters after the 2026-08-16 bodge: rail and resistor unrecorded -> TODO(measure)
    iq = (0.005, 0.010)  # LM1084 quiescent 5 mA typ (SNVS037H 7.x text), 10 mA max (EC table, 5.0 V version)
    vin = (7.4, 8.4)  # pack operating band (CLAUDE.md fw v30 LIMIT_V_BATT_MIN 7.4 V; 8.4 V CV)
    lo = (vin[0] - 5.0) * (i_logic[0] + i_opa + i_enc[0]) + vin[0] * iq[0]
    hi = (vin[1] - 5.0) * (i_logic[1] + i_opa + i_enc[1]) + vin[1] * iq[1]
    nom = (7.9 - 5.0) * (0.200 + i_opa + 0.0) + 7.9 * 0.005
    res["P_W"] = (round(lo, 3), round(nom, 3), round(hi, 3))
    # Thermal resistances (SNVS037H 5.4, KTT): RthJA 40.4 (JEDEC 2s2p high-K), PsiJB 22.0, RthJC(bot) 0.65/2.7 C/W.
    # Figure 7-14 (PCB heat-sink copper vs area): ~70 C/W at ~400 mm^2 (read from the plot), steeper below.
    # Board model: radial fin, two 1 oz layers (35 um, k 385) with fill fraction f, FR4 negligible, h both sides.
    kt_cu = 0.035e-3 * 385.0  # W/K per layer
    # (layers-equivalent of continuous 1 oz copper, h_total both faces W/m2K, lateral-gap conductance share)
    # R_couple = vertical FR4 path under the island (27 K/W) in parallel with the lateral path across the L1 isolation
    # gap (~20-55 K/W, order k_FR4 x perimeter); best 12, nom 18, worst 27 (vertical only).
    cases = {"best": (1.5, 28.0, 12.0), "nom": (1.2, 24.0, 18.0), "worst": (0.7, 18.0, None)}
    a = math.sqrt((153.1 + 2 * 0.254 * 60) / math.pi) * 1e-3  # 5V pour outline 153.1 mm^2 + w/2 rim (~60 mm perimeter)
    res["pour_equiv_radius_mm"] = round(a * 1e3, 2)
    prof = {}
    for k, (nl, h, rc_override) in cases.items():
        kt = kt_cu * nl
        lc = math.sqrt(kt / h)
        rs = special.k0(a / lc) / (2 * math.pi * kt * (a / lc) * special.k1(a / lc))  # plane rise at r=a per watt
        # coupling pour -> GND copper: vertical through 1.5 mm FR4 (k 0.3) under the pour, parallel with the lateral gap
        g_v = 0.3 / 1.5e-3 * math.pi * a * a
        r_c = rc_override if rc_override is not None else 1.0 / g_v
        dist = [0, 1, 5, 10, 20]
        ratio = [float(special.k0((a + d * 1e-3) / lc) / special.k0(a / lc)) for d in dist]
        prof[k] = {"Lc_mm": round(lc * 1e3, 1), "R_spread_CperW": round(rs, 1), "R_couple_CperW": round(r_c, 1),
                   "decay_ratio_at_d": dict(zip(dist, [round(r, 3) for r in ratio]))}
    res["fin"] = prof
    # Temperature rise table: pour rise = P (R_couple + R_spread); plane rise at distance d = P R_spread ratio(d).
    tab = {}
    for (pk, P) in (("P_lo", lo), ("P_nom", nom), ("P_hi", hi)):
        row = {}
        for k in cases:
            f = prof[k]
            pour_rise = P * (f["R_couple_CperW"] + f["R_spread_CperW"])
            row[k] = {"pour": round(pour_rise, 1),
                      **{"d%dmm" % d: round(P * f["R_spread_CperW"] * f["decay_ratio_at_d"][d], 1) for d in (1, 5, 10, 20)}}
        tab[pk] = row
    res["rise_table_C"] = tab
    # Datasheet bounds for the junction and the board next to the package
    res["datasheet_bounds"] = {
        "TJ_rise_lo_highK": round(lo * 40.4, 1), "TJ_rise_hi_highK": round(hi * 40.4, 1),
        "board_rise_1mm_from_pkg_highK_lo": round(lo * (40.4 - 22.0), 1),
        "board_rise_1mm_from_pkg_highK_hi": round(hi * (40.4 - 22.0), 1),
        "pour_rise_fig714_70CperW_lo": round(lo * 70, 1), "pour_rise_fig714_70CperW_hi": round(hi * 70, 1),
    }
    return res


# 5. Pin-field load and extension resonance: see mb_pinload.py (ORDER OF MAGNITUDE).


def main():
    print("Board outline", OUTLINE, "plain holes", HOLES, "via stop limit", VIA_STOP_LIMIT,
          "(vias with drill <= limit are tented)")
    print("Free (unconnected) through-hole pads on the whole MB:")
    for f in sorted(FREE_TH):
        print("   ", f)
    allrep = {}
    for name, z in ZONES.items():
        r = zone_report(name, z)
        allrep[name] = r
        print("\n=== ZONE", name, z)
        for k in ("area_mm2", "on_board_area_mm2", "part_free_area_mm2", "tallest_mm", "unknown_height_parts",
                  "body_needed_mm", "dist_5V_pour_mm", "dist_REG5V_mm", "edge_margin_mm", "dist_mount_holes_mm"):
            print("  %-22s %s" % (k, r[k]))
        print("  parts:")
        for p in r["parts"]:
            print("     %-10s %-22s h=%-5s %s  [%s]" % (p[0], p[1], p[2], p[4], p[3]))
        print("  copper (pour mm2 / trace mm):")
        for k, v in r["copper"].items():
            tag = " POWER" if k.split()[0] in POWER_NETS else ""
            print("     %-40s %8.1f%s" % (k, v, tag))
        print("  vias (all tented):", len(r["vias"]), sorted(set(v[0] for v in r["vias"])))
        print("  free TH holes inside:", r["free_th_holes"])
        print("  switching-node distances:", r["switch_dist_mm"])
        if name in TAPFIELD_ALT:
            alt = tap_lengths(TAPFIELD_ALT[name])
            r["tap_alt"] = alt
    base = tap_lengths(TAPFIELD_R3)
    print("\n=== TAP straight lengths (mm) from the r3 field", TAPFIELD_R3, "and from a field moved onto each zone")
    hdr = ["tap", "r3"] + list(TAPFIELD_ALT)
    print("  " + " | ".join(hdr))
    sums = {k: 0.0 for k in ["r3"] + list(TAPFIELD_ALT)}
    for t in TAPS:
        row = [t, base[t]] + [allrep[z]["tap_alt"][t] for z in TAPFIELD_ALT]
        sums["r3"] += base[t]
        for z in TAPFIELD_ALT:
            sums[z] += allrep[z]["tap_alt"][t]
        print("  " + " | ".join(str(v) for v in row))
    print("  SUM", {k: round(v, 1) for k, v in sums.items()})
    for z in TAPFIELD_ALT:
        moved = [t for t in TAPS if allrep[z]["tap_alt"][t] < base[t]]
        tot = sum(min(base[t], allrep[z]["tap_alt"][t]) for t in TAPS)
        allrep[z]["tap_split_sum"] = round(tot, 1)
        print("  split field for %s (each tap to the nearer field): SUM %.1f mm, %d taps moved: %s"
              % (z, tot, len(moved), ", ".join(m.split()[0] for m in moved)))
    th = lm1084()
    print("\n=== LM1084 (ESTIMATE)")
    print(json.dumps(th, indent=1))
    import mb_pinload
    pl = mb_pinload.pin_load()
    print("\n=== PIN LOAD (ORDER OF MAGNITUDE)")
    for k, v in pl["assumptions"].items():
        print("   assumption", k, ":", v)
    for c in pl["rows"]:
        print("  ", c)
    for c in pl["inplane"]:
        print("   inplane", c)
    for c in pl["freq"]:
        print("   freq", c)
    for c in pl["strip_stress"]:
        print("   strip", c)
    with open(os.path.join(HERE, "mb_mech_calc_out.json"), "w") as f:
        json.dump({"zones": allrep, "taps_r3": base, "lm1084": th, "pin": pl}, f, indent=1, default=str)
    plot()


def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, Polygon, Circle
    fig, ax = plt.subplots(figsize=(14, 10.5), dpi=110)
    ax.add_patch(Rectangle((0, 0), OUTLINE[2], OUTLINE[3], fill=False, lw=1.5, ec="k"))
    col = {"VBUS": "#d62728", "V-MOT": "#9467bd", "VCHG-IN": "#ff7f0e", "VCHG": "#e377c2", "VBT": "#8c564b",
           "5V": "#bcbd22", "VSW-FC": "#17becf", "VSW-BT": "#17becf", "VOUT-FC": "#1f77b4", "VOUT-BT": "#1f77b4",
           "VFC": "#2ca02c", "VBUS-FC": "#d62728", "VBUS-BT": "#d62728"}
    for (net, lay, pts, w) in POLYS:
        if net == "GND":
            continue
        ax.add_patch(Polygon(pts, closed=True, alpha=0.35 if lay == "1" else 0.15, fc=col.get(net, "#7f7f7f"),
                             ec=col.get(net, "#7f7f7f"), lw=0.5))
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        ax.text(sum(xs) / len(xs), sum(ys) / len(ys), net, fontsize=6, color=col.get(net, "k"))
    for (net, lay, x1, y1, x2, y2, w) in WIRES:
        if net in POWER_NETS and w >= 0.5:
            ax.plot([x1, x2], [y1, y2], color=col.get(net, "#7f7f7f"), lw=max(0.5, w * 2),
                    alpha=0.7 if lay == "1" else 0.35, ls="-" if lay == "1" else "--")
    for e in ELS.values():
        b = e["bbox"]
        if b[0] > 92 or e["name"] == "CHG":
            continue
        h = height_of(e)[0]
        fc = "none" if h is None or h < 1.5 else ("#ffcc99" if h < 3 else "#ff9999")
        ax.add_patch(Rectangle((b[0], b[1]), b[2] - b[0], b[3] - b[1], fill=fc != "none", fc=fc, ec="#444", lw=0.5,
                               alpha=0.8))
        ax.text(b[0], b[3] + 0.2, "%s %s" % (e["name"], "" if h is None else "%.2g" % h), fontsize=5)
    chg = ELS["CHG"]
    for (pn, px, py, dr) in chg["pads"]:
        ax.add_patch(Circle((px, py), 0.55, fc="k"))
    ax.add_patch(Rectangle((CR[0], CR[1]), CR[2] - CR[0], CR[3] - CR[1], fill=False, ec="b", lw=1.5))
    ax.text(CR[0] + 0.5, CR[1] + 0.5, "CR r3", color="b", fontsize=8)
    zc = ["#1f77b4", "#2ca02c", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#17becf"]
    for i, (n, z) in enumerate(ZONES.items()):
        ax.add_patch(Rectangle((z[0], z[1]), z[2] - z[0], z[3] - z[1], fill=False, ec=zc[i % len(zc)], lw=1.2, ls=":"))
        ax.text(z[0] + 0.3, z[3] - 1.2, n.split(" (")[0], color=zc[i % len(zc)], fontsize=7)
    for (hx, hy, d) in HOLES:
        ax.add_patch(Circle((hx, hy), d / 2, fill=False, ec="k"))
    ax.set_xlim(-22, 92)
    ax.set_ylim(-2, 100)
    ax.set_aspect("equal")
    ax.set_title("MB plan view (Eagle board coords, top view, +y up). Fill: red >= 3 mm tall, orange 1.5-3 mm; "
                 "label = name height_mm")
    ax.grid(True, lw=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "mb_mech_map.png"))


if __name__ == "__main__":
    main()
