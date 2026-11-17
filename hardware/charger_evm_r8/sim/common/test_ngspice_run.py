"""Verification tests for ngspice_run.py.

Run:  C:/Users/ricky/miniforge3/python.exe test_ngspice_run.py
  or  C:/Users/ricky/miniforge3/python.exe ngspice_run.py --selftest
Prints one PASS/FAIL line per test (ASCII only) and returns exit code 0 when all pass.
"""
from __future__ import annotations

import math
import os
import sys
import traceback

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ngspice_run as ng  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def rc_transient_vs_analytic():
    """RC step: v(out) = 1 - exp(-t/RC), RC = 1 ms; max error over 0..5 ms < 1 mV."""
    deck = """* rc step
V1 in 0 PWL(0 0 1n 1)
R1 in out 1k
C1 out 0 1u
.tran 1u 5m 0 1u
.end
"""
    r = ng.run_deck(deck, vectors=["time", "out"])
    assert r.ok, r.errors
    t, v = r["time"], r["out"]
    err = np.max(np.abs(v - (1 - np.exp(-np.maximum(t - 1e-9, 0) / 1e-3))))
    assert err < 1e-3, f"max error {err:.3e} V"
    return f"max |error| = {err:.2e} V over {len(t)} points"


@test
def dc_sweep_divider():
    """DC sweep of a 3:1 divider; v(out) = vin/4 exactly."""
    deck = """* dc sweep
V1 in 0 0
R1 in out 3k
R2 out 0 1k
.dc V1 0 20 0.5
.end
"""
    r = ng.run_deck(deck)
    assert r.ok, r.errors
    vin = r["v-sweep"] if "v-sweep" in r.vec else r["v1"]
    err = np.max(np.abs(r["out"] - vin / 4))
    assert err < 1e-9 and len(vin) == 41, (err, len(vin))
    return f"41 points, max |error| = {err:.1e} V"


@test
def meas_capture():
    """.meas FIND/WHEN/AVG are parsed from stdout into SimResult.meas."""
    deck = """* meas
V1 in 0 PWL(0 0 1n 1)
R1 in out 1k
C1 out 0 1u
.tran 1u 5m 0 1u
.meas tran v_at_tau FIND v(out) AT=1m
.meas tran t_half WHEN v(out)=0.5 RISE=1
.meas tran vavg AVG v(out) FROM=0 TO=5m
.end
"""
    r = ng.run_deck(deck)
    assert r.ok, r.errors
    m = r.meas
    assert abs(m["v_at_tau"] - (1 - math.exp(-1))) < 1e-3, m
    assert abs(m["t_half"] - 1e-3 * math.log(2)) < 5e-6, m
    exp_avg = 1 - (1e-3 / 5e-3) * (1 - math.exp(-5))
    assert abs(m["vavg"] - exp_avg) < 2e-3, m
    return f"v_at_tau={m['v_at_tau']:.5f} t_half={m['t_half']:.4e} vavg={m['vavg']:.4f}"


@test
def bsource_behavioural():
    """B-source with a nonlinear expression and a ternary: V = v(a)^2 for v(a)>1 else 0."""
    deck = """* bsrc
V1 a 0 0
B1 y 0 V = v(a) > 1 ? v(a)*v(a) : 0
R1 y 0 1k
B2 z 0 I = 1m*tanh(v(a))
R2 z 0 1k
.dc V1 0 3 0.1
.end
"""
    r = ng.run_deck(deck)
    assert r.ok, r.errors
    a = r["v-sweep"] if "v-sweep" in r.vec else r["v1"]
    expect_y = np.where(a > 1, a * a, 0)
    # B2 sources 1m*tanh into node z from ground side: current flows from y-node? check sign
    e1 = np.max(np.abs(r["y"] - expect_y)[np.abs(a - 1) > 1e-6])
    e2 = np.max(np.abs(np.abs(r["z"]) - np.tanh(a)))
    assert e1 < 1e-9 and e2 < 1e-9, (e1, e2)
    return f"ternary err {e1:.1e}, I-source err {e2:.1e} (sign: v(z)={r['z'][-1]:+.3f} at a=3)"


@test
def xspice_digital_and_with_bridges():
    """adc_bridge -> d_and -> d_inverter -> dac_bridge; output is NAND of two clocks."""
    deck = """* xspice
V1 a 0 PULSE(0 3.3 0 1n 1n 10u 20u)
V2 b 0 PULSE(0 3.3 0 1n 1n 20u 40u)
aadc [a b] [da db] adc1
.model adc1 adc_bridge(in_low=1.0 in_high=2.0)
aand [da db] dy and1
.model and1 d_and(rise_delay=1n fall_delay=1n)
aor [da db] dor or1
.model or1 d_or(rise_delay=1n fall_delay=1n)
ainv dy dyn inv1
.model inv1 d_inverter(rise_delay=1n fall_delay=1n)
adac [dyn dor] [y o] dac1
.model dac1 dac_bridge(out_low=0 out_high=3.3 t_rise=10n t_fall=10n)
R1 y 0 10k
R2 o 0 10k
.tran 0.1u 80u 0 0.1u
.end
"""
    r = ng.run_deck(deck)
    assert r.ok, r.errors
    t, a, b, y, o = r["time"], r["a"], r["b"], r["y"], r["o"]
    sel = np.ones_like(t, dtype=bool)
    for edge in np.arange(0, 81e-6, 10e-6):     # skip 0.5 us around each input edge
        sel &= np.abs(t - edge) > 0.5e-6
    ah, bh = a[sel] > 1.65, b[sel] > 1.65
    nand_ok = np.all((y[sel] > 1.65) == ~(ah & bh))
    or_ok = np.all((o[sel] > 1.65) == (ah | bh))
    assert nand_ok and or_ok, (nand_ok, or_ok)
    return f"NAND and OR truth tables hold on {sel.sum()} samples"


