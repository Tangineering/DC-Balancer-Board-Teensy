"""Parallel-copper metric for a soft keep-away rule: how much logic track runs beside analog track inside a zone.

Usage (pcbnew venv: shapely is there, not in miniforge):
  python parallel_metric.py <model.json> <routes.json> --zone-parts R102,R109 --analog-nets /A,/B
         [--ignore-nets /GND,/3V3] [--zone-margin 2.0] [--exempt-pins J1.7,U102.1] [--gap 0.5] [--ang 20]
         [--broadside In2.Cu:B.Cu] [--y-flip-offset Y0] [--check-pad REF.PAD] [--json out.json]
  A net list may be given as @file (one net per line).

Zone: the convex hulls of the pads of each --zone-parts part, joined, grown by --zone-margin mm, on all layers.
Classes: analog = --analog-nets; ignored = --ignore-nets (plane and supply nets, neither class); logic = every
other net in <routes.json>.
Metric: the length (mm) of logic track centreline inside the zone that runs parallel to analog track copper. A
piece of logic centreline counts when it lies within --gap mm (edge to edge) of an analog segment whose direction
is within --ang degrees of its own. Each mm of logic centreline counts once, however many analog segments run
beside it.
  same layer : the analog segment is on the same copper layer;
  broadside  : the two layers form a --broadside pair (no plane between them; default In2.Cu:B.Cu, the layers of
               the test board that face each other without the L2 plane between).
Also reported: all logic length in the zone, logic vias in the zone, and the part of the same-layer figure that
belongs to the escapes of --exempt-pins (the in-zone F.Cu piece of an exempt pin's net that touches that pad).

Frames: model.json and routes.json are in the KiCad frame (y down). A constraint written in the design frame
(y up, y = Y0 - y) gives wrong counts if it is applied to these numbers unconverted. Before the numbers are used,
run once with --check-pad on a pad whose position is known in both frames, and compare.
Verified 2026-11-12 against the scratch metric of the CR round-3 study (identical figures on the same inputs)."""
import argparse
import json
import math

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union


def netlist(s):
    if not s:
        return set()
    if s.startswith("@"):
        return {ln.strip() for ln in open(s[1:], encoding="utf-8") if ln.strip()}
    return {n for n in s.split(",") if n}


ap = argparse.ArgumentParser()
ap.add_argument("model")
ap.add_argument("routes")
ap.add_argument("--zone-parts", required=True)
ap.add_argument("--analog-nets", required=True)
ap.add_argument("--ignore-nets", default="")
ap.add_argument("--zone-margin", type=float, default=2.0)
ap.add_argument("--exempt-pins", default="")
ap.add_argument("--gap", type=float, default=0.5)
ap.add_argument("--ang", type=float, default=20.0)
ap.add_argument("--broadside", default="In2.Cu:B.Cu")
ap.add_argument("--y-flip-offset", type=float, default=None)
ap.add_argument("--check-pad", default=None)
ap.add_argument("--json", default=None)
A = ap.parse_args()
M = json.load(open(A.model))
R = json.load(open(A.routes))["results"]
ANALOG, IGNORE = netlist(A.analog_nets), netlist(A.ignore_nets)
ZPARTS = set(netlist(A.zone_parts))
EXEMPT = {tuple(p.rsplit(".", 1)) for p in netlist(A.exempt_pins)}
BROAD = set()
for pair in A.broadside.split(","):
    if pair:
        a, b = pair.split(":")
        BROAD |= {(a, b), (b, a)}
yoff = A.y_flip_offset if A.y_flip_offset is not None else M.get("y_flip_offset")


def design(x, y):
    return (x, yoff - y) if yoff is not None else (x, y)


def poly(P):
    return Polygon(P[0] if isinstance(P[0][0], list) else P)


