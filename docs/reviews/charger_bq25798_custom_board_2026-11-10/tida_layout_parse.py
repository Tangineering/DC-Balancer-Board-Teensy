"""Parse the TIDA-050047 (TIDM752 REV_A1) Altium outputs around the BQ2579x power stage.

Reads, without executing anything from the reference folder:
  - the Altium .PcbDoc (binary; ASCII records only): layer stack and component placements;
  - the RS-274X Gerbers (gerbonara 1.6.x): pads, vias and pours near U1 on every copper, mask and paste layer;
  - the Excellon drill file: hole sizes and positions near U1;
  - the .RUL design-rule export.

Coordinates are reported in mm in two frames:
  board : Gerber board coordinates, top view;
  cell  : origin at the U1 centre, rotated so that the BQ2579x power edge (pins 25-29) is at +y,
          the orientation of SLUSDV2C Fig 8-21 and of section 3.4 of the design document.
U1 is placed at 180 degrees on the TIDA board, so cell = -(board - U1 centre).

Usage:  python -I tida_layout_parse.py <REV_A1 folder> <png output folder>
Writes the text report to stdout and window renders (PNG) to the output folder.
"""
import math
import os
import re
import sys
from collections import Counter, defaultdict

from gerbonara import ExcellonFile, GerberFile
from gerbonara.utils import MM

MIL = 0.0254  # mm per mil

REV = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else None
GDIR = os.path.join(REV, 'Project Outputs', 'Gerber Output')
DDIR = os.path.join(REV, 'Project Outputs', 'NC Drill Output')
BASE = 'PD_BQ_Ref_Design_PCB'
PCB = os.path.join(REV, BASE + '.PcbDoc')


def hdr(t):
    print()
    print('=' * 100)
    print(t)
    print('=' * 100)


# ---------------------------------------------------------------- 1. PcbDoc: stack and placements
raw = open(PCB, 'rb').read()

hdr('1. Layer stack (PcbDoc board record: LAYERnNAME / COPTHICK / DIELHEIGHT / DIELTYPE / DIELCONST)')
i = raw.find(b'|LAYER1NAME=')
seg = raw[i:i + 60000].decode('latin1')
kv = dict(x.split('=', 1) for x in re.findall(
    r'\|(LAYER\d+(?:NAME|COPTHICK|DIELHEIGHT|DIELCONST|DIELMATERIAL|DIELTYPE|NEXT|PREV)=[^|]*)', seg))
n, total = 1, 0.0
print('Altium DIELTYPE: 1 = core, 2 = prepreg (Altium convention)')
while n and n != 0:
    name = kv.get('LAYER%dNAME' % n)
    cu = kv.get('LAYER%dCOPTHICK' % n, '0mil')
    di = kv.get('LAYER%dDIELHEIGHT' % n, '0mil')
    nxt = int(kv.get('LAYER%dNEXT' % n, '0'))
    cu_mil = float(cu.replace('mil', ''))
    di_mil = float(di.replace('mil', '')) if nxt else 0.0
    total += cu_mil + di_mil
    print('  L%-3d %-15s Cu %5.2f mil (%.1f um, %.2f oz)   dielectric below: %s'
          % (n, name, cu_mil, cu_mil * 25.4, cu_mil / 1.37,
             ('%.1f mil (%.3f mm) type %s er %s %s' % (di_mil, di_mil * MIL, kv.get('LAYER%dDIELTYPE' % n),
                                                       kv.get('LAYER%dDIELCONST' % n),
                                                       kv.get('LAYER%dDIELMATERIAL' % n))) if nxt else '-'))
    n = nxt
print('  Copper + dielectric total: %.1f mil = %.3f mm (solder mask not included)' % (total, total * MIL))

hdr('2. Component placements (PcbDoc Components6 records)')
comps = {}
for m in re.finditer(rb'SOURCEDESIGNATOR=([^|]*)', raw):
    s = raw[m.start() - 1500:m.start() + 1200].decode('latin1')
    a = s.rfind('\x00', 0, 1500)
    b = s.find('\x00', 1500)
    s = s[a + 1:b]

    def g(k):
        mm = re.search(r'\|' + k + r'=([^|]*)', s)
        return mm.group(1) if mm else ''
    des = g('SOURCEDESIGNATOR')
    if not g('X'):
        continue
    comps[des] = dict(pattern=g('PATTERN'), x=float(g('X').replace('mil', '')) * MIL,
                      y=float(g('Y').replace('mil', '')) * MIL, rot=float(g('ROTATION') or 0),
                      layer=g('LAYER'))
