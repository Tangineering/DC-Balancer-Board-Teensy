"""Route a placed board: power pours (hand-scripted, from the layout module), Freerouting for the signal nets,
then the GND pours and stitching vias. Usage: python route.py <board> <projdir>

Order:
 1. move silkscreen references to the fab layers (dense board; the iBOM and fab drawing carry them, D-12);
 2. add the hand-scripted power zones and the GND plane, fill them;
 3. export Specctra DSN, run Freerouting 2.5.0 headless, import the SES;
 4. add the GND pours (outer layers), fill, add stitching vias where copper clearance allows, refill, save.
"""
import importlib
import math
import os
import subprocess
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

from shapely.geometry import Point, box, Polygon, LineString
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbbuild as pb  # noqa: E402

JAVA = r"C:\Tools\jdk-25.0.5+8\bin\java.exe"
FR = r"C:\Tools\freerouting\freerouting-2.5.0.jar"
LAYER = {"F": pcbnew.F_Cu, "In1": pcbnew.In1_Cu, "In2": pcbnew.In2_Cu, "B": pcbnew.B_Cu}


def add_zone(b, fr, poly, layer, net, prio, name, thermal_tht=True, min_w=0.2, clear=0.2):
    if poly.geom_type == "MultiPolygon":
        return [add_zone(b, fr, g, layer, net, prio, "%s_%d" % (name, i), thermal_tht, min_w, clear)
                for i, g in enumerate(poly.geoms) if g.area > 2.0]
    z = pcbnew.ZONE(b)
    z.SetLayer(layer)
    z.SetNet(b.FindNet(net))
    z.SetAssignedPriority(prio)
    z.SetZoneName(name)
    if layer in (pcbnew.In1_Cu, pcbnew.In2_Cu):
        clear = max(clear, 0.27)   # fab: plated hole to internal copper 0.254 mm
    z.SetLocalClearance(pcbnew.FromMM(clear))
    z.SetMinThickness(pcbnew.FromMM(min_w))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL if thermal_tht else pcbnew.ZONE_CONNECTION_FULL)
    z.SetThermalReliefGap(pcbnew.FromMM(0.3))
    z.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.6))
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    ol = z.Outline()
    ol.NewOutline()
    for x, y in list(poly.exterior.coords)[:-1]:
        ol.Append(fr.v(x, y))
    b.Add(z)
    return z


def add_via(b, fr, x, y, net, d=0.6, drill=0.3):
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(fr.v(x, y))
    v.SetWidth(pcbnew.FromMM(d))
    v.SetDrill(pcbnew.FromMM(drill))
    v.SetNet(b.FindNet(net))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    b.Add(v)
    return v


def add_track(b, fr, pts, net, w, layer):
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(fr.v(x0, y0))
        t.SetEnd(fr.v(x1, y1))
        t.SetWidth(pcbnew.FromMM(w))
        t.SetLayer(layer)
        t.SetNet(b.FindNet(net))
        t.SetLocked(True)
        b.Add(t)


def copper_geoms(b, fr, layer_ids):
    """Shapely geometry per net of every pad/track/via on the given copper layers (Eagle frame)."""
    out = {}
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if not any(p.IsOnLayer(l) for l in layer_ids):
                continue
            poly = p.GetEffectivePolygon(layer_ids[0] if p.IsOnLayer(layer_ids[0]) else
                                         [l for l in layer_ids if p.IsOnLayer(l)][0], pcbnew.ERROR_INSIDE)
            g = []
            for i in range(poly.OutlineCount()):
                o = poly.Outline(i)
                g.append(Polygon([fr.e(o.CPoint(k)) for k in range(o.PointCount())]).buffer(0))
            if p.GetDrillSizeX() > 0:
                g.append(Point(fr.e(p.GetPosition())).buffer(pcbnew.ToMM(p.GetDrillSizeX()) / 2 + 0.05))
            out.setdefault(p.GetNetname(), []).append(unary_union(g))
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            g = Point(fr.e(t.GetPosition())).buffer(pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)) / 2)
        else:
            if t.GetLayer() not in layer_ids:
                continue
            g = LineString([fr.e(t.GetStart()), fr.e(t.GetEnd())]).buffer(pcbnew.ToMM(t.GetWidth()) / 2)
        out.setdefault(t.GetNetname(), []).append(g)
    return {k: unary_union(v) for k, v in out.items()}


def stitch(b, fr, L, net, pitch, region, keep_out, clear=0.25, d=0.6, log=None):
    """GND stitching vias on a square grid inside region, where every copper layer has clearance."""
    allc = copper_geoms(b, fr, [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu])
    foreign = unary_union([g for n, g in allc.items() if n != net])
    pads = []
    for fp in b.GetFootprints():
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            x0, x1 = pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetRight())
            y0, y1 = fr.yoff - pcbnew.ToMM(bb.GetBottom()), fr.yoff - pcbnew.ToMM(bb.GetTop())
            pads.append(box(x0, y0, x1, y1))
    keep_out = keep_out.union(unary_union(pads).buffer(0.2))   # no via in or beside any pad
    n = 0
    minx, miny, maxx, maxy = region.bounds
    y = miny
    placed = []
    while y <= maxy:
        x = minx
        while x <= maxx:
            c = Point(x, y)
            if region.contains(c.buffer(d / 2 + 0.4)) and not keep_out.intersects(c.buffer(d / 2 + 0.3)) \
                    and foreign.distance(c) > d / 2 + clear and all(c.distance(q) > 1.0 for q in placed):
                add_via(b, fr, x, y, net, d)
                placed.append(c)
                n += 1
            x += pitch
        y += pitch
    if log is not None:
        log.append("stitching vias %s: %d" % (net, n))
    return placed


