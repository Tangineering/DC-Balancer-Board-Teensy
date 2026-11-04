#!/usr/bin/env python3
"""drive_ripple.py -- the once-per-flywheel-revolution drive-loop ripple: the
small-signal PREDICTOR, the frozen fw v35 coefficient reference, an offline
closed-loop SIMULATOR of the same recursion, and the LOCK-IN analysis the HIL
suite scores the `drive-ripple-*` scenarios with (2026-11-04).

WHY THIS EXISTS.  fw v37 re-synthesised the drive law at a lower crossover so
that a once-per-revolution ripple in `v_actual` becomes less motor-current
ripple (docs/fw37_planning_2026-11-04.md sections 6.1 and 9.1).  The HIL plant's
flywheel is perfectly smooth, so no pre-existing scenario contains that
disturbance.  hil_plant_sim.Plant now carries two scenario-level ripple hooks
(a MEASUREMENT ripple on the injected speed - the encoder-artefact hypothesis -
and a FORCE ripple in the mechanics - the real-speed-ripple hypothesis), and
this module says what the board's `current` must do in each case.

STDLIB ONLY, deliberately: hil_plant_sim.py and run_hil_suite.py import nothing
outside the standard library, and neither may grow a numpy dependency through
this module.  ⚠️ BOTH NOW IMPORT IT AT MODULE LOAD (2026-11-04): this file must
sit beside them in tools/, or neither imports at all.  Complex arithmetic and a 5x5 complex solve are all it needs.

⚠️ CONSTANTS_HASH.  This module is NOT one of the three modules
`hil_plant_sim.collect_model_constants()` sweeps (h2_map, hil_electrical,
hil_plant_sim), and hil_plant_sim imports it as a MODULE (`import
drive_ripple`), never `from drive_ripple import NAME` - a from-import would
re-export its UPPERCASE numerics into hil_plant_sim's namespace, where the
sweep WOULD record them and move every run's `constants_hash` on a commit that
changed no plant model value.

The loop being predicted (every term cited where it is used below):

    plant      G(s) = K_F / (M_EFF s + B_lin)          [m/s per A]
               (hil_plant_sim.Plant.step(); the Coulomb term is a constant
                force at cruise and has no small-signal part; B_lin = B_EFF on
                the `rig` road load, 2 k_air v on a compensated one)
    controller C(z) = DD + CD (zI - AD)^-1 BD          [A per m/s]
               (teensy_controller/drive_controller_coeffs.h, z = e^{j w Ts},
                Ts = DRIVE_CTRL_TS_US; the Hanus conditioning term is zero while
                unsaturated, so the LINEAR law is exactly the state space)
    latency    e^{-j w tau},  tau = Ts_eff/2 (the controller's own ZOH)
                                  + HIL_LOOP_DELAY_S (the HIL pipeline)
               (Ts_eff in DRIVE_TS_EFF_BAND_S: the board's re-armed 2 ms gate)
    L = C G e^{-j w tau},  S = 1/(1+L),  T = L/(1+L)

    measurement ripple n (injected speed = v_true + n):
        i_cmd = -C S n        -> |i| = |C S| A_meas
        v_inj =  S n,  v_true = -T n   -> true/injected ratio = |L|
    force ripple d (net force + d):
        v_true = v_inj = S d / (M s + B)
        i_cmd  = -T d / K_F   -> |i| = |T| F_rip / K_F
"""

import cmath
import math
import os
import re

# ─────────────────────────────────────────────────────────────────────────────
# Geometry.  FLYWHEEL_RADIUS_M is the firmware's own constant
# (teensy_controller/teensy_controller.ino:2740, `#define FLYWHEEL_RADIUS_M
# 0.0762f`, measured 3.00 in, 2026-08-13); f_rot = v / (2 pi R) = 2.089 Hz per
# m/s, the line docs/fw37_planning_2026-11-04.md section 6.1 finds in 635/635
# steady-speed windows of the Pi bags.
# ─────────────────────────────────────────────────────────────────────────────
FLYWHEEL_RADIUS_M = 0.0762


def f_rot_hz(v_mps):
    """Once-per-revolution frequency of the flywheel at speed v [Hz]."""
    return abs(float(v_mps)) / (2.0 * math.pi * FLYWHEEL_RADIUS_M)


