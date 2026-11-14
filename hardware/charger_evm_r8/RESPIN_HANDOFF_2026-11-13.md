# CR respin handoff: U101 alternatives and the edits a respin must keep (2026-11-13)

## 1. Purpose

This document is the input for any routing session that changes the CR (`cr/cr.kicad_pcb`) or the EIB
(`eib/eib.kicad_pcb`) after 2026-11-13. Section 2 records why a respin may be needed: U101, the TPS26630RGER eFuse,
has no authorized stock. Section 3 inventories every edit made to the boards after their scripted generation, because a
plain regeneration loses them. A respin starts from the current boards and edits them in place (section 3.0, point 4).

## 2. U101 has no authorized stock

### 2.1 Stock

On 2026-11-13, TPS26630RGER had 0 stock at Digi-Key (restock 8-Jul-2027), Mouser and TME. TPS26631, TPS26633,
TPS26636, TPS26637, TPS16630 and TPS16631 also had 0 authorized stock; only brokers listed them. A datasheet search
over TI, Analog Devices/Maxim and other vendors gave the candidates of section 2.2; each was re-verified against its
datasheet. Stock was read on Digi-Key and on findchips.com (Mouser, Newark) on 2026-11-13.

### 2.2 Candidates

| Part | Package | Pin-compatible with TPS26630 RGE | Stock (2026-11-13) | Main deviations from B.4 |
|---|---|---|---|---|
| Toshiba TCKE1401NM,R1F | VQFN24D 4 x 4 mm, 0.5 mm | Yes: same pin map (Fig 5.1 against the B.8 U101 row); the fitted land covers the Toshiba land (Fig 13.2) | Mouser 1,984 from 1 piece ($4.61, 757-TCKE1401NMR1F); Digi-Key 3,000 as a 3,000-piece reel only | OVP reference 1.18-1.298 V gives a 22.18-24.39 V cutoff against the 22.6-23.6 V band; I_LIM about +-17 % (1.84-2.59 A at 9 kOhm); UVLO rising maximum 10.19 V against the FR-30 10.2 V threshold; IMON gain 22.3-33.5 uA/A; IN absolute maximum 80 V (better than 67 V) |
| TI TPS26601RHFR / RHFT | VQFN-24 RHF 5 x 4 mm, 0.5 mm | No (respin) | Mouser 562 (RHFR); Newark 89 (RHFT) | 150 mOhm; I_CB ceiling about 2.2 A; the circuit breaker latches after 4 ms instead of 129-202 ms; IN absolute maximum 62 V; IMON 78.28 uA/A |
| TI TPS26600PWPT | HTSSOP-16, 0.65 mm | No (respin) | 0 | no timed latch (auto-retry or TSD-only latch) |
| Analog Devices MAX17613A/B/C | TQFN-20 4 x 4 mm | No (respin) | Mouser 79 (B); Newark 1,352 (C) | 130-230 mOhm; FLAG does not cover OV/UV |
| Analog Devices MAX17525 / MAX17526A | TQFN-20 5 x 5 mm | No (respin) | Mouser 3,147 (MAX17525) | the OVP band fails (1.18-1.27 V reference) |
| TI TPS16851VMAR | LQFN-CLIP-23 6 x 5 mm | No (respin) | Mouser 1,087 | oversized; low-current OCP and IMON accuracy unverified |
| TI TPS16530RGER | VQFN-24 RGE 4 x 4 mm | Footprint yes, but pin 7 is an active-low EN | not checked | no precision OVP cutoff; fails B.4 |

TCKE1401NM is the only stocked part that fits the existing footprint, so it avoids a respin. It needs new values for
R101 (9.09 kOhm for 2.21 A typical, or 8.45 kOhm for 2.37 A), R103 (64.2 kOhm 0.1 %) and R104 (51.1 kOhm 0.1 %), and
an operator ruling on the OVP band, the I_LIM spread and the UVLO margin. Datasheet: Toshiba TCKE1401NM Rev. 3.0
(2026-10-09). **Decision (operator ruling 2026-11-13, chat: "Use TCKE1401NM for U101"):** TCKE1401NM is fitted without a
respin (`LAYOUT_DECISIONS.md` D-67), with R101 8.45 kOhm, R103 64.9 kOhm (64.2 kOhm 0.1 % is not stocked) and R104
51.1 kOhm, ordered from Mouser (`bom_2026-11-13/mouser_import.csv`). The respin of section 3 is therefore not
required now; section 3 stays the reference for any later board change. TPS26601RHFR remains the fallback if the
TCKE1401NM fails its bench tests (T-C-04).

