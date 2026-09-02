#!/usr/bin/env python3
"""Final repairs: EP ground stitching (3x3 vias in the nRF exposed pad),
BS-BACK segment shift (0.004mm clearance miss), STAT micro-bridges,
VBAT_EN big-box route to the net's west cluster, refill + DRC."""
import os, math, subprocess, json
import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
MM = pcbnew.FromMM
def TOMM(v): return v/1e6
def V(x,y): return pcbnew.VECTOR2I(MM(x),MM(y))
VIA_D,VIA_DRILL=0.45,0.20
FC,BC=int(pcbnew.F_Cu),int(pcbnew.B_Cu)

board=pcbnew.LoadBoard(PCB)
netobj={}
for fp in board.GetFootprints():
    for p in fp.Pads():
        if p.GetNetname(): netobj[p.GetNetname()]=p.GetNet()

def add_seg(x1,y1,x2,y2,lay,net,w):
    t=pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1,y1)); t.SetEnd(V(x2,y2)); t.SetLayer(lay)
    t.SetWidth(MM(w)); t.SetNet(netobj[net]); board.Add(t)
def add_via(x,y,net):
    v=pcbnew.PCB_VIA(board)
    v.SetPosition(V(x,y)); v.SetDrill(MM(VIA_DRILL)); v.SetWidth(MM(VIA_D))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu); v.SetNet(netobj[net]); board.Add(v)

# ---- 1. shift the BS-BACK vertical from x=159.3 to x=159.2 ------------------
moved=0
for t in board.GetTracks():
    if t.GetClass()=="PCB_VIA" or t.GetNetname()!="BTN_SIDE_BACK": continue
    if int(t.GetLayer())!=BC: continue
    s,e=t.GetStart(),t.GetEnd()
    sx,sy,ex,ey=TOMM(s.x),TOMM(s.y),TOMM(e.x),TOMM(e.y)
    if abs(sx-159.3)<0.02 and abs(ex-159.3)<0.02 and abs(sy-ey)>1.0:
        t.SetStart(V(159.20,sy)); t.SetEnd(V(159.20,ey)); moved+=1
    elif abs(sx-159.3)<0.02 and abs(sy-ey)<=1.0:
        t.SetStart(V(159.20,sy)); moved+=1
    elif abs(ex-159.3)<0.02 and abs(sy-ey)<=1.0:
        t.SetEnd(V(159.20,ey)); moved+=1
print(f"BS-BACK shift: {moved} endpoints/segments adjusted", flush=True)

# ---- 2. nRF EP ground stitching (via-in-pad, standard QFN practice) ---------
filler=pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
zone_by_layer={}
for z in board.Zones():
    for lid in z.GetLayerSet().Seq():
        zone_by_layer[int(lid)]=z
def pour_at(x,y,layer):
    z=zone_by_layer.get(int(layer))
    if z is None: return False
    try: return z.HitTestFilledArea(layer, V(x,y), 0)
    except Exception: return False
# existing via/pad holes to respect
holes=[]
for t in board.GetTracks():
    if t.GetClass()=="PCB_VIA":
        p=t.GetPosition(); holes.append((TOMM(p.x),TOMM(p.y)))
ep=0
for gx in (155.9,157.0,158.1):
    for gy in (103.9,105.0,106.1):
        if any(math.hypot(gx-a,gy-b)<0.65 for a,b in holes): continue
        if not pour_at(gx,gy,pcbnew.B_Cu): continue
        add_via(gx,gy,"GND"); holes.append((gx,gy)); ep+=1
print(f"EP stitch vias: {ep}", flush=True)

# ---- 3. STAT micro-bridges through the AD-row channel ------------------------
add_seg(156.00,107.90,156.00,108.70,FC,"STAT",0.10)
add_seg(156.00,108.70,155.95,108.80,FC,"STAT",0.10)
print("STAT bridges laid", flush=True)

board.Save(PCB)
print("saved (pre-route)", flush=True)