# ─────────────────────────────────────────────────────────────────────────────
# The HIL pipeline's latency, OUTSIDE the controller's own ZOH.
#
# RE-DERIVED 2026-11-04 (fix round, review M1).  The first cut itemised five
# half-tick terms that summed to 1.0 ms while quoting 1.5, and counted the
# forward-Euler hold and the host pickup as two lags when they are one
# sample-and-hold.  The derivation now goes through the ONE quantity that is
# actually an integer: the host-tick round trip.
#
# At the host's 1 kHz tick (hil_plant_sim.main(): rx obs -> Plant.step() ->
# pack_inject()), the board's 1 kHz millis-gated observation send (.ino:4681
# hilSendTick(), HIL_SEND_PERIOD_MS 1) and the drive law on its 2 ms gate
# (.ino:12759 motorControlGated(), MOTOR_CTRL_PERIOD_US 2000 :3718):
#   t_k   host tick at which the frame the controller samples was SENT
#         (the latest frame older than the controller tick by the transit d);
#   t_m   first host tick whose rx-before-step sees the observation frame
#         carrying that controller output (after the wait for the board's next
#         1 ms send, the transit d, and the wait for the host's next tick top).
# Every wait in between is absorbed into  R = t_m - t_k, an INTEGER number of
# host ticks: R = 1 whenever controller-phase + send-wait + 2d fits in one
# tick, 2 otherwise, 3 on a late loop() service.  The free-running clocks set
# the phases, and within a 6 s window they are a FIXED DRAW (the two crystals
# drift by ppm), not their mean - so a run sits at one R (or alternates
# between two adjacent ones), not at the average.
# Mapping R onto the loop's continuous-time delay:
#   -1 tick   the host steps BEFORE it sends: the frame sent at t_k already
#             carries the plant state one tick past the force applied at t_k,
#             so the shortest possible round trip (R = 1) is ZERO extra delay.
#             (This is the same fact as "step-before-pack leads by a tick" and
#             "the host applies at the next tick top", which therefore cancel
#             instead of adding, and it is why the forward-Euler one-tick hold
#             adds nothing of its own: the command only changes every
#             controller tick, so its 1 ms plant hold is nested inside the
#             controller's 2 ms ZOH, which loop_terms() carries as Ts/2.)
#   extra delay = (R - 1) ticks  in {0, 1, 2} ms.
# Verified on simulate_hold(), whose integer pipeline is exactly this
# structure: predict_hold() at (d_in + d_out) ticks matches the simulation to
# <= 0.022 % for both laws, both hooks and all four holds at d = (0,0),
# (1,1), (1,2), (2,2),
# and a free delay fit lands on 0.00 / 2.00 / 3.00 / 4.00 ms (+/- 0.02).
# Measured cross-check: the suite's `seq`-echo round trip is "L = 1 or 2
# ticks" (hil_plant_sim main(), the scp-inrush note) - R = 1 or 2.
# NOMINAL 1.0 ms (R = 2, the midpoint of the observed L = 1-2), BAND
# [0, 3] ms: R = 1..3 plus one tick for a late loop() service between frame
# arrival and updateSensors() or between the command and the send.
# ─────────────────────────────────────────────────────────────────────────────
HIL_LOOP_DELAY_S = 1.0e-3
HIL_LOOP_DELAY_BAND_S = (0.0, 3.0e-3)

# The board's EFFECTIVE drive-law period.  rateLimitDue() (.ino:3723) re-arms
# from `now`, not from `last + period`, so every controller tick is late by
# the loop() service latency and the effective period is 2000 us + that
# latency; the inner youlaController_Drive() gate (>= TS - 200 us) always
# passes.  The coefficients were discretised at 2.000 ms, so a slower clock
# time-scales the law (C evaluated at e^{j w Ts_eff}, ZOH Ts_eff/2).  The band
# is [2.0, 2.1] ms - a 100 us mean overrun, the order of one loop() iteration
# carrying a UDP drain; TODO(calibrate) against a BLG t_us census.
DRIVE_TS_EFF_BAND_S = (2.0e-3, 2.1e-3)

# ─────────────────────────────────────────────────────────────────────────────
# The scored tolerance on the measured `current` 1x amplitude against the
# prediction.  See drive_ripple_tolerance_basis() for the derivation; the
# value is fixed here so the suite's check and the docs cite one number.
# ─────────────────────────────────────────────────────────────────────────────
PREDICTION_TOL_FRAC = 0.15

# ─────────────────────────────────────────────────────────────────────────────
# The repo's CURRENT drive law: parsed from the GENERATED header at import, the
# same discipline governor_model._load_share_controller_coeffs() follows, so a
# regeneration can never leave a transcription here stale.
# ─────────────────────────────────────────────────────────────────────────────
DRIVE_COEFF_HEADER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "teensy_controller", "drive_controller_coeffs.h")

_NUM = r"-?[0-9]+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?"


def _strip_c_comments(src):
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", " ", src)


def _parse_matrix(src, name, rows, cols, path):
    m = re.search(name + r"\s*\[[^\]]*\]\s*\[[^\]]*\]\s*=\s*\{(.*?)\}\s*;",
                  src, flags=re.S)
    if m is None:
        raise RuntimeError("%s not found in %s" % (name, path))
    out = []
    for row in re.findall(r"\{([^{}]*)\}", m.group(1)):
        vals = [float(v) for v in re.findall(_NUM, row)]
        if len(vals) != cols:
            raise RuntimeError("malformed %s row in %s: %r" % (name, path, row))
        out.append(tuple(vals))
    if len(out) != rows:
        raise RuntimeError("%s has %d rows in %s, expected %d"
                           % (name, len(out), path, rows))
    return tuple(out)


