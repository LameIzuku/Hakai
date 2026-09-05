#!/usr/bin/env python3
"""v6 post-route pipeline (consolidated, idempotent).

Starts from the pristine placement, imports the Freerouting SES, then:
  1. island removal ALWAYS on both GND pours + refill
  2. pour-validated GND stitching vias
  3. finisher: closes remaining non-GND ratsnest edges with a courtyard-aware
     clearance model (pair-max netclass rule outside the QFN courtyards,
     relaxed 0.075 inside, matching the .kicad_dru)
  4. GND spokes for stranded pads (correct start layers, fresh occupancy)
  5. rev 6.0 title block, final refill, save, authoritative DRC report
"""
import os, math, heapq, subprocess, json, re, shutil
import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
PRISTINE = os.path.join(PROJ, "hakai_mouse_v6_unrouted.kicad_pcb")
SES = os.path.join(PROJ, "build", "hakai_v6.ses")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
MM = pcbnew.FromMM
def TOMM(v): return v/1e6
def V(x,y): return pcbnew.VECTOR2I(MM(x),MM(y))

VIA_D, VIA_DRILL = 0.45, 0.20
CLR = 0.15
FINE_CLR = 0.075
HOLE_CLR = 0.20
M = 0.04                       # global safety margin
FINE_NETS={"STAT","nRESET","DCC","DEC4_6","VBAT_EN","XL1","DEC3","XL2","ANT",
           "BTN_RIGHT","BTN_SIDE_FWD","ENC_B","1V9_A"}
PWR_NETS={"VBUS","VSYS","VBAT","1V9","LDO_IN"}
def width_of(net):
    if net in FINE_NETS: return 0.10
    if net in PWR_NETS: return 0.30
    return 0.15

OUT = [(104,40),(123,40),(123,78),(147,78),(147,40),(166,40),(170,44),(170,88),
       (166,96),(166,144),(160,150),(110,150),(104,144),(104,96),(100,88),(100,44)]
def inside_poly(px,py,poly=OUT):
    n=len(poly); c=False; j=n-1
    for i in range(n):
        xi,yi=poly[i]; xj,yj=poly[j]
        if ((yi>py)!=(yj>py)) and (px < (xj-xi)*(py-yi)/(yj-yi)+xi): c=not c
        j=i
    return c
def near_edge(x,y,ko=0.30):
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

# ---------- stage 0: pristine + SES ------------------------------------------
shutil.copyfile(PRISTINE, PCB)
board=pcbnew.LoadBoard(PCB)
print("SES import:", pcbnew.ImportSpecctraSES(board, SES), flush=True)

for z in board.Zones():
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
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

# QFN courtyard boxes (relaxed-clearance regions, matches .kicad_dru)
courts=[]
for ref in ("U4","U2"):
    for fp in board.GetFootprints():
        if fp.GetReference()==ref:
            bb=fp.GetBoundingBox(False,False)
            cx,cy=TOMM(bb.GetCenter().x),TOMM(bb.GetCenter().y)
            half=3.75 if ref=="U4" else 2.0
            courts.append((cx-half,cy-half,cx+half,cy+half))
def in_court(x,y):
    return any(x0<=x<=x1 and y0<=y<=y1 for x0,y0,x1,y1 in courts)

netobj={}
def build_occ():
    """occupancy from real geometry; owner=netname, copper extents only."""
    occ={FC:{},BC:{}}
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
            hx,hy=TOMM(sz.x)/2,TOMM(sz.y)/2
            for lay in (FC,BC):
                if not p.IsOnLayer(lay): continue
                for i in range(gxi(x-hx),gxi(x+hx)+1):
                    for j in range(gyi(y-hy),gyi(y+hy)+1):
                        if 0<=i<NX and 0<=j<NY: occ[lay][(i,j)]=net
    for i in range(NX):
        x=wxi(i)
        for j in range(NY):
            if not inside_poly(x,wyi(j)) or near_edge(x,wyi(j)):
                occ[FC][(i,j)]="#BLK"; occ[BC][(i,j)]="#BLK"
    return occ

def req_clr(net,other,x,y):
    """pair-max clearance per KiCad rules, relaxed inside QFN courtyards."""
    if in_court(x,y): return FINE_CLR
    a=FINE_CLR if net in FINE_NETS else CLR
    b=FINE_CLR if other in FINE_NETS else CLR
    return max(a,b)

