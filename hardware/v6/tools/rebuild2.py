#!/usr/bin/env python3
"""Recovery step A: strip the 4 escape nets' copper (mine AND freerouting's
partial work), remove the 3 same-net-hole GND vias, re-add the exact channel
stubs, save, and export a DSN that carries all remaining wiring so freerouting
completes only what is missing."""
import os
import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
MM = pcbnew.FromMM
def TOMM(v): return v/1e6
def V(x,y): return pcbnew.VECTOR2I(MM(x),MM(y))

STRIP = {"BTN_RIGHT","BTN_SIDE_FWD","STAT","ENC_B"}
BAD_VIAS = [(111.246625,119.246338),(135.05,125.58033)]   # same-net hole offenders
STUBS = {
    "BTN_RIGHT":     ((154.25,104.50),(153.35,104.50)),
    "ENC_B":         ((154.25,106.00),(153.35,106.00)),
    "BTN_SIDE_FWD":  ((154.25,105.00),(153.35,105.00)),
    "STAT":          ((156.00,107.75),(156.00,108.70)),
}

board = pcbnew.LoadBoard(PCB)
netobj={}
for fp in board.GetFootprints():
    for p in fp.Pads():
        if p.GetNetname(): netobj[p.GetNetname()]=p.GetNet()

rm_t=rm_v=0
for t in list(board.GetTracks()):
    net=t.GetNetname()
    if net in STRIP:
        board.Remove(t)
        if t.GetClass()=="PCB_VIA": rm_v+=1
        else: rm_t+=1
    elif net=="GND" and t.GetClass()=="PCB_VIA":
        p=t.GetPosition()
        for bx,by in BAD_VIAS:
            if abs(TOMM(p.x)-bx)<0.05 and abs(TOMM(p.y)-by)<0.05:
                board.Remove(t); rm_v+=1; break
print(f"stripped {rm_t} tracks, {rm_v} vias")

for net,(ball,tip) in STUBS.items():
    t=pcbnew.PCB_TRACK(board)
    t.SetStart(V(*ball)); t.SetEnd(V(*tip))
    t.SetLayer(pcbnew.F_Cu); t.SetWidth(MM(0.10)); t.SetNet(netobj[net])
    board.Add(t)
print("4 channel stubs re-added")

board.Save(PCB)
# reload after Remove() before any further processing (SWIG lifetime)
board = pcbnew.LoadBoard(PCB)
ok = pcbnew.ExportSpecctraDSN(board, os.path.join(PROJ,"build","hakai_v6b.dsn"))
print("DSN with existing wiring:", ok)