def load_drive_coeffs(path=DRIVE_COEFF_HEADER):
    """Parse drive_controller_coeffs.h into the dict the functions below take.

    Comments are stripped first so a number quoted in prose cannot be picked
    up.  Raises RuntimeError on any missing or malformed field: a predictor
    built on a half-parsed header would score a board against a fiction."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        src = _strip_c_comments(fh.read())

    def _define(name):
        m = re.search(r"#define\s+" + name + r"\s+(" + _NUM + r")", src)
        if m is None:
            raise RuntimeError("%s not found in %s" % (name, path))
        return m.group(1)

    def _scalar(name):
        m = re.search(name + r"\s*=\s*(" + _NUM + r")f?\s*;", src)
        if m is None:
            raise RuntimeError("%s not found in %s" % (name, path))
        return float(m.group(1))

    n = int(_define("DRIVE_CTRL_NSTATES"))
    return {
        "source": os.path.relpath(path, os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))).replace(os.sep, "/"),
        "TS_US": int(_define("DRIVE_CTRL_TS_US")),
        "NSTATES": n,
        "KI": _scalar("DRIVE_CTRL_KI"),
        "I_MIN": _scalar("DRIVE_CTRL_I_MIN"),
        "I_MAX": _scalar("DRIVE_CTRL_I_MAX"),
        "DD": _scalar("DRIVE_CTRL_DD"),
        "AD": _parse_matrix(src, "DRIVE_CTRL_AD", n, n, path),
        "BD": tuple(r[0] for r in _parse_matrix(src, "DRIVE_CTRL_BD", n, 1, path)),
        "CD": _parse_matrix(src, "DRIVE_CTRL_CD", 1, n, path)[0],
        "L": tuple(r[0] for r in _parse_matrix(src, "DRIVE_CTRL_L", n, 1, path)),
    }


# ─────────────────────────────────────────────────────────────────────────────
# THE fw v35 DRIVE LAW, FROZEN.  Transcribed ONCE from
#     git show ab4a705:teensy_controller/drive_controller_coeffs.h
# (ab4a705 = "fw v35 (flashed on the board)"; the header there is the fw
# v18/v19 synthesis, unchanged through v36 - db59fb7 is the first commit that
# moves it).  A FROZEN REFERENCE, not a live parse, so the suite never shells
# out to git at runtime and the alternate prediction cannot drift with the
# tree.  The decimal strings are the header's own 17-significant-digit
# renderings of the float32 coefficients, so Python reads back the identical
# float32 values.  Shipped rung (planning section 9.1): WC = 60,
# Wu(0.25, 300, 12.5), crossover 15.98 rad/s design.
# ─────────────────────────────────────────────────────────────────────────────
V35_DRIVE_COEFFS = {
    "source": "git ab4a705:teensy_controller/drive_controller_coeffs.h (fw v35, frozen)",
    "TS_US": 2000,
    "NSTATES": 5,
    "KI": 7.827835513e+01,
    "I_MIN": -1.200000000e+01,
    "I_MAX": 1.200000000e+01,
    "DD": 1.71760928630828857e+00,
    "AD": (
        (1.00000000000000000e+00, 0.00000000000000000e+00, 0.00000000000000000e+00,
         0.00000000000000000e+00, 0.00000000000000000e+00),
        (0.00000000000000000e+00, 9.95453119277954102e-01, -1.55954966321587563e-02,
         1.42631642520427704e-02, 5.21950249094516039e-04),
        (0.00000000000000000e+00, -1.55954975634813309e-02, 8.99340927600860596e-01,
         1.73323512077331543e-01, 4.44363243877887726e-03),
        (0.00000000000000000e+00, -1.42631651833653450e-02, -1.73323541879653931e-01,
         5.91669917106628418e-01, -3.99195104837417603e-02),
        (0.00000000000000000e+00, -5.23665919899940491e-04, -4.45802928879857063e-03,
         -4.00532595813274384e-02, 2.28838920593261719e-01),
    ),
    "BD": (1.00000000000000000e+00, -5.94164729118347168e-02, -1.20190031826496124e-01,
           -8.77784788608551025e-02, -3.49337351508438587e-03),
    "CD": (1.56556710600852966e-01, -2.97082366943359375e+01, -6.00950164794921875e+01,
           4.38892250061035156e+01, 1.74104142189025879e+00),
    "L": (1.45551145076751709e-01, -8.58125369995832443e-03, -1.94378476589918137e-02,
          2.90428404696285725e-03, 2.40362691693007946e-03),
}


def repo_drive_coeffs():
    """The CURRENT header's law (fw v37 at the time of writing)."""
    return load_drive_coeffs(DRIVE_COEFF_HEADER)


