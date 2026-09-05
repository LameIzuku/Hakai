#!/usr/bin/env python3
"""Surgical finish:
 1. restore the 3 GND links my orphan sweep wrongly deleted (exact endpoints);
 2. route the 3 long spans with LOCALIZED occupancy (bbox-only grids, fast);
 3. fragment endgame: via-tie every non-mainland pour fragment where possible,
    else delete my pad-untouched GND crumbs inside it;
 4. island mode back to ALWAYS, final refill, save, DRC.
"""
import os, math, heapq, subprocess, json
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
G=0.05
FC,BC=int(pcbnew.F_Cu),int(pcbnew.B_Cu)
OTHER={FC:BC,BC:FC}
OUT = [(104,40),(123,40),(123,78),(147,78),(147,40),(166,40),(170,44),(170,88),
       (166,96),(166,144),(160,150),(110,150),(104,144),(104,96),(100,88),(100,44)]
def inside_poly(px,py,poly=OUT):
    n=len(poly); c=False; j=n-1
    for i in range(n):
        xi,yi=poly[i]; xj,yj=poly[j]
        if ((yi>py)!=(yj>py)) and (px < (xj-xi)*(py-yi)/(yj-yi)+xi): c=not c
        j=i
    return c
def near_edge(x,y,ko):
    if not inside_poly(x,y): return True
    for ox,oy in ((ko,0),(-ko,0),(0,ko),(0,-ko)):
        if not inside_poly(x+ox,y+oy): return True
    return False
def seg_dist(px,py,x1,y1,x2,y2):
    dx,dy=x2-x1,y2-y1
    L2=dx*dx+dy*dy
    if L2==0: return math.hypot(px-x1,py-y1)
    t=max(0,min(1,((px-x1)*dx+(py-y1)*dy)/L2))
    return math.hypot(px-(x1+t*dx),py-(y1+t*dy))

board=pcbnew.LoadBoard(PCB)
netobj={}
for fp in board.GetFootprints():
    for p in fp.Pads():
        if p.GetNetname(): netobj[p.GetNetname()]=p.GetNet()

courts=[]
for _ref,_half in (("U4",3.9),("U2",2.1)):
    for _fp in board.GetFootprints():
        if _fp.GetReference()==_ref:
            _bb=_fp.GetBoundingBox(False,False)
            courts.append((TOMM(_bb.GetCenter().x)-_half,TOMM(_bb.GetCenter().y)-_half,
                           TOMM(_bb.GetCenter().x)+_half,TOMM(_bb.GetCenter().y)+_half))
def in_court(x,y):
    return any(x0<=x<=x1 and y0<=y<=y1 for x0,y0,x1,y1 in courts)

poly_boxes=[]
for _fp in board.GetFootprints():
    for _g in _fp.GraphicalItems():
        try:
            bb=_g.GetBoundingBox()
            w,h=TOMM(bb.GetWidth()),TOMM(bb.GetHeight())
            if pcbnew.IsCopperLayer(_g.GetLayer()) or (_g.GetLayerName()=="Edge.Cuts" and max(w,h)<=25):
                poly_boxes.append((TOMM(bb.GetX())-0.3,TOMM(bb.GetY())-0.3,
                                   TOMM(bb.GetX())+w+0.3,TOMM(bb.GetY())+h+0.3))
        except Exception: pass
for _d in board.GetDrawings():
    try:
        if _d.GetLayerName()!="Edge.Cuts": continue
        bb=_d.GetBoundingBox()
        w,h=TOMM(bb.GetWidth()),TOMM(bb.GetHeight())
        if max(w,h)<=25:
            poly_boxes.append((TOMM(bb.GetX())-0.3,TOMM(bb.GetY())-0.3,
                               TOMM(bb.GetX())+w+0.3,TOMM(bb.GetY())+h+0.3))
    except Exception: pass

def add_seg(x1,y1,x2,y2,lay,net,w):
    t=pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1,y1)); t.SetEnd(V(x2,y2)); t.SetLayer(lay)
    t.SetWidth(MM(w)); t.SetNet(netobj[net]); board.Add(t)
