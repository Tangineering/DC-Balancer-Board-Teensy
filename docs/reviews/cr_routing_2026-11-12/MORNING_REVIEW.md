# CR Routability Study: Morning Review, 2026-11-12

## 1. Scope

This document reports the overnight routability study of the charger EVM r8 CR board (4 layers) under the
`route-race` skill. It lists the measured results, the decisions that the routing orchestrator took within its
delegation, and the items that need an operator ruling. The EIB board is outside the scope of this study: the
design owner reported it complete (DRC 0, fab package `fab/eib_2026-11-11`).

The design owner (session "EVM design updates") writes a combined review at
`hardware/charger_evm_r8/MORNING_REVIEW_2026-11-12.md` on branch `charger-evm-round4`. Its decision 4 and item 4.1
concern constraint (c) and are referenced below. The full numbers are in the shared notes folder of that session,
`routing_r1_cr/` (`BATCH_NOTE.md`, `CHANGE_REQUESTS.md`, `ROUND2_RESULTS.md`).

## 2. Method

- Boards: `cr.kicad_pcb` of commit 5ddc21a (tier 3 DNP removed) as the base, and variants `r1_A` and `r1_B` of
  commit c7dc669. Every test ran on a scratch copy. No project file, generator or worktree of another session
  was written.
- Via rule VR-1: no via on an SMD pad or in its mask opening (operator ruling 2026-11-11).
- Every figure is for seeds 1 to 4 with a 60-iteration limit. A difference is a result only when it has the same
  sign at all four seeds. Every run ended in the legalisation step with 26 to 58 nets still in conflict, so the
  completion figures come from legalisation, not from a converged negotiation.
- Completion counts the connections of non-plane nets, 199 in total.

## 3. Results

### 3.1 Round 1 (base board)

The plain plan made 174, 170, 169 and 170 connections (mean 170.8). Seed 1 is valid: 25 connections open, 0 vias
on SMD pads, 3 new starved thermals. Table 1 lists every round-1 test.

Table 1. Round-1 tests against the plain plan (connections made, seeds 1 to 4).

| Test | Result | Verdict |
|---|---|---|
| /3V3 held out (bound for a fill or rail) | remaining 143 connections open 25/29/30/29 -> 23/16/15/16 | gain (overstated) |
| /3V3 as a soft fill on In2.Cu, x 18.5-37.5 | remaining open 22/17/23/27; 35-45 of 57 /3V3 pads without a via site | not adopted |
| /3V3 tracks on F.Cu and B.Cu only | 163/160/169/168 | not separated (-5.8) |
| /3V3 at priority 5 | 169/166/173/173 | not separated (-0.5) |
| /SCL, /SDA at priority 3 | 171/167/163/175 | not separated (-1.8) |
| J101 group at priority 4 | 167/166/162/165 | worse at every seed (-5.8) |
| Via 0.554/0.254 mm | 167/173/173/170 | not separated (0.0) |
| R147 rotated 90 degrees (two forms) | relief trials | rejected |
| R101 +0.20 mm; R101 and R105 +0.40 mm | relief trials; /N_DVDT open at every seed | rejected |
| R129 moved; R129 and R122 moved | relief trials | rejected |

The capacity check found one defect of the placement: pad R147.2 (/QUAL) was enclosed by the VCHGOUT L4 strap and
could not be reached on an empty board. The design owner corrected this in variant A. The earlier "U101 +x
pocket" limit (R101/R105 +y) did not hold on this board; the design owner withdrew that request.

### 3.2 Constraint (c): divider-top keep-away

The plain plan does not enforce constraint (c). The design owner ruled the binding form (D-35): no logic-net
copper on F.Cu and no logic-net via within 2.0 mm of R102, R109, R111 and R114. Ten logic pads already lie inside
that zone by placement (J1.7, J1.8, J101.7, J101.11, J101.13, U102.1, U103.1, U105.5, U109.1, U109.3); the design
owner exempted each pad with one F.Cu escape. The exemption of the three packer-placed pins (U105, U109) is
interim and is the operator's item 4.1.

The router has no hard per-net keep-out. A reserved zone with a cost of 30 times the base cost reduced the F.Cu
residual to 1 piece per seed. However, it left 6 to 9 logic vias in the zone and cost 4.5 connections on
average (worse at every seed). A cost of 300 did not remove the vias (2 to 9 per seed). No run is compliant.

### 3.3 Round 2 (variants of the design owner)

Table 2 compares the variants under the binding plan.

Table 2. Round 2, binding plan (connections made, seeds 1 to 4).

| Board | Made | Mean | Verdict |
|---|---|---|---|
| base | 173/167/161/164 | 166.2 | reference |
| r1_A (strap keep-out; R147 off the strap) | 173/162/170/171 | 169.0 | not separated (+2.8) |
| r1_B (A plus grid re-pack; packer dispersed the grid) | 167/167/177/166 | 169.2 | not separated (+3.0) |

No round-2 change has a gain verdict, so the loop stopped under the skill's stop rule after two rounds. The best
scored result is r1_B at seed 3: 177 of 199 made, valid, 0 vias on SMD pads, 1 new starved thermal (J1 pad 4).
After the plane-via step, 27 GND connections stay open and 34 GND fill pieces have no via site under VR-1.

