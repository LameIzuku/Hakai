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

# ---- 1. via nudging (track endpoints follow) ---------------------------------
def nudge_via(net,vx,vy,reach=0.45):
    via=None
    for t in board.GetTracks():
        if t.GetClass()=="PCB_VIA" and t.GetNetname()==net:
            p=t.GetPosition()
            if abs(TOMM(p.x)-vx)<0.03 and abs(TOMM(p.y)-vy)<0.03: via=t; break
    if via is None:
        print(f"  nudge {net}: via at ({vx},{vy}) not found"); return False
    for k,it in enumerate(items):
        if (it and it[0]=="disk" and it[4]==net
                and abs(it[1]-vx)<0.03 and abs(it[2]-vy)<0.03):
            items[k]=None; break
    for k,(hx,hy,hr) in enumerate(holes):
        if abs(hx-vx)<0.03 and abs(hy-vy)<0.03: holes.pop(k); break
    best=None
    steps=[round(-reach+0.05*i,2) for i in range(int(reach*40)+1)]
    for dx in steps:
        for dy in steps:
            nx,ny=round(vx+dx,3),round(vy+dy,3)
            if via_clear(nx,ny,net,margin=0.03) is None:
                sc=abs(dx)+abs(dy)
                if best is None or sc<best[0]: best=(sc,nx,ny)
    if best is None:
        print(f"  nudge {net}: no clear spot near ({vx},{vy})")
        items.append(("disk",vx,vy,VIA_D/2,net)); holes.append((vx,vy,VIA_DRILL/2))
        return False
    _,nx,ny=best
    via.SetPosition(V(nx,ny))
    for t in board.GetTracks():
        if t.GetClass()=="PCB_VIA" or t.GetNetname()!=net: continue
        s,e=t.GetStart(),t.GetEnd()
        if abs(TOMM(s.x)-vx)<0.03 and abs(TOMM(s.y)-vy)<0.03: t.SetStart(V(nx,ny))
        if abs(TOMM(e.x)-vx)<0.03 and abs(TOMM(e.y)-vy)<0.03: t.SetEnd(V(nx,ny))
    items.append(("disk",nx,ny,VIA_D/2,net)); holes.append((nx,ny,VIA_DRILL/2))
    print(f"  nudged {net} via ({vx},{vy}) -> ({nx},{ny})")
    return True

moved=0
for vx,vy in [(120.90,98.30),(147.65,105.30),(148.75,105.15)]:
    if nudge_via("BTN_SIDE_FWD",vx,vy): moved+=1
# free BTN_RIGHT's channel exit: this freerouting via plugs the only lane
nudge_via("BTN_SIDE_BACK",152.9127,104.706,reach=0.6)
print(f"vias nudged: {moved}+cage", flush=True)

# ---- 2. waypoint routes -------------------------------------------------------
def lay_route(net,w,plan):
    """plan = list of ("via",x,y) and ("seg",lay,x1,y1,x2,y2). all-or-nothing."""
    for step in plan:
        if step[0]=="via":
            _,x,y=step
            wr=via_clear(x,y,net)
            if wr is not None:
                print(f"  {net}: via ({x},{y}) blocked by {str(wr[2])[:60]} d={wr[0]:.3f}<{wr[1]:.3f}")
                return False
        else:
            _,lay,x1,y1,x2,y2=step
            wr=seg_clear(lay,x1,y1,x2,y2,w/2,net)
            if wr is not None:
                print(f"  {net}: seg ({x1},{y1})->({x2},{y2}) blocked by {str(wr[2])[:60]} d={wr[0]:.3f}<{wr[1]:.3f}")
                return False
    for step in plan:
        if step[0]=="via": add_via(step[1],step[2],net)
        else: add_seg(step[2],step[3],step[4],step[5],step[1],net,w)
    print(f"  {net}: waypoint route committed ({len(plan)} steps)")
    return True

# BTN_RIGHT: tip (153.35,104.50) -> C29-1 (153.00,70.48)
BR=[("seg",FC,153.35,104.50,152.85,104.50),
    ("via",152.85,104.35),
    ("seg",FC,152.85,104.50,152.85,104.35),
    ("seg",BC,152.85,104.35,152.85,71.20),
    ("via",152.85,71.20),
    ("seg",FC,152.85,71.20,152.85,70.48),
    ("seg",FC,152.85,70.48,153.00,70.48)]
