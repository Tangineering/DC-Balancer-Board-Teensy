"""Characterisation of the overdrive-dependent TLV3012B model (tlv3012b_od in ../models/permit_behavioural.lib).

A single comparator at VS 3.3 V receives an input step from 100 mV before the threshold to VOD beyond it (the SBOS300C
Table 6.10 test: VSTEP 200 mV at VOD 100 mV) and a ramp at the slew of the T2-race UVB input. The delay from the threshold crossing
to the output crossing VS / 2 is compared with the values read from SBOS300C Figures 8-12 and 8-13.
Called by run.py; can also run alone (python od_check.py).
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
from ngspice_run import run_deck  # noqa: E402

LIB = os.path.abspath(os.path.join(HERE, "..", "models", "permit_behavioural.lib")).replace("\\", "/")
VODS = (5e-3, 10e-3, 30e-3, 100e-3, 500e-3)
# values read from SBOS300C Figures 8-12 (tPHL) and 8-13 (tPLH), VS 3.3 V, 25 C
FIG_HL = {5e-3: 8.0e-6, 10e-3: 5.0e-6, 30e-3: 2.4e-6, 100e-3: 1.3e-6, 500e-3: 1.1e-6}
FIG_LH = {5e-3: 6.0e-6, 10e-3: 4.3e-6, 30e-3: 2.0e-6, 100e-3: 1.25e-6, 500e-3: 0.9e-6}
TPD100 = (1.3e-6, 2.0e-6, 4.0e-6)


def deck(tpd100, direction, vod=None, slew=None):
    """direction 'hl' (IN+ falls through IN- = 1.0 V) or 'lh'; a step of 200 mV ending vod beyond, or a ramp."""
    t0 = 100e-6
    if slew is None:
        # start 100 mV on the far side of the threshold (the Table 6.10 VSTEP 200 mV at VOD 100 mV), end vod beyond it
        a, b = (1.1, 1.0 - vod) if direction == "hl" else (0.9, 1.0 + vod)
        src = "PWL(0 %g %g %g %g %g)" % (a, t0, a, t0 + 1e-9, b)
        t_cross = t0 + 1e-9 * 0.1 / (0.1 + vod)
    else:
        sgn = -1 if direction == "hl" else 1
        a = 1.0 - sgn * 0.1
        t_cross = t0 + 0.1 / slew
        src = "PWL(0 %g %g %g %g %g)" % (a, t0, a, t0 + 0.3 / slew, a + sgn * 0.3)
    L = ["* tlv3012b_od characterisation", ".include '%s'" % LIB,
         "Vs vp 0 3.3", "Vn inm 0 1.0", "Vp inp 0 %s" % src,
         "X1 out 0 inp inm ref vp tlv3012b_od vos=0 vhys=0 vpor=1.5 tpor=10u tpd100=%g" % tpd100,
         "Cl out 0 10p", ".options method=gear reltol=1e-4", ".tran 5n %g 0 5n" % (t0 + 80e-6), ".end"]
    return "\n".join(L) + "\n", t_cross


def delay(r, t_cross, direction):
    t, v = r["time"], r["out"]
    k = t > t_cross
    if direction == "hl":
        idx = np.where(k & (v < 1.65))[0]
    else:
        idx = np.where(k & (v > 1.65))[0]
    return float(t[idx[0]] - t_cross) if idx.size else float("nan")


def characterise(slews=(13e-3 / 1e-6,)):
    rows = []
    for tp in TPD100:
        for d in ("hl", "lh"):
            for vod in VODS:
                txt, tc = deck(tp, d, vod=vod)
                r = run_deck(txt, vectors=["time", "out"])
                fig = (FIG_HL if d == "hl" else FIG_LH)[vod]
                rows.append(dict(tpd100_us=tp * 1e6, direction=d, input="step", vod_mV=vod * 1e3, slew_V_per_us="",
                                 delay_us=round(delay(r, tc, d) * 1e6, 3),
                                 sbos300c_fig_us=fig * 1e6 if tp == 1.3e-6 else ""))
            for s in slews:
                txt, tc = deck(tp, d, slew=s)
                r = run_deck(txt, vectors=["time", "out"])
                rows.append(dict(tpd100_us=tp * 1e6, direction=d, input="ramp", vod_mV="", slew_V_per_us=s * 1e-6,
                                 delay_us=round(delay(r, tc, d) * 1e6, 3), sbos300c_fig_us=""))
    return rows


if __name__ == "__main__":
    for row in characterise():
        print(row)
