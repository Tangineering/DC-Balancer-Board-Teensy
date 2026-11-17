# CR placement re-review, variant B after the D-55 fix round (r9b)

## 1. Scope and method

This document re-reviews the live CR board `cr/cr.kicad_pcb` (variant B of `gen/layout_cr.py`, pour stage, no
signal routing) after the D-55 fix round. It checks each finding of `cr/placement_review_r9.md` (B-1, M-1 to M-4,
m-1 to m-9) against the board, and it searches for issues that the fix round introduced. The review is read-only.
The board, the netlist, the generator and the tool scripts are unchanged by this review.

The measurements come from a scripted pcbnew read of the board (KiCad 9.0, the `tools/pcb/.venv` interpreter). Every
coordinate is in the MB frame (KiCad Y = 100 - y). A distance named "centre to centre" is between pad centres; every
other distance is edge to edge. The D-54 record board `cr/variants_r9/B/cr.kicad_pcb` serves as the reference for
"before" figures.

The **escape check** of this review works as follows. For one pad and one copper layer, the obstacle set is the fill
of every pour of another net (the /GND fills excepted, because /GND is the plane net and the router cuts it) and
every pad of another net, each grown by the Default net-class clearance plus half the track width (0.1524 + 0.0762
mm). The free space is the outline, less a 0.40 mm edge band, less the obstacles. The check reports the area of the
free component that holds the pad and the same-net pads in that component. A component that holds no same-net pad
and has no room for a 0.6 mm via is **sealed**.

Three trial pours were filled on scratch copies of the board to test the recommended fix of finding N-1. The live
board was not edited; its sha256 is `02533a75...7ae7` before and after the review.

Severity uses the three levels of the r9 review (Blocker, Major, Minor).

The verification inputs are:

- the board sha256 `02533a7594358a8bbfb1bbdc684ffab4a2b3fb4337f70289b82ead3b96977ae7`;
- the date-stripped `cr/cr.net` sha256 `da64c37a...f484` and the `gen/netlist.py` sha256 `f78b38f1...abb4`, both
  equal to the D-53 freeze, with `cr/cr.net` unmodified in git;
- `cr/constraint_check.md` (88 pass, 0 FAIL) and `cr/drc_place.rpt` (75 silk over copper, 49 silk overlap, 109
  unconnected).

## 2. Closure of the r9 findings

Table 1 gives the status of each r9 finding on the rebuilt board.

Table 1. r9 findings on the D-55 board.

| Finding | Status | Evidence on the board |
|---|---|---|
| B-1 U101 network outside the pocket | Closed for placement; routability depends on N-1 | R101.1 3.73 mm to pin 10, C101.1 4.59 mm to pin 9, R103.2 4.60 mm and R104.1 2.31 mm to pin 7, R105.1 3.26 mm and R129.1 2.80 mm to pin 13, R106s.1 4.31 mm to pin 14 (all centre to centre, recomputed from the pad positions). Straight-line MST edges crossing the CHG column: 0; the nearest edge is CHG_EFUSE_FLT (R106s.2 to J102.9) at 0.543 mm from the column envelope. R104 and R129 are listed D-20 exemptions; R103 and C129 are inside the window. |
| M-1 paste on the via drills | Closed (coverage residual, N-6) | Four 0.50 x 0.50 mm apertures at (41.15 / 42.25, 63.10 / 64.20). Smallest aperture-to-drill gap 0.274 mm (diagonal). Coverage 13.7 % of the 2.7 x 2.7 mm pad. |
| M-2 pre-vias on the C102b pad | Closed | Vias at (39.45, 51.80) and (40.65, 51.40) plus (39.45, 55.00). Smallest annulus-to-pad copper gap 0.140 mm at (40.65, 51.40), 0.09 mm to the pad plus its 0.05 mm mask expansion. Six VCHGIN vias within 3 mm of C102b pad 1. The C102c end keeps two vias, as D-21 records. |
| M-3 J1.10 on an L1 island | Closed as stated, but the fix causes N-1 and N-2 | `VCHGIN_L1` fills as one piece (41.16 mm2) and reaches J1.10 on its E, W and N sides. The same extension seals four signal pads (N-1) and isolates the C102c GND pad (N-2). |
| M-4 rule file and net class | Closed (process residual, N-8) | Board minima 0.127 / 0.127 mm, annular ring 0.1016 mm, via 0.4572 mm, hole to hole 0.127 mm; Default net class 0.1524 / 0.1524 mm, via 0.6 / 0.3 mm. `cr/cr.kicad_dru` is identical to `tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru` and to `cr/variants_r9/B/cr.kicad_dru`. `gen/make_board.sh` copies the new file. |
| m-1 W1/W2 | Closed | W2 at (27.200, 61.200); pad gap 0.807 mm; no courtyard overlap. |
| m-2 R103/R104 D-20 rows | Closed | Listed-exemption rows present; R103 inside the window, R104 listed. |
| m-3 W3 at R110 | Closed | All six dividers +0.70 mm in x; W3 pad to R110.1 1.47 mm. |
| m-4 R177, R107 | Closed | R177 at (43.584, 40.100), R107 at (42.634, 37.750), west of the column; J3V3_2 and 3V3 do not cross it. |
| m-5 C102b/J101 | Closed | C102b at y 53.19; DRC reports no courtyard overlap. |
| m-6 B.Cu pad 25 | Closed | U101 has no SMD pad on B.Cu; the nine thermal-via pads have a solid zone connection; DRC reports no starved thermal. |
| m-7 silkscreen | Open in part | Silk to edge 0. The 75 silk-over-copper and 49 silk-overlap items remain, all reference fields. `gen/silk_fix.py` runs but does not touch reference fields. |
| m-8 divider-top nets | Open (data only) | `route_cr.GUIDE_CORRIDORS` exists; no script reads it. The route-race decides the A.8 2 mm rule. |
| m-9 plane via in U101.25 | Closed in the tool, not exercised | The probe found no plane via in U101.25 with or without `--allow-via-in-pad`. The thermal-via pads tie the exposed-pad fill, so the keep-out is never tested on this board. A related router defect remains (N-5). |

