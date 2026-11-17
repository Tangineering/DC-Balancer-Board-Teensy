"""D-66 (EIB): R265.2 (was ILIM_SENSE to J201.11) and R264.2 (was CE_SENSE to J201.13) become not connected, as in
gen/netlist.py; the tracks and vias of /ILIM_SENSE and /CE_SENSE are deleted. Both resistors are DNP (dec2-eib).
Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/eib_sense_nc.py"""
import pcbnew
try:
    import wx
    wx.DisableAsserts()
except Exception:
    pass

PCB = "eib/eib.kicad_pcb"
b = pcbnew.LoadBoard(PCB)
KEEP = []
for ref in ("R265", "R264"):
    p = [q for q in b.FindFootprintByReference(ref).Pads() if q.GetNumber() == "2"][0]
    name = "unconnected-(%s-Pad2)" % ref
    ni = b.FindNet(name)
    if ni is None:
        ni = pcbnew.NETINFO_ITEM(b, name)
        b.Add(ni)
    old = p.GetNetname()
    p.SetNet(ni)
    print("%s.2: %s -> %s" % (ref, old, name))
n = 0
for t in list(b.GetTracks()):
    if t.GetNetname() in ("/ILIM_SENSE", "/CE_SENSE"):
        b.Remove(t); KEEP.append(t); n += 1
print("ILIM_SENSE / CE_SENSE tracks and vias deleted: %d" % n)
b.BuildConnectivity()
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
b.Save(PCB)