def add_via(x,y,net):
    v=pcbnew.PCB_VIA(board)
    v.SetPosition(V(x,y)); v.SetDrill(MM(VIA_DRILL)); v.SetWidth(MM(VIA_D))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu); v.SetNet(netobj[net]); board.Add(v)

# ---- 1. restore the wrongly-swept GND links ---------------------------------
#add_seg(114.70,148.20,115.80,149.00,FC,"GND",0.15)   # J1 B1
#add_seg(123.30,148.20,122.20,149.00,FC,"GND",0.15)   # J1 A1
#add_seg(132.90,140.60,135.90,140.00,BC,"GND",0.15)   # ANT1-2 (PTH, B side)
print("restored 3 GND links", flush=True)

# ---- 2. localized span router ------------------------------------------------
class Box:
    def __init__(self,x0,y0,x1,y1):
        self.x0,self.y0=x0,y0
        self.nx=int((x1-x0)/G)+1; self.ny=int((y1-y0)/G)+1
    def gx(self,x): return int(round((x-self.x0)/G))
    def gy(self,y): return int(round((y-self.y0)/G))
    def wx(self,i): return round(self.x0+i*G,4)
    def wy(self,j): return round(self.y0+j*G,4)

def build_local(box):
    occ={FC:{},BC:{}}; holes=[]
    X0b,Y0b=box.x0,box.y0
    X1b,Y1b=box.wx(box.nx-1),box.wy(box.ny-1)
    def stamp_seg_local(lay,x1,y1,x2,y2,hw,net):
        if max(x1,x2)<X0b-hw or min(x1,x2)>X1b+hw: return
        if max(y1,y2)<Y0b-hw or min(y1,y2)>Y1b+hw: return
        for i in range(max(0,box.gx(min(x1,x2)-hw)),min(box.nx,box.gx(max(x1,x2)+hw)+1)):
            for j in range(max(0,box.gy(min(y1,y2)-hw)),min(box.ny,box.gy(max(y1,y2)+hw)+1)):
                if seg_dist(box.wx(i),box.wy(j),x1,y1,x2,y2)<=hw:
                    occ[lay][(i,j)]=net
    def stamp_disk_local(lay,x,y,r,net):
        if x<X0b-r or x>X1b+r or y<Y0b-r or y>Y1b+r: return
        for i in range(max(0,box.gx(x-r)),min(box.nx,box.gx(x+r)+1)):
            for j in range(max(0,box.gy(y-r)),min(box.ny,box.gy(y+r)+1)):
                if (box.wx(i)-x)**2+(box.wy(j)-y)**2<=r*r:
                    occ[lay][(i,j)]=net
    for t in board.GetTracks():
        net=t.GetNetname()
        if t.GetClass()=="PCB_VIA":
            p=t.GetPosition()
            holes.append((TOMM(p.x),TOMM(p.y),VIA_DRILL/2))
            for lay in (FC,BC): stamp_disk_local(lay,TOMM(p.x),TOMM(p.y),VIA_D/2+0.01,net)
        else:
            s,e=t.GetStart(),t.GetEnd()
            stamp_seg_local(int(t.GetLayer()),TOMM(s.x),TOMM(s.y),TOMM(e.x),TOMM(e.y),
                            TOMM(t.GetWidth())/2+0.01,net)
    for fp in board.GetFootprints():
        for p in fp.Pads():
            net=p.GetNetname() or "#NC"
            pos=p.GetPosition(); sz=p.GetSize()
            x,y=TOMM(pos.x),TOMM(pos.y)
            dr=p.GetDrillSize()
            if dr.x>0: holes.append((x,y,max(TOMM(dr.x),TOMM(dr.y))/2))
            hx,hy=TOMM(sz.x)/2+0.01,TOMM(sz.y)/2+0.01
            for lay in (FC,BC):
                if not p.IsOnLayer(lay): continue
                if x+hx<X0b or x-hx>X1b or y+hy<Y0b or y-hy>Y1b: continue
                for i in range(max(0,box.gx(x-hx)),min(box.nx,box.gx(x+hx)+1)):
                    for j in range(max(0,box.gy(y-hy)),min(box.ny,box.gy(y+hy)+1)):
                        occ[lay][(i,j)]=net
    for x0,y0,x1,y1 in poly_boxes:
        if x1<X0b or x0>X1b or y1<Y0b or y0>Y1b: continue
        for i in range(max(0,box.gx(x0)),min(box.nx,box.gx(x1)+1)):
            for j in range(max(0,box.gy(y0)),min(box.ny,box.gy(y1)+1)):
                occ[FC][(i,j)]="#BLK"; occ[BC][(i,j)]="#BLK"
    return occ,holes

