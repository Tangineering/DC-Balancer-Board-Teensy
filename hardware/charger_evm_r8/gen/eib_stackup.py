"""REVIEW_2026-11-14 CRL-6 analogue for the EIB (S3): eib/eib.kicad_pcb had no (stackup) block, so the Gerber job
file carried KiCad's defaults (finish 'None', no colours). This script writes the OSH Park standard 2-layer stack-up
into the board setup, in place (https://docs.oshpark.com/services/two-layer/, read 2026-11-14):

- board 1.6 mm nominal ("63mil (1.6mm) nominal"); copper 1 oz (0.035 mm) on both layers;
- dielectric FR4 (175 Tg Kingboard KB6167F), epsilon_r 4.5 at 10 MHz; core 1.6 - 2 x 0.035 - 2 x 0.01 = 1.51 mm (derived
  so that the stack sums to 1.6 mm; OSH Park does not state the core); loss tangent 0.02 (KiCad FR4 default, not
  stated by OSH Park);
- solder mask purple on both sides (SMOBC), 0.01 mm (KiCad default; OSH Park does not state it);
- silkscreen white on both sides (OSH Park: "High Res DLP" silk; white is the OSH Park colour on purple mask);
- finish ENIG (IPC-4552).

The pcbnew Python API does not expose BOARD_STACKUP in this build, so the block is written as text into (setup) and
the board is then loaded and saved by pcbnew, which parses and normalizes it; the script asserts that KiCad kept the
finish and the thickness. Copper, mask expansion, rules and the other setup values are not changed. Idempotent.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/eib_stackup.py
"""
import re

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

PCB = "eib/eib.kicad_pcb"
STACK = [
    '(layer "F.SilkS" (type "Top Silk Screen") (color "White"))',
    '(layer "F.Paste" (type "Top Solder Paste"))',
    '(layer "F.Mask" (type "Top Solder Mask") (color "Purple") (thickness 0.01))',
    '(layer "F.Cu" (type "copper") (thickness 0.035))',
    '(layer "dielectric 1" (type "core") (color "FR4 natural") (thickness 1.51) (material "FR4") (epsilon_r 4.5) '
    '(loss_tangent 0.02))',
    '(layer "B.Cu" (type "copper") (thickness 0.035))',
    '(layer "B.Mask" (type "Bottom Solder Mask") (color "Purple") (thickness 0.01))',
    '(layer "B.Paste" (type "Bottom Solder Paste"))',
    '(layer "B.SilkS" (type "Bottom Silk Screen") (color "White"))',
    '(copper_finish "ENIG")',
    '(dielectric_constraints no)',
]

raw = open(PCB, encoding="utf-8", newline="").read()
eol = "\r\n" if "\r\n" in raw else "\n"
if "(stackup" in raw:
    print("stack-up already present")
else:
    m = re.search(r"\(setup" + re.escape(eol), raw)
    assert m, "no (setup) block"
    block = "\t\t(stackup" + eol + "".join("\t\t\t" + s + eol for s in STACK) + "\t\t)" + eol
    raw = raw[:m.end()] + block + raw[m.end():]
    with open(PCB, "w", encoding="utf-8", newline="") as f:
        f.write(raw)
    b = pcbnew.LoadBoard(PCB)   # parse and normalize
    b.Save(PCB)
    print("stack-up written")
txt = open(PCB, encoding="utf-8").read()
blk = txt[txt.index("(stackup"):txt.index("(pad_to_mask_clearance")]
assert '(copper_finish "ENIG")' in blk and blk.count('(color "Purple")') == 2 and "(thickness 1.51)" in blk, blk
print(re.sub(r"\s+", " ", blk).strip())
