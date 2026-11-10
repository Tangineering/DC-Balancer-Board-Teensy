#!/usr/bin/env python3
"""Rule-B area inside the reserved tab X foot keep-out (x 60.70-64.70, y 59.26-63.26) and the MB L1 features under it.
Run: /c/Users/ricky/miniforge3/python.exe -I r7_foot_check.py"""
import importlib.util
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("r7", os.path.join(HERE, "r7_minimal_calc.py"))
r7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r7)
board = r7.load_board()
foot = (60.70, 59.26, 64.70, 63.26)
RES = 0.05
xs = np.arange(foot[0] + RES / 2, foot[2], RES)
ys = np.arange(foot[1] + RES / 2, foot[3], RES)
X, Y = np.meshgrid(xs, ys)
m, wires, polys, vias = r7.shadow_masks(board, foot, (X, Y), 1.0)
cell = RES * RES
anyng = m["POWER"] | m["3V3"] | m["SIGNAL"]
print("foot keep-out %s: area %.1f mm2, of which rule-B area (clear of non-GND +1 mm) %.1f mm2" % (
    foot, X.size * cell, (~anyng).sum() * cell))
m0, _, _, _ = r7.shadow_masks(board, foot, (X, Y), 0.0)
print("  directly over non-GND copper (no grow): %.1f mm2 (POWER %.1f, 3V3 %.1f, SIGNAL %.1f)" % (
    (m0["POWER"] | m0["3V3"] | m0["SIGNAL"]).sum() * cell, m0["POWER"].sum() * cell, m0["3V3"].sum() * cell,
    m0["SIGNAL"].sum() * cell))
print("  vias within the foot square:", [(n, x, y) for n, x, y, d in vias
                                        if foot[0] <= x <= foot[2] and foot[1] <= y <= foot[3]])
