"""Render the annotated BQ25798EVM figures of EVM_REWORK_GUIDE.md from the TI user guide SLUUCB5E.

Source: references/TI_BQ25798_design_files/BQ2579xEVM_SLUUCB5E.pdf (TI SLUUCB5E rev E), Figure 4-1 (top layer, p. 15),
Figure 4-4 (bottom layer, p. 18, drawn as viewed from below) and Figure 4-6 (schematic page 2, p. 20).

Coordinates are in the EVM frame of docs/reviews/charger_eval_2026-11-05/round4/work/evm_geometry.md: millimetres, top
view, origin at the lower-left board corner, +x right, +y up. Named test points and jumper pins come from that file's
Table 1 (vector-extracted). The other part centres were read from the 600 dpi renders against a 5 mm grid and are good to
about +-0.5 mm; they only place the markers.

Run with the miniforge Python (numpy, Pillow) and pdftoppm on the PATH:
    python gen_figures.py
Writes img/*.png beside this script. Prints ASCII only.
"""
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PDF = os.path.join(REPO, "references", "TI_BQ25798_design_files", "BQ2579xEVM_SLUUCB5E.pdf")
OUT = os.path.join(HERE, "img")
DPI = 600

# Board outline centre lines in the 600 dpi renders (pixels), measured from the outline strokes.
TOP = dict(cl=1066.0, cr=4069.5, rt=910.5, rb=3924.0, mirror=False)
BOT = dict(cl=1044.5, cr=4050.5, rt=425.5, rb=3439.0, mirror=True)

# Marker classes: colour, legend text
CLS = {
    "remove": ((210, 0, 0), "remove"),
    "fit": ((0, 150, 0), "fit / replace"),
    "jumper": ((0, 90, 220), "move or fit a shunt / link"),
    "insulate": ((230, 120, 0), "desolder or insulate"),
    "point": ((150, 0, 170), "solder point / check point"),
    "hold": ((0, 0, 0), "do not change"),
}

