"""Re-lay the CR or EIB schematic into functional blocks without changing its connectivity.

The tool reads the symbol instances (with all fields and UUIDs) from a source .kicad_sch, places them by
the block layout specs in gen/sch_layout/<board>/, draws the wires, labels, junctions, no-connect flags,
block frames and block titles, and writes the result. Symbol UUIDs, references, values, footprints and
fields are copied unchanged, so the PCB footprint links and the schematic-parity check are unaffected.
Every net keeps at least one local label with its original name, so the net names are unchanged.

Usage:
  python sch_blocks.py <board> <source.kicad_sch> <out.kicad_sch>   assemble
  python sch_blocks.py <board> <source.kicad_sch> --pins             print every pin point (debug)

Block spec (gen/sch_layout/<board>/<nn>_<id>.json), coordinates in mm, local to the block, y down,
all points on the 1.27 mm grid:
  {"id": "efuse", "title": "INPUT PROTECTION + EFUSE", "subtitle": "B.4: ...", "size": [w, h],
   "parts": {"U101": {"at": [x, y], "rot": 0}, "R101": {"at": [x, y], "rot": 90,
             "ref": [dx, dy], "val": [dx, dy]}},
   "wires": [["U101.6", [x, y], "R103.1"], ...],          polyline; a "REF.PIN" string is that pin's point
   "labels": [{"net": "VCHGIN", "at": "U101.1"},           at a pin: oriented away from the body
              {"net": "GND", "at": [x, y], "rot": 0}],     at a wire point: rot 0 right, 90 up, 180 left, 270 down
   "texts": [{"text": "...", "at": [x, y], "size": 1.27}]}
Pins that are no-connect in the source get their no-connect flag automatically.
The sheet layout gen/sch_layout/<board>/sheet.json: {"paper": [w, h], "blocks": {"efuse": [x, y], ...}}.
Parts that no block places are parked below the blocks with one label per pin (the legacy style).
"""
import glob
import json
import math
import os
import re
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
G = 1.27
NS = uuid.UUID("0b7d4e52-9a3c-4f1e-8d2a-6c5b4a3f2e10")


# ---------------------------------------------------------------- s-expression I/O
class Q(str):
    """A quoted string atom."""


def parse(text):
    tok = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))')
    pos, stack, cur = 0, [], []
    n = len(text)
    while pos < n:
        m = tok.match(text, pos)
        if not m or m.end() == pos:
            if text[pos:].strip() == "":
                break
            raise ValueError("parse error at %d" % pos)
        pos = m.end()
        if m.group(1):
            stack.append(cur)
            cur = []
        elif m.group(2):
            done = cur
            cur = stack.pop()
            cur.append(done)
        elif m.group(3) is not None:
            cur.append(Q(m.group(3).replace('\\"', '"').replace("\\\\", "\\")))
        else:
            cur.append(m.group(4))
    return cur[0]


def dump(node, depth=0):
    if isinstance(node, Q):
        return '"%s"' % node.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    if isinstance(node, str):
        return node
    inner = " ".join(dump(x, depth + 1) for x in node)
    return "(" + inner + ")"


def find(node, key):
    for x in node:
        if isinstance(x, list) and x and x[0] == key:
            return x
    return None


def findall(node, key):
    return [x for x in node if isinstance(x, list) and x and x[0] == key]


def num(v):
    return float(v)


def fmt(v):
    s = "%.4f" % v
    s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def snap(v):
    return round(v / G) * G


def uid(*k):
    return str(uuid.uuid5(NS, "/".join(str(x) for x in k)))


