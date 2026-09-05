#!/usr/bin/env python3
"""GND endgame: deterministically clear every remaining GND ratsnest edge.

 (a) pad<->pad / pad<->track GND edges (real positions): route directly.
 (b) pour fragments: enumerate each zone's filled outlines; any fragment
     without a GND via inside gets one placed at an interior point where the
     opposite layer's pour is also filled (ties every fragment to the mainland).
Runs on the CURRENT board (not pristine) - keeps all prior routing.
"""
import os, math, heapq, subprocess, json, re
import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
MM = pcbnew.FromMM
def TOMM(v): return v/1e6
def V(x,y): return pcbnew.VECTOR2I(MM(x),MM(y))

VIA_D, VIA_DRILL, CLR, M = 0.45, 0.20, 0.15, 0.04
FINE_NETS={"STAT","nRESET","DCC","DEC4_6","VBAT_EN","XL1","DEC3","XL2","ANT",
           "BTN_RIGHT","BTN_SIDE_FWD","ENC_B","1V9_A"}
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

G=0.05
X0,Y0=99.0,39.0
NX,NY=int(72/G)+1,int(112/G)+1
def gxi(x): return int(round((x-X0)/G))
def gyi(y): return int(round((y-Y0)/G))
def wxi(i): return round(X0+i*G,4)
def wyi(j): return round(Y0+j*G,4)
FC,BC=int(pcbnew.F_Cu),int(pcbnew.B_Cu)
OTHER={FC:BC,BC:FC}

import shutil
PRISTINE=os.path.join(PROJ,"hakai_mouse_v6_unrouted.kicad_pcb")
shutil.copyfile(PRISTINE, PCB)
board=pcbnew.LoadBoard(PCB)
filler=pcbnew.ZONE_FILLER(board)
netobj={}

# footprint copper GRAPHICS (e.g. the ANT1 antenna polygon) are not pads and
# must be treated as hard obstacles; collect their bboxes (expanded)
poly_boxes=[]
for _fp in board.GetFootprints():
    for _g in _fp.GraphicalItems():
        try:
            if _g.GetClass() not in ("PCB_SHAPE","FP_SHAPE"): continue
            if not pcbnew.IsCopperLayer(_g.GetLayer()): continue
            _bb=_g.GetBoundingBox()
            poly_boxes.append((TOMM(_bb.GetX())-0.3, TOMM(_bb.GetY())-0.3,
                               TOMM(_bb.GetX()+_bb.GetWidth())+0.3,
                               TOMM(_bb.GetY()+_bb.GetHeight())+0.3))
        except Exception:
            pass
# internal Edge.Cuts cutouts (sensor aperture / LED stadium / guide holes):
# small closed shapes inside the outline — copper must never cross them
for _d in list(board.GetDrawings())+[g for f in board.GetFootprints() for g in f.GraphicalItems()]:
    try:
        if _d.GetLayerName()!="Edge.Cuts": continue
        _bb=_d.GetBoundingBox()
        w,h=TOMM(_bb.GetWidth()),TOMM(_bb.GetHeight())
        if max(w,h)>25: continue          # board outline segments: skip
        poly_boxes.append((TOMM(_bb.GetX())-0.3, TOMM(_bb.GetY())-0.3,
                           TOMM(_bb.GetX())+w+0.3, TOMM(_bb.GetY())+h+0.3))
    except Exception:
        pass

def in_poly_box(x,y):
    return any(x0<=x<=x1 and y0<=y<=y1 for x0,y0,x1,y1 in poly_boxes)

# --- stage 0: pristine board + best freerouting session (round 2) ------------
SES=os.path.join(PROJ,"build","hakai_v6.ses")
print("SES import:", pcbnew.ImportSpecctraSES(board, SES), flush=True)
for z in board.Zones():
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
# GND ring-2 balls -> exposed pad (0.35 mm hops, both GND, deterministic)
_g=None
for _fp in board.GetFootprints():
    for _p in _fp.Pads():
        if _p.GetNetname()=="GND": _g=_p.GetNet(); break
    if _g: break