hull, xpads = {}, {}
for it in M["items"]:
    if it["kind"] != "pad":
        continue
    key = (it.get("ref"), str(it.get("num")))
    if A.check_pad and "%s.%s" % key == A.check_pad:
        c = poly(it["poly"]).centroid
        print("check pad %s (%s): KiCad frame (%.3f, %.3f); design frame (%.3f, %.3f)%s" % (
            A.check_pad, it["net"], c.x, c.y, *design(c.x, c.y),
            "" if yoff is not None else " - no y_flip_offset given, the two frames are the same here"))
    if it.get("ref") in ZPARTS:
        hull.setdefault(it["ref"], []).append(poly(it["poly"]))
    if key in EXEMPT:
        xpads.setdefault(it["net"], []).append(poly(it["poly"]))
missing = ZPARTS - set(hull)
if missing:
    raise SystemExit("zone parts without pads in the model: %s" % ", ".join(sorted(missing)))
zone = unary_union([unary_union(v).convex_hull for v in hull.values()]).buffer(A.zone_margin)


def direction(x1, y1, x2, y2):
    return math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0


def angdiff(a, b):
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


analog, logic, vias_in = [], [], []
for r in R:
    n = r["net"]
    if n in IGNORE:
        continue
    for (L, x1, y1, x2, y2), w in zip(r["tracks"], r["widths"]):
        if (x1, y1) == (x2, y2):
            continue
        ls = LineString([(x1, y1), (x2, y2)])
        if ls.distance(zone) > A.gap + 1.0:
            continue
        rec = (L, ls, w, direction(x1, y1, x2, y2))
        (analog.append(rec) if n in ANALOG else logic.append((n,) + rec))
    if n not in ANALOG:
        for (x, y), vd in zip(r["vias"], r["via_d"]):
            if Point(x, y).buffer(vd / 2).intersects(zone):
                vias_in.append((n,) + tuple(round(v, 2) for v in design(x, y)))

esc = {}
for n, L, ls, w, d in logic:
    if L == "F.Cu" and n in xpads:
        esc.setdefault(n, []).append(ls.intersection(zone).buffer(w / 2))
esc_geom = {}
for n, gs in esc.items():
    u = unary_union(gs)
    parts = list(u.geoms) if hasattr(u, "geoms") else [u]
    keep = [p for p in parts if any(p.intersects(pp.buffer(0.01)) for pp in xpads[n])]
    esc_geom[n] = unary_union(keep) if keep else None

tot = {"zone_logic_len": 0.0, "same_layer": 0.0, "broadside": 0.0, "same_layer_exempt_escape": 0.0}
per_net = {}
for n, L, ls, w, d in logic:
    inz = ls.intersection(zone)
    if inz.is_empty or inz.length == 0:
        continue
    tot["zone_logic_len"] += inz.length
    for kind, ok in (("same_layer", lambda La: La == L), ("broadside", lambda La: (L, La) in BROAD)):
        near = [als.buffer(A.gap + aw / 2 + w / 2) for (La, als, aw, ad) in analog
                if ok(La) and angdiff(d, ad) <= A.ang]
        if not near:
            continue
        par = inz.intersection(unary_union(near))
        if par.is_empty:
            continue
        tot[kind] += par.length
        per_net.setdefault(n, {"same_layer": 0.0, "broadside": 0.0})[kind] += par.length
        if kind == "same_layer" and esc_geom.get(n) is not None:
            tot["same_layer_exempt_escape"] += par.intersection(esc_geom[n]).length

out = dict(gap=A.gap, ang=A.ang, zone_parts=sorted(ZPARTS), zone_margin=A.zone_margin,
           via_frame="design (y = %s - y)" % yoff if yoff is not None else "KiCad",
           **{k: round(v, 2) for k, v in tot.items()}, logic_vias_in_zone=len(vias_in),
           per_net={k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in sorted(per_net.items())},
           vias=vias_in)
print("logic length in zone %.2f mm | parallel to analog: same layer %.2f mm (of which exempt escapes %.2f), "
      "broadside %.2f mm | logic vias in zone %d (positions in the %s frame)"
      % (tot["zone_logic_len"], tot["same_layer"], tot["same_layer_exempt_escape"], tot["broadside"], len(vias_in),
         out["via_frame"]))
for k, v in out["per_net"].items():
    print("  %-14s same %.2f  broadside %.2f" % (k, v["same_layer"], v["broadside"]))
if A.json:
    json.dump(out, open(A.json, "w"), indent=1)
