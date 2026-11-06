# Charger replacement evaluation: working material (2026-11-05)

Agent working files behind `docs/charger_replacement_evaluation_2026-11-05.md`, which is the single authoritative decision
document. Where anything here disagrees with that document, the document wins.

## Round 2 (`round2/`), the current round

Re-run under the operator's 2026-11-05 rulings: regen harvesting and FC charging are both hard requirements; Path A must be
shown fully feasible; R3 is replaced by "no circular loop, no runaway, fail-safe", with an always-powered charger accepted;
the board and pack survived the 2026-11-04 incident; an MCU hardware watchdog is required future work. Candidate primaries
(TI, ADI, MPS datasheets and EVM guides) were read this round; every candidate number is cited to a literature number and page.

| File | Content |
|---|---|
| `loop_analysis.md` | Loop and runaway analysis of the always-powered design: why the charger threshold cannot be the interlock, the V-MOT/VBUS comparator (H1), the FC-window permit (H2), single-fault table, state x mode matrix, MCU watchdog spec |
| `regen_dynamics.md` | Regen pulse analysis from 9 BLGs + the RegenTest_v2 bag; VESC ~21.35 V cut-off; capture model; warm-response (τ) requirement; EMS usefulness |
| `dossier_*.md` | One dossier per candidate: BQ25798, BQ25713, BQ25773, BQ25720, A2 (= BQ25731), LTC4015, A1 (= BQ25756), BQ24650, MP2759 |
| `design_BQ25798.{md,svg}` | Complete Path A design for the chosen part (carries a correction banner: the study's section 4 supersedes it on the C7 network, the /CE drive, R42 bias, VAC_OVP POR and the HR4 status) |
| `design_BQ25713.{md,svg}` | Complete Path A design for the runner-up (C7-qualified permit network, mode-switched ILIM) |
| `figs/` | Regen figures: measured pulses, model traces, capture vs τ, τ_max vs C |
| `calc/` | `capsim.py` (capture model), `comp_calc.py` (H1 comparator values), `taumax.py`/`taumax.json`, `grid.py`, `events.json`, `ilim_calc_bq25713.py` |

Not preserved as files: the 27 adversarial reviews (loop, regen and integration lenses on each dossier) and the final
three-reviewer panel. Their findings are summarized in sections 0.3 and 1.2-1.3 of the decision document and folded into the
corrections listed there. Scratch paths inside the copied files refer to the round-2 working directory, not the repo; the
datasheet PDFs were not copied.

Round-2 verdict: **UNDETERMINED** (Path A credible, not yet fully feasible); chosen part BQ25798EVM, runner-up BQ25713EVM-017,
BQ25773EVM bought in parallel for stage 1. Decisive next steps need no purchase: VESC cut-off checks M-R0/M-R3 and the
operator's FC-window purge ruling.

## Round 1 (top-level files), superseded where round 2 disagrees

Board interface spec (`spec.md`, still valid), incident re-check with an ML0227 decode (`incident.md`, still valid),
firmware/system blast radius (`firmware_impact.md`, effort estimate superseded), one dossier per round-1 shortlisted charger,
the LTC4015 wiring mockup, and the Path B (re-spin) analysis (`path_b_respin.md`, costs still quoted as round-1 estimates).

**Round-1 caveat:** no candidate datasheet or EVM user guide was readable then (vendor domains blocked); candidate-side
numbers in the round-1 files are search snippets or recollection and are UNVERIFIED. Round 1 also predates the 2026-11-05
rulings; its framing of regen as "demonstration value" and its R3 interlock are void.