def coeffs_sha256(c):
    """sha256 of the parsed LINEAR LAW (TS, DD, AD, BD, CD, L, clamp), over a
    canonical repr of the float values - the provenance of the law a run was
    scored against (comments and formatting in the header do not move it)."""
    import hashlib
    blob = repr((int(c["TS_US"]), float(c["DD"]),
                 tuple(tuple(float(v) for v in r) for r in c["AD"]),
                 tuple(float(v) for v in c["BD"]),
                 tuple(float(v) for v in c["CD"]),
                 tuple(float(v) for v in c["L"]),
                 float(c["I_MIN"]), float(c["I_MAX"])))
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


def coeffs_equal(a, b):
    """True when two coefficient dicts carry the same LINEAR LAW (AD/BD/CD/DD,
    TS) - used to say "the repo header IS the frozen v35 law" instead of
    printing two identical predictions as if they were alternatives."""
    return (a["TS_US"] == b["TS_US"] and a["DD"] == b["DD"]
            and tuple(a["BD"]) == tuple(b["BD"])
            and tuple(a["CD"]) == tuple(b["CD"])
            and tuple(map(tuple, a["AD"])) == tuple(map(tuple, b["AD"])))


# ─────────────────────────────────────────────────────────────────────────────
# Frequency response
# ─────────────────────────────────────────────────────────────────────────────

def _csolve(a, b):
    """Solve a x = b for a small dense complex system (Gaussian elimination
    with partial pivoting).  a: list of lists, b: list.  Returns x."""
    n = len(b)
    m = [list(a[i]) + [b[i]] for i in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) == 0.0:
            raise ZeroDivisionError("singular system in _csolve")
        m[c], m[p] = m[p], m[c]
        piv = m[c][c]
        for r in range(c + 1, n):
            f = m[r][c] / piv
            if f:
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    x = [0j] * n
    for r in range(n - 1, -1, -1):
        acc = m[r][n]
        for k in range(r + 1, n):
            acc -= m[r][k] * x[k]
        x[r] = acc / m[r][r]
    return x


def controller_response(coeffs, f_hz):
    """C(e^{j w Ts}) = DD + CD (zI - AD)^-1 BD   [A per (m/s)].

    The LINEAR law: the Hanus conditioning term L (u - u_unsat) is identically
    zero while the clamp is inactive (drive_controller.h, driveControllerStep),
    which is the regime every ripple hold is checked to be in."""
    ts = coeffs["TS_US"] * 1e-6
    z = cmath.exp(1j * 2.0 * math.pi * float(f_hz) * ts)
    n = coeffs["NSTATES"]
    ad = coeffs["AD"]
    a = [[(z if i == j else 0.0) - ad[i][j] for j in range(n)] for i in range(n)]
    x = _csolve(a, [complex(v) for v in coeffs["BD"]])
    return coeffs["DD"] + sum(coeffs["CD"][j] * x[j] for j in range(n))


def hil_plant_params(drag_mode=None, v_mps=None):
    """{m_eff, b_lin, k_f} from hil_plant_sim's OWN calibrated constants.

    Imported lazily so this module stays importable on its own (and so
    hil_plant_sim importing it is not circular).  `b_lin` is the small-signal
    road-load slope: B_EFF on the `rig` profile (the Coulomb term is constant
    while v > 0), 2 k_air |v| on a quadratic compensated profile."""
    import hil_plant_sim as _hps
    k_air = _hps.drag_k_air(drag_mode or _hps.DRAG_MODE_DEFAULT)
    if k_air == 0.0:
        b_lin = _hps.B_EFF
    else:
        b_lin = 2.0 * k_air * abs(float(v_mps or 0.0))
    return {"m_eff": _hps.M_EFF, "b_lin": b_lin, "k_f": _hps.K_F}


def loop_terms(coeffs, f_hz, plant, delay_s=HIL_LOOP_DELAY_S, ts_eff_s=None):
    """The open/closed-loop transfer values at one frequency.

    `delay_s` is the latency OUTSIDE the controller's own ZOH (see
    HIL_LOOP_DELAY_S); the ZOH's Ts/2 is added here, so passing delay_s = 0
    still models a sampled controller.  `ts_eff_s` (default: the header's
    TS) is the period the board actually steps the law at (see
    DRIVE_TS_EFF_BAND_S): the same difference equation run on a slower clock
    is the 2 ms law evaluated at f * ts_eff / ts."""
    w = 2.0 * math.pi * float(f_hz)
    ts_design = coeffs["TS_US"] * 1e-6
    ts = ts_design if ts_eff_s is None else float(ts_eff_s)
    c = controller_response(coeffs, float(f_hz) * ts / ts_design)
    mech = complex(plant["b_lin"], plant["m_eff"] * w)        # M s + B
    g = plant["k_f"] / mech
    lag = cmath.exp(-1j * w * (0.5 * ts + float(delay_s)))
    loop = c * g * lag
    s = 1.0 / (1.0 + loop)
    t = loop * s
    return {"f_hz": float(f_hz), "C": c, "G": g, "lag": lag, "L": loop,
            "S": s, "T": t, "CS": c * s, "mech": mech}


