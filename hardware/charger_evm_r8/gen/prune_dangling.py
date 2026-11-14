"""Delete dead-end copper: every track segment with an end that touches no pad, via, zone or other track of its net
is deleted, then every via that connects copper on fewer than two layers and sits on no pad; repeated until stable.
The zones are then refilled with the connectivity built (an unbuilt connectivity leaves inner-layer pad clearances
unfilled). One process, one load (re-loading a board in the same process breaks the SWIG wrappers).
Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/prune_dangling.py <cr|eib> [net,net,...]   (D-66)"""
import math
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

B = sys.argv[1]
ONLY = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
PCB = "%s/%s.kicad_pcb" % (B, B)
mm, FMM = pcbnew.ToMM, pcbnew.FromMM
b = pcbnew.LoadBoard(PCB)
KEEP = []


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def end_connected(net, lay, x, y, self_id):
    for o in b.GetTracks():
        if o.GetNetCode() != net or o.m_Uuid.AsString() == self_id:
            continue
        if o.GetClass() == "PCB_VIA":
            if math.hypot(mm(o.GetPosition().x) - x, mm(o.GetPosition().y) - y) <= mm(o.GetWidth(pcbnew.F_Cu)) / 2:
                return True
        elif o.GetLayer() == lay and seg_dist(x, y, mm(o.GetStart().x), mm(o.GetStart().y), mm(o.GetEnd().x),
                                              mm(o.GetEnd().y)) <= mm(o.GetWidth()) / 2:
            return True
    pt = pcbnew.VECTOR2I(FMM(x), FMM(y))
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetNetCode() == net and p.IsOnLayer(lay) and p.HitTest(pt):
                return True
    for z in b.Zones():
        if z.GetNetCode() == net and z.IsOnLayer(lay) and z.HitTestFilledArea(lay, pt):
            return True
    return False


def via_layers(v):
    """Copper layers on which via v meets a track, pad or zone of its net."""
    net, x, y, r = v.GetNetCode(), mm(v.GetPosition().x), mm(v.GetPosition().y), mm(v.GetWidth(pcbnew.F_Cu)) / 2
    ls = set()
    for o in b.GetTracks():
        if o.GetClass() == "PCB_TRACK" and o.GetNetCode() == net and seg_dist(
                x, y, mm(o.GetStart().x), mm(o.GetStart().y), mm(o.GetEnd().x), mm(o.GetEnd().y)) <= r + mm(o.GetWidth()) / 2:
            ls.add(o.GetLayer())
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetNetCode() == net and p.HitTest(v.GetPosition()):
                ls.add("pad")
    for z in b.Zones():
        if z.GetNetCode() == net:
            for lay in z.GetLayerSet().Seq():
                if z.HitTestFilledArea(lay, v.GetPosition()):
                    ls.add(lay)
    return ls


total_t = total_v = 0
while True:
    dead = []
    for t in b.GetTracks():
        if t.GetClass() != "PCB_TRACK" or t.GetNetCode() <= 0 or (ONLY and t.GetNetname() not in ONLY):
            continue
        sid = t.m_Uuid.AsString()
        for p in (t.GetStart(), t.GetEnd()):
            if not end_connected(t.GetNetCode(), t.GetLayer(), mm(p.x), mm(p.y), sid):
                dead.append(t)
                break
    vdead = []
    for v in b.GetTracks():
        if v.GetClass() == "PCB_VIA" and (not ONLY or v.GetNetname() in ONLY):
            ls = via_layers(v)
            if "pad" not in ls and len(ls) < 2:
                vdead.append(v)
    if not dead and not vdead:
        break
    for t in dead + vdead:
        print("  deleted %s %s at (%.3f, %.3f)" % (t.GetClass(), t.GetNetname(), mm(t.GetPosition().x), mm(t.GetPosition().y)))
        b.Remove(t); KEEP.append(t)
    total_t += len(dead); total_v += len(vdead)
b.BuildConnectivity()
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
b.Save(PCB)
print("dead-end tracks deleted: %d, dead vias deleted: %d" % (total_t, total_v))