u1 = comps['U1']
print('U1: pattern %s, layer %s, rotation %.0f deg, PcbDoc (%.3f, %.3f) mm'
      % (u1['pattern'], u1['layer'], u1['rot'], u1['x'], u1['y']))


def to_cell_pcb(x, y):
    """PcbDoc coordinates -> cell frame (U1 rotated 180 deg on the board)."""
    return -(x - u1['x']), -(y - u1['y'])


print('\nParts within 12 mm of U1, cell frame (mm; +y = power edge side):')
print('  %-6s %-30s %-8s %6s %8s %8s %8s' % ('Ref', 'Pattern', 'Side', 'Rot', 'cell x', 'cell y', 'dist'))
near = []
for d, c in comps.items():
    cx, cy = to_cell_pcb(c['x'], c['y'])
    r = math.hypot(cx, cy)
    if r <= 12.0 and c['layer'] in ('TOP', 'BOTTOM', 'MID1', 'MID2'):
        near.append((r, d, c, cx, cy))
for r, d, c, cx, cy in sorted(near):
    print('  %-6s %-30s %-8s %6.0f %8.2f %8.2f %8.2f' % (d, c['pattern'], c['layer'], c['rot'], cx, cy, r))

# ---------------------------------------------------------------- 3. Gerbers: locate U1 pads
hdr('3. Gerber layers and the U1 land pattern as drawn')
layers = {
    'GTL': 'Top Layer (L1)', 'G1': 'Signal Layer 1 (L2)', 'G2': 'Signal Layer 2 (L3)', 'GBL': 'Bottom Layer (L4)',
    'GTS': 'Top Solder mask', 'GTP': 'Top Paste', 'GBS': 'Bottom Solder mask', 'GBP': 'Bottom Paste',
    'GTO': 'Top Overlay', 'GBO': 'Bottom Overlay', 'GM5': 'M5 Assembly Top', 'GM6': 'M6 Assembly Bottom',
    'GM10': 'M10 Fab Notes', 'GM12': 'M12 Stackup', 'GKO': 'Keep-Out', 'GM1': 'M1 Board Outline',
}
G = {}
for ext in layers:
    p = os.path.join(GDIR, BASE + '.' + ext)
    if os.path.exists(p):
        G[ext] = GerberFile.open(p)


def flashes(gf):
    out = []
    for o in gf.objects:
        if type(o).__name__ != 'Flash':
            continue
        (x0, y0), (x1, y1) = o.bounding_box(MM)
        out.append(dict(x=(x0 + x1) / 2, y=(y0 + y1) / 2, w=x1 - x0, h=y1 - y0,
                        ap=getattr(o.aperture, 'original_number', None),
                        apname=type(o.aperture).__name__, obj=o))
    return out


top_fl = flashes(G['GTL'])
# The 0.2 mm x 0.6 mm rounded-rectangle pads exist only on the RQM footprint; their centroid locates U1.
small = [f for f in top_fl if abs(min(f['w'], f['h']) - 0.200) < 0.02 and abs(max(f['w'], f['h']) - 0.600) < 0.03]
# Two QFN parts carry 0.2 x 0.6 mm pads (U1 RQM0029A and U4, the TPS25750). Cluster them and pick the cluster
# whose offset to the PcbDoc U1 position also maps the PcbDoc U4 position onto the other cluster.
clusters = []
for f in small:
    for c in clusters:
        if any(abs(f['x'] - q['x']) < 5 and abs(f['y'] - q['y']) < 5 for q in c):
            c.append(f)
            break
    else:
        clusters.append([f])
cents = [(sum(f['x'] for f in c) / len(c), sum(f['y'] for f in c) / len(c), len(c)) for c in clusters]
u4 = comps['U4']
best = None
for cx_, cy_, nc in cents:
    ox, oy = cx_ - u1['x'], cy_ - u1['y']
    err = min(math.hypot(u4['x'] + ox - c2[0], u4['y'] + oy - c2[1]) for c2 in cents if c2[:2] != (cx_, cy_))
    print('cluster of %d pads at (%.3f, %.3f); U4 mapping error %.2f mm' % (nc, cx_, cy_, err))
    if best is None or err < best[0]:
        best = (err, cx_, cy_)
