# Two-layer boards

A 2-layer board has one signal layer and one layer that should stay a ground pour. Whether every net connects is
only half of the result: the other half is how much signal copper cuts the pour.

## 1. Measures of success

- Open connections: 0.
- Signal track length on the pour layer: as low as the crossings allow.
- Islands of a trial pour (`score.py --test-pour <ground net>:<pour layer>`): no more than the unrouted board
  gives, plus the islands that the design accepts.

Run the unconstrained baseline first (`default: {"mode": "free"}`). On a small 2-layer board it normally
connects every net; the plan is then judged on the pour measures, not on completion.

## 2. Pattern

1. Name the pour layer (normally `B.Cu`) and the signal layer.
2. Signals: prefer the signal layer by cost, do not forbid the pour layer.
   `"layer_cost": {"B.Cu": 4}` at plan level, and `"costs": {"via": 20}`.
   A plan that forbids the pour layer for all signals fails: one layer is not planar.
3. Ground net without a pour yet. There are two patterns; route both and keep the better score.
   - **Ground free on both layers** at priority 9 with `"layer_cost": {"B.Cu": 1}` for its group. This is the
     default. It completed on every test board.
   - **Ground on the pour layer only**:
     `{"name": "gnd", "nets": ["/AGND"], "mode": "free", "layers": ["B.Cu"], "escape": 1.2, "priority": 9}`.
     Each ground pad on the signal side gets a via inside its escape disc, and the tracks merge into the later
     pour. Use it only when the rules are fine enough that a via fits beside every ground pad; at coarse rules
     it left 17 of 19 ground connections open in the dry test.
   The score does not charge ground vias (vias on the trial-pour net are outside the rank).
4. Read `capacity.py` check 5 and `flows.py` for the crossings. Each crossing needs a bridge on the pour layer.
   Keep bridges short. Two parallel bridges 0.3 to 0.6 mm apart leave a strip of pour between them; `score.md`
   lists every piece of the trial pour with its position, so find the strip and move or merge the bridges.
5. A local net with many crossings may use both layers (`layer_cost` 1 for its group).
6. Supply rails (3V3 and similar): signal layer, `priority: 2`, a width for the current.

## 3. Limits found in the dry tests

- Through-hole header rows: the gap between pads can be too narrow for a track. Pins of the inner row then leave
  only through the channel between the rows or by a via. `capacity.py` check 3 measures this correctly when a
  path corridor is drawn through the channel.
- Forbidding the pour layer for one net moves the crossing to another net. The total crossing demand is set by
  the placement.
- Escape discs exist on every layer, so a `layers` restriction is never strict near a pad.
