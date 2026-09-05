#!/usr/bin/env python3
"""Close remaining non-GND ratsnest edges on the freerouted v6 board.

Reads the authoritative DRC unconnected list, then A*-routes each broken edge
over an occupancy grid built from the REAL board geometry (diagonal tracks
included). GND edges are left to the pour/spoke repair in fr_import.py.
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
PWR_NETS={"VBUS","VSYS","VBAT","1V9","LDO_IN"}
def width_of(net):
    if net in FINE_NETS: return 0.10
    if net in PWR_NETS: return 0.30
    return 0.15
def clr_of(net):
    return 0.075 if net in FINE_NETS else CLR

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

G=0.05                       # finer grid than the first router: exact-ish geometry
X0,Y0=99.0,39.0
NX,NY=int(72/G)+1,int(112/G)+1
def gxi(x): return int(round((x-X0)/G))
def gyi(y): return int(round((y-Y0)/G))
def wxi(i): return round(X0+i*G,4)
def wyi(j): return round(Y0+j*G,4)

board=pcbnew.LoadBoard(PCB)
FC,BC=int(pcbnew.F_Cu),int(pcbnew.B_Cu)
netobj={}

def build_occ():
    occ={FC:{},BC:{}}
    def stamp_disk(lay,x,y,r,net):
        for i in range(gxi(x-r),gxi(x+r)+1):
            for j in range(gyi(y-r),gyi(y+r)+1):
                if 0<=i<NX and 0<=j<NY and (wxi(i)-x)**2+(wyi(j)-y)**2<=r*r:
                    occ[lay][(i,j)]=net
    for t in board.GetTracks():
        net=t.GetNetname()
        if net: netobj[net]=t.GetNet()
        if t.GetClass()=="PCB_VIA":
            p=t.GetPosition()
            for lay in (FC,BC):
                stamp_disk(lay,TOMM(p.x),TOMM(p.y),VIA_D/2,net)
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
    for i in range(0,NX):
        x=wxi(i)
        for j in range(0,NY):
            if not inside_poly(x,wyi(j)) or near_edge(x,wyi(j)):
                occ[FC][(i,j)]="#BLK"; occ[BC][(i,j)]="#BLK"
    return occ

def usable(occ,lay,i,j,net,rad_cells):
    """cell + halo of rad_cells must be free-or-own-net."""
    for di in range(-rad_cells,rad_cells+1):
        for dj in range(-rad_cells,rad_cells+1):
            o=occ[lay].get((i+di,j+dj))
            if o is not None and o!=net: return False
            if not(0<=i+di<NX and 0<=j+dj<NY): return False
    return True

def route_edge(occ,net,p1,p2):
    w=width_of(net); c=clr_of(net)
    rad=int(math.ceil((w/2+c)/G))
    vrad=int(math.ceil((VIA_D/2+c)/G))
    si,sj=gxi(p1[0]),gyi(p1[1])
    ti,tj=gxi(p2[0]),gyi(p2[1])
    OTHER={FC:BC,BC:FC}
    srcs=[(si,sj,l) for l in (FC,BC) if occ[l].get((si,sj))==net]
    goals={(i,j) for i in range(ti-2,ti+3) for j in range(tj-2,tj+3)}
    if not srcs: return False
    def h(i,j): return abs(i-ti)+abs(j-tj)
    openq=[]; g={}; came={}
    for csrc in srcs: g[csrc]=0; heapq.heappush(openq,(h(csrc[0],csrc[1]),0)+csrc)
    n=0
    while openq:
        n+=1
        if n>900000: return False
        f,cost,i,j,l=heapq.heappop(openq)
        if cost>g.get((i,j,l),1e9): continue
        if (i,j) in goals and occ[l].get((i,j))==net:
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
                    v=pcbnew.PCB_VIA(board)
                    v.SetPosition(V(wxi(a[0]),wyi(a[1])))
                    v.SetDrill(MM(VIA_DRILL)); v.SetWidth(MM(VIA_D))
                    v.SetViaType(pcbnew.VIATYPE_THROUGH)
                    v.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu); v.SetNet(netobj[net])
                    board.Add(v)
                    for lay in (FC,BC):
                        for di in range(-vrad,vrad+1):
                            for dj in range(-vrad,vrad+1):
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
                t.SetLayer(l0); t.SetWidth(MM(w)); t.SetNet(netobj[net])
                board.Add(t)
                for kk in range(rs,k+1):
                    ci,cj,_=path[kk]
                    for ddi in range(-rad,rad+1):
                        for ddj in range(-rad,rad+1):
                            occ[l0][(ci+ddi,cj+ddj)]=net
            return True
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            ni,nj=i+dx,j+dy
            if not usable(occ,l,ni,nj,net,rad): continue
            nc=cost+1; kk=(ni,nj,l)
            if nc<g.get(kk,1e9):
                g[kk]=nc; came[kk]=(i,j,l); heapq.heappush(openq,(nc+h(ni,nj),nc,ni,nj,l))
        ol=OTHER[l]
        if usable(occ,ol,i,j,net,rad) and usable(occ,l,i,j,net,vrad) and usable(occ,ol,i,j,net,vrad):
            nc=cost+30; kk=(i,j,ol)
            if nc<g.get(kk,1e9):
                g[kk]=nc; came[kk]=(i,j,l); heapq.heappush(openq,(nc+h(i,j),nc,i,j,ol))
    return False

import re
for it in range(3):
    out=os.path.join(PROJ,"build","drc_finish.json")
    subprocess.run([KCLI,"pcb","drc","--format","json","-o",out,PCB],capture_output=True)
    d=json.load(open(out,encoding="utf-8"))
    edges=[]
    for u in d.get("unconnected_items",[]):
        its=u.get("items",[])
        if len(its)!=2: continue
        descs=[x.get("description","") for x in its]
        if any("[GND]" in dd for dd in descs): continue
        m=re.search(r"\[(\S+)\]",descs[0])
        if not m: continue
        net=m.group(1)
        ps=[(x["pos"]["x"],x["pos"]["y"]) for x in its if x.get("pos")]
        if len(ps)==2: edges.append((net,ps[0],ps[1]))
    print(f"finish iter {it}: {len(edges)} non-GND edges", flush=True)
    if not edges: break
    occ=build_occ()
    done=0
    for net,p1,p2 in edges:
        if route_edge(occ,net,p1,p2): done+=1
        elif route_edge(occ,net,p2,p1): done+=1
    print(f"  closed {done}", flush=True)
    board.Save(PCB)
    if done==0: break

filler=pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
board.Save(PCB)
out=os.path.join(PROJ,"build","drc_finish.json")
subprocess.run([KCLI,"pcb","drc","--format","json","-o",out,PCB],capture_output=True)
d=json.load(open(out,encoding="utf-8"))
from collections import Counter
typ=Counter(v["type"] for v in d.get("violations",[]))
print(f"FINISH DRC: unconnected={len(d.get('unconnected_items',[]))} violations={len(d.get('violations',[]))}")
for k,n in typ.most_common(): print(f"   {k}: {n}")
