"""BQ25798EVM (BMS034A/B) geometry from the vector layer figures of TI SLUUCB5E (Figs 4-1 .. 4-4, pp. 15-18).

Usage (from any folder; the PDF is an argument, never imported):
    python -I evm_geom.py <path to sluucb5e.pdf>

Method
------
The four layer figures are vector Form XObjects (no raster images; `pdfimages -list` is empty). Every pad, drill,
silkscreen and mechanical-layer stroke is a PDF path, so positions are extracted from the path coordinates, not read off
a render. The figure-to-board scale is calibrated from part pitches that are fixed by the parts themselves:
  x: J9 (3M N2510 5x2 shrouded header, 2.54 mm) and J8 (Molex 4x1, 2.54 mm) hole pitch along x
  y: J9 row pitch and the 2-pin JP22..JP29 pin pitch along y (2.54 mm)
The export is very slightly anisotropic (x and y scales differ by 0.31 %), so each axis is scaled separately.
EVM frame: origin = lower-left corner of the board outline in TOP VIEW, +x right, +y up, mm.
The bottom-layer figure (p. 18) is drawn mirrored (viewed from below) and is un-mirrored here.
"""
import sys, re, math, json
from pypdf import PdfReader

PDF = sys.argv[1]
R = PdfReader(PDF)


def form_paths(pageno):
    """Return painted paths of the page's single figure Form XObject, in form units (pt), y up."""
    pg = R.pages[pageno - 1]
    form = list(pg['/Resources']['/XObject'].get_object().values())[0].get_object()
    data = form.get_data().decode('latin1')
    toks = re.findall(r'/[^\s/\[\]()<>]+|-?\d*\.?\d+(?:[eE][-+]?\d+)?|[A-Za-z*\'"]+|\[|\]|\([^)]*\)|<[^>]*>', data)

    def mul(a, b):
        return [a[0]*b[0] + a[1]*b[2], a[0]*b[1] + a[1]*b[3], a[2]*b[0] + a[3]*b[2], a[2]*b[1] + a[3]*b[3],
                a[4]*b[0] + a[5]*b[2] + b[4], a[4]*b[1] + a[5]*b[3] + b[5]]
    ctm = [1, 0, 0, 1, 0, 0]; st = []; fill = (0,); stroke = (0,); lw = 1.0; ops = []; cur = []; sub = None; out = []
    tx = lambda m, x, y: (m[0]*x + m[2]*y + m[4], m[1]*x + m[3]*y + m[5])
    for t in toks:
        if t[0] in '-.0123456789':
            ops.append(float(t)); continue
        if t[0] in '/[]<(':
            ops.append(t); continue
        if t == 'q': st.append((ctm[:], fill, stroke, lw))
        elif t == 'Q': ctm, fill, stroke, lw = st.pop()
        elif t == 'cm': ctm = mul(ops[-6:], ctm)
        elif t == 'w': lw = ops[-1]
        elif t in ('scn', 'sc', 'rg'): fill = tuple(round(v, 3) for v in ops if isinstance(v, float))[-3:]
        elif t in ('SCN', 'SC', 'RG'): stroke = tuple(round(v, 3) for v in ops if isinstance(v, float))[-3:]
        elif t == 'm': sub = [tx(ctm, ops[-2], ops[-1])]; cur.append(sub)
        elif t == 'l': sub.append(tx(ctm, ops[-2], ops[-1]))
        elif t == 'c': o = ops[-6:]; sub += [tx(ctm, o[0], o[1]), tx(ctm, o[2], o[3]), tx(ctm, o[4], o[5])]
        elif t == 're':
            x, y, w, h = ops[-4:]
            sub = [tx(ctm, x, y), tx(ctm, x + w, y), tx(ctm, x + w, y + h), tx(ctm, x, y + h)]; cur.append(sub)
        elif t in ('S', 's', 'f', 'F', 'f*', 'B', 'B*', 'b', 'b*', 'n'):
            pts = [p for s in cur for p in s]
            if pts and t != 'n':
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                out.append(dict(op=t, fill=fill[0] if fill else 0, stroke=stroke[0] if stroke else 0,
                                lw=lw * abs(ctm[0]), bbox=(min(xs), min(ys), max(xs), max(ys))))
            cur = []; sub = None
        ops = []
    return out


