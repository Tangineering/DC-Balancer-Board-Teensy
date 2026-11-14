"""D-66: replace the J101 (CR) or J201 (EIB) FTSH header by the WIRE9 wire-pad footprint in place, on the routed
board, without rerouting the board. Usage (pcbnew venv, from hardware/charger_evm_r8):
    python gen/swap_wire9.py <cr|eib>
Steps:
1. The WIRE9 footprint is loaded from the board's project library and placed at the centre of the old header,
   same side, rotation 0; reference, value and fields are kept. Pad nets come from <board>/<board>.net.
2. Tracks and vias of other nets that the new plated pads would violate are deleted (outer layers: pad edge +
   net-class clearance; inner layers: the fab hole-to-copper rule, because unused inner pads are removed on the CR).
3. Track segments of the header's nets and of the nets cut in step 2 whose end is left open are deleted, one
   segment at a time, until every remaining end touches a pad, a via, a zone or another track of the net. Vias are
   never deleted here, so a route stops at its last via and the router reconnects from there.
4. Zones are refilled and the board saved. The unconnected items are closed afterwards by gen/finish.sh.
"""
import math
import re
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

BOARD = sys.argv[1]
REF = {"cr": "J101", "eib": "J201"}[BOARD]
LIB = "%s/charger_r8_%s.pretty" % (BOARD, BOARD)
NAME = {"cr": "WirePads_PTH_3x3_D1.0mm_Pad1.8mm_P2.54mm_CrtYd0.25",
        "eib": "WirePads_PTH_3x3_D1.0mm_Pad1.8mm_P2.54mm_CrtYd0.10"}[BOARD]
PCB = "%s/%s.kicad_pcb" % (BOARD, BOARD)
mm, FMM = pcbnew.ToMM, pcbnew.FromMM

b = pcbnew.LoadBoard(PCB)
KEEP = []   # removed items stay referenced until the save (freed wrappers corrupt the board)
ds = b.GetDesignSettings()
CLEAR = mm(ds.m_NetSettings.GetDefaultNetclass().GetClearance())
HOLE_INNER = 0.254 if BOARD == "cr" else 0.0   # cr.kicad_dru fab_hole_to_inner_copper

# ---- 1. pad nets from the exported netlist
net_txt = open("%s/%s.net" % (BOARD, BOARD), encoding="utf-8").read()
pin_net = {}
for m in re.finditer(r'\(net \(code "\d+"\) \(name "([^"]+)"\)(.*?)\)\s*\)\s*(?=\(net |\)\s*\)\s*$)', net_txt, re.S):
    for n in re.finditer(r'\(node \(ref "%s"\) \(pin "(\d+)"\)' % REF, m.group(2)):
        pin_net[n.group(1)] = m.group(1)
assert len(pin_net) == 9, pin_net

old = b.FindFootprintByReference(REF)
pos, layer = old.GetPosition(), old.GetLayer()
old_pads = [(p.GetPosition().x, p.GetPosition().y, p.GetNetname()) for p in old.Pads()]
nets = {p.GetNetname() for p in old.Pads() if p.GetNetCode() > 0}
value = "W5 wire pads"   # the netlist.py value (D-66)

new = pcbnew.FootprintLoad(LIB, NAME)
assert new is not None, (LIB, NAME)
new.SetReference(REF)
new.SetValue(value)
new.SetFPIDAsString("charger_r8_%s:%s" % (BOARD, NAME))
new.SetPosition(pos)
for p in new.Pads():
    p.SetNet(b.FindNet(pin_net[p.GetNumber()]))
for fld in ("Reference",):
    pass
# keep the old reference text placement (D-59 / D-64 silk placement)
new.Reference().SetPosition(old.Reference().GetPosition())
new.Reference().SetVisible(old.Reference().IsVisible())
new.Reference().SetLayer(old.Reference().GetLayer())
new.Reference().SetTextSize(old.Reference().GetTextSize())
new.Reference().SetTextThickness(old.Reference().GetTextThickness())
# the old MPN / Manufacturer fields named the FTSH header and are not carried over (the wire pads are no part)
new.SetPath(old.GetPath())
new.SetSheetname(old.GetSheetname())
new.SetSheetfile(old.GetSheetfile())
b.Remove(old); KEEP.append(old)
b.Add(new)
new_pads = [(p.GetPosition().x, p.GetPosition().y, p.GetNetname(), mm(p.GetSize().x) / 2, mm(p.GetDrillSize().x) / 2)
            for p in new.Pads()]
