#!/usr/bin/env python3
"""Close the last 9 GND pour fragments (one via each) and delete the two
dangling crumbs; refill; authoritative DRC."""
import os, math, subprocess, json
import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
MM = pcbnew.FromMM
def TOMM(v): return v/1e6
def V(x,y): return pcbnew.VECTOR2I(MM(x),MM(y))
VIA_D,VIA_DRILL,CLR=0.45,0.20,0.15
FC,BC=int(pcbnew.F_Cu),int(pcbnew.B_Cu)

board=pcbnew.LoadBoard(PCB)
gnd=None
for fp in board.GetFootprints():
    for p in fp.Pads():
        if p.GetNetname()=="GND": gnd=p.GetNet(); break
    if gnd: break

# ---- delete the 2 dangling crumbs -------------------------------------------
def near(a,b,x,y,eps=0.05): return abs(a-x)<eps and abs(b-y)<eps
rm=0
for t in list(board.GetTracks()):
    if t.GetClass()=="PCB_VIA": continue
    s,e=t.GetStart(),t.GetEnd()
    for px,py in ((TOMM(s.x),TOMM(s.y)),(TOMM(e.x),TOMM(e.y))):
        if (t.GetNetname()=="GND" and near(px,py,132.8783,140.6062)) or \
           (t.GetNetname()=="BTN_SIDE_BACK" and near(px,py,153.05,120.3)):
            board.Remove(t); rm+=1; break
print(f"dangling crumbs removed: {rm}", flush=True)
# restore ANT1-2 ground link westward into the B pour (keepout-clear)
_have=any(t.GetClass()!="PCB_VIA" and t.GetNetname()=="GND"
          and abs(TOMM(t.GetStart().x)-135.90)<0.02 and abs(TOMM(t.GetStart().y)-140.00)<0.02
          for t in board.GetTracks())
if not _have:
    _t=pcbnew.PCB_TRACK(board)
    _t.SetStart(V(135.90,140.00)); _t.SetEnd(V(133.60,140.00))
    _t.SetLayer(pcbnew.B_Cu); _t.SetWidth(MM(0.15)); _t.SetNet(gnd)
    board.Add(_t)
    print("ANT1-2 ground link restored", flush=True)
board.Save(PCB)
board=pcbnew.LoadBoard(PCB)
for fp in board.GetFootprints():
    for p in fp.Pads():
        if p.GetNetname()=="GND": gnd=p.GetNet(); break
    if gnd: break

# ---- geometric obstacle model for via placement ------------------------------
items=[]; holes=[]
for t in board.GetTracks():
    if t.GetClass()=="PCB_VIA":
        p=t.GetPosition()
        items.append((TOMM(p.x),TOMM(p.y),VIA_D/2,t.GetNetname(),"disk",None))
        holes.append((TOMM(p.x),TOMM(p.y),VIA_DRILL/2))
    else:
        s,e=t.GetStart(),t.GetEnd()
        items.append((TOMM(s.x),TOMM(s.y),TOMM(t.GetWidth())/2,t.GetNetname(),"seg",
                      (TOMM(e.x),TOMM(e.y))))
for fp in board.GetFootprints():
    for p in fp.Pads():
        q=p.GetPosition(); bb=p.GetBoundingBox()
        dr=p.GetDrillSize()
        if dr.x>0: holes.append((TOMM(q.x),TOMM(q.y),max(TOMM(dr.x),TOMM(dr.y))/2))
        if not (p.IsOnLayer(FC) or p.IsOnLayer(BC)): continue
        items.append((TOMM(q.x),TOMM(q.y),
                      math.hypot(TOMM(bb.GetWidth())/2,TOMM(bb.GetHeight())/2),
                      p.GetNetname() or "#NC","pad",None))
def seg_dist(px,py,x1,y1,x2,y2):
    dx,dy=x2-x1,y2-y1
    L2=dx*dx+dy*dy
    if L2==0: return math.hypot(px-x1,py-y1)
    t=max(0,min(1,((px-x1)*dx+(py-y1)*dy)/L2))
    return math.hypot(px-(x1+t*dx),py-(y1+t*dy))
def via_ok(x,y):
    for hx,hy,hr in holes:
        if math.hypot(x-hx,y-hy)<hr+VIA_DRILL/2+0.22: return False
    for it in items:
        ax,ay,r,net,kind,extra=it
        if kind=="seg":
            d=seg_dist(x,y,ax,ay,extra[0],extra[1])-VIA_D/2-r
        else:
            d=math.hypot(x-ax,y-ay)-VIA_D/2-r
        if net=="GND":
            if kind!="pad" and d< -0.5: pass
            if d<0.10 and kind=="pad": return False   # keep off GND pad copper a bit
            continue
        if d<CLR+0.02: return False
    return True

filler=pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
zl={}
for z in board.Zones():
    for lid in z.GetLayerSet().Seq(): zl[int(lid)]=z
def pour(x,y,lay):
    z=zl.get(int(lay))
    try: return z.HitTestFilledArea(lay,V(x,y),0)
    except Exception: return False

gvias=[(TOMM(t.GetPosition().x),TOMM(t.GetPosition().y)) for t in board.GetTracks()
       if t.GetClass()=="PCB_VIA" and t.GetNetname()=="GND"]
added=0
for z in board.Zones():
    for lid in z.GetLayerSet().Seq():
        polys=z.GetFilledPolysList(lid)
        areas=sorted(((polys.Outline(i).Area(),i) for i in range(polys.OutlineCount())),reverse=True)
        for a,oi in areas[1:]:
            if any(polys.Contains(V(vx,vy),oi) for vx,vy in gvias): continue
            bb=polys.Outline(oi).BBox()
            x0,y0=TOMM(bb.GetX()),TOMM(bb.GetY())
            x1,y1=x0+TOMM(bb.GetWidth()),y0+TOMM(bb.GetHeight())
            done=False
            yy=y0+0.25
            while yy<y1 and not done:
                xx=x0+0.25
                while xx<x1 and not done:
                    other=pcbnew.B_Cu if int(lid)==FC else pcbnew.F_Cu
                    if (polys.Contains(V(xx,yy),oi)
                            and pour(xx,yy,other)
                            and via_ok(xx,yy)):
                        v=pcbnew.PCB_VIA(board)
                        v.SetPosition(V(xx,yy)); v.SetDrill(MM(VIA_DRILL)); v.SetWidth(MM(VIA_D))
                        v.SetViaType(pcbnew.VIATYPE_THROUGH)
                        v.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu); v.SetNet(gnd)
                        board.Add(v)
                        gvias.append((xx,yy)); holes.append((xx,yy,VIA_DRILL/2))
                        added+=1; done=True
                    xx+=0.2
                yy+=0.2
print(f"fragment vias added: {added}", flush=True)

filler.Fill(board.Zones())
board.Save(PCB)
out=os.path.join(PROJ,"build","drc_final.json")
subprocess.run([KCLI,"pcb","drc","--format","json","-o",out,PCB],capture_output=True)
d=json.load(open(out,encoding="utf-8"))
from collections import Counter
sev=Counter(v.get("severity") for v in d.get("violations",[]))
typ=Counter(v["type"] for v in d.get("violations",[]))
print(f"FINAL DRC: unconnected={len(d.get('unconnected_items',[]))} "
      f"violations={len(d.get('violations',[]))} severities={dict(sev)}")
for k,n in typ.most_common(): print(f"   {k}: {n}")
for u in d.get("unconnected_items",[])[:12]:
    ds=[i.get("description","")[:44] for i in u.get("items",[])]
    print("  LEFT:"," | ".join(ds))