## 3. Edits a respin must keep

The deltas below were measured every board delta below by parsing `cr/cr.kicad_pcb` and `eib/eib.kicad_pcb` at each commit and in the working tree. Segments were keyed by layer, net name, width and endpoints; vias by position, net and size; footprints and zones were compared too.

**Coordinate frames.** "KiCad" means the board file frame. "MB" means y = 100 − KiCad y (`gen/cr_geometry.py`, D-01). The docs mix the two:
- D-60/D-62 holes and the D-61 gap-fill vias are in the MB frame.
- D-65, D-66, `via_merge_cr.py` and `wire9_stitch.py` use the KiCad frame.
- The `547dc11` commit message uses the MB frame for its J101.9 via, (37.50, 46.03). That is KiCad (37.50, 53.97).

### 3.0 Headline points for the respin

1. **D-66 is entirely uncommitted.** This covers:
   - the board, schematic and netlist edits on both boards;
   - five new untracked scripts: `gen/swap_wire9.py`, `eib_sense_nc.py`, `prune_dangling.py`, `wire9_padvias.py`, `wire9_stitch.py`;
   - two untracked WirePads `.kicad_mod` files and two deleted FTSH `.kicad_mod` files;
   - the `gen/fplib.py`, `fpmap.py`, `netlist.py`, `sch.py` and `bom_split.py` changes;
   - the BOM files, and the `fab/cr_2026-11-13d/` and `fab/eib_2026-11-13b/` packages.

   A `git checkout`, `git stash` or regeneration loses all of it. Commit it before any respin work starts.
2. **No scripted sequence reproduces the current CR.** There are two breaks:
   - the operator's KiCad cleanup `547dc11` (manual);
   - one manual /GND via nudge in D-66.

   Three other parts depend on files or settings that are not committed:
   - The D-58 routing plan exists only outside the repo, at the side-session notes, now copied to `cr/routing_r9_notes/plan_softum.json`. The board-model and routes files for `plane_vias.py` are held by the routing session and are not in git either.
   - The exact D-66 `finish.sh`, `prune_dangling.py` and `straighten.py` arguments are not recorded.
   - `via_merge_cr.py` (D-65) and `wire9_stitch.py` are coordinate-keyed. `via_merge_cr.py` asserts that each via exists exactly once (`assert len(r) == 1`, 0.02 mm L1 tolerance). It aborts on any board that is not byte-for-byte the `e1f05d4` copper.
3. **Many preserved edits sit on the U101 network.** The operator's `547dc11` In2 re-draws of /N_FLT, /N_ILIM and /N_UV land on U101 pins 14, 10 and 6. Their bounding boxes span KiCad x 40.3–47.6, y 30.3–41.9, around U101 at (41.7, 36.35). Also nearby:
   - the In2 runs of /CHG_EFUSE_FLT and /CHG_IIN that start beside U101;
   - the operator's /GND via at (39.575, 31.475);
   - the D-65 SDA and SCL merges at y 42–46;
   - the D-65 deletion of the /GND via at C129.1.

   A U101 footprint swap re-routes those nets anyway. Every other edit is away from U101 and can be preserved.
4. **Recommended respin path (my assessment, not tested):** an in-place U101 swap on the current board.
   - Model it on `gen/swap_wire9.py`: replace the footprint at (41.7, 36.35, rotation 90).
   - Delete the copper that conflicts with the new footprint, then run `prune_dangling.py` on the U101 nets.
   - Reconnect with `finish.sh` or the corridor router held to the U101 region, then run `straighten.py --nets <U101 nets>`, `stitch_gaps.py`, `silk_refs.py`, the checks and the export.

   Every edit in sections 3.1 and 3.2 then survives except the U101-adjacent ones. A full regeneration from `make_board.sh` loses all of sections 3.1 and 3.2.

### 3.1 CR edits

#### 3.1.1 Scripted finish steps D-59 to D-62 (before the manual break)

These come from the routing session: the board was routed at `621fb28`, then trimmed, stitched, straightened and gap-filled to the D-62 board at `89c2d72`.