@test
def diode_model():
    """Diode with IS=1e-14, N=1: at 1 mA, Vd = N*Vt*ln(I/IS + 1) (Vt at 27 C)."""
    deck = """* diode
I1 0 a 1m
D1 a 0 dmod
.model dmod D(IS=1e-14 N=1 RS=0)
.op
.end
"""
    r = ng.run_deck(deck)
    assert r.ok, r.errors
    vt = 1.380649e-23 * 300.15 / 1.602176634e-19
    expect = vt * math.log(1e-3 / 1e-14 + 1)
    got = float(r["a"][0])
    assert abs(got - expect) < 1e-3, (got, expect)
    return f"Vd = {got:.5f} V vs analytic {expect:.5f} V"


@test
def multiple_plots_and_ac():
    """.op + .ac + .tran in one deck give separate plots; AC data come back complex."""
    deck = """* multi
V1 in 0 DC 0 AC 1 PWL(0 0 1n 1)
R1 in out 1k
C1 out 0 1u
.op
.ac dec 10 1 100k
.tran 10u 2m
.end
"""
    r = ng.run_deck(deck)
    assert r.ok, r.errors
    names = list(r.plots)
    ac = [p for p in names if p.startswith("ac")]
    tr = [p for p in names if p.startswith("tran")]
    op = [p for p in names if p.startswith("op")]
    assert ac and tr and op, names
    f = np.real(r.plots[ac[0]]["frequency"])
    h = r.plots[ac[0]]["out"]
    assert np.iscomplexobj(h)
    fc = 1 / (2 * math.pi * 1e-3)
    k = np.argmin(np.abs(f - 100))
    hexp = 1 / (1 + 1j * f[k] / fc)
    assert abs(h[k] - hexp) < 1e-6, (h[k], hexp)
    return f"plots {names}; |H(100 Hz)| = {abs(h[k]):.5f}"


@test
def psa_compat_mode():
    """ngbehavior=psa: PSpice-style VALUE={} E-source, IF() function, and a .param."""
    deck = """* psa
.param gain=2.5
V1 a 0 0
E1 y 0 VALUE={IF(V(a)>1, gain*V(a), 0)}
R1 y 0 1k
.dc V1 0 2 0.5
.end
"""
    r = ng.run_deck(deck, ngbehavior="psa")
    assert r.ok, r.errors + [r.log[-800:]]
    a = r["v-sweep"] if "v-sweep" in r.vec else r["v1"]
    expect = np.where(a > 1, 2.5 * a, 0)
    err = np.max(np.abs(r["y"] - expect)[np.abs(a - 1) > 1e-6])
    assert err < 1e-9, err
    assert "psa" in r.log.lower() or "pspice" in r.log.lower(), "compat note missing from log"
    return f"VALUE/IF evaluated, err {err:.1e}; log confirms PSpice compatibility mode"


@test
def bg_run_and_inprocess_reset():
    """bg_run path, then two in-process decks back to back (reset between runs)."""
    deck1 = "* one\nV1 a 0 1\nR1 a b 1k\nR2 b 0 1k\n.op\n.end\n"
    deck2 = "* two\nV1 a 0 3\nR1 a c 2k\nR2 c 0 1k\n.op\n.end\n"
    r0 = ng.run_deck(deck1, background=True)
    assert r0.ok and abs(r0["b"][0] - 0.5) < 1e-9, r0.errors
    ra = ng.run_deck(deck1, use_subprocess=False)
    rb = ng.run_deck(deck2, use_subprocess=False)
    assert abs(ra["b"][0] - 0.5) < 1e-9
    assert abs(rb["c"][0] - 1.0) < 1e-9 and "b" not in rb.vec, list(rb.vec)
    return "bg_run ok; in-process reset ok (second run has no stale vectors)"


@test
def deck_file_path_input():
    """run_deck accepts a path to a deck file."""
    import tempfile
    d = ng.SCRATCH_DIR if os.path.isdir(ng.SCRATCH_DIR) else None
    with tempfile.NamedTemporaryFile("w", suffix=".cir", delete=False, dir=d) as fh:
        fh.write("* file\nV1 a 0 2\nR1 a 0 1k\n.op\n.end\n")
        p = fh.name
    try:
        r = ng.run_deck(p)
        assert r.ok and abs(r["v1#branch"][0] + 2e-3) < 1e-12, r.vec
    finally:
        os.remove(p)
    return "file path accepted"


def main():
    print("ngspice version: " + ng.ngspice_version())
    nfail = 0
    for fn in TESTS:
        try:
            msg = fn()
            print(f"PASS {fn.__name__}: {msg}")
        except Exception as exc:  # noqa: BLE001
            nfail += 1
            print(f"FAIL {fn.__name__}: {exc!r}")
            traceback.print_exc(limit=2)
    print(f"{len(TESTS) - nfail}/{len(TESTS)} passed")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