top, bot = form_paths(15), form_paths(18)
holes = lambda P: [p for p in P if p['op'] == 'f' and p['fill'] == 0.824]
ctr = lambda p: ((p['bbox'][0] + p['bbox'][2]) / 2, (p['bbox'][1] + p['bbox'][3]) / 2)

# ---- board outline (first four strokes of each figure, 1.03 pt lines)
ol = [p['bbox'] for p in top[:4]]
L = min(b[0] for b in ol); Rr = max(b[2] for b in ol); B = min(b[1] for b in ol); T = max(b[3] for b in ol)
olb = [p['bbox'] for p in bot[:6] if p['lw'] > 1.0]
Lb = min(b[0] for b in olb); Rb = max(b[2] for b in olb); Bb = min(b[1] for b in olb); Tb = max(b[3] for b in olb)

# ---- scale calibration from hole pitches (form pt per mm)
def row(P, y_lo, y_hi, x_lo, x_hi):
    return sorted(ctr(p) for p in holes(P) if y_lo < ctr(p)[1] < y_hi and x_lo < ctr(p)[0] < x_hi)
# J9 = 5x2 at form x 85..131, y 75..89 ; J8 = 4x1 at form x 65..100, y 49..53 (located from the render, see report)
j9 = sorted(set((round(x, 3), round(y, 3)) for x, y in row(top, 74, 90, 85, 131)))
j9x = sorted(set(x for x, _ in j9)); j9y = sorted(set(y for _, y in j9))
j8 = sorted(set(round(x, 3) for x, _ in row(top, 49, 53, 65, 100)))
SX = (j9x[-1] - j9x[0]) / (len(j9x) - 1) / 2.54
SX8 = (j8[-1] - j8[0]) / (len(j8) - 1) / 2.54
SY = (j9y[-1] - j9y[0]) / (len(j9y) - 1) / 2.54
jp = sorted(set(round(ctr(p)[1], 3) for p in holes(top) if 350 < ctr(p)[1] < 370 and 190 < ctr(p)[0] < 306))
SYJP = (jp[-1] - jp[0]) / 2.54
print("SCALE  J9 x pitch -> %.6f pt/mm (n=%d holes in x), J8 x pitch -> %.6f pt/mm (n=%d)" % (SX, len(j9x), SX8, len(j8)))
print("SCALE  J9 y pitch -> %.6f pt/mm, JP22-JP29 2-pin pitch -> %.6f pt/mm ; anisotropy x/y = %.5f" % (SY, SYJP, SX / SY))
W_mm = (Rr - L) / SX; H_mm = (T - B) / SY
print("OUTLINE top figure  %.3f x %.3f mm (= %.1f x %.1f mil)" % (W_mm, H_mm, W_mm / 0.0254, H_mm / 0.0254))
print("OUTLINE bottom fig  %.3f x %.3f mm" % ((Rb - Lb) / SX, (Tb - Bb) / SY))
mm_t = lambda x, y: ((x - L) / SX, (y - B) / SY)
mm_b = lambda x, y: ((Rb - x) / SX, (y - Bb) / SY)   # p.18 is mirrored

# ---- drill census (each hole is drawn on two passes in the composite figure; count unique centres)
cen = {}
for p in holes(top):
    d = round((p['bbox'][2] - p['bbox'][0]) / SX, 2)
    cen.setdefault(d, set()).add(tuple(round(v, 2) for v in ctr(p)))
print("DRILLS (top figure, unique centres): " + ", ".join("%.2f mm x %d" % (d, len(s)) for d, s in sorted(cen.items())))
print("       largest drill = %.2f mm" % max(cen))

# ---- named features: (approximate mm from the silkscreen read, snapped to the nearest pad / circle centre)
def snap(P, mmf, x, y, kind):
    best = None
    for p in P:
        b = p['bbox']; w = (b[2] - b[0]) / SX
        ok = {'th': p['op'] == 'f' and p['fill'] == 0.824 and 0.9 < w < 1.3,
              'tp_smt': p['op'] == 'f*' and p['fill'] == 0.848 and 3 < w < 6,
              'fid': p['op'] == 'f*' and p['fill'] == 0.848 and 0.95 < w < 1.05,
              'bump': p['op'] == 'S' and 11 < w < 12}[kind]
        if not ok: continue
        cx, cy = mmf(*ctr(p)); d = math.hypot(cx - x, cy - y)
        if best is None or d < best[0]: best = (d, cx, cy, w)
    return best

