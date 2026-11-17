"""REVIEW_2026-11-14 EIB-7 / EIL-6 / BOM-2 (S3): the EIB stencil printed paste on the 32 SMD pads of the DNP parts
(C203, C204, R258-R265, U203, U204). This script gives every footprint whose DNP attribute is set on
eib/eib.kicad_pcb a footprint-level solder-paste margin override of -2.0 mm, in place. The override is larger than
half of every pad of these footprints (largest pad 1.0 mm), so KiCad plots no F.Paste aperture for them; the
gerbers/eib-F_Paste.gtp flash count falls from 94 to 62.

Why an override and not a pad layer change: removing F.Paste from the pad layer sets makes each instance differ from
its library footprint (12 lib_footprint_mismatch warnings under --severity-all); the footprint-level margin is not
part of that comparison, so DRC stays at 0. Copper, mask, nets, fields, positions and the library footprints are not
touched; DNP is a per-instance build choice (D-49), so gen/fplib.py does not change. The DNP set is the board
attribute, which equals the 'dnp' property set of eib/eib.net (C203 C204 E4 E6 R258-R265 U203 U204; E4 and E6 are
THT pads without paste). Idempotent. Reversal: set the margin of these footprints back to 0 (no override).

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/eib_dnp_paste.py
"""
import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

EXPECTED = {"C203", "C204", "E4", "E6", "R258", "R259", "R260", "R261", "R262", "R263", "R264", "R265", "U203", "U204"}
MARGIN = pcbnew.FromMM(-2.0)
PCB = "eib/eib.kicad_pcb"
b = pcbnew.LoadBoard(PCB)
dnp = {fp.GetReference(): fp for fp in b.GetFootprints() if fp.IsDNP()}
assert set(dnp) == EXPECTED, sorted(set(dnp) ^ EXPECTED)
n = 0
for ref in sorted(dnp):
    fp = dnp[ref]
    for p in fp.Pads():   # every pad must vanish from the paste plot under the override
        s = p.GetSize(pcbnew.F_Cu)
        assert min(s.x, s.y) + 2 * MARGIN < 0 or not p.IsOnLayer(pcbnew.F_Paste), (ref, p.GetNumber())
        assert p.GetLocalSolderPasteMargin() in (None, 0), (ref, p.GetNumber(), "pad-level paste override present")
    if fp.GetLocalSolderPasteMargin() != MARGIN:
        fp.SetLocalSolderPasteMargin(MARGIN)
        n += 1
b.Save(PCB)
print("DNP footprints: paste margin -2.0 mm set on %d of %d" % (n, len(dnp)))
