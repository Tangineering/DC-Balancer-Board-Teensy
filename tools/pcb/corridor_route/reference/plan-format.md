# Plan file format (`plan.json`)

One plan format serves every method. A method uses the parts it needs.

```json
{
  "frame": {"y_flip_offset": 100.0},
  "rules": {"track": 0.127, "clear": 0.127, "via": 0.6, "drill": 0.3},
  "keep_nets": ["/GND"],
  "plane_net": "/GND",
  "soft_pours": ["GND_L4_fill"],
  "costs": {"via": 10, "pour": 30, "reserve": 6, "direction": 3},
  "layer_cost": {"B.Cu": 1.5},
  "directions": {"F.Cu": "h", "In2.Cu": "v", "B.Cu": "any"},
  "regions": [{"name": "TABX", "box": [48.7, 40, 58, 66]}, {"name": "LOGIC", "polygon": [[18, 67], [37, 67], [37, 76], [18, 76]]}],
  "corridors": [
    {"id": "TAPS_L3", "layer": "In2.Cu", "path": [[52, 62], [44, 50], [30, 50]], "width": 3.0, "reserve": true,
     "note": "tab X taps to the interior through the header wall, gap 3"},
    {"id": "LOGIC_FB", "layers": ["F.Cu", "B.Cu"], "polygon": [[18, 67], [37, 67], [37, 76], [18, 76]]}
  ],
  "groups": [
    {"name": "kelvin", "nets": ["/N_CSP", "/N_CSN"], "mode": "local", "margin": 1.0, "priority": 1},
    {"name": "rail3v3", "nets": ["/3V3"], "mode": "free", "priority": 1, "width": 0.25},
    {"name": "taps", "nets": ["/H1_RB", "/H2C_RB"], "route": ["TAPS_L3", ["GAP3_L3", "GAP4_L3"]], "escape": 2.5, "priority": 2},
    {"name": "agnd", "nets": ["/AGND"], "mode": "free", "layers": ["B.Cu"], "escape": 1.2, "priority": 9}
  ],
  "default": {"mode": "local", "margin": 2.5, "escape": 1.5, "priority": 5}
}
```

## Top level

| Key | Meaning |
|---|---|
| `frame.y_flip_offset` | The plan uses design coordinates with y up; KiCad y = offset - y. Omit it to plan in the KiCad frame. |
| `rules` | `track`, `clear`, `via`, `drill` in mm. Default: the board minimums. Optional `res` (grid): the default is half the fab pitch `(track + clear) / 2`, or a quarter of it when half is above 0.13 mm; both keep the exact fab pitch. Set `res` only when `capacity.py` check 1 prints a GRID message, to the value it gives. Optional `thermal_keepout` (default 0.35 mm): width of the cost ring around a through-hole pad of a poured net (`costs.thermal`, default 8). |
| `keep_nets` | Nets that are not routed. Every net with a pour is kept automatically. |
| `plane_net` | The net (or list of nets) that a plane layer connects. It is kept; the project's plane-via step connects it. |
| `route_nets` | Nets with a pour that are routed anyway. |
| `soft_pours` / `hard_pours` | Zone names or net names. A hard pour of another net is an obstacle with the zone's clearance. A soft pour only costs (`costs.pour`); a track may cut it and the refill pulls the pour back. Default: a low-priority fill is soft, every other pour is hard. |
| `costs.via` | Cost of one via in cell steps (default 10). Raise it to keep nets on their layer. |
| `costs.reserve` | Cost multiplier inside a reserved corridor for nets that are not assigned to it (default 6). |
| `costs.direction` | Cost multiplier of a step against the preferred direction of a layer (default 3). |
| `layer_cost` | Cost multiplier of a layer for every net. A group can override it. |
| `directions` | Preferred direction of each layer: `h` (along x), `v` (along y) or `any`. A group can override it. |
| `regions` | Named areas for `flows.py` and the images. They do not constrain the router. |

## Corridors

- A group in mode `corridor` may use only the area of its corridors plus the escape discs of its pads. A path
  corridor that covers only a bottleneck leaves the rest of the way unreachable. Either let the corridors of
  the `route` list overlap from pad to pad, or add one region corridor that covers the rest of the board to the
  same `route` list: `{"id": "BODY", "layers": ["F.Cu", "In2.Cu", "B.Cu"], "polygon": [...]}` with
  `"route": ["NECK", "BODY"]`.
- Two corridors join only where they overlap. Corridors that end 0.5 mm apart are not connected.
- A **path corridor** has `path` (polyline) and `width`, on one `layer` or a list `layers`. `capacity.py` checks
  its capacity at every station except the last 0.5 mm of each end. Do not put a path vertex on a concave
  corner of the outline; the narrowest station then sits on the corner.
- A **region corridor** has `polygon`. It gets no capacity check; checks 5 and 6 of `capacity.py` cover it.
- `reserve: true` makes the corridor expensive for nets that are not assigned to it. Without it, other nets route
  through the corridor freely.
- Two path corridors that run parallel (within 30 degrees) and overlap on a shared layer are one physical
  channel. `capacity.py` adds their demand. Corridors that cross are not added.
- Every net of a group counts in every corridor of the group's `route` list (1/k for an alternative). A net that
  uses only one corridor of a chain needs its own group.

## Groups

| Key | Meaning |
|---|---|
| `nets` | The nets of the group. Every net is in at most one group; all others take `default`. |
| `mode` | `corridor` (implied by `route`), `local` (pad bounding box plus `margin`), or `free` (whole board). |
| `route` | Corridors that the nets may use. An inner list is a set of alternatives: each net uses one of them, and each alternative carries 1/k of the demand. |
| `escape` | Radius of the disc around each pad that the net may also use, on every layer (mm). The disc must contain a via site when the pad and the corridor are on different layers. |
| `margin` | Margin of the `local` box (mm). |
| `layers` | Restricts a `local` or `free` group to these layers (the escape discs stay on every layer). |
| `priority` | Lower routes first and is removed last. 1 = constrained nets and large rails; 5 = ordinary; 9 = nets that should yield. |
| `width` | Track width of the group (mm), at least `rules.track`. |
| `layer_cost`, `directions`, `via_cost` | Group overrides of the plan-level values. |