### 3.4 Other constraints

- Timing nets (D-18): maximum copper y is 55.86 against the limit 66.862 on every run. Pass.
- /N_FLT and /CHG_EFUSE_FLT: 2 vias each on most runs, 4 on /N_FLT at some seeds. The one-via target is not met.
- The comparator analog nets enter the U101 commutation-loop region on some runs (preference only). For
  example, /N_FNP enters it on seed 1 of the round-1 reference; this was not tracked on every run.

## 4. Decisions taken by the orchestrator

The operator should review these decisions. Each one can be reversed without loss of data; the runs remain in the
scratch race folder.

1. **/3V3 stays as tracks** (delegated by the operator on 2026-11-11). The hold-out bound is +10.8 connections.
   However, the one real form that the tools can model, a soft In2.Cu fill, left 35 to 45 of the 57 /3V3 pads
   without a via site. A hard In2.Cu zone fails the capacity check because the timing nets and /KELVIN cannot
   reach their pads. Reversal: request a generator-built /3V3 fill variant with its own pad vias.
2. **Net classes for the (c) residual.** The orchestrator counted /N_UV, /N_OV, /N_IMON, /N_DVDT, /N_ILIM and
   /BT_CURR as analog (exempt) and the timing net /N_CX111 as logic. The design owner's definition does not name
   these nets explicitly.
3. **Plan tests without corridors.** CR1-04 (I2C) and CR1-05 (J101 group) were tested as priorities only. The
   skill records that corridors which hold nets lost connections in every dry test.
4. **Stop after two rounds.** The stop rule ("a round has no change with a gain verdict") applied in both rounds.
   A third round was not started.
5. **Scorer correction.** The first (c) counts that the orchestrator sent to the design owner were wrong because
   of a coordinate-frame error in a scratch checker. The error was found and a correction was sent before the
   round-2 batch. The placement list of Section 3.2 was not affected.

## 5. Items for the operator

1. **Constraint (c) (design-owner decision 4 and item 4.1).** Confirm the F.Cu-plus-vias scope, the ten pad
   exemptions, and the interim exemption of U105.5, U109.1 and U109.3.
2. **How to close the CR.** The best result is 22 signal and 27 GND connections from closed, plus the (c) via
   residual. This is not "a few connections". The options are:
   - a substantial interactive pass in the KiCad GUI, starting from r1_B seed 3;
   - a router change that enforces the (c) zone as a hard keep-out for logic tracks and vias;
   - a ruling on the layer count. VR-1 is final, so the via rule is not an option.
3. **Branch of the variants.** Variants A and B are on `charger-evm-round4` (commit c7dc669; the D-35
   amendment is commit 51077bc). Neither is separated from the base at four seeds. The design owner has since
   made the strap keep-out of A the default placement (its decision 6, commit e4a3e97); B is not adopted.
   The design owner's list of options includes relaxing the via rule; the 2026-11-11 ruling made VR-1 final.

### 5.1 Round 3 (added 2026-11-12, day)

The design owner relayed operator rulings of 2026-11-12: tented vias inside SMD pads are acceptable, and the
divider-top rule is an all-layer optimisation metric. The committed design-owner review at 13a14fc still states
VR-1 as final, so the relaxation rests on the relay alone. Round 3 ran on 13a14fc (identical placement to r1_A)
with via-in-pad allowed. The full report is `routing_r1_cr/ROUND3_RESULTS.md`.

- The plain plan made 180.5 on average (179 to 182). With soft all-layer divider zones it made 179.5 (178 to
  181), which is not separated.
- The soft zones reduced the logic length parallel to analog copper in the zone from 7.2-12.1 mm to 0.0-1.8 mm
  (same layer) at every seed.
- After the plane-via step, 11 to 19 GND connections stay open. In2.Cu tracks block most of the remaining via
  sites.
- The router placed 102 to 119 signal vias in SMD pads per seed, because it has no cost on that choice. The
  operator should confirm the count is acceptable at this scale.

## 6. Tool faults found

- On the round-1 best seed, the plane-via apply and zone refill added 13 DRC items at J1 pad 14 (GND, PTH) against
  a /W track on In2.Cu. Cause found in round 3: a plane via beside a GND through-hole pad that is not flashed on
  In2.Cu makes KiCad flash the pad there, onto the routed tracks. `plane_vias.py --respect-unflashed` (new,
  opt-in, uncommitted) keeps the vias off those sites.
- `seeds.py compare` cannot read a `whatif.py holdout` folder (no `SEEDS.json`), so hold-out runs are compared by
  hand.

## 7. Locations

- Race folder (scratch, temporary):
  `C:\Users\ricky\AppData\Local\Temp\claude\e80299759e621188\67a97ad9-62a0-4f0f-a3e2-bbc3982f4e27\scratchpad\RACE`,
  with `STATUS.md` for a resume. The best routed board is `cr\r2_B\ref\seeds\s3\board_pv\cr.kicad_pcb` in it.
- Batch and results: the design owner's notes folder, `routing_r1_cr/`.