| ID | What changed | Reproducible by | Respin must |
|---|---|---|---|
| D-58 | Corridor-router signal routing: plan softum, seed 1. 148 router vias, 830.8 mm of track. | `tools/pcb/corridor_route/` (board-routing skill: model, `seeds.py run`, `apply_routes.py`, `plane_vias.py`). The plan file was only in the side-session notes; it is now copied to `cr/routing_r9_notes/`. Determinism across rebuilds is not verified. | `cr/routing_r9_notes/plan_softum.json` is the plan (copied 2026-11-13). After `114ad04`, plan softu at the 0.05 mm mask margin is equivalent. The soft keep-outs at the divider tops (R102, R109, R111, R114) and via cost 200 on /N_UV, /N_OV, /N_DVDT and /N_ILIM are U101-network constraints, so carry them into any U101 re-route. |
| D-59 | Reference placement. | `gen/silk_refs.py cr/cr.kicad_pcb cr/silk_refs.md` | Re-run last, after all copper work. |
| D-60/D-62 | Trimmed outline (10 corners, 1.0 mm fillets) and MH1–MH4. | `gen/trim_cr.py <work dir>`, using `FINAL_OUTLINE`, `KEY_EAR`, `MOUNTING_HOLES`, `TRIM_ANGLES`, `TRIM_MIN_EDGE` and `FILLET` from `gen/cr_geometry.py`. It refuses a board that is already trimmed. | Run on an untrimmed routed board, or keep the current Edge.Cuts. A U101 swap does not touch it. |
| D-61 (re-run in D-62) | 279 /GND grid stitching vias, straightening, and 3 gap-fill vias at MB (36.04, 26.88), (34.29, 33.53) and (33.54, 59.53). | `plane_vias.py <model> <plan> <routes> cr/cr.kicad_pcb <out routes> --stitch 2.5`, then `apply_routes.py`, `straighten.py cr/cr.kicad_pcb <out>` and `stitch_gaps.py cr/cr.kicad_pcb <out> --y-flip-offset 100`. Copy each output board back over `cr/cr.kicad_pcb`. | Do not run `route.py stitch()` as well. After a U101 swap, run `stitch_gaps.py` locally so the D-20 row (≤ 3.54 mm) still passes. |
| `6804a16` / D-62 | J102 MPN and cable fields. | `gen/sync_fields.py cr/cr.kicad_pcb cr/cr.net` | Re-run after any netlist regeneration. |

#### 3.1.2 Manual operator cleanup `547dc11` (KiCad GUI)

Board `89c2d72` (= `547dc11^`) to `547dc11`:
- No footprint, zone outline, Edge.Cuts or text changed.
- Segments went from 779 to 735: 123 deleted and 79 added, **all on In2.Cu**, all 0.1524 mm.
- Track length went from 837.5 to 839.8 mm.
- No signal via moved, so every re-draw runs between the existing via and pad endpoints, mostly as 45-degree runs.
- `cr.kicad_pro` gained only KiCad's default ERC/BOM sections on save. No rule changed, and `cr.kicad_dru` is unchanged.

**Table 1.2a. In2.Cu re-draws per net (`547dc11`).**

| Net | Deleted segments / mm | Added segments / mm | KiCad bounding box | Still in the current board |
|---|---|---|---|---|
| /3V3 | 11 / 16.87 | 11 / 17.31 | x 25.85–39.49, y 52.89–67.98 | 11 of 11 |
| /CE_DRV | 5 / 3.62 | 4 / 3.62 | x 39.95–41.32, y 63.40–66.45 | 4 of 4 |
| /CE_DRV_J | 13 / 3.31 | 2 / 3.25 | x 37.74–38.12, y 55.18–58.30 | 0 of 2 (replaced in D-66) |
| /CHG_EFUSE_FLT | 7 / 35.38 | 3 / 35.38 | x 47.41–51.53, y 31.71–65.39 | 3 of 3 |
| /CHG_IIN | 14 / 49.84 | 11 / 50.79 | x 46.19–53.88, y 30.95–74.99 | 11 of 11 |
| /FCC_TAP | 4 / 4.52 | 2 / 4.52 | x 42.54–45.36, y 76.28–79.64 | 2 of 2 |
| /H1 | 3 / 2.70 | 3 / 2.71 | x 26.08–28.36, y 68.51–69.50 | 3 of 3 |
| /H1_RB | 9 / 6.48 | 3 / 6.48 | x 37.05–39.18, y 63.10–68.13 | 3 of 3 |
| /ILIM_REL | 7 / 4.09 | 4 / 4.09 | x 39.57–41.77, y 60.20–66.07 | 4 of 4 |
| /N_FLT (U101.14) | 5 / 7.54 | 5 / 8.13 | x 40.27–44.52, y 30.26–33.46 | 5 of 5 |
| /N_H1M | 4 / 6.79 | 2 / 6.66 | x 25.16–30.50, y 58.60–61.80 | 2 of 2 |
| /N_ILIM (U101.10) | 7 / 5.89 | 6 / 6.42 | x 42.61–45.23, y 31.05–34.45 | 6 of 6 |
| /N_UV (U101.6) | 6 / 9.23 | 4 / 9.13 | x 45.20–47.57, y 35.52–41.92 | 4 of 4 |
| /T1_VMOT | 18 / 35.49 | 11 / 35.32 | x 22.88–51.38, y 61.58–81.54 | 11 of 11 |
| /T2C | 10 / 31.04 | 8 / 31.23 | x 25.16–49.55, y 67.98–82.08 | 8 of 8 |

