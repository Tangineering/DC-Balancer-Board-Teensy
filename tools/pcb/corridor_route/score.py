"""Score a routed board against its unrouted baseline. Every routing method is scored by this one script, so that
results of different methods are comparable.

Usage (pcbnew venv):
  python score.py <routed.kicad_pcb> <baseline.kicad_pcb> <out_prefix> [--plane-nets /GND,/AGND]
                  [--test-pour NET:LAYER] [--label NAME] [--min-island 0.5]

<out_prefix> is a file name prefix, not a folder: the script writes <out_prefix>.json, <out_prefix>.md and
<out_prefix>_drc.json (the full kicad-cli DRC report of the routed board). Both boards must sit beside their
project files (same base name), or kicad-cli skips the board rules and the schematic parity test. The boards are
only read. The exit code is 0 when the score was written.

Measures:
  open connections     unconnected items from kicad-cli DRC, split into plane nets (connected later by the
                       plane-via step or by a pour) and all other nets. This is the completion measure.
  new DRC violations   violations of the routed board that the baseline does not have. A violation is
                       identified by its type, its items and its position, so a new violation cannot hide behind
                       one that the routing removed. Each new violation is listed with its position.
  vias on SMD pads     vias added by the routing whose copper lies on an SMD pad or inside its solder-mask
                       opening: the pad grown by its own mask expansion, at least --mask-margin (default 0.05 mm),
                       with square corners. KiCad DRC does not report them; solder runs into the hole. They make a result not valid unless --allow-via-in-pad is given.
  pour islands         filled outlines of at least --min-island mm2 per zone, baseline and routed. Only hard
                       pours (zone priority above 1) and the trial pour count in the rank; soft fills (priority 0
                       or 1) are listed for information, because a later stitching step joins them.
                       With --test-pour, a trial pour of NET over the whole board on LAYER is filled on a copy in
                       memory; its islands are listed with their positions and areas.
  vias                 all vias, and the vias that the routing added and that are not on a plane net or on the
                       trial-pour net. Only the second number is in the rank: a ground via is needed anyway once
                       the pour exists, and the vias of the baseline are not the router's.
  track length         total and per layer; with --test-pour also the length on the pour layer of other nets.
Rank (lower is better, compared in this order): open connections on non-plane nets, new DRC violations, extra
pour islands, added vias not on plane or pour nets, track length. An attempt with a new DRC violation other
than starved_thermal, or with a via on an SMD pad, is not a valid result, whatever its rank. "Valid" means that
the routing added no defect. It does not mean that the board is finished: the plane nets are still open, and
the starved thermals that are listed must be cleared before fabrication."""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter

import pcbnew
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
try:
    import wx
    wx.DisableAsserts()
except Exception:
    pass

