# Schematic block layouts (CR and EIB)

`gen/sch_blocks.py` re-lays the CR and EIB schematics into functional blocks, in the style of the MB
schematic (`references/Scale Car DC Balancer Board Schematic 2026-06-22.pdf`): each block has a frame, a
large grey title, its parts wired to each other, and labels for the nets that leave the block. The
connectivity, the symbol UUIDs and every field are copied unchanged from the source schematic, so the PCB is
unaffected. `gen/sch_verify.py` is the gate.

## 1. Files

| File | Content |
|---|---|
| `<board>/sheet.json` | paper size, the power-flag nets (`flags`) and the position of each block on the sheet |
| `<board>/<nn>_<id>.json` | one block: title, subtitle, size, part placements, wires, labels and notes |

The spec format is in the `sch_blocks.py` docstring.

## 2. Blocks

| Board | Block id | Title | Parts |
|---|---|---|---|
| CR | `charger_hdr` | CHARGER HEADER + LEADS | J1, W1, W2, W3, W4, W6, W7, R107, R108, #FLG01, #FLG02, #FLG03 |
| CR | `efuse` | INPUT PROTECTION + EFUSE | C102a, C102b, C102c, D107, U101, R101, R102, R103, R104, R105, C101, C103, D103 |
| CR | `h1_uvb` | H1 + UVB COMPARATORS | U102, U103, R109, R110, C106, D104, R111, R112, C107, D105, R113, R114, R115, C108, D106, R116, C110, C111 |
| CR | `fcc` | FC-CHARGE EN-STATE COMPARATORS | U119, U120, R184, R185, C130, R186, R187, R188, R189, C131, C132 |
| CR | `permit` | PERMIT LOGIC | U105, U106, U107, U110, U118, R123, C114, C115, C116, C119, C126 |
| CR | `eib_link` | EIB LINK (W5) | J101, R130, R131A, R131B, R132, R176, R177 |
| CR | `jtap` | J-TAP MB TAPS + 3V3 FEED | J102, R106s, R129, C129, R122, R126, R147, R175, C125 |
| EIB | `link` | W5 LINK + EVM PADS | J201, E1, E7, E8, R273, R274, R275, R276, #FLG01, #FLG02 |
| EIB | `receivers` | COMMAND RECEIVERS | U201, U202, R250, R251, R253, R266, R267, R268, R269, R270, C201, C202, E5 |
| EIB | `ilim` | ILIM SWITCHES | Q201, Q202, Q203, R252, R254, R271, R255, R257, C205, E2, E3 |
| EIB | `sense` | SENSE COMPARATORS (DNP) | U203, U204, R258, R259, R260, R261, R262, R263, R264, R265, C203, C204, E4, E6 |

The block notes (titles, subtitles and texts) were checked one by one against the netlist and the design
document on 2026-11-17: 94 of 104 were correct, and the other 10 were corrected or shortened. A note states
only what the design document or the netlist states.

The 3V3 decoupling capacitors are in the block of the IC they sit beside on the PCB (`kicad_pcb` footprint
positions, 2.6-3.8 mm from the IC).

## 3. Commands

```bash
python gen/sch_blocks.py cr cr/cr.kicad_sch --block gen/sch_layout/cr/02_efuse.json
```

prints each part's pin points in block coordinates, with the net, the outward direction and the body box.

```bash
SCH_ONLY=efuse python gen/sch_verify.py cr <work dir> --png
```

assembles the sheet with only that block (the other parts park in the legacy label style), compares the
netlist with the git HEAD schematic, runs ERC and DRC with schematic parity, and renders `blk_efuse.png`.
Without `SCH_ONLY` it gates the whole sheet. Python: miniforge (`cairosvg` for the render; KiCad's
`cairo-2.dll` is put on the DLL path).

To write the board schematic itself:

```bash
python gen/sch_blocks.py cr <source.kicad_sch> cr/cr.kicad_sch
```

The source can be the previous schematic in any layout: connectivity is read from KiCad's netlist export.
The in-place field scripts (`sync_fields.py` and the Note-field scripts) edit symbol properties and keep
working on the block layout.