## 3. New findings

### 3.1 Blocker

**N-1. The M-3 `VCHGIN_L1` extension seals U101 pins 6, 7 and 9 and R102 pad 2 on F.Cu.** The extension adds
`box(42.35, 57.95, 44.85, 62.10)` and the pad-10 ring `box(43.90, 60.55, 48.20, 63.60)` to `route_cr.VIN_L1`. The
filled pour surrounds the south and east faces of the U101 +x pin row and the R102 N_UV pad. On In2.Cu the
`VCHGIN_L3_strap` lies under the same area, so no via can be placed next to these pads either. Table 2 gives the
escape check on the D-55 board and on the D-54 board.

Table 2. F.Cu escape check of the U101 network pads (area of the free component that holds the pad).

| Pad | Net | D-55 board | D-54 board |
|---|---|---|---|
| U101.6 | /N_UV | 0.03 mm2, sealed | open; reaches R102.2 and R103.1 |
| R102.2 | /N_UV | 0.97 mm2 (pad included), sealed | open |
| U101.7 | /N_OV | 0.14 mm2, sealed | open; reaches R103.2 and R104.1 |
| U101.9 | /N_DVDT | 0.20 mm2, sealed | open; reaches C101.1 |
| U101.10, .13, .14 | /N_ILIM, /N_IMON, /N_FLT | open | open |

This result agrees with the D-55 routing probe: 103 of 107 connections close at all four seeds, and the four open
connections are /N_UV x 2, /N_OV and /N_DVDT. The probe run with a soft `VCHGIN_L1` closes 107 of 107, which shows
that the D-55 placement itself is routable. The r9 review recommended the other M-3 option (L3 strap as the only
pad-10 path), which matches the D-21 statement that N_UV must cross the L1 corridor.

Recommended fix (generator change in `gen/route_cr.py`, no netlist change), tested as trial 4 on a scratch copy:

1. Replace `VIN_L1` by the D-54 main body without any copper at pad 10:
   `box(36.95, 57.20, 42.35, 61.50)`, `box(40.15, 61.50, 42.65, 62.55)`, `box(42.35, 60.60, 43.10, 61.55)` and
   `box(42.35, 56.55, 44.45, 57.95)`. The third box joins U101 pin 5 (VCHGIN) to the main pour; without it, the
   pin-5 fill is an island (trial 1, one extra unconnected item).
2. Feed J1.10 through `VCHGIN_L3_strap` and its own plated barrel only. Widen the strap toward -y: replace
   `box(39.15, 60.15, 47.10, 62.75)` in `VIN_L3` by `box(39.15, 59.55, 47.10, 62.75)`. The narrowest strap section,
   at the U101 thermal-via column (x 42.80), then grows from 1.995 mm to 2.596 mm.
