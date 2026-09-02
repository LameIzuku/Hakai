import os
import pcbnew

PCB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "hakai_mouse_final.kicad_pcb")
board = pcbnew.LoadBoard(PCB)
filler = pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
pcbnew.SaveBoard(PCB, board)
print("zones filled:", len(board.Zones()), "-> saved")
