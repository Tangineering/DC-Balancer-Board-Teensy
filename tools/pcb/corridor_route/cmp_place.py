"""Compare the routing inputs of two boards: footprint placement, pad nets, zones and track count.

Usage (pcbnew venv):  python cmp_place.py <a.kicad_pcb> <b.kicad_pcb>

Use it when a new base board arrives for a study round. If the placement, the pad nets and the zones are equal,
the earlier round's runs on board A are a valid control for board B (same model, same routing problem); the track
count is printed for information (locked power tracks count). Positions are in the KiCad frame, rounded to 1 um.
Exit status 0 when placement, pad nets and zones are equal, 1 otherwise."""
import sys

import pcbnew

try:
    import wx
    wx.DisableAsserts()
except Exception:
    pass


def summary(path):
    b = pcbnew.LoadBoard(path)
    fp = {}
    for f in b.GetFootprints():
        p = f.GetPosition()
        fp[f.GetReference()] = (round(pcbnew.ToMM(p.x), 3), round(pcbnew.ToMM(p.y), 3),
                                round(f.GetOrientationDegrees(), 1), f.GetLayer(),
                                tuple(sorted((pd.GetNumber(), pd.GetNetname()) for pd in f.Pads())))
    zones = sorted((z.GetNetname(), z.GetZoneName(), tuple(z.GetLayerSet().Seq()), z.GetNumCorners())
                   for z in b.Zones())
    return fp, zones, len(b.GetTracks())


if len(sys.argv) != 3:
    raise SystemExit(__doc__)
A, B = summary(sys.argv[1]), summary(sys.argv[2])
fa, fb = A[0], B[0]
only_a = sorted(set(fa) - set(fb))
only_b = sorted(set(fb) - set(fa))
moved = sorted(r for r in set(fa) & set(fb) if fa[r][:4] != fb[r][:4])
renet = sorted(r for r in set(fa) & set(fb) if fa[r][4] != fb[r][4])
print("footprints %d / %d; only A %s; only B %s" % (len(fa), len(fb), only_a, only_b))
print("moved %d: %s" % (len(moved), [(r, fa[r][:4], fb[r][:4]) for r in moved[:20]]))
print("pad/net differences %d: %s" % (len(renet), renet[:20]))
print("zones equal: %s (%d / %d); tracks %d / %d" % (A[1] == B[1], len(A[1]), len(B[1]), A[2], B[2]))
same = not (only_a or only_b or moved or renet) and A[1] == B[1]
print("routing inputs %s" % ("EQUAL: the earlier runs on A are a control for B" if same else "DIFFER"))
sys.exit(0 if same else 1)
