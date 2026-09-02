#!/usr/bin/env python3
"""Import the Freerouting SES back into the v6 board, refill pours, add
pour-validated GND stitching vias, bump the title-block rev, save, and DRC.

Run with KiCad's bundled python AFTER freerouting wrote build/hakai_v6.ses.
"""
import os, math, subprocess, json
import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
SES = os.path.join(PROJ, "build", "hakai_v6.ses")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
MM = pcbnew.FromMM
def TOMM(v): return v/1e6
def V(x,y): return pcbnew.VECTOR2I(MM(x),MM(y))

VIA_D, VIA_DRILL = 0.45, 0.20
CLR = 0.15
STITCH_R = VIA_D/2 + 0.30           # keep-clear radius around a stitch via

OUT = [(104,40),(123,40),(123,78),(147,78),(147,40),(166,40),(170,44),(170,88),
       (166,96),(166,144),(160,150),(110,150),(104,144),(104,96),(100,88),(100,44)]
def inside_poly(px,py,poly=OUT):
    n=len(poly); c=False; j=n-1
    for i in range(n):
        xi,yi=poly[i]; xj,yj=poly[j]
        if ((yi>py)!=(yj>py)) and (px < (xj-xi)*(py-yi)/(yj-yi)+xi): c=not c
        j=i
    return c
def near_edge(x,y,ko=0.45):
    if not inside_poly(x,y): return True
    for ox,oy in ((ko,0),(-ko,0),(0,ko),(0,-ko)):
        if not inside_poly(x+ox,y+oy): return True
    return False

board = pcbnew.LoadBoard(PCB)
ok = pcbnew.ImportSpecctraSES(board, SES)
print("SES import:", ok)

# refill pours so connectivity + stitch validation see real copper
filler = pcbnew.ZONE_FILLER(board)
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

# collect copper obstacles for stitch-via placement (geometric, no grid)
obstacles=[]     # (x,y,keepout_radius) approximation per item
for t in board.GetTracks():
    cls=t.GetClass()
    if cls=="PCB_VIA":
        p=t.GetPosition()
        if t.GetNetname()!="GND":
            obstacles.append((TOMM(p.x),TOMM(p.y),VIA_D/2+0.10))
        else:
            obstacles.append((TOMM(p.x),TOMM(p.y),VIA_D/2+0.05))  # spacing GND-GND
    else:
        s,e=t.GetStart(),t.GetEnd()
        obstacles.append(("seg",TOMM(s.x),TOMM(s.y),TOMM(e.x),TOMM(e.y),
                          TOMM(t.GetWidth())/2, t.GetNetname()))
pads=[]
for fp in board.GetFootprints():
    for p in fp.Pads():
        pos=p.GetPosition(); sz=p.GetSize()
        # corner distance, not max-half: rectangular pads reach further diagonally
        r=math.hypot(TOMM(sz.x)/2,TOMM(sz.y)/2)
        dr=p.GetDrillSize().x
        pads.append((TOMM(pos.x),TOMM(pos.y), r, TOMM(dr)/2 if dr>0 else 0,
                     p.GetNetname()))

def seg_dist(px,py,x1,y1,x2,y2):
    dx,dy=x2-x1,y2-y1
    L2=dx*dx+dy*dy
    if L2==0: return math.hypot(px-x1,py-y1)
    t=max(0,min(1,((px-x1)*dx+(py-y1)*dy)/L2))
    return math.hypot(px-(x1+t*dx),py-(y1+t*dy))

M=0.03   # safety margin over exact rule distances
def stitch_ok(x,y):
    for ob in obstacles:
        if ob[0]=="seg":
            _,x1,y1,x2,y2,hw,net=ob
            dmin=seg_dist(x,y,x1,y1,x2,y2)
            if net=="GND":
                if dmin < hw+VIA_D/2+0.05: return False
            else:
                # copper-copper AND via-hole-to-copper
                if dmin < hw+max(VIA_D/2+CLR, VIA_DRILL/2+0.20)+M: return False
        else:
            ox,oy,r=ob
            if math.hypot(x-ox,y-oy) < r+VIA_D/2+M: return False
    for ox,oy,r,hr,net in pads:
        d=math.hypot(x-ox,y-oy)
        if net=="GND":
            if d < r+VIA_D/2+0.05: return False
        else:
            if d < r+max(VIA_D/2+CLR, VIA_DRILL/2+0.20)+M: return False
        if hr>0 and d < hr+VIA_DRILL/2+0.20+M: return False
    return True

gnd=None
for fp in board.GetFootprints():
    for p in fp.Pads():
        if p.GetNetname()=="GND": gnd=p.GetNet(); break
    if gnd: break

