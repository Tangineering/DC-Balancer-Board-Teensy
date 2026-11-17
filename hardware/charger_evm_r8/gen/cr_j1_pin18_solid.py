"""REVIEW_2026-11-14 CRL-4 (S3): J1 pin 18 (VCHG, battery side) joined the F.Cu VCHG pour (VCHG_L1, thermal reliefs,
0.6 mm spokes at 45 degrees, 0.3 mm gap) through only two spokes, 1.22 mm of copper in total, because the pour reaches
the pad only on two of its four diagonals. VCHG has no inner-layer copper, so the whole pin-18 current crosses these
spokes on F.Cu. Basis (design document A.8 / H.22): 3.21 A battery-side current shared 60/40 by pins 18 and 19, that is
1.93 A per pin (each pin is rated for 2.0 A, T-A-05); A.8 asks for VCHG copper >= 2.0 mm wide on 1 oz.

IPC-2152 baseline fit (docs/reviews/charger_eval_2026-11-05/round4/calc/r9_calc.py ipc2152_area_mil2, 35 um outer copper
counted as clad only, long-conductor basis): 1.22 mm = 66.2 mil2 carries 2.09 A at a 10 degC rise; at 1.93 A the rise
is 8.3 degC, and at the full 3.21 A (pin 19 open or a poor joint) 27.7 degC. The neck passes the 10 degC basis by a
margin of 8 % in current only, and it does not meet the A.8 2.0 mm width rule. Pin 19 (four spokes, 2.43 mm) meets both.

Change: a board rule in cr/cr.kicad_dru sets a solid zone connection for J1 pad 18 only (a DRC rule, not a pad
override, so the J1 instance stays equal to its library footprint and gen/fplib.py needs no change). All zones of
cr/cr.kicad_pcb are then refilled with the board loaded beside its own cr.kicad_pro and cr.kicad_dru, and the board is
saved. Tracks, vias, pads and footprints are not touched. Idempotent.

Hand-soldering consequence: pin 18 is a TSW post soldered from the top side; with the solid connection the joint heats
the whole F.Cu VCHG pour (no inner-layer VCHG copper and no plane), so it needs more heat than pin 19 or W3, which keep
their thermal reliefs (a higher iron setting or a larger tip, and a longer dwell).

Note for a regeneration: gen/make_board.sh copies tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru over
cr/cr.kicad_dru; this script must then be re-run.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/cr_j1_pin18_solid.py
"""
import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

DRU = "cr/cr.kicad_dru"
RULE = ("\n# REVIEW_2026-11-14 CRL-4 (gen/cr_j1_pin18_solid.py): J1 pin 18 (VCHG, 1.93 A at the A.8 60/40 split) joins the\n"
        "# F.Cu VCHG pour solidly; with the zone thermal reliefs only two 0.6 mm spokes reached it (1.22 mm < A.8 2.0 mm).\n"
        "(rule \"cr_J1_pin18_solid\"\n"
        "  (condition \"A.Type == 'Pad' && A.memberOfFootprint('J1') && A.Pad_Number == '18'\")\n"
        "  (constraint zone_connection solid))\n")

txt = open(DRU, encoding="utf-8", newline="").read()
if '(rule "cr_J1_pin18_solid"' in txt:
    print("%s: rule already present" % DRU)
else:
    eol = "\r\n" if "\r\n" in txt else "\n"
    with open(DRU, "w", encoding="utf-8", newline="") as f:
        f.write(txt.rstrip("\r\n") + eol + RULE.replace("\n", eol))
    print("%s: rule added" % DRU)

PCB = "cr/cr.kicad_pcb"
b = pcbnew.LoadBoard(PCB)
b.BuildConnectivity()
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
b.Save(PCB)
print("zones refilled: %d" % len(list(b.Zones())))