ux, uy = best[1], best[2]
print('U1 cluster centroid (board) (%.3f, %.3f) mm' % (ux, uy))
# Refine the centre from the bounding box of all flashes and regions within 2.4 mm of the centroid.
cand = [f for f in top_fl if abs(f['x'] - ux) < 2.4 and abs(f['y'] - uy) < 2.4]
# Only the pin pads (rounded-rectangle macro flashes, short side 0.2 mm) define the land-pattern extent;
# vias and the under-body pours would bias the centre.
boxes = [(f['x'] - f['w'] / 2, f['y'] - f['h'] / 2, f['x'] + f['w'] / 2, f['y'] + f['h'] / 2) for f in cand
         if f['apname'] == 'ApertureMacroInstance' and abs(min(f['w'], f['h']) - 0.2) < 0.01]
bx0 = min(b[0] for b in boxes); by0 = min(b[1] for b in boxes)
bx1 = max(b[2] for b in boxes); by1 = max(b[3] for b in boxes)
UX, UY = (bx0 + bx1) / 2, (by0 + by1) / 2
print('U1 land-pattern extent (board): x %.3f..%.3f, y %.3f..%.3f -> %.3f x %.3f mm; centre (%.3f, %.3f)'
      % (bx0, bx1, by0, by1, bx1 - bx0, by1 - by0, UX, UY))
OFFX, OFFY = UX - u1['x'], UY - u1['y']
print('Offset Gerber - PcbDoc: (%.3f, %.3f) mm' % (OFFX, OFFY))


def cell(x, y):
    return -(x - UX), -(y - UY)


print('\nU1 flashes on GTL, cell frame (power edge at +y), sorted by edge:')
print('  %8s %8s %7s %7s  %s' % ('x', 'y', 'w', 'h', 'aperture'))
rows = []
for f in cand:
    cx, cy = cell(f['x'], f['y'])
    rows.append((round(-cy, 2), round(cx, 2), cx, cy, f))
for _, _, cx, cy, f in sorted(rows):
    print('  %8.3f %8.3f %7.3f %7.3f  D%s %s' % (cx, cy, f['w'], f['h'], f['ap'], f['apname']))
print('  count: %d flashes inside the 4.8 mm window' % len(cand))

# Regions (L-shaped corner pads are drawn as regions in some libraries)
print('\nRegions on GTL whose bounding box lies inside the U1 outline +/-2.4 mm (cell frame):')
for o in G['GTL'].objects:
    if type(o).__name__ != 'Region':
        continue
    (x0, y0), (x1, y1) = o.bounding_box(MM)
    if x1 - x0 < 3 and y1 - y0 < 3 and abs((x0 + x1) / 2 - UX) < 2.4 and abs((y0 + y1) / 2 - UY) < 2.4:
        a, b = cell(x0, y0), cell(x1, y1)
        print('  x %.3f..%.3f  y %.3f..%.3f  (%d vertices)' % (min(a[0], b[0]), max(a[0], b[0]),
                                                              min(a[1], b[1]), max(a[1], b[1]),
                                                              len(o.outline)))

# Mask and paste openings of U1
for ext in ('GTS', 'GTP'):
    fl = [f for f in flashes(G[ext]) if abs(f['x'] - UX) < 2.4 and abs(f['y'] - UY) < 2.4]
    sizes = Counter((round(min(f['w'], f['h']), 3), round(max(f['w'], f['h']), 3)) for f in fl)
    print('\n%s (%s) openings in the U1 window: %d; size histogram (short x long, mm): %s'
          % (ext, layers[ext], len(fl), dict(sizes)))
    regs = [o for o in G[ext].objects if type(o).__name__ == 'Region']
    rin = []
    for o in regs:
        (x0, y0), (x1, y1) = o.bounding_box(MM)
        if abs((x0 + x1) / 2 - UX) < 2.4 and abs((y0 + y1) / 2 - UY) < 2.4:
            rin.append((round(x1 - x0, 3), round(y1 - y0, 3)))
    if rin:
        print('   regions in the window (w x h, mm): %s' % rin)

