"""Check 4, item 3: W1/W2 hard short with the round-3 in_spike model (function source extracted from r3_calc.py)."""
import ast
import os

HERE = os.path.dirname(os.path.abspath(__file__))
R3 = os.path.normpath(os.path.join(HERE, "..", "..", "..", "round3", "calc", "r3_calc.py"))
src = open(R3, encoding="utf-8").read()
tree = ast.parse(src)
fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "in_spike"][0]
code = ast.get_source_segment(src, fn)
ns = {"MB_END": False}
exec(code, ns)
in_spike = ns["in_spike"]


def lead_peak(v0, cs, lin, cin, lout, rin=0.045, ron=0.031, cout=1.0e-6, dt=1e-9, tend=12e-6):
    """same equations as r3 in_spike, recording the OUT-lead current peak (own copy)."""
    vs = vin = vout = v0
    i_in = i_out = 0.0
    t, tc, on, ipk = 0.0, None, True, 0.0
    while t < tend:
        i_in += (vs - i_in * rin - vin) / lin * dt
        i_fet = (vin - vout) / ron if on else 0.0
        i_out += vout / lout * dt
        ipk = max(ipk, i_out)
        vs -= i_in / cs * dt
        vin += (i_in - i_fet) / cin * dt
        vout += (i_fet - i_out) / cout * dt
        if on and tc is None and i_fet > 45.0:
            tc = t
        if on and tc is not None and t >= tc + 1e-6:
            on = False
        t += dt
    return ipk


for Lmm in (181.6, 199.5, 290.0, 300.0):
    lout = 0.5e-6 * Lmm / 1000.0
    worst = None
    for v0 in (16.0, 22.0):
        for cs in (5e-6, 20e-6):
            for lin in (50e-9, 150e-9):
                vpk, ioff = in_spike(v0, cs, lin, 3.4e-6, lout=lout)
                if worst is None or vpk > worst[0]:
                    worst = (vpk, ioff, v0, cs, lin)
    ip = lead_peak(worst[2], worst[3], worst[4], 3.4e-6, lout)
    print("L %.1f mm (%.1f nH): IN peak %.2f V, I_off %.1f A, lead peak %.1f A at V0 %.0f, C_S %.0f uF, L_IN %.0f nH; "
          "margin to 36 V %.2f V" % (Lmm, lout * 1e9, worst[0], worst[1], ip, worst[2], worst[3] * 1e6, worst[4] * 1e9,
                                     36 - worst[0]))