def predict_hold(coeffs, v_mps, plant, a_meas=0.0, f_rip=0.0,
                 delay_s=HIL_LOOP_DELAY_S, ts_eff_s=None):
    """Predicted 1x amplitudes at a cruise hold of speed `v_mps`.

    Returns amplitudes [A or m/s] and the current's phase relative to the
    injected-speed ripple [deg, negative = current lags].  Superposition: the
    two hooks are linear inputs to one linear loop, so a hold carrying both is
    the complex sum (the scenarios carry one each)."""
    f = f_rot_hz(v_mps)
    lt = loop_terms(coeffs, f, plant, delay_s=delay_s, ts_eff_s=ts_eff_s)
    # Complex phasors relative to the ripple's own sin(theta + phi) reference.
    n = complex(a_meas)                       # measurement ripple phasor
    d = complex(f_rip)                        # force ripple phasor
    v_true = -lt["T"] * n + lt["S"] * d / lt["mech"]
    v_inj = v_true + n
    # i = -C * lag_in * v_inj; the amplitude does not depend on how the delay
    # is split between the two pipeline legs, the phase does by < 1 deg here.
    i_cmd = -lt["C"] * lt["lag"] * v_inj
    out = {
        "v_mps": float(v_mps), "f_hz": f,
        "abs_C": abs(lt["C"]), "abs_S": abs(lt["S"]), "abs_T": abs(lt["T"]),
        "abs_L": abs(lt["L"]), "abs_CS": abs(lt["CS"]),
        "i_amp": abs(i_cmd), "v_inj_amp": abs(v_inj), "v_true_amp": abs(v_true),
        "i_phase_vs_vinj_deg": (math.degrees(cmath.phase(i_cmd / v_inj))
                                if abs(v_inj) > 0 else None),
        "true_over_inj": (abs(v_true) / abs(v_inj)) if abs(v_inj) > 0 else None,
        "delay_s": float(delay_s),
        "L_re": lt["L"].real, "L_im": lt["L"].imag,
    }
    return out


def predict_hold_band(coeffs, v_mps, plant, a_meas=0.0, f_rip=0.0,
                      band=HIL_LOOP_DELAY_BAND_S, ts_band=DRIVE_TS_EFF_BAND_S):
    """(lo, hi) of the predicted current amplitude across the latency band
    crossed with the controller-period band (a 9 x 3 grid)."""
    vals = []
    lo_d, hi_d = band
    for k in range(9):
        dly = lo_d + (hi_d - lo_d) * k / 8.0
        for j in range(3):
            ts = ts_band[0] + (ts_band[1] - ts_band[0]) * j / 2.0
            vals.append(predict_hold(coeffs, v_mps, plant, a_meas, f_rip,
                                     delay_s=dly, ts_eff_s=ts)["i_amp"])
    return min(vals), max(vals)


def drive_ripple_tolerance_basis(coeffs_list, speeds, plant, a_meas=0.0,
                                 f_rip=0.0, band=HIL_LOOP_DELAY_BAND_S,
                                 ts_band=DRIVE_TS_EFF_BAND_S):
    """The worst relative spread of the predicted amplitude across the latency
    and controller-period bands, over every law / hold given: the timing term
    of the tolerance budget (see docs/HIL_SCENARIOS.md, drive-ripple-*).
    Pass ts_band=(ts, ts) or band=(d, d) to isolate one term."""
    worst = 0.0
    for c in coeffs_list:
        for v in speeds:
            nom = predict_hold(c, v, plant, a_meas, f_rip)["i_amp"]
            lo, hi = predict_hold_band(c, v, plant, a_meas, f_rip,
                                       band=band, ts_band=ts_band)
            if nom > 0:
                worst = max(worst, (hi - nom) / nom, (nom - lo) / nom)
    return worst


def bus_ripple_signatures(i_ph, v_inj_ph, i0, v0, k_bus, loop_l):
    """The BENCH-TRANSFERABLE signature (report only; review M2).

    On bench observables alone - the motor command i, the measured speed
    v_inj and the bus current - the controller relation i = -C v_inj is the
    SAME under both hypotheses, so i / v_inj cannot discriminate.  The bus
    current can, because it is billed from the TRUE shaft power:
        I_bus = K_F i v_true / (ETA_BOOST V_bus) + const        (Plant.step)
    and to first order about (I0, v0)
        dI_bus = k_bus (v0 di + I0 dv_true),   k_bus = K_F / (ETA_BOOST V_bus).
    Hypothesis MEAS (artefact): v_inj = S n, v_true = -T n, so in bench terms
        dv_true = -L v_inj          (L the loop gain at f_rot, law-dependent)
    Hypothesis FORCE (real ripple): dv_true = v_inj.
    `i_ph`, `v_inj_ph` are complex 1x phasors (lock-in I + jQ); `loop_l` the
    complex predicted L.  Returns the two predicted bus phasors.  The model
    is exact for the simple engine; under the hi-fi engine the source
    currents are converter terminals and the gain is approximate (the
    PHASE, which is what separates the hypotheses, is not)."""
    meas = k_bus * (v0 * i_ph + i0 * (-loop_l * v_inj_ph))
    force = k_bus * (v0 * i_ph + i0 * v_inj_ph)
    return {"meas": meas, "force": force}


