"""Copy the Value, MPN, Manufacturer and Note fields of the exported netlist onto the board footprints (no geometry
change; operator ruling 2026-11-13, Review 1/2; Value and Manufacturer added for D-67, the U101 TCKE1401NM change).
Usage (pcbnew venv): python gen/sync_fields.py cr/cr.kicad_pcb cr/cr.net"""
import re
import sys
import pcbnew

board, net = sys.argv[1], sys.argv[2]
txt = open(net, encoding="utf-8").read()
want = {}
for ref, blk in re.findall(r'\(comp \(ref "([^"]+)"\)(.*?)\(tstamps', txt, re.S):
    f = dict(re.findall(r'\(field \(name "([^"]+)"\) "((?:[^"\\]|\\.)*)"\)', blk))
    v = re.search(r'\(value "((?:[^"\\]|\\.)*)"\)', blk)
    want[ref] = {k: f[k] for k in ("MPN", "Manufacturer", "Note") if k in f}
    if v:
        want[ref]["Value"] = v.group(1)
b = pcbnew.LoadBoard(board)
n = 0
for fp in b.GetFootprints():
    w = want.get(fp.GetReference(), {})
    for k, v in w.items():
        if k == "Value":
            if fp.GetValue() != v:
                fp.SetValue(v)
                n += 1
                print("updated", fp.GetReference(), k, v)
            continue
        fld = fp.GetFieldByName(k)
        if fld is not None and fld.GetText() != v:
            fld.SetText(v)
            n += 1
            print("updated", fp.GetReference(), k, v)
b.Save(board)
print("fields updated:", n)
