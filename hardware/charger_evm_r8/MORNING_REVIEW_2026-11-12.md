# Charger EVM r8: overnight review (2026-11-11 to 2026-11-12)

This document records the overnight work on the CR routing and the decisions that the operator should review.
`HANDOFF.md` section 7 holds the operator rulings of 2026-11-11; `LAYOUT_DECISIONS.md` is the full design record.

## 1. Decisions to review

| # | Decision | Made by | Basis | Reversal |
|---|---|---|---|---|
| 1 | DNP tier 3 removed from the CR (U117, R160-R163, C127, C124; R137 stays; the F23 pad stays with no net). Commit `5ddc21a`. | design owner | Approved with the tier 1-2 ruling as the next lever (`HANDOFF.md` section 2 before this round); the routing study needed it applied | Revert `5ddc21a` |
| 2 | Comparator analog nets kept out of the U101 loop region as a preference, not a gate. Violations are reported rather than rejected. | design owner | A.8 places the comparators 10.40 mm from the loop band (H.23(f)); no design row states a routing rule | Make it a gate, or drop it |
| 3 | The routing study's via rule is renamed "VR-1" in requests. `LAYOUT_DECISIONS.md` D-20 is the stack-up row, so the old name clashed. | design owner | Terminology | None needed |
| 4 | Layer scope of the A.8 rule "divider tops R102/R109/R111/R114 at least 2 mm from any logic trace". The rule binds logic-net copper on F.Cu and logic-net vias on any layer within 2.0 mm. Logic tracks on In2.Cu and B.Cu may pass under the four parts. /3V3, /GND and the analog band nets are not "logic". | design owner, on a question from the routing orchestrator | The A.8 row states no layer and no rationale. The round-4 tap-side proposal treats L3 striplines between GND layers as compliant, so GND shielding is the intended mechanism. L2 is solid GND between F.Cu and In2.Cu, and the via ban keeps L2 free of antipads in the zone. | Make the rule bind on all layers. The orchestrator runs both forms, so section 3 states the cost of the all-layer form. |
| 5 | The A.8-fixed pins inside the divider-top zone (J1.7, J1.8, J101.7, J101.11, J101.13, U102.1, U103.1) are exempt, each with its pad and one F.Cu escape. U105.5, U109.1 and U109.3 carry the same exemption on an interim basis (item 4.1). | design owner | A.8 fixes those parts, and the rule says "trace". A placement variant that kept packer-placed logic out of the zone left U111, or U105 and U118, unplaced. | Hand-place U105 and U109, or make the rule bind on pads as well |
| 6 | The VCHGOUT L4 strap keep-out (variant A) is the default CR placement; `cr/cr.kicad_pcb` is rebuilt with it. Grid growth (variant B) is not adopted. | design owner | A fixes a real defect (R147.2 unreachable on an empty board) at +2.8 connections, not separated; B adds 0.2 at the cost of 30 moved parts | `CR_PLACE_VARIANT=BASE0` rebuilds the 5ddc21a placement |

## 2. Board state at the start of the study

The base is commit `5ddc21a`, branch `charger-evm-round4`. The CR (`cr/cr.kicad_pcb`) is placed and poured, with no signal routing. The checks give the following results:

- ERC: 0.
- DRC with schematic parity: 200 unconnected items (212 before tier 3), 4 starved thermals and 2 silkscreen items. Three of the starved thermals are U101 thermal-pad vias. The fourth is J1 pad 10 to two VCHGIN_L1 slivers of 0.65 and 0.50 mm². In the rebuilt fill, pad 10 joins the main VCHGIN_L1 island directly; the earlier board had it on a separate 2.3 mm² island.
- Constraint check: 0 FAIL.

The placement images `cr/placement_*.png` show the board before tier 3. They were not regenerated because matplotlib is not installed in the pcbnew venv.

At the end of the night, `main` is at `d6bc969`. The branch `charger-evm-round4` is six commits ahead (`5ddc21a` to
the commit that holds this review). To bring `main` level, run `git merge --ff-only charger-evm-round4` in the primary
checkout.

## 3. Routing study results

### 3.1 Round 1

The reference is the plain plan at four seeds with a 60-iteration limit, under VR-1. It makes 174, 170, 169 and 170
of 199 connections, so 25 to 30 stay open. Nine nets are open at every seed: /BT_OK, /FCC, /FCC_TAP, /H1Q, /J3V3_2,
/N_DVDT, /QUAL, /SCL and /STAT. The reference does not enforce the divider-top rule (decision 4). The orchestrator is
re-running it in two compliant forms.

No tested change showed a gain. The design owner decided the round 1 change requests as follows
(`archive_r7_outline/cr/variants/r1_decisions.json`):

- CR1-03 (R147 enclosed by the VCHGOUT L4 strap; tap grid row gaps 0.34-0.35 mm) was accepted as modified, in two
  variants for round 2 (LAYOUT_DECISIONS.md D-34):
  - Variant A makes the strap outline a bottom keep-out for the packer, which moves 7 parts.
  - Variant B adds the grid courtyard growth to A, which moves 30 parts.
  - Both variants pass ERC, DRC (equal to the base) and the constraint check.
- CR1-02 (R101/R105 moved +y) was rejected. It was refuted at four seeds.
- CR1-07 (/3V3 kept as tracks, decided by the orchestrator), CR1-06 (via size), CR1-01, CR1-04 and CR1-05 were noted.
  These requests change nothing on the board.

