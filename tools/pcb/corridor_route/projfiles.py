"""Copy a board's project files into a work folder, so that kicad-cli finds the design rules, the schematic and the
libraries beside the board copy."""
import glob
import os
import shutil


def copy_project(src_board, outdir, with_board=False):
    """returns the path of the board (copy) in outdir; the board file keeps its name"""
    srcdir = os.path.dirname(os.path.abspath(src_board))
    if os.path.abspath(outdir) == srcdir:
        raise SystemExit("the output folder must differ from the input board's folder")
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src_board))[0]
    for ext in (".kicad_pro", ".kicad_sch", ".kicad_dru"):
        f = os.path.join(srcdir, stem + ext)
        if os.path.exists(f):
            shutil.copy2(f, outdir)
    for f in ("fp-lib-table", "sym-lib-table"):
        if os.path.exists(os.path.join(srcdir, f)):
            shutil.copy2(os.path.join(srcdir, f), outdir)
    for f in glob.glob(os.path.join(srcdir, "*.kicad_sym")):
        shutil.copy2(f, outdir)
    for d in glob.glob(os.path.join(srcdir, "*.pretty")):
        dst = os.path.join(outdir, os.path.basename(d))
        if not os.path.exists(dst):
            shutil.copytree(d, dst)
    out = os.path.join(outdir, stem + ".kicad_pcb")
    if with_board:
        shutil.copy2(src_board, out)
    return out
