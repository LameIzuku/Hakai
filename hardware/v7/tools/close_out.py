#!/usr/bin/env python3
"""Close-out pass: fix the last unconnected edges + in-court violations.

 1. delete my in-court grid-snapped ENC_B/STAT additions (0.05-multiple coords)
    that violate against freerouting's non-grid vias;
 2. re-route every remaining non-GND edge with: in-court safety margin 0.03,
    node cap 2M, bend bias — long spans route in open field;
 3. micro-bridge same-net gaps < 2 mm with exact endpoint tracks;
 4. delete orphan GND vias inside pour fragments that have no opposite pour
    (island removal then clears the fragment);
 5. C9 spoke at 0.10 width; final refill + DRC.
"""
import os, math, heapq, subprocess, json, re
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
def width_of(net): return 0.10 if net in FINE_NETS else 0.15

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

board=pcbnew.LoadBoard(PCB)
netobj={}
def ongrid(v,eps=1e-4): return abs(v*20-round(v*20))<eps

# ---- stage 1: delete my in-court grid additions for ENC_B / STAT ------------
courts=[]
for _ref,_half in (("U4",3.9),("U2",2.1)):
    for _fp in board.GetFootprints():
        if _fp.GetReference()==_ref:
            _bb=_fp.GetBoundingBox(False,False)
            _cx,_cy=TOMM(_bb.GetCenter().x),TOMM(_bb.GetCenter().y)
            courts.append((_cx-_half,_cy-_half,_cx+_half,_cy+_half))
def in_court(x,y):
    return any(x0<=x<=x1 and y0<=y<=y1 for x0,y0,x1,y1 in courts)

STUB_SEGS={((154.25,104.50),(153.35,104.50)),((154.25,106.00),(153.35,106.00)),
           ((154.25,105.00),(153.35,105.00)),((156.00,107.75),(156.00,108.70)),
           ((155.50,102.25),(155.50,102.80)),((159.75,103.50),(159.35,103.50))}
def is_stub(t):
    s,e=t.GetStart(),t.GetEnd()
    a=(round(TOMM(s.x),2),round(TOMM(s.y),2)); b=(round(TOMM(e.x),2),round(TOMM(e.y),2))
    return (a,b) in STUB_SEGS or (b,a) in STUB_SEGS

rm=0
for t in list(board.GetTracks()):
    net=t.GetNetname()
    if t.GetClass()!="PCB_VIA":
        s,e=t.GetStart(),t.GetEnd()
        ys=[TOMM(s.y),TOMM(e.y)]
        # the clearance-blind ENC_B micro-bridge grazing pad R1
        if net=="ENC_B" and int(t.GetLayer())==FC and all(105.89<v<105.99 for v in ys):
            board.Remove(t); rm+=1
print(f"stage1: removed {rm} offending bridge segments", flush=True)

# VBAT_EN ball B13 channel stub (was missing from the original four)
_vb=None
for _fp in board.GetFootprints():
    for _p in _fp.Pads():
        if _p.GetNetname()=="VBAT_EN": _vb=_p.GetNet(); break
    if _vb: break
_have=any(t.GetClass()!="PCB_VIA" and t.GetNetname()=="VBAT_EN"
          and abs(TOMM(t.GetStart().x)-157.0)<0.01 and abs(TOMM(t.GetStart().y)-102.25)<0.01
          for t in board.GetTracks())
if _vb is not None and not _have:
    _t=pcbnew.PCB_TRACK(board)
    _t.SetStart(V(157.00,102.25)); _t.SetEnd(V(157.00,101.30))
    _t.SetLayer(pcbnew.F_Cu); _t.SetWidth(MM(0.10)); _t.SetNet(_vb)
    board.Add(_t)
    print("VBAT_EN channel stub added", flush=True)
board.Save(PCB)
board=pcbnew.LoadBoard(PCB)
filler=pcbnew.ZONE_FILLER(board)
zone_by_layer={}
for z in board.Zones():
    # AREA mode: fragments below 5 mm^2 are removed even if they contain items
    try:
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_AREA)
        z.SetMinIslandArea(int(5e12))     # 5 mm^2 in nm^2
    except Exception:
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    for lid in z.GetLayerSet().Seq():
        zone_by_layer[int(lid)]=z
def pour_at(x,y,layer):
    z=zone_by_layer.get(int(layer))
    if z is None: return False
    try: return z.HitTestFilledArea(layer, V(x,y), 0)
    except Exception: return False