### 3.2 Divider-top rule residual (D-35 as amended)

The residual counts logic F.Cu pieces and logic vias within 2.0 mm of the four divider-top pad hulls. The 10 exempt
pins and their escapes are excluded. The orchestrator corrected an earlier count that had a frame error in its
checker. Table 1 gives the residual by seed (seeds 1 to 4).

Table 1. Divider-top residual by seed.

| Board and plan | Made of 199 | F.Cu pieces | of which second entries of exempt nets | Logic vias |
|---|---|---|---|---|
| Base, plain plan | 174/170/169/170 | 1/1/2/4 | 1/0/2/2 | 8/6/7/14 |
| Base, F.Cu keep zones at 30x | 173/167/161/164 | 1/1/1/1 | 0/0/0/0 | 6/7/9/6 |
| r1_A, keep zones at 30x | (round 2 batch) | 2/1/1/1 | 1/1/0/0 | 6/6/11/9 |
| r1_B, keep zones at 30x | (round 2 batch) | 4/3/2/2 | 0/1/2/0 | 4/6/11/8 |

The F.Cu residual is between 1 and 4 pieces per seed. Logic vias inside the zone (4 to 14 per seed) are the main
residual, and no plan meets the rule. On the base, the keep zones cost 4.5 connections on average. A run at 300x is
testing whether the vias can be moved out.

### 3.3 Round 2

Every round 2 run applies the binding divider-top plan (F.Cu keep zones at 30x), with seeds 1 to 4 and a
60-iteration limit. Table 2 gives the completion of each board. The orchestrator's full record is `ROUND2_RESULTS.md` in
its notes folder; its own review is in `docs/reviews/cr_routing_2026-11-12/` in the main checkout.

Table 2. Connections made of 199, round 2.

| Board | Made, seeds 1-4 | Mean | Verdict |
|---|---|---|---|
| Base, plain plan (round 1 reference) | 174/170/169/170 | 170.8 | reference |
| Base, binding plan | 173/167/161/164 | 166.2 | worse than plain (-4.5) |
| Base, keep zones on all layers | 172/162/162/172 | 167.0 | comparison only |
| r1_A, binding plan | 173/162/170/171 | 169.0 | +2.8 against the base, not separated |
| r1_B, binding plan | 167/167/177/166 | 169.2 | +3.0 against the base, not separated; +0.2 against A |

The all-layer form of the divider-top rule costs no more than the F.Cu form (167.0 against 166.2), so the layer scope
of decision 4 does not change the result. On r1_A, /QUAL, /STAT, /FCC and /FCC_TAP are no longer open at every seed,
and R147.2 is reachable on both variants. No change has a gain verdict, so the routing study stopped after round 2
(route-race stop rule).

The best result is r1_B at seed 3, which is valid with 0 vias on SMD pads:

- 177 of 199 signal connections are made, so 22 stay open.
- After the plane-via step, 27 GND connections stay open. 34 of the 56 GND fill pieces have no via site under VR-1.
- The divider-top residual is 2 F.Cu pieces and 11 logic vias.
- The run adds one new starved thermal, at J1 pad 4 on the L4 GND pour.

The two timing nets keep below y 55.86 against the 66.862 limit on every run. /N_FLT and /CHG_EFUSE_FLT each take two
vias on most runs, against a target of one.

The design owner adopted the strap keep-out of r1_A as the default placement (decision 6). The grid growth of r1_B is
not adopted: it moves 30 parts for +0.2 connections over A.

## 4. Items for the operator

1. **Divider-top rule against the placement (D-35).** The A.8 rule keeps logic copper at least 2 mm from R102, R109,
   R111 and R114. The placement does not meet it, so routing alone cannot meet it either:
   - Seven pins of A.8-fixed parts lie inside the zone (J1.7, J1.8, J101.7, J101.11, J101.13, U102.1, U103.1). The
     design owner exempted these pins, each with its pad and one escape.
   - Three pads of packer-placed parts lie inside the zone: U109.1 /H1, U109.3 /RGN_ON and U105.5 /P5N, at 0.40 to
     0.58 mm. A placement variant that kept them out left one or two logic ICs unplaced, so they carry an interim
     exemption.
   - The question is whether the operator accepts these exemptions. The alternatives are to hand-place U105 and U109
     outside the zone or to change the rule itself.
2. **Layer scope of the same rule** (decision 4): F.Cu plus vias, or all layers. The two forms make 166.2 and 167.0
   connections, so the choice can follow the electrical rationale alone. No routed result meets either form: 2 to 14
   logic vias stay inside the zone, and a 300x cost does not remove them. Meeting the rule needs a router change that
   makes the zone a hard keep-out for logic nets and vias, or hand routing.
3. **How to finish the CR.** The scripted study has stopped. Its best result leaves 22 signal and 27 GND connections
   open. Under VR-1, 34 of the 56 GND fill pieces have no via site, so GND continuity also needs work. The untested
   levers are:
   - an interactive push-and-shove pass in the KiCad GUI, starting from r1_B seed 3 or a re-run on the new base;
   - a router change that adds hard keep-outs for the divider-top zone;
   - a 6-layer stack, or a relaxed via rule (VR-1 is final per the 2026-11-11 ruling).
   Each of these is the operator's call.
