# Charger EVM r8: overnight review (2026-11-11 to 2026-11-12)

This document records the overnight work on the CR routing and the decisions that the operator should review.
`HANDOFF.md` section 7 holds the operator rulings of 2026-11-11; `LAYOUT_DECISIONS.md` is the full design record.

## 1. Decisions to review

| # | Decision | Made by | Basis | Reversal |
|---|---|---|---|---|
| 1 | DNP tier 3 removed from the CR (U117, R160-R163, C127, C124; R137 stays; the F23 pad stays with no net). Commit `5ddc21a`. | design owner | Approved with the tier 1-2 ruling as the next lever (`HANDOFF.md` section 2 before this round); the routing study needed it applied | Revert `5ddc21a` |
| 2 | Comparator analog nets kept out of the U101 loop region as a preference, not a gate. Violations are reported rather than rejected. | design owner | A.8 places the comparators 10.40 mm from the loop band (H.23(f)); no design row states a routing rule | Make it a gate, or drop it |
| 3 | The routing study's via rule is renamed "VR-1" in requests. `LAYOUT_DECISIONS.md` D-20 is the stack-up row, so the old name clashed. | design owner | Terminology | None needed |

## 2. Board state at the start of the study

The base is commit `5ddc21a`, branch `charger-evm-round4`. The CR (`cr/cr.kicad_pcb`) is placed and poured, with no signal routing. The checks give the following results:

- ERC: 0.
- DRC with schematic parity: 200 unconnected items (212 before tier 3), 4 starved thermals and 2 silkscreen items. Three of the starved thermals are U101 thermal-pad vias. The fourth is J1 pad 10 to two VCHGIN_L1 slivers of 0.65 and 0.50 mm². In the rebuilt fill, pad 10 joins the main VCHGIN_L1 island directly; the earlier board had it on a separate 2.3 mm² island.
- Constraint check: 0 FAIL.

The placement images `cr/placement_*.png` show the board before tier 3. They were not regenerated because matplotlib is not installed in the pcbnew venv.

The `main` branch is at `d6bc969`, one commit behind `5ddc21a`. To bring it level, run `git merge --ff-only charger-evm-round4` in the primary checkout.

## 3. Routing study results

Pending: the routing orchestrator session reports here.

## 4. Items for the operator

Pending.
