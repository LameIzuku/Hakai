#!/usr/bin/env python3
"""Waypoint finish (visually chosen corridors, strictly checked):
 1. nudge the 3 marginal BTN_SIDE_FWD vias (track endpoints follow);
 2. lay BTN_RIGHT and VBAT_EN as explicit waypoint routes down the empty
    B.Cu corridors seen in the renders — every leg swept-checked before commit;
 3. junk-sweep pour fragments to fixpoint; delete dangling crumbs;
 4. final refill + save + DRC.
"""
import os, math, subprocess, json
import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
MM = pcbnew.FromMM
def TOMM(v): return v/1e6
def V(x,y): return pcbnew.VECTOR2I(MM(x),MM(y))
VIA_D, VIA_DRILL, CLR = 0.45, 0.20, 0.15
FINE_NETS={"STAT","nRESET","DCC","DEC4_6","VBAT_EN","XL1","DEC3","XL2","ANT",
           "BTN_RIGHT","BTN_SIDE_FWD","ENC_B","1V9_A"}
FC,BC=int(pcbnew.F_Cu),int(pcbnew.B_Cu)
def seg_dist(px,py,x1,y1,x2,y2):
    dx,dy=x2-x1,y2-y1
    L2=dx*dx+dy*dy
    if L2==0: return math.hypot(px-x1,py-y1)
    t=max(0,min(1,((px-x1)*dx+(py-y1)*dy)/L2))
    return math.hypot(px-(x1+t*dx),py-(y1+t*dy))
def seg_seg_dist(a1,a2,b1,b2):
    if _inter(a1,a2,b1,b2): return 0.0
    return min(seg_dist(*b1,*a1,*a2),seg_dist(*b2,*a1,*a2),
               seg_dist(*a1,*b1,*b2),seg_dist(*a2,*b1,*b2))
def _ccw(A,B,C): return (C[1]-A[1])*(B[0]-A[0])>(B[1]-A[1])*(C[0]-A[0])
def _inter(A,B,C,D):
    return _ccw(A,C,D)!=_ccw(B,C,D) and _ccw(A,B,C)!=_ccw(A,B,D)

board=pcbnew.LoadBoard(PCB)
netobj={}
items=[]        # ("seg",lay,x1,y1,x2,y2,hw,net) | ("disk",x,y,r,net,is_hole_r)
holes=[]
for t in board.GetTracks():
    net=t.GetNetname()
    if net: netobj[net]=t.GetNet()
    if t.GetClass()=="PCB_VIA":
        p=t.GetPosition()
        items.append(("disk",TOMM(p.x),TOMM(p.y),VIA_D/2,net))
        holes.append((TOMM(p.x),TOMM(p.y),VIA_DRILL/2))
    else:
        s,e=t.GetStart(),t.GetEnd()
        items.append(("seg",int(t.GetLayer()),TOMM(s.x),TOMM(s.y),TOMM(e.x),TOMM(e.y),
                      TOMM(t.GetWidth())/2,net))
for fp in board.GetFootprints():
    for p in fp.Pads():
        net=p.GetNetname() or "#NC"
        if p.GetNetname(): netobj[p.GetNetname()]=p.GetNet()
        pos=p.GetPosition(); sz=p.GetSize()
        x,y=TOMM(pos.x),TOMM(pos.y)
        # axis-aligned box model (rotation folded into the bbox)
        bb=p.GetBoundingBox()
        hx,hy=TOMM(bb.GetWidth())/2,TOMM(bb.GetHeight())/2
        dr=p.GetDrillSize()
        if dr.x>0: holes.append((x,y,max(TOMM(dr.x),TOMM(dr.y))/2))
        lays=[l for l in (FC,BC) if p.IsOnLayer(l)]
        items.append(("box",x,y,hx,hy,net,tuple(lays)))
    for g in fp.GraphicalItems():
        try:
            if not pcbnew.IsCopperLayer(g.GetLayer()): continue
            bb=g.GetBoundingBox()
            items.append(("box",TOMM(bb.GetCenter().x),TOMM(bb.GetCenter().y),
                          TOMM(bb.GetWidth())/2,TOMM(bb.GetHeight())/2,
                          "#ANT",(FC,BC)))
        except Exception: pass

def box_pt_dist(px,py,cx,cy,hx,hy):
    dx=max(abs(px-cx)-hx,0.0); dy=max(abs(py-cy)-hy,0.0)
    return math.hypot(dx,dy)