def usable_at(occ,lay,i,j,net,half_w):
    """copper of width 2*half_w centered here must satisfy pair-max clearance
    to every foreign cell in range; scan radius = half_w + maxreq + margin."""
    x,y=wxi(i),wyi(j)
    R=half_w+CLR+M
    rc=int(math.ceil(R/G))
    for di in range(-rc,rc+1):
        for dj in range(-rc,rc+1):
            ci,cj=i+di,j+dj
            if not(0<=ci<NX and 0<=cj<NY): return False
            o=occ[lay].get((ci,cj))
            if o is None or o==net: continue
            if o=="#BLK":
                if math.hypot(di,dj)*G <= half_w+M: return False
                continue
            need=half_w+req_clr(net,o,x,y)+M
            if math.hypot(di,dj)*G < need: return False
    return True

def add_track(x1,y1,x2,y2,lay,net,w):
    t=pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1,y1)); t.SetEnd(V(x2,y2)); t.SetLayer(lay)
    t.SetWidth(MM(w)); t.SetNet(netobj[net]); board.Add(t)
def add_via_at(x,y,net):
    v=pcbnew.PCB_VIA(board)
    v.SetPosition(V(x,y)); v.SetDrill(MM(VIA_DRILL)); v.SetWidth(MM(VIA_D))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu); v.SetNet(netobj[net]); board.Add(v)

def commit(occ,path,net,w):
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
        add_track(wxi(path[rs][0]),wyi(path[rs][1]),wxi(path[k][0]),wyi(path[k][1]),l0,net,w)
        r=int(math.ceil((w/2)/G))
        for kk in range(rs,k+1):
            ci,cj,_=path[kk]
            for ddi in range(-r,r+1):
                for ddj in range(-r,r+1):
                    occ[l0][(ci+ddi,cj+ddj)]=net

def astar(occ,net,srcs,goal_fn,anchor,w,cap=900000,via_cost=40):
    hw=w/2
    vhw=VIA_D/2
    ax,ay=anchor
    def h(i,j): return abs(i-ax)+abs(j-ay)
    openq=[]; g={}; came={}
    for s in srcs:
        g[s]=0; heapq.heappush(openq,(h(s[0],s[1]),0)+s)
    n=0
    while openq:
        n+=1
        if n>cap: return None
        f,cost,i,j,l=heapq.heappop(openq)
        if cost>g.get((i,j,l),1e9): continue
        if cost>2 and goal_fn(i,j,l):
            path=[]; cur=(i,j,l)
            while True:
                path.append(cur)
                if cur not in came: break
                cur=came[cur]
            path.reverse(); return path
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            ni,nj=i+dx,j+dy
            o=occ[l].get((ni,nj))
            if o==net or (o is None and inside_poly(wxi(ni),wyi(nj))):
                if o!=net and not usable_at(occ,l,ni,nj,net,hw): continue
                nc=cost+1; kk=(ni,nj,l)
                if nc<g.get(kk,1e9):
                    g[kk]=nc; came[kk]=(i,j,l); heapq.heappush(openq,(nc+h(ni,nj),nc,ni,nj,l))
        ol=OTHER[l]
        if usable_at(occ,l,i,j,net,vhw) and usable_at(occ,ol,i,j,net,vhw):
            nc=cost+via_cost; kk=(i,j,ol)
            if nc<g.get(kk,1e9):
                g[kk]=nc; came[kk]=(i,j,l); heapq.heappush(openq,(nc+h(i,j),nc,i,j,ol))
    return None

def drc():
    out=os.path.join(PROJ,"build","drc_post.json")
    filler.Fill(board.Zones())
    board.Save(PCB)
    subprocess.run([KCLI,"pcb","drc","--format","json","-o",out,PCB],capture_output=True)
    return json.load(open(out,encoding="utf-8"))

# ---------- stage 1: stitching vias ------------------------------------------
occ=build_occ()
def stitch_ok(occ,i,j):
    return (usable_at(occ,FC,i,j,"GND",VIA_D/2) and
            usable_at(occ,BC,i,j,"GND",VIA_D/2))
