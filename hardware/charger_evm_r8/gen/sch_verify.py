"""Gate for a block re-layout of the CR or EIB schematic: connectivity, fields, ERC and PCB parity.

Usage: python sch_verify.py <board> <work dir> [--source <sch>] [--png]

1. Copies the board project (pro, pcb, dru, symbol library, sym-lib-table) into <work dir>.
2. Assembles <work dir>/<board>.kicad_sch from --source (default: the git HEAD schematic of the board)
   and gen/sch_layout/<board>/.
3. Compares the KiCad netlist of the result with the netlist of the source: the same components with the
   same value, footprint, fields, properties, UUID and sheet path; the same net name on every pin.
4. Runs ERC (all severities) and DRC with schematic parity against the unchanged PCB.
5. With --png, renders the sheet to <work dir>/<board>.png and one crop per block to <work dir>/blk_<id>.png.
Exit 0 only when every check passes. Prints a JSON summary.
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sch_blocks as sb  # noqa: E402

BOARD_DIR = os.path.dirname(HERE)


def run(args):
    return subprocess.run(args, capture_output=True, text=True)


def main():
    board, work = sys.argv[1], os.path.abspath(sys.argv[2])
    src = None
    if "--source" in sys.argv:
        src = sys.argv[sys.argv.index("--source") + 1]
    os.makedirs(work, exist_ok=True)
    bd = os.path.join(BOARD_DIR, board)
    for f in os.listdir(bd):
        if f.endswith((".kicad_pro", ".kicad_pcb", ".kicad_dru", ".kicad_sym")) or f == "sym-lib-table" \
                or f == "fp-lib-table" or f.endswith(".pretty"):
            if "RTbackup" in f:
                continue
            s, d = os.path.join(bd, f), os.path.join(work, f)
            if os.path.isdir(s):
                shutil.rmtree(d, ignore_errors=True)
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
    if src is None:
        src = os.path.join(work, "_source.kicad_sch")
        rel = "hardware/charger_evm_r8/%s/%s.kicad_sch" % (board, board)
        r = run(["git", "-C", BOARD_DIR, "show", "HEAD:" + rel])
        if r.returncode != 0:
            raise SystemExit(r.stderr)
        open(src, "w", encoding="utf-8", newline="\n").write(r.stdout)
    out = os.path.join(work, board + ".kicad_sch")
    res = sb.assemble(board, src, out)
    summary = {"assemble_errors": res["errors"], "assemble_warnings": res["warnings"],
               "placed": res["placed"], "parked": res["parked"]}
    ok = not res["errors"]
    # connectivity and fields
    c0, p0 = sb.netlist_of(src)
    c1, p1 = sb.netlist_of(out)
    diffs = []
    for ref in sorted(set(c0) | set(c1)):
        if ref not in c0 or ref not in c1:
            diffs.append("component %s only in %s" % (ref, "source" if ref in c0 else "result"))
            continue
        for d in (c0[ref], c1[ref]):
            d["props"].pop("Sheetfile", None)  # the source file path, not a design property
        for k in ("value", "footprint", "fields", "props", "tstamps", "sheetpath"):
            if c0[ref][k] != c1[ref][k]:
                diffs.append("%s %s: %r -> %r" % (ref, k, c0[ref][k], c1[ref][k]))

    def norm(n):
        return "unconnected" if n.startswith("unconnected-") else n
    for k in sorted(set(p0) | set(p1)):
        a, b = norm(p0.get(k, "<absent>")), norm(p1.get(k, "<absent>"))
        if a != b:
            diffs.append("pin %s.%s: net %s -> %s" % (k[0], k[1], a, b))
    summary["netlist_diffs"] = diffs
    ok = ok and not diffs
    # ERC
    erc = os.path.join(work, "erc.rpt")
    run([sb.KICAD_CLI, "sch", "erc", "--format", "report", "--severity-all", "-o", erc, out])
    txt = open(erc, encoding="utf-8", errors="replace").read() if os.path.exists(erc) else "ERC did not run"
    m = re.search(r"\*\* ERC messages: (\d+)", txt)
    summary["erc_messages"] = int(m.group(1)) if m else -1
    if summary["erc_messages"] != 0:
        summary["erc_excerpt"] = [ln for ln in txt.splitlines() if ln.startswith(("[", "    @"))][:60]
    ok = ok and summary["erc_messages"] == 0
    # DRC with schematic parity against the unchanged PCB
    drc = os.path.join(work, "drc.rpt")
    run([sb.KICAD_CLI, "pcb", "drc", "--format", "report", "--severity-all", "--schematic-parity", "-o", drc,
         os.path.join(work, board + ".kicad_pcb")])
    txt = open(drc, encoding="utf-8", errors="replace").read() if os.path.exists(drc) else ""
    counts = {k: int(v) for v, k in re.findall(r"\*\* Found (\d+) ([A-Za-z ]+?)(?: \*\*|$)", txt, re.M)}
    summary["drc"] = counts
    if any(counts.values()):
        summary["drc_excerpt"] = [ln for ln in txt.splitlines() if ln.startswith("[")][:40]
    ok = ok and bool(counts) and not any(counts.values())
    if "--png" in sys.argv:
        summary["png"] = render(board, work, out)
    summary["PASS"] = ok
    print(json.dumps(summary, indent=1))
    sys.exit(0 if ok else 1)


def render(board, work, sch):
    """Render the sheet with kicad-cli (SVG) and cairosvg; crop each block frame with Pillow."""
    kdir = os.path.dirname(sb.KICAD_CLI)
    if hasattr(os, "add_dll_directory") and os.path.isdir(kdir):
        os.add_dll_directory(kdir)  # KiCad ships cairo-2.dll
        os.environ["PATH"] = kdir + os.pathsep + os.environ.get("PATH", "")
    import cairosvg
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    svgdir = os.path.join(work, "svg")
    shutil.rmtree(svgdir, ignore_errors=True)
    os.makedirs(svgdir)
    r = run([sb.KICAD_CLI, "sch", "export", "svg", "--exclude-drawing-sheet", "-o", svgdir, sch])
    svgs = [f for f in os.listdir(svgdir) if f.endswith(".svg")]
    if not svgs:
        return {"error": r.stdout + r.stderr}
    svg = os.path.join(svgdir, svgs[0])
    sheet, blocks = sb.load_layout(board)
    pw, ph = sheet["paper"]
    scale = 8.0  # px per mm
    png = os.path.join(work, board + ".png")
    cairosvg.svg2png(url=svg, write_to=png, output_width=int(pw * scale), output_height=int(ph * scale),
                     background_color="white")
    im = Image.open(png)
    outs = {"sheet": png}
    for b in blocks:
        if b["id"] not in sheet["blocks"]:
            continue
        x, y = sheet["blocks"][b["id"]]
        w, h = b["size"]
        crop = im.crop((int((x - 3) * scale), int((y - 3) * scale), int((x + w + 3) * scale),
                        int((y + h + 3) * scale)))
        f = os.path.join(work, "blk_%s.png" % b["id"])
        crop.save(f)
        outs[b["id"]] = f
    small = im.copy()
    small.thumbnail((2400, 2400))
    small.save(os.path.join(work, board + "_overview.png"))
    outs["overview"] = os.path.join(work, board + "_overview.png")
    return outs


if __name__ == "__main__":
    main()
