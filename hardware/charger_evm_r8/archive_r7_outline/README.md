# Archive: CR layout work on the r7 outline

## 1. Purpose

This folder holds the CR layout work that was done on the r7 outline before the plug-on outline change of 2026-11-12
(`OUTLINE_CHANGE_REASSESSMENT_2026-11-12.md`). The work is stale against the reduced netlist and the new outline. It is
kept as reference only; no file in this folder is an input to the generator or to the fab package.

## 2. Contents

- `cr/variants/`: the r1 placement variants A and B and their decision file.
- `cr/attempts/`: the best partial pathfinder route (516 clearance violations) and its DRC report.
- `cr/*.png`: the placement and routing images of the last r7-outline build.
- `routability_2026-11-12/`: the footprint and functional routability options and their claim checks, cited by
  `ROUTABILITY_OPTIONS_2026-11-12.md`.

- `cr/interactive/`: the interactive-routing project on the r7 outline (r2_A seed 1 routes and plane vias); its
  README marks it as superseded.
