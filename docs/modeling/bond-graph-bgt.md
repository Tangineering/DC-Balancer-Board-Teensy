# Bond Graph (BondGraphTools revamp) — Scale Car DC Balancer Board rev 20260622

Executable revamp of the hand-drawn first pass in [`bond-graph.md`](bond-graph.md). The model is
built with the Python [`BondGraphTools`](https://pypi.org/project/BondGraphTools/) library
(`bond_graph_bgt.py`) and every sheet under `bond-graph-bgt/` is rendered by the library's own
`BondGraphTools.draw()` (Kamada–Kawai auto-layout; only the sheet title, axis margins and the
`Se`/compound glyph text are post-fixed on the matplotlib figure).

The original document, its SVG, and all firmware/tooling are untouched; this adds files only.

```
pip install BondGraphTools          # drawing needs matplotlib + networkx only (no Julia/odes)
python3 docs/modeling/bond_graph_bgt.py
```

## Sheets

| File | Sheet |
|------|-------|
| `bond-graph-bgt/00_top_level.png` | Power-path topology: FC/BT sources and boosts, the six RT1987 switches, `0:VBUS`, `0:V-MOT`, `0:CHG`, `0:BAT`, drivetrain, chopper, Ag105 charger, logic LDO, BQ29200 OVP |
| `01_fc_source_boost.png` | H-20 stack (`Se` + nonlinear `R`) → input cap → `I:L_fc` / DCR+INA253 shunt → `TF:(1−D_fc)` → output cap |
| `02_bt_boost.png` | Battery boost branch (same structure, fed from `0:BAT` through `SW BT_SEQ`) |
| `03_battery_pack.png` | 2S pack: `Se:V_bat,oc(SOC)` + `R_bat,int` + slow `C:Q_soc` on a 1-junction |
| `04_rt1987_switch.png` | One path switch: series 1-junction + `R:Rds(on)` (open = bond removed) |
| `05_drivetrain_vehicle.png` | `TF:VESC(D_m)` → armature `R_a`/`L_a` → `GY:k_t` → rotor `J`/`b` → `TF:N_gear` → `TF:r_wheel` → vehicle `m`, `R_roll`, `R_aero`, `Se:F_grade` |
| `06_drivetrain_bench.png` | Bench variant: rotor 1-junction loaded by `I:J_flywheel` (encoder location) |
| `07_brake_chopper.png` | TL431 / BSP170P / 47 Ω dump on `0:V-MOT` (hardware-only) |
| `08_ag105_charger.png` | `TF:Ag105(D_chg)` + loss `R` returning into `0:BAT` |

Top level: 21 components, 22 bonds. Half-arrows follow the traction (source → load) direction;
the `V-MOT → Drivetrain` and `Ag105` bonds carry power in both directions (regen).

## Mapping from the first-pass document

| `bond-graph.md` element | BondGraphTools element used | Note |
|---|---|---|
| `MTF` boost `(1−D)`, VESC, Ag105 | `TF` with a **symbolic** modulus (`1-D_fc`, `1-D_bt`, `D_m`, `D_chg`) | The library has no modulated transformer; the modulus is a free parameter the droop loop / firmware sets |
| `MR:SW_*` RT1987 switches, chopper FET, BQ29200 clamp | `R` (inside a 2-port compound for the six path switches) | No modulated resistor / switch element; "open" = remove the bond. Per-firmware-state switch table is unchanged: `bond-graph.md` §6 |
| Signal / activated bonds (MCU sense + command) | **not drawn** | The library draws power bonds only; the sensed/commanded signal list stays in `bond-graph.md` §5 |
| `Se`, `Sf` | `Se` (drawn by the library as its `SS` glyph, relabelled `Se:`) | — |
| Sub-graphs §4.1–4.5 | compound models with `expose`d ports (`SS: in/out/a/b/term`) | `SS:` glyphs on a sub-sheet are that block's external ports |

Element values and their sources are the §8 table of `bond-graph.md`; `TODO(calibrate)` items are
marked in the script's comments and are unchanged. The §9 open question on the 470 µF placement
(`C_mot` on `0:V-MOT` vs `CAL` on `0:CHG`) is carried over verbatim — both are drawn, one may be
spurious.

## Limitations of this rendering

- Layout is the library's spring/Kamada–Kawai placement, so node positions carry no meaning and
  the bond-port labels (`[a]`, `[b]`, `[in]`…) can overlap a block name on the busy top sheet.
- Symbolic simulation (`bgt.simulate`) needs `scikit.odes` + Julia and was not exercised; the
  script only builds and draws the topology.
