#!/usr/bin/env python3
"""HAKAI mouse v6 autorouter (pcbnew, KiCad 10).

Two-layer grid maze router:
  * fine-pitch pads on U4 (aQFN-73) and U2 (VQFN-16) get explicit radial escape
    stubs first, so the maze router only works in open space and the QFN bodies
    are then hard-blocked;
  * every non-GND net is connected via a min-spanning tree of A* routes on a
    0.1 mm grid, F.Cu biased horizontal / B.Cu biased vertical, vias to switch;
  * GND rides the existing both-layer pours; a via grid stitches the planes.

Run with KiCad's bundled python:
  "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" tools/route.py
"""
import os, heapq, sys, shutil
import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
PRISTINE = os.path.join(PROJ, "hakai_mouse_v6_unrouted.kicad_pcb")
MM = pcbnew.FromMM
def TOMM(v): return v / 1e6
def V(x, y): return pcbnew.VECTOR2I(MM(x), MM(y))

# ---- design rules ----------------------------------------------------------
G = 0.1
TRACE = 0.15
TRACE_PWR = 0.30
CLR = 0.15
VIA_D = 0.45
VIA_DRILL = 0.25
QFN_TRACE = 0.10
QFN_CLR = 0.075
VIA_COST = 11          # in grid-steps: cheap enough to use both layers freely
BEND = 0.6            # per off-bias step
MAX_EXPAND = 150000    # default A* node cap (pass1/2); RRR raises it via CAP
EDGE_KO = 0.22         # board-edge copper keep-out (rule wants >=0.15)
MARGIN = 0.04          # extra halo vs grid quantization
# track owns cells within this of its centreline (self half + clr + other half)
def thalo(w): return w/2 + CLR + TRACE/2 + MARGIN
VHALO = VIA_D/2 + CLR + TRACE/2 + MARGIN     # via copper halo
HOLE_CLR = 0.25                               # board min hole-to-copper
# via keep-clear radius: copper disk vs foreign copper AND via hole vs copper
VDISK = max(VIA_D/2 + CLR, VIA_DRILL/2 + HOLE_CLR) + MARGIN
VDISK_CELLS = [(di,dj) for di in range(-6,7) for dj in range(-6,7)
               if (di*G)**2+(dj*G)**2 <= VDISK*VDISK]
PWR_NETS = {"1V9","1V9_A","VSYS","VBAT","VBUS","LDO_IN","DEC4_6"}

OUT = [(104,40),(123,40),(123,78),(147,78),(147,40),(166,40),(170,44),(170,88),
       (166,96),(166,144),(160,150),(110,150),(104,144),(104,96),(100,88),(100,44)]

def inside_poly(px, py, poly=OUT):
    n=len(poly); c=False; j=n-1
    for i in range(n):
        xi,yi=poly[i]; xj,yj=poly[j]
        if ((yi>py)!=(yj>py)) and (px < (xj-xi)*(py-yi)/(yj-yi)+xi):
            c=not c
        j=i
    return c

X0,Y0,X1,Y1 = 99.0,39.0,171.0,151.0
NX=int((X1-X0)/G)+1; NY=int((Y1-Y0)/G)+1
def gx(x): return int(round((x-X0)/G))
def gy(y): return int(round((y-Y0)/G))
def wx(i): return round(X0+i*G,3)
def wy(j): return round(Y0+j*G,3)

occ = {pcbnew.F_Cu:{}, pcbnew.B_Cu:{}}
def block(layer,i,j,owner):
    if 0<=i<NX and 0<=j<NY:
        if occ[layer].get((i,j))=="#BLK": return
        occ[layer][(i,j)]=owner
def stamp(layer,cx,cy,hx,hy,owner):
    for i in range(gx(cx-hx),gx(cx+hx)+1):
        for j in range(gy(cy-hy),gy(cy+hy)+1):
            block(layer,i,j,owner)
def usable(layer,i,j,net):
    if not(0<=i<NX and 0<=j<NY): return False
    o=occ[layer].get((i,j))
    return o is None or o==net
