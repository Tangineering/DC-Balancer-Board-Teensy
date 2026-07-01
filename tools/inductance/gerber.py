"""
Minimal RS-274X (Gerber) and Excellon parser for copper-pour inductance extraction.

Scope, deliberately narrow:
  * Reads the copper layers exported by EAGLE (the format used by this project's
    references/PCB Manufacturing Files/copper_top.gbr / copper_bottom.gbr).
  * Extracts the three primitives we need to know "where is copper":
        - regions   : filled polygons  (G36 ... G37)            -> the pours
        - traces    : stroked segments  (aperture + D01)         -> the tracks
        - flashes   : single aperture placements (D03)           -> the pads
  * Reads the Excellon drill file (drill_1_64.xln) for via/hole locations.

It is intentionally dependency-light: pure stdlib + (optionally) numpy is NOT
required here -- this module returns plain Python lists/tuples of floats in
millimetres. The rasteriser (geometry.py) turns these into a copper mask.

What it does NOT do (documented limits, not silent gaps):
  * Aperture macros (%AM...) are approximated by their bounding circle. The only
    macro in this board's copper is the octagonal thermal/pad 'OC8', whose exact
    shape is irrelevant to pour inductance.
  * Arcs (G02/G03) inside regions are linearised. This board's copper uses linear
    interpolation only (verified: a single G01 in the file), so this path is a
    safety net, not the common case.
  * Step-and-repeat (%SR) is not handled (not present in these files).

Coordinates are returned in millimetres, absolute, in the Gerber's own frame.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Optional


# ----------------------------------------------------------------------------
# Data structures
# ----------------------------------------------------------------------------

@dataclass
class Aperture:
    """A Gerber aperture (D-code >= 10)."""
    code: int
    kind: str            # 'C', 'R', 'O', 'P', or 'MACRO'
    params: list[float] = field(default_factory=list)

    def bbox_halfextent(self) -> tuple[float, float]:
        """Half-width, half-height of the aperture bounding box (mm)."""
        if self.kind == 'C':
            r = self.params[0] / 2.0
            return r, r
        if self.kind in ('R', 'O'):
            return self.params[0] / 2.0, self.params[1] / 2.0
        if self.kind == 'P':
            r = self.params[0] / 2.0
            return r, r
        # MACRO / unknown -> bounding circle stored in params[0]
        r = (self.params[0] / 2.0) if self.params else 0.0
        return r, r

    def contains(self, dx: float, dy: float) -> bool:
        """Is local point (dx,dy), relative to the aperture origin, inside copper?"""
        if self.kind == 'C':
            return (dx * dx + dy * dy) <= (self.params[0] / 2.0) ** 2
        if self.kind == 'R':
            return abs(dx) <= self.params[0] / 2.0 and abs(dy) <= self.params[1] / 2.0
        if self.kind == 'O':
            w, h = self.params[0], self.params[1]
            # obround = stadium; approximate as rounded rectangle
            a, b = w / 2.0, h / 2.0
            if w >= h:
                r = b
                cx = a - r
                if abs(dx) <= cx:
                    return abs(dy) <= r
                return (abs(dx) - cx) ** 2 + dy * dy <= r * r
            else:
                r = a
                cy = b - r
                if abs(dy) <= cy:
                    return abs(dx) <= r
                return (abs(dy) - cy) ** 2 + dx * dx <= r * r
        if self.kind == 'P':
            r = self.params[0] / 2.0
            return (dx * dx + dy * dy) <= r * r          # bounding circle of polygon
        r = (self.params[0] / 2.0) if self.params else 0.0
        return (dx * dx + dy * dy) <= r * r


@dataclass
class Trace:
    x0: float
    y0: float
    x1: float
    y1: float
    width: float          # aperture diameter / stroke width (mm)


@dataclass
class Flash:
    x: float
    y: float
    aperture: Aperture


@dataclass
class Region:
    points: list[tuple[float, float]]    # closed polygon (mm)
    dark: bool = True                    # LPD=True paints copper, LPC=False clears it


@dataclass
class GerberLayer:
    name: str
    regions: list[Region] = field(default_factory=list)
    traces: list[Trace] = field(default_factory=list)
    flashes: list[Flash] = field(default_factory=list)
    units_mm: bool = True

    def bbox(self) -> tuple[float, float, float, float]:
        """(xmin, ymin, xmax, ymax) over every primitive, in mm."""
        xs: list[float] = []
        ys: list[float] = []
        for r in self.regions:
            for (x, y) in r.points:
                xs.append(x); ys.append(y)
        for t in self.traces:
            xs += [t.x0, t.x1]; ys += [t.y0, t.y1]
        for f in self.flashes:
            hx, hy = f.aperture.bbox_halfextent()
            xs += [f.x - hx, f.x + hx]; ys += [f.y - hy, f.y + hy]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))


# ----------------------------------------------------------------------------
# Gerber (RS-274X) parser
# ----------------------------------------------------------------------------

_RE_FS = re.compile(r"FSLAX(\d)(\d)Y(\d)(\d)")


def _coord(raw: str, int_digits: int, dec_digits: int) -> float:
    """Decode a Gerber integer coordinate token to mm (leading-zero-omitted)."""
    neg = raw.startswith('-')
    if neg:
        raw = raw[1:]
    raw = raw.lstrip('+')
    # Leading zeros omitted, trailing present: pad on the LEFT to full width.
    width = int_digits + dec_digits
    raw = raw.rjust(width, '0')
    val = int(raw) / (10 ** dec_digits)
    return -val if neg else val


def parse_gerber(path: str) -> GerberLayer:
    """Parse one RS-274X copper layer file into a GerberLayer."""
    with open(path, 'r', errors='replace') as fh:
        text = fh.read()

    name = path
    units_mm = True
    int_d, dec_d = 3, 4               # FSLAX34Y34 default for this board
    apertures: dict[int, Aperture] = {}
    macro_diam: dict[str, float] = {}   # macro name -> approx bounding diameter

    layer = GerberLayer(name=name)

    # --- split into commands. Extended commands are wrapped in %...% and may be
    #     multi-line (aperture macros). Function codes end with '*'. -----------
    # First pull out extended (%) blocks.
    pos = 0
    commands: list[str] = []
    while pos < len(text):
        if text[pos] == '%':
            end = text.find('%', pos + 1)
            block = text[pos + 1:end]
            commands.append('%' + block)         # keep marker
            pos = end + 1
        elif text[pos] in '\r\n \t':
            pos += 1
        else:
            end = text.find('*', pos)
            if end == -1:
                break
            commands.append(text[pos:end])
            pos = end + 1

    # Modal state
    cur_x = cur_y = 0.0
    cur_ap: Optional[Aperture] = None
    in_region = False
    region_pts: list[tuple[float, float]] = []
    dark = True
    interp = 1  # 1 linear, 2 cw, 3 ccw

    op_re = re.compile(r"^(?:X(-?\+?\d+))?(?:Y(-?\+?\d+))?(?:I(-?\+?\d+))?(?:J(-?\+?\d+))?(D0[123])?$")

    def flush_region():
        nonlocal region_pts
        if len(region_pts) >= 3:
            layer.regions.append(Region(points=region_pts[:], dark=dark))
        region_pts = []

    for cmd in commands:
        c = cmd.strip().rstrip('*')
        if not c:
            continue

        # ---- extended (%) commands -------------------------------------------
        if c.startswith('%'):
            body = c[1:]
            if body.startswith('MOMM'):
                units_mm = True
            elif body.startswith('MOIN'):
                units_mm = False
            elif body.startswith('FSLA') or body.startswith('FS'):
                m = _RE_FS.search(body)
                if m:
                    # FSLAX<int><dec>Y<int><dec>: decimals are group(2) for X.
                    int_d, dec_d = int(m.group(1)), int(m.group(2))
            elif body.startswith('LPD'):
                dark = True
            elif body.startswith('LPC'):
                dark = False
            elif body.startswith('AM'):
                # aperture macro: name on first line, primitives follow (split by '*')
                name_m = body[2:].split('*', 1)[0].strip()
                diam = _macro_bounding_diameter(body)
                macro_diam[name_m] = diam
            elif body.startswith('AD'):
                ap = _parse_aperture(body, macro_diam, units_mm)
                if ap:
                    apertures[ap.code] = ap
            # other extended commands (IP, IN, SR...) ignored
            continue

        # ---- function codes --------------------------------------------------
        # strip leading G-codes that share a line with an operation
        gmatch = re.match(r"^(G0?\d+)", c)
        if gmatch:
            g = gmatch.group(1)
            rest = c[len(g):]
            gnum = int(g[1:])
            if gnum == 36:
                in_region = True
                region_pts = []
                c = rest
            elif gnum == 37:
                flush_region()
                in_region = False
                c = rest
            elif gnum in (1, 2, 3):
                interp = gnum
                c = rest
            elif gnum in (74, 75):
                c = rest                         # arc quadrant mode; ignored (linear board)
            elif gnum == 4:
                continue                          # comment
            else:
                c = rest
            if not c:
                continue

        # aperture select  Dnn  (nn >= 10)
        dmatch = re.match(r"^D(\d+)$", c)
        if dmatch:
            code = int(dmatch.group(1))
            if code >= 10:
                cur_ap = apertures.get(code)
            continue

        # coordinate operation
        m = op_re.match(c)
        if not m:
            continue
        nx = _coord(m.group(1), int_d, dec_d) if m.group(1) else cur_x
        ny = _coord(m.group(2), int_d, dec_d) if m.group(2) else cur_y
        op = m.group(5)

        if op == 'D02':                          # move
            if in_region and region_pts:
                flush_region()                   # new contour within same region block
            cur_x, cur_y = nx, ny
            if in_region:
                region_pts = [(nx, ny)]
        elif op == 'D01':                        # interpolate / draw
            if in_region:
                # linear segment of the region contour (arcs linearised crudely)
                region_pts.append((nx, ny))
            else:
                if cur_ap is not None:
                    w = max(cur_ap.bbox_halfextent()) * 2.0
                    layer.traces.append(Trace(cur_x, cur_y, nx, ny, w))
            cur_x, cur_y = nx, ny
        elif op == 'D03':                        # flash
            if cur_ap is not None:
                layer.flashes.append(Flash(nx, ny, cur_ap))
            cur_x, cur_y = nx, ny
        else:
            # bare coordinate with no D-code: treat as move
            cur_x, cur_y = nx, ny

    if in_region:
        flush_region()

    layer.units_mm = units_mm
    if not units_mm:                              # normalise inches -> mm
        _scale_layer(layer, 25.4)
        layer.units_mm = True
    return layer


def _parse_aperture(body: str, macro_diam: dict[str, float], units_mm: bool) -> Optional[Aperture]:
    """Parse '%ADDnn<TYPE>,p1Xp2...' into an Aperture (params in mm)."""
    m = re.match(r"ADD(\d+)([A-Za-z_$][\w$]*),?(.*)", body)
    if not m:
        return None
    code = int(m.group(1))
    typ = m.group(2)
    rest = m.group(3)
    nums = [float(x) for x in re.split(r"[X]", rest) if _isnum(x)]
    scale = 1.0 if units_mm else 25.4
    nums = [n * scale for n in nums]
    if typ in ('C', 'R', 'O', 'P'):
        return Aperture(code=code, kind=typ, params=nums)
    # macro aperture
    diam = macro_diam.get(typ, nums[0] if nums else 0.0)
    return Aperture(code=code, kind='MACRO', params=[diam])


def _macro_bounding_diameter(body: str) -> float:
    """Very rough bounding diameter for an aperture macro definition."""
    nums = [float(x) for x in re.findall(r"-?\d+\.?\d*", body) if _isnum(x)]
    return max(nums) if nums else 0.0


def _isnum(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _scale_layer(layer: GerberLayer, k: float) -> None:
    for r in layer.regions:
        r.points = [(x * k, y * k) for (x, y) in r.points]
    for t in layer.traces:
        t.x0 *= k; t.y0 *= k; t.x1 *= k; t.y1 *= k; t.width *= k
    for f in layer.flashes:
        f.x *= k; f.y *= k
        f.aperture.params = [p * k for p in f.aperture.params]


# ----------------------------------------------------------------------------
# Excellon drill parser
# ----------------------------------------------------------------------------

@dataclass
class Hole:
    x: float
    y: float
    diameter: float       # mm


def parse_excellon(path: str) -> list[Hole]:
    """Parse an Excellon drill file into a list of Holes (mm)."""
    with open(path, 'r', errors='replace') as fh:
        lines = fh.read().splitlines()

    units_mm = True
    tools: dict[int, float] = {}
    cur_tool = 0
    holes: list[Hole] = []
    # Excellon format/decimal handling: many EAGLE files emit explicit decimals.
    # Zero-suppression: header 'TZ' => trailing zeros KEPT => leading suppressed
    # => numbers right-justified => pad on the LEFT.  'LZ' is the opposite.
    fmt_int, fmt_dec = 3, 3
    pad_left = True

    re_tool_def = re.compile(r"^T(\d+).*?C([\d.]+)")
    re_tool_sel = re.compile(r"^T(\d+)\s*$")
    re_xy = re.compile(r"X(-?[\d.]+)?Y(-?[\d.]+)?")

    in_header = True
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s in ('M48',):
            in_header = True
            continue
        if s in ('%', 'M95'):
            in_header = False
            continue
        if s.startswith('METRIC'):
            units_mm = True
            if 'LZ' in s:
                pad_left = False
            elif 'TZ' in s:
                pad_left = True
            m = re.search(r"(\d+)\.(\d+)", s)
            if m:
                fmt_int, fmt_dec = len(m.group(1)), len(m.group(2))
            continue
        if s.startswith('INCH'):
            units_mm = False
            if 'LZ' in s:
                pad_left = False
            elif 'TZ' in s:
                pad_left = True
            continue
        if s.startswith('FMAT'):
            continue
        mdef = re_tool_def.match(s)
        if mdef and in_header:
            tools[int(mdef.group(1))] = float(mdef.group(2))
            continue
        msel = re_tool_sel.match(s)
        if msel:
            cur_tool = int(msel.group(1))
            in_header = False
            continue
        if s.startswith('G') or s.startswith('M'):
            continue
        mxy = re_xy.search(s)
        if mxy and (mxy.group(1) or mxy.group(2)):
            x = _excellon_num(mxy.group(1), fmt_int, fmt_dec, pad_left) if mxy.group(1) else 0.0
            y = _excellon_num(mxy.group(2), fmt_int, fmt_dec, pad_left) if mxy.group(2) else 0.0
            if not units_mm:
                x *= 25.4; y *= 25.4
            d = tools.get(cur_tool, 0.0)
            if not units_mm:
                d *= 25.4
            holes.append(Hole(x, y, d))
    return holes


def _excellon_num(tok: str, int_d: int, dec_d: int, pad_left: bool) -> float:
    if tok is None:
        return 0.0
    if '.' in tok:
        return float(tok)
    neg = tok.startswith('-')
    if neg:
        tok = tok[1:]
    width = int_d + dec_d
    if pad_left:                       # leading zeros suppressed -> right-justified
        tok = tok.rjust(width, '0')
    else:                              # trailing zeros suppressed -> left-justified
        tok = tok.ljust(width, '0')
    val = int(tok) / (10 ** dec_d)
    return -val if neg else val


if __name__ == '__main__':
    import sys
    lyr = parse_gerber(sys.argv[1])
    bx = lyr.bbox()
    print(f"{lyr.name}")
    print(f"  regions={len(lyr.regions)} traces={len(lyr.traces)} flashes={len(lyr.flashes)}")
    print(f"  bbox(mm)= x[{bx[0]:.3f},{bx[2]:.3f}] y[{bx[1]:.3f},{bx[3]:.3f}]  "
          f"size={bx[2]-bx[0]:.2f} x {bx[3]-bx[1]:.2f}")