for (x1,y1,x2,y2) in ((155.50,102.25,155.50,102.80),(159.75,103.50,159.35,103.50)):
    _t=pcbnew.PCB_TRACK(board)
    _t.SetStart(V(x1,y1)); _t.SetEnd(V(x2,y2))
    _t.SetLayer(pcbnew.F_Cu); _t.SetWidth(MM(0.15)); _t.SetNet(_g)
    board.Add(_t)
board.Save(PCB)
board = pcbnew.LoadBoard(PCB)
filler = pcbnew.ZONE_FILLER(board)
zone_by_layer={}
for z in board.Zones():
    for lid in z.GetLayerSet().Seq():
        zone_by_layer[int(lid)]=z
def pour_at(x,y,layer):
    z=zone_by_layer.get(int(layer))
    if z is None: return False
    try: return z.HitTestFilledArea(layer, V(x,y), 0)
    except Exception: return False

HOLES=[]     # (x,y,radius) of EVERY drill (pads any net + vias any net)
def hole_ok(x,y):
    """a new via hole (r=VIA_DRILL/2) must keep hole-to-hole >= 0.20+margin."""
    for hx,hy,hr in HOLES:
        if math.hypot(x-hx,y-hy) < hr+VIA_DRILL/2+0.20+0.05: return False
    return True

def build_occ():
    occ={FC:{},BC:{}}
    HOLES.clear()
    def disk(lay,x,y,r,net):
        for i in range(gxi(x-r),gxi(x+r)+1):
            for j in range(gyi(y-r),gyi(y+r)+1):
                if 0<=i<NX and 0<=j<NY and (wxi(i)-x)**2+(wyi(j)-y)**2<=r*r:
                    occ[lay][(i,j)]=net
    for t in board.GetTracks():
        net=t.GetNetname()
        if net: netobj[net]=t.GetNet()
        if t.GetClass()=="PCB_VIA":
            p=t.GetPosition()
            HOLES.append((TOMM(p.x),TOMM(p.y),VIA_DRILL/2))
            for lay in (FC,BC): disk(lay,TOMM(p.x),TOMM(p.y),VIA_D/2,net)
        else:
            s,e=t.GetStart(),t.GetEnd()
            x1,y1,x2,y2=TOMM(s.x),TOMM(s.y),TOMM(e.x),TOMM(e.y)
            hw=TOMM(t.GetWidth())/2
            lay=int(t.GetLayer())
            for i in range(gxi(min(x1,x2)-hw),gxi(max(x1,x2)+hw)+1):
                for j in range(gyi(min(y1,y2)-hw),gyi(max(y1,y2)+hw)+1):
                    if 0<=i<NX and 0<=j<NY and seg_dist(wxi(i),wyi(j),x1,y1,x2,y2)<=hw:
                        occ[lay][(i,j)]=net
    for fp in board.GetFootprints():
        for p in fp.Pads():
            net=p.GetNetname() or "#NC"
            if p.GetNetname(): netobj[p.GetNetname()]=p.GetNet()
            pos=p.GetPosition(); sz=p.GetSize()
            x,y=TOMM(pos.x),TOMM(pos.y)
            dr=p.GetDrillSize()
            if dr.x>0:
                HOLES.append((x,y,max(TOMM(dr.x),TOMM(dr.y))/2))
            hx,hy=TOMM(sz.x)/2,TOMM(sz.y)/2
            for lay in (FC,BC):
                if not p.IsOnLayer(lay): continue
                for i in range(gxi(x-hx),gxi(x+hx)+1):
                    for j in range(gyi(y-hy),gyi(y+hy)+1):
                        if 0<=i<NX and 0<=j<NY: occ[lay][(i,j)]=net
    # footprint copper graphics (antenna polygon etc.) -> hard block both layers
    for x0,y0,x1,y1 in poly_boxes:
        for i in range(gxi(x0),gxi(x1)+1):
            for j in range(gyi(y0),gyi(y1)+1):
                if 0<=i<NX and 0<=j<NY:
                    occ[FC][(i,j)]="#BLK"; occ[BC][(i,j)]="#BLK"
    return occ

# QFN courtyards: clearance relaxed to the .kicad_dru value inside
courts=[]
for _ref,_half in (("U4",3.75),("U2",2.0)):
    for _fp in board.GetFootprints():
        if _fp.GetReference()==_ref:
            _bb=_fp.GetBoundingBox(False,False)
            _cx,_cy=TOMM(_bb.GetCenter().x),TOMM(_bb.GetCenter().y)
            courts.append((_cx-_half,_cy-_half,_cx+_half,_cy+_half))
