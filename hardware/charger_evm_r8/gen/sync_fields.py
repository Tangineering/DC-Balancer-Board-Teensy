"""Copy the MPN and Note fields of the exported netlist onto the board footprints (no geometry change; operator
ruling 2026-11-13, Review 1/2). Usage (pcbnew venv): python gen/sync_fields.py cr/cr.kicad_pcb cr/cr.net"""
import re
import sys
import pcbnew

board, net = sys.argv[1], sys.argv[2]
txt = open(net, encoding="utf-8").read()
want = {}
for ref, blk in re.findall(r'\(comp \(ref "([^"]+)"\)(.*?)\(tstamps', txt, re.S):
    f = dict(re.findall(r'\(field \(name "([^"]+)"\) "((?:[^"\\]|\\.)*)"\)', blk))
    want[ref] = {k: f[k] for k in ("MPN", "Note") if k in f}
b = pcbnew.LoadBoard(board)
n = 0
for fp in b.GetFootprints():
    w = want.get(fp.GetReference(), {})
    for k, v in w.items():
        fld = fp.GetFieldByName(k)
        if fld is not None and fld.GetText() != v:
            fld.SetText(v)
            n += 1
            print("updated", fp.GetReference(), k)
b.Save(board)
print("fields updated:", n)
