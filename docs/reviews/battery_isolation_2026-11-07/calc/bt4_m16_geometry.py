"""bt4 M16 verification: pad positions of the BQ29200 clamp group from the BRD (Eagle rotations)."""
import math
# element (x, y, rot) from 'Scale Car Board PCB 20260625.brd' lines 3907-4024
# package pads: CAPC1608X85 +/-0.7746 (0.9209 x 0.9702), RESC1005X40 +/-0.5075 (0.5351 x 0.644)
def rot(p, r):
    x, y = p
    return {0: (x, y), 90: (-y, x), 180: (-x, -y), 270: (y, -x)}[r]
def pad(el, local):
    (ex, ey, r) = el
    dx, dy = rot(local, r)
    return (ex + dx, ey + dy)
RB1A = (20.828, 27.94, 90); RB3 = (18.796, 28.448, 0); CBL2 = (18.542, 30.226, 180); CBL1 = (21.082, 30.988, 90)
P = {
 'RB1A.1 VMID': pad(RB1A, (-0.5075, 0)), 'RB1A.2 VC1_CB': pad(RB1A, (0.5075, 0)),
 'RB3.1 VMID': pad(RB3, (-0.5075, 0)), 'RB3.2 VC1': pad(RB3, (0.5075, 0)),
 'CBL2.1 VC1': pad(CBL2, (-0.7746, 0)), 'CBL2.2 GND': pad(CBL2, (0.7746, 0)),
 'CBL1.top': pad(CBL1, (0.7746, 0)),
}
for k, v in P.items(): print(f'{k:16s} ({v[0]:.4f}, {v[1]:.4f})')
d = lambda a, b: math.dist(a, b)
via = (20.066, 29.21)  # GND via, BRD line 4822, drill 0.35
print('CBL2 pad1-pad2 centre      %.3f mm' % d(P['CBL2.1 VC1'], P['CBL2.2 GND']))
print('GND via - RB1A.2 centre    %.3f mm' % d(via, P['RB1A.2 VC1_CB']))
print('RB1A.2 - CBL2.2 centre     %.3f mm' % d(P['RB1A.2 VC1_CB'], P['CBL2.2 GND']))
a, b = P['RB1A.2 VC1_CB'], P['CBL2.2 GND']; x = 19.3166  # VC1 trace vertical x=19.3166, y 28.461..30.226
y = a[1] + (a[0] - x) / (a[0] - b[0]) * (b[1] - a[1])
print('straight D_VCB lead meets x=19.3166 at y=%.3f (VC1 trace spans 28.461-30.226)' % y)
top = P['CBL1.top'][1] + 0.9209 / 2
print('highest group pad edge y=%.3f; gap to body y 34.5 = %.2f mm; to AG105 silk y 32.844 = %.2f mm' % (top, 34.5 - top, 32.844 - top))