The operator also made /GND via changes. 13 vias were removed and 10 added (449 to 446), all 0.6 / 0.3 mm. In KiCad coordinates:

**Moved (9):**
- (28.135, 59.366) → (28.575, 59.400)
- (32.098, 74.759) → (32.095, 74.705)
- (35.603, 52.127) → (35.850, 52.625)
- (36.746, 51.137) → (36.725, 51.025); D-66 later nudged this one to (36.605, 51.025)
- (36.746, 56.318) → (36.781, 56.256); deleted later in D-65
- (39.870, 31.477) → (39.575, 31.475)
- (43.375, 79.483) → (43.825, 79.575)
- (47.490, 34.906) → (48.468, 35.102); deleted later in D-65 (C129.1)
- (53.205, 43.745) → (52.725, 43.875)

**Deleted (4):** (29.964, 74.378), (35.222, 79.407), (36.289, 55.861) and (48.481, 31.553).

**Added (1):** (37.500, 53.967), on J101 pad 9. D-65 deleted it later.

**Reproducibility:** no script. The exact geometry exists only in `547dc11:hardware/charger_evm_r8/cr/cr.kicad_pcb`. Appendix A gives the added polylines.

`cr/cr.kicad_pcb_RTbackup.kicad_pcb`, `.kicad_pro` and `.kicad_dru` are untracked. Their copper equals `547dc11` exactly (0 differences), and neither file has arcs, so they hold nothing extra.

**What a respin must do:** keep these In2 segments and the six surviving operator vias. In a full regeneration, transplant them: copy the In2.Cu segments of the 14 nets other than /CE_DRV_J, and the six vias, from the current board. Then run DRC, because the re-generated F.Cu or vias may differ. Expect the /N_FLT, /N_ILIM and /N_UV re-draws, and the U101 ends of /CHG_EFUSE_FLT and /CHG_IIN, to be invalidated by the U101 swap.

#### 3.1.3 D-65, `f56cd29` (scripted, but only on the `547dc11` board)

- Segments went from 735 to 699: 47 deleted (In2 jogs and F.Cu stubs) and 11 F.Cu segments added.
- Vias went from 446 to 428.
- Nets affected: /SDA, /SCL, /TS_EXT and /J3V3_1 (both vias deleted); /N_H1M, /N_FNP, /N_UVP and /3V3 (four pairs, one via each).
- Three /GND vias deleted: (48.47, 35.10), (37.50, 53.97) and (36.78, 56.26). All three are operator vias from `547dc11`.
- The GATE pair at (42.46, 64.93) / (43.91, 64.78) is kept.
- Zones were refilled only. No footprint changed.

**Reproducible by:** `"$PY" gen/via_merge_cr.py <in.kicad_pcb> <out.kicad_pcb>`, run on the `e1f05d4` (= `547dc11`) board. Place copies of `cr/cr.kicad_pro` and `cr/cr.kicad_dru` with the same basename next to the input. The docs state that it reproduces `f56cd29` exactly.

**What a respin must do:** keep the result. Re-running the script on any other board aborts at its assert. For a fresh route, the equivalent rule is to forbid same-net via pairs that only jog on In2 for under about 1.4 mm, and to keep /GND vias off J101 pads and ≥ 0.1 mm from other-net mask openings.

#### 3.1.4 D-66, uncommitted working tree (J101 FTSH header → 3 × 3 PTH wire pads)