# (label, side, x, y, w, h, class). w/h in mm: rectangle; w = 0: circle of radius h.
ITEMS = [
    # EM1 JP17
    ("EM1 JP17 shunt off, pin 2 clipped", "EM1 JP17", "top", 54.611, 25.53, 3.6, 6.4, "remove"),
    # EM2 R42 -> R272, TP27, TP36, JP12 pin 1
    ("EM2 R42 (remove)", "EM2 R42", "bot", 57.5, 25.5, 2.2, 3.2, "remove"),
    ("TP27 REGN", "TP27 REGN", "top", 26.670, 80.009, 0, 2.2, "point"),
    ("TP36 /CE", "TP36 /CE", "top", 55.874, 19.710, 0, 2.2, "point"),
    ("JP12 pin 1 REGN", "JP12-1 REGN", "top", 39.370, 13.741, 0, 2.0, "point"),
    # EM3 R21, R20, JP13/JP14 pin 1
    ("EM3 R21 -> 0 ohm", "EM3 R21", "bot", 73.8, 63.9, 2.0, 3.2, "fit"),
    ("EM3 R20 (remove)", "EM3 R20", "bot", 69.6, 64.0, 2.0, 3.2, "remove"),
    ("EM3 JP14 shunt off, pin 1 clipped", "EM3 JP14-1", "top", 71.375, 67.309, 0, 2.0, "remove"),
    ("EM3 JP13 pin 1 clipped", "EM3 JP13-1", "top", 67.438, 67.309, 0, 2.0, "remove"),
    ("JP14 pin 2 (E2)", "JP14-2 (E2)", "top", 71.375, 64.769, 0, 1.8, "point"),
    # EM4 R23
    ("EM4 R23 -> 49.9k", "EM4 R23", "bot", 77.6, 65.9, 2.0, 3.2, "fit"),
    # EM5 R256 / C252 on JP21
    ("EM5 R256 + C252 across JP21", "EM5 JP21", "top", 75.312, 66.039, 3.6, 6.4, "fit"),
    ("TP33 ILIM_HIZ", "TP33", "top", 80.011, 63.499, 0, 2.2, "point"),
    ("TP49 AGND", "TP49", "top", 83.440, 79.120, 5.6, 4.2, "point"),
    # EM6 R39 / R40
    ("EM6 R39", "EM6 R39", "bot", 23.8, 19.6, 1.8, 3.0, "remove"),
    ("EM6 R40", "EM6 R40", "bot", 27.5, 19.6, 1.8, 3.0, "remove"),
    # EM7 terminals
    ("EM7 J2", "EM7 J2", "top", 7.104, 27.99, 9.6, 10.6, "insulate"),
    ("EM7 J3", "EM7 J3", "top", 81.99, 46.69, 9.6, 10.6, "insulate"),
    ("EM7 J4", "EM7 J4", "top", 35.61, 81.67, 10.6, 9.6, "insulate"),
    # EM8 JP32
    ("EM8 JP32", "EM8 JP32", "top", 58.5, 67.4, 3.6, 6.2, "remove"),
    # EM9 JP9
    ("EM9 JP9 -> 2-3", "EM9 JP9 -> 2-3", "top", 82.2, 16.6, 8.6, 3.4, "jumper"),
    # EM10 JP1, JP2
    ("EM10 JP1 -> 2-3", "EM10 JP1 -> 2-3", "top", 46.7, 30.25, 3.4, 8.6, "jumper"),
    ("EM10 JP2 -> 2-3", "EM10 JP2 -> 2-3", "top", 37.0, 30.25, 3.4, 8.6, "jumper"),
    # EM11 JP3 link, JP4 shunt
    ("EM11 JP3 20 AWG link", "EM11 JP3 20 AWG link", "top", 20.0, 45.7, 3.4, 6.2, "jumper"),
    ("EM11 JP4 shunt", "EM11 JP4 shunt", "top", 20.0, 36.55, 3.4, 6.2, "jumper"),
    # EM12 JP5
    ("EM12 JP5 18 AWG link", "EM12 JP5 18 AWG link", "top", 66.7, 33.0, 3.4, 6.2, "jumper"),
    # EM13 JP8
    ("EM13 JP8 -> 1-2", "EM13 JP8 -> 1-2", "top", 53.2, 37.1, 8.6, 3.4, "jumper"),
    # EM14 capacitors
    ("EM14 C10-C12 group", "EM14 C10-C12 group", "top", 38.1, 41.8, 8.2, 4.6, "fit"),
    ("EM14 C29-C31", "EM14 C29-C31", "top", 41.0, 46.5, 8.2, 4.6, "fit"),
    # EM15 JP30
    ("EM15 JP30", "EM15 JP30", "top", 3.75, 15.85, 3.4, 6.2, "remove"),
    # EM16 JP6, JP10, JP11
    ("EM16 JP6", "EM16 JP6", "top", 5.0, 70.5, 6.2, 3.4, "remove"),
    ("EM16 JP10", "EM16 JP10", "top", 12.5, 67.95, 3.4, 6.2, "remove"),
    ("EM16 JP11", "EM16 JP11", "top", 5.0, 65.5, 6.2, 3.4, "remove"),
    # EM17 JP7
    ("EM17 JP7", "EM17 JP7", "top", 12.8, 40.75, 3.4, 8.6, "remove"),
    # EM18, EM19 kept
    ("EM18 JP18 keep", "EM18 JP18 keep", "top", 50.5, 12.45, 3.4, 6.2, "hold"),
    ("EM19 JP24 keep", "EM19 JP24 keep", "top", 54.2, 82.45, 3.4, 6.2, "hold"),
]


def render_page(page, tmp):
    stem = os.path.join(tmp, "p%d" % page)
    subprocess.run(["pdftoppm", "-r", str(DPI), "-f", str(page), "-l", str(page), "-png", PDF, stem], check=True)
    for f in os.listdir(tmp):
        if f.startswith("p%d" % page) and f.endswith(".png"):
            return Image.open(os.path.join(tmp, f)).convert("RGB")
    raise RuntimeError("render failed")


