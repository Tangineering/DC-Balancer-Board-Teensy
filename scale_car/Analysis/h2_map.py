#!/usr/bin/env python3
r"""
h2_map.py — hydrogen usage map for the Horizon H-20, and the flow-vs-power plot.

    python3 h2_map.py                            # datasheet curve only
    python3 h2_map.py ../Logs/rosbag_sdp_*       # overlay Faraday from bags
    python3 h2_map.py --grav 10.0:31.2:1.0 ...   # add gravimetric points
                                                 #   P_stack:mg_per_min:sigma

WHAT THIS IS FOR
----------------
Two jobs, one definition. The Pi's bridge node computes hydrogen usage online
from the same model; this file is the reference map and the plotting side. The
constants below are the single source of truth for both — if you change
N_CELLS or the purge term here, change the matching ROS parameter on the Pi.

THE MODEL
---------
    m_dot = N · I_stack · M_H2 / (2F)   +   m_dot_purge
            \___ Faraday, electrochemistry ___/   \_ NOT MEASURED _/

    I_stack = V_bus · I_fc / (V_fc · eta_boost)

V_fc is the stack voltage and I_fc is the BUS-side boost output current
(/vehicle_state elements 4 and 5), so that conversion is required. Getting it
wrong scales every hydrogen number by the boost ratio, roughly 1.6x.

WHY THE DATASHEET MAP IS NOT INDEPENDENT EVIDENCE
-------------------------------------------------
Read its five points back through Faraday's law and the implied cell voltage is
0.70 V flat below 15 W, sagging to 0.50 V at 23.5 W. That is a textbook PEM
polarisation curve. So the published fuel map IS Faraday's law with the stack's
own droop folded into it, and the "kinks" at 13.95 W and 18.60 W that earlier
cost-to-go builds treated as fuel-map features are just the knee of that curve.

It is kept here as the REFERENCE curve. The independent series is Faraday
computed from measured V_fc and I_fc in a bag: if those points land on the
datasheet line, N_CELLS and ETA_BOOST are both right.

WHAT IS NOT MEASURED
--------------------
N_CELLS is inferred from the datasheet map, not read off the manual.
PURGE_ML_MIN is zero, deliberately. The purge TIMING is known from the bench
(100 ms every 10.340 s, independent of load) but the flow it vents is not. The
published curve passes through the origin, so it carries no purge term either.
An hour of idle soak with no electrical load measures it directly: Faraday
consumption is then zero and every milligram lost is purge plus crossover.
"""

import glob
import os
import sys

import numpy as np

# ── Physical constants ────────────────────────────────────────────────────────
F    = 96485.0      # C/mol, Faraday
VM   = 22414.0      # ml/mol at STP
M_H2 = 2.016        # g/mol

# ── Platform constants — keep in sync with the Pi's ROS parameters ───────────
N_CELLS      = 14     # INFERRED from the datasheet map. Confirm against the manual.
ETA_BOOST    = 0.90   # FC boost efficiency, assumed
PURGE_ML_MIN = 0.0    # UNMEASURED. Do not put 3.0 here — that was never a
                      # datasheet value, and the published curve starts at 0.

# ── Horizon H-20 datasheet, stack side ───────────────────────────────────────
# The 0 W point is deliberately absent: the published curve passes through the
# origin, so it gives no purge intercept.
DS_P    = np.array([  5.0,  10.0,  15.0,  20.0,  23.5])   # W
DS_FLOW = np.array([ 50.0, 100.0, 150.0, 230.0, 330.0])   # ml/min

# /vehicle_state indices (bridge node, 18 elements)
IDX_V_FC, IDX_I_FC, IDX_V_BUS = 4, 5, 6


# ── The model ─────────────────────────────────────────────────────────────────
def stack_current(v_fc, i_fc_bus, v_bus, eta=ETA_BOOST):
    """Bus-side FC current referred to the stack. Zero where V_fc is not live."""
    v_fc = np.atleast_1d(np.asarray(v_fc, float))
    i_fc = np.atleast_1d(np.asarray(i_fc_bus, float))
    v_bs = np.atleast_1d(np.asarray(v_bus, float))
    out = np.zeros_like(v_fc)
    ok = v_fc > 1.0
    out[ok] = v_bs[ok] * i_fc[ok] / (v_fc[ok] * eta)
    return out


def faraday_ml_min(i_stack, n=N_CELLS):
    """Stoichiometric hydrogen flow, ml/min at STP."""
    return np.asarray(i_stack, float) * n / (2.0 * F) * VM * 60.0


def faraday_g_per_s(i_stack, n=N_CELLS):
    """Stoichiometric hydrogen mass flow, g/s."""
    return np.asarray(i_stack, float) * n * M_H2 / (2.0 * F)


def purge_g_per_s(purge_ml_min=PURGE_ML_MIN):
    """Non-Faradaic loss as mass flow. Constant with load: the purge timer is
    fixed and the anode pressure is regulator-held."""
    return purge_ml_min / VM * M_H2 / 60.0


def total_g_per_s(i_stack, n=N_CELLS, purge_ml_min=PURGE_ML_MIN):
    return faraday_g_per_s(i_stack, n) + purge_g_per_s(purge_ml_min)


def datasheet_ml_min(p_stack):
    """Reference curve, linearly interpolated between the published points."""
    return np.interp(p_stack, DS_P, DS_FLOW)


