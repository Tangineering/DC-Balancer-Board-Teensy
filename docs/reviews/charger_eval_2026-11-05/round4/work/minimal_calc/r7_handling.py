#!/usr/bin/env python3
"""Handling push of 10 N normal to the MB at each tab tip (elastic pin-group model of round4/work/mb_pinload.py), and
the y-mirror check of tab X against the LM1084 / CO-5V bodies (.brd bboxes from round4/calc/mb_neighbours_out.txt).
Run: /c/Users/ricky/miniforge3/python.exe -I r7_handling.py"""
PA = [(20.998, 36.544 + 2.54 * k) for k in range(12)]   # design A.8
PB = [(45.998, 39.084 + 2.54 * k) for k in range(10)]
P = PA + PB
xc = sum(p[0] for p in P) / 22
yc = sum(p[1] for p in P) / 22
sxx = sum((p[0] - xc) ** 2 for p in P)
syy = sum((p[1] - yc) ** 2 for p in P)
for name, (tx, ty) in (("tab X tip (65.00, 62.30)", (65.00, 62.30)), ("tab Y tip (28.71, 76.51)", (28.71, 76.51))):
    F = 10.0
    loads = [F / 22 + F * (tx - xc) * (p[0] - xc) / sxx + F * (ty - yc) * (p[1] - yc) / syy for p in P]
    i = max(range(22), key=lambda k: loads[k])
    print("%s: worst pin at %s carries %.2f N for a 10 N push" % (name, P[i], loads[i]))
yc_m = (36.544 + 64.484) / 2
tab = (48.70, 56.30, 65.00, 68.30)
m = (tab[0], 2 * yc_m - tab[3], tab[2], 2 * yc_m - tab[1])
print("mirror axis y = %.3f; tab X mirrored to %s" % (yc_m, [round(v, 2) for v in m]))
for nm, b, h in (("REG-5V", (50.97, 36.87, 62.31, 54.51), 4.83), ("CO-5V", (49.30, 37.27, 52.30, 41.98), 2.10)):
    ov = max(0, min(m[2], b[2]) - max(m[0], b[0])) * max(0, min(m[3], b[3]) - max(m[1], b[1]))
    print("  overlap with %s (height %.2f mm vs 2.54 mm standoff): %.1f mm2 -> %s" % (
        nm, h, ov, "cannot seat" if (ov > 0 and h > 2.54) else "seats"))
