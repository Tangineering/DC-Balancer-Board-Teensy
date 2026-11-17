"""REVIEW_2026-11-14 EIL-2 (S2): the EIB IC and transistor footprints carried no pin-1 or orientation silkscreen
(D-12 stripped it), so U201 (DCT SSOP-8) could be fitted rotated 180 degrees (IC GND on the 3V3 pad). This script
adds a filled F.SilkS pin-1 dot (radius 0.10 mm, stroke 0.15 mm, outer diameter 0.35 mm) diagonally off the outer
corner of pad 1 to U201 (SSOP-8), U202 (SC70-5 / DCK), Q201-Q203 (SOT-23) and U203/U204 (SOT-23-6, DNP), in place.

Step 1 writes the four affected library footprints of eib/charger_r8_eib.pretty from gen/fplib.py (PIN1_DOT); the
only change against the committed files is the dot (the tedit stamp is kept), so the board stays equal to its
library (DRC lib_footprint_mismatch). The rest of the library is not regenerated. Step 2 copies the dot of each
library footprint onto the board instances at their position and orientation, as gen/u101_paste_swap.py does for
the U101 paste windows. Pads, nets, fields, values and library IDs are not touched. Idempotent.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/eib_pin1_marks.py
"""
import os
import re
import shutil
import sys
import tempfile

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import fplib  # noqa: E402
import fpmap  # noqa: E402

LIB = "eib/charger_r8_eib.pretty"
PKGS = {"SSOP-8": ["U201"], "SC70-5": ["U202"], "SOT-23": ["Q201", "Q202", "Q203"], "SOT-23-6": ["U203", "U204"]}
KEEP = []

# step 1: library footprints
fplib.CRT, fplib.BOARD = 0.10, "eib"
tmp = tempfile.mkdtemp()
names = {}
for k in PKGS:
    src, name = fpmap.fp("eib", k)
    names[k] = name
    fplib.CUSTOM[k](tmp, name)
    new = open(os.path.join(tmp, name + ".kicad_mod"), encoding="utf-8").read()
    path = os.path.join(LIB, name + ".kicad_mod")
    old = open(path, encoding="utf-8").read()
    stamp = re.search(r"\(tedit [0-9a-f]+\)", old)
    if stamp:
        new = re.sub(r"\(tedit [0-9a-f]+\)", stamp.group(0), new, count=1)
    dl = [l for l in new.splitlines() if l not in old.splitlines()]
    assert all("fp_circle" in l and "F.SilkS" in l for l in dl) and len(dl) <= 1, (name, dl)
    eol = "\r\n" if "\r\n" in open(path, encoding="utf-8", newline="").read() else "\n"   # keep the file's EOL
    if new != old:
        with open(path, "w", encoding="utf-8", newline=eol) as f:
            f.write(new)
        print("library: %s pin-1 dot added" % name)
shutil.rmtree(tmp)


def is_dot(it):
    return it.GetLayer() == pcbnew.F_SilkS and it.GetClass() == "PCB_SHAPE" and it.GetShape() == pcbnew.SHAPE_T_CIRCLE


# step 2: board instances
PCB = "eib/eib.kicad_pcb"
b = pcbnew.LoadBoard(PCB)
for k, refs in PKGS.items():
    for ref in refs:
        fp = b.FindFootprintByReference(ref)
        assert str(fp.GetFPID().GetLibItemName()) == names[k], (ref, fp.GetFPID().GetLibItemName())
        if any(is_dot(it) for it in fp.GraphicalItems()):
            print("%s: pin-1 dot already present" % ref)
            continue
        lib = pcbnew.FootprintLoad(LIB, names[k])
        assert lib is not None, names[k]
        lib.SetPosition(fp.GetPosition())
        lib.SetOrientation(fp.GetOrientation())
        dots = [it for it in lib.GraphicalItems() if is_dot(it)]
        assert len(dots) == 1, (ref, len(dots))
        lib.Remove(dots[0])
        fp.Add(dots[0])
        KEEP.extend([dots[0], lib])
        c = dots[0].GetCenter()
        print("%s: pin-1 dot at (%.3f, %.3f)" % (ref, pcbnew.ToMM(c.x), pcbnew.ToMM(c.y)))
b.Save(PCB)