def implied_cell_voltage(n=N_CELLS):
    """What each datasheet point says the cell voltage must be, if Faraday
    holds. The consistency check — not a second measurement."""
    i = DS_FLOW * 2 * F / (n * VM * 60.0)
    return DS_P / i / n


# ── Bag reader ────────────────────────────────────────────────────────────────
def from_bag(path):
    """Returns (P_stack [W], Faraday flow [ml/min]) per sample, or (None, None)."""
    try:
        from mcap_ros2.reader import read_ros2_messages
    except ImportError:
        sys.exit("pip install mcap mcap-ros2-support")

    mcap = path
    if not path.endswith(".mcap"):
        hits = glob.glob(os.path.join(path, "*.mcap"))
        if len(hits) != 1:
            return None, None
        mcap = hits[0]

    vfc, ifc, vbus = [], [], []
    for m in read_ros2_messages(mcap):
        if m.channel.topic != "/vehicle_state":
            continue
        d = list(m.ros_msg.data)
        if len(d) < 18:
            continue
        vfc.append(d[IDX_V_FC]); ifc.append(d[IDX_I_FC]); vbus.append(d[IDX_V_BUS])

    if len(vfc) < 50:
        return None, None
    vfc, ifc, vbus = np.array(vfc), np.array(ifc), np.array(vbus)
    i_st = stack_current(vfc, ifc, vbus)
    return vfc * i_st, faraday_ml_min(i_st)


def cumulative_grams(path):
    """Total hydrogen over a bag, from the current trace. Faraday only unless
    PURGE_ML_MIN has been measured and set."""
    try:
        from mcap_ros2.reader import read_ros2_messages
    except ImportError:
        sys.exit("pip install mcap mcap-ros2-support")
    mcap = path
    if not path.endswith(".mcap"):
        hits = glob.glob(os.path.join(path, "*.mcap"))
        if len(hits) != 1:
            return None
        mcap = hits[0]
    t, vfc, ifc, vbus = [], [], [], []
    for m in read_ros2_messages(mcap):
        if m.channel.topic != "/vehicle_state":
            continue
        d = list(m.ros_msg.data)
        if len(d) < 18:
            continue
        t.append(m.log_time_ns / 1e9)
        vfc.append(d[IDX_V_FC]); ifc.append(d[IDX_I_FC]); vbus.append(d[IDX_V_BUS])
    if len(t) < 50:
        return None
    t = np.array(t) - t[0]
    i_st = stack_current(np.array(vfc), np.array(ifc), np.array(vbus))
    g_s = total_g_per_s(i_st)
    return float(np.trapz(g_s, t)), float(t[-1])


# ── Plot ──────────────────────────────────────────────────────────────────────
def main():
    args = [a for a in sys.argv[1:]]
    grav = []
    while "--grav" in args:
        k = args.index("--grav")
        for spec in args[k + 1:]:
            if spec.startswith("-"):
                break
            try:
                p, mg, sd = (float(x) for x in spec.split(":"))
                grav.append((p, mg, sd))
            except ValueError:
                break
        del args[k:k + 1 + len(grav)]
    bags = [a for a in args if not a.startswith("-")]

    print(f"H-20 hydrogen map")
    print(f"  N = {N_CELLS} cells (INFERRED, confirm against the manual)")
    print(f"  eta_boost = {ETA_BOOST} (assumed)")
    print(f"  purge = {PURGE_ML_MIN} ml/min (UNMEASURED — idle soak gives it)")
    print(f"\n{'P_stack':>8} {'ml/min':>8} {'mg/min':>8} {'V/cell':>8}")
    for p, f_, v in zip(DS_P, DS_FLOW, implied_cell_voltage()):
        print(f"{p:8.1f} {f_:8.0f} {f_ / VM * M_H2 * 1000:8.2f} {v:8.2f}")
    print("\n  Those cell voltages are the datasheet read backwards through")
    print("  Faraday: 0.70 V flat, then sagging. It is a polarisation curve.")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    pp = np.linspace(0, 24, 300)
    ax.plot(pp, datasheet_ml_min(pp), "-", color="#1F497D", lw=2,
            label="H-20 datasheet (reference)")
    ax.plot(DS_P, DS_FLOW, "o", color="#1F497D", ms=6)

    for b in bags:
        P, flow = from_bag(b)
        name = os.path.basename(b.rstrip("/"))
        if P is None:
            print(f"  skipped {name}: too few samples")
            continue
        m = P > 0.2
        ax.plot(P[m], flow[m], ".", ms=2.5, alpha=0.35,
                label=f"Faraday from {name[:30]}")
        tot = cumulative_grams(b)
        if tot:
            print(f"  {name[:40]}: {tot[0] * 1000:.1f} mg over {tot[1]:.0f} s")

    for p, mg, sd in grav:
        ax.errorbar([p], [mg / M_H2 * VM / 1000.0],
                    yerr=[sd / M_H2 * VM / 1000.0],
                    fmt="s", color="#DFBF50", ms=8, capsize=4,
                    label="gravimetric" if (p, mg, sd) == grav[0] else None)

    ax.set_xlabel("stack power [W]")
    ax.set_ylabel("H$_2$ flow [ml/min]")
    ax.set_title("Hydrogen flow against stack power")
    ax.grid(alpha=0.3)
    ax.set_xlim(0, 24)
    ax.set_ylim(0, 350)
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    out = "h2_map.png"
    fig.savefig(out, dpi=130)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
