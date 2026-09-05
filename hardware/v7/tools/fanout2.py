#!/usr/bin/env python3
"""Deterministic full QFN fanout on the pristine board, then DSN export.

Every netted, non-GND pad of U4 (aQFN-73) and U2 (VQFN-16) gets a radial
escape stub (0.10 mm) to open field — ring-2 balls pass dead-centre through
the 0.25 mm ring-0 channels (legal per the qfn_escape .kicad_dru rules).
GND ring-2 balls B7/F23 get direct links to the GND exposed pad instead.
Freerouting then only ever connects open-field stub tips.
"""
import os, shutil
import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
PRISTINE = os.path.join(PROJ, "hakai_mouse_v6_unrouted.kicad_pcb")
MM = pcbnew.FromMM
def TOMM(v): return v/1e6
def V(x,y): return pcbnew.VECTOR2I(MM(x),MM(y))

shutil.copyfile(PRISTINE, PCB)
board = pcbnew.LoadBoard(PCB)
netobj={}
for fp in board.GetFootprints():
    for p in fp.Pads():
        if p.GetNetname(): netobj[p.GetNetname()]=p.GetNet()

def add(x1,y1,x2,y2,net,w=0.10):
    t=pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1,y1)); t.SetEnd(V(x2,y2))
    t.SetLayer(pcbnew.F_Cu); t.SetWidth(MM(w)); t.SetNet(netobj[net])
    board.Add(t)

def fanout(ref, ring2_len):
    fp=[f for f in board.GetFootprints() if f.GetReference()==ref][0]
    bb=fp.GetBoundingBox(False,False)
    cx,cy=TOMM(bb.GetCenter().x),TOMM(bb.GetCenter().y)
    # body half: distance of outermost pad ring from centre
    half=max(max(abs(TOMM(p.GetPosition().x)-cx),abs(TOMM(p.GetPosition().y)-cy))
             for p in fp.Pads() if p.GetNumber() not in ("","EP"))
    n=0
    for p in fp.Pads():
        num=p.GetNumber()
        if num in ("","EP"): continue
        net=p.GetNetname()
        if not net or net=="GND" or net.startswith("unconnected"): continue
        x,y=TOMM(p.GetPosition().x),TOMM(p.GetPosition().y)
        dx,dy=x-cx,y-cy
        if abs(dx)>=abs(dy): ux,uy=(1 if dx>0 else -1),0
        else:                ux,uy=0,(1 if dy>0 else -1)
        inset=half-max(abs(dx),abs(dy))
        L=0.55+(ring2_len if inset>0.35 else 0.0)
        add(x,y,round(x+ux*L,2),round(y+uy*L,2),net)
        n+=1
    return n

n4=fanout("U4",0.80)
n2=fanout("U2",0.60)
# GND ring-2 balls -> exposed pad (0.35 mm hop, both GND)
add(155.50,102.25,155.50,102.80,"GND",0.15)   # B7 -> EP
add(159.75,103.50,159.35,103.50,"GND",0.15)   # F23 -> EP
print(f"fanout stubs: U4={n4} U2={n2} + 2 GND->EP links")

board.Save(PCB)
board=pcbnew.LoadBoard(PCB)
print("DSN:", pcbnew.ExportSpecctraDSN(board, os.path.join(PROJ,"build","hakai_v6d.dsn")))