KICAD_CLI = os.environ.get("KICAD_CLI", r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe")


def netlist_of(sch_path):
    """Export the KiCad netlist of a schematic; return (components, {(ref, pin): net name})."""
    import subprocess
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".net")
    os.close(fd)
    try:
        r = subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", tmp, sch_path],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("netlist export failed: %s %s" % (r.stdout, r.stderr))
        root = parse(open(tmp, encoding="utf-8").read())
    finally:
        os.remove(tmp)
    comps = {}
    for c in findall(find(root, "components"), "comp"):
        ref = str(find(c, "ref")[1])
        d = {}
        for k in ("value", "footprint"):
            v = find(c, k)
            d[k] = str(v[1]) if v else ""
        d["fields"] = {str(f[1][1]): (str(f[2]) if len(f) > 2 else "") for f in findall(find(c, "fields") or [], "field")}
        d["props"] = {str(find(p, "name")[1]): str(find(p, "value")[1]) for p in findall(c, "property")
                      if find(p, "value")}
        d["tstamps"] = str(find(c, "tstamps")[1]) if find(c, "tstamps") else ""
        d["sheetpath"] = dump(find(c, "sheetpath"))
        comps[ref] = d
    pins = {}
    for n in findall(find(root, "nets"), "net"):
        name = str(find(n, "name")[1])
        for nd in findall(n, "node"):
            pins[(str(find(nd, "ref")[1]), str(find(nd, "pin")[1]))] = name
    return comps, pins


# ---------------------------------------------------------------- geometry
def lib_pins(libsym):
    """{pin number: (x, y, angle, length)} in library coordinates (y up), over all units/sub-symbols."""
    out = {}

    def walk(n):
        for x in n:
            if isinstance(x, list) and x:
                if x[0] == "pin":
                    at = find(x, "at")
                    ln = find(x, "length")
                    nm = find(x, "number")
                    out[str(nm[1])] = (num(at[1]), num(at[2]), int(float(at[3])) if len(at) > 3 else 0,
                                       num(ln[1]) if ln else 0.0)
                else:
                    walk(x)
    walk(libsym)
    return out


def lib_body(libsym):
    """Bounding box of the body graphics (rectangles and polylines) in library coordinates."""
    xs, ys = [], []

    def walk(n):
        for x in n:
            if isinstance(x, list) and x:
                if x[0] == "rectangle":
                    s, e = find(x, "start"), find(x, "end")
                    xs.extend([num(s[1]), num(e[1])])
                    ys.extend([num(s[2]), num(e[2])])
                elif x[0] == "polyline":
                    for p in findall(find(x, "pts"), "xy"):
                        xs.append(num(p[1]))
                        ys.append(num(p[2]))
                elif x[0] != "pin":
                    walk(x)
    walk(libsym)
    if not xs:
        return (-1.27, -1.27, 1.27, 1.27)
    return (min(xs), min(ys), max(xs), max(ys))


def xform(px, py, X, Y, rot):
    """Library point (y up) to sheet point (y down) for a symbol at (X, Y) rotated rot degrees."""
    a = math.radians(rot)
    rx = px * math.cos(a) - py * math.sin(a)
    ry = px * math.sin(a) + py * math.cos(a)
    return (round(X + rx, 4), round(Y - ry, 4))


def pin_dir(ang, rot):
    """Outward direction of a pin (from the body toward the connection end) on the sheet, as (dx, dy)."""
    # A library pin at angle a points from its connection end toward the body; outward is a + 180.
    a = math.radians((ang + 180 + rot) % 360)
    return (round(math.cos(a)), -round(math.sin(a)))