3. Close the IPC-2152 inner-layer check of D-29 for 2.41 A in the 0.5 oz strap at the 2.596 mm neck.
   TODO(verify: IPC-2152 internal-conductor chart, 0.5 oz). A comparison figure from the IPC-2221 external curve at
   a 10 degC rise is about 2.0 mm; it is not the IPC-2152 value.
4. Record the change in D-55 (or a D-56) with the M-3 ring marked as superseded, and re-run the 4-seed probe.

Trial 4 also includes the N-3 fix. Its results are as follows:

- Every pad of Table 2 is open on F.Cu and reaches its same-net pads.
- `VCHGIN_L1` fills as one piece (26.77 mm2) and holds U101 pins 1, 2 and 5.
- The C102c.2 GND island is gone.
- The DRC shows no new violation type and no clearance item.
- The unconnected count falls from 109 to 107; the four removed items are /GND fill pieces.

### 3.2 Major

**N-2. The M-3 extension isolates the C102c ground pad.** C102c.2 (the input capacitor next to U101 IN, at
(42.575, 60.270)) now sits in a 0.80 mm2 `GND_L1_fill` island that is enclosed by `VCHGIN_L1`. On the D-54 board
C102c.2 joined the main L1 ground fill. On In2.Cu the `VCHGIN_L3_strap` lies under the pad, so the plane-via step
finds no site (D-55 probe, `nosite_why.py`). This island is the extra item in the unconnected count (108 to 109).
Without a ground connection, C102c does not decouple the U101 input.
Fix: the N-1 fix removes the enclosure; in trial 4, C102c.2 joins the main ground fill again. No extra via is needed.

**N-3. The C103 ground pad has no ground connection (present on the D-54 board as well; not in the r9 review).**
C103.2 (the output capacitor, at (38.080, 63.930)) sits in a 1.38 mm2 `GND_L1_fill` island inside `VCHGOUT_L1`. The
plane-via step finds no site, so C103.2 stays open after routing at every probe seed.
Fix: notch `VOUT_L1` with `box(37.40, 62.60, 38.80, 63.40)` and add a /GND pre-via in `route_cr.PRE_VIAS` at
(38.08, 62.90) (and in `layout_cr.PRE_VIA_SITES`). On In2.Cu the via centre is 1.18 mm from the `VCHGOUT_L3_strap`
edge (x 36.90) and clear of `VIN_L3` (x >= 39.15). Trial 4 used (38.08, 62.98): the island grows to 4.93 mm2 and is tied to
the plane, the DRC is clean, and the annulus clears the C103.2 pad copper by 0.150 mm (0.10 mm to the pad plus mask).
The lower position (38.08, 62.90) adds 0.08 mm to that margin. The notch narrows the VCHGOUT L1 pour from 3.94 mm to
about 3.2 mm over 1.4 mm of length; D-22 keeps the L3 strap in parallel.

### 3.3 Minor

**N-4. The slot order of the U101 network forces F.Cu crossings between its own nets.** Pins 7, 9, 10, 13 and 14 lie
in counter-clockwise order around U101 as N_OV, N_DVDT, N_ILIM, N_IMON, N_FLT. The slots, in the same direction, carry
N_OV (R104), N_UV (R103), N_IMON (R129), N_FLT (R106s), N_ILIM (R101), N_DVDT (C101) and N_IMON (R105). Every pad
of the outer ring leads outward to another net, so a single-layer route between U101 and the ring needs one
crossing for each pair whose order differs. The crossings are as follows:

- N_DVDT with N_ILIM (R101 and C101 in reverse order);
- N_IMON (to R129) and N_FLT with N_DVDT and N_ILIM;
- N_UV (pin 6 to R103.1, row 2) with N_OV (pin 7 to R104.1, row 1).

Each crossing costs two In2.Cu vias on a high-impedance programming node within 5 mm of U101. Confidence is high
for the order argument. The route-race measures the actual via count. The two fixes below cost nothing against
A.8 and remove two of the crossing pairs:

- Exchange the R101 and C101 slots in `U101_NET_TARGET` (C101 at (43.60, 68.45), R101 at (42.00, 68.45)). The
  distances become C101.1 to pin 9 4.28 mm and R101.1 to pin 10 4.09 mm.
- Exchange the R103 and R104 rows (R103 at (45.95, 64.20), R104 at (45.95, 65.80)). The distances become R103.2 to
  pin 7 3.58 mm and R104.1 to pin 7 3.69 mm. R104 then lies inside the D-20 window, and its listed exemption retires.