hole_ko=set()      # grid cells too close to ANY pad hole for a via
def via_ok(i,j,net):
    """a through-via at (i,j) needs its copper disk clear of foreign copper,
    its hole clear of all copper, and clearance from every pad hole."""
    if (i,j) in hole_ko: return False
    for di,dj in VDISK_CELLS:
        ci,cj=i+di,j+dj
        for lay in (pcbnew.F_Cu,pcbnew.B_Cu):
            o=occ[lay].get((ci,cj))
            if o=="#BLK" or (o is not None and o!=net): return False
            if (ci,cj) in hard[lay] and o!=net: return False
    return True

# RRR bookkeeping: hard cells (pads/body/outside, never rippable), per-net items
hard={pcbnew.F_Cu:set(), pcbnew.B_Cu:set()}
net_items={}        # netname -> [board items]  (for rip-up)
net_occ={}          # netname -> set (layer,i,j) it stamped as track/via copper
def mark_hard(layer,cx,cy,hx,hy):
    for i in range(gx(cx-hx),gx(cx+hx)+1):
        for j in range(gy(cy-hy),gy(cy+hy)+1):
            if 0<=i<NX and 0<=j<NY: hard[layer].add((i,j))

# idempotent: always route from the pristine unrouted snapshot
shutil.copyfile(PRISTINE, PCB)
board = pcbnew.LoadBoard(PCB)
netmap = {}   # populated in the pad-raster loop below

# outside board (+EDGE_KO keep-out) -> hard block
def near_edge(x,y):
    if not inside_poly(x,y): return True
    for ox,oy in ((EDGE_KO,0),(-EDGE_KO,0),(0,EDGE_KO),(0,-EDGE_KO),
                  (EDGE_KO*0.7,EDGE_KO*0.7),(-EDGE_KO*0.7,EDGE_KO*0.7),
                  (EDGE_KO*0.7,-EDGE_KO*0.7),(-EDGE_KO*0.7,-EDGE_KO*0.7)):
        if not inside_poly(x+ox,y+oy): return True
    return False
for i in range(NX):
    xi=wx(i)
    for j in range(NY):
        if near_edge(xi,wy(j)):
            occ[pcbnew.F_Cu][(i,j)]="#BLK"; occ[pcbnew.B_Cu][(i,j)]="#BLK"
            hard[pcbnew.F_Cu].add((i,j)); hard[pcbnew.B_Cu].add((i,j))

# ---- pads ------------------------------------------------------------------
fps={f.GetReference():f for f in board.GetFootprints()}
pad_of={}       # (ref,num)->pad
padinfo={}      # (ref,num)->(net,x,y,hx,hy,on_f,on_b)
for ref,fp in fps.items():
    for p in fp.Pads():
        num=p.GetNumber()
        if num=="": continue
        net=p.GetNetname()
        pos=p.GetPosition(); x,y=TOMM(pos.x),TOMM(pos.y)
        sz=p.GetSize(); hx,hy=TOMM(sz.x)/2,TOMM(sz.y)/2
        on_f=p.IsOnLayer(pcbnew.F_Cu); on_b=p.IsOnLayer(pcbnew.B_Cu)
        pad_of[(ref,num)]=p
        padinfo[(ref,num)]=(net,x,y,hx,hy,on_f,on_b)
        if net: netmap[net]=p.GetNet()
        dr=p.GetDrillSize()
        if dr.x>0:   # PTH/NPTH: keep via holes away from this hole
            rko=max(TOMM(dr.x),TOMM(dr.y))/2 + HOLE_CLR + VIA_DRILL/2 + MARGIN
            for a in range(gx(x-rko),gx(x+rko)+1):
                for b in range(gy(y-rko),gy(y+rko)+1):
                    if (wx(a)-x)**2+(wy(b)-y)**2 <= rko*rko:
                        hole_ko.add((a,b))
        halo=CLR+TRACE/2+MARGIN
        for lay,on in ((pcbnew.F_Cu,on_f),(pcbnew.B_Cu,on_b)):
            if on:
                stamp(lay,x,y,hx+halo,hy+halo,net if net else "#NC")
                mark_hard(lay,x,y,hx+halo,hy+halo)   # pads never rippable

# core pass: re-own each netted pad's core (no halo) so its own net can always
# reach it even where a neighbouring pad's clearance halo overlapped it
for (ref,num),(net,x,y,hx,hy,of,ob) in padinfo.items():
    if not net or net.startswith("unconnected"): continue
    for lay,on in ((pcbnew.F_Cu,of),(pcbnew.B_Cu,ob)):
        if on:
            for i in range(gx(x-hx),gx(x+hx)+1):
                for j in range(gy(y-hy),gy(y+hy)+1):
                    if 0<=i<NX and 0<=j<NY:
                        occ[lay][(i,j)]=net        # pad copper always reachable
                        hard[lay].discard((i,j))