FEAT = [  # name, approx x, approx y, kind, note
    ("J1 pin VIN1 (round)", 6.6, 50.8, 'th', "ED120/2DS; silkscreen VIN1"),
    ("J1 pin PGND (square)", 6.6, 55.9, 'th', "silkscreen PGND"),
    ("J5 pin BATTERY (square)", 82.5, 24.2, 'th', "ED120/3DS"),
    ("J5 pin BATP", 82.5, 29.3, 'th', "SNS_BATP / EXT_BATP"),
    ("J5 pin PGND", 82.5, 34.4, 'th', ""),
    ("J7 pin EXT_TS (square)", 62.9, 6.2, 'th', "Molex 0393570002, 3.5 mm"),
    ("J7 pin AGND", 66.4, 6.2, 'th', ""),
    ("J8 pin 1 GND (square)", 15.5, 6.0, 'th', "Molex 0022053041 R/A"),
    ("J8 pin 2 SCL", 18.0, 6.0, 'th', ""),
    ("J8 pin 3 SDA", 20.6, 6.0, 'th', ""),
    ("J8 pin 4 PULLUP via R37", 23.1, 6.0, 'th', ""),
    ("TP27 REGN", 26.7, 80.0, 'th', ""),
    ("TP33 ILIM_HIZ", 80.0, 63.5, 'th', ""),
    ("TP36 /CE", 55.9, 19.7, 'th', ""),
    ("TP35 TS", 59.7, 19.7, 'th', ""),
    ("TP38 STAT", 66.0, 59.7, 'th', ""),
    ("TP41 PULLUP", 30.5, 21.6, 'th', ""),
    ("TP49 AGND (SMT pad centre)", 83.4, 79.1, 'tp_smt', "Keystone 5016"),
    ("JP12 pin 1 REGN (square)", 39.4, 13.7, 'th', ""),
    ("JP12 pin 2 TS network", 39.4, 11.2, 'th', ""),
    ("JP13 pin 1 REGN (square)", 67.4, 67.3, 'th', ""),
    ("JP13 pin 2 to R20", 67.4, 64.8, 'th', ""),
    ("JP14 pin 1 REGN (square)", 71.4, 67.3, 'th', ""),
    ("JP14 pin 2 to R21", 71.4, 64.8, 'th', ""),
    ("JP17 pin 1 /CE (square)", 54.6, 26.8, 'th', ""),
    ("JP17 pin 2 AGND", 54.6, 24.3, 'th', ""),
    ("JP21 pin 1 ILIM_HIZ (square, LOWER)", 75.3, 64.8, 'th', ""),
    ("JP21 pin 2 AGND (round, UPPER)", 75.3, 67.3, 'th', ""),
    ("FID top-left", 2.3, 86.6, 'fid', ""), ("FID top-right", 86.6, 86.6, 'fid', ""), ("FID bottom-left", 2.3, 2.3, 'fid', ""),
]
pos = {}
print("\nFEATURES (EVM frame, mm)        x        y     snap_err  size")
for name, x, y, kind, note in FEAT:
    d, cx, cy, w = snap(top, mm_t, x, y, kind)
    pos[name] = (cx, cy)
    print("  %-36s %7.3f  %7.3f   %5.3f   %5.3f  %s" % (name, cx, cy, d, w, note))
print("BUMPON outlines (bottom figure, un-mirrored):")
for x, y in ((7.6, 7.6), (7.6, 81.3), (81.3, 7.6), (81.3, 81.3)):
    d, cx, cy, w = snap(bot, mm_b, x, y, 'bump')
    print("  centre (%.3f, %.3f) drawn dia %.3f mm" % (cx, cy, w))
print("FIDUCIALS bottom figure (un-mirrored):")
for x, y in ((2.3, 86.6), (86.6, 86.6), (2.3, 2.3)):
    d, cx, cy, w = snap(bot, mm_b, x, y, 'fid')
    print("  (%.3f, %.3f) dot %.3f mm" % (cx, cy, w))