def box_seg_dist(x1,y1,x2,y2,cx,cy,hx,hy):
    # sample-based min distance segment->box (fine for short axis-aligned legs)
    L=math.hypot(x2-x1,y2-y1)
    n=max(2,int(L/0.05)+1)
    return min(box_pt_dist(x1+(x2-x1)*k/n, y1+(y2-y1)*k/n, cx,cy,hx,hy)
               for k in range(n+1))

courts=[]
for _ref,_half in (("U4",3.9),("U2",2.1)):
    for _fp in board.GetFootprints():
        if _fp.GetReference()==_ref:
            _bb=_fp.GetBoundingBox(False,False)
            courts.append((TOMM(_bb.GetCenter().x)-_half,TOMM(_bb.GetCenter().y)-_half,
                           TOMM(_bb.GetCenter().x)+_half,TOMM(_bb.GetCenter().y)+_half))
def in_court(x,y):
    return any(x0<=x<=x1 and y0<=y<=y1 for x0,y0,x1,y1 in courts)

def req(net,other,x,y):
    if in_court(x,y): return 0.072
    a=0.075 if net in FINE_NETS else CLR
    b=0.075 if other in FINE_NETS else CLR
    return max(a,b)
def seg_clear(lay,x1,y1,x2,y2,hw,net,margin=0.02,skips=()):
    """exact geometric check of a candidate segment vs all board items."""
    worst=None
    mx,my=(x1+x2)/2,(y1+y2)/2
    for it in items:
        if it is None or it in skips: continue
        if it[0]=="seg":
            _,l2,a1,b1,a2,b2,hw2,net2=it
            if l2!=lay or net2==net: continue
            d=seg_seg_dist((x1,y1),(x2,y2),(a1,b1),(a2,b2))-hw-hw2
        elif it[0]=="disk":
            _,x,y,r,net2=it
            if net2==net: continue
            d=seg_dist(x,y,x1,y1,x2,y2)-hw-r
        else:
            _,x,y,hx2,hy2,net2,lays=it
            if net2==net or lay not in lays: continue
            d=box_seg_dist(x1,y1,x2,y2,x,y,hx2,hy2)-hw
        need=req(net,net2,mx,my)+margin
        if d<need and (worst is None or d<worst[0]):
            worst=(d,need,it)
    return worst          # None = clear
def via_clear(x,y,net,margin=0.02):
    worst=None
    for it in items:
        if it is None: continue
        if it[0]=="seg":
            _,l2,a1,b1,a2,b2,hw2,net2=it
            if net2==net: continue
            d=seg_dist(x,y,a1,b1,a2,b2)-VIA_D/2-hw2
        elif it[0]=="disk":
            _,ax,ay,r,net2=it
            if net2==net: continue
            d=math.hypot(x-ax,y-ay)-VIA_D/2-r
        else:
            _,ax,ay,hx2,hy2,net2,lays=it
            if net2==net: continue
            d=box_pt_dist(x,y,ax,ay,hx2,hy2)-VIA_D/2
        need=req(net,net2,x,y)+margin
        if d<need and (worst is None or d<worst[0]): worst=(d,need,it)
    for hx,hy,hr in holes:
        d=math.hypot(x-hx,y-hy)-VIA_DRILL/2-hr
        if d<0.20+margin and (worst is None or d<worst[0]): worst=(d,0.20+margin,"hole")
    return worst

def add_seg(x1,y1,x2,y2,lay,net,w):
    t=pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1,y1)); t.SetEnd(V(x2,y2)); t.SetLayer(lay)
    t.SetWidth(MM(w)); t.SetNet(netobj[net]); board.Add(t)
    items.append(("seg",lay,x1,y1,x2,y2,w/2,net))
def add_via(x,y,net):
    v=pcbnew.PCB_VIA(board)
    v.SetPosition(V(x,y)); v.SetDrill(MM(VIA_DRILL)); v.SetWidth(MM(VIA_D))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu); v.SetNet(netobj[net]); board.Add(v)
    items.append(("disk",x,y,VIA_D/2,net)); holes.append((x,y,VIA_DRILL/2))