# ---------------------------------------------------------------- 4. Drills
hdr('4. Drill holes (Excellon RoundHoles) - whole board and within the power-cell window')
ex = ExcellonFile.open(os.path.join(DDIR, BASE + '-RoundHoles.TXT'))
holes = []
for o in ex.objects:
    if type(o).__name__ != 'Flash':
        continue
    (x0, y0), (x1, y1) = o.bounding_box(MM)
    holes.append(((x0 + x1) / 2, (y0 + y1) / 2, round(x1 - x0, 3)))
print('Whole board: %s' % dict(Counter(h[2] for h in holes)))
WIN = (-9.0, 9.0, -6.0, 12.0)  # cell frame x0, x1, y0, y1


def inwin(cx, cy, w=WIN):
    return w[0] <= cx <= w[1] and w[2] <= cy <= w[3]


cell_holes = []
for x, y, d in holes:
    cx, cy = cell(x, y)
    if inwin(cx, cy):
        cell_holes.append((cx, cy, d))
print('Window cell x %.0f..%.0f, y %.0f..%.0f: %d holes, sizes %s'
      % (WIN[0], WIN[1], WIN[2], WIN[3], len(cell_holes), dict(Counter(h[2] for h in cell_holes))))
print('All holes in the window, cell frame (y descending): (x, y, drill)')
for cx, cy, d in sorted(cell_holes, key=lambda h: (-round(h[1], 2), h[0])):
    print('  (%6.2f, %6.2f) %.3f' % (cx, cy, d))
inside = [h for h in cell_holes if abs(h[0]) <= 2.2 and abs(h[1]) <= 2.2]
print('Holes inside the U1 land-pattern extent (|x|,|y| <= 2.2 mm): %d' % len(inside))
for cx, cy, d in sorted(inside, key=lambda h: (-h[1], h[0])):
    print('  (%6.3f, %6.3f) drill %.3f' % (cx, cy, d))

# Land pattern of SLUSDV2C p.149 as rectangles (cell frame, TI top view), pin -> list of (x0, x1, y0, y1)
LP = {}
for k, y in enumerate((1.2, 0.8, 0.4, 0.0, -0.4, -0.8, -1.2)):
    LP[2 + k] = [(-2.2, -1.6, y - 0.1, y + 0.1)]                      # pins 2-8, left
    L = {-0.4: 0.68, -0.8: 0.65, -1.2: 0.70}.get(y, 0.6)              # pins 19, 18, 17 longer
    LP[23 - k] = [(2.2 - L, 2.2, y - 0.1, y + 0.1)]                   # pins 23-17, right
for k, x in enumerate((-1.0, -0.6, -0.2, 0.2, 0.6, 1.0)):
    LP[10 + k] = [(x - 0.1, x + 0.1, -2.2, -1.6)]                     # pins 10-15, control edge
for pin, x in ((25, 0.9), (26, 0.45), (27, 0.0), (28, -0.45)):
    LP[pin] = [(x - 0.1, x + 0.1, 1.2, 2.2)]                          # power edge
LP[29] = [(-1.0, -0.8, 1.25, 2.2)]                                    # PMID, 0.95 mm long
LP[1] = [(-2.2, -1.25, 1.5, 1.7), (-1.45, -1.25, 1.5, 2.2)]          # L-shaped corner pads
LP[24] = [(1.25, 2.2, 1.5, 1.7), (1.25, 1.45, 1.5, 2.2)]
LP[9] = [(-2.2, -1.3, -1.7, -1.5), (-1.5, -1.3, -2.2, -1.5)]
LP[16] = [(1.3, 2.2, -1.7, -1.5), (1.3, 1.5, -2.2, -1.5)]
PIN_NAME = {1: 'STAT', 2: 'VBUS', 3: 'VBUS', 4: 'BTST1', 5: 'REGN', 6: 'D+', 7: 'D-', 8: 'VAC2', 9: 'VAC1',
            10: 'ACDRV2', 11: 'ACDRV1', 12: '/QON', 13: '/CE', 14: 'SCL', 15: 'SDA', 16: 'TS', 17: 'ILIM_HIZ',
            18: 'BATP', 19: 'BTST2', 20: 'PROG', 21: '/INT', 22: 'BAT', 23: 'BAT', 24: 'SDRV', 25: 'SYS',
            26: 'SW2', 27: 'GND', 28: 'SW1', 29: 'PMID'}