# ---- track / via helpers ---------------------------------------------------
made_tracks=0; made_vias=0
def add_seg(x1,y1,x2,y2,layer,nobj,width):
    global made_tracks
    if (x1,y1)==(x2,y2): return
    t=pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1,y1)); t.SetEnd(V(x2,y2)); t.SetLayer(layer)
    t.SetWidth(MM(width)); t.SetNet(nobj); board.Add(t); made_tracks+=1
    net_items.setdefault(nobj.GetNetname(),[]).append(t)
def add_via(x,y,nobj):
    global made_vias
    v=pcbnew.PCB_VIA(board); v.SetPosition(V(x,y))
    v.SetDrill(MM(VIA_DRILL)); v.SetWidth(MM(VIA_D))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu); v.SetNet(nobj); board.Add(v); made_vias+=1
    net_items.setdefault(nobj.GetNetname(),[]).append(v)

def stamp_seg(x1,y1,x2,y2,layer,name,width):
    """own the swept rectangle of a track (with clearance halo) under `name`."""
    h=thalo(width)
    i0,i1=sorted((gx(min(x1,x2)),gx(max(x1,x2))))
    j0,j1=sorted((gy(min(y1,y2)),gy(max(y1,y2))))
    for i in range(i0-2,i1+3):
        for j in range(j0-2,j1+3):
            cx,cy=wx(i),wy(j)
            if (min(x1,x2)-h<=cx<=max(x1,x2)+h) and (min(y1,y2)-h<=cy<=max(y1,y2)+h):
                if (i,j) in hard[layer]: continue
                block(layer,i,j,name)
                net_occ.setdefault(name,set()).add((layer,i,j))

STUB_ITEMS=set()     # fanout stub tracks: NEVER ripped (landings depend on them)
land_cells={}        # netname -> set of landing (i,j,layer) cells to preserve

def rip_net(name):
    """remove a net's tracks/vias (except fanout stubs) and free its
    occupancy cells; landing cells survive so reroutes reconnect to real copper."""
    keep=[]
    for it in net_items.get(name,[]):
        if id(it) in STUB_ITEMS:
            keep.append(it); continue
        try: board.Remove(it)
        except Exception: pass
    net_items[name]=keep
    for (layer,i,j) in net_occ.get(name,()):
        if (i,j) in hard[layer]: continue          # stub corridors stay owned
        if occ[layer].get((i,j))==name: occ[layer][(i,j)]=None
    net_occ[name]={c for c in net_occ.get(name,set()) if (c[1],c[2]) in hard[c[0]]}
    net_cells[name]=set(land_cells.get(name,set()))

