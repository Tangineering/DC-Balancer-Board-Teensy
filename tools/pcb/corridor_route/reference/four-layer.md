# Four-layer boards

The usual stack is: L1 signals and power pours, L2 solid ground plane, L3 signals and power straps, L4 signals
and a ground fill. The routing layers are L1, L3 and L4 (`--layers F.Cu,In2.Cu,B.Cu`); the plane layer is not a
routing layer.

## 1. Before routing

- Name the plane net in `plane_net`. Its pads are connected by the project's plane-via step after routing; the
  score counts them separately.
- Read the NO POUR flag in `model_summary.md`. A rail with many pads and no pour was the largest single source
  of conflicts in the dry tests (59 pads, in conflict with 23 nets). Route it first at priority 1 and write a
  request for a pour or an L3 rail.
- Hard pours and straps on L1, L3 and L4 are walls. `capacity.py` counts them. A pad sealed by a pour is a
  request, not a routing task.
- Soft ground fills on L1 and L4 are cut by tracks. Their islands and the plane-net open count rise; both are
  listed for information and are restored by the project's plane-via and stitching step.
- A through-hole pad connects only on the layers where the board flashes it. On an inner layer without a pad the
  hole is an obstacle for every net, the pad's own net included.

## 2. Layer use

- Long flows: L3 (inner). It has no parts, so its capacity is the highest away from through-hole rows and
  straps.
- Local nets: L1 and L4, the side where their parts are.
- Two flows that cross: different layers, or directions per layer (`directions`). The direction of a layer
  follows the flows through the narrowest channel of the board (a neck, a gap row), not the count of long nets.
- Constrained local nets at priority 1 take the inner layer first. Give their groups `layer_cost` 2 on the
  inner layer when the long flows lose there.
- Every change between L1 and L4 passes a via that also blocks L3. In a dense block, via sites are the scarce
  resource, not track space: raise `escape` only where the report shows a missing via site, and keep `costs.via`
  at 10 or above in dense areas.
- A through-hole row is a wall on every layer. Count its gaps per layer; an inner layer with smaller pads has
  wider gaps.

## 3. Bottlenecks to look for first

- A tab or a neck of the outline: all nets between the tab and the body pass the neck. Count them with
  `flows.py` and measure the neck with a path corridor in `capacity.py` before anything else is planned.
- A through-hole header that separates two regions.
- A dense IC block with parts on both sides (no via sites).
- A power strap on the inner signal layer.

If the neck capacity at margin 2 is below the flow, no plan closes the board. Write the request (move parts
across the neck, another exit, finer rules within the fab limit) and route what can be routed.
