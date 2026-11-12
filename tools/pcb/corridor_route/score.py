"""Score a routed board against its unrouted baseline. Every routing method is scored by this one script, so that
results of different methods are comparable.

Usage (pcbnew venv):
  python score.py <routed.kicad_pcb> <baseline.kicad_pcb> <out_prefix> [--plane-nets /GND,/AGND]
                  [--test-pour NET:LAYER] [--label NAME]

Writes <out_prefix>.json and <out_prefix>.md. Both boards must sit beside their project files (same base name),
or kicad-cli skips the board rules and the schematic parity test. Reads the boards only.

Measures:
  open connections     unconnected items from kicad-cli DRC, split into plane nets (connected later by the
                       plane-via step or the pour) and all other nets. This is the completion measure.
  new DRC violations   violations by type on the routed board minus the same type on the baseline.
  vias, track length   total and per layer; for a --test-pour layer also the length on nets other than the pour net.
  pour islands         filled outlines per zone, baseline and routed; with --test-pour, a trial pour of NET over the
                       whole board on LAYER is filled on a copy in memory and its islands are counted.
Rank (lower is better, compared in this order): open connections on non-plane nets, new DRC violations other
than unconnected, extra pour islands, vias, track length."""
import argparse
import json
import os
import re
import subprocess
import tempfile
from collections import Counter

