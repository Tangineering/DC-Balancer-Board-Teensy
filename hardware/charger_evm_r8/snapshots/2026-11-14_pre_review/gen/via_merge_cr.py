"""D-65: remove same-net via pairs that only hop to In2 for a short stub, and the GND stitching vias at the
J101.9 pad and the tight mask gaps, on the routed CR without rerouting it.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/via_merge_cr.py <in.kicad_pcb> <out.kicad_pcb>
(stage 2 runs in a child process of the same script)
The input is the board of commit e1f05d4 (cr/cr.kicad_pcb after the operator's routing cleanup). Load the input
next to a copy of cr/cr.kicad_pro and cr/cr.kicad_dru with the same basename: the zone filler takes the board
minimums from the project (D-57 build note), and a missing project leaves the J102 NPTH pegs 0.2505 mm from the
GND pours.

Stage 1, per pair: the In2 track chain between the two vias is deleted. With "both" the two vias are deleted;
with "A" only via A is deleted and via B keeps its other inner tracks. An F.Cu track of the existing F.Cu width
joins the two former via centres. Stage 2 merges the two F.Cu tracks that meet at each deleted via centre into
one straight segment. DRC must stay at 0 violations and 0 unconnected items; the GATE pair at (42.46, 64.93) /
(43.91, 64.78) was tested and is kept, because its F.Cu link crosses /QF.
"""
import json
import subprocess
import sys
import pcbnew

MM = pcbnew.ToMM
KEEP = []  # removed items stay referenced: freeing their wrappers corrupts the board (access violation in Zones())
TOL = 20000  # nm, L1 distance: the coordinates below are rounded to 0.01 mm or 0.001 mm

# label, via A (mm), via B (mm), which go
PAIRS = [
    ("SDA", (47.19, 42.53), (47.64, 42.37), "both"),
    ("SCL", (47.26, 45.27), (47.87, 45.65), "both"),
    ("TS_EXT", (22.19, 40.01), (22.65, 40.24), "both"),
    ("J3V3_1", (36.44, 48.62), (36.90, 48.70), "both"),
    ("N_H1M", (31.18, 55.56), (31.41, 55.94), "A"),
    ("N_FNP", (29.51, 64.09), (29.74, 63.71), "A"),
    ("N_UVP", (33.55, 54.18), (34.08, 54.49), "A"),
    ("3V3 U105", (36.06, 70.11), (36.14, 70.57), "A"),
    ("3V3 C125", (34.00, 73.54), (34.54, 73.23), "A"),
    ("3V3 leaf 71.86", (35.908, 71.863), (36.136, 70.568), "A"),
    ("3V3 leaf 69.04", (45.737, 69.044), (45.052, 70.11), "A"),
]
# trackless /GND stitching vias: on J101.9 (D-37) and 0.076 mm from the J101.7 mask; C129.1; J101.11
GND_VIAS = [(48.47, 35.10), (37.50, 53.97), (36.78, 56.26)]


def xy(p):
    return (p.x, p.y) if hasattr(p, "x") else p


def near(p, q):
    p, q = xy(p), xy(q)
    return abs(p[0] - q[0]) + abs(p[1] - q[1]) < TOL


def mmpt(x, y):
    return (pcbnew.FromMM(x), pcbnew.FromMM(y))


def via_at(b, x, y):
    r = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA" and near(t.GetPosition(), mmpt(x, y))]
    assert len(r) == 1, (x, y, len(r))
    return r[0]