print("%s replaced by %s at (%.3f, %.3f)" % (REF, NAME, mm(pos.x), mm(pos.y)))


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


# ---- 2. other-net copper that the new pads violate
hit = []
for t in b.GetTracks():
    for (px, py, pnet, pr, dr) in new_pads:
        x, y = mm(px), mm(py)
        if t.GetNetname() == pnet:   # a same-net via inside the new pad: its hole clashes with the pad hole
            if t.GetClass() == "PCB_VIA" and math.hypot(mm(t.GetPosition().x) - x, mm(t.GetPosition().y) - y) < pr:
                hit.append(t); break
            continue
        if t.GetClass() == "PCB_VIA":
            d = math.hypot(mm(t.GetPosition().x) - x, mm(t.GetPosition().y) - y)
            vr = mm(t.GetWidth(pcbnew.F_Cu)) / 2
            if d < pr + CLEAR + vr or d < dr + mm(t.GetDrillValue()) / 2 + 0.254:
                hit.append(t); break
        else:
            d = seg_dist(x, y, mm(t.GetStart().x), mm(t.GetStart().y), mm(t.GetEnd().x), mm(t.GetEnd().y))
            inner = t.GetLayer() not in (pcbnew.F_Cu, pcbnew.B_Cu)
            lim = (dr + HOLE_INNER if (inner and BOARD == "cr") else pr + CLEAR) + mm(t.GetWidth()) / 2
            if d < lim:
                hit.append(t); break
for t in hit:
    print("  deleted %s %s %s" % (t.GetClass(), t.GetNetname(),
                                 "(%.3f, %.3f)" % (mm(t.GetPosition().x), mm(t.GetPosition().y)) if t.GetClass() == "PCB_VIA"
                                 else "%s (%.3f, %.3f)-(%.3f, %.3f)" % (b.GetLayerName(t.GetLayer()), mm(t.GetStart().x),
                                                                       mm(t.GetStart().y), mm(t.GetEnd().x), mm(t.GetEnd().y))))
    b.Remove(t); KEEP.append(t)
print("other-net items deleted at the new pads: %d" % len(hit))
cut_nets = {t.GetNetname() for t in hit}
# ---- 3. prune open track ends of the header's nets and of every net cut in step 2
def touched(t, x, y):
    lay, net, tid = t.GetLayer(), t.GetNetCode(), t.m_Uuid.AsString()
    for o in b.GetTracks():
        if o.m_Uuid.AsString() == tid or o.GetNetCode() != net:
            continue
        if o.GetClass() == "PCB_VIA":
            if math.hypot(mm(o.GetPosition().x) - x, mm(o.GetPosition().y) - y) <= mm(o.GetWidth(pcbnew.F_Cu)) / 2:
                return True
        elif o.GetLayer() == lay:
            if seg_dist(x, y, mm(o.GetStart().x), mm(o.GetStart().y), mm(o.GetEnd().x), mm(o.GetEnd().y)) <= \
                    mm(o.GetWidth()) / 2:
                return True
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetNetCode() == net and p.IsOnLayer(lay) and p.HitTest(pcbnew.VECTOR2I(FMM(x), FMM(y))):
                return True
    for z in b.Zones():   # a track end inside a filled zone of its own net is connected
        if z.GetNetCode() == net and z.IsOnLayer(lay) and z.HitTestFilledArea(lay, pcbnew.VECTOR2I(FMM(x), FMM(y))):
            return True
    return False


pruned = 0
while True:
    gone = []
    for t in b.GetTracks():
        if t.GetClass() != "PCB_TRACK" or t.GetNetname() not in nets | cut_nets:
            continue
        ends = [(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))]
        if not all(touched(t, x, y) for x, y in ends):
            gone.append(t)
    if not gone:
        break
    for t in gone:
        b.Remove(t); KEEP.append(t)
    pruned += len(gone)
print("open-ended track segments deleted: %d" % pruned)

pcbnew.ZONE_FILLER(b).Fill(b.Zones())
b.Save(PCB)