# VBAT_EN: tip (157.00,101.30) -> Q1-1 (139.56,129.05)
VE=[("seg",FC,157.00,101.30,157.00,100.60),
    ("via",157.00,100.60),
    ("seg",BC,157.00,100.60,146.50,100.60),
    ("seg",BC,146.50,100.60,146.50,127.50),
    ("seg",BC,146.50,127.50,139.56,127.50),
    ("seg",BC,139.56,127.50,139.56,128.30),
    ("via",139.56,128.30),
    ("seg",FC,139.56,128.30,139.56,129.05)]
okBR=lay_route("BTN_RIGHT",0.10,BR)
okVE=lay_route("VBAT_EN",0.10,VE)

# fallback lanes if blocked
if not okBR:
    for lane in (152.45,152.05,151.65,154.90):
        BR2=[("seg",FC,153.35,104.50,lane,104.50),
             ("via",lane,104.30),
             ("seg",FC,lane,104.50,lane,104.30),
             ("seg",BC,lane,104.30,lane,71.20),
             ("via",lane,71.20),
             ("seg",FC,lane,71.20,lane,70.48),
             ("seg",FC,lane,70.48,153.00,70.48)]
        if lay_route("BTN_RIGHT",0.10,BR2): okBR=True; break
if not okVE:
    for lane in (147.00,147.50,145.90,148.20):
        VE2=[("seg",FC,157.00,101.30,157.00,100.60),
             ("via",157.00,100.60),
             ("seg",BC,157.00,100.60,lane,100.60),
             ("seg",BC,lane,100.60,lane,127.50),
             ("seg",BC,lane,127.50,139.56,127.50),
             ("seg",BC,139.56,127.50,139.56,128.30),
             ("via",139.56,128.30),
             ("seg",FC,139.56,128.30,139.56,129.05)]
        if lay_route("VBAT_EN",0.10,VE2): okVE=True; break
print(f"spans: BTN_RIGHT={'OK' if okBR else 'FAIL'} VBAT_EN={'OK' if okVE else 'FAIL'}", flush=True)

# ---- 3. fragment junk sweep to fixpoint + crumb cleanup -----------------------
filler=pcbnew.ZONE_FILLER(board)
for z in board.Zones():
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
gnd_pads=[]
for fp in board.GetFootprints():
    for p in fp.Pads():
        if p.GetNetname()=="GND":
            q=p.GetPosition(); gnd_pads.append((TOMM(q.x),TOMM(q.y)))
PROTECT=[(155.50,102.25),(159.75,103.50),(114.70,148.20),(123.30,148.20),(132.90,140.60)]
def keep(x,y):
    return (any(math.hypot(x-a,y-b)<0.8 for a,b in gnd_pads)
            or any(math.hypot(x-a,y-b)<1.0 for a,b in PROTECT))
for sweep in range(5):
    filler.Fill(board.Zones())
    removed=0
    for z in board.Zones():
        for lid in z.GetLayerSet().Seq():
            try: polys=z.GetFilledPolysList(lid)
            except Exception: continue
            areas=sorted(((polys.Outline(i).Area(),i) for i in range(polys.OutlineCount())),reverse=True)
            for _,oi in areas[1:]:
                frag=[]; padtouch=False
                for t in board.GetTracks():
                    if t.GetNetname()!="GND": continue
                    pos=t.GetPosition()
                    if polys.Contains(pos,oi):
                        x,y=TOMM(pos.x),TOMM(pos.y)
                        if keep(x,y): padtouch=True; break
                        frag.append(t)
                if not padtouch:
                    for t in frag: board.Remove(t); removed+=1
    print(f"sweep {sweep}: removed {removed}", flush=True)
    if removed==0: break
    board.Save(PCB)
    board=pcbnew.LoadBoard(PCB)
    filler=pcbnew.ZONE_FILLER(board)
    for z in board.Zones():
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)

filler.Fill(board.Zones())
board.Save(PCB)
out=os.path.join(PROJ,"build","drc_way.json")
subprocess.run([KCLI,"pcb","drc","--format","json","-o",out,PCB],capture_output=True)
d=json.load(open(out,encoding="utf-8"))
from collections import Counter
sev=Counter(v.get("severity") for v in d.get("violations",[]))
typ=Counter(v["type"] for v in d.get("violations",[]))
print(f"WAYPOINT DRC: unconnected={len(d.get('unconnected_items',[]))} "
      f"violations={len(d.get('violations',[]))} severities={dict(sev)}")
for k,n in typ.most_common(): print(f"   {k}: {n}")
for u in d.get("unconnected_items",[])[:15]:
    ds=[i.get("description","")[:42] for i in u.get("items",[])]
    print("  LEFT:"," | ".join(ds))