stitch=0
placed=[]
for x10 in range(1000,1680,40):        # 4mm grid in 0.1mm units
    for y10 in range(430,1480,40):
        x,y=x10/10.0,y10/10.0
        if near_edge(x,y,0.45): continue
        if not (pour_at(x,y,pcbnew.F_Cu) and pour_at(x,y,pcbnew.B_Cu)): continue
        i,j=gxi(x),gyi(y)
        if not stitch_ok(occ,i,j): continue
        if any(math.hypot(x-a,y-b)<2.5 for a,b in placed): continue
        if "GND" not in netobj: continue
        add_via_at(x,y,"GND")
        r=int(math.ceil((VIA_D/2)/G))
        for lay in (FC,BC):
            for di in range(-r,r+1):
                for dj in range(-r,r+1):
                    occ[lay][(i+di,j+dj)]="GND"
        placed.append((x,y)); stitch+=1
print("stitch vias:",stitch, flush=True)

# ---------- stage 2: close non-GND edges -------------------------------------
for it in range(4):
    d=drc()
    edges=[]
    for u in d.get("unconnected_items",[]):
        its=u.get("items",[])
        if len(its)!=2: continue
        ds=[x.get("description","") for x in its]
        if any("[GND]" in dd for dd in ds): continue
        m=re.search(r"\[(\S+)\]",ds[0])
        if not m: continue
        ps=[(x["pos"]["x"],x["pos"]["y"]) for x in its if x.get("pos")]
        if len(ps)==2: edges.append((m.group(1),ps[0],ps[1]))
    print(f"finisher iter {it}: {len(edges)} non-GND edges", flush=True)
    if not edges: break
    occ=build_occ()
    done=0
    for net,p1,p2 in edges:
        w=width_of(net)
        for a,bgt in ((p1,p2),(p2,p1)):
            si,sj=gxi(a[0]),gyi(a[1])
            srcs=[(si,sj,l) for l in (FC,BC) if occ[l].get((si,sj))==net]
            if not srcs: continue
            ti,tj=gxi(bgt[0]),gyi(bgt[1])
            goal=lambda i,j,l,ti=ti,tj=tj,net=net: (abs(i-ti)<=3 and abs(j-tj)<=3
                                                    and occ[l].get((i,j))==net)
            path=astar(occ,net,srcs,goal,(ti,tj),w)
            if path:
                commit(occ,path,net,w); done+=1; break
    print(f"  closed {done}", flush=True)
    if done==0: break

# ---------- stage 3: GND spokes ----------------------------------------------
for it in range(4):
    d=drc()
    pts=[]
    for u in d.get("unconnected_items",[]):
        for x in u.get("items",[]):
            desc=x.get("description","")
            if "[GND]" not in desc or desc.startswith("Zone"): continue
            pos=x.get("pos") or {}
            if pos.get("x") is None: continue
            pts.append((round(pos["x"],2),round(pos["y"],2)))
    pts=sorted(set(pts))
    print(f"GND spokes iter {it}: unconnected={len(d.get('unconnected_items',[]))} pts={len(pts)}", flush=True)
    if not pts: break
    occ=build_occ()
    pc={}
    def pour_c(i,j,l):
        k=(i,j,l)
        if k not in pc: pc[k]=pour_at(wxi(i),wyi(j),l)
        return pc[k]
    fixed=0
    for px,py in pts:
        si,sj=gxi(px),gyi(py)
        srcs=[(si,sj,l) for l in (FC,BC) if occ[l].get((si,sj))=="GND"]
        if not srcs: continue
        goal=lambda i,j,l: pour_c(i,j,l)
        path=astar(occ,"GND",srcs,goal,(si,sj),0.15,cap=80000,via_cost=25)
        if path:
            commit(occ,path,"GND",0.15); fixed+=1
    print(f"  spokes {fixed}", flush=True)
    if fixed==0: break

# ---------- stage 4: finalize --------------------------------------------------
tb=board.GetTitleBlock()
tb.SetRevision("6.0")
tb.SetTitle("HAKAI Wireless Gaming Mouse - Rev 6.0")
board.SetTitleBlock(tb)
d=drc()
from collections import Counter
sev=Counter(v.get("severity") for v in d.get("violations",[]))
typ=Counter(v["type"] for v in d.get("violations",[]))
print(f"POST-ROUTE DRC: unconnected={len(d.get('unconnected_items',[]))} "
      f"violations={len(d.get('violations',[]))} severities={dict(sev)}", flush=True)
for k,n in typ.most_common(): print(f"   {k}: {n}")