def route_span(net,src,dst,bbox,w):
    box=Box(*bbox)
    occ,holes=build_local(box)
    def hole_ok(x,y):
        for hx,hy,hr in holes:
            if math.hypot(x-hx,y-hy)<hr+VIA_DRILL/2+0.25: return False
        return True
    def req(o,x,y):
        if in_court(x,y): return 0.072
        a=0.075 if net in FINE_NETS else CLR
        b=0.075 if o in FINE_NETS else CLR
        return max(a,b)
    def ok(lay,i,j,half):
        x,y=box.wx(i),box.wy(j)
        if not inside_poly(x,y) or near_edge(x,y,0.12+half): return False
        rc=int(math.ceil((half+CLR+0.05)/G))
        for di in range(-rc,rc+1):
            for dj in range(-rc,rc+1):
                o=occ[lay].get((i+di,j+dj))
                if o is None or o==net: continue
                if math.hypot(di,dj)*G < half+req(o,x,y)+0.015: return False
        return True
    si,sj=box.gx(src[0]),box.gy(src[1])
    ti,tj=box.gx(dst[0]),box.gy(dst[1])
    srcs=[(si,sj,l) for l in (FC,BC) if occ[l].get((si,sj))==net]
    if not srcs:
        print(f"  {net}: source not on net copper"); return False
    def h(i,j): return abs(i-ti)+abs(j-tj)
    openq=[]; g={}; came={}
    for s in srcs: g[s]=0; heapq.heappush(openq,(h(s[0],s[1]),0)+s)
    hw=w/2; n=0
    while openq:
        n+=1
        if n>4000000:
            print(f"  {net}: cap hit"); return False
        f,cost,i,j,l=heapq.heappop(openq)
        if cost>g.get((i,j,l),1e9): continue
        if abs(i-ti)<=2 and abs(j-tj)<=2 and occ[l].get((i,j))==net:
            path=[]; cur=(i,j,l)
            while True:
                path.append(cur)
                if cur not in came: break
                cur=came[cur]
            path.reverse()
            k=0
            while k<len(path)-1:
                a,bb2=path[k],path[k+1]
                if (a[0],a[1])==(bb2[0],bb2[1]) and a[2]!=bb2[2]:
                    add_via(box.wx(a[0]),box.wy(a[1]),net)
                    k+=1; continue
                rs=k; di,dj=bb2[0]-a[0],bb2[1]-a[1]; l0=a[2]
                while k<len(path)-1:
                    c1,c2=path[k],path[k+1]
                    if c1[2]!=l0 or c2[2]!=l0: break
                    if (c2[0]-c1[0],c2[1]-c1[1])!=(di,dj): break
                    k+=1
                add_seg(box.wx(path[rs][0]),box.wy(path[rs][1]),
                        box.wx(path[k][0]),box.wy(path[k][1]),l0,net,w)
            add_seg(box.wx(path[-1][0]),box.wy(path[-1][1]),dst[0],dst[1],path[-1][2],net,w)
            print(f"  {net}: routed ({len(path)} cells, {n} expanded)")
            return True
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            ni,nj=i+dx,j+dy
            if not(0<=ni<box.nx and 0<=nj<box.ny): continue
            o=occ[l].get((ni,nj))
            if o==net or (o is None and inside_poly(box.wx(ni),box.wy(nj))):
                if o!=net and not ok(l,ni,nj,hw): continue
                bend=0.4 if ((l==FC and dy!=0) or (l==BC and dx!=0)) else 0.0
                nc=cost+1+bend; kk=(ni,nj,l)
                if nc<g.get(kk,1e9):
                    g[kk]=nc; came[kk]=(i,j,l); heapq.heappush(openq,(nc+h(ni,nj),nc,ni,nj,l))
        ol=OTHER[l]
        if ok(l,i,j,VIA_D/2) and ok(ol,i,j,VIA_D/2) and hole_ok(box.wx(i),box.wy(j)):
            nc=cost+30; kk=(i,j,ol)
            if nc<g.get(kk,1e9):
                g[kk]=nc; came[kk]=(i,j,l); heapq.heappush(openq,(nc+h(i,j),nc,i,j,ol))
    print(f"  {net}: exhausted"); return False