ap = argparse.ArgumentParser()
ap.add_argument("routed")
ap.add_argument("baseline")
ap.add_argument("out")
ap.add_argument("--plane-nets", default="")
ap.add_argument("--test-pour", default="")
ap.add_argument("--label", default="")
ap.add_argument("--min-island", type=float, default=0.5)
ap.add_argument("--mask-margin", type=float, default=0.05)
ap.add_argument("--allow-via-in-pad", action="store_true")
ap.add_argument("--kicad-cli", default=r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe")
A = ap.parse_args()
plane = {n for n in A.plane_nets.split(",") if n}
pour_net, pour_layer = (A.test_pour.rsplit(":", 1) if A.test_pour else (None, None))
mm = pcbnew.ToMM
if os.path.isdir(A.out):
    A.out = os.path.join(A.out, "score")


def drc(board, keep=None):
    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    has_sch = os.path.exists(os.path.splitext(board)[0] + ".kicad_sch")
    cmd = [A.kicad_cli, "pcb", "drc", "--format", "json", "--severity-all", "-o", tmp]
    if has_sch:
        cmd.append("--schematic-parity")
    subprocess.run(cmd + [board], capture_output=True, text=True)
    D = json.load(open(tmp, encoding="utf-8"))
    if keep:
        shutil.copy(tmp, keep)
    os.remove(tmp)
    viol = Counter(v["type"] for v in D.get("violations", []))
    detail = {}
    ident = Counter()
    for v in D.get("violations", []):
        its = v.get("items", [])
        # the position of the pad or track, not the anchor of a zone
        pit = [i for i in its if not i.get("description", "").startswith("Zone")] or its
        pos = pit[0].get("pos", {}) if pit else {}
        txt = "(%.2f, %.2f) %s" % (pos.get("x", 0), pos.get("y", 0),
                                   " / ".join(i.get("description", "")[:60] for i in its[:2]))
        detail.setdefault(v["type"], []).append(txt)
        ident[(v["type"], txt)] += 1
    un_plane = un_other = 0
    by_net = Counter()
    for u in D.get("unconnected_items", []):
        nets = set()
        for it in u.get("items", []):
            nets |= set(re.findall(r"\[([^\]]+)\]", it.get("description", "")))
        if nets & plane:
            un_plane += 1
        else:
            un_other += 1
            for n in nets:
                by_net[n] += 1
    parity = Counter(v["type"] for v in D.get("schematic_parity", []))
    return dict(violations=dict(viol), detail=detail, ident=ident, open_plane=un_plane, open_other=un_other,
                open_by_net=dict(by_net), parity=dict(parity), parity_run=has_sch)


def islands_of(fl):
    out = []
    for i in range(fl.OutlineCount()):
        o = fl.Outline(i)
        area = o.Area() / 1e12
        bb = o.BBox()
        out.append((area, mm(bb.GetCenter().x), mm(bb.GetCenter().y)))
    return sorted(out, reverse=True)


def copper(board):
    b = pcbnew.LoadBoard(board)
    length, vias, sig_vias = Counter(), 0, 0
    per_net_layer = Counter()
    smd = []
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                for lid, mlid in ((pcbnew.F_Cu, pcbnew.F_Mask), (pcbnew.B_Cu, pcbnew.B_Mask)):
                    if p.IsOnLayer(lid):
                        sps = p.GetEffectivePolygon(lid, pcbnew.ERROR_INSIDE)
                        cu = unary_union([Polygon([(mm(sps.Outline(i).CPoint(k).x), mm(sps.Outline(i).CPoint(k).y))
                                                   for k in range(sps.Outline(i).PointCount())]).buffer(0)
                                          for i in range(sps.OutlineCount())])
                        exp = mm(p.GetSolderMaskExpansion(mlid)) if p.IsOnLayer(mlid) else 0.0
                        # the mask opening: the pad grown by its expansion (at least --mask-margin), square corners
                        smd.append((cu, cu.buffer(max(exp, A.mask_margin), join_style=2),
                                    "%s.%s" % (fp.GetReference(), p.GetNumber())))
    via_pos, in_pad = set(), []
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            vias += 1
            c = t.GetPosition()
            via_pos.add((c.x, c.y))
            ann = Point(mm(c.x), mm(c.y)).buffer(mm(t.GetWidth(pcbnew.F_Cu)) / 2, 64)
            for cu, opening, name in smd:
                if opening.intersects(ann):
                    in_pad.append((c.x, c.y, "centre in pad" if cu.contains(Point(mm(c.x), mm(c.y)))
                                   else "on the pad edge or in its mask opening", name, t.GetNetname()))
                    break
            if t.GetNetname() not in plane and t.GetNetname() != pour_net:
                sig_vias += 1
        else:
            ln = b.GetLayerName(t.GetLayer())
            d = mm(t.GetLength())
            length[ln] += d
            per_net_layer[(t.GetNetname(), ln)] += d
    hard, soft = {}, {}
    for z in b.Zones():
        if z.GetIsRuleArea():
            continue
        for lay in z.GetLayerSet().Seq():
            isl = [i for i in islands_of(z.GetFilledPolysList(lay)) if i[0] >= A.min_island]
            key = "%s@%s" % (z.GetZoneName() or z.GetNetname(), b.GetLayerName(lay))
            (soft if z.GetAssignedPriority() <= 1 else hard)[key] = len(isl)
    out = dict(vias=vias, sig_vias=sig_vias, length={k: round(v, 1) for k, v in length.items()}, hard=hard, soft=soft,
               via_pos=via_pos, in_pad=in_pad)
    if A.test_pour:
        lid = b.GetLayerID(pour_layer)
        bb = b.GetBoardEdgesBoundingBox()
        z = pcbnew.ZONE(b)
        z.SetLayer(lid)
        z.SetNet(b.FindNet(pour_net))
        ol = z.Outline()
        ol.NewOutline()
        for x, y in ((bb.GetLeft(), bb.GetTop()), (bb.GetRight(), bb.GetTop()), (bb.GetRight(), bb.GetBottom()),
                     (bb.GetLeft(), bb.GetBottom())):
            ol.Append(x, y)
        z.SetLocalClearance(pcbnew.FromMM(0.2))
        z.SetMinThickness(pcbnew.FromMM(0.2))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
        b.Add(z)
        pcbnew.ZONE_FILLER(b).Fill([z])
        allisl = islands_of(z.GetFilledPolysList(lid))
        isl = [i for i in allisl if i[0] >= A.min_island]
        out["test_pour"] = dict(net=pour_net, layer=pour_layer, islands=len(isl), slivers=len(allisl) - len(isl),
                                largest_mm2=round(isl[0][0], 1) if isl else 0,
                                total_mm2=round(sum(i[0] for i in allisl), 1),
                                list=[(round(a, 2), round(x, 2), round(y, 2)) for a, x, y in allisl[:25]],
                                signal_length_on_layer=round(sum(v for (n, ln), v in per_net_layer.items()
                                                                 if ln == pour_layer and n != pour_net), 1))
    return out


base = drc(A.baseline)
rt = drc(A.routed, keep=A.out + "_drc.json")
cb, cr = copper(A.baseline), copper(A.routed)
types = sorted(set(base["violations"]) | set(rt["violations"]))
delta = {t: rt["violations"].get(t, 0) - base["violations"].get(t, 0) for t in types}
fresh_id = rt["ident"] - base["ident"]                     # violations that the baseline does not have
fresh_by_type = Counter()
for (t, txt), n in fresh_id.items():
    fresh_by_type[t] += n
new_viol = sum(fresh_by_type.values())
vip = [v for v in cr["in_pad"] if (v[0], v[1]) not in cb["via_pos"]]      # only vias that the routing added
invalid = sum(n for t, n in fresh_by_type.items() if t != "starved_thermal") + (0 if A.allow_via_in_pad else len(vip))
cr["sig_vias"] = max(0, cr["sig_vias"] - cb["sig_vias"])
extra_islands = sum(max(0, cr["hard"].get(k, 0) - v) for k, v in cb["hard"].items())
if "test_pour" in cr:
    extra_islands += max(0, cr["test_pour"]["islands"] - cb["test_pour"]["islands"])
total_len = round(sum(cr["length"].values()), 1)
rank = [rt["open_other"], new_viol, extra_islands, cr["sig_vias"], total_len]
S = dict(label=A.label, routed=os.path.abspath(A.routed), baseline=os.path.abspath(A.baseline), rank=rank,
         valid=(invalid == 0), vias_on_smd_pads=len(vip), new_by_type=dict(fresh_by_type),
         open_other=rt["open_other"], open_other_baseline=base["open_other"],
         open_plane=rt["open_plane"], open_by_net=rt["open_by_net"], new_violations=new_viol,
         violation_delta=delta, violations_routed=rt["violations"], violations_baseline=base["violations"],
         parity=rt["parity"], parity_run=rt["parity_run"], vias=cr["vias"], sig_vias=cr["sig_vias"],
         vias_baseline=cb["vias"], length=cr["length"], hard_islands=cr["hard"], hard_islands_baseline=cb["hard"],
         soft_islands=cr["soft"], soft_islands_baseline=cb["soft"], extra_islands=extra_islands,
         test_pour=cr.get("test_pour"), test_pour_baseline=cb.get("test_pour"))
json.dump(S, open(A.out + ".json", "w"), indent=1)
L = ["# Routing score%s" % ((": " + A.label) if A.label else ""), "",
     "| Measure | Baseline | Routed |", "|---|---|---|",
     "| Open connections, non-plane nets | %d | %d |" % (base["open_other"], rt["open_other"]),
     "| Open connections, plane nets (%s) | %d | %d |" % (", ".join(sorted(plane)) or "none named", base["open_plane"],
                                                         rt["open_plane"]),
     "| Vias, all | %d | %d |" % (cb["vias"], cr["vias"]),
     "| Vias added, not on plane or pour nets | - | %d |" % cr["sig_vias"],
     "| Added vias on an SMD pad or in its mask opening | - | %d (%d centred in a pad) |" % (
         len(vip), sum(1 for v in vip if v[2] == "centre in pad")),
     "| Track length (mm) | %s | %s |" % (cb["length"], cr["length"]),
     "| Schematic parity issues | %s | %s |" % (base["parity"] if base["parity_run"] else "not run",
                                                rt["parity"] if rt["parity_run"] else "not run")]
if "test_pour" in cr:
    L += ["| Trial pour %s on %s: islands >= %.1f mm2, largest (mm2) | %d, %.0f | %d, %.0f |" % (
        pour_net, pour_layer, A.min_island, cb["test_pour"]["islands"], cb["test_pour"]["largest_mm2"],
        cr["test_pour"]["islands"], cr["test_pour"]["largest_mm2"]),
        "| Trial pour slivers below %.1f mm2 (not ranked) | %d | %d |" % (A.min_island, cb["test_pour"]["slivers"],
                                                                          cr["test_pour"]["slivers"]),
        "| Signal track length on the pour layer (mm) | %.0f | %.0f |" % (cb["test_pour"]["signal_length_on_layer"],
                                                                         cr["test_pour"]["signal_length_on_layer"])]
why = []
if any(n for t, n in fresh_by_type.items() if t != "starved_thermal"):
    why.append("new DRC violations other than starved_thermal")
if vip and not A.allow_via_in_pad:
    why.append("%d added via(s) on an SMD pad" % len(vip))
L += ["", "Result valid: %s." % ("yes" if invalid == 0 else "NO - " + "; ".join(why)),
      "", "Valid means that the routing added no defect. The board is not finished: the plane nets are open, and "
      "%d new starved thermal(s) must be cleared before fabrication." % fresh_by_type.get("starved_thermal", 0),
      "", "## DRC violations by type", "",
      "New = violations of the routed board that the baseline does not have (same type, items and position).", "",
      "| Type | Baseline | Routed | New |", "|---|---|---|---|"]
for t in types:
    L.append("| %s | %d | %d | %d |" % (t, base["violations"].get(t, 0), rt["violations"].get(t, 0), fresh_by_type.get(t, 0)))
if fresh_id:
    L += ["", "## New violations (routed board; KiCad frame, mm)", ""]
    rows_ = sorted(fresh_id)
    L += ["- %s: %s" % k for k in rows_[:30]]
    if len(rows_) > 30:
        L.append("- ... %d more in %s_drc.json" % (len(rows_) - 30, os.path.basename(A.out)))
if vip:
    L += ["", "## Added vias on SMD pads (KiCad frame, mm)", ""]
    L += ["- (%.2f, %.2f) %s of %s, via net %s" % (mm(v[0]), mm(v[1]), v[2], v[3], v[4]) for v in vip[:30]]
    if len(vip) > 30:
        L.append("- ... %d more" % (len(vip) - 30))
L += ["", "## Pour islands (>= %.1f mm2)" % A.min_island, "", "| Zone | Kind | Baseline | Routed |", "|---|---|---|---|"]
for k in sorted(set(cb["hard"]) | set(cr["hard"])):
    L.append("| %s | hard (ranked) | %s | %s |" % (k, cb["hard"].get(k, "-"), cr["hard"].get(k, "-")))
for k in sorted(set(cb["soft"]) | set(cr["soft"])):
    L.append("| %s | soft fill (information) | %s | %s |" % (k, cb["soft"].get(k, "-"), cr["soft"].get(k, "-")))
if "test_pour" in cr:
    L += ["", "## Trial pour pieces (area mm2 at KiCad x, y), largest first", "",
          ", ".join("%.2f at (%.1f, %.1f)" % tuple(i) for i in cr["test_pour"]["list"])]
if rt["open_by_net"]:
    L += ["", "## Open connections by net", "",
          ", ".join("%s %d" % kv for kv in sorted(rt["open_by_net"].items(), key=lambda kv: -kv[1]))]
L += ["", "Rank vector (lower is better, compared left to right): open non-plane connections %d, new DRC "
      "violations %d, extra pour islands %d, added vias not on plane or pour nets %d, track length %.0f mm." % tuple(rank)]
open(A.out + ".md", "w", encoding="utf-8").write("\n".join(L) + "\n")
print("\n".join(L))
