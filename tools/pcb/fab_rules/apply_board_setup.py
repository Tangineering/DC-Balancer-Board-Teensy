"""Write the OSH Park / PCBWay conservative minimums into a board's own design settings.

The values duplicate the .kicad_dru files in this folder (sources are cited there) and add the
settings that custom rules cannot express: solder-mask expansion, solder-mask web and board
thickness.

Usage (KiCad-Python venv):
    python apply_board_setup.py <board.kicad_pcb>
"""
import sys
import pcbnew

MM = pcbnew.FromMM

board = pcbnew.LoadBoard(sys.argv[1])
ds = board.GetDesignSettings()
ds.m_TrackMinWidth = MM(0.1524)          # 6 mil
ds.m_MinClearance = MM(0.1524)           # 6 mil
ds.m_CopperEdgeClearance = MM(0.381)     # 15 mil
ds.m_MinThroughDrill = MM(0.254)         # 10 mil
ds.m_ViasMinAnnularWidth = MM(0.15)
ds.m_ViasMinSize = MM(0.554)             # 0.254 drill + 2 x 0.15 ring
ds.m_HoleToHoleMin = MM(0.2794)          # 11 mil (via-to-via); the .kicad_dru raises pads to 0.4064
ds.m_HoleClearance = MM(0.254)           # 10 mil (OSH Park 4-layer, internal copper)
ds.m_SolderMaskExpansion = MM(0.0508)    # 2 mil, TODO(verify)
ds.m_SolderMaskMinWidth = MM(0.1016)     # 4 mil web
ds.m_MinSilkTextHeight = MM(0.8)
ds.m_MinSilkTextThickness = MM(0.15)
ds.SetBoardThickness(MM(1.6))
pcbnew.SaveBoard(sys.argv[1], board)  # also writes the design settings into the .kicad_pro
print("design settings written to", sys.argv[1])