import pcbnew
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
ap.add_argument("--kicad-cli", default=r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe")
A = ap.parse_args()
plane = {n for n in A.plane_nets.split(",") if n}
mm = pcbnew.ToMM


def drc(board):
    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    has_sch = os.path.exists(os.path.splitext(board)[0] + ".kicad_sch")
    cmd = [A.kicad_cli, "pcb", "drc", "--format", "json", "--severity-all", "-o", tmp]
    if has_sch:
        cmd.append("--schematic-parity")
    subprocess.run(cmd + [board], capture_output=True, text=True)
    D = json.load(open(tmp, encoding="utf-8"))
    os.remove(tmp)
    viol = Counter(v["type"] for v in D.get("violations", []))
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
    return dict(violations=dict(viol), open_plane=un_plane, open_other=un_other, open_by_net=dict(by_net),
                parity=dict(parity), parity_run=has_sch)


def copper(board):
    b = pcbnew.LoadBoard(board)
    length, vias = Counter(), 0
    per_net_layer = Counter()
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            vias += 1
        else:
            ln = b.GetLayerName(t.GetLayer())
            d = mm(t.GetLength())
            length[ln] += d
            per_net_layer[(t.GetNetname(), ln)] += d
    islands = {}
    for z in b.Zones():
        if z.GetIsRuleArea():
            continue
        for lay in z.GetLayerSet().Seq():
            fl = z.GetFilledPolysList(lay)
            islands["%s@%s" % (z.GetZoneName() or z.GetNetname(), b.GetLayerName(lay))] = fl.OutlineCount()
    out = dict(vias=vias, length={k: round(v, 1) for k, v in length.items()}, islands=islands)
    if A.test_pour:
        net, layer = A.test_pour.rsplit(":", 1)
        lid = b.GetLayerID(layer)
        bb = b.GetBoardEdgesBoundingBox()
        z = pcbnew.ZONE(b)
        z.SetLayer(lid)
        z.SetNet(b.FindNet(net))
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
        fp = z.GetFilledPolysList(lid)
        areas = sorted((fp.Outline(i).Area() / 1e12 for i in range(fp.OutlineCount())), reverse=True)
        out["test_pour"] = dict(net=net, layer=layer, islands=len(areas), largest_mm2=round(areas[0], 1) if areas else 0,
                                total_mm2=round(sum(areas), 1),
                                signal_length_on_layer=round(sum(v for (n, ln), v in per_net_layer.items()
                                                                 if ln == layer and n != net), 1))
    return out


base, rt = drc(A.baseline), drc(A.routed)
cb, cr = copper(A.baseline), copper(A.routed)
types = sorted(set(base["violations"]) | set(rt["violations"]))
delta = {t: rt["violations"].get(t, 0) - base["violations"].get(t, 0) for t in types}
new_viol = sum(v for v in delta.values() if v > 0)
extra_islands = sum(max(0, cr["islands"].get(k, 0) - v) for k, v in cb["islands"].items())
if "test_pour" in cr:
    extra_islands += max(0, cr["test_pour"]["islands"] - cb["test_pour"]["islands"])
total_len = round(sum(cr["length"].values()), 1)
rank = [rt["open_other"], new_viol, extra_islands, cr["vias"], total_len]
S = dict(label=A.label, routed=os.path.abspath(A.routed), baseline=os.path.abspath(A.baseline), rank=rank,
         open_other=rt["open_other"], open_other_baseline=base["open_other"], open_plane=rt["open_plane"],
         open_by_net=rt["open_by_net"], new_violations=new_viol, violation_delta=delta,
         violations_routed=rt["violations"], violations_baseline=base["violations"], parity=rt["parity"],
         parity_run=rt["parity_run"], vias=cr["vias"], vias_baseline=cb["vias"], length=cr["length"],
         islands=cr["islands"], islands_baseline=cb["islands"], extra_islands=extra_islands,
         test_pour=cr.get("test_pour"), test_pour_baseline=cb.get("test_pour"))
json.dump(S, open(A.out + ".json", "w"), indent=1)
L = ["# Routing score%s" % ((": " + A.label) if A.label else ""), "",
     "| Measure | Baseline | Routed |", "|---|---|---|",
     "| Open connections, non-plane nets | %d | %d |" % (base["open_other"], rt["open_other"]),
     "| Open connections, plane nets (%s) | %d | %d |" % (", ".join(sorted(plane)) or "none named", base["open_plane"],
                                                         rt["open_plane"]),
     "| Vias | %d | %d |" % (cb["vias"], cr["vias"]),
     "| Track length (mm) | %s | %s |" % (cb["length"], cr["length"]),
     "| Schematic parity issues | %s | %s |" % (base["parity"] if base["parity_run"] else "not run",
                                                rt["parity"] if rt["parity_run"] else "not run")]
if "test_pour" in cr:
    L += ["| Trial pour %s on %s: islands, largest (mm2) | %d, %.0f | %d, %.0f |" % (
        cr["test_pour"]["net"], cr["test_pour"]["layer"], cb["test_pour"]["islands"], cb["test_pour"]["largest_mm2"],
        cr["test_pour"]["islands"], cr["test_pour"]["largest_mm2"]),
        "| Signal track length on the pour layer (mm) | %.0f | %.0f |" % (cb["test_pour"]["signal_length_on_layer"],
                                                                         cr["test_pour"]["signal_length_on_layer"])]
L += ["", "## DRC violations by type", "", "| Type | Baseline | Routed | New |", "|---|---|---|---|"]
for t in types:
    L.append("| %s | %d | %d | %s |" % (t, base["violations"].get(t, 0), rt["violations"].get(t, 0),
                                       ("+%d" % delta[t]) if delta[t] > 0 else str(delta[t])))
L += ["", "## Zone islands", "", "| Zone | Baseline | Routed |", "|---|---|---|"]
for k in sorted(set(cb["islands"]) | set(cr["islands"])):
    L.append("| %s | %s | %s |" % (k, cb["islands"].get(k, "-"), cr["islands"].get(k, "-")))
if rt["open_by_net"]:
    L += ["", "## Open connections by net", "",
          ", ".join("%s %d" % kv for kv in sorted(rt["open_by_net"].items(), key=lambda kv: -kv[1]))]
L += ["", "Rank vector (lower is better, compared left to right): open non-plane connections %d, new DRC "
      "violations %d, extra pour islands %d, vias %d, track length %.0f mm." % tuple(rank)]
open(A.out + ".md", "w", encoding="utf-8").write("\n".join(L) + "\n")
print("\n".join(L))
