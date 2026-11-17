"""Copy the Value, MPN, Manufacturer and Note fields of the exported netlist onto the board footprints (no geometry
change; operator ruling 2026-11-13, Review 1/2; Value and Manufacturer added for D-67, the U101 TCKE1401NM change).
Usage (pcbnew venv): python gen/sync_fields.py cr/cr.kicad_pcb cr/cr.net [--add-missing]
Since 2026-11-14 (BOM-11 sync), an MPN, Manufacturer or Note field that the netlist no longer carries for a reference
is cleared on the footprint (C101 lost its TODO note), and the script calls wx.DisableAsserts().
Since 2026-11-15 (phase C, REVIEW2 R2-BOM-2): with --add-missing, a netlist MPN, Manufacturer or Note field that the
footprint does not have is added. The new field copies the text attributes of the footprint's own Value field
(layer, size, position) and is hidden, so no plotted layer and no copper changes. Without the flag the script
updates existing fields only, as before; it then lists each missing field that it did not add."""
import re
import sys
import pcbnew
import wx

wx.DisableAsserts()

args = [a for a in sys.argv[1:] if not a.startswith("--")]
ADD = "--add-missing" in sys.argv[1:]
board, net = args[0], args[1]
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
        if fld is None:
            if not v:
                continue
            if not ADD:
                print("missing (not added; use --add-missing)", fp.GetReference(), k)
                continue
            src = fp.Value()                                  # hidden-field template: the Value field attributes
            nf = pcbnew.PCB_FIELD(src, fp.GetNextFieldId(), k)
            nf.SetParent(fp)
            nf.SetText(v)
            nf.SetVisible(False)
            fp.AddField(nf)
            n += 1
            print("added", fp.GetReference(), k, v)
        elif fld.GetText() != v:
            fld.SetText(v)
            n += 1
            print("updated", fp.GetReference(), k, v)
    if fp.GetReference() in want:
        for k in ("MPN", "Manufacturer", "Note"):
            fld = fp.GetFieldByName(k)
            if k not in w and fld is not None and fld.GetText():
                fld.SetText("")
                n += 1
                print("cleared", fp.GetReference(), k)
if n:
    b.Save(board)
print("fields updated:", n)