def in_court(x,y):
    return any(x0<=x<=x1 and y0<=y<=y1 for x0,y0,x1,y1 in courts)

def req_clr(net,other,x=None,y=None):
    if x is not None and in_court(x,y): return 0.072
    a=0.075 if net in FINE_NETS else CLR
    b=0.075 if other in FINE_NETS else CLR
    return max(a,b)

# deterministic ring-2 escape stubs: dead-centre of the 0.25 mm channel between
# ring-0 balls -> legal by construction under the qfn_escape .kicad_dru rules.
# net -> (ball_xy, tip_xy); tip sits in open field past the ring-0 column/row.
STUBS={
    "BTN_RIGHT":     ((154.25,104.50),(153.35,104.50)),
    "ENC_B":         ((154.25,106.00),(153.35,106.00)),
    "BTN_SIDE_FWD":  ((154.25,105.00),(153.35,105.00)),
    "STAT":          ((156.00,107.75),(156.00,108.70)),
}
stub_placed=set()

def usable_at(occ,lay,i,j,net,half_w,edge_ko):
    x,y=wxi(i),wyi(j)
    if near_edge(x,y,edge_ko+half_w): return False
    mm=0.0 if in_court(x,y) else M       # grid margin impossible in the channel
    R=half_w+CLR+M
    rc=int(math.ceil(R/G))
    for di in range(-rc,rc+1):
        for dj in range(-rc,rc+1):
            o=occ[lay].get((i+di,j+dj))
            if o is None or o==net: continue
            if math.hypot(di,dj)*G < half_w+req_clr(net,o,x,y)+mm: return False
    return True

def add_via_at(x,y,net):
    v=pcbnew.PCB_VIA(board)
    v.SetPosition(V(x,y)); v.SetDrill(MM(VIA_DRILL)); v.SetWidth(MM(VIA_D))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu); v.SetNet(netobj[net]); board.Add(v)
    HOLES.append((x,y,VIA_DRILL/2))     # subsequent placements respect this hole

def route_pair(occ,net,p1,p2,w):
    si,sj=gxi(p1[0]),gyi(p1[1]); ti,tj=gxi(p2[0]),gyi(p2[1])
    srcs=[(si,sj,l) for l in (FC,BC) if occ[l].get((si,sj))==net]
    if not srcs: return False
    def goal(i,j,l): return abs(i-ti)<=3 and abs(j-tj)<=3 and occ[l].get((i,j))==net
    hw=w/2
    def h(i,j): return abs(i-ti)+abs(j-tj)
    openq=[]; g={}; came={}
    for s in srcs: g[s]=0; heapq.heappush(openq,(h(s[0],s[1]),0)+s)
    n=0
    while openq:
        n+=1
        if n>300000: return False
        f,cost,i,j,l=heapq.heappop(openq)
        if cost>g.get((i,j,l),1e9): continue
        if cost>2 and goal(i,j,l):
            path=[]; cur=(i,j,l)
            while True:
                path.append(cur)
                if cur not in came: break
                cur=came[cur]
            path.reverse()
            k=0
            while k<len(path)-1:
                a,b=path[k],path[k+1]
                if (a[0],a[1])==(b[0],b[1]) and a[2]!=b[2]:
                    add_via_at(wxi(a[0]),wyi(a[1]),net)
                    r=int(math.ceil((VIA_D/2)/G))
                    for lay in (FC,BC):
                        for di in range(-r,r+1):
                            for dj in range(-r,r+1):
                                occ[lay][(a[0]+di,a[1]+dj)]=net
                    k+=1; continue
                rs=k; di,dj=b[0]-a[0],b[1]-a[1]; l0=a[2]
                while k<len(path)-1:
                    c1,c2=path[k],path[k+1]
                    if c1[2]!=l0 or c2[2]!=l0: break
                    if (c2[0]-c1[0],c2[1]-c1[1])!=(di,dj): break
                    k+=1
                t=pcbnew.PCB_TRACK(board)
                t.SetStart(V(wxi(path[rs][0]),wyi(path[rs][1])))
                t.SetEnd(V(wxi(path[k][0]),wyi(path[k][1])))
                t.SetLayer(l0); t.SetWidth(MM(w)); t.SetNet(netobj[net]); board.Add(t)
                r=int(math.ceil(hw/G))
                for kk in range(rs,k+1):
                    ci,cj,_=path[kk]
                    for ddi in range(-r,r+1):
                        for ddj in range(-r,r+1):
                            occ[l0][(ci+ddi,cj+ddj)]=net
            return True
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            ni,nj=i+dx,j+dy
            o=occ[l].get((ni,nj))
            if o==net or (o is None and inside_poly(wxi(ni),wyi(nj))):
                if o!=net and not usable_at(occ,l,ni,nj,net,hw,0.12): continue
                # layer direction bias -> clean L-paths instead of staircases
                bend=0.4 if ((l==FC and dy!=0) or (l==BC and dx!=0)) else 0.0
                nc=cost+1+bend; kk=(ni,nj,l)
                if nc<g.get(kk,1e9):
                    g[kk]=nc; came[kk]=(i,j,l); heapq.heappush(openq,(nc+h(ni,nj),nc,ni,nj,l))
        ol=OTHER[l]
        if (usable_at(occ,l,i,j,net,VIA_D/2,0.12) and usable_at(occ,ol,i,j,net,VIA_D/2,0.12)
                and hole_ok(wxi(i),wyi(j))):
            nc=cost+30; kk=(i,j,ol)
            if nc<g.get(kk,1e9):
                g[kk]=nc; came[kk]=(i,j,l); heapq.heappush(openq,(nc+h(i,j),nc,i,j,ol))
    return False