The N_IMON/N_FLT pair remains. It is removed only if R129 and R106s move to the north strip and C101 moves to pocket
row 3. The straight-line CHG-column row then counts their J102 lines as crossings, although a route north and east of
the pocket does not cross the column. This larger change is a route-race test item, not a pre-race fix.

**N-5. Router defect: `core.py` exempts the U101 exposed pad from the SMD via ban.** In
`tools/pcb/corridor_route/core.py` `_build_obstacles()`, the set `drilled` holds (ref, number) for every hole. The nine
U101 thermal vias are holes numbered "25", so the exposed SMD pad U101.25 counts as drilled and never enters
`smd_ban`. The code confirms the probe's diagnosis. On this board the defect is masked, because the plane-via step
now has its own SMD keep-out and the thermal-via pads tie the exposed-pad fill.
Fix: decide the ban from the pad item itself (an SMD pad without its own drill is banned), not from (ref, number);
add a test that asserts no legal via cell inside U101.25 plus mask plus via radius. In addition, the new
`plane_vias.py` keep-out ignores the plan's `via_in_pad` list; make it honour that list for consistency with the
router.

**N-6. The exposed-pad paste coverage is 13.7 %.** This figure is well below the coverage that exposed-pad
assembly guides usually ask for. TODO(verify: SLVSE94G section 11, TI SLUA271, stencil vendor) the target. The
check row passes on "gap > 0" only.
Fix: with the same 3 x 3 via grid, 0.70 x 0.70 mm apertures at the same four centres keep 0.133 mm from each drill
(diagonal) and give 26.9 % coverage. Add the coverage target to the check row once it is known.

**N-7. No check row detects a sealed pad.** The constraint check passed with 0 FAIL while four pads were sealed. The
column-crossing row is a straight-line proxy and cannot see pours.
Fix: add an escape row to `gen/check_constraints.py` for the U101 network pads (U101.6, .7, .9, .10, .13, .14,
R102.2) and the U101 ground pads of C102c and C103. Use the method of section 1: hard non-GND pours and other-net
pads, grown by clearance plus half the track width, on F.Cu. Each pad must reach a same-net pad or a via site.

**N-8. Process items.** The items are as follows:

- `tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru` is untracked. A checkout without it breaks
  `gen/make_board.sh cr`. Commit it with the D-55 round.
- The variant-A record in `cr/variants_r9/A/` predates D-55. Variant A shares the U101-network phase, so a variant
  comparison is valid only after a rebuild.
- The 124 reference-field silk items (m-7) need a decision before the fab package (D-12a keeps references on the
  silkscreen).

## 4. Items checked with no finding

- **Netlist:** `cr/cr.net` is unmodified in git; the date-stripped sha256 and the `gen/netlist.py` sha256 equal the
  D-53 freeze. The U101 footprint keeps pads 1-24 and pad 25 (one F.Cu SMD pad, nine plated thermal vias) on the same
  nets; J1 pads 7-11 keep their nets.
- **Pocket parts against J1.10:** the R104 courtyard bottom (y 63.48) is 0.59 mm above the J1.10 pad top (y 62.894).
- **C129:** inside the D-20 window, beside R129 pad 2 (CHG_IIN at 46.759 / 48.259).
- **North strip:** R101, C101 and R105 courtyards start at y 66.98, above the `VCHGOUT_L1` pour top (y 66.64).
- **New VCHGIN vias near J101:** (40.65, 51.40) is 0.407 mm from J101.2 (J3V3_2) and (39.45, 51.80) is 0.490 mm from
  J101.1 (J3V3_1). The D-54 vias were 0.376 and 0.424 mm from the same pads, so the fix does not reduce the spacing.
- **DRC:** no courtyard, clearance, starved-thermal or silk-to-edge item; 0 parity issues.

## 5. Readiness for the route-race (step 6)

The board is not ready for the full route-race. N-1 leaves four connections open at every probe seed, and no plan
or grid change can close them. Apply the N-1 and N-3 fixes in `gen/route_cr.py` (and `gen/layout_cr.py` for the
pre-via site), rebuild the pour stage, and re-run the 4-seed probe. The expected result from trial 4 is 0 sealed
pads and 107 unconnected items before routing. N-4 and N-7 are inexpensive and are best applied in the same rebuild.
N-5 and N-6 do not block step 6.