# ---- QFN fanout ------------------------------------------------------------
def fanout(ref, body_c, body_half, ring2_extra=0.7):
    """draw radial escape stubs for every non-GND, netted pad of `ref`.
    returns dict (ref,num)->(landing_x,landing_y) on F.Cu, and blocks body box."""
    cx,cy=body_c
    landings={}
    fp=fps[ref]
    for p in fp.Pads():
        num=p.GetNumber()
        if num in("","EP"): continue
        net=p.GetNetname()
        if not net or net=="GND" or net.startswith("unconnected"): continue
        pos=p.GetPosition(); x,y=TOMM(pos.x),TOMM(pos.y)
        dx,dy=x-cx,y-cy
        # dominant axis = escape direction
        if abs(dx)>=abs(dy):
            ux,uy=(1 if dx>0 else -1),0
        else:
            ux,uy=0,(1 if dy>0 else -1)
        inset=body_half-max(abs(dx),abs(dy))
        length=0.55+(ring2_extra if inset>0.35 else 0.0)
        lx,ly=round(x+ux*length,1),round(y+uy*length,1)
        nobj=netmap[net]
        add_seg(x,y,lx,ly,pcbnew.F_Cu,nobj,QFN_TRACE)
        STUB_ITEMS.add(id(net_items[net][-1]))     # stubs survive rip-up
        land_cells.setdefault(net,set()).add((gx(lx),gy(ly),pcbnew.F_Cu))
        # register + protect the stub corridor (foreign nets must not cross it)
        stamp_seg(x,y,lx,ly,pcbnew.F_Cu,net,QFN_TRACE)
        h=QFN_TRACE/2+QFN_CLR
        for gi in range(gx(min(x,lx)-h),gx(max(x,lx)+h)+1):
            for gj in range(gy(min(y,ly)-h),gy(max(y,ly)+h)+1):
                hard[pcbnew.F_Cu].add((gi,gj))
        landings[(ref,num)]=(lx,ly)
    # hard-block body box (both layers) so nothing routes through the part
    for i in range(gx(cx-body_half),gx(cx+body_half)+1):
        for j in range(gy(cy-body_half),gy(cy+body_half)+1):
            occ[pcbnew.F_Cu][(i,j)]="#BLK"; occ[pcbnew.B_Cu][(i,j)]="#BLK"
            hard[pcbnew.F_Cu].add((i,j)); hard[pcbnew.B_Cu].add((i,j))
    # re-open landing points + stub corridor ownership on F (reachable by net)
    for (r,num),(lx,ly) in landings.items():
        net=padinfo[(r,num)][0]
        stamp(pcbnew.F_Cu,lx,ly,QFN_TRACE/2+QFN_CLR,QFN_TRACE/2+QFN_CLR,net)
        occ[pcbnew.F_Cu][(gx(lx),gy(ly))]=net
    return landings

# body centers/halves
def body_of(ref):
    fp=fps[ref]; bb=fp.GetBoundingBox(False,False)
    cx=TOMM(bb.GetCenter().x); cy=TOMM(bb.GetCenter().y)
    return (cx,cy)

land = {}
# U4 aQFN-73 (7x7), U2 VQFN-16 (3x3)
land.update(fanout("U4", body_of("U4"), 3.5, ring2_extra=0.8))
land.update(fanout("U2", body_of("U2"), 1.8, ring2_extra=0.6))
print(f"fanout stubs: {made_tracks} tracks")

# ---- terminals per net -----------------------------------------------------
# terminal = (x,y, layers-tuple).  QFN pads replaced by their landing (F only).
def terminals_for(net):
    ts=[]
    for (ref,num),(n,x,y,hx,hy,of,ob) in padinfo.items():
        if n!=net: continue
        if (ref,num) in land:
            lx,ly=land[(ref,num)]; ts.append((lx,ly,(pcbnew.F_Cu,)))
        else:
            layers=tuple(l for l,on in((pcbnew.F_Cu,of),(pcbnew.B_Cu,ob)) if on)
            ts.append((x,y,layers))
    return ts

# ---- A* between two terminals ----------------------------------------------
DIRS=[(1,0),(-1,0),(0,1),(0,-1)]
def force_own(cell_layers, net):
    """guarantee A* can start/end: own the terminal cell (+1 ring) for this net."""
    for i,j,l in cell_layers:
        for di in (-1,0,1):
            for dj in (-1,0,1):
                ci,cj=i+di,j+dj
                if 0<=ci<NX and 0<=cj<NY and occ[l].get((ci,cj))!="#BLK":
                    occ[l][(ci,cj)]=net

