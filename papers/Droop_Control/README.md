# Droop Control paper (MDPI Energies) — planning mock-up

`droop_control.tex` is a **structural mock-up**, not the manuscript: it plans the paper,
carries the argument skeleton for each section, and organizes the figures from the
modeling/bring-up work. The author (Ricky) writes the final prose; everything marked
`% NOTE` is placeholder argumentation, and every `% PLANNING NOTES` block lists what
must be resolved before that section is submittable.

## Structure

| File | Section | Status |
|---|---|---|
| `sections/01_introduction.tex` | Introduction + Related Work + method-comparison table | Draft w/ ~23 real refs (some `% TODO(verify)`) |
| `sections/02_droop_design.tex` | Droop design, gain selection, PCB constraints | Draft, **as-built (post-2026-07-11 retune) constants**: RE_MAX = 2.014 Ω, K_DROOP = 0.30 Ω |
| `sections/03_robust_controller.tex` | Plant model, H∞/Youla synthesis, 60-corner + full-order validation | Draft, all numbers traceable to `controller_design/*` |
| `sections/04_board_design.tex` | Board architecture, droop hardware chain, power pathing | Draft, 3 figure TODOs (block diagram, topology, photo) |
| `sections/05_bringup_debugging.tex` | Five boost deaths, inductance tool, RT1987 soft-start | Draft, several `TODO(verify)` (2.7× vs 2.2× ratio, Death-5 micro-mechanism) |
| `sections/06_mimo_outlook.tex` | Combined MIMO power+drive controller | **Placeholder — analysis not performed** |
| `sections/07_conclusions.tex` | Conclusions | Skeleton |
| `sections/99_references.tex` | thebibliography | Mock list; migrate to .bib later |

## Known cross-section issues (resolve before submission)

1. **Bus voltage**: Sec. 2/3 use the 16 V-retune constants (V₀ = 15.91 V); older docs say 17.5 V. One number everywhere.
2. **Inductance ratio**: docs say ~2.7×, current sweep store says ~2.2× (loop-closure change). Pick one, purge the other.
3. **Droop derivation duplication**: Secs. 2 and 3 both derive Re/share law — keep it in Sec. 2, trim Sec. 3 to dynamics only.
4. **Provisional numbers**: K_DROOP, ΔV₀, τr, Td are pre-calibration; if bench cal lands, regenerate coefficients (never hand-edit `share_controller_coeffs.h`) and re-extract every table from the `*_metrics.txt` files.
5. **No experimental results yet** — the paper currently verifies, it does not validate. CAL-1/CAL-2 bench data is the minimum bar.

## Building

```
pdflatex droop_control.tex
```

Figures: SVG sources live in `controller_design/figures/`; the PDF copies in `Figures/`
are converted (svglib). If an SVG is regenerated, re-convert. Missing figures are
`\fbox` placeholders with TODO comments specifying required content.