def rect_dist(px, py, r):
    dx = max(r[0] - px, 0, px - r[1])
    dy = max(r[2] - py, 0, py - r[3])
    return math.hypot(dx, dy)


print('\nCheck: every GTL straight pin-pad flash against the SLUSDV2C p.149 rectangles:')
dev = 0.0
for f in cand:
    if f['apname'] != 'ApertureMacroInstance':
        continue
    cx, cy = cell(f['x'], f['y'])
    best_d = min((abs((r[0] + r[1]) / 2 - cx) + abs((r[2] + r[3]) / 2 - cy) + abs((r[1] - r[0]) - f['w'])
                  + abs((r[3] - r[2]) - f['h'])) for rs in LP.values() for r in rs)
    dev = max(dev, best_d)
print('  max summed deviation (centre x + centre y + width + height): %.4f mm' % dev)

print('\nUnder-body vias: edge clearance of the via land to the three nearest pin pads (mm):')
for cx, cy, d in sorted(inside, key=lambda h: (-h[1], h[0])):
    land = 0.762 if d > 0.35 else 0.508
    ds = sorted((rect_dist(cx, cy, r) - land / 2, p) for p, rs in LP.items() for r in rs)
    seen, out = set(), []
    for v, p in ds:
        if p not in seen:
            seen.add(p)
            out.append('%d %s %.3f' % (p, PIN_NAME[p], v))
        if len(out) == 3:
            break
    print('  (%6.3f, %6.3f) drill %.3f land %.3f -> %s' % (cx, cy, d, land, '; '.join(out)))

# Via pad diameters: circular flashes on L2/L3 co-located with drills
print('\nVia land diameters (circular flashes on GTL/GBL concentric with a drill, window):')
for ext in ('GTL', 'G1', 'G2', 'GBL'):
    fl = flashes(G[ext])
    pairs = Counter()
    for cx, cy, d in cell_holes:
        for f in fl:
            fx, fy = cell(f['x'], f['y'])
            if abs(fx - cx) < 0.01 and abs(fy - cy) < 0.01 and abs(f['w'] - f['h']) < 0.01:
                pairs[(d, round(f['w'], 3))] += 1
    print('  %s: drill -> land: %s' % (ext, dict(pairs)))

# ---------------------------------------------------------------- 5. Pours and lines per layer in the window
hdr('5. Copper per layer in the power-cell window (cell frame)')
for ext in ('GTL', 'G1', 'G2', 'GBL'):
    gf = G[ext]
    cnt = Counter()
    widths = Counter()
    regs = []
    for o in gf.objects:
        t = type(o).__name__
        (x0, y0), (x1, y1) = o.bounding_box(MM)
        a, b = cell(x0, y0), cell(x1, y1)
        rx0, rx1, ry0, ry1 = min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1])
        if rx1 < WIN[0] or rx0 > WIN[1] or ry1 < WIN[2] or ry0 > WIN[3]:
            continue
        cnt[t] += 1
        if t in ('Line', 'Arc'):
            widths[round(o.aperture.equivalent_width(MM), 3)] += 1
        if t == 'Region':
            regs.append((rx0, rx1, ry0, ry1, o.polarity_dark))
    print('\n%s (%s): objects %s' % (ext, layers[ext], dict(cnt)))
    print('  line widths (mm: count): %s' % dict(sorted(widths.items())))
    big = [r for r in regs if (r[1] - r[0]) * (r[3] - r[2]) > 1.0]
    print('  regions > 1 mm^2 bbox: %d (dark %d, clear %d)' % (len(big), sum(r[4] for r in big),
                                                               sum(not r[4] for r in big)))
    for r in sorted(big, key=lambda r: -(r[1] - r[0]) * (r[3] - r[2]))[:14]:
        print('   %s  x %6.2f..%6.2f  y %6.2f..%6.2f' % ('dark ' if r[4] else 'clear', r[0], r[1], r[2], r[3]))

# Minimum line width over the whole board per layer
print('\nMinimum drawn line width per copper layer, whole board (mm):')
for ext in ('GTL', 'G1', 'G2', 'GBL'):
    ws = [round(o.aperture.equivalent_width(MM), 3) for o in G[ext].objects if type(o).__name__ in ('Line', 'Arc')]
    print('  %s: min %.3f, histogram %s' % (ext, min(ws), dict(sorted(Counter(ws).items()))))