# ---------------------------------------------------------------- source model
class Source:
    def __init__(self, path):
        self.root = parse(open(path, encoding="utf-8").read())
        self.libs = {}
        for s in findall(find(self.root, "lib_symbols"), "symbol"):
            self.libs[str(s[1])] = s
        self.syms = {}
        for s in findall(self.root, "symbol"):
            ref = None
            for p in findall(s, "property"):
                if p[1] == "Reference":
                    ref = str(p[2])
            self.syms[ref] = s
        self.pins = {r: lib_pins(self.libs[str(find(s, "lib_id")[1])]) for r, s in self.syms.items()}
        # source connectivity from KiCad's own netlist export: {(ref, pin): net name without the "/"}
        self.net, self.nc = {}, set()
        for (ref, pin), name in netlist_of(path)[1].items():
            if name.startswith("unconnected-"):
                self.nc.add((ref, pin))
            else:
                self.net[(ref, pin)] = name.lstrip("/")

    def at(self, ref):
        a = find(self.syms[ref], "at")
        return num(a[1]), num(a[2]), int(float(a[3])) if len(a) > 3 else 0

    def pin_points(self, ref, X=None, Y=None, rot=None):
        x0, y0, r0 = self.at(ref)
        X = x0 if X is None else X
        Y = y0 if Y is None else Y
        rot = r0 if rot is None else rot
        return {p: xform(px, py, X, Y, rot) for p, (px, py, a, ln) in self.pins[ref].items()}


# ---------------------------------------------------------------- assembly
def load_layout(board, only=None):
    """Sheet layout and block specs. only: a block id; the other blocks are then left out (their parts park).
    A block without a position in sheet.json is placed automatically in a row along the top."""
    d = os.path.join(HERE, "sch_layout", board)
    sheet = json.load(open(os.path.join(d, "sheet.json"), encoding="utf-8-sig"))
    only = only or os.environ.get("SCH_ONLY") or None
    blocks = []
    for f in sorted(glob.glob(os.path.join(d, "[0-9]*.json"))):
        b = json.load(open(f, encoding="utf-8-sig"))
        b["_file"] = os.path.basename(f)
        if only and b.get("id") != only:
            continue
        blocks.append(b)
    x = 20.32
    for b in blocks:
        if b["id"] not in sheet["blocks"]:
            sheet["blocks"][b["id"]] = [x, 20.32]
        x = max(x, sheet["blocks"][b["id"]][0] + b["size"][0] + 12.7)
    return sheet, blocks


def on_seg(p, a, b, interior=True):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    if abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) > 1e-6:
        return False
    if min(x1, x2) - 1e-6 <= x <= max(x1, x2) + 1e-6 and min(y1, y2) - 1e-6 <= y <= max(y1, y2) + 1e-6:
        if interior:
            return (abs(x - x1) + abs(y - y1)) > 1e-6 and (abs(x - x2) + abs(y - y2)) > 1e-6
        return True
    return False