def freeroute(b, projdir, name, passes=40):
    dsn = os.path.join(projdir, name + ".dsn")
    ses = os.path.join(projdir, name + ".ses")
    pcbnew.ExportSpecctraDSN(b, dsn)
    if os.path.exists(ses):
        os.remove(ses)
    cmd = [JAVA, "-Djava.awt.headless=true", "-jar", FR, "--gui.enabled=false",
           "--usage_and_diagnostic_data.disable_analytics=true", "-de", dsn, "-do", ses,
           "--router.autorouter.max_passes=%d" % passes]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3000)
    with open(os.path.join(projdir, "freerouting.log"), "w", encoding="utf-8") as f:
        f.write(r.stdout[-20000:] + "\n" + r.stderr[-20000:])
    if not os.path.exists(ses):
        raise SystemExit("Freerouting produced no SES (see freerouting.log)")
    pcbnew.ImportSpecctraSES(b, ses)


def stitch_only(board_name, projdir):
    """ROUTE_STITCH_ONLY=1: add the GND stitching vias to a routed board, refill, save."""
    L = importlib.import_module("route_" + board_name)
    pcb = os.path.join(projdir, board_name + ".kicad_pcb")
    b = pcbnew.LoadBoard(pcb)
    fr = pb.Frame(L.YOFF)
    log = []
    for net, pitch, region, keep in L.stitching():
        stitch(b, fr, L, net, pitch, region, keep, log=log)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save(pcb)
    print("\n".join(log))


def main(board_name, projdir):
    if os.environ.get("ROUTE_STITCH_ONLY") == "1":
        return stitch_only(board_name, projdir)
    L = importlib.import_module("route_" + board_name)
    pcb = os.path.join(projdir, board_name + ".kicad_pcb")
    src = os.path.join(projdir, board_name + "_placed.kicad_pcb")
    b = pcbnew.LoadBoard(src if os.path.exists(src) else pcb)
    fr = pb.Frame(L.YOFF)
    log = []
    # 1. silkscreen references -> fab
    for fp in b.GetFootprints():
        if fp.GetReference() not in L.SILK_REFS:
            fp.Reference().SetVisible(False)
    # net classes
    ds = b.GetDesignSettings()
    nc = ds.m_NetSettings.GetDefaultNetclass()
    nc.SetTrackWidth(pcbnew.FromMM(L.TRACK))
    nc.SetClearance(pcbnew.FromMM(L.CLEAR))
    nc.SetViaDiameter(pcbnew.FromMM(getattr(L, "VIA", (0.6, 0.3))[0]))
    nc.SetViaDrill(pcbnew.FromMM(getattr(L, "VIA", (0.6, 0.3))[1]))
    # edge band: Freerouting does not apply the fab copper-to-edge rule (0.381 mm); a 0.45 mm keep-out ring does
    band = L.P.difference(L.P.buffer(-getattr(L, "EDGE_BAND", 0.45), join_style=2))
    pb.add_rule_area(b, fr, band, [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu] if L.P.area > 1200 else
                     [pcbnew.F_Cu, pcbnew.B_Cu], "edge_band_router", tracks=True, vias=True, pads=False, pour=False,
                     fps=False)
    for lname in getattr(L, "POWER_LAYERS", []):
        b.SetLayerType(LAYER[lname], pcbnew.LT_POWER)   # router uses the layer only for plane connections
    # 2. power zones, pre-placed vias and tracks
    for zdef in L.power_zones():   # optional sixth field: thermal relief on THT pads (D-56; default True)
        name, poly, layer, net, prio = zdef[:5]
        add_zone(b, fr, poly, LAYER[layer], net, prio, name, thermal_tht=zdef[5] if len(zdef) > 5 else True)
    for x, y, net in L.PRE_VIAS:
        add_via(b, fr, x, y, net)
    for pts, net, w, layer in L.PRE_TRACKS:
        add_track(b, fr, pts, net, w, LAYER[layer])
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    # 3. autoroute (skip with ROUTE_REUSE_SES=1 to import an existing session)
    if os.environ.get("ROUTE_SKIP_FR") == "1":
        pass   # signal routing by gen/pathfinder.py afterwards
    elif os.environ.get("ROUTE_REUSE_SES") == "1":
        pcbnew.ImportSpecctraSES(b, os.path.join(projdir, board_name + ".ses"))
    else:
        freeroute(b, projdir, board_name, L.PASSES)
        for rnd in range(getattr(L, "ROUNDS", 1) - 1):
            # restart from the imported wiring (the DSN carries it), so the router works only on what is left
            freeroute(b, projdir, board_name, L.PASSES)
            log.append("router round %d done" % (rnd + 2))
    print("imported, tracks:", len(b.GetTracks()), flush=True)
    # Freerouting necks tracks down at some pad entries; the fab minimum is 0.1524 mm (tools/pcb fab rules)
    nfix = 0
    for t in b.GetTracks():
        if t.GetClass() == "PCB_TRACK" and t.GetWidth() < pcbnew.FromMM(0.16):
            t.SetWidth(pcbnew.FromMM(0.16))
            nfix += 1
    log.append("tracks widened to 0.16 mm: %d" % nfix)
    # 4. GND pours and stitching
    for name, poly, layer, net, prio in L.gnd_pours():
        add_zone(b, fr, poly, LAYER[layer], net, prio, name)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    print("pours filled", flush=True)
    if os.environ.get("ROUTE_SKIP_FR") != "1":
        for net, pitch, region, keep in L.stitching():
            stitch(b, fr, L, net, pitch, region, keep, log=log)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    for lname in getattr(L, "POWER_LAYERS", []):
        b.SetLayerType(LAYER[lname], pcbnew.LT_SIGNAL)
    b.Save(pcb)
    with open(os.path.join(projdir, "route_log.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
