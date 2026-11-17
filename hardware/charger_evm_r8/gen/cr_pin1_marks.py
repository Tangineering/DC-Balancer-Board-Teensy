"""REVIEW_2026-11-14 CRL-3 / INT-5 (S3): the CR IC and diode footprints carried no pin-1 or polarity silkscreen (D-12a
kept the marks on F.Fab), so U101, the two SMA power diodes and the logic ICs could be placed reversed with no cue on the
bare board (a reversed D107 forward-biases the unprotected VCHG-IN bus to GND). This script adds, in place:

- a filled F.SilkS pin-1 dot (radius 0.10 mm, stroke 0.15 mm, outer diameter 0.35 mm) beside pad 1 of U101 (VQFN-24),
  D104-D106 (SOT-23, BAV199), U102, U103, U107, U119, U120 (SOT-23-6) and U105, U106, U110, U118 (DCT SSOP-8);
- a 0.15 mm F.SilkS cathode bar beyond the toe of pad 1 (K) of D103 and D107 (SMA).

The positions are those of gen/fplib.py (PIN1_DOT, with the CR overrides PIN1_DOT_CR, and CATHODE_BAR_CR). They were
chosen so that on every CR instance the mark keeps >= 0.07 mm from every solder-mask opening and stays off every via
drill; the nearest pad to each dot is pad 1 of its own part.

Step 1 writes the five affected library footprints of cr/charger_r8_cr.pretty from gen/fplib.py; the only change
against the committed files is the mark (the tedit stamp and the line ends are kept), so the board stays equal to its
library (DRC lib_footprint_mismatch). The rest of the library is not regenerated. Step 2 copies the mark of each
library footprint onto the board instances at their position and orientation (gen/eib_pin1_marks.py,
gen/u101_paste_swap.py). Pads, nets, fields, values and library IDs are not touched. Idempotent.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/cr_pin1_marks.py
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

LIB = "cr/charger_r8_cr.pretty"
PKGS = {"VQFN24": ["U101"], "SOT-23": ["D104", "D105", "D106"],
        "SOT-23-6": ["U102", "U103", "U107", "U119", "U120"],
        "SSOP-8": ["U105", "U106", "U110", "U118"], "SMA": ["D103", "D107"]}
KEEP = []

# step 1: library footprints
fplib.CRT, fplib.BOARD = 0.25, "cr"
tmp = tempfile.mkdtemp()
names = {}
for k in PKGS:
    src, name = fpmap.fp("cr", k)
    names[k] = name
    fplib.CUSTOM[k](tmp, name)
    new = open(os.path.join(tmp, name + ".kicad_mod"), encoding="utf-8").read()
    path = os.path.join(LIB, name + ".kicad_mod")
    old = open(path, encoding="utf-8").read()
    stamp = re.search(r"\(tedit [0-9a-f]+\)", old)
    if stamp:
        new = re.sub(r"\(tedit [0-9a-f]+\)", stamp.group(0), new, count=1)
    dl = [ln for ln in new.splitlines() if ln not in old.splitlines()]
    gone = [ln for ln in old.splitlines() if ln not in new.splitlines()]
    assert not gone and len(dl) <= 1 and all(("fp_circle" in ln or "fp_line" in ln) and "F.SilkS" in ln
                                              for ln in dl), (name, dl, gone)
    eol = "\r\n" if "\r\n" in open(path, encoding="utf-8", newline="").read() else "\n"   # keep the file's EOL
    if new != old:
        with open(path, "w", encoding="utf-8", newline=eol) as f:
            f.write(new)
        print("library: %s mark added" % name)
shutil.rmtree(tmp)


def is_mark(it):
    return it.GetLayer() == pcbnew.F_SilkS and it.GetClass() == "PCB_SHAPE" and \
        it.GetShape() in (pcbnew.SHAPE_T_CIRCLE, pcbnew.SHAPE_T_SEGMENT)


# step 2: board instances
PCB = "cr/cr.kicad_pcb"
b = pcbnew.LoadBoard(PCB)
for k, refs in PKGS.items():
    for ref in refs:
        fp = b.FindFootprintByReference(ref)
        assert str(fp.GetFPID().GetLibItemName()) == names[k], (ref, fp.GetFPID().GetLibItemName())
        if any(is_mark(it) for it in fp.GraphicalItems()):
            print("%s: mark already present" % ref)
            continue
        lib = pcbnew.FootprintLoad(LIB, names[k])
        assert lib is not None, names[k]
        lib.SetPosition(fp.GetPosition())
        lib.SetOrientation(fp.GetOrientation())
        marks = [it for it in lib.GraphicalItems() if is_mark(it)]
        assert len(marks) == 1, (ref, len(marks))
        lib.Remove(marks[0])
        fp.Add(marks[0])
        KEEP.extend([marks[0], lib])
        c = marks[0].GetCenter() if marks[0].GetShape() == pcbnew.SHAPE_T_CIRCLE else marks[0].GetStart()
        print("%s: %s at (%.3f, %.3f)" % (ref, "dot" if marks[0].GetShape() == pcbnew.SHAPE_T_CIRCLE else "cathode bar",
                                          pcbnew.ToMM(c.x), pcbnew.ToMM(c.y)))
b.Save(PCB)
