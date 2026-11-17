"""REVIEW_2026-11-14 CRL-6 (S3): cr/cr.kicad_pcb had no (stackup) block, so the Gerber job file carried KiCad's
defaults (0.035 mm copper on all four layers, 0.48 mm FR4 dielectrics, finish 'None'). This script writes the OSH Park
standard 4-layer stack-up into the board setup, in place. Source: https://docs.oshpark.com/services/four-layer/ (read
2026-11-15; the same page was read on 2026-11-13 for the operator ruling of HANDOFF section 3a item 4):

- board 63 mil (1.6 mm) nominal;
- outer copper 1 oz, clad and plated, 1.7 mil (0.0432 mm) finished; inner copper 0.5 oz clad, 0.68 mil (0.0175 mm);
- L1-L2 and L3-L4 prepreg FR408HR 2113, 7.87 mil (0.1999 mm), Dk 3.61 at 1 GHz; L2-L3 core FR408HR 39 mil
  (0.9906 mm); loss tangent not stated by OSH Park (0.02 is the KiCad default, kept);
- solder resist 0.6 mil (0.0152 mm), purple (Taiyo PSR-4000BN), SMOBC both sides; silkscreen 0.6 mil, white;
- finish ENIG (IPC-4552).

The listed layers sum to 1.542 mm against the 1.6 mm nominal; the figures are entered as the page states them, and the
board thickness (general, 1.6 mm) is unchanged, so the job file states BoardThickness 1.6 (checked 2026-11-15). KiCad
keeps no silkscreen thickness; it is dropped on save. The pcbnew Python API does not expose
BOARD_STACKUP in this build, so the block is written as text into (setup) and the board is then loaded and saved by
pcbnew, which parses and normalizes it (gen/eib_stackup.py). Copper, mask expansion, rules and the other setup values
are not changed. Idempotent.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/cr_stackup.py
"""
import re

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

PCB = "cr/cr.kicad_pcb"
PREPREG = '(type "prepreg") (color "FR4 natural") (thickness 0.1999) (material "FR408HR 2113") (epsilon_r 3.61) ' \
          '(loss_tangent 0.02)'
STACK = [
    '(layer "F.SilkS" (type "Top Silk Screen") (color "White") (thickness 0.0152))',
    '(layer "F.Paste" (type "Top Solder Paste"))',
    '(layer "F.Mask" (type "Top Solder Mask") (color "Purple") (thickness 0.0152) (material "PSR-4000BN"))',
    '(layer "F.Cu" (type "copper") (thickness 0.0432))',
    '(layer "dielectric 1" ' + PREPREG + ')',
    '(layer "In1.Cu" (type "copper") (thickness 0.0175))',
    '(layer "dielectric 2" (type "core") (color "FR4 natural") (thickness 0.9906) (material "FR408HR") '
    '(epsilon_r 3.61) (loss_tangent 0.02))',
    '(layer "In2.Cu" (type "copper") (thickness 0.0175))',
    '(layer "dielectric 3" ' + PREPREG + ')',
    '(layer "B.Cu" (type "copper") (thickness 0.0432))',
    '(layer "B.Mask" (type "Bottom Solder Mask") (color "Purple") (thickness 0.0152) (material "PSR-4000BN"))',
    '(layer "B.Paste" (type "Bottom Solder Paste"))',
    '(layer "B.SilkS" (type "Bottom Silk Screen") (color "White") (thickness 0.0152))',
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
assert '(copper_finish "ENIG")' in blk and blk.count('(color "Purple")') == 2 and "(thickness 0.9906)" in blk \
    and blk.count("(thickness 0.0175)") == 2 and blk.count("(thickness 0.0432)") == 2, blk
th = re.search(r"\(general\s+\(thickness ([\d.]+)\)", txt).group(1)
print("board thickness (general): %s mm" % th)
print(re.sub(r"\s+", " ", blk).strip())