def mapper(geo):
    kx = (geo["cr"] - geo["cl"]) / 88.9
    ky = (geo["rb"] - geo["rt"]) / 88.9

    def px(x, y):
        xx = (88.9 - x) if geo["mirror"] else x
        return (geo["cl"] + xx * kx, geo["rb"] - y * ky)
    return px, kx, ky


def font(sz):
    try:
        return ImageFont.truetype("arialbd.ttf", sz)
    except OSError:
        return ImageFont.load_default()


def draw_items(im, geo, side, offset=(0, 0), scale=1.0, use_tag=True, lw=7, fs=40, label=True):
    """Draw every item of one side onto im. offset = (left, top) of im in 600 dpi render pixels, scale = im px per
    600 dpi px. Labels stay inside the image, avoid each other and the markers, and carry a leader line."""
    px, kx, ky = mapper(geo)
    kx *= scale
    ky *= scale
    d = ImageDraw.Draw(im)
    f = font(fs)
    W, H = im.size
    marks = []
    for name, tag, s, x, y, w, h, c in ITEMS:
        if s != side:
            continue
        cx, cy = px(x, y)
        cx = (cx - offset[0]) * scale
        cy = (cy - offset[1]) * scale
        if w == 0:
            hw = hh = h * kx
        else:
            hw, hh = w * kx / 2, h * ky / 2
        if cx + hw < 0 or cy + hh < 0 or cx - hw > W or cy - hh > H:
            continue
        marks.append((name, tag, c, cx, cy, hw, hh, w == 0))
    for name, tag, c, cx, cy, hw, hh, circ in marks:
        col = CLS[c][0]
        if circ:
            d.ellipse((cx - hw, cy - hh, cx + hw, cy + hh), outline=col, width=lw)
        else:
            d.rectangle((cx - hw, cy - hh, cx + hw, cy + hh), outline=col, width=lw)
    if not label:
        return
    mboxes = [(cx - hw, cy - hh, cx + hw, cy + hh) for _, _, _, cx, cy, hw, hh, _ in marks]
    placed = []

    def overlap(a, b):
        return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])
    for name, tag, c, cx, cy, hw, hh, circ in marks:
        col = CLS[c][0]
        txt = tag if use_tag else name
        tb = d.textbbox((0, 0), txt, font=f)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        best = None
        for r in (12, 40, 80, 130, 190, 260):
            for ax, ay in ((1, -1), (-1, -1), (1, 1), (-1, 1), (0, -1), (0, 1), (1, 0), (-1, 0)):
                tx = cx + ax * (hw + r) + (0 if ax > 0 else (-tw if ax < 0 else -tw / 2))
                ty = cy + ay * (hh + r) + (0 if ay > 0 else (-th if ay < 0 else -th / 2))
                box = (tx - 6, ty - 6, tx + tw + 8, ty + th + 10)
                inside = box[0] >= 0 and box[1] >= 0 and box[2] <= W and box[3] <= H
                nclash = sum(overlap(box, b) for b in placed) + sum(overlap(box, b) for b in mboxes)
                score = (0 if inside else 100) + 10 * nclash + r / 100.0
                if best is None or score < best[0]:
                    best = (score, tx, ty, box)
        _, tx, ty, box = best
        tx = min(max(tx, 4), W - tw - 12)
        ty = min(max(ty, 4), H - th - 14)
        box = (tx - 6, ty - 6, tx + tw + 8, ty + th + 10)
        # leader line from the box centre to the marker edge
        bx, by = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        dx, dy = bx - cx, by - cy
        n = max(1e-6, (dx * dx + dy * dy) ** 0.5)
        ex, ey = cx + dx / n * min(hw, hh), cy + dy / n * min(hw, hh)
        if not overlap(box, (cx - hw, cy - hh, cx + hw, cy + hh)):
            d.line((ex, ey, bx, by), fill=col, width=max(2, lw // 2))
        d.rectangle(box, fill=(255, 255, 255), outline=col, width=3)
        d.text((tx, ty - tb[1]), txt, fill=col, font=f)
        placed.append(box)


def grid(im, geo, step=10, fs=34):
    px, kx, ky = mapper(geo)
    d = ImageDraw.Draw(im)
    f = font(fs)
    for m in range(0, 90, step):
        x, _ = px(m, 0)
        _, y = px(0, m)
        d.text((x - 12, geo["rb"] + 18), str(m), fill=(0, 110, 200), font=f)
        d.text((geo["cl"] - 80 if not geo["mirror"] else geo["cr"] + 20, y - 18), str(m), fill=(0, 110, 200), font=f)


def legend_img(fs=40):
    im = Image.new("RGB", (1500, 6 * (fs + 22) + 30), (255, 255, 255))
    d = ImageDraw.Draw(im)
    f = font(fs)
    y = 15
    for c in ("remove", "fit", "jumper", "insulate", "point", "hold"):
        col, txt = CLS[c]
        d.rectangle((20, y, 90, y + fs), outline=col, width=7)
        d.text((110, y - 4), txt, fill=(0, 0, 0), font=f)
        y += fs + 22
    return im


def crop_board(im, geo, pad=70, extra_bottom=80):
    return im.crop((int(geo["cl"] - pad - 60), int(geo["rt"] - pad), int(geo["cr"] + pad + 60),
                    int(geo["rb"] + pad + extra_bottom)))


def window(geo, x0, y0, x1, y1):
    px, _, _ = mapper(geo)
    a = px(x0, y1)
    b = px(x1, y0)
    l, r = sorted((a[0], b[0]))
    return (int(l), int(a[1]), int(r), int(b[1]))


def save(im, name, width=None):
    if width and im.size[0] > width:
        im = im.resize((width, int(im.size[1] * width / im.size[0])), Image.LANCZOS)
    im.save(os.path.join(OUT, name), optimize=True)
    print("wrote", name, im.size)


def zoom(page, geo, side, box_mm, name, fs=44, width=1800, dpi=1200):
    """Render one window of a page at `dpi` (pdftoppm -x/-y/-W/-H) and draw the items on it."""
    win = window(geo, *box_mm)
    k = dpi / DPI
    with tempfile.TemporaryDirectory() as tmp:
        stem = os.path.join(tmp, "z")
        subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page), "-x", str(int(win[0] * k)),
                        "-y", str(int(win[1] * k)), "-W", str(int((win[2] - win[0]) * k)),
                        "-H", str(int((win[3] - win[1]) * k)), "-png", PDF, stem], check=True)
        fn = [x for x in os.listdir(tmp) if x.endswith(".png")][0]
        im = Image.open(os.path.join(tmp, fn)).convert("RGB")
    draw_items(im, geo, side, offset=(win[0], win[1]), scale=k, fs=fs, lw=9)
    save(im, name, width)