# ─────────────────────────────────────────────────────────────────────────────
# Offline closed-loop simulator (validation of the predictor).
#
# Reproduces, tick for tick at the host's 1 kHz:
#   * hil_plant_sim.Plant.step()'s `rig` mechanics (Coulomb + viscous, the
#     V_STICTION deadband, forward Euler) plus the two ripple hooks exactly as
#     the plant applies them;
#   * drive_controller.h driveControllerStep() (the Hanus conditioned state
#     space, double state, clamp at I_MIN/I_MAX) held over Ts by the .ino's
#     youlaController_Drive() gate;
#   * the pipeline as INTEGER-TICK delays: the controller reads the speed the
#     plant emitted `d_in` ticks earlier, and its output reaches the plant
#     `d_out` ticks after it was computed.
# Its equivalent continuous delay (for predict_hold) is
#     sim_equivalent_delay_s() = (d_in + d_out) * dt
# d = (0, 0) is the board's shortest real round trip (R = 1 in the
# HIL_LOOP_DELAY_S derivation): the command computed from the speed emitted
# at tick k acts at tick k+1, and the step-before-send lead cancels that
# tick exactly.  CORRECTED 2026-11-04 (review M1): the first cut used
# (d_in + d_out - 1) dt + dt/2, which double-counted the Euler hold; a free
# fit of the delay to the simulation gives 0.00 / 2.00 / 3.00 / 4.00 ms at
# d = (0,0) / (1,1) / (1,2) / (2,2).
# ─────────────────────────────────────────────────────────────────────────────

def sim_equivalent_delay_s(d_in=1, d_out=1, dt=1e-3):
    return (d_in + d_out) * dt


# The firmware's zero-setpoint cutoff (.ino:3652 V_SP_ZERO_THRESH = 0.07f;
# motorControl() :12704 commands 0 A and holds the controller reset below it).
V_SP_ZERO_THRESH_MPS = 0.07