stitch=0
placed=[]
if gnd:
    step=4.0
    xs=[100+step*i for i in range(int(72/step))]
    ys=[40+step*j for j in range(int(112/step))]
    for x in xs:
        for y in ys:
            if near_edge(x,y): continue
            if not (pour_at(x,y,pcbnew.F_Cu) and pour_at(x,y,pcbnew.B_Cu)): continue
            if not stitch_ok(x,y): continue
            if any(math.hypot(x-a,y-b)<2.5 for a,b in placed): continue
            v=pcbnew.PCB_VIA(board)
            v.SetPosition(V(x,y)); v.SetDrill(MM(VIA_DRILL)); v.SetWidth(MM(VIA_D))
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu); v.SetNet(gnd)
            board.Add(v); placed.append((x,y)); stitch+=1
print("GND stitch vias:", stitch)

# ---- GND repair: reconnect stranded GND items via short spokes --------------
import heapq
G=0.1
X0,Y0=99.0,39.0
NX,NY=int(72/G)+1,int(112/G)+1
def gxi(x): return int(round((x-X0)/G))
def gyi(y): return int(round((y-Y0)/G))
def wxi(i): return round(X0+i*G,3)
def wyi(j): return round(Y0+j*G,3)

def build_occ():
    """occupancy grid from REAL board geometry (tracks incl. diagonals, vias, pads)."""
    occ={int(pcbnew.F_Cu):{}, int(pcbnew.B_Cu):{}}
    def stamp_disk(lay,x,y,r,net):
        for i in range(gxi(x-r),gxi(x+r)+1):
            for j in range(gyi(y-r),gyi(y+r)+1):
                if 0<=i<NX and 0<=j<NY and (wxi(i)-x)**2+(wyi(j)-y)**2<=r*r:
                    occ[lay][(i,j)]=net
    for t in board.GetTracks():
        if t.GetClass()=="PCB_VIA":
            p=t.GetPosition()
            r=VIA_D/2+CLR+0.05
            for lay in (int(pcbnew.F_Cu),int(pcbnew.B_Cu)):
                stamp_disk(lay,TOMM(p.x),TOMM(p.y),r,t.GetNetname())
        else:
            s,e=t.GetStart(),t.GetEnd()
            x1,y1,x2,y2=TOMM(s.x),TOMM(s.y),TOMM(e.x),TOMM(e.y)
            hw=TOMM(t.GetWidth())/2+CLR+0.05
            lay=int(t.GetLayer()); net=t.GetNetname()
            for i in range(gxi(min(x1,x2)-hw),gxi(max(x1,x2)+hw)+1):
                for j in range(gyi(min(y1,y2)-hw),gyi(max(y1,y2)+hw)+1):
                    if 0<=i<NX and 0<=j<NY and seg_dist(wxi(i),wyi(j),x1,y1,x2,y2)<=hw:
                        occ[lay][(i,j)]=net
    for fp in board.GetFootprints():
        for p in fp.Pads():
            pos=p.GetPosition(); sz=p.GetSize()
            x,y=TOMM(pos.x),TOMM(pos.y)
            hx,hy=TOMM(sz.x)/2+CLR+0.05,TOMM(sz.y)/2+CLR+0.05
            net=p.GetNetname() or "#NC"
            for lay in (int(pcbnew.F_Cu),int(pcbnew.B_Cu)):
                if not p.IsOnLayer(lay): continue
                for i in range(gxi(x-hx),gxi(x+hx)+1):
                    for j in range(gyi(y-hy),gyi(y+hy)+1):
                        if 0<=i<NX and 0<=j<NY: occ[lay][(i,j)]=net
    # outside board
    for i in range(NX):
        for j in range(NY):
            if not inside_poly(wxi(i),wyi(j)) or near_edge(wxi(i),wyi(j),0.30):
                occ[int(pcbnew.F_Cu)][(i,j)]="#BLK"; occ[int(pcbnew.B_Cu)][(i,j)]="#BLK"
    return occ