def gnd_vias():
    """collect existing GND via positions"""
    out=[]
    for t in board.GetTracks():
        if t.GetClass()=="PCB_VIA" and t.GetNetname()=="GND":
            p=t.GetPosition(); out.append((TOMM(p.x),TOMM(p.y)))
    return out

def fragment_vias(occ):
    """place a stitch via inside every pour fragment lacking one."""
    added=0
    vias=gnd_vias()
    for lay in (FC,BC):
        z=zone_by_layer.get(lay)
        if z is None: continue
        try:
            polys=z.GetFilledPolysList(lay)
        except Exception:
            continue
        for oi in range(polys.OutlineCount()):
            ol=polys.Outline(oi)
            bb=ol.BBox()
            x0,y0=TOMM(bb.GetX()),TOMM(bb.GetY())
            x1,y1=x0+TOMM(bb.GetWidth()),y0+TOMM(bb.GetHeight())
            # fragment already tied?
            has=any(x0-0.1<=vx<=x1+0.1 and y0-0.1<=vy<=y1+0.1 and
                    polys.Contains(V(vx,vy),oi) for vx,vy in vias)
            if has: continue
            # find interior point: both pours + clearance
            done=False
            step=max(0.4,min(x1-x0,y1-y0)/6 or 0.4)
            yy=y0+0.3
            while yy<y1 and not done:
                xx=x0+0.3
                while xx<x1 and not done:
                    if (polys.Contains(V(xx,yy),oi)
                            and pour_at(xx,yy,OTHER[lay])
                            and not near_edge(xx,yy,0.35)
                            and hole_ok(xx,yy)
                            and usable_at(occ,FC,gxi(xx),gyi(yy),"GND",VIA_D/2,0.12)
                            and usable_at(occ,BC,gxi(xx),gyi(yy),"GND",VIA_D/2,0.12)):
                        add_via_at(xx,yy,"GND")
                        vias.append((xx,yy))
                        r=int(math.ceil((VIA_D/2)/G))
                        for l2 in (FC,BC):
                            for di in range(-r,r+1):
                                for dj in range(-r,r+1):
                                    occ[l2][(gxi(xx)+di,gyi(yy)+dj)]="GND"
                        added+=1; done=True
                    xx+=step
                yy+=step
    return added