def simulate_hold(coeffs, v_sp, duration_s=20.0, plant=None, a_meas=0.0,
                  a_meas2=0.0, f_rip=0.0, phase_rad=0.0, d_in=1, d_out=1,
                  dt=1e-3, v0=None, f_coulomb=None, v_stiction=None,
                  seed_dc=True):
    """Closed-loop simulation of one hold (or profile).

    `v_sp` is a constant or a callable t -> setpoint.  Returns dict of lists:
    t, theta (wrapped [0, 2 pi)), v_true, v_inj, current, u_unsat, v_sp.
    With `seed_dc` (the default) the run starts at `v0` (default: the
    setpoint at t = 0) with the controller state seeded at the DC operating
    point, so a hold does not spend its window settling the integrator; with
    seed_dc=False it starts from a reset controller, as the firmware does on
    leaving the zero-setpoint cutoff.  Below V_SP_ZERO_THRESH_MPS the
    controller is held reset and 0 A is commanded (motorControl()).
    """
    import hil_plant_sim as _hps
    plant = plant or hil_plant_params()
    sp_fn = v_sp if callable(v_sp) else (lambda _t, _v=float(v_sp): _v)
    m_eff, b_lin, k_f = plant["m_eff"], plant["b_lin"], plant["k_f"]
    f_c = _hps.F_COULOMB if f_coulomb is None else f_coulomb
    v_st = _hps.V_STICTION if v_stiction is None else v_stiction
    n = coeffs["NSTATES"]
    ad, bd, cd, dd, lv = coeffs["AD"], coeffs["BD"], coeffs["CD"], coeffs["DD"], coeffs["L"]
    imin, imax = coeffs["I_MIN"], coeffs["I_MAX"]
    ctrl_ticks = max(1, int(round(coeffs["TS_US"] * 1e-6 / dt)))
    v = float(sp_fn(0.0) if v0 is None else v0)
    # DC seed: at e = 0 the only non-zero state is the integrator (state 0 is
    # the integrator in this realization: AD[0][0] == 1, AD[0][j>0] == 0), and
    # its value must produce the hold current u0 = (F_c + B v)/K_F.
    x = [0.0] * n
    u0 = ((f_c + b_lin * v) / k_f) if (seed_dc and abs(v) >= v_st) else 0.0
    # Solve the steady state of the non-integral states with x0 fixed:
    # x_r = (I - A_rr)^-1 A_r0 x0, u = CD . x.  Linear in x0, so scale.
    a_rr = [[(1.0 if i == j else 0.0) - ad[i + 1][j + 1] for j in range(n - 1)]
            for i in range(n - 1)]
    a_r0 = [ad[i + 1][0] for i in range(n - 1)]
    xr = _csolve(a_rr, [complex(v_) for v_ in a_r0])
    gain = cd[0] + sum(cd[j + 1] * xr[j].real for j in range(n - 1))
    x0 = u0 / gain if gain else 0.0
    x[0] = x0
    for j in range(n - 1):
        x[j + 1] = xr[j].real * x0
    theta = 0.0
    held = u0
    out = {"t": [], "theta": [], "v_true": [], "v_inj": [], "current": [],
           "u_unsat": [], "v_sp": []}
    cut = False
    steps = int(round(duration_s / dt))
    inj_hist = [v] * (d_in + 2)          # speeds as emitted, newest last
    cmd_hist = [held] * (d_out + 2)      # controller outputs, newest last
    u_unsat_last = held
    for k in range(steps):
        # ── the plant tick (Plant.step order: force from the received cmd) ──
        i_cmd = cmd_hist[-1 - d_out] if d_out < len(cmd_hist) else cmd_hist[0]
        f_drive = k_f * i_cmd
        if abs(v) < v_st:
            if abs(f_drive) <= f_c:
                f_net = 0.0
                v = 0.0
            else:
                f_net = f_drive - (f_c if f_drive > 0 else -f_c) - b_lin * v
        else:
            f_net = f_drive - (1.0 if v > 0 else -1.0) * f_c - b_lin * v
            if f_rip:
                f_net += f_rip * math.sin(theta + phase_rad)
        v += (f_net / m_eff) * dt
        if abs(v) >= v_st:
            theta = (theta + v / FLYWHEEL_RADIUS_M * dt) % (2.0 * math.pi)
        v_inj = v
        if abs(v) >= v_st and (a_meas or a_meas2):
            v_inj = (v + a_meas * math.sin(theta + phase_rad)
                     + a_meas2 * math.sin(2.0 * theta + phase_rad))
        inj_hist.append(v_inj)
        if len(inj_hist) > d_in + 2:
            inj_hist.pop(0)
        # ── the board: controller tick on its 2 ms gate ────────────────────
        sp = sp_fn((k + 1) * dt)
        if k % ctrl_ticks == 0:
            if abs(sp) < V_SP_ZERO_THRESH_MPS:
                # The zero cutoff: reset on entry, 0 A while inside.
                if not cut:
                    x = [0.0] * n
                    cut = True
                held = 0.0
                u_unsat_last = 0.0
            else:
                cut = False
                v_seen = (inj_hist[-1 - d_in] if d_in < len(inj_hist)
                          else inj_hist[0])
                e = sp - v_seen
                u = dd * e + sum(cd[j] * x[j] for j in range(n))
                u_unsat_last = u
                uc = imax if u > imax else (imin if u < imin else u)
                dc = uc - u
                x = [bd[i] * e + lv[i] * dc
                     + sum(ad[i][j] * x[j] for j in range(n))
                     for i in range(n)]
                held = uc
        cmd_hist.append(held)
        if len(cmd_hist) > d_out + 2:
            cmd_hist.pop(0)
        out["t"].append((k + 1) * dt)
        out["theta"].append(theta)
        out["v_true"].append(v)
        out["v_inj"].append(v_inj)
        out["current"].append(i_cmd)
        out["u_unsat"].append(u_unsat_last)
        out["v_sp"].append(sp)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Lock-in (single-bin least-squares demodulation).
#
# A joint least-squares fit of  x = a + b t + I sin(theta) + Q cos(theta)
# over a window spanning an INTEGER number of revolutions of the reference
# angle.  The mean and the linear trend are fitted jointly, not subtracted
# first, because in the force variant the true speed itself ripples, so the
# angle is not sampled uniformly in time and a bare DFT would leak the cruise
# DC current (~3-5 A) into the 1x bin at the percent level - the same order as
# the effect being scored.  x = A sin(theta + phi) gives I = A cos(phi),
# Q = A sin(phi).
# ─────────────────────────────────────────────────────────────────────────────

def _solve_real(a, b):
    return [v.real for v in _csolve([[complex(v) for v in r] for r in a],
                                    [complex(v) for v in b])]


def unwrap(angles):
    out = []
    off = 0.0
    prev = None
    for a in angles:
        if prev is not None:
            d = a - prev
            if d < -math.pi:
                off += 2.0 * math.pi
            elif d > math.pi:
                off -= 2.0 * math.pi
        out.append(a + off)
        prev = a
    return out


def integer_rev_span(theta_unwrapped):
    """(start, stop) indices of the longest prefix-anchored span covering an
    integer number (>= 1) of revolutions; (0, 0) when under one revolution."""
    if not theta_unwrapped:
        return 0, 0
    th0 = theta_unwrapped[0]
    revs = int(math.floor((theta_unwrapped[-1] - th0) / (2.0 * math.pi)))
    if revs < 1:
        return 0, 0
    target = th0 + revs * 2.0 * math.pi
    stop = len(theta_unwrapped)
    for i in range(len(theta_unwrapped) - 1, -1, -1):
        if theta_unwrapped[i] <= target:
            stop = i + 1
            break
    return 0, stop


