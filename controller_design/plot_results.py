#!/usr/bin/env python3
"""plot_results.py — render the thesis figures from the synthesis CSVs.

Run AFTER synthesize_controller.py. Produces (in figures/):
  loopshapes_youla_h.svg   — S, T, Y vs inverse weights (paper Fig. 2/3 style)
  controller_bode.svg      — Gc: H-inf vs Youla-H vs reduced vs discrete
  timedomain_step_ramp.svg — step + ramp tracking, Youla-H vs legacy PI

If tps61288_full_model.py has been run, additionally produces:
  fullorder_bode_overlay.svg — full-order vs simplified plant + corner band
  fullorder_envelope.svg     — full-model family vs simplified corner family
  fullorder_step_overlay.svg — closed-loop step, full vs simplified plant
"""
import csv
import os

import matplotlib
matplotlib.use("SVG")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, "figures")


def read_csv(name):
    with open(os.path.join(FIG, name)) as f:
        rd = csv.reader(f)
        hdr = next(rd)
        cols = {h: [] for h in hdr}
        for row in rd:
            for h, v in zip(hdr, row):
                try:
                    cols[h].append(float(v))
                except ValueError:
                    cols[h].append(float("nan"))
    return cols


plt.rcParams.update({"font.size": 9, "font.family": "serif",
                     "axes.grid": True, "grid.alpha": 0.3,
                     "svg.fonttype": "none"})

# ── loop shapes ──────────────────────────────────────────────────────────────
c = read_csv("loopshapes_youla_h.csv")
fig, ax = plt.subplots(figsize=(6.5, 4.2))
w = c["w_rad_s"]
def db(v): return [20*__import__("math").log10(max(x, 1e-12)) for x in v]
ax.semilogx(w, db(c["S_mag"]), "k--", label="S")
ax.semilogx(w, db(c["T_mag"]), "k-",  label="T")
ax.semilogx(w, db(c["Y_mag"]), "k:",  label="Y")
ax.semilogx(w, db(c["invWp"]), "b-.", lw=0.9, label="1/Wp")
ax.semilogx(w, db(c["invWd"]), "b--", lw=0.9, label="1/Wd")
ax.semilogx(w, db(c["invWu"]), "b:",  lw=0.9, label="1/Wu")
ax.set_xlabel("Frequency (rad/s)"); ax.set_ylabel("Magnitude (dB)")
ax.set_title("Youla-H closed-loop shapes — droop power-share loop")
ax.set_ylim(-100, 30); ax.set_xlim(1e-2, 1e5); ax.legend(ncol=2, loc="lower left")
fig.tight_layout(); fig.savefig(os.path.join(FIG, "loopshapes_youla_h.svg"))

# ── controller Bode ──────────────────────────────────────────────────────────
c = read_csv("controller_bode.csv")
fig, ax = plt.subplots(figsize=(6.5, 4.2))
ax.semilogx(c["w_rad_s"], db(c["Gc_hinf_mag"]),    "k-",  label=r"$G_C$ H$\infty$")
ax.semilogx(c["w_rad_s"], db(c["Gc_youlah_mag"]),  "k--", label=r"$G_C$ Youla-H (full)")
ax.semilogx(c["w_rad_s"], db(c["Gc_reduced_mag"]), "b-.", label=r"$G_C$ reduced (int + 3)")
ax.semilogx(c["w_rad_s"], db(c["Gc_discrete_mag"]),"r:",  label=r"$G_C(z)$, $T_s$ = 1 ms")
ax.set_xlabel("Frequency (rad/s)"); ax.set_ylabel("Magnitude (dB)")
ax.set_title("Controller magnitude: H∞ vs Youla-H (pure integrator at DC)")
ax.set_xlim(1e-2, 1e5); ax.legend(loc="upper right")
fig.tight_layout(); fig.savefig(os.path.join(FIG, "controller_bode.svg"))