MARK={"#BLK","#NC",None}
def astar_soft(net, srcs, goalcells, anchor, SOFT=500, cap=MAX_EXPAND):
    """like astar but MAY cross foreign track copper at high cost (never crosses
    hard cells = pads/body/outside). Returns (path, crossed_nets) or (None,set())."""
    ax,ay=anchor
    def h(i,j): return abs(i-ax)+abs(j-ay)
    def passable(l,i,j):
        if not(0<=i<NX and 0<=j<NY): return None
        o=occ[l].get((i,j))
        if o==net: return 0                 # own copper/landing: always ok
        if (i,j) in hard[l]: return None    # foreign pad/body/stub/outside
        if o=="#BLK": return None
        if o is None: return 0
        return SOFT                         # foreign track copper -> crossable
    openq=[]; g={}; came={}
    for i,j,l in srcs:
        if passable(l,i,j) is None: continue
        g[(i,j,l)]=0; heapq.heappush(openq,(h(i,j),0,i,j,l))
    expanded=0
    while openq:
        expanded+=1
        if expanded>cap: return None,set()
        f,cost,i,j,l=heapq.heappop(openq)
        if cost>g.get((i,j,l),1e9): continue
        if (i,j,l) in goalcells:
            path=[]; cur=(i,j,l)
            while True:
                path.append(cur)
                if cur not in came: break
                cur=came[cur]
            path.reverse()
            crossed={occ[cl].get((ci,cj)) for (ci,cj,cl) in path}
            crossed={c for c in crossed if c not in MARK and c!=net}
            return path,crossed
        for dx,dy in DIRS:
            ni,nj=i+dx,j+dy
            pc=passable(l,ni,nj)
            if pc is None: continue
            bias=BEND if ((l==pcbnew.F_Cu and dy!=0) or (l==pcbnew.B_Cu and dx!=0)) else 0
            nc=cost+1+bias+pc; k=(ni,nj,l)
            if nc<g.get(k,1e9):
                g[k]=nc; came[k]=(i,j,l); heapq.heappush(openq,(nc+h(ni,nj),nc,ni,nj,l))
        ol=pcbnew.B_Cu if l==pcbnew.F_Cu else pcbnew.F_Cu
        pc=passable(ol,i,j)
        if pc is not None and (pc==0 and via_ok(i,j,net) or pc>0):
            nc=cost+VIA_COST+pc; k=(i,j,ol)
            if nc<g.get(k,1e9):
                g[k]=nc; came[k]=(i,j,l); heapq.heappush(openq,(nc+h(i,j),nc,i,j,ol))
    return None,set()

def astar(net, srcs, goalcells, anchor, cap=MAX_EXPAND):
    """srcs: list (i,j,layer). goalcells: set (i,j,layer) to reach (any).
    anchor: single (ai,aj) for the heuristic. Returns path or None."""
    ax,ay=anchor
    def h(i,j):
        return abs(i-ax)+abs(j-ay)
    openq=[]; g={}; came={}
    for i,j,l in srcs:
        if not usable(l,i,j,net): continue
        g[(i,j,l)]=0; heapq.heappush(openq,(h(i,j),0,i,j,l))
    expanded=0
    while openq:
        expanded+=1
        if expanded>cap: return None
        f,cost,i,j,l=heapq.heappop(openq)
        if cost>g.get((i,j,l),1e9): continue
        if (i,j,l) in goalcells:
            path=[]; cur=(i,j,l)
            while True:
                path.append(cur)
                if cur not in came: break
                cur=came[cur]
            path.reverse(); return path
        for dx,dy in DIRS:
            ni,nj=i+dx,j+dy
            if not usable(l,ni,nj,net): continue
            bias=BEND if ((l==pcbnew.F_Cu and dy!=0) or (l==pcbnew.B_Cu and dx!=0)) else 0
            nc=cost+1+bias; k=(ni,nj,l)
            if nc<g.get(k,1e9):
                g[k]=nc; came[k]=(i,j,l); heapq.heappush(openq,(nc+h(ni,nj),nc,ni,nj,l))
        ol=pcbnew.B_Cu if l==pcbnew.F_Cu else pcbnew.F_Cu
        if usable(ol,i,j,net) and via_ok(i,j,net):
            nc=cost+VIA_COST; k=(i,j,ol)
            if nc<g.get(k,1e9):
                g[k]=nc; came[k]=(i,j,l); heapq.heappush(openq,(nc+h(i,j),nc,i,j,ol))
    return None

def stamp_via(name,i,j):
    for lay in (pcbnew.F_Cu,pcbnew.B_Cu):
        occ[lay][(i,j)]=name; net_occ.setdefault(name,set()).add((lay,i,j))
        for a in range(gx(wx(i)-VHALO),gx(wx(i)+VHALO)+1):
            for b in range(gy(wy(j)-VHALO),gy(wy(j)+VHALO)+1):
                if (a,b) in hard[lay]: continue
                if occ[lay].get((a,b)) in (None,name):
                    occ[lay][(a,b)]=name; net_occ.setdefault(name,set()).add((lay,a,b))