def lockin(t, x, theta, harmonic=1):
    """{amp, phase_deg, I, Q, mean, revs, n} of the `harmonic` x theta line.

    `theta` may be wrapped; it is unwrapped here and the window trimmed to an
    integer number of revolutions.  Returns None when the window holds less
    than one revolution or fewer than 8 samples."""
    if len(t) != len(x) or len(t) != len(theta):
        raise ValueError("lockin: t, x and theta must be the same length")
    th = unwrap(theta)
    i0, i1 = integer_rev_span(th)
    if i1 - i0 < 8:
        return None
    t = t[i0:i1]
    x = x[i0:i1]
    th = th[i0:i1]
    tm = sum(t) / len(t)
    cols = []
    for tt, a in zip(t, th):
        cols.append((1.0, tt - tm, math.sin(harmonic * a), math.cos(harmonic * a)))
    ata = [[0.0] * 4 for _ in range(4)]
    atb = [0.0] * 4
    for row, xv in zip(cols, x):
        for i in range(4):
            atb[i] += row[i] * xv
            ri = row[i]
            for j in range(4):
                ata[i][j] += ri * row[j]
    sol = _solve_real(ata, atb)
    i_c, q_c = sol[2], sol[3]
    return {"amp": math.hypot(i_c, q_c),
            "phase_deg": math.degrees(math.atan2(q_c, i_c)),
            "I": i_c, "Q": q_c, "mean": sol[0], "slope": sol[1],
            "revs": (th[-1] - th[0]) / (2.0 * math.pi), "n": len(t)}


def phase_diff_deg(a_deg, b_deg):
    """a - b wrapped to (-180, 180]."""
    d = (a_deg - b_deg) % 360.0
    return d - 360.0 if d > 180.0 else d


# ─────────────────────────────────────────────────────────────────────────────
# Step metrics (report-only): the 0 -> v step's 2 % settle, overshoot, peak
# current and time on the rail.
# ─────────────────────────────────────────────────────────────────────────────

def step_metrics(t, v, current, t_step, v_target, i_rail, t_end=None,
                 rail_tol=1e-3, band_frac=0.02):
    """Measured on rows with t_step <= t <= t_end (t_end None = to the end).
    `v` is the speed to judge (the TRUE speed when the CSV carries it - the
    injected one under a measurement ripple carries the artefact).  Settle =
    the last instant |v - target| exceeded band_frac * target, minus t_step;
    None if the window ends outside the band (it never settled).  `rail_s` is
    the time |current| sat within rail_tol of i_rail."""
    rows = [(tt, vv, ii) for tt, vv, ii in zip(t, v, current)
            if tt >= t_step and (t_end is None or tt <= t_end)]
    if not rows:
        return None
    band = band_frac * abs(v_target)
    last_out = None
    peak_v = None
    peak_i = None
    rail_s = 0.0
    prev_t = None
    for tt, vv, ii in rows:
        if abs(vv - v_target) > band:
            last_out = tt
        if peak_v is None or vv > peak_v:
            peak_v = vv
        if ii is not None:
            if peak_i is None or abs(ii) > abs(peak_i):
                peak_i = ii
            if prev_t is not None and abs(abs(ii) - i_rail) <= rail_tol:
                rail_s += tt - prev_t
        prev_t = tt
    settled = last_out is None or last_out < rows[-1][0]
    return {
        "settle_2pct_s": (None if not settled else
                          (0.0 if last_out is None else last_out - t_step)),
        "overshoot_pct": (None if peak_v is None or not v_target else
                          max(0.0, (peak_v - v_target) / abs(v_target) * 100.0)),
        "peak_current_a": peak_i,
        "rail_s": rail_s,
    }


def predicted_table(coeffs, speeds, plant, a_meas=0.0, f_rip=0.0):
    """[predict_hold(...)] for each speed - the report rows."""
    return [predict_hold(coeffs, v, plant, a_meas=a_meas, f_rip=f_rip)
            for v in speeds]


if __name__ == "__main__":      # pragma: no cover - a convenience printout
    p = hil_plant_params()
    for label, c in (("repo", repo_drive_coeffs()), ("v35", V35_DRIVE_COEFFS)):
        for v in (1.0, 1.5, 2.2, 2.7):
            pm = predict_hold(c, v, p, a_meas=0.020)
            pf = predict_hold(c, v, p, f_rip=1.0)
            print("%-4s v=%.1f f=%.3f |C|=%6.2f |S|=%.3f |CS|=%6.2f  meas i=%.3f A "
                  "ratio=%.3f  force i=%.3f A v=%.4f" % (
                      label, v, pm["f_hz"], pm["abs_C"], pm["abs_S"], pm["abs_CS"],
                      pm["i_amp"], pm["true_over_inj"], pf["i_amp"], pf["v_inj_amp"]))