**Board delta, `f56cd29` → working tree.** Segments went from 699 to 692 (43 deleted, 36 added), track length from 838.1 to 818.7 mm, and vias from **428 to 420** by count in the file. LAYOUT_DECISIONS D-66 says "428 to 417". That figure probably predates the three `wire9_stitch` vias; correct it.

**Table 1.4a. D-66 changes per net.**

| Net | Deleted segments / mm | Added segments / mm | Layers |
|---|---|---|---|
| /CE_DRV_J | 5 / 7.09 | 16 / 5.78 | F.Cu deleted; In2 deleted and added |
| /CHG_ARM | 16 / 32.68 | 9 / 26.60 | In2 run moved to F.Cu |
| /ILIM_REL_B | 2 / 6.22 | 2 / 2.67 | F.Cu and In2 |
| /J3V3_1 | 1 / 1.07 | 2 / 1.28 | F.Cu |
| /J3V3_2 | 7 / 11.59 | 2 / 7.36 | F.Cu and In2 |
| /RFC_OFF_J | 4 / 5.27 | 2 / 2.41 | F.Cu and In2 |
| /STAT | 8 / 11.58 | 3 / 9.95 | F.Cu and In2 |

**Vias deleted (12):**
- /CE_DRV_J (36.746, 52.203)
- /CHG_ARM (36.517, 61.957)
- /ILIM_REL_A (40.403, 53.499)
- /ILIM_REL_B (40.937, 52.508)
- /J3V3_2 (44.290, 58.452) and (44.442, 49.689)
- /RFC_OFF_J (42.689, 58.452) and (44.442, 54.794)
- /STAT (43.985, 51.441)
- /GND (40.480, 51.594), (42.766, 51.594) and (36.725, 51.025)

**Vias added (4):** /GND (36.605, 51.025), (39.330, 51.900), (41.870, 51.900) and (41.870, 54.440).

**Footprint:** J101 changed to `WirePads_PTH_3x3_D1.0mm_Pad1.8mm_P2.54mm_CrtYd0.25` at (40.6, 53.17). The old reference text placement is kept. U101, U102 and U105 differ only by net renumbering, because the unconnected J101.11 and J101.13 nets were dropped.

**Schematic and netlist:** J101 symbol `JW9`, pins 1–5 and 7–10. Pins 11–14 are dropped. Regenerated by `gen/sch.py` and the kicad-cli netlist export.

**Reproducibility, in order** (from `hardware/charger_evm_r8`, pcbnew venv):
1. `"$PY" gen/fplib.py cr cr`, `"$PY" gen/sch.py cr cr`, `kicad-cli sch erc ...`, `kicad-cli sch export netlist --format kicadsexpr -o cr/cr.net cr/cr.kicad_sch`. These are the first four lines of `make_board.sh`. **Do not run `pcbbuild.py`**: it overwrites the routed board.
2. `"$PY" gen/swap_wire9.py cr`
3. `"$PY" gen/prune_dangling.py cr <nets>`. The net list is not recorded. It is probably /J3V3_1,/J3V3_2,/STAT,/CE_DRV_J,/ILIM_REL_A,/ILIM_REL_B,/RFC_OFF_J,/CHG_ARM (my inference).
4. `TRACK=0.1524 bash gen/finish.sh cr F.Cu,In2.Cu 0.6 0.3 /GND <rounds> <res> 0.1524`. The exact rounds, res and PROTECT values are not recorded.
5. `"$PY" ../../tools/pcb/corridor_route/straighten.py cr/cr.kicad_pcb <out> --nets <affected nets>`, then copy back. The net list is not recorded.
6. `"$PY" gen/wire9_padvias.py cr`
7. `"$PY" gen/wire9_stitch.py 41.87,54.44 41.87,51.90 39.33,51.90`
8. **Manual (no committed script):** move the /GND via from (36.725, 51.025) to (36.605, 51.025). This makes it 0.204 mm from the pad-1 mask opening, against 0.084 mm before.

The last finishing-router output is `cr/finish_routes.json` and `cr/finish_dump.json`, written at 16:59. Both are gitignored, so they are the only record of what the router produced.

**What a respin must do:**
- Keep the WIRE9 footprint, the D-66 wire-to-grid map (Table D-66; the CR and EIB grid orders differ by design) and the three in-grid stitching vias (or re-check D-20).
- Keep the via ≥ 0.2 mm from the J101 pad-1 mask.
- Keep B.Cu track-free (D-20).
- A U101 swap need not touch this area, which is about 15 mm from U101.