def commit_path(path,nobj,width,connected=None):
    name=nobj.GetNetname()
    pts=path
    if connected is not None:
        for c in pts: connected.add(c)
        net_cells.setdefault(name,set()).update(pts)
    k=0
    while k<len(pts)-1:
        i,j,l=pts[k]
        i2,j2,l2=pts[k+1]
        if (i,j)==(i2,j2) and l!=l2:
            add_via(wx(i),wy(j),nobj); stamp_via(name,i,j)
            k+=1; continue
        run_start=k; l0=l
        di=i2-i; dj=j2-j
        while k<len(pts)-1:
            a=pts[k]; b=pts[k+1]
            if a[2]!=l0 or b[2]!=l0: break
            if (b[0]-a[0],b[1]-a[1])!=(di,dj): break
            k+=1
        si,sj,_=pts[run_start]; ei,ej,_=pts[k]
        add_seg(wx(si),wy(sj),wx(ei),wy(ej),l0,nobj,width)
        stamp_seg(wx(si),wy(sj),wx(ei),wy(ej),l0,name,width)

# ---- MST + route ------------------------------------------------------------
def mst_edges(pts):
    n=len(pts)
    if n<=1: return []
    used=[0]; edges=[]
    while len(used)<n:
        best=None
        for a in used:
            for b in range(n):
                if b in used: continue
                d=abs(pts[a][0]-pts[b][0])+abs(pts[a][1]-pts[b][1])
                if best is None or d<best[0]: best=(d,a,b)
        edges.append((best[1],best[2])); used.append(best[2])
    return edges

signal_nets=[n for n in netmap if n and n!="GND" and not n.startswith("unconnected")]
def net_span(net):
    ts=terminals_for(net)
    if len(ts)<2: return 0
    xs=[t[0] for t in ts]; ys=[t[1] for t in ts]
    return (max(xs)-min(xs))+(max(ys)-min(ys))
signal_nets.sort(key=net_span)          # short nets first

def cells_of(term):
    x,y,layers=term
    return [(gx(x),gy(y),l) for l in layers]

net_cells={}    # net -> set of committed (i,j,l) copper cells (for retry)
routed=0; failed=[]
# ---- pass 1: MST fixed-target edges, single-target A* ----------------------
for net in signal_nets:
    ts=terminals_for(net)
    if len(ts)<2: continue
    width=TRACE_PWR if net in PWR_NETS else TRACE
    nobj=netmap[net]
    nc=net_cells.setdefault(net,set())
    for a,b in mst_edges(ts):
        srcs=cells_of(ts[a]); goals=cells_of(ts[b])
        force_own(srcs,net); force_own(goals,net)
        for c in srcs+goals: nc.add(c)
        if {(i,j) for i,j,l in srcs} & {(i,j) for i,j,l in goals}:
            routed+=1; continue                 # coincident terminals
        anchor=(gx(ts[b][0]),gy(ts[b][1]))
        path=astar(net,srcs,set(goals),anchor)
        if path is None:
            failed.append((net,srcs,ts[b])); continue
        commit_path(path,nobj,width,nc)
        routed+=1
print(f"pass1 routed={routed} failed={len(failed)} tracks={made_tracks} vias={made_vias}", flush=True)

# ---- pass 2: retry failures -> connect to ANY copper already on the net ------
retry=failed; failed=[]
for net,srcs,gterm in retry:
    width=TRACE_PWR if net in PWR_NETS else TRACE
    nobj=netmap[net]
    src_set={(i,j,l) for i,j,l in srcs}
    goalcells={c for c in net_cells.get(net,set()) if c not in src_set}
    if not goalcells:
        failed.append((net,srcs,gterm)); continue
    force_own(srcs,net)
    si,sj,_=srcs[0]
    anchor=min({(i,j) for i,j,l in goalcells}, key=lambda c: abs(c[0]-si)+abs(c[1]-sj))
    path=astar(net,srcs,goalcells,anchor)
    if path is None:
        failed.append((net,srcs,gterm)); continue
    commit_path(path,nobj,width,net_cells[net]); routed+=1

print(f"AFTER RETRY: routed={routed} failed={len(failed)} tracks={made_tracks} vias={made_vias}", flush=True)

# ---- pass 3: rip-up & reroute ----------------------------------------------
def net_goalcells(net, gterm, srcs):
    gc=set(net_cells.get(net,set()))
    gc|={(gx(gterm[0]),gy(gterm[1]),l) for l in gterm[2]}
    src_set={(i,j,l) for i,j,l in srcs}
    return {c for c in gc if c not in src_set}