for it in range(4):
    filler.Fill(board.Zones())
    board.Save(PCB)
    out=os.path.join(PROJ,"build","drc_endgame.json")
    subprocess.run([KCLI,"pcb","drc","--format","json","-o",out,PCB],capture_output=True)
    d=json.load(open(out,encoding="utf-8"))
    unc=d.get("unconnected_items",[])
    print(f"endgame iter {it}: unconnected={len(unc)}", flush=True)
    if not unc: break
    occ=build_occ()
    # (a) direct edges with two real positions, GND or not
    fixed=0
    zonepairs=0
    for u in unc:
        its=u.get("items",[])
        if len(its)!=2: continue
        ds=[x.get("description","") for x in its]
        if all(dd.startswith("Zone") for dd in ds):
            zonepairs+=1; continue
        m=re.search(r"\[(\S+)\]",ds[0])
        if not m: continue
        net=m.group(1)
        ps=[(x["pos"]["x"],x["pos"]["y"]) for x in its if x.get("pos")]
        ps=[p for p in ps if p!=(100.0,40.0)]      # zone-anchor position is useless
        w=0.10 if net in FINE_NETS else 0.15
        # ring-2 escape: lay the deterministic channel stub first, route from tip
        if net in STUBS:
            ball,tip=STUBS[net]
            if net not in stub_placed:
                t=pcbnew.PCB_TRACK(board)
                t.SetStart(V(*ball)); t.SetEnd(V(*tip)); t.SetLayer(FC)
                t.SetWidth(MM(0.10)); t.SetNet(netobj[net]); board.Add(t)
                stub_placed.add(net)
                r=int(math.ceil(0.05/G))
                for (sx,sy) in (ball,tip):
                    for di in range(-r,r+1):
                        for dj in range(-r,r+1):
                            occ[FC][(gxi(sx)+di,gyi(sy)+dj)]=net
            ps=[tip if math.hypot(p[0]-ball[0],p[1]-ball[1])<0.6 else p for p in ps]
        okd=False
        if len(ps)==2:
            okd=route_pair(occ,net,ps[0],ps[1],w) or route_pair(occ,net,ps[1],ps[0],w)
        elif len(ps)==1 and net=="GND":
            # item vs zone: short spoke to live pour
            si,sj=gxi(ps[0][0]),gyi(ps[0][1])
            srcs=[(si,sj,l) for l in (FC,BC) if occ[l].get((si,sj))=="GND"]
            pc={}
            def pour_c(i,j,l):
                k=(i,j,l)
                if k not in pc: pc[k]=pour_at(wxi(i),wyi(j),l)
                return pc[k]
            if srcs:
                # BFS outward to the nearest live-pour cell, then route to it
                seen=set(srcs); q=list(srcs); n=0; goalc=None
                while q and n<60000:
                    n+=1
                    i,j,l=q.pop(0)
                    if n>3 and pour_c(i,j,l): goalc=(i,j,l); break
                    for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
                        ni,nj=i+dx,j+dy
                        o=occ[l].get((ni,nj))
                        if (ni,nj,l) in seen: continue
                        if o=="GND" or (o is None and inside_poly(wxi(ni),wyi(nj))
                                        and usable_at(occ,l,ni,nj,"GND",0.075,0.12)):
                            seen.add((ni,nj,l)); q.append((ni,nj,l))
                if goalc:
                    okd=route_pair(occ,"GND",ps[0],(wxi(goalc[0]),wyi(goalc[1])),0.15)
        if okd: fixed+=1
    # (b) fragment vias
    fv=fragment_vias(occ)
    print(f"  direct-routed {fixed}, fragment vias {fv}, zone-pairs seen {zonepairs}", flush=True)
    if fixed==0 and fv==0: break

filler.Fill(board.Zones())
board.Save(PCB)
out=os.path.join(PROJ,"build","drc_endgame.json")
subprocess.run([KCLI,"pcb","drc","--format","json","-o",out,PCB],capture_output=True)
d=json.load(open(out,encoding="utf-8"))
from collections import Counter
typ=Counter(v["type"] for v in d.get("violations",[]))
sev=Counter(v.get("severity") for v in d.get("violations",[]))
print(f"ENDGAME DRC: unconnected={len(d.get('unconnected_items',[]))} "
      f"violations={len(d.get('violations',[]))} severities={dict(sev)}")
for k,n in typ.most_common(): print(f"   {k}: {n}")
for u in d.get("unconnected_items",[])[:12]:
    print("  LEFT: "+" | ".join(i.get("description","")[:45] for i in u.get("items",[])))