poly_boxes=[]
for _fp in board.GetFootprints():
    for _g in _fp.GraphicalItems():
        try:
            if _g.GetClass() not in ("PCB_SHAPE","FP_SHAPE"): continue
            lay=_g.GetLayer()
            bb=_g.GetBoundingBox()
            w,h=TOMM(bb.GetWidth()),TOMM(bb.GetHeight())
            if pcbnew.IsCopperLayer(lay) or (_g.GetLayerName()=="Edge.Cuts" and max(w,h)<=25):
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

HOLES=[]
def hole_ok(x,y):
    for hx,hy,hr in HOLES:
        if math.hypot(x-hx,y-hy) < hr+VIA_DRILL/2+0.25: return False
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
            for lay in (FC,BC): disk(lay,TOMM(p.x),TOMM(p.y),VIA_D/2+0.02,net)
        else:
            s,e=t.GetStart(),t.GetEnd()
            x1,y1,x2,y2=TOMM(s.x),TOMM(s.y),TOMM(e.x),TOMM(e.y)
            hw=TOMM(t.GetWidth())/2+0.02
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
            if dr.x>0: HOLES.append((x,y,max(TOMM(dr.x),TOMM(dr.y))/2))
            hx,hy=TOMM(sz.x)/2,TOMM(sz.y)/2
            for lay in (FC,BC):
                if not p.IsOnLayer(lay): continue
                for i in range(gxi(x-hx),gxi(x+hx)+1):
                    for j in range(gyi(y-hy),gyi(y+hy)+1):
                        if 0<=i<NX and 0<=j<NY: occ[lay][(i,j)]=net
    for x0,y0,x1,y1 in poly_boxes:
        for i in range(gxi(x0),gxi(x1)+1):
            for j in range(gyi(y0),gyi(y1)+1):
                if 0<=i<NX and 0<=j<NY:
                    occ[FC][(i,j)]="#BLK"; occ[BC][(i,j)]="#BLK"
    return occ

def req_clr(net,other,x,y):
    if in_court(x,y): return 0.072
    a=0.075 if net in FINE_NETS else CLR
    b=0.075 if other in FINE_NETS else CLR
    return max(a,b)

def usable_at(occ,lay,i,j,net,half_w,edge_ko=0.12):
    x,y=wxi(i),wyi(j)
    if near_edge(x,y,edge_ko+half_w): return False
    mm=0.03                                   # margin everywhere incl. court
    R=half_w+CLR+0.05
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
    HOLES.append((x,y,VIA_DRILL/2))

def add_seg_exact(x1,y1,x2,y2,lay,net,w):
    t=pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1,y1)); t.SetEnd(V(x2,y2)); t.SetLayer(lay)
    t.SetWidth(MM(w)); t.SetNet(netobj[net]); board.Add(t)

def route_pair(occ,net,p1,p2,w,cap=2000000):
    si,sj=gxi(p1[0]),gyi(p1[1]); ti,tj=gxi(p2[0]),gyi(p2[1])
    srcs=[(si,sj,l) for l in (FC,BC) if occ[l].get((si,sj))==net]
    if not srcs: return False
    hw=w/2
    def h(i,j): return abs(i-ti)+abs(j-tj)
    openq=[]; g={}; came={}
    for s in srcs: g[s]=0; heapq.heappush(openq,(h(s[0],s[1]),0)+s)
    n=0
    while openq:
        n+=1
        if n>cap: return False
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
                add_seg_exact(wxi(path[rs][0]),wyi(path[rs][1]),
                              wxi(path[k][0]),wyi(path[k][1]),l0,net,w)
                r=int(math.ceil(hw/G))
                for kk in range(rs,k+1):
                    ci,cj,_=path[kk]
                    for ddi in range(-r,r+1):
                        for ddj in range(-r,r+1):
                            occ[l0][(ci+ddi,cj+ddj)]=net
            # exact tail: land on the true target coordinate
            add_seg_exact(wxi(path[-1][0]),wyi(path[-1][1]),p2[0],p2[1],path[-1][2],net,w)
            return True
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            ni,nj=i+dx,j+dy
            o=occ[l].get((ni,nj))
            if o==net or (o is None and inside_poly(wxi(ni),wyi(nj))):
                if o!=net and not usable_at(occ,l,ni,nj,net,hw): continue
                bend=0.4 if ((l==FC and dy!=0) or (l==BC and dx!=0)) else 0.0
                nc=cost+1+bend; kk=(ni,nj,l)
                if nc<g.get(kk,1e9):
                    g[kk]=nc; came[kk]=(i,j,l); heapq.heappush(openq,(nc+h(ni,nj),nc,ni,nj,l))
        ol=OTHER[l]
        if (usable_at(occ,l,i,j,net,VIA_D/2) and usable_at(occ,ol,i,j,net,VIA_D/2)
                and hole_ok(wxi(i),wyi(j))):
            nc=cost+30; kk=(i,j,ol)
            if nc<g.get(kk,1e9):
                g[kk]=nc; came[kk]=(i,j,l); heapq.heappush(openq,(nc+h(i,j),nc,i,j,ol))
    return False

