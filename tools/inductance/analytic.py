"""
Closed-form sanity bounds for loop inductance.

These are NOT the answer -- they are a cheap independent check so a wildly wrong
mesh/port setup is caught before anyone trusts the FastHenry number. The DC
asymptote of the swept solver result should land near these.
"""

from __future__ import annotations

import math

MU0 = 4e-7 * math.pi


def microstrip_loop_inductance(length_mm: float, width_mm: float, height_mm: float) -> float:
    """
    Loop inductance (henries) of a wide trace of length `length` and width
    `width` running over a ground plane `height` below it, current returning in
    the plane. Wide-line / parallel-plate approximation:

        L ~= mu0 * length * height / width        (valid for width >> height)

    Slightly improved with a fringing correction (Wheeler-ish) so it is not a
    gross underestimate when width ~ height:

        L ~= mu0 * length * height / (width + 0.44*... )   -- we keep it simple
    """
    L_m = length_mm / 1000.0
    w_m = width_mm / 1000.0
    h_m = height_mm / 1000.0
    # parallel-plate with a mild fringe correction on the effective width
    w_eff = w_m + 2.0 * h_m / math.pi * (1.0 + math.log(math.pi))  # crude fringe
    return MU0 * L_m * h_m / max(w_eff, 1e-9)


def parallel_plate_loop_inductance(length_mm: float, width_mm: float, height_mm: float) -> float:
    """Pure parallel-plate (no fringe): mu0*len*h/w. Upper-ish bound for wide w."""
    return MU0 * (length_mm / 1000.0) * (height_mm / 1000.0) / max(width_mm / 1000.0, 1e-9)


def rectangular_bar_partial_inductance(length_mm: float, width_mm: float, thick_mm: float) -> float:
    """
    Partial self-inductance (H) of an isolated rectangular bar -- the no-return
    reference. Standard low-frequency formula (Rosa/Grover):

        L = mu0/(2*pi) * len * [ ln(2*len/(w+t)) + 0.5 + 0.2235*(w+t)/len ]
    """
    L = length_mm / 1000.0
    w = width_mm / 1000.0
    t = thick_mm / 1000.0
    if L <= 0 or (w + t) <= 0:
        return float("nan")
    return MU0 / (2 * math.pi) * L * (
        math.log(2 * L / (w + t)) + 0.5 + 0.2235 * (w + t) / L
    )