# ---- round-3 cross-check (r3_calc.py H.22(i): 150-dpi render px, 8.66 px/mm, y down)
# Form -> 150-dpi page px on p.15: px = (fx + 123.0) / 0.48, py = (497.7 - fy) / 0.48 (page placement of the figure)
to_px = lambda xm, ym: ((xm * SX + L + 123.0) / 0.48, (497.7 - (ym * SY + B)) / 0.48)
r3 = {"TP49": ((970, 308), "TP49 AGND (SMT pad centre)"), "TP33": ((941, 441), "TP33 ILIM_HIZ"),
      "JP21 pin 1": ((902, 408), "JP21 pin 1 ILIM_HIZ (square, LOWER)"), "JP14 pin 2": ((869, 432), "JP14 pin 2 to R21"),
      "TP38": ((822, 474), "TP38 STAT"), "TP27": ((490, 300), "TP27 REGN"), "JP12 REGN pin": ((598, 862), "JP12 pin 1 REGN (square)"),
      "TP36": ((740, 812), "TP36 /CE"), "JP17 /CE pin": ((727, 752), "JP17 pin 1 /CE (square)")}
print("\nROUND-3 CHECK  right edge: vector %.1f px vs r3 1017 px; true scale at 150 dpi = %.3f (x) / %.3f (y) px/mm vs r3 8.66"
      % (to_px(W_mm, 0)[0], SX * 150 / 72, SY * 150 / 72))
for k, ((px, py), nm) in r3.items():
    vx, vy = to_px(*pos[nm])
    print("  %-14s r3 (%4d,%4d)  vector (%6.1f,%6.1f)  delta (%+5.1f,%+5.1f) px = (%+5.2f,%+5.2f) mm"
          % (k, px, py, vx, vy, px - vx, py - vy, (px - vx) / (SX * 150 / 72), -(py - vy) / (SY * 150 / 72)))

# ---- straight distances of the r6 EIB row recomputed in mm (same placement rule as r3: column 7 mm off the right edge,
#      E3 5 mm above TP33, rows 2.54 mm apart downward), with the corrected scale and the corrected JP21 pin 1
x_pad = W_mm + 7.0; yE3 = pos["TP33 ILIM_HIZ"][1] + 5.0
order = ["E8", None, "E3", "E4", "E2", None, "E7", None, "E1", None, "E5", "E6"]
tgt = {"E8": ["TP49 AGND (SMT pad centre)"], "E3": ["TP33 ILIM_HIZ"], "E4": ["JP21 pin 1 ILIM_HIZ (square, LOWER)"],
       "E2": ["JP14 pin 2 to R21"], "E7": ["TP38 STAT"], "E1": ["JP12 pin 1 REGN (square)", "TP27 REGN"],
       "E5": ["TP36 /CE"], "E6": ["JP17 pin 1 /CE (square)"]}
r3_straight = {"E8": 13.5, "E3": 16.5, "E4": 20.3, "E2": 24.1, "E7": 29.5, "E1": 67.3, "E5": 47.7, "E6": 44.3}
r3_max = {"E8": 20, "E3": 25, "E4": 30, "E2": 35, "E7": 40, "E1": 85, "E5": 60, "E6": 60}
print("\nEIB STRAIGHT DISTANCES (r6 placement rule, vector positions): pad column x = %.2f mm, E3 at y = %.2f mm" % (x_pad, yE3))
for i, e in enumerate(order):
    if e is None: continue
    y = yE3 - (i - 2) * 2.54
    d, t = min((math.hypot(x_pad - pos[n][0], y - pos[n][1]), n) for n in tgt[e])
    mx = 5 * math.ceil(d * 1.25 / 5)
    print("  %s row %2d y=%6.2f -> %-38s %5.1f mm (r3 %4.1f, %+4.1f %%); x1.25 rounded-up max %d mm (r3 %d)"
          % (e, i + 1, y, t, d, r3_straight[e], 100 * (d / r3_straight[e] - 1), mx, r3_max[e]))
# the r3 E4 target as r3 drew it (upper JP21 pad = pin 2 AGND)
y4 = yE3 - 1 * 2.54
print("  (E4 to the UPPER JP21 pad, r3's point: %.1f mm)" % math.hypot(x_pad - pos["JP21 pin 2 AGND (round, UPPER)"][0], y4 - pos["JP21 pin 2 AGND (round, UPPER)"][1]))