def drc():
    filler.Fill(board.Zones())
    board.Save(PCB)
    out=os.path.join(PROJ,"build","drc_close.json")
    subprocess.run([KCLI,"pcb","drc","--format","json","-o",out,PCB],capture_output=True)
    return json.load(open(out,encoding="utf-8"))

for it in range(4):
    d=drc()
    unc=d.get("unconnected_items",[])
    print(f"close iter {it}: unconnected={len(unc)}", flush=True)
    if not unc: break
    occ=build_occ()
    acted=0
    # orphan GND crumbs: items with pour under NEITHER layer -> delete
    for t in list(board.GetTracks()):
        if t.GetNetname()!="GND": continue
        if t.GetClass()=="PCB_VIA":
            p=t.GetPosition(); x,y=TOMM(p.x),TOMM(p.y)
            if not pour_at(x,y,pcbnew.F_Cu) and not pour_at(x,y,pcbnew.B_Cu):
                board.Remove(t); acted+=1
        else:
            s,e=t.GetStart(),t.GetEnd()
            L=TOMM((e-s).EuclideanNorm())
            if L<1.0:
                mx,my=(TOMM(s.x)+TOMM(e.x))/2,(TOMM(s.y)+TOMM(e.y))/2
                if (not pour_at(mx,my,pcbnew.F_Cu) and not pour_at(mx,my,pcbnew.B_Cu)
                        and not in_court(mx,my)):
                    board.Remove(t); acted+=1
    for u in unc:
        its=u.get("items",[])
        if len(its)!=2: continue
        ds=[x.get("description","") for x in its]
        if all(dd.startswith("Zone") for dd in ds): continue
        m=re.search(r"\[(\S+)\]",ds[0])
        if not m: continue
        net=m.group(1)
        if net.startswith("unconnected"): continue
        ps=[(x["pos"]["x"],x["pos"]["y"]) for x in its if x.get("pos")]
        ps=[p for p in ps if p!=(100.0,40.0)]
        w=width_of(net)
        if len(ps)==2:
            gap=math.hypot(ps[0][0]-ps[1][0],ps[0][1]-ps[1][1])
            if gap<2.0 and not (in_court(*ps[0]) or in_court(*ps[1])):
                lay=FC     # micro-bridge only in open field (clearance-blind)
                for x in its:
                    mm2=re.search(r"on (F|B)\.Cu",x.get("description",""))
                    if mm2: lay=FC if mm2.group(1)=="F" else BC
                add_seg_exact(ps[0][0],ps[0][1],ps[1][0],ps[1][1],lay,net,w)
                acted+=1; continue
            if route_pair(occ,net,ps[0],ps[1],w,cap=5000000) or \
               route_pair(occ,net,ps[1],ps[0],w,cap=5000000):
                acted+=1
        elif len(ps)==1 and net=="GND":
            # spoke to pour, fine width
            pc={}
            def pour_c(i,j,l):
                k=(i,j,l)
                if k not in pc: pc[k]=pour_at(wxi(i),wyi(j),l)
                return pc[k]
            si,sj=gxi(ps[0][0]),gyi(ps[0][1])
            srcs=[(si,sj,l) for l in (FC,BC) if occ[l].get((si,sj))=="GND"]
            best=None
            for rad in range(4,60):
                for l in (FC,BC):
                    for di in range(-rad,rad+1):
                        for dj in (-rad,rad):
                            if pour_c(si+di,sj+dj,l): best=(wxi(si+di),wyi(sj+dj)); break
                        if best: break
                    if best: break
                if best: break
            if best and srcs and route_pair(occ,"GND",ps[0],best,0.10,cap=100000):
                acted+=1
    print(f"  actions={acted}", flush=True)
    if acted==0: break

d=drc()
from collections import Counter
typ=Counter(v["type"] for v in d.get("violations",[]))
sev=Counter(v.get("severity") for v in d.get("violations",[]))
print(f"CLOSEOUT DRC: unconnected={len(d.get('unconnected_items',[]))} "
      f"violations={len(d.get('violations',[]))} severities={dict(sev)}")
for k,n in typ.most_common(): print(f"   {k}: {n}")
