# CR r9 route-race, round 1: results and change requests (base 86cd19d)

## 1. Scope

This note reports round 1 of the route-race on the r9 CR board (`hardware/charger_evm_r8/cr/cr.kicad_pcb` of commit
86cd19d, sha256 d9e30438..., identical to the D-56 probe board). It lists the tested plans with their verdicts and one
change request. Every figure is for seeds 1 to 4 with a 60-iteration limit; every run ended with no conflict left, so
no figure comes from legalisation. A difference is a result only when it has the same sign at all four seeds.

- Routing: F.Cu and In2.Cu, 0.1524 / 0.1524 mm, via 0.6 / 0.3 mm, `via_in_pad` false (D-37 step 1), plane net /GND.
- Tools: `tools/pcb/corridor_route` on branch `charger-evm-r9-route`, commit ce47d93 (N-5 fix).
- Control: the D-56 probe plan, unchanged (`plan_ref.json`). The control reproduces the probe at every seed (router
  vias 155/149/149/155, divider metric 19.97/0.90/8.87/0.00 mm), so the N-5 fix changes no route on this board.
- Divider metric: `parallel_metric.py` with the probe arguments. The frame check passes: R109.1 reads design
  (26.922, 43.125). Broadside length is 0 on every run (no B.Cu routing; In1.Cu shields F.Cu from In2.Cu).

## 2. Tool changes (branch charger-evm-r9-route, commit ce47d93)

- **N-5.** `board_model.py` marks each pad with `drilled` (the pad has its own hole); `core.py` bans a via on a pad
  without one. The former (ref, number) key exempted U101.25 because its nine thermal vias are holes numbered 25.
  Old models fall back to the old key. `smd_ban_test.py` asserts that no legal via cell lies inside a banned SMD pad
  grown by the via radius and mask margin; it passes with the fix and finds 802 legal cells in U101.25 with the old
  `core.py`.
- **D-55 m-9 review.** The SMD keep-out of `plane_vias.py` was correct for `via_in_pad` false, but it ignored a
  `true` value or a list. It now admits the pads that the plan admits, as the router does; `--allow-via-in-pad`
  still removes the keep-out. The plane-via step placed no via in an SMD pad on any of the 28 finished seeds.

## 3. Results

Table 1 summarises the plans. All runs make 107 of 107 connections unless stated, are valid before and after the
plane-via step, and have 0 vias on SMD pads. The full per-seed table is `TABLE.md`.

Table 1. Plans against the control (seeds 1-4; paired differences in brackets).

| Plan | Change | Router vias | Logic length in the divider zone, mm | U101 hi-Z vias | /GND open after plane vias | Verdict |
|---|---|---|---|---|---|---|
| ref | D-56 probe plan | 155/149/149/155 | 24.4/7.4/16.3/7.3 | 14/13/14/13 | 1/1/1/1 | control |
| soft | divider-top zones on F.Cu and In2.Cu at reserve 30; /3V3 and the analog groups exempt | 152/146/148/148 (-3,-3,-1,-7) | 0.1/0.1/0.1/0.4 | 14 | 2/1/1/1 | gain (vias, zone length) |
| guide | `route_cr.GUIDE_CORRIDORS` as guides for /T1_VMOT, /T2C | 151/148/148/150 (-4,-1,-1,-5) | 6.8/6.8/6.8/8.2 | 13-14 | 1/1/1/1 | gain (vias); the two tap nets 10-25 mm longer |
| soft + guide | both | 152/149/154/149 | 0.1-0.4 | 13-14 | 1/2/1/2 | not separated from soft; longer |
| u101 | U101 hi-Z nodes incl. N_IMON, N_FLT at via cost 200 | 139-147 | - | 6 | - | worse: /N_FLT open at every seed (106/107) |
| u101b | as u101, /N_FLT at via cost 40 | 139-147 | - | 6 | - | worse: /N_FLT open at every seed |
| u101c | /N_UV, /N_OV, /N_DVDT, /N_ILIM at via cost 200 | 150/144/149/149 | 7.3-13.2 | 9 at every seed | 1/2/1/2 | gain (hi-Z vias) |
| **softu** | soft + u101c | **145/143/144/148 (-10,-6,-5,-7)** | **0.1/0.2/0.1/0.1** | **9 at every seed** | 1/2/3/1 | **gain on all three; chosen** |
| swap R105 / R106s | placement variant (scratch), control plan | 156/153/151/150 | - | 13 | - | refuted: no gain; fails D-55 B-1 |