# ---------------------------------------------------------------- 5b. Schematic library part pin map
hdr('5b. BQ25792RQM library part in BQ25792.SchDoc: pin number -> name (Altium RECORD=2 pin records)')
sch = open(os.path.join(REV, 'BQ25792.SchDoc'), 'rb').read()
print('Part names found: %s' % sorted(set(x.decode() for x in re.findall(rb'BQ2579\w*', sch))))
DS_PINS = {1: 'STAT', 2: 'VBUS', 3: 'VBUS', 4: 'BTST1', 5: 'REGN', 6: 'D+', 7: 'D-', 8: 'VAC2', 9: 'VAC1',
           10: 'ACDRV2', 11: 'ACDRV1', 12: 'QON', 13: 'CE', 14: 'SCL', 15: 'SDA', 16: 'TS', 17: 'ILIM_HIZ',
           18: 'BATP', 19: 'BTST2', 20: 'PROG', 21: 'INT', 22: 'BAT', 23: 'BAT', 24: 'SDRV', 25: 'SYS', 26: 'SW2',
           27: 'GND', 28: 'SW1', 29: 'PMID'}  # SLUSDV2C Table 5-1 (BQ25798)
found = {}
# Overbar names are stored with backslashes (Q\O\N\); they are stripped before the comparison.
# The sheet holds other parts too, so a pin counts only where number and name both match.
for m in re.finditer(rb'\|RECORD=2\|[^\x00]*', sch):
    t = m.group(0).decode('latin1')
    nm = re.search(r'\|NAME=([^|]*)', t)
    dg = re.search(r'\|DESIGNATOR=(\d+)\|', t)
    if nm and dg and int(dg.group(1)) in DS_PINS:
        if nm.group(1).replace(chr(92), '') == DS_PINS[int(dg.group(1))]:
            found[int(dg.group(1))] = DS_PINS[int(dg.group(1))]
print('Pins whose SchDoc number and name equal SLUSDV2C Table 5-1: %d of 29' % len(found))
print('Missing: %s' % [k for k in DS_PINS if k not in found])

# ---------------------------------------------------------------- 6. Design rules
hdr('6. Design-rule export (.RUL), values in mil')
for line in open(os.path.join(GDIR, BASE + '.RUL'), encoding='latin1'):
    if line.startswith('RuleKind'):
        print('  ' + line.strip())