#### 3.1.5 BOM substitutions (`bom_2026-11-13/README.md` section 4, uncommitted)

No footprint or board change. Every substitute has the same package, and **the schematic and board MPN fields still name the original parts**. The substitutes exist only in `gen/bom_split.py` and the BOM CSVs.

Max thickness of each substitute (from `bom_split.py`):

| Ref | Substitute | Package | Max thickness |
|---|---|---|---|
| C102b | CNC6P1X7R2A475K250AE | 1210 | 2.80 mm |
| C102a | CL31B105KCHSFNE | 1206 | 1.80 mm |
| C103 | CL21B105KBFNNNF | 0805 | 1.35 mm |
| C125 | CL21B106KOQNNNE | 0805 | 1.40 mm |
| 10 µF parts | GMC21X5R106K50NT | 0805 | 1.50 mm |

The original part thicknesses are not recorded in the BOM README.

There is no board height limit (operator ruling 2026-11-10), so no layout action follows. A respin should decide one thing: either move the substitute MPNs into `gen/netlist.py` and re-run `sync_fields.py`, or keep them BOM-only. Note that `TPS26630RGER` (U101) is held out of the Digi-Key file for lack of stock.

### 3.2 EIB edits

| ID | Commit | What changed (measured) | Reproducible by | Respin must |
|---|---|---|---|---|
| D-63 | `f12a546` | Segments 479 → 418 (255 deleted, 194 added; F.Cu and B.Cu, 26 nets). Track length 608.4 → 604.0 mm. Vias 52 → 96 (44 /AGND added, none deleted). New zone `AGND_L1_pour` (F.Cu); `AGND_L2_pour_1` refilled. | (1) `straighten.py eib/eib.kicad_pcb <out> --clear 0.2`, run twice with copy-back. (2) The pour comes from `gen/route_eib.py gnd_pours()`, now in the generator. (3) **Inline, no script:** set top-pour island removal to off. (4) `stitch_gaps.py eib/eib.kicad_pcb <out> --net /AGND --clear 0.2 --hole-gap 0.28 --layer F.Cu`, then the same with `--layer B.Cu`. (5) **Inline, no script:** restore island removal and refill. | Keep the pours, the 44 vias and R273 as the only GND_J–AGND link. |
| D-64 | `e1f05d4` | 38 reference fields made visible and placed: 31 on F.Silkscreen, 7 on F.Fab. Copper unchanged. The footprint bodies differ only in their reference fields. | **Inline, no script:** make the 38 references visible on F.SilkS at 1.0 / 0.15 mm (`silk_refs.py` only moves references that are already visible). Then `"$PY" gen/silk_refs.py eib/eib.kicad_pcb eib/silk_refs.md`. | Repeat both steps after any copper change. |
| D-66 | uncommitted | J201 changed to a WIRE9 footprint (CrtYd 0.10) at (20, 31), with its own grid order (Table D-66). R264.2 and R265.2 not connected; /ILIM_SENSE and /CE_SENSE copper deleted. Segments 418 → 332 (285 deleted, 199 added). Track length 604.0 → 500.7 mm. Vias 96 → 94 (37 deleted, 35 added; /AGND unchanged). Re-routed: 3V3, GND_J, CE_DRV_J, ILIM_REL_A/B, N_ISM, N_ISP, N_RAIN, N_RFIN, N_U203O, Q201_G, Q202_G, REF203, REGN, RFC_OFF_J, STAT, nCE_DRV. Partly re-routed (straightening only): N_CSP and N_Q202D. Some old 0.16 mm segments are now 0.2 mm. | fplib, sch, ERC and netlist export for `eib` (no `pcbbuild`); `gen/swap_wire9.py eib`; `gen/eib_sense_nc.py`; `gen/prune_dangling.py eib <nets>`; `finish.sh eib F.Cu,B.Cu ...` at 0.2 mm track and clearance with rip-up. /3V3 was ripped, so PROTECT was not the default /3V3. Then `straighten.py` over all signal nets, three passes. **The `prune_dangling.py` nets, the `finish.sh` arguments and the two-attempt rip-up settings are not recorded.** | Keep the result as it is. A U101 swap does not touch the EIB. |

`3eb0cda` (EIB DNP set, 2026-11-13 05:24) is now reproducible: `pcbbuild.py` sets DNP from the netlist `dnp` property.

