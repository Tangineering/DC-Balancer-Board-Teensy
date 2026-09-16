# Anti-windup / discretization study for the Youla-H paper

Working material for a candidate "Discretization and Anti-Windup" subsection. Nothing here
is wired into the manuscript yet; the drafts reference figures by the paths in this folder.

| File | Purpose |
|---|---|
| `antiwindup_variants.m` | MATLAB: re-runs every variant below and writes the figures in the paper's style to `figures/` |
| `make_YH-AW-18.py` | Drivetrain plant (paper Eqs. Gch/Gcyh): clamp only, integrator back-calculation, full-state conditioning |
| `make_YH-vs-H-cond.py` | Drivetrain: H-inf vs Youla-H, both fully conditioned (saturating step + slow ramp) |
| `make_YH-AW-2nd.py` | Example plant 1/(s+1), crossover 1 rad/s (the paper's alternate system), four variants |
| `make_YH-AW-3rd.py` | Example plant, crossover 0.3 rad/s: integrator-only anti-windup suffices; loop-shape figure too |
| `drafts/section_antiwindup_drivetrain.tex` | Option 1: subsection text + drivetrain figure |
| `drafts/section_antiwindup_example_plant.tex` | Option 2: alternative second paragraph + example-plant figure |
| `drafts/section_alternate_system_replacement.tex` | Option 3: drop-in replacement for the Alternate System subsection |

The committed `figures/*.png,pdf` are the MATLAB renders; the Python scripts write their own
renders to `figures/python/` so the two never overwrite each other. Python scripts need numpy/scipy/matplotlib and import the repo's `controller_design/hinf_synthesis.py`
for the example-plant syntheses; run them from anywhere. The MATLAB script needs the Control System
and Robust Control toolboxes and re-synthesizes the drivetrain controller from the Appendix A weights.

Headline finding: under full-state (Hanus) conditioning the H-inf and Youla-H controllers saturate and
recover identically (same transmission zeros, so the same saturated-mode spectrum); Youla-H's benefit
after discretization is the exact DC tracking plus the well-posed integrator/remainder split, not
better anti-windup. Integrator-only back-calculation is sufficient only when the remainder's
low-frequency gain is small next to the integrator residue (the 0.3 rad/s example plant).
