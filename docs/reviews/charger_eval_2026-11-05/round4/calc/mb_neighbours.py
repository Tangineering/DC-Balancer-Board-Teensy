#!/usr/bin/env python3
"""Round 4 (r7): motherboard geometry around the CHG (Ag105) footprint, from the Eagle .brd (stdlib only).

Prints, in Eagle board coordinates (top view, origin = MB origin, +x right, +y UP, mm):
  1. the board outline (Dimension layer 20) and every plain hole (mounting holes);
  2. every element whose pad or graphic extent lies within MARGIN mm of the CHG pad envelope, with its side
     (top/bottom), package, value, extent and the gap to the CHG pad envelope in x and y;
  3. (--copper) top-layer and bottom-layer copper wires/polygons inside a query rectangle.
Heights are NOT in the .brd; heights quoted in the design come from datasheets or are TODO(measure).
Usage: python -I mb_neighbours.py [--brd PATH] [--margin MM] [--json OUT] [--copper x0,y0,x1,y1]
"""
import argparse
import json
import math
import os
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
DEF_BRD = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "references",
                                        "Scale Car Board PCB 20260625.brd"))


def rot_of(s):
    s = s or "R0"
    mir = "M" in s
    ang = float(s.replace("M", "").replace("S", "").replace("R", "") or 0)
    return mir, ang


def xf(px, py, ex, ey, rot):
    mir, ang = rot_of(rot)
    if mir:
        px = -px
    a = math.radians(ang)
    return ex + px * math.cos(a) - py * math.sin(a), ey + px * math.sin(a) + py * math.cos(a)


def bbox(pts):
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def element_records(board):
    pkgs = {}
    for lib in board.find("libraries"):
        pk_root = lib.find("packages")
        if pk_root is None:
            continue
        for pk in pk_root:
            pkgs[(lib.get("name"), pk.get("name"))] = pk
    els = []
    for e in board.find("elements"):
        ex, ey = float(e.get("x")), float(e.get("y"))
        rot = e.get("rot", "R0")
        pk = pkgs.get((e.get("library"), e.get("package")))
        pads, graph = [], []
        if pk is not None:
            for g in pk:
                if g.tag == "pad":
                    px, py = float(g.get("x")), float(g.get("y"))
                    dr = float(g.get("drill"))
                    dia = float(g.get("diameter") or 0) or (dr + 0.8)
                    cx, cy = xf(px, py, ex, ey, rot)
                    pads.append(dict(name=g.get("name"), x=cx, y=cy, drill=dr,
                                     bb=[cx - dia / 2, cy - dia / 2, cx + dia / 2, cy + dia / 2]))
                elif g.tag == "smd":
                    px, py = float(g.get("x")), float(g.get("y"))
                    dx, dy = float(g.get("dx")), float(g.get("dy"))
                    _, la = rot_of(g.get("rot", "R0"))
                    r = math.radians(la)
                    corners = []
                    for sx in (-0.5, 0.5):
                        for sy in (-0.5, 0.5):
                            qx, qy = sx * dx, sy * dy
                            qx, qy = qx * math.cos(r) - qy * math.sin(r), qx * math.sin(r) + qy * math.cos(r)
                            corners.append(xf(px + qx, py + qy, ex, ey, rot))
                    b = bbox(corners)
                    pads.append(dict(name=g.get("name"), x=(b[0] + b[2]) / 2, y=(b[1] + b[3]) / 2, drill=0.0, bb=b))
                elif g.tag in ("wire", "rectangle") and g.get("layer") in ("21", "22", "51", "52", "39", "40"):
                    graph += [xf(float(g.get("x1")), float(g.get("y1")), ex, ey, rot),
                              xf(float(g.get("x2")), float(g.get("y2")), ex, ey, rot)]
                elif g.tag == "circle" and g.get("layer") in ("21", "22", "51", "52"):
                    cx, cy = xf(float(g.get("x")), float(g.get("y")), ex, ey, rot)
                    rr = float(g.get("radius"))
                    graph += [(cx - rr, cy - rr), (cx + rr, cy + rr)]
        padpts = []
        for p in pads:
            padpts += [(p["bb"][0], p["bb"][1]), (p["bb"][2], p["bb"][3])]
        allb = bbox(padpts + graph) or [ex, ey, ex, ey]
        els.append(dict(name=e.get("name"), value=e.get("value"), package=e.get("package"), x=ex, y=ey, rot=rot,
                        side="bottom" if rot_of(rot)[0] else "top", pad_bbox=bbox(padpts), graph_bbox=bbox(graph),
                        tht=any(p["drill"] > 0 for p in pads), bbox=allb,
                        pads=[(p["name"], round(p["x"], 3), round(p["y"], 3), p["drill"]) for p in pads]))
    return els