### 3.3 Command sequence that rebuilds the current boards

From `hardware/charger_evm_r8` in Git Bash:

```bash
export MSYS_NO_PATHCONV=1
PY="/c/Life Ops/School/Thesis/DC-Balancer-Board-Teensy/tools/pcb/.venv/Scripts/python.exe"
```

HANDOFF.md section 4 still names the old `DC-Balancer-round4` venv path, which is stale; `f12a546` moved the scripts to the path above.

#### 3.3.1 CR

```bash
# A. Libraries, schematic, netlist, placement, power copper (D-54..D-57 board)
bash gen/make_board.sh cr        # then restore cr/cr.net date line + 13 stamp-only library files from git
(cd gen && ROUTE_SKIP_FR=1 "$PY" route.py cr ../cr)
git checkout -- cr/cr.kicad_pro   # then refill zones with the board loaded as cr/cr.kicad_pcb (D-57 note)
# B. D-58 routing -> 621fb28: board-routing skill, cr/routing_r9_notes/plan_softum.json, seed 1:
#    model, seeds.py run, apply_routes.py, plane_vias.py
# C. D-60/D-62 trim
"$PY" gen/trim_cr.py <work dir>
# D. D-61 finish (copy each <out>/cr.kicad_pcb back over cr/cr.kicad_pcb)
"$PY" ../../tools/pcb/corridor_route/plane_vias.py <model> <plan> <routes> cr/cr.kicad_pcb <out routes> --stitch 2.5
"$PY" ../../tools/pcb/corridor_route/apply_routes.py cr/cr.kicad_pcb <out routes> <out>
"$PY" ../../tools/pcb/corridor_route/straighten.py cr/cr.kicad_pcb <out>
"$PY" ../../tools/pcb/corridor_route/stitch_gaps.py cr/cr.kicad_pcb <out> --y-flip-offset 100
"$PY" gen/silk_refs.py cr/cr.kicad_pcb cr/silk_refs.md
"$PY" gen/sync_fields.py cr/cr.kicad_pcb cr/cr.net            # = 89c2d72 (not re-verified)
# E. BREAK 1: operator KiCad cleanup 547dc11 (section 3.1.2) - manual only
# F. D-65 (input must be exactly the 547dc11 copper; .kicad_pro/.kicad_dru copies beside it)
"$PY" gen/via_merge_cr.py <in.kicad_pcb> <out.kicad_pcb>       # = f56cd29
# G. D-66: section 3.1.4, steps 1-7 (unrecorded arguments)
# H. BREAK 2: /GND via (36.725, 51.025) -> (36.605, 51.025), manual
# I. Checks and package
(cd gen && "$PY" check_constraints.py cr ../cr > ../cr/constraint_check.md)
"/c/Program Files/KiCad/9.0/bin/kicad-cli.exe" pcb drc --severity-all --schematic-parity -o cr/drc.rpt cr/cr.kicad_pcb
bash gen/export.sh cr <date> && "$PY" gen/fab_readme.py cr <date> [<reference package dir>]
```

`gen/make_cr_all.sh` is the r7-outline PathFinder flow and does **not** build this board.

#### 3.3.2 EIB

```bash
bash gen/make_eib_all.sh   # make_board eib; route.py eib (Freerouting 2.5.0);
                           # finish.sh eib F.Cu,B.Cu 0.6 0.3 "" 6 0.05 0.16 -> D-28 board (469d94f)
                           # Freerouting repeatability not verified
# D-63: section 3.2 steps (1)-(5), two of them inline
# D-64: inline reference visibility, then silk_refs.py
# D-66: section 3.2, unrecorded arguments
# Checks and package as for the CR
```

#### 3.3.3 Where the sequence breaks

**CR:**
- Step B: the plan, model and routes files are outside the repo, and router determinism is not verified.
- Step E: `547dc11` is manual.
- Step F: only works on the exact `547dc11` copper.
- Step G: the arguments are unrecorded.
- Step H: manual.

**EIB:**
- Freerouting repeatability is not verified.
- D-63 has two inline island-removal toggles, and D-64 has the inline visibility step.
- The D-66 arguments are unrecorded.

**Conclusion:** the only lossless base for a respin is the current working-tree `cr/cr.kicad_pcb` (after D-66 is committed), edited in place.

### Appendix A. Segments added in `547dc11` (In2.Cu, 0.1524 mm, KiCad frame)

