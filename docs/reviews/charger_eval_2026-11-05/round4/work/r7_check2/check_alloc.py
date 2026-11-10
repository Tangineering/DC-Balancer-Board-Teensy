"""Item 4: adopted allocation from the stackup_area.py booking (its CR list and courtyards) and the r7 areas."""
import contextlib
import io
import math
import os
import runpy

SA = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "calc", "stackup_area.py"))
with contextlib.redirect_stdout(io.StringIO()):
    g = runpy.run_path(SA)
CR, CY, POUR, CR_FIXED = g["CR"], g["CY"], g["POUR"], g["CR_FIXED"]
bottom = sum(CY[p] for r, p, dnp, s in CR if s == "bottom")
top_parts = sum(CY[p] for r, p, dnp, s in CR if s == "top")
top = top_parts + sum(CR_FIXED.values()) + sum(POUR.values())
print("stackup_area booking: r3 bottom set %.3f mm2; top incl. fixed items and pours %.3f mm2; total %.3f" % (
    bottom, top, bottom + top))
MOVE = ["R175", "R109", "R110", "R111", "R112", "R114", "R115"]
rows = {r: (p, dnp, s) for r, p, dnp, s in CR}
mv = 0.0
for r in MOVE:
    p, dnp, s = rows[r]
    mv += CY[p]
    print("   %-5s %-5s dnp %-5s r3 side %-6s courtyard %.3f mm2" % (r, p, dnp, s, CY[p]))
print("moved %.3f mm2" % mv)
TOP_USABLE, BOT_AREA = 1084.2, 559.6
for nm, t, b in (("r3 bottom set kept", top, bottom), ("adopted A3", top + mv, bottom - mv)):
    print("%-20s top %.2f mm2 U %.2f %%; bottom %.2f mm2 U %.2f %%" % (nm, t, t / TOP_USABLE * 100, b, b / BOT_AREA * 100))
# balanced split: move m so that (top + m)/TU = (bottom - m)/BA
m = (bottom * TOP_USABLE - top * BOT_AREA) / (TOP_USABLE + BOT_AREA)
print("balanced split: move %.2f mm2 -> %.2f %% each side" % (m, (top + m) / TOP_USABLE * 100))
# bottom area cross-check: the foot keep-outs inside the bottom-rule region
print("FT2 keep-out + lane inside tab Y inset (y <= 75.50): %.2f mm2 (calc 157.0 -> 123.7 = %.1f)" % (
    5.0 * (75.50 - 68.82), 157.0 - 123.7))
fz = 4.804 * (67.80 - 65.611)
print("FT1 keep-out inside the tab X region left free by the rule (x 59.22-64.024, y 65.611-67.80): %.2f mm2 (calc %.1f)" % (
    fz, 55.1 - 44.3))