def gnd_spoke(occ,px,py):
    """Dijkstra from stranded GND item to live pour; commits track segments."""
    OTHER={int(pcbnew.F_Cu):int(pcbnew.B_Cu), int(pcbnew.B_Cu):int(pcbnew.F_Cu)}
    si,sj=gxi(px),gyi(py)
    srcs=[]
    for l in OTHER:
        if occ[l].get((si,sj)) in ("GND",None):
            occ[l][(si,sj)]="GND"; srcs.append((si,sj,l))
    if not srcs: return False
    pc={}
    def pour_c(i,j,l):
        k=(i,j,l)
        if k not in pc: pc[k]=pour_at(wxi(i),wyi(j),l)
        return pc[k]
    openq=[]; g={}; came={}
    for c in srcs: g[c]=0; heapq.heappush(openq,(0,)+c)
    n=0
    while openq:
        n+=1
        if n>60000: return False
        cost,i,j,l=heapq.heappop(openq)
        if cost>g.get((i,j,l),1e9): continue
        if cost>3 and pour_c(i,j,l):
            path=[]; cur=(i,j,l)
            while True:
                path.append(cur)
                if cur not in came: break
                cur=came[cur]
            path.reverse()
            # commit: straight runs + vias
            k=0
            gndnet=gnd
            while k<len(path)-1:
                a=path[k]; b=path[k+1]
                if (a[0],a[1])==(b[0],b[1]) and a[2]!=b[2]:
                    v=pcbnew.PCB_VIA(board)
                    v.SetPosition(V(wxi(a[0]),wyi(a[1])))
                    v.SetDrill(MM(VIA_DRILL)); v.SetWidth(MM(VIA_D))
                    v.SetViaType(pcbnew.VIATYPE_THROUGH)
                    v.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu); v.SetNet(gndnet)
                    board.Add(v); k+=1; continue
                rs=k; di,dj=b[0]-a[0],b[1]-a[1]; l0=a[2]
                while k<len(path)-1:
                    c1,c2=path[k],path[k+1]
                    if c1[2]!=l0 or c2[2]!=l0: break
                    if (c2[0]-c1[0],c2[1]-c1[1])!=(di,dj): break
                    k+=1
                t=pcbnew.PCB_TRACK(board)
                t.SetStart(V(wxi(path[rs][0]),wyi(path[rs][1])))
                t.SetEnd(V(wxi(path[k][0]),wyi(path[k][1])))
                t.SetLayer(l0); t.SetWidth(MM(0.15)); t.SetNet(gndnet)
                board.Add(t)
            for c in path: occ[c[2]][(c[0],c[1])]="GND"
            return True
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            ni,nj=i+dx,j+dy
            if not(0<=ni<NX and 0<=nj<NY): continue
            if occ[l].get((ni,nj)) not in ("GND",None): continue
            nc=cost+1; kk=(ni,nj,l)
            if nc<g.get(kk,1e9):
                g[kk]=nc; came[kk]=(i,j,l); heapq.heappush(openq,(nc,ni,nj,l))
        ol=OTHER[l]
        if occ[ol].get((i,j)) in ("GND",None) and stitch_ok(wxi(i),wyi(j)):
            nc=cost+12; kk=(i,j,ol)
            if nc<g.get(kk,1e9):
                g[kk]=nc; came[kk]=(i,j,l); heapq.heappush(openq,(nc,i,j,ol))
    return False

for rep in range(3):
    filler.Fill(board.Zones())
    board.Save(PCB)
    out=os.path.join(PROJ,"build","drc_fr.json")
    subprocess.run([KCLI,"pcb","drc","--format","json","-o",out,PCB],capture_output=True)
    d=json.load(open(out,encoding="utf-8"))
    gnd_pts={}
    for u in d.get("unconnected_items",[]):
        for x in u.get("items",[]):
            desc=x.get("description","")
            if "[GND]" not in desc or desc.startswith("Zone"): continue
            pos=x.get("pos") or {}
            if pos.get("x") is None: continue
            gnd_pts[(round(pos["x"],2),round(pos["y"],2))]=desc
    print(f"GND repair iter {rep}: unconnected={len(d.get('unconnected_items',[]))} gnd_pts={len(gnd_pts)}",flush=True)
    if not gnd_pts: break
    occ=build_occ()
    fixed=0
    for (px,py),desc in gnd_pts.items():
        if gnd_spoke(occ,px,py): fixed+=1
    print(f"  spokes added: {fixed}",flush=True)
    if fixed==0: break

# rev 6.0 title block
tb=board.GetTitleBlock()
tb.SetRevision("6.0")
tb.SetTitle("HAKAI Wireless Gaming Mouse - Rev 6.0")
board.SetTitleBlock(tb)

filler.Fill(board.Zones())
board.Save(PCB)
print("saved", PCB)

# authoritative DRC
out=os.path.join(PROJ,"build","drc_fr.json")
subprocess.run([KCLI,"pcb","drc","--format","json","-o",out,PCB],capture_output=True)
d=json.load(open(out,encoding="utf-8"))
from collections import Counter
sev=Counter(v.get("severity") for v in d.get("violations",[]))
typ=Counter(v["type"] for v in d.get("violations",[]))
print(f"DRC: unconnected={len(d.get('unconnected_items',[]))} "
      f"violations={len(d.get('violations',[]))} severities={dict(sev)}")
for k,n in typ.most_common(): print(f"   {k}: {n}")