def main():
    os.makedirs(OUT, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        top = render_page(15, tmp)
        bot = render_page(18, tmp)
        sch = render_page(20, tmp)

    # Overviews: markers on the full renders, then crop to the board.
    t = top.copy()
    grid(t, TOP)
    tb = (int(TOP["cl"] - 130), int(TOP["rt"] - 70), int(TOP["cr"] + 130), int(TOP["rb"] + 150))
    t = t.crop(tb)
    draw_items(t, TOP, "top", offset=(tb[0], tb[1]), fs=34, lw=6)
    save(t, "fig02_top_overview.png", 2600)

    b = bot.copy()
    grid(b, BOT)
    bb = (int(BOT["cl"] - 130), int(BOT["rt"] - 70), int(BOT["cr"] + 130), int(BOT["rb"] + 150))
    b = b.crop(bb)
    draw_items(b, BOT, "bot", offset=(bb[0], bb[1]), fs=40, lw=7)
    save(b, "fig03_bottom_overview.png", 2600)

    zoom(15, TOP, "top", (60, 56, 88.9, 74), "fig13_ilim_top.png")
    zoom(18, BOT, "bot", (64, 58, 82, 71), "fig10_ilim_bottom.png", width=1200)
    zoom(15, TOP, "top", (30, 8, 64, 32), "fig14_ce_top.png")
    zoom(18, BOT, "bot", (50, 19, 64, 31), "fig11_ce_bottom.png", width=1000)
    zoom(18, BOT, "bot", (18, 14, 33, 25), "fig12_i2c_bottom.png", width=1000)
    zoom(15, TOP, "top", (0, 10, 28, 75), "fig06_left_jumpers_top.png", width=1100)
    zoom(15, TOP, "top", (28, 24, 74, 52), "fig08_centre_top.png")
    zoom(15, TOP, "top", (72, 10, 88.9, 23), "fig09_jp9_top.png", width=1000)
    zoom(15, TOP, "top", (50, 60, 66, 75), "fig07_jp32_top.png", width=1000)
    zoom(15, TOP, "top", (0, 20, 88.9, 89), "fig15_terminals_top.png", width=1800)

    save(legend_img(), "fig01_legend.png")

    # EM2 link geometry: the R42 site (underside, drawn dashed in the top view) against TP27, TP36 and JP12 pin 1.
    with tempfile.TemporaryDirectory() as tmp:
        top2 = render_page(15, tmp)
        sch1 = render_page(19, tmp)
    px, kx, ky = mapper(TOP)
    d = ImageDraw.Draw(top2)
    f = font(44)
    r42 = (57.5, 25.5)
    pts = {"TP27": (26.670, 80.009), "TP36": (55.874, 19.710), "JP12-1": (39.370, 13.741)}

    def dist(a, b):
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
    x, y = px(*r42)
    hw, hh = 1.1 * kx, 1.6 * ky
    d.rectangle((x - hw, y - hh, x + hw, y + hh), outline=(210, 0, 0), width=8)
    tb = d.textbbox((x + hw + 12, y + hh + 10), "R42 site (on the underside)", font=f)
    d.rectangle((tb[0] - 6, tb[1] - 6, tb[2] + 6, tb[3] + 6), fill=(255, 255, 255), outline=(210, 0, 0), width=3)
    d.text((x + hw + 12, y + hh + 10), "R42 site (on the underside)", fill=(210, 0, 0), font=f)
    for (a, b, col, txt) in ((r42, pts["TP27"], (150, 0, 170), "R42 site to TP27: %.1f mm (design: L1 <= 10 mm)"),
                             (pts["TP36"], pts["JP12-1"], (0, 90, 220), "TP36 to JP12-1: %.1f mm (design: L2 <= 15 mm)")):
        A, B = px(*a), px(*b)
        d.line((A[0], A[1], B[0], B[1]), fill=col, width=8)
        mx, my = (A[0] + B[0]) / 2, (A[1] + B[1]) / 2
        t = txt % dist(a, b)
        tw = d.textbbox((0, 0), t, font=f)[2]
        right = px(86.0, 0)[0]
        tx = min(mx + 20, right - tw)
        ty = my + 30
        tb = d.textbbox((tx, ty), t, font=f)
        d.rectangle((tb[0] - 6, tb[1] - 6, tb[2] + 6, tb[3] + 6), fill=(255, 255, 255), outline=col, width=3)
        d.text((tx, ty), t, fill=col, font=f)
    for n, p in pts.items():
        X, Y = px(*p)
        d.ellipse((X - 2.2 * kx, Y - 2.2 * kx, X + 2.2 * kx, Y + 2.2 * kx), outline=(150, 0, 170), width=8)
    win = window(TOP, 18, 6, 88.9, 88)
    save(top2.crop(win), "fig16_em2_link_geometry.png", 1600)
    print("EM2 distances: R42-TP27 %.2f mm, TP36-JP12-1 %.2f mm" % (dist(r42, pts["TP27"]), dist(pts["TP36"], pts["JP12-1"])))

    # EM2 Option 1 (operator choice 2026-11-16): L1 on the underside from the R42 site to the TP27 through-hole tail.
    # Candidate route read off the 1200 dpi bottom render on a 5 mm grid (top-frame mm). It keeps about 1 mm or more
    # from every SMT body and through-hole pad it passes: D5 and the pad at (30.1, 26.9) on the first riser, C34 and
    # R1 on the second riser. The dry fit confirms it.
    route = [(57.1, 25.4), (57.1, 24.2), (32.4, 24.2), (32.4, 41.0), (31.0, 42.0), (31.0, 79.0), (26.67, 80.009)]
    tacks = [(45.0, 24.2), (32.4, 33.0), (31.0, 48.0), (31.0, 62.0), (31.0, 74.0)]
    seg = sum(dist(route[i], route[i + 1]) for i in range(len(route) - 1))
    geo = BOT
    win = window(geo, 22, 18, 62, 84)
    k = 2.0
    with tempfile.TemporaryDirectory() as tmp:
        stem = os.path.join(tmp, "r")
        subprocess.run(["pdftoppm", "-r", "1200", "-f", "18", "-l", "18", "-x", str(int(win[0] * k)),
                        "-y", str(int(win[1] * k)), "-W", str(int((win[2] - win[0]) * k)),
                        "-H", str(int((win[3] - win[1]) * k)), "-png", PDF, stem], check=True)
        fn = [x for x in os.listdir(tmp) if x.endswith(".png")][0]
        rim = Image.open(os.path.join(tmp, fn)).convert("RGB")
    bpx, bkx, bky = mapper(geo)

    def P(p):
        X, Y = bpx(*p)
        return ((X - win[0]) * k, (Y - win[1]) * k)
    d = ImageDraw.Draw(rim)
    f = font(64)
    pts_r = [P(p) for p in route]
    d.line(pts_r, fill=(150, 0, 170), width=16, joint="curve")
    for t in tacks:
        X, Y = P(t)
        d.ellipse((X - 22, Y - 22, X + 22, Y + 22), fill=(230, 120, 0), outline=(0, 0, 0), width=3)
    X, Y = P((57.5, 25.5))
    hw, hh = 1.1 * bkx * k, 1.6 * bky * k
    d.rectangle((X - hw, Y - hh, X + hw, Y + hh), outline=(210, 0, 0), width=12)
    X, Y = P((26.67, 80.009))
    r = 2.2 * bkx * k
    d.ellipse((X - r, Y - r, X + r, Y + r), outline=(150, 0, 170), width=12)
    for (p, txt, col, dx, dy) in (((57.5, 25.5), "R272 on the R42 /CE pad", (210, 0, 0), 60, 40),
                                  ((26.67, 80.009), "TP27 tail (REGN)", (150, 0, 170), -720, 110),
                                  ((40.0, 70.0), "L1 about %.0f mm" % seg, (150, 0, 170), -420, 0)):
        X, Y = P(p)
        tb = d.textbbox((X + dx, Y + dy), txt, font=f)
        d.rectangle((tb[0] - 8, tb[1] - 8, tb[2] + 8, tb[3] + 8), fill=(255, 255, 255), outline=col, width=4)
        d.text((X + dx, Y + dy), txt, fill=col, font=f)
    save(rim, "fig17_em2_l1_route_bottom.png", 1300)
    print("EM2 L1 candidate route: %.1f mm" % seg)

    # Schematic page 1 (Fig 4-5): jumper pin numbers of JP1-JP9 and the VBUS / PMID capacitors.
    w1, h1 = sch1.size
    save(sch1.crop((int(0.06 * w1), int(0.14 * h1), int(0.94 * w1), int(0.83 * h1))), "fig05_schematic_page1.png", 2400)

    # Schematic page 2 (Fig 4-6): ILIM_HIZ set (JP13, JP14, JP21, R20, R21, R23) and /CE (JP17).
    w, h = sch.size
    save(sch.crop((int(0.52 * w), int(0.10 * h), int(0.95 * w), int(0.29 * h))), "fig04_schematic_ilim_ce.png", 1800)


if __name__ == "__main__":
    main()