def route_net_full(cn):
    """(re)route every MST edge of cn with normal A*; return list of failed edges."""
    ts=terminals_for(cn); w=TRACE_PWR if cn in PWR_NETS else TRACE
    nobj=netmap[cn]; nc=net_cells.setdefault(cn,set()); fails=[]
    for a,b in mst_edges(ts):
        srcs=cells_of(ts[a]); goals=cells_of(ts[b])
        force_own(srcs,cn); force_own(goals,cn)
        for c in srcs+goals: nc.add(c)
        if {(i,j) for i,j,l in srcs} & {(i,j) for i,j,l in goals}: continue
        # prefer connecting to whatever copper the net already has
        gc=set(goals)|{c for c in nc if c not in {(i,j,l) for i,j,l in srcs}}
        anchor=(gx(ts[b][0]),gy(ts[b][1]))
        path=astar(cn,srcs,gc,anchor)
        if path is None:
            fails.append((cn,srcs,ts[b])); continue
        commit_path(path,nobj,w,nc)
    return fails

# only SMALL, non-power signal nets may be ripped (bounded damage if a reroute
# fails); crossing a big/power/GND net is disallowed so RRR can never shatter it
nterm={n:len(terminals_for(n)) for n in signal_nets}
def rippable(cn):
    return cn not in PWR_NETS and cn!="GND" and nterm.get(cn,99)<=4

queue=failed; failed=[]; rounds=0
while queue and rounds<10:
    rounds+=1; nextq=[]
    for net,srcs,gterm in queue:
        width=TRACE_PWR if net in PWR_NETS else TRACE
        goalcells=net_goalcells(net,gterm,srcs)
        if not goalcells:
            nextq.append((net,srcs,gterm)); continue
        force_own(srcs,net)
        gcoords={(i,j) for i,j,l in goalcells}
        si,sj,_=srcs[0]
        anchor=min(gcoords, key=lambda c: abs(c[0]-si)+abs(c[1]-sj))
        path,crossed=astar_soft(net,srcs,goalcells,anchor,cap=1200000)
        if path is None or any(not rippable(cn) for cn in crossed):
            nextq.append((net,srcs,gterm)); continue   # don't shatter big nets
        for cn in crossed: rip_net(cn)
        commit_path(path,netmap[net],width,net_cells.setdefault(net,set())); routed+=1
        for cn in crossed:                       # reroute the small nets we ripped
            nextq.extend(route_net_full(cn))
    print(f"  RRR round {rounds}: {len(queue)}->{len(nextq)} unresolved, routed={routed}", flush=True)
    if len(nextq)>=len(queue) and rounds>2:
        queue=nextq; break
    queue=nextq
failed=queue

print(f"FINAL: routed={routed} unrouted_edges={len(failed)} tracks={made_tracks} vias={made_vias}", flush=True)
for net,srcs,gterm in failed[:60]:
    print("  UNROUTED",net,(round(gterm[0],1),round(gterm[1],1)))

# ---- refill pours, then pour-validated GND stitching ------------------------
filler=pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
zone_by_layer={}
for z in board.Zones():
    for lid in z.GetLayerSet().Seq():
        zone_by_layer[lid]=z
def pour_at(x,y,layer):
    z=zone_by_layer.get(int(layer))
    if z is None: return False
    try:
        return z.HitTestFilledArea(layer, V(x,y), 0)
    except Exception:
        return False

gnd=netmap.get("GND")
stitch=0
if gnd:
    for i in range(gx(102),gx(168),40):   # ~4mm grid
        for j in range(gy(43),gy(148),40):
            x,y=wx(i),wy(j)
            if near_edge(x,y): continue
            # via only where BOTH pours really exist and the disk is clear
            if via_ok(i,j,"GND") and pour_at(x,y,pcbnew.F_Cu) and pour_at(x,y,pcbnew.B_Cu):
                add_via(x,y,gnd); stamp_via("GND",i,j); stitch+=1
print(f"GND stitch vias: {stitch}")

# ---- GND repair loop: authoritative DRC drives spoke routing ----------------
import subprocess, json as _json
KCLI=r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"

def find_via_at(px,py):
    for t in board.GetTracks():
        if t.GetClass()=="PCB_VIA":
            p=t.GetPosition()
            if abs(TOMM(p.x)-px)<0.02 and abs(TOMM(p.y)-py)<0.02:
                return t
    return None

