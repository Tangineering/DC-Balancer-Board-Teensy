# CR placement variants for the routing study

These variants are built by `gen/make_board.sh cr` with `CR_PLACE_VARIANT` set, followed by the pour step of `route.py`
(LAYOUT_DECISIONS.md D-34). The base board `cr/cr.kicad_pcb` stays the placement of commit `5ddc21a`.

| Folder | Description |
|---|---|
| `r1_A/` | The VCHGOUT L4 strap outline + 0.15 mm is a bottom keep-out (R147 and R128 leave the strap); 7 parts move |
| `r1_B/` | Variant A plus the B.Cu tap/divider grid courtyards grown 0.225 mm (row pitch about 1.75 mm); 30 parts move |

`r1_decisions.json` holds the design owner's decisions on the round 1 change requests.