def assemble(board, src_path, out_path, report=None):
    src = Source(src_path)
    sheet, blocks = load_layout(board)
    # PWR_FLAG pins are not in KiCad's netlist; sheet.json names their nets, and the assembler labels them
    for ref, net in sheet.get("flags", {}).items():
        src.net[(ref, "1")] = net
    errors, warns = [], []
    placed = {}          # ref -> (X, Y, rot, blockid, spec)
    out_items = []       # s-expr nodes after the symbols
    wires_all, labels_all = [], []
    texts = []
    rects = []
    for b in blocks:
        bid = b["id"]
        if bid not in sheet["blocks"]:
            errors.append("block %s has no position in sheet.json" % bid)
            continue
        ox, oy = sheet["blocks"][bid]
        w, h = b["size"]
        rects.append((bid, ox, oy, ox + w, oy + h))
        texts.append((b.get("title", bid).upper(), ox + 2.54, oy + 7.62, 3.81, "#848484", bid + "/title"))
        if b.get("subtitle"):
            texts.append((b["subtitle"], ox + 2.54, oy + 11.43, 1.524, "#848484", bid + "/sub"))
        for i, t in enumerate(b.get("texts", [])):
            texts.append((t["text"], ox + t["at"][0], oy + t["at"][1], t.get("size", 1.27), t.get("color"),
                          "%s/t%d" % (bid, i)))
        for ref, ps in b.get("parts", {}).items():
            if ref not in src.syms:
                errors.append("%s: unknown part %s" % (bid, ref))
                continue
            if ref in placed:
                errors.append("%s placed in both %s and %s" % (ref, placed[ref][3], bid))
                continue
            x, y = ps["at"]
            X, Y = ox + x, oy + y
            if abs(snap(X) - X) > 1e-3 or abs(snap(Y) - Y) > 1e-3:
                errors.append("%s: %s at (%s, %s) is off the 1.27 mm grid" % (bid, ref, x, y))
            placed[ref] = (X, Y, int(ps.get("rot", 0)), bid, ps)

    def pt(bid, ox, oy, p):
        if isinstance(p, str):
            ref, _, pin = p.partition(".")
            if ref not in placed:
                errors.append("%s: pin reference %s to a part not placed" % (bid, p))
                return None
            X, Y, rot, pb, _ = placed[ref]
            pts = src.pin_points(ref, X, Y, rot)
            if pin not in pts:
                errors.append("%s: %s has no pin %s" % (bid, ref, pin))
                return None
            return pts[pin]
        return (round(ox + p[0], 4), round(oy + p[1], 4))

    for b in blocks:
        bid = b["id"]
        if bid not in sheet["blocks"]:
            continue
        ox, oy = sheet["blocks"][bid]
        for wi, poly in enumerate(b.get("wires", [])):
            pts = [pt(bid, ox, oy, p) for p in poly]
            if None in pts:
                continue
            for a, c in zip(pts, pts[1:]):
                if a == c:
                    continue
                if abs(a[0] - c[0]) > 1e-6 and abs(a[1] - c[1]) > 1e-6:
                    errors.append("%s: wire %d segment %s-%s is not horizontal or vertical" % (bid, wi, a, c))
                wires_all.append((a, c, "%s/w%d/%s" % (bid, wi, len(wires_all))))
        for li, lb in enumerate(b.get("labels", [])):
            if isinstance(lb["at"], str):
                ref, _, pin = lb["at"].partition(".")
                p = pt(bid, ox, oy, lb["at"])
                if p is None:
                    continue
                if "rot" in lb:
                    rot = lb["rot"]
                else:
                    X, Y, srot, _, _ = placed[ref]
                    dx, dy = pin_dir(src.pins[ref][pin][2], srot)
                    rot = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[(dx, dy)]
            else:
                p = pt(bid, ox, oy, lb["at"])
                rot = lb.get("rot", 0)
            labels_all.append((lb["net"], p, rot, "%s/l%d" % (bid, li), lb.get("kind", "label")))

    # power flags placed in a block: label the flag pin with its net (unless the block already did)
    have = {(round(p[0], 3), round(p[1], 3)) for _, p, _, _, _ in labels_all if p}
    for ref, net in sheet.get("flags", {}).items():
        if ref in placed:
            X, Y, rot, bid, ps = placed[ref]
            q = src.pin_points(ref, X, Y, rot)["1"]
            if (round(q[0], 3), round(q[1], 3)) not in have:
                dx, dy = pin_dir(src.pins[ref]["1"][2], rot)
                r = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[(dx, dy)]
                labels_all.append((net, q, r, "%s/flag/%s" % (bid, ref), "label"))
    # park parts no block placed (legacy style: one label per pin)
    unplaced = [r for r in src.syms if r not in placed]
    py0 = max([r[4] for r in rects] + [0]) + 30.0
    px, rowh = 20.32, 0
    for ref in sorted(unplaced):
        x0, y0, r0 = src.at(ref)
        bx = lib_body(src.libs[str(find(src.syms[ref], "lib_id")[1])])
        cw = (bx[2] - bx[0]) + 40.64
        ch = (bx[3] - bx[1]) + 15.24
        if px + cw > sheet["paper"][0] - 20:
            px, py0, rowh = 20.32, py0 + rowh, 0
        X, Y = snap(px + cw / 2), snap(py0 + ch / 2)
        placed[ref] = (X, Y, 0, "_parked", {})
        for p, q in src.pin_points(ref, X, Y, 0).items():
            if (ref, p) in src.nc:
                continue
            net = src.net.get((ref, p))
            if net is None:
                errors.append("parked %s pin %s has neither a label nor a no-connect in the source" % (ref, p))
                continue
            dx, dy = pin_dir(src.pins[ref][p][2], 0)
            rot = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[(dx, dy)]
            labels_all.append((net, q, rot, "_parked/%s/%s" % (ref, p), "label"))
        px += cw
        rowh = max(rowh, ch)
    if unplaced:
        warns.append("%d parts parked (no block places them): %s" % (len(unplaced), " ".join(sorted(unplaced))))

    # every pin point on the sheet
    pinpts = {}
    for ref, (X, Y, rot, bid, ps) in placed.items():
        for p, q in src.pin_points(ref, X, Y, rot).items():
            pinpts.setdefault((round(q[0], 3), round(q[1], 3)), []).append((ref, p))

    # no-connect flags; checks that no wire or label lands on them
    ncs = []
    for (ref, p) in sorted(src.nc):
        X, Y, rot, bid, ps = placed[ref]
        ncs.append((src.pin_points(ref, X, Y, rot)[p], "%s.%s" % (ref, p)))

    # split every wire at the wire ends and labels that touch its interior, so that every connection
    # is endpoint-to-endpoint (KiCad does not join a wire end to another wire's interior on file load)
    cuts = set()
    for a, c, _ in wires_all:
        cuts.add((round(a[0], 3), round(a[1], 3)))
        cuts.add((round(c[0], 3), round(c[1], 3)))
    for _, p, _, _, _ in labels_all:
        if p:
            cuts.add((round(p[0], 3), round(p[1], 3)))
    split = []
    for a, c, wid in wires_all:
        inner = sorted([k for k in cuts if on_seg(k, a, c, interior=True)],
                       key=lambda k: abs(k[0] - a[0]) + abs(k[1] - a[1]))
        pts = [a] + inner + [c]
        for i, (u, v) in enumerate(zip(pts, pts[1:])):
            split.append((u, v, "%s/s%d" % (wid, i)))
    wires_all = split
    # junctions: a wire end (or pin) touched by 3 or more wire ends / pins / interior passes
    ends = {}
    for a, c, _ in wires_all:
        for e in (a, c):
            k = (round(e[0], 3), round(e[1], 3))
            ends[k] = ends.get(k, 0) + 1
    junctions = []
    for k, cnt in ends.items():
        total = cnt + len(pinpts.get(k, []))
        for a, c, _ in wires_all:
            if on_seg(k, a, c, interior=True):
                total += 2
        if total >= 3:
            junctions.append(k)
    # lint: pin points that sit on a wire interior (an unintended or invisible connection)
    for k, prs in pinpts.items():
        for a, c, wid in wires_all:
            if on_seg(k, a, c, interior=True):
                warns.append("pin %s lies on the interior of wire %s" % (
                    ",".join("%s.%s" % x for x in prs), wid))
    for q, nm in ncs:
        k = (round(q[0], 3), round(q[1], 3))
        if k in ends:
            errors.append("no-connect pin %s has a wire" % nm)

    # ---------------------------------------------------------------- write
    root = src.root
    out = [x for x in root if not (isinstance(x, list) and x and x[0] in (
        "symbol", "label", "no_connect", "wire", "junction", "text", "rectangle", "global_label",
        "sheet_instances", "embedded_fonts", "paper", "polyline"))]
    # keep header order: version, generator, generator_version, uuid, paper, title_block, lib_symbols
    hdr = []
    for x in out:
        hdr.append(x)
        if isinstance(x, list) and x and x[0] == "uuid":
            hdr.append(["paper", Q("User"), fmt(sheet["paper"][0]), fmt(sheet["paper"][1])])
    tb = find(hdr, "title_block")
    if tb is not None:
        # short lines that fit the title-block frame; the date and revision name the layout that printed the sheet
        for c in findall(tb, "comment"):
            if str(c[1]) == "1":
                c[2] = Q("Source: design doc B.8 pin-level netlist (gen/netlist.py)")
            if str(c[1]) == "2":
                c[2] = Q("Layout: gen/sch_blocks.py + gen/sch_layout/%s/; do not hand-edit" % board)
        if sheet.get("date"):
            d = find(tb, "date")
            if d is not None:
                d[1] = Q(sheet["date"])
        if sheet.get("rev"):
            r = find(tb, "rev")
            if r is not None:
                r[1] = Q(sheet["rev"])
    body = []
    for ref in sorted(placed, key=lambda r: (placed[r][3], r)):
        X, Y, rot, bid, ps = placed[ref]
        s = src.syms[ref]
        x0, y0, r0 = src.at(ref)
        node = [list(x) if isinstance(x, list) else x for x in s]
        for i, x in enumerate(node):
            if isinstance(x, list) and x and x[0] == "at":
                node[i] = ["at", fmt(X), fmt(Y), str(rot)]
            if isinstance(x, list) and x and x[0] == "property":
                p = [list(y) if isinstance(y, list) else y for y in x]
                at = find(p, "at")
                ai = p.index(at)
                name = str(p[1])
                ovr = ps.get({"Reference": "ref", "Value": "val"}.get(name, "_none"))
                eff = find(p, "effects")
                hidden = eff is not None and any(isinstance(e, list) and e and e[0] == "hide" for e in eff)
                if ovr is not None:
                    nx, ny = X + ovr[0], Y + ovr[1]
                    just = ps.get(name.lower()[:3] + "_just")
                elif name in ("Reference", "Value") and not hidden:
                    dx, dy = num(at[1]) - x0, num(at[2]) - y0
                    if rot in (90, 270) and str(find(s, "lib_id")[1]).split(":")[1] in ("R", "C"):
                        # horizontal passive: reference above, value below, centred
                        dy = 2.54 if str(find(s, "lib_id")[1]).endswith(":R") else 3.81
                        nx, ny = X, Y + (-dy if name == "Reference" else dy)
                        just = "center"
                    else:
                        nx, ny = X + dx, Y + dy
                        just = None
                else:
                    nx, ny = X, Y
                    just = None
                # field angles are stored in the symbol frame; keep the text horizontal on the sheet
                p[ai] = ["at", fmt(nx), fmt(ny), "90" if rot in (90, 270) else "0"]
                if just and eff is not None:
                    e2 = [y for y in eff if not (isinstance(y, list) and y and y[0] == "justify")]
                    if just != "center":
                        e2.append(["justify"] + just.split())
                    p[p.index(eff)] = e2
                node[i] = p
        body.append(node)
    for a, c, k in wires_all:
        body.append(["wire", ["pts", ["xy", fmt(a[0]), fmt(a[1])], ["xy", fmt(c[0]), fmt(c[1])]],
                     ["stroke", ["width", "0"], ["type", "default"]], ["uuid", Q(uid(board, "w", k))]])
    for k in sorted(junctions):
        body.append(["junction", ["at", fmt(k[0]), fmt(k[1])], ["diameter", "0"], ["color", "0", "0", "0", "0"],
                     ["uuid", Q(uid(board, "j", k))]])
    for net, p, rot, k, kind in labels_all:
        just = {0: "left bottom", 90: "left bottom", 180: "right bottom", 270: "right bottom"}[rot]
        body.append(["label", Q(net), ["at", fmt(p[0]), fmt(p[1]), str(rot)],
                     ["effects", ["font", ["size", "1.27", "1.27"]], ["justify"] + just.split()],
                     ["uuid", Q(uid(board, "l", k))]])
    for q, nm in ncs:
        body.append(["no_connect", ["at", fmt(q[0]), fmt(q[1])], ["uuid", Q(uid(board, "nc", nm))]])
    for bid, x1, y1, x2, y2 in rects:
        body.append(["rectangle", ["start", fmt(x1), fmt(y1)], ["end", fmt(x2), fmt(y2)],
                     ["stroke", ["width", "0.254"], ["type", "dash"], ["color", "132", "132", "132", "1"]],
                     ["fill", ["type", "none"]], ["uuid", Q(uid(board, "rect", bid))]])
    for txt, x, y, size, color, k in texts:
        font = ["font", ["size", fmt(size), fmt(size)]]
        if color:
            c = color.lstrip("#")
            font.append(["color", str(int(c[0:2], 16)), str(int(c[2:4], 16)), str(int(c[4:6], 16)), "1"])
        body.append(["text", Q(txt), ["exclude_from_sim", "no"], ["at", fmt(x), fmt(y), "0"],
                     ["effects", font, ["justify", "left", "bottom"]], ["uuid", Q(uid(board, "t", k))]])
    final = hdr + body + [["sheet_instances", ["path", Q("/"), ["page", Q("1")]]], ["embedded_fonts", "no"]]
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("(" + " ".join(dump(x) for x in final if not isinstance(x, list)) + "\n")
        for x in final:
            if isinstance(x, list):
                f.write("  " + dump(x) + "\n")
        f.write(")\n")
    res = {"errors": errors, "warnings": warns, "placed": len(placed) - len(unplaced),
           "parked": len(unplaced), "wires": len(wires_all), "labels": len(labels_all),
           "junctions": len(junctions)}
    if report:
        json.dump(res, open(report, "w"), indent=1)
    return res