pour_cache={}
def pour_cached(i,j,layer):
    k=(i,j,int(layer))
    if k not in pour_cache:
        pour_cache[k]=pour_at(wx(i),wy(j),layer)
    return pour_cache[k]

def route_gnd_to_pour(px,py):
    """short Dijkstra from a stranded GND pad to the nearest real pour copper."""
    si,sj=gx(px),gy(py)
    srcs=[]
    for l in (pcbnew.F_Cu,pcbnew.B_Cu):
        if occ[l].get((si,sj)) in ("GND",None):
            occ[l][(si,sj)]="GND"; srcs.append((si,sj,l))
    if not srcs: return False
    openq=[]; g={}; came={}
    for c in srcs: g[c]=0; heapq.heappush(openq,(0,)+c)
    expanded=0
    while openq:
        expanded+=1
        if expanded>40000: return False
        cost,i,j,l=heapq.heappop(openq)
        if cost>g.get((i,j,l),1e9): continue
        if cost>3 and pour_cached(i,j,l):          # reached live pour copper
            path=[]; cur=(i,j,l)
            while True:
                path.append(cur)
                if cur not in came: break
                cur=came[cur]
            path.reverse()
            commit_path(path,netmap["GND"],TRACE)
            return True
        for dx,dy in DIRS:
            ni,nj=i+dx,j+dy
            if not usable(l,ni,nj,"GND"): continue
            nc=cost+1; k=(ni,nj,l)
            if nc<g.get(k,1e9):
                g[k]=nc; came[k]=(i,j,l); heapq.heappush(openq,(nc,ni,nj,l))
        ol=pcbnew.B_Cu if l==pcbnew.F_Cu else pcbnew.F_Cu
        if usable(ol,i,j,"GND") and via_ok(i,j,"GND"):
            nc=cost+VIA_COST; k=(i,j,ol)
            if nc<g.get(k,1e9):
                g[k]=nc; came[k]=(i,j,l); heapq.heappush(openq,(nc,i,j,ol))
    return False

DRC_JSON=os.path.join(PROJ,"build","drc_route.json")
for rep in range(3):
    pour_cache.clear()
    filler.Fill(board.Zones())
    board.Save(PCB)
    subprocess.run([KCLI,"pcb","drc","--format","json","-o",DRC_JSON,PCB],
                   capture_output=True)
    d=_json.load(open(DRC_JSON, encoding="utf-8"))
    unc=d.get("unconnected_items",[])
    gnd_items={}
    for u in unc:
        for x in u.get("items",[]):
            desc=x.get("description","")
            if "[GND]" not in desc: continue
            pos=x.get("pos") or {}
            px,py=pos.get("x"),pos.get("y")
            if px is None: continue
            gnd_items[(round(px,2),round(py,2))]=desc
    print(f"GND repair iter {rep}: {len(unc)} total unconnected, {len(gnd_items)} GND items", flush=True)
    if not gnd_items: break
    fixed=0
    for (px,py),desc in gnd_items.items():
        if desc.startswith("Via"):
            if not (pour_at(px,py,pcbnew.F_Cu) and pour_at(px,py,pcbnew.B_Cu)):
                v=find_via_at(px,py)
                if v is not None: board.Remove(v); fixed+=1
        elif desc.startswith(("Pad","PTH")):
            if route_gnd_to_pour(px,py): fixed+=1
    print(f"  repaired {fixed}", flush=True)
    if fixed==0: break

filler.Fill(board.Zones())
board.Save(PCB)
print("saved", PCB)

# ---- authoritative final numbers from DRC -----------------------------------
subprocess.run([KCLI,"pcb","drc","--format","json","-o",DRC_JSON,PCB],
               capture_output=True)
d=_json.load(open(DRC_JSON, encoding="utf-8"))
from collections import Counter
sev=Counter(v.get("severity") for v in d.get("violations",[]))
typ=Counter(v["type"] for v in d.get("violations",[]))
print(f"FINAL DRC: unconnected={len(d.get('unconnected_items',[]))} "
      f"violations={len(d.get('violations',[]))} by_severity={dict(sev)}", flush=True)
for k,n in typ.most_common(): print(f"   {k}: {n}")
