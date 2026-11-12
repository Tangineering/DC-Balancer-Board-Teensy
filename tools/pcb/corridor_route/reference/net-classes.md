# Net classification before routing

Classify every routable net before the plan is written. The class sets the group, the priority, the width and
the mode. Write the result as the `groups` of the plan; `capacity.py` check 1 prints the census.

## 1. Classes

| Class | How to recognise it | Plan entry |
|---|---|---|
| Kept power and ground | The net has a pour or a plane (`model_summary.md`, column Pour) | Nothing. The router keeps it. Name the plane net in `plane_net`. |
| Rail without a pour | 12 or more pads, no pour (flagged NO POUR) | Group with `mode: free`, `priority: 1`, a `width` for its current. Write a request for a pour or a rail. |
| Constrained analog | The design document limits the net: Kelvin sense pair, high-impedance node, feedback divider tap, guard or keep-away distance, short loop | Group with `priority: 1`, `mode: local` and a small `margin`, or its own short corridor. Cite the design row in the corridor `note`. Keep it out of shared corridors. |
| Power signal | A net that carries more current than a signal track allows (gate-drive supplies, sense-resistor feeds, LED strings) | Group with `width` from section 2. |
| Flow net | Pads in two or more regions (`flows.py`) | Corridor method: one group per flow. Direction method: default group. |
| Local net | All pads in one region and within a few millimetres | `default` (`mode: local`). On a 2-layer board, see `two-layer.md`. |

High-speed and differential nets (USB, clocks above 10 MHz, controlled impedance) are outside the scope of these
skills. If the board has one, stop and report it.

## 2. Track width for current

Use the IPC-2221 relation, `I = k * dT^0.44 * A^0.725`, with `A` the cross-section in square mils, `k` = 0.048
for an outer layer and 0.024 for an inner layer. For 1 oz copper (35 um) and a 10 K rise:

| Current (A) | Outer layer width (mm) | Inner layer width (mm) |
|---|---|---|
| 0.5 | 0.12 | 0.30 |
| 1.0 | 0.30 | 0.78 |
| 2.0 | 0.78 | 2.0 |
| 3.0 | 1.4 | 3.6 |

A width above about 1 mm is a pour or a strap, not a routed track; write a request. Take the current of each net
from the design document, not from the net name. Do not use a width below the table for the stated current.

## 3. Order of routing

The router orders nets by `priority`, then by the number of nets whose straight-line trees they cross (fewest
first), then by pad count. Use the priority for the classes:

| Priority | Class |
|---|---|
| 1 | Constrained analog; rail without a pour |
| 2 to 3 | Flows through a bottleneck (few gaps, one layer) |
| 5 | Ordinary flow and local nets |
| 7 to 9 | Nets that should yield (a ground net that a pour will connect later) |