def main():
    board, src = sys.argv[1], sys.argv[2]
    if sys.argv[3] == "--pins":
        s = Source(src)
        for r in sorted(s.syms):
            print(r, {p: (s.net.get((r, p)) or ("NC" if (r, p) in s.nc else "?")) for p in s.pins[r]})
        return
    if sys.argv[3] == "--block":
        # pin points of a block's parts in block-local coordinates, with net, outward direction and body box
        s = Source(src)
        b = json.load(open(sys.argv[4], encoding="utf-8-sig"))
        flags = load_layout(board)[0].get("flags", {})
        for ref, ps in b["parts"].items():
            x, y = ps["at"]
            rot = int(ps.get("rot", 0))
            bx = lib_body(s.libs[str(find(s.syms[ref], "lib_id")[1])])
            c = [xform(bx[0], bx[1], x, y, rot), xform(bx[2], bx[3], x, y, rot)]
            print("%s at (%s, %s) rot %d body x %s..%s y %s..%s" % (
                ref, fmt(x), fmt(y), rot, fmt(min(c[0][0], c[1][0])), fmt(max(c[0][0], c[1][0])),
                fmt(min(c[0][1], c[1][1])), fmt(max(c[0][1], c[1][1]))))
            for p, q in sorted(s.pin_points(ref, x, y, rot).items(), key=lambda t: (t[1][0], t[1][1])):
                d = {(1, 0): "right", (-1, 0): "left", (0, -1): "up", (0, 1): "down"}[pin_dir(s.pins[ref][p][2], rot)]
                net = "NC" if (ref, p) in s.nc else (flags.get(ref) if ref in flags else s.net.get((ref, p), "?"))
                print("   %s.%s (%s, %s) %s %s" % (ref, p, fmt(q[0]), fmt(q[1]), d, net))
        return
    res = assemble(board, src, sys.argv[3])
    for e in res["errors"]:
        print("ERROR", e)
    for w in res["warnings"]:
        print("WARN ", w)
    print("placed %(placed)d parked %(parked)d wires %(wires)d labels %(labels)d junctions %(junctions)d" % res)
    sys.exit(1 if res["errors"] else 0)


if __name__ == "__main__":
    main()
