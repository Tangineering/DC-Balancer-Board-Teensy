# ROUTABILITY: plain-plan probe of the D-56 CR board

## 1. Scope and method

This note records a four-seed routability probe of the live CR board after the D-56 fix round
(`cr/cr.kicad_pcb`, sha256 `d9e30438...a4a5`, pour stage, no signal routing). The probe follows the
board-routing skill on a scratch copy only. The live board was not written.

The plan is the D-54 probe plan without change:

- rules: track 0.1524 mm, clearance 0.1524 mm, via 0.6 / 0.3 mm, `via_in_pad` false;
- routing layers F.Cu and In2.Cu, plane net /GND, frame `y_flip_offset` 100;
- groups: /3V3 (free, priority 1), `analog_short` (local, margin 2.5, priority 1, via cost 40),
  `analog_long` (free, priority 2, via cost 40), all other nets free at priority 5.

Each seed was finished in the skill order: apply, score, plane vias, apply, score, parallel metric. The
divider-top metric is the `parallel_metric.py` same-layer length of logic track parallel to analog track in the
zone of R102, R109, R111 and R114, with the D-54 net lists and exempt pins. The frame check of the metric passed:
R109.1 reads design (26.922, 43.125), and `cr/placement_log.txt` places R109 at (27.834, 43.125) with the pad
0.912 mm to -x of the centre.

## 2. Capacity check

`capacity.py` reports 0 sealed pads, no plan error, every net routable alone, and the result PASS. The D-55
board had 4 sealed pads (U101.6, U101.7, U101.9, R102.2) behind the VCHGIN_L1 extension. The one congestion cell
above 1.0 is (43.53, 63.05), the U101 +x pocket, at utilisation 1.46; it is information only.

## 3. Results

Table 1 gives the result of each seed. All four seeds stopped with no conflict left (15 to 19 iterations, 60
allowed); no result comes from legalisation.

Table 1. Plain plan on the D-56 board (107 non-plane connections; lengths in mm; plan frame).

| Measure | Seed 1 | Seed 2 | Seed 3 | Seed 4 |
|---|---|---|---|---|
| Open connections, non-plane | 0 | 0 | 0 | 0 |
| New DRC violations (clearance included) | 0 | 0 | 0 | 0 |
| Valid before / after plane vias | yes / yes | yes / yes | yes / yes | yes / yes |
| Vias added by the router | 155 | 149 | 149 | 155 |
| Vias on SMD pads (routed / plane-via board) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Track length, F.Cu + In2.Cu | 907.0 | 882.5 | 933.1 | 890.6 |
| Divider-top metric, same layer (nets) | 19.97 (/H1_RB 15.42, /CHG_ARM 4.55) | 0.90 (/CHG_ARM) | 8.87 (/H1_RB 7.03, /CHG_ARM 1.84) | 0.00 |
| Logic vias in the divider zone | 1 | 1 | 1 | 1 |
| /GND opens before / after plane vias | 2 / 1 | 2 / 1 | 2 / 1 | 2 / 1 |
| Plane vias added; pieces without a site | 6; 1 | 5; 1 | 4; 2 | 6; 1 |
| VCHGIN_L1 islands after routing | 1 | 1 | 1 | 1 |
| VCHGOUT_L1 islands after routing | 2 | 2 | 2 | 2 |
| New starved thermals | 0 | 0 | 0 | 0 |

`seeds.py compare` against the D-55 probe (same plan, same seeds) gives +4 open connections at every seed and the
verdict "B better". The D-55 board left /N_UV (2), /N_OV and /N_DVDT open at every seed.

The unrouted D-56 board has 0 /GND opens. Therefore the one /GND open after the plane-via step is made by the
routing. The plane-via step added no via in U101.25 at any seed.

The VCHGIN_L1 pour stays one piece of 26.77 mm2 with all seven /VCHGIN F.Cu pads at every seed. VCHGOUT_L1 has 2
pieces at every seed, the same count as the unrouted board: the second piece is 0.55 mm2, has no pad, and lies at
design x 29.10-30.10, y 60.00-61.00. The D-55 board has the same piece, so the D-56 round did not cause it.

## 4. Open items

### 4.1 C102c.2 /GND piece cut by /N_UV (every seed)

The /N_UV track from U101.6 to R102.2 runs south on F.Cu at about x 43.5, y 59.2-61.5, at all four seeds (16 track
points of /N_UV in that window at each seed). It cuts the GND_L1_fill strip that joins C102c.2 to the main fill.
The cut piece is 1.7 mm2 at design (42.9, 59.4). `nosite_why.py` finds no free via cell in it: every cell is blocked
by obstacles on both layers (the In2.Cu VCHGIN_L3_strap lies under the whole piece).

The conflict is topological. VCHGIN copper bounds the piece on -x, +y and -y, so any F.Cu path from U101.6 to R102.2
on the +x side of C102c.2 isolates the pad. In2.Cu offers no other path, because the VCHGIN_L3_strap pad-10 band
covers x 39.15-47.10, y 58.50-62.75. A /GND via in that band needs a strap cut-out at the narrowest strap section
(3.645 mm at x 42.75, 6.6 % margin on the R9.H25 basis).

Candidate changes for the design owner, each to be tested by a 4-seed re-probe:

1. A `gen/route_cr.py` pre-track for /N_UV that passes on the -x side of C102c.2 (between C102c.1 and C102c.2),
   with a matching notch in VIN_L1. C102c.2 then stays on the +x side of the lane, joined to the main fill.
2. A /GND pre-via for C102c.2 inside a VCHGIN_L3_strap cut-out, only if R9.H25 is re-run on the cut strap and
   still passes.
3. A placement change that moves the C102c ground pad to the -x side of the /N_UV lane without a pad inside the
   VCHGIN pour.

### 4.2 GND_L1_star_0 piece at seed 3 only

Seed 3 leaves a 0.5 mm2 GND_L1_star_0 piece at design (20.4, 57.4) without a via site (In2.Cu routed copper, drills
and unflashed layers block it). One seed is not evidence; a move of one In2.Cu track in the GUI clears it.

### 4.3 Divider-top metric spread

The divider-top metric ranges from 0.00 to 19.97 mm between seeds. /H1_RB causes the two high values (15.42 and
7.03 mm). The plain plan has no keep-away for the zone. If the design owner sets a limit, the reserved-corridor
plan of the skill (section 2, step 4) is the test.

### 4.4 VCHGOUT_L1 padless piece

The 0.55 mm2 VCHGOUT_L1 piece at design x 29.10-30.10, y 60.00-61.00 has no pad. It is a pour-shape item of
`gen/route_cr.py` (`VOUT_L1`), independent of routing. Remove it in the pour definition or leave it to island
removal.

## 5. Routability verdict

The D-56 board routes completely: 107 of 107 connections at 4 of 4 seeds, all results valid before and after the
plane-via step, 0 vias on SMD pads, and the VCHGIN_L1 pour in one piece. The board is ready for the step-6
route-race. However, one /GND connection (C102c.2) is open after the plane-via step at every seed. Item 4.1 is a
request to close before a routed result can pass the finish test. Items 4.2 to 4.4 are information.

Probe records (scratch, not committed): `rprobe_d56/W/` in the session scratchpad (plan, capacity report,
`plain/SEEDS.md`, per-seed scores, plane-via reports and images).
