"""Build the self-contained order / design-reference / assembly package of the charger CR and EIB boards.

Usage (from hardware/charger_evm_r8, miniforge Python with markdown-it-py):
    python gen/export_package.py <date> [--fab-date <fab package date>] [--bom <bom folder>]
Writes export/<date>/ and export/charger_r8_package_<date>.zip. The script copies the fab outputs and the BOM set,
re-plots the PCB layers and a reference placement drawing, renders the PCBs in 3D with kicad-cli, and prints every
Markdown document and image set to PDF with headless Microsoft Edge (CommonMark + tables via markdown-it-py). It reads
the repository only (the pcbnew placement plot loads the board in memory and never saves it). Re-run it after any
change to a source. A build from a working tree with uncommitted changes is stamped as such in every page header and
in INDEX.
"""
import argparse
import csv
import datetime
import glob
import html
import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

from markdown_it import MarkdownIt

HERE = os.path.dirname(os.path.abspath(__file__))
BD = os.path.dirname(HERE)                                   # hardware/charger_evm_r8
REPO = os.path.dirname(os.path.dirname(BD))
KICAD = os.environ.get("KICAD_CLI", r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe")
PCBNEW_PY = os.path.join(REPO, "tools", "pcb", ".venv", "Scripts", "python.exe")
EDGE = next((p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                         r"C:\Program Files\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)
DESIGN_DOC = os.path.join(REPO, "docs", "charger_bq25798_wiring_design_2026-11-05.md")
DECK = os.path.join(REPO, "docs", "slides", "charger_path_redesign_CR_EIB_2026-11-17.pdf")

CSS = """
@page { size: Letter; margin: 13mm 12mm 13mm 12mm; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 9.5pt; line-height: 1.35; color: #111; }
h1 { font-size: 17pt; border-bottom: 2px solid #333; padding-bottom: 3px; }
h2 { font-size: 13.5pt; border-bottom: 1px solid #999; margin-top: 18px; }
h3 { font-size: 11.5pt; } h4 { font-size: 10pt; }
table { border-collapse: collapse; margin: 6px 0; width: 100%; font-size: 7.6pt; page-break-inside: auto; }
th, td { border: 1px solid #aaa; padding: 2px 4px; vertical-align: top; overflow-wrap: break-word; word-break: normal; }
th { background: #eee; } tr { page-break-inside: avoid; }
code { font-family: Consolas, monospace; font-size: 8.3pt; background: #f3f3f3; padding: 0 2px; overflow-wrap: break-word; }
pre { background: #f3f3f3; padding: 6px; font-size: 7.8pt; white-space: pre-wrap; overflow-wrap: break-word; }
img { max-width: 100%; max-height: 228mm; width: auto; height: auto; page-break-inside: avoid; }
.hdr { font-size: 7.5pt; color: #555; border-bottom: 1px solid #ccc; margin-bottom: 8px; }
.fig { break-inside: avoid; page-break-inside: avoid; margin: 8px 0 14px 0; text-align: center; }
.fig img { border: 1px solid #ccc; }
.fig.pb { page-break-before: always; }
.cap { font-size: 8.5pt; color: #333; text-align: left; }
.box { border: 1px solid #888; background: #f6f6f6; padding: 4px 8px; margin: 6px 0 10px 0; }
"""


def run(args, **kw):
    r = subprocess.run(args, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise SystemExit("FAILED: %s\n%s\n%s" % (" ".join(args), r.stdout[-2000:], r.stderr[-2000:]))
    return r


def git_state():
    """(short commit, list of modified/untracked source paths that the package reads)."""
    rev = run(["git", "-C", BD, "rev-parse", "--short", "HEAD"]).stdout.strip()
    paths = [".", os.path.relpath(DESIGN_DOC, BD), os.path.relpath(DECK, BD)]
    st = subprocess.run(["git", "-C", BD, "status", "--porcelain", "--"] + paths, capture_output=True,
                        text=True).stdout.splitlines()
    dirty = [ln[3:].strip('"') for ln in st]
    dirty = [d for d in dirty if "/export/" not in d and "RTbackup" not in d and not d.endswith("guide.json")]
    return rev, dirty


def uri(path):
    return "file:///" + os.path.abspath(path).replace("\\", "/")


def html_to_pdf(html_text, out_pdf, tmpdir):
    h = os.path.join(tmpdir, "doc_%08d.html" % (abs(hash(out_pdf)) % 10 ** 8))
    with open(h, "w", encoding="utf-8") as f:
        f.write(html_text)
    os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
    if os.path.exists(out_pdf):
        os.remove(out_pdf)
    run([EDGE, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
         "--virtual-time-budget=30000", "--print-to-pdf=" + out_pdf, uri(h)])
    if not os.path.exists(out_pdf) or os.path.getsize(out_pdf) < 1000:
        raise SystemExit("PDF not written: " + out_pdf)


def page(title, body, base_dir, note):
    return ('<!doctype html><html><head><meta charset="utf-8"><base href="%s/"><title>%s</title><style>%s</style>'
            '</head><body><div class="hdr">%s</div>%s</body></html>' % (uri(base_dir), html.escape(title), CSS, note,
                                                                        body))


MD = MarkdownIt("commonmark", {"html": True}).enable("table").enable("strikethrough")
IMG_EXT = (".png", ".jpg", ".jpeg", ".svg", ".gif")


class Converter:
    """Markdown to HTML with package-aware links and figures; collects render warnings."""

    def __init__(self, link_map, warnings):
        self.link_map = link_map          # absolute source path (normcase) -> package-relative name
        self.warnings = warnings

    def convert(self, md_path, text):
        base = os.path.dirname(md_path)
        body = MD.render(text)
        # 1. links to images become embedded figures after their paragraph
        def para(m):
            p = m.group(0)
            imgs = []

            def lnk(mm):
                href, label = mm.group(1), mm.group(2)
                if href.lower().split("#")[0].endswith(IMG_EXT) and not href.startswith("http"):
                    f = os.path.normpath(os.path.join(base, html.unescape(href)))
                    if os.path.exists(f):
                        imgs.append((f, re.sub("<[^>]+>", "", label)))
                        return label
                return mm.group(0)
            p = re.sub(r'<a href="([^"]+)">(.*?)</a>', lnk, p)
            for f, lab in imgs:
                p += '<div class="fig"><img src="%s"><div class="cap">%s</div></div>' % (uri(f), html.escape(lab))
            return p
        body = re.sub(r"<p>.*?</p>", para, body, flags=re.S)
        # 2. other relative links: to a packaged document -> its package name; otherwise drop the dead link

        def other(mm):
            href, label = mm.group(1), mm.group(2)
            if re.match(r"^(https?|mailto):", href) or href.startswith("#"):
                return mm.group(0)
            f = os.path.normcase(os.path.normpath(os.path.join(base, html.unescape(href.split("#")[0]))))
            if f in self.link_map:
                return '%s <i>[in this package: %s]</i>' % (label, html.escape(self.link_map[f]))
            return label
        body = re.sub(r'<a href="([^"]+)">(.*?)</a>', other, body, flags=re.S)
        # 3. images that do not exist
        for src in re.findall(r'<img src="([^"]+)"', body):
            if src.startswith("file:///"):
                p = src[8:].replace("/", os.sep)
            else:
                p = os.path.join(base, html.unescape(src))
            if not os.path.exists(html.unescape(p).replace("%20", " ")):
                self.warnings.append("%s: missing image %s" % (os.path.basename(md_path), src))
        # 4. break points in code spans after / and _
        body = re.sub(r"<code>(.*?)</code>", lambda m: "<code>" + re.sub(r"([/_.])", r"\1<wbr>", m.group(1)) + "</code>",
                      body, flags=re.S)
        # 5. gates: identifiers lost and stray '**'
        plain = html.unescape(re.sub("<[^>]+>", "", body.replace("<wbr>", "")))
        src_ids, out_ids = {}, {}
        for t in re.findall(r"[A-Za-z0-9]+_[A-Za-z0-9_]+", text):
            src_ids[t] = src_ids.get(t, 0) + 1
        for t in re.findall(r"[A-Za-z0-9]+_[A-Za-z0-9_]+", plain):
            out_ids[t] = out_ids.get(t, 0) + 1
        lost = [t for t, n in src_ids.items() if out_ids.get(t, 0) < n and not t.endswith((".png", ".md"))]
        if lost:
            self.warnings.append("%s: %d identifiers render fewer times than in the source (e.g. %s)" %
                                 (os.path.basename(md_path), len(lost), ", ".join(lost[:6])))
        if "**" in plain:
            self.warnings.append("%s: %d literal '**' in the rendered text (nested bold in the source)" %
                                 (os.path.basename(md_path), plain.count("**")))
        return body


def images_page(title, intro_html, figs, tail_html=""):
    parts = [intro_html]
    for i, (img, cap, cls) in enumerate(figs):
        # board plots (SVG, true size a few cm) are scaled up to fill the page height
        style = ' style="height: 205mm; max-width: 100%; object-fit: contain;"' if img.lower().endswith(".svg") else ""
        parts.append('<div class="fig %s"><img src="%s"%s><div class="cap">%s</div></div>' % (cls, uri(img), style,
                                                                                             html.escape(cap)))
    parts.append(tail_html)
    return "<h1>%s</h1>%s" % (html.escape(title), "".join(parts))


def render_board(board, outdir):
    """3D renders of one board: top, bottom and two isometric views (PNG)."""
    os.makedirs(outdir, exist_ok=True)
    pcb = os.path.join(BD, board, board + ".kicad_pcb")
    views = [("top", ["--side", "top"]), ("bottom", ["--side", "bottom"]),
             ("isometric top", ["--side", "top", "--rotate", "-45,0,45", "--perspective"]),
             ("isometric bottom", ["--side", "bottom", "--rotate", "-45,0,-45", "--perspective"])]
    out = []
    for name, args in views:
        f = os.path.join(outdir, "%s_%s.png" % (board, name.replace(" ", "_")))
        run([KICAD, "pcb", "render", "--quality", "high", "--width", "2400", "--height", "1300",
             "--background", "opaque", "-o", f] + args + [pcb])
        out.append((f, name))
    return out


LAYERS = {"cr": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu", "F.Silkscreen", "B.Silkscreen", "F.Mask", "B.Mask", "F.Paste"],
          "eib": ["F.Cu", "B.Cu", "F.Silkscreen", "B.Silkscreen", "F.Mask", "B.Mask", "F.Paste"]}
LAYER_NOTE = {"F.Cu": "top copper (L1)", "In1.Cu": "inner copper L2 (solid GND)", "In2.Cu": "inner copper L3",
              "B.Cu": "bottom copper", "F.Silkscreen": "top silkscreen as printed",
              "B.Silkscreen": "bottom silkscreen as printed", "F.Mask": "top solder mask openings",
              "B.Mask": "bottom solder mask openings", "F.Paste": "top paste (stencil apertures)"}


def plot_layers(board, outdir):
    """One SVG per layer, board area only, black and white; bottom layers mirrored (seen from the bottom)."""
    pcb = os.path.join(BD, board, board + ".kicad_pcb")
    figs = []
    for L in LAYERS[board]:
        d = os.path.join(outdir, board, L.replace(".", "_"))
        os.makedirs(d, exist_ok=True)
        args = [KICAD, "pcb", "export", "svg", "--mode-multi", "--layers", L, "--common-layers", "Edge.Cuts",
                "--page-size-mode", "2", "--exclude-drawing-sheet", "--black-and-white", "-o", d + os.sep]
        if L.startswith("B."):
            args.append("--mirror")
        run(args + [pcb])
        svg = glob.glob(os.path.join(d, "*.svg"))[0]
        side = " (viewed from the bottom, mirrored)" if L.startswith("B.") else " (viewed from the top)"
        figs.append((svg, "%s %s: %s%s" % (board.upper(), L, LAYER_NOTE.get(L, ""), side)))
    return figs


def plot_refs(board, outdir):
    r = run([PCBNEW_PY, os.path.join(HERE, "plot_refs.py"), os.path.join(BD, board, board + ".kicad_pcb"), outdir,
             "top"])
    return [ln for ln in r.stdout.splitlines() if ln.endswith(".svg")][-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date")
    ap.add_argument("--fab-date", default=None)
    ap.add_argument("--bom", default="bom_2026-11-14")
    a = ap.parse_args()
    if EDGE is None:
        raise SystemExit("Microsoft Edge or Chrome not found (needed for the PDF print)")
    D, FD = a.date, (a.fab_date or a.date)
    rev, dirty = git_state()
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    revtxt = rev + (" + %d uncommitted source changes (listed in INDEX)" % len(dirty) if dirty else "")
    note = ("Charger retrofit r8 (CR + EIB) package %s &middot; commit %s &middot; printed %s"
            % (D, html.escape(revtxt), stamp))
    root = os.path.join(BD, "export", D)
    if os.path.exists(root):
        shutil.rmtree(root)
    O, R, A = (os.path.join(root, s) for s in ("01_order", "02_design_reference", "03_assembly"))
    tmp = tempfile.mkdtemp(prefix="chg_export_")
    fab = {b: os.path.join(BD, "fab", "%s_%s" % (b, FD)) for b in ("cr", "eib")}
    for b, p in fab.items():
        if not os.path.isdir(p):
            raise SystemExit("missing fab package " + p)
    made, warnings = [], []

    # package names of the documents that other documents link to
    N = {
        "overview": "02_design_reference/01_design_overview.pdf",
        "readme": "02_design_reference/06_design_review_guide_README.pdf",
        "design": "02_design_reference/07_design_record_charger_bq25798_wiring_design.pdf",
        "layout": "02_design_reference/08_layout_decisions.pdf",
    }
    link_map = {os.path.normcase(os.path.normpath(k)): v for k, v in {
        os.path.join(BD, "OVERVIEW.md"): N["overview"], os.path.join(BD, "README.md"): N["readme"],
        DESIGN_DOC: N["design"], os.path.join(BD, "LAYOUT_DECISIONS.md"): N["layout"],
        os.path.join(BD, "evm_rework", "EVM_REWORK_GUIDE.md"): "03_assembly/EVM_rework_guide.pdf",
        os.path.join(BD, "BOM_CHECK_2026-11-17.md"): "02_design_reference/09_bom_check_2026-11-17.pdf",
        os.path.join(BD, "FOOTPRINT_CHECK_2026-11-17.md"): "02_design_reference/10_footprint_check_2026-11-17.pdf",
        os.path.join(BD, "DATASHEET_RECHECK_2026-11-17.md"): "02_design_reference/11_datasheet_recheck_2026-11-17.pdf",
        os.path.join(BD, a.bom, "README.md"): "01_order/bom/BOM_README.pdf",
    }.items()}
    conv = Converter(link_map, warnings)

    def cp(src, dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        made.append(dst)

    def pdf_md(src, dst, prefix_html="", subs=()):
        text = open(src, encoding="utf-8-sig").read()
        for old, new in subs:
            if old not in text:
                warnings.append("%s: substitution target not found: %r" % (os.path.basename(src), old[:60]))
            text = text.replace(old, new)
        body = prefix_html + conv.convert(src, text)
        html_to_pdf(page(os.path.basename(src), body, os.path.dirname(src), note), dst, tmp)
        made.append(dst)

    def pdf_images(title, intro, figs, dst, tail=""):
        html_to_pdf(page(title, images_page(title, intro, figs, tail), tmp, note), dst, tmp)
        made.append(dst)

    renders = {b: render_board(b, os.path.join(tmp, "render")) for b in ("cr", "eib")}

    # ---- 01 order
    fabmap = ('<div class="box"><b>Package file map.</b> This README was written for the fab folder '
              '<code>fab/{b}_{FD}/</code>. In this package: <code>kikit_oshpark/gerbers.zip</code> is '
              '<code>01_order/pcb/{b}_oshpark_gerbers.zip</code>; <code>{b}_gerbers_drill.zip</code> is '
              '<code>01_order/pcb/{b}_gerbers_drill_any_fab.zip</code> (it now also holds the drill maps); '
              '<code>gerbers/{b}-F_Paste.gtp</code> is <code>01_order/stencil/</code>; <code>assembly/</code> files '
              'are in <code>03_assembly/</code> (the guide as <code>{b}_assembly_guide.pdf</code>); '
              '<code>docs/{b}-schematic.pdf</code> and <code>docs/{b}-pcb.pdf</code> are '
              '<code>02_design_reference/03_{b}_schematic.pdf</code> and <code>04_{b}_pcb_layers.pdf</code>; '
              '<code>docs/{b}.step</code> is <code>02_design_reference/3d/</code>; '
              '<code>bom_2026-11-14/</code> is <code>01_order/bom/</code>; <code>LAYOUT_DECISIONS.md</code> is '
              '<code>02_design_reference/08_layout_decisions.pdf</code>. The KiKit JLCPCB/PCBWay folders, '
              '<code>reports/</code> and <code>tools/pcb/fab_rules</code> are not in the package; see INDEX section 2.'
              '</div>')
    for b in ("cr", "eib"):
        cp(os.path.join(fab[b], "kikit_oshpark", "gerbers.zip"), os.path.join(O, "pcb", "%s_oshpark_gerbers.zip" % b))
        anyzip = os.path.join(O, "pcb", "%s_gerbers_drill_any_fab.zip" % b)
        os.makedirs(os.path.dirname(anyzip), exist_ok=True)
        with zipfile.ZipFile(anyzip, "w", zipfile.ZIP_DEFLATED) as zf:
            for sub in ("gerbers", "drill"):
                for f in sorted(glob.glob(os.path.join(fab[b], sub, "*"))):
                    zf.write(f, os.path.basename(f))
        made.append(anyzip)
        cp(os.path.join(fab[b], "gerbers", "%s-F_Paste.gtp" % b), os.path.join(O, "stencil", "%s-F_Paste.gtp" % b))
        pdf_md(os.path.join(fab[b], "README.md"), os.path.join(O, "pcb", "%s_fab_package_README.pdf" % b),
               fabmap.format(b=b, FD=FD))
    bom = os.path.join(BD, a.bom)
    for f in sorted(glob.glob(os.path.join(bom, "*.csv"))):
        cp(f, os.path.join(O, "bom", os.path.basename(f)))
    bommap = ('<div class="box"><b>Package file map.</b> In this README, <code>%s/</code> is <code>01_order/bom/</code>; '
              'the stencil and PCB upload paths named in <code>cr_bom.csv</code> and <code>eib_bom.csv</code> '
              '(<code>fab/*_2026-11-14/...</code>) are <code>01_order/stencil/</code> and <code>01_order/pcb/</code> '
              'of this package (the %s fab files; copper, mask, paste and drill are identical to 2026-11-14). '
              'Files of other BOM folders (for example <code>bom_2026-11-13/README.md</code>) are not in the package.'
              '</div>' % (a.bom, FD))
    pdf_md(os.path.join(bom, "README.md"), os.path.join(O, "bom", "BOM_README.pdf"), bommap)

    # ---- 02 design reference
    cr_iso = [f for f, v in renders["cr"] if v == "isometric top"][0]
    overview_subs = []
    ov = open(os.path.join(BD, "OVERVIEW.md"), encoding="utf-8").read()
    mm = re.search(r"```mermaid.*?```", ov, re.S)
    if mm:
        overview_subs.append((mm.group(0), "![Figure 1 (block diagram, rendered)](figures/fig2_1_block_diagram.png)"))
    overview_subs.append(("figures/cr_routed_2026-11-13/3d_iso.png", uri(cr_iso)))
    pdf_md(os.path.join(BD, "OVERVIEW.md"), os.path.join(R, "01_design_overview.pdf"), subs=overview_subs)
    cp(DECK, os.path.join(R, "02_lab_update_slides_charger_path_redesign.pdf"))
    layer_figs = {}
    for b in ("cr", "eib"):
        cp(os.path.join(fab[b], "docs", "%s-schematic.pdf" % b), os.path.join(R, "03_%s_schematic.pdf" % b))
        cp(os.path.join(fab[b], "docs", "%s.step" % b), os.path.join(R, "3d", "%s.step" % b))
        figs = plot_layers(b, os.path.join(tmp, "layers"))
        refs = plot_refs(b, os.path.join(tmp, "refs"))
        layer_figs[b] = refs
        allf = [(refs, "%s reference placement, top side: courtyards, pads and every reference designator" % b.upper(),
                 "")] + [(f, c, "pb") for f, c in figs]
        pdf_images("%s PCB layers" % b.upper(),
                   "<p>Each page shows one layer of the board as ordered (fab files %s), board area only, scaled to "
                   "the page, with the board outline. Bottom layers are drawn as seen from the bottom.</p>" % FD,
                   allf, os.path.join(R, "04_%s_pcb_layers.pdf" % b))
    figs = []
    for b in ("cr", "eib"):
        for f, v in renders[b]:
            figs.append((f, "%s, %s view (KiCad 3D render of the board as ordered; parts without a 3D model are not "
                            "shown)" % (b.upper(), v), ""))
    pdf_images("PCB renders: CR and EIB", "<p>3D renders of the boards as ordered (fab files %s).</p>" % FD, figs,
               os.path.join(R, "05_pcb_renders.pdf"))
    pdf_md(os.path.join(BD, "README.md"), os.path.join(R, "06_design_review_guide_README.pdf"))
    pdf_md(DESIGN_DOC, os.path.join(R, "07_design_record_charger_bq25798_wiring_design.pdf"))
    pdf_md(os.path.join(BD, "LAYOUT_DECISIONS.md"), os.path.join(R, "08_layout_decisions.pdf"))
    for i, name in ((9, "BOM_CHECK_2026-11-17.md"), (10, "FOOTPRINT_CHECK_2026-11-17.md"),
                    (11, "DATASHEET_RECHECK_2026-11-17.md")):
        if os.path.exists(os.path.join(BD, name)):
            pdf_md(os.path.join(BD, name), os.path.join(R, "%02d_%s.pdf" % (i, name[:-3].lower())))

    # ---- 03 assembly
    for b in ("cr", "eib"):
        g = os.path.join(fab[b], "assembly", "guide")
        pages = sorted(glob.glob(os.path.join(g, "%s_guide_*.png" % b)),
                       key=lambda p: int(re.findall(r"(\d+)\.png$", p)[0]))
        figs = [(os.path.join(g, "%s_overview.png" % b),
                 "%s top: the silkscreen as printed. Parts labelled here sit at their own pads; every other top-side "
                 "SMD part is shown on the guide pages that follow." % b.upper(), "")]
        figs += [(p, "%s guide page %s" % (b.upper(), re.findall(r"(\d+)\.png$", p)[0]), "pb") for p in pages]
        figs += [(layer_figs[b], "%s reference placement (every reference designator, top side)" % b.upper(), "pb")]
        intro = ("<p>The silkscreen labels only the parts whose reference sits at the part (D-97). Each guide page "
                 "outlines a set of the other top-side SMD parts and tags each with its reference and value. The "
                 "last figure places every reference designator. The part table follows the figures.</p>")
        tail = '<div style="page-break-before: always"></div>' + conv.convert(
            os.path.join(g, "README.md"), open(os.path.join(g, "README.md"), encoding="utf-8").read())
        pdf_images("%s assembly guide" % b.upper(), intro, figs, os.path.join(A, "%s_assembly_guide.pdf" % b), tail)
        for f in ("%s_ibom.html" % b, "%s-pos.csv" % b):
            cp(os.path.join(fab[b], "assembly", f), os.path.join(A, f))
        # fab BOM: strip the "?" artefact of the KiCad export on letter-suffix references
        src = open(os.path.join(fab[b], "assembly", "%s-bom.csv" % b), encoding="utf-8").read()
        dst = os.path.join(A, "%s-bom.csv" % b)
        with open(dst, "w", encoding="utf-8", newline="") as fh:
            fh.write(re.sub(r"([A-Za-z]+\d+[A-Za-z]+)\?", r"\1", src))
        made.append(dst)
        for p in [os.path.join(g, "%s_overview.png" % b)] + pages + [os.path.join(g, "README.md")]:
            cp(p, os.path.join(A, "guide_images", os.path.basename(p) if not p.endswith("README.md")
                               else "%s_guide_README.md" % b))
        refpdf = os.path.join(A, "%s_placement_refs.pdf" % b)
        pdf_images("%s reference placement" % b.upper(), "", [(layer_figs[b], "%s top side: every reference "
                                                               "designator at its part" % b.upper(), "")], refpdf)
    pdf_md(os.path.join(BD, "evm_rework", "EVM_REWORK_GUIDE.md"), os.path.join(A, "EVM_rework_guide.pdf"))

    # ---- index
    txt = open(os.path.join(HERE, "export_package_index.md"), encoding="utf-8").read()
    txt = txt.replace("{DATE}", D).replace("{FD}", FD).replace("{REV}", rev).replace("{BOM}", a.bom) \
        .replace("{STAMP}", stamp)
    if dirty:
        txt = txt.replace("{DIRTY}", "**Note:** the build used a working tree with %d uncommitted source changes "
                          "(Appendix B); the commit alone does not reproduce this package." % len(dirty))
    else:
        txt = txt.replace("{DIRTY}", "The working tree had no uncommitted source changes.")
    rows = ["| `%s` | %.0f kB |" % (os.path.relpath(p, root).replace("\\", "/"), os.path.getsize(p) / 1024.0)
            for p in sorted(made)]
    txt += "\n## Appendix A: file list\n\n| File | Size |\n|---|---|\n" + "\n".join(rows) + "\n"
    if dirty:
        txt += "\n## Appendix B: uncommitted source changes at build time\n\n" + "\n".join(
            "- `%s`" % d for d in dirty) + "\n"
    if warnings:
        txt += "\n## Appendix C: render notes\n\n" + "\n".join("- %s" % w for w in warnings) + "\n"
    with open(os.path.join(root, "INDEX.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    html_to_pdf(page("INDEX", conv.convert(os.path.join(root, "INDEX.md"), txt), root, note),
                os.path.join(root, "INDEX.pdf"), tmp)

    # ---- zip
    z = os.path.join(BD, "export", "charger_r8_package_%s.zip" % D)
    if os.path.exists(z):
        os.remove(z)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for dp, dn, fn in os.walk(root):
            for f in fn:
                p = os.path.join(dp, f)
                zf.write(p, os.path.join("charger_r8_package_%s" % D, os.path.relpath(p, root)))
    shutil.rmtree(tmp, ignore_errors=True)
    for w in warnings:
        print("NOTE", w)
    print("wrote %s (%d files) and %s (%.1f MB); commit %s" % (root, len(made) + 2, z, os.path.getsize(z) / 1e6,
                                                               revtxt))


if __name__ == "__main__":
    main()