def near(a,b,x,y,eps=0.03): return abs(a-x)<eps and abs(b-y)<eps
# ---- shift the two BS-BACK B horizontals down (frees C12 via-in-pad space) --
moves=[(109.10,108.70),(109.55,109.05)]
sh=0
for t in board.GetTracks():
    if t.GetClass()=="PCB_VIA" or t.GetNetname()!="BTN_SIDE_BACK": continue
    if int(t.GetLayer())!=BC: continue
    s,e=t.GetStart(),t.GetEnd()
    sx,sy,ex,ey=TOMM(s.x),TOMM(s.y),TOMM(e.x),TOMM(e.y)
    for oldy,newy in moves:
        if abs(sy-oldy)<0.02 and abs(ey-oldy)<0.02 and abs(sx-ex)>1.0:
            t.SetStart(V(sx,newy)); t.SetEnd(V(ex,newy)); sh+=1
        else:
            if abs(sy-oldy)<0.02 and 146.0<sx<150.2: t.SetStart(V(sx,newy)); sh+=1
            if abs(ey-oldy)<0.02 and 146.0<ex<150.2: t.SetEnd(V(ex,newy)); sh+=1
print(f"horizontal shifts: {sh}", flush=True)

# rebuild geometric model after shifts
items.clear(); holes.clear()
for t in board.GetTracks():
    if t.GetClass()=="PCB_VIA":
        p=t.GetPosition()
        items.append(("disk",TOMM(p.x),TOMM(p.y),VIA_D/2,t.GetNetname()))
        holes.append((TOMM(p.x),TOMM(p.y),VIA_DRILL/2))
    else:
        s,e=t.GetStart(),t.GetEnd()
        items.append(("seg",int(t.GetLayer()),TOMM(s.x),TOMM(s.y),TOMM(e.x),TOMM(e.y),
                      TOMM(t.GetWidth())/2,t.GetNetname()))
for fp in board.GetFootprints():
    for p in fp.Pads():
        pos=p.GetPosition(); bb=p.GetBoundingBox()
        dr=p.GetDrillSize()
        if dr.x>0: holes.append((TOMM(pos.x),TOMM(pos.y),max(TOMM(dr.x),TOMM(dr.y))/2))
        lays=[l for l in (FC,BC) if p.IsOnLayer(l)]
        items.append(("box",TOMM(pos.x),TOMM(pos.y),TOMM(bb.GetWidth())/2,
                      TOMM(bb.GetHeight())/2,p.GetNetname() or "#NC",tuple(lays)))

def try_plans(net,w,plans,waive_own_pad=True):
    for pi,plan in enumerate(plans):
        ok=True
        for step in plan:
            if step[0]=="via": wr=via_clear(step[1],step[2],net,margin=0.01)
            else: wr=seg_clear(step[1],step[2],step[3],step[4],step[5],w/2,net,margin=0.01)
            if wr is not None:
                print(f"  {net} p{pi} {step} blocked: {str(wr[2])[:52]} d={wr[0]:.3f}<{wr[1]:.3f}")
                ok=False; break
        if ok:
            for step in plan:
                if step[0]=="via": add_via(step[1],step[2],net)
                else: add_seg(step[2],step[3],step[4],step[5],step[1],net,w)
            print(f"  {net}: p{pi} committed")
            return True
    return False

# C12-2: via-in-pad + B hop west to the GND via cluster
c12=try_plans("GND",0.15,[
 [("via",148.05,109.55),("seg",BC,148.05,109.55,146.95,109.55),
  ("seg",BC,146.95,109.55,146.95,109.85)],
 [("via",148.05,109.50),("seg",BC,148.05,109.50,146.95,109.50),
  ("seg",BC,146.95,109.50,146.95,109.85)],
])
# C19-2: F lane south to the via cluster
c19=try_plans("GND",0.10,[
 [("seg",FC,151.50,113.60,151.50,115.75)],
 [("seg",FC,151.45,113.60,151.45,115.72)],
 [("seg",FC,151.55,113.60,151.55,115.78)],
])
print(f"C12={c12} C19={c19}", flush=True)
board.Save(PCB)
import subprocess, json
board2=pcbnew.LoadBoard(PCB)
f2=pcbnew.ZONE_FILLER(board2); f2.Fill(board2.Zones())
board2.Save(PCB)
out=os.path.join(PROJ,"build","drc_final.json")
subprocess.run([KCLI,"pcb","drc","--format","json","-o",out,PCB],capture_output=True)
d=json.load(open(out,encoding="utf-8"))
from collections import Counter
sev=Counter(v.get("severity") for v in d.get("violations",[]))
typ=Counter(v["type"] for v in d.get("violations",[]))
print(f"FINAL DRC: unconnected={len(d.get('unconnected_items',[]))} "
      f"violations={len(d.get('violations',[]))} severities={dict(sev)}")
for k,n in typ.most_common(): print(f"   {k}: {n}")
for u in d.get("unconnected_items",[])[:8]:
    ds=[i.get("description","")[:44] for i in u.get("items",[])]
    print("  LEFT:"," | ".join(ds))