- /3V3: (26.680,66.834)-(26.764,66.750); (35.831,53.651)-(35.831,59.138); (26.764,65.996)-(26.764,66.750); (25.849,66.834)-(26.680,66.834); (27.399,64.650)-(27.933,64.650); (39.184,64.014)-(39.184,64.109); (35.069,52.889)-(35.831,53.651); (39.489,64.414)-(39.489,67.977); (27.933,64.650)-(30.802,67.520); (39.184,64.109)-(39.489,64.414); (27.145,64.395)-(27.399,64.650)
- /CE_DRV: (41.318,65.993)-(41.318,66.453); (40.708,65.383)-(41.318,65.993); (40.708,64.167)-(40.708,65.383); (39.946,63.405)-(40.708,64.167)
- /CE_DRV_J (superseded by D-66): (38.041,55.480)-(38.041,58.299); (37.736,55.175)-(38.041,55.480)
- /CHG_EFUSE_FLT: (47.414,31.706)-(47.414,35.014); (47.414,35.014)-(51.529,39.129); (51.529,39.129)-(51.529,65.386)
- /CHG_IIN: (46.800,30.950)-(47.775,30.950); (53.867,68.617)-(53.875,68.625); (46.195,31.555)-(46.195,31.858); (46.195,31.555)-(46.800,30.950); (47.775,30.950)-(48.225,31.400); (53.867,68.617)-(53.875,68.617); (53.875,68.625)-(53.875,69.974); (48.862,74.987)-(53.875,69.974); (48.225,31.400)-(48.225,32.822); (53.875,38.472)-(53.875,68.617); (48.225,32.822)-(53.875,38.472)
- /FCC_TAP: (42.537,79.635)-(45.356,76.816); (45.356,76.283)-(45.356,76.816)
- /H1: (27.051,69.501)-(28.364,69.501); (26.078,68.528)-(27.051,69.501); (26.078,68.510)-(26.078,68.528)
- /H1_RB: (37.813,68.129)-(39.184,66.758); (39.184,65.234)-(39.184,66.758); (37.051,63.100)-(39.184,65.234)
- /ILIM_REL: (41.470,64.167)-(41.470,65.370); (39.565,60.204)-(39.565,62.262); (41.470,65.370)-(41.775,65.675); (41.775,65.675)-(41.775,66.072)
- /N_FLT: (41.442,30.258)-(44.518,30.258); (40.275,31.425)-(40.275,32.200); (40.275,32.200)-(41.533,33.458); (40.275,31.425)-(41.442,30.258); (41.533,33.458)-(42.385,33.458)
- /N_H1M: (25.163,61.805)-(28.364,58.604); (28.364,58.604)-(30.497,58.604)
- /N_ILIM: (43.325,31.050)-(44.750,31.050); (42.669,31.706)-(43.325,31.050); (44.213,34.449)-(45.225,33.437); (44.750,31.050)-(45.225,31.525); (42.613,31.706)-(42.669,31.706); (45.225,31.525)-(45.225,33.437)
- /N_UV: (47.490,37.116)-(47.490,41.535); (47.109,41.916)-(47.490,41.535); (45.890,35.516)-(47.490,37.116); (45.204,41.916)-(47.109,41.916)
- /T1_VMOT: (31.889,75.262)-(32.037,75.262); (32.037,75.262)-(37.020,80.245); (37.020,80.245)-(45.966,80.245); (25.544,67.901)-(25.544,68.792); (47.261,81.540)-(48.328,81.540); (31.594,74.842)-(31.594,74.967); (31.594,74.967)-(31.889,75.262); (22.877,61.957)-(23.258,61.576); (25.544,68.792)-(31.594,74.842); (22.877,61.957)-(22.877,65.234); (48.328,81.540)-(51.376,78.492)
- /T2C: (25.163,67.977)-(25.163,69.038); (48.632,82.075)-(49.547,81.159); (36.974,80.855)-(45.580,80.855); (25.163,69.038)-(30.497,74.372); (30.497,74.372)-(30.497,74.378); (46.800,82.075)-(48.632,82.075); (45.580,80.855)-(46.800,82.075); (30.497,74.378)-(36.974,80.855)

The diff tool used for these figures is `gen/pcbdiff.py`. Usage: `python gen/pcbdiff.py <rev>:<path> WT:<path>`. It compares by net name, so it can be reused to check that a rebuilt board keeps these edits.