# ---------------------------------------------------------------- 7. Renders
if OUT:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon, Circle

    def prims_polys(gf, win):
        polys = []
        for o in gf.objects:
            (x0, y0), (x1, y1) = o.bounding_box(MM)
            a, b = cell(x0, y0), cell(x1, y1)
            if max(a[0], b[0]) < win[0] or min(a[0], b[0]) > win[1] or max(a[1], b[1]) < win[2] \
                    or min(a[1], b[1]) > win[3]:
                continue
            for p in o.to_primitives(MM):
                pn = type(p).__name__
                dark = getattr(p, 'polarity_dark', True)
                if pn == 'Circle':
                    polys.append(('c', cell(p.x, p.y), p.r, dark))
                elif pn == 'Rectangle':
                    cx0, cy0 = p.x, p.y
                    hw, hh = p.w / 2, p.h / 2
                    rot = getattr(p, 'rotation', 0) or 0
                    pts = []
                    for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
                        rx = dx * math.cos(rot) - dy * math.sin(rot)
                        ry = dx * math.sin(rot) + dy * math.cos(rot)
                        pts.append(cell(cx0 + rx, cy0 + ry))
                    polys.append(('p', pts, None, dark))
                elif pn == 'Line':
                    x0p, y0p = cell(p.x1, p.y1)
                    x1p, y1p = cell(p.x2, p.y2)
                    polys.append(('l', ((x0p, y0p), (x1p, y1p)), p.width, dark))
                elif pn == 'ArcPoly':
                    pts = [cell(x, y) for x, y in p.outline]
                    if len(pts) > 2:
                        polys.append(('p', pts, None, dark))
        return polys

    def render(ext, win, fname, title):
        fig, ax = plt.subplots(figsize=(9, 9 * (win[3] - win[2]) / (win[1] - win[0])))
        ax.set_facecolor('white')
        for kind, geo, r, dark in prims_polys(G[ext], win):
            col = '#b87333' if dark else 'white'
            if kind == 'c':
                ax.add_patch(Circle(geo, r, color=col, lw=0))
            elif kind == 'p':
                ax.add_patch(Polygon(geo, closed=True, color=col, lw=0))
            elif kind == 'l':
                # draw a stroked line as its exact outline: rectangle plus two end discs (data units)
                (xa, ya), (xb, yb) = geo
                L = math.hypot(xb - xa, yb - ya)
                if L > 1e-9:
                    nx, ny = -(yb - ya) / L * r / 2, (xb - xa) / L * r / 2
                    ax.add_patch(Polygon([(xa + nx, ya + ny), (xb + nx, yb + ny), (xb - nx, yb - ny),
                                          (xa - nx, ya - ny)], closed=True, color=col, lw=0))
                ax.add_patch(Circle((xa, ya), r / 2, color=col, lw=0))
                ax.add_patch(Circle((xb, yb), r / 2, color=col, lw=0))
        for cx, cy, d in cell_holes:
            ax.add_patch(Circle((cx, cy), d / 2, color='black', lw=0))
        ax.set_xlim(win[0], win[1]); ax.set_ylim(win[2], win[3]); ax.set_aspect('equal')
        ax.grid(True, lw=0.3); ax.set_title(title, fontsize=9)
        ax.set_xlabel('cell x (mm)'); ax.set_ylabel('cell y (mm), power edge at +y')
        fig.tight_layout(); fig.savefig(os.path.join(OUT, fname), dpi=110); plt.close(fig)

    os.makedirs(OUT, exist_ok=True)
    for ext in ('GTL', 'G1', 'G2', 'GBL', 'GTO', 'GBO', 'GM5', 'GM6'):
        render(ext, WIN, 'tida_%s.png' % ext, '%s %s, cell frame, drills in black' % (ext, layers[ext]))
    render('GTL', (-2.6, 2.6, -2.6, 2.6), 'tida_GTL_ic.png', 'GTL U1 land pattern, cell frame')
    render('G2', (-3.0, 3.0, -1.0, 9.0), 'tida_G2_sw.png', 'G2 (L3) SW1/SW2 strips, cell frame')
    render('GTL', (-9.0, 9.0, 1.5, 6.5), 'tida_GTL_caps.png', 'GTL PMID / SYS rows, cell frame')
    render('GTP', (-2.6, 2.6, -2.6, 2.6), 'tida_GTP_ic.png', 'GTP U1 paste, cell frame')
    render('GTS', (-2.6, 2.6, -2.6, 2.6), 'tida_GTS_ic.png', 'GTS U1 mask openings, cell frame')
    # whole-board views of the fab-note and stack-up layers
    for ext in ('GM10', 'GM12'):
        gf = G[ext]
        (x0, y0), (x1, y1) = gf.bounding_box(MM)
        fig, ax = plt.subplots(figsize=(14, 14 * (y1 - y0) / (x1 - x0)))
        for o in gf.objects:
            for p in o.to_primitives(MM):
                if type(p).__name__ == 'Line':
                    ax.plot([p.x1, p.x2], [p.y1, p.y2], 'k-', lw=0.5)
        ax.set_aspect('equal'); ax.axis('off')
        fig.savefig(os.path.join(OUT, 'tida_%s.png' % ext), dpi=130); plt.close(fig)
        # crop to the table in the right 35 % of the layer extent, at a readable scale
        segs = [p for o in gf.objects for p in o.to_primitives(MM) if type(p).__name__ == 'Line'
                and min(p.x1, p.x2) > x0 + 0.65 * (x1 - x0)]
        cx0 = min(min(p.x1, p.x2) for p in segs); cx1 = max(max(p.x1, p.x2) for p in segs)
        cy0 = min(min(p.y1, p.y2) for p in segs); cy1 = max(max(p.y1, p.y2) for p in segs)
        fig, ax = plt.subplots(figsize=(10, 10 * (cy1 - cy0) / (cx1 - cx0)))
        for p in segs:
            ax.plot([p.x1, p.x2], [p.y1, p.y2], 'k-', lw=0.6)
        ax.set_aspect('equal'); ax.axis('off')
        fig.savefig(os.path.join(OUT, 'tida_%s_table.png' % ext), dpi=160); plt.close(fig)
    print('\nRenders written to %s' % OUT)
