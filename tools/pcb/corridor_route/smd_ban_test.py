"""Test of the router's SMD via ban (review N-5, 2026-11-13).

Usage: "$PY" smd_ban_test.py <model.json> <plan.json> [--pad REF.PAD ...]

For every SMD pad of the model (a pad item without its own drill) that the plan does not admit through
rules.via_in_pad, the test asserts that no grid cell whose centre lies inside the pad outline, grown by the via
radius and the mask margin less one grid step, is a legal via cell (Ctx.ownV != BLOCK) on the pad's layer.
--pad names pads that must be present and tested (the test fails if one is missing); the CR default is U101.25,
the exposed pad whose nine thermal vias are holes with the same number.

A second check rebuilds the ban with the old (ref, number) key and reports whether the named pads would have
escaped it, so the test shows the defect it guards against. Exit code 0: pass; 1: fail.
"""
import argparse
import sys

import numpy as np
import shapely
from shapely.geometry import Polygon

sys.path.insert(0, ".")
from core import BLOCK, Ctx  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("model")
ap.add_argument("plan")
ap.add_argument("--pad", action="append", default=None)
A = ap.parse_args()
must = A.pad if A.pad is not None else ["U101.25"]

C = Ctx(A.model, A.plan)
items = C.D["items"]
if not any("drilled" in it for it in items if it["kind"] == "pad"):
    print("FAIL: the model has no 'drilled' field on its pads; rebuild it with board_model.py")
    sys.exit(1)
vip = set(C.via_in_pad) if isinstance(C.via_in_pad, list) else set()
drilled_old = {(it.get("ref"), it.get("num")) for it in items if it["kind"] == "hole"}
grow = max(C.via / 2 + C.mask_margin - C.R, 0.0)
fails, tested, escaped_old = [], set(), set()
for it in items:
    if it["kind"] != "pad" or it["drilled"]:
        continue
    name = "%s.%s" % (it.get("ref"), it.get("num"))
    if C.via_in_pad is True or name in vip:
        continue
    for ln in it["layers"]:
        if ln not in C.LAYERS:
            continue
        li = C.LAYERS.index(ln)
        g = Polygon(it["poly"]).buffer(0).buffer(grow)
        m = shapely.contains_xy(g, C.X, C.Y)
        n_in = int(m.sum())
        n_legal = int((C.ownV[li][m] != BLOCK).sum())
        tested.add(name)
        if (it.get("ref"), it.get("num")) in drilled_old:
            escaped_old.add(name)
        if n_legal:
            fails.append("%s %s: %d of %d cells inside the pad + via radius + mask margin are legal via cells"
                         % (name, ln, n_legal, n_in))
missing = [p for p in must if p not in tested]
print("SMD pads tested: %d; named pads: %s" % (len(tested), ", ".join(must) or "none"))
print("Pads that the old (ref, number) key would have exempted: %s" % (", ".join(sorted(escaped_old)) or "none"))
for p in missing:
    fails.append("%s: not tested (not an SMD pad of the model, or admitted by rules.via_in_pad)" % p)
for f in fails:
    print("FAIL: " + f)
print("PASS" if not fails else "FAIL (%d)" % len(fails))
sys.exit(1 if fails else 0)
