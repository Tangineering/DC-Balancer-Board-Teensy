"""(i) W3/W4 routes with the EVM corner used only when the direct line meets the EVM rectangle."""
import math

d = lambda a, b: math.hypot(a[0] - b[0], a[1] - b[1])  # noqa: E731
MB_TOP, xs, evy = 98.044, -27.43, 118.044
evr = xs + 88.90
for name, py in (("W3", 24.193), ("W4", 34.353)):
    src = (24.3, 45.4) if name == "W3" else (24.3, 55.6)
    pin = (xs + 82.487, evy + py)
    app = (xs + 86.488 + 10.0, pin[1])
    best = None
    for i in range(0, 181):
        xa = 56.0 + 0.05 * i
        for k in range(0, 260):
            xb = 56.0 + 0.05 * k
            if xb > 68.91:
                break
            xe = xb + (app[0] - xb) * (evy - MB_TOP) / (app[1] - MB_TOP)
            mid = [] if xe >= evr else [(evr, evy)]
            pts = [src, (xa, 68.3), (xb, MB_TOP)] + mid + [app, pin]
            L = sum(d(pts[q], pts[q + 1]) for q in range(len(pts) - 1))
            tie = math.hypot(max(0.0, xb - 65.0), MB_TOP - 68.3)
            if best is None or L < best[0]:
                best = (L, xb, tie)
    print("%s route %.1f mm, build max %d, x2 %.2f, chassis tie %.2f" % (
        name, best[0], math.ceil(1.25 * best[0] / 10 - 1e-9) * 10, best[1], best[2]))