def copper_in(board, rect):
    x0, y0, x1, y1 = rect
    out = []
    for sig in board.find("signals"):
        for g in sig:
            if g.tag == "wire" and g.get("layer") in ("1", "16"):
                ax, ay, bx, by = (float(g.get(k)) for k in ("x1", "y1", "x2", "y2"))
                if max(ax, bx) >= x0 and min(ax, bx) <= x1 and max(ay, by) >= y0 and min(ay, by) <= y1:
                    out.append(("wire", sig.get("name"), g.get("layer"), round(ax, 2), round(ay, 2), round(bx, 2),
                                round(by, 2), float(g.get("width"))))
            elif g.tag == "polygon" and g.get("layer") in ("1", "16"):
                pts = [(float(v.get("x")), float(v.get("y"))) for v in g.findall("vertex")]
                b = bbox(pts)
                if b[2] >= x0 and b[0] <= x1 and b[3] >= y0 and b[1] <= y1:
                    out.append(("poly", sig.get("name"), g.get("layer"), *[round(v, 2) for v in b], g.get("rank")))
            elif g.tag == "via":
                x, y = float(g.get("x")), float(g.get("y"))
                if x0 <= x <= x1 and y0 <= y <= y1:
                    out.append(("via", sig.get("name"), "-", round(x, 2), round(y, 2), float(g.get("drill"))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brd", default=DEF_BRD)
    ap.add_argument("--margin", type=float, default=40.0)
    ap.add_argument("--json")
    ap.add_argument("--copper")
    a = ap.parse_args()
    board = ET.parse(a.brd).getroot().find("drawing/board")
    outline = []
    for w in board.find("plain"):
        if w.tag == "wire" and w.get("layer") == "20":
            outline += [(float(w.get("x1")), float(w.get("y1"))), (float(w.get("x2")), float(w.get("y2")))]
    holes = [(float(h.get("x")), float(h.get("y")), float(h.get("drill"))) for h in board.find("plain")
             if h.tag == "hole"]
    print("BOARD OUTLINE bbox (layer 20):", [round(v, 3) for v in bbox(outline)])
    print("PLAIN HOLES (x, y, drill):", [(round(x, 2), round(y, 2), d) for x, y, d in holes])
    els = element_records(board)
    chg = [r for r in els if r["name"] == "CHG"][0]
    cb = chg["pad_bbox"]
    print("CHG pad envelope:", [round(v, 3) for v in cb], " graphics:",
          [round(v, 3) for v in chg["graph_bbox"]] if chg["graph_bbox"] else None)
    near = []
    for r in els:
        if r["name"] == "CHG":
            continue
        b = r["bbox"]
        gx = max(cb[0] - b[2], b[0] - cb[2], 0.0)
        gy = max(cb[1] - b[3], b[1] - cb[3], 0.0)
        if gx <= a.margin and gy <= a.margin:
            r["gap_x"], r["gap_y"] = gx, gy
            r["dir"] = (("-x" if b[2] <= cb[0] else "+x" if b[0] >= cb[2] else "")
                        + ("-y" if b[3] <= cb[1] else "+y" if b[1] >= cb[3] else "")) or "inside"
            near.append(r)
    near.sort(key=lambda r: (r["dir"], math.hypot(r["gap_x"], r["gap_y"])))
    print("\n%-11s %-6s %-22s %-16s %-3s %-30s %-6s %-6s %s" % ("name", "side", "package", "value", "TH",
                                                                "bbox x0,y0,x1,y1", "gapx", "gapy", "dir"))
    for r in near:
        print("%-11s %-6s %-22s %-16s %-3s %-30s %-6.2f %-6.2f %s" % (
            r["name"], r["side"], (r["package"] or "")[:22], (r["value"] or "")[:16], "y" if r["tht"] else "",
            ",".join("%.2f" % v for v in r["bbox"]), r["gap_x"], r["gap_y"], r["dir"]))
    if a.copper:
        rect = [float(v) for v in a.copper.split(",")]
        print("\nCOPPER in", rect)
        for c in copper_in(board, rect):
            print(c)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(dict(outline=bbox(outline), holes=holes, chg=chg, near=near), f, indent=1, default=str)


if __name__ == "__main__":
    main()