# ── time domain ──────────────────────────────────────────────────────────────
c = read_csv("timedomain_step_ramp.csv")
fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.5, 5.6), sharex=False)
t = c["t_s"]
n_step = next((i for i, v in enumerate(c["step_alpha_youlah"]) if v != v), len(t))
a1.plot(t[:n_step], c["step_ref"][:n_step], "k:", lw=1, label="reference")
a1.plot(t[:n_step], c["step_alpha_youlah"][:n_step], "b-", label="Youla-H")
a1.plot(t[:n_step], c["step_alpha_pi"][:n_step], "r--", lw=0.9, label="legacy PI")
a1.plot(t[:n_step], c["step_r_cmd"][:n_step], "g-.", lw=0.8, label="r command (Youla-H)")
a1.set_xlabel("Time (s)"); a1.set_ylabel("share α"); a1.legend(loc="lower right")
a1.set_title("Share step 0.5 → 0.7 (nominal discrete loop, Ts = 1 ms)")
a2.plot(t, c["ramp_ref"], "k:", lw=1, label="reference (EMS ramp 0.05/s)")
a2.plot(t, c["ramp_alpha"], "b-", label="Youla-H")
a2.set_xlabel("Time (s)"); a2.set_ylabel("share α"); a2.legend(loc="lower right")
a2.set_title("Ramp tracking — no accumulating bias (T(0) = 1)")
fig.tight_layout(); fig.savefig(os.path.join(FIG, "timedomain_step_ramp.svg"))

n_figs = 3

# ── full-order validation figures (only if tps61288_full_model.py has run) ──
if os.path.exists(os.path.join(FIG, "fullorder_bode_overlay.csv")):
    c = read_csv("fullorder_bode_overlay.csv")
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.5, 6.2), sharex=True)
    w = c["w_rad_s"]
    a1.fill_between(w, db(c["corner_mag_min"]), db(c["corner_mag_max"]),
                    color="0.85", label="simplified corner family")
    a1.semilogx(w, db(c["simp_mag"]), "b--", label="simplified nominal")
    a1.semilogx(w, db(c["full_mag"]), "r-", lw=1.2, label="full-order (TPS61288 DS §9.2.2.5)")
    a1.axvline(1100, color="k", ls=":", lw=0.8)
    a1.set_xscale("log")
    a1.set_ylabel("Magnitude (dB)"); a1.legend(loc="lower left")
    a1.set_title("Share plant r → α: full-order vs simplified design model")
    a2.semilogx(w, c["simp_phase_deg"], "b--", label="simplified nominal")
    a2.semilogx(w, c["full_phase_deg"], "r-", lw=1.2, label="full-order")
    a2.axvline(1100, color="k", ls=":", lw=0.8)
    a2.set_xlabel("Frequency (rad/s)"); a2.set_ylabel("Phase (deg)")
    a2.legend(loc="lower left"); a2.set_ylim(-360, 30)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "fullorder_bode_overlay.svg"))

    c = read_csv("fullorder_envelope.csv")
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    w = c["w_rad_s"]
    ax.fill_between(w, db(c["corner_mag_min"]), db(c["corner_mag_max"]),
                    color="0.85", label="simplified corner family (9 corners)")
    ax.fill_between(w, db(c["full_mag_min"]), db(c["full_mag_max"]),
                    color="tab:red", alpha=0.35,
                    label="full-order family (432 operating points)")
    ax.semilogx(w, db(c["simp_nom_mag"]), "b--", lw=1.0, label="simplified nominal")
    ax.set_xscale("log")
    ax.set_xlabel("Frequency (rad/s)"); ax.set_ylabel("Magnitude (dB)")
    ax.set_title("Design band: simplified corner family covers the full-order family")
    ax.legend(loc="lower left")
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "fullorder_envelope.svg"))

    c = read_csv("fullorder_step_overlay.csv")
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    ax.plot(c["t_s"], c["alpha_simplified"], "b--", label="simplified plant")
    ax.plot(c["t_s"], c["alpha_full"], "r-", lw=1.0, label="full-order plant")
    ax.set_xlabel("Time (s)"); ax.set_ylabel("share α"); ax.set_xlim(0, 0.15)
    ax.set_title("Closed loop with the shipped controller: step 0.5 → 0.7")
    ax.legend(loc="lower right")
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "fullorder_step_overlay.svg"))
    n_figs += 3

print(f"wrote {n_figs} SVG figures to figures/")
