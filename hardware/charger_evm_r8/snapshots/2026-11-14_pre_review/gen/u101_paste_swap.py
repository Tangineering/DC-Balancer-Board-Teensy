"""D-69: replace the four paste-only window apertures of U101 on cr/cr.kicad_pcb with those of the current library
footprint (gen/fplib.py vqfn24), at the footprint's position and orientation. Pins, nets, fields and copper are not
touched. Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/u101_paste_swap.py"""
import pcbnew

LIB = "cr/charger_r8_cr.pretty"
NAME = "TPS26630_RGE0024_VQFN-24_4x4mm_P0.5mm_ThermalVias_CrtYd0.25"
KEEP = []

b = pcbnew.LoadBoard("cr/cr.kicad_pcb")
old = b.FindFootprintByReference("U101")


def paste_only(p):
    return p.IsOnLayer(pcbnew.F_Paste) and not p.IsOnLayer(pcbnew.F_Cu)


gone = [p for p in old.Pads() if paste_only(p)]
assert len(gone) == 4, len(gone)
for p in gone:
    old.Remove(p)
    KEEP.append(p)

lib = pcbnew.FootprintLoad(LIB, NAME)
assert lib is not None
lib.SetPosition(old.GetPosition())
lib.SetOrientation(old.GetOrientation())
new = [p for p in lib.Pads() if paste_only(p)]
assert len(new) == 4 and all(p.GetShape() == pcbnew.PAD_SHAPE_CUSTOM for p in new), len(new)
for p in new:
    lib.Remove(p)
    old.Add(p)
    KEEP.append(p)
KEEP.append(lib)
b.Save("cr/cr.kicad_pcb")
print("U101: %d paste apertures replaced" % len(new))