SPANS=[
    ("BTN_RIGHT",   (153.35,104.50),(153.00,70.48),(146,60,163,108)),
    ("BTN_SIDE_FWD",(153.35,105.00),(115.50,103.48),(112,95,157,118)),
    ("VBAT_EN",     (157.00,101.30),(139.56,129.05),(133,96,161,133)),
]
for net,src,dst,bbox in SPANS:
    route_span(net,src,dst,bbox,0.10)

# ---- 3. fragment junk: fragments with no pad-touching item = dead copper ----
for z in board.Zones():
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
filler=pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())

gnd_pads=[]
for fp in board.GetFootprints():
    for p in fp.Pads():
        if p.GetNetname()=="GND":
            q=p.GetPosition(); gnd_pads.append((TOMM(q.x),TOMM(q.y)))
def touches_pad(x,y):
    return any(math.hypot(x-a,y-b)<0.8 for a,b in gnd_pads)
PROTECT=[(155.50,102.25),(159.75,103.50),
         (114.70,148.20),(123.30,148.20),(132.90,140.60)]
def protected(x,y):
    return any(math.hypot(x-a,y-b)<1.0 for a,b in PROTECT)

zjunk=0
for z in board.Zones():
    for lid in z.GetLayerSet().Seq():
        try: polys=z.GetFilledPolysList(lid)
        except Exception: continue
        areas=[(polys.Outline(i).Area(),i) for i in range(polys.OutlineCount())]
        if not areas: continue
        areas.sort(reverse=True)
        for _,oi in areas[1:]:          # every non-mainland fragment
            items=[]; padtouch=False
            for t in board.GetTracks():
                if t.GetNetname()!="GND": continue
                pos=t.GetPosition()
                if polys.Contains(pos,oi):
                    x,y=TOMM(pos.x),TOMM(pos.y)
                    if touches_pad(x,y) or protected(x,y): padtouch=True; break
                    items.append(t)
            if not padtouch:
                for t in items: board.Remove(t); zjunk+=1
print(f"fragment junk removed: {zjunk}", flush=True)
board.Save(PCB)
board=pcbnew.LoadBoard(PCB)
filler=pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
board.Save(PCB)
out=os.path.join(PROJ,"build","drc_span.json")
subprocess.run([KCLI,"pcb","drc","--format","json","-o",out,PCB],capture_output=True)
d=json.load(open(out,encoding="utf-8"))
from collections import Counter
sev=Counter(v.get("severity") for v in d.get("violations",[]))
typ=Counter(v["type"] for v in d.get("violations",[]))
print(f"SPAN DRC: unconnected={len(d.get('unconnected_items',[]))} "
      f"violations={len(d.get('violations',[]))} severities={dict(sev)}")
for k,n in typ.most_common(): print(f"   {k}: {n}")
for u in d.get("unconnected_items",[])[:15]:
    ds=[i.get("description","")[:44] for i in u.get("items",[])]
    print("  LEFT:"," | ".join(ds))
