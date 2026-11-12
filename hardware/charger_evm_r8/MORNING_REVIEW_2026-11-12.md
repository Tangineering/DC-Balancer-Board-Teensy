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

## 2. Board state at the start of the study

The base is commit `5ddc21a`, branch `charger-evm-round4`. The CR (`cr/cr.kicad_pcb`) is placed and poured, with no signal routing. The checks give the following results:

- ERC: 0.
- DRC with schematic parity: 200 unconnected items (212 before tier 3), 4 starved thermals and 2 silkscreen items. Three of the starved thermals are U101 thermal-pad vias. The fourth is J1 pad 10 to two VCHGIN_L1 slivers of 0.65 and 0.50 mm². In the rebuilt fill, pad 10 joins the main VCHGIN_L1 island directly; the earlier board had it on a separate 2.3 mm² island.
- Constraint check: 0 FAIL.

The placement images `cr/placement_*.png` show the board before tier 3. They were not regenerated because matplotlib is not installed in the pcbnew venv.

The `main` branch is at `d6bc969`, one commit behind `5ddc21a`. To bring it level, run `git merge --ff-only charger-evm-round4` in the primary checkout.

## 3. Routing study results

### 3.1 Round 1

The reference is the plain plan at four seeds with a 60-iteration limit, under VR-1. It makes 174, 170, 169 and 170
of 199 connections, so 25 to 30 stay open. Nine nets are open at every seed: /BT_OK, /FCC, /FCC_TAP, /H1Q, /J3V3_2,
/N_DVDT, /QUAL, /SCL and /STAT. The reference does not enforce the divider-top rule (decision 4). The orchestrator is
re-running it in two compliant forms.

No tested change showed a gain. The design owner decided the round 1 change requests as follows
(`cr/variants/r1_decisions.json`):

- CR1-03 (R147 enclosed by the VCHGOUT L4 strap; tap grid row gaps 0.34-0.35 mm) was accepted as modified, in two
  variants for round 2 (LAYOUT_DECISIONS.md D-34):
  - Variant A makes the strap outline a bottom keep-out for the packer, which moves 7 parts.
  - Variant B adds the grid courtyard growth to A, which moves 30 parts.
  - Both variants pass ERC, DRC (equal to the base) and the constraint check.
- CR1-02 (R101/R105 moved +y) was rejected. It was refuted at four seeds.
- CR1-07 (/3V3 kept as tracks, decided by the orchestrator), CR1-06 (via size), CR1-01, CR1-04 and CR1-05 were noted.
  These requests change nothing on the board.

Pending: the round 2 results on variants A and B.

## 4. Items for the operator

Pending.
