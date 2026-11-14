# Plane-via step

Pieces of the fills of the plane nets (/GND) on the routing layers: 8. Tied by a new via: 4. Without a via site: 0. Below 0.3 mm2 and not tied (slivers, left to the island removal): 1.

Vias kept off the unflashed layers of their own net's through-hole pads: yes.

Stitching: 585 vias at pitch 2.50 mm; 50 grid nodes without a legal site.

## Pieces without a via site

None.

Apply the output to the routed board with `apply_routes.py`, then score the result against the unrouted board. The open connections of the plane nets in `score.md` are the test: 0 is a pass.