def stage1(b, log):
    plan, gone = [], []
    for name, a, c, rm in PAIRS:
        va, vc = via_at(b, *a), via_at(b, *c)
        pa, pc = xy(va.GetPosition()), xy(vc.GetPosition())
        inner = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetCode() == va.GetNetCode()
                 and t.GetLayer() != pcbnew.F_Cu]
        path, node, seen = [], pa, set()
        while not near(node, pc):
            nxt = [t for t in inner if id(t) not in seen and (near(t.GetStart(), node) or near(t.GetEnd(), node))]
            assert nxt, (name, "no inner chain between the vias")
            far = lambda t: xy(t.GetEnd()) if near(t.GetStart(), node) else xy(t.GetStart())
            t = min(nxt, key=lambda t: abs(far(t)[0] - pc[0]) + abs(far(t)[1] - pc[1]))
            seen.add(id(t)); path.append(t); node = far(t)
            assert len(path) < 10, (name, "inner chain too long")
        rem = [va, vc] if rm == "both" else [va]
        for v in rem:
            other = [t for t in inner if t not in path
                     and (near(t.GetStart(), v.GetPosition()) or near(t.GetEnd(), v.GetPosition()))]
            assert not other, (name, "a deleted via carries other inner tracks")
        ftr = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetLayer() == pcbnew.F_Cu
               and any(near(e, q) for e in (t.GetStart(), t.GetEnd()) for q in (pa, pc))]
        plan.append((path, rem, pa, pc, ftr[0].GetWidth(), va.GetNetCode()))
        gone += [xy(v.GetPosition()) for v in rem]
        log.append("%s: %d via(s) and %d In2 segment(s) deleted" % (name, len(rem), len(path)))
    for path, rem, pa, pc, w, nc in plan:
        for t in path:
            b.Remove(t); KEEP.append(t)
        for v in rem:
            b.Remove(v); KEEP.append(v)
        nt = pcbnew.PCB_TRACK(b); nt.SetStart(pcbnew.VECTOR2I(*pa)); nt.SetEnd(pcbnew.VECTOR2I(*pc))
        nt.SetLayer(pcbnew.F_Cu); nt.SetWidth(w); nt.SetNetCode(nc); b.Add(nt)
    gv = [via_at(b, x, y) for x, y in GND_VIAS]
    for v in gv:
        b.Remove(v); KEEP.append(v)
    log.append("%d /GND stitching vias deleted" % len(gv))
    return gone


def stage2(b, gone, log):
    for q in gone:
        tr = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetLayer() == pcbnew.F_Cu
              and (near(t.GetStart(), q) or near(t.GetEnd(), q))]
        vias = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA" and near(t.GetPosition(), q)]
        if len(tr) != 2 or vias:
            log.append("(%.3f, %.3f): not merged (%d F.Cu tracks, %d vias)" % (MM(q[0]), MM(q[1]), len(tr), len(vias)))
            continue
        ends = [xy(t.GetEnd()) if near(t.GetStart(), q) else xy(t.GetStart()) for t in tr]
        w, nc = tr[0].GetWidth(), tr[0].GetNetCode()
        for t in tr:
            b.Remove(t); KEEP.append(t)
        nt = pcbnew.PCB_TRACK(b); nt.SetStart(pcbnew.VECTOR2I(*ends[0])); nt.SetEnd(pcbnew.VECTOR2I(*ends[1]))
        nt.SetLayer(pcbnew.F_Cu); nt.SetWidth(w); nt.SetNetCode(nc); b.Add(nt)


def main():
    if sys.argv[1] == "--stage2":  # second process: the SWIG wrappers of a board are unreliable after Remove/Add
        dst, gone = sys.argv[2], json.loads(sys.argv[3])
        log = []
        b = pcbnew.LoadBoard(dst)
        stage2(b, [tuple(q) for q in gone], log)
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        b.Save(dst)
        print("\n".join(log))
        return
    src, dst = sys.argv[1], sys.argv[2]
    log = []
    b = pcbnew.LoadBoard(src)
    gone = stage1(b, log)  # every item is looked up before the first Remove
    b.Save(dst)
    print("\n".join(log), flush=True)
    subprocess.run([sys.executable, __file__, "--stage2", dst, json.dumps(gone)], check=True)


if __name__ == "__main__":
    main()
