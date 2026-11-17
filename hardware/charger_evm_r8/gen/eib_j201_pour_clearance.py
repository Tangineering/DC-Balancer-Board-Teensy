"""REVIEW_2026-11-14 EIL-0 (S2): the D-68 0.5 mm pour clearance covered only the E lead pads; the J201 wire pads (D-66,
hand-soldered W5 leads) sat 0.153 mm from the AGND pours on both layers. This script extends the zone-only rule to
J201 in gen/eib_pour_rules.kicad_dru (appended by gen/make_board.sh) and in eib/eib.kicad_dru, refills every zone of
eib/eib.kicad_pcb in place and saves it. Tracks, vias, pads and footprints are not touched. Idempotent.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/eib_j201_pour_clearance.py
The board is loaded as eib/eib.kicad_pcb so that the zone filler reads eib/eib.kicad_pro and eib/eib.kicad_dru.
"""
import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

OLD = "(condition \"A.Type == 'Zone' && B.memberOfFootprint('E*')\")"
NEW = "(condition \"A.Type == 'Zone' && (B.memberOfFootprint('E*') || B.memberOfFootprint('J201'))\")"
NOTE = ("# REVIEW_2026-11-14 EIL-0: the same 0.5 mm pour clearance also holds for the J201 W5 wire pads (D-66, "
        "hand-soldered leads).\n")

for path in ("gen/eib_pour_rules.kicad_dru", "eib/eib.kicad_dru"):
    txt = open(path, encoding="utf-8").read()
    if NEW in txt:
        print("%s: rule already extended" % path)
        continue
    assert txt.count(OLD) == 1, (path, "D-68 rule condition not found exactly once")
    i = txt.index('(rule "eib_E_pad_pour_clearance"')
    txt = txt[:i] + NOTE + txt[i:].replace(OLD, NEW)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    print("%s: rule extended to J201" % path)

PCB = "eib/eib.kicad_pcb"
b = pcbnew.LoadBoard(PCB)
b.BuildConnectivity()
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
b.Save(PCB)
print("zones refilled: %d" % len(list(b.Zones())))