The table shows the following:

- The divider-top same-layer parallel metric is 0.00 mm at every seed of `soft` and `softu` (control
  19.97/0.90/8.87/0.00). Seed 4 of the control is also 0, so this column alone is not separated; the logic length in
  the zone is lower at every seed. One logic via stays in the zone at most seeds (the /CE_DRV_J escape, as in the
  probe).
- **U101 high-impedance nodes.** In the control every one of the six nets uses a via pair. The router prefers two
  vias at cost 40 to a few millimetres of the soft F.Cu GND fill around the pocket. At via cost 200, /N_OV and
  /N_ILIM route with 0 vias; /N_UV and /N_DVDT keep 2 at every seed, so those pairs are forced by the pocket
  geometry.
- **N_IMON / N_FLT.** The pair crosses by topology: U101 pin 14 (/N_FLT) lies west of pin 13 (/N_IMON), R106s is
  east, and /N_IMON branches to R105 (west) and R129 (east). /N_IMON takes 3 vias and /N_FLT 2 in every plan. A via
  cost of 200 on /N_IMON leaves /N_FLT open at every seed. The swap of R105 and R106s (same 0603 footprint) removes
  one /N_IMON via (2 instead of 3) and no /N_FLT via, and it fails the D-55 B-1 row (the /CHG_EFUSE_FLT ratsnest then
  crosses the CHG +x pin column); it is refuted.
- Guide corridors reduce the via count but make /T1_VMOT and /T2C 10-25 mm longer, and add nothing on top of the
  soft zones. They are not adopted.
- /GND after the plane-via step: 1 to 3 open on `softu`, 1 on the control (not separated). C102c.2 is open in every
  run of every plan (request R9-01). The other pieces are In2.Cu-blocked fill pieces at single seeds.

## 4. Change request

**R9-01 (pour_or_rail / placement, untested): C102c.2 /GND is cut off at every seed of every plan.** The /N_UV track
from U101.6 to R102.2 encloses the GND_L1_fill piece of C102c.2 (1.7 mm2 at design (42.9, 59.4)). The piece is closed
on all sides: U101 pins 6-7 and their escapes (/N_UV, /N_OV) to the north and east, the J1 +x pin column (J1.9 is
unconnected; the 0.64 mm pad gaps hold no fill) to the east, R102 to the south, and VCHGIN_L1 with the pin-5 tie to
the west. `nosite_why.py` finds no via cell: the VCHGIN_L3_strap blocks every cell on In2.Cu. No plan can close it;
the routed board keeps one unconnected item until the pour, strap or placement changes. The candidates of
`cr/probe_d56.md` section 4.1 stand (a /N_UV pre-track on the -x side of C102c.2 with a VIN_L1 notch; a /GND pre-via
in a strap cut-out with R9.H25 re-run; a C102c move). Evidence: `TABLE.md` (28 finished seeds),
`seeds_*/s*/nosite.txt` in the race folder.

## 5. Next step

On a new commit with R9-01 resolved, the orchestrator routes `plan_softu.json` at seeds 1-4, finishes the seeds,
picks the best valid seed, applies it to the board on `charger-evm-r9-route`, and runs DRC. If no change comes back,
the orchestrator applies `softu` seed 1 (145 vias; /GND open after plane vias: C102c.2 only) to 86cd19d and reports
the single unconnected item.

Race folder (scratch): `RACE9` in the orchestrator scratchpad, with `STATUS.md`, the plans, `seeds_<plan>/`, and the
swap variant in `var_swap/`.
