import pcbnew, math, heapq
board=pcbnew.LoadBoard(r"C:\Users\kavya\Documents\hakai\claud\final v2 (v6)\hakai_mouse_v6.kicad_pcb.bak_pre_gnd_fjump")
# copy to temp logic - load bak path as board file
board=pcbnew.LoadBoard(r"C:\Users\kavya\Documents\hakai\claud\final v2 (v6)\hakai_mouse_v6.kicad_pcb")
import shutil
shutil.copy2(r"C:\Users\kavya\Documents\hakai\claud\final v2 (v6)\hakai_mouse_v6.kicad_pcb.bak_pre_gnd_fjump",
             r"C:\Users\kavya\Documents\hakai\claud\final v2 (v6)\hakai_mouse_v6.kicad_pcb")
board=pcbnew.LoadBoard(r"C:\Users\kavya\Documents\hakai\claud\final v2 (v6)\hakai_mouse_v6.kicad_pcb")
MM=lambda v:v/1e6
to_del=[]
for t in list(board.GetTracks()):
    if t.GetClass()=='PCB_VIA': continue
    if t.GetLayer()!=pcbnew.F_Cu: continue
    s,e=t.GetStart(),t.GetEnd()
    sx,sy,ex,ey=MM(s.x),MM(s.y),MM(e.x),MM(e.y)
    net=t.GetNetname()
    if net=='XC2' and abs(sx-150.9945)<0.1 and abs(sy-117.9745)<0.1:
        to_del.append(t)
    if net=='XC1' and abs(sx-150.30)<0.05 and abs(ex-150.30)<0.05 and min(sy,ey)<116:
        to_del.append(t)
for t in to_del: board.Remove(t)
print('removed',len(to_del))
obs=[]
for t in board.GetTracks():
    if t.GetClass()=='PCB_VIA':
        if t.GetNetname()=='GND': continue
        p=t.GetPosition()
        try: r=MM(t.GetWidth(pcbnew.F_Cu))/2
        except: r=0.225
        obs.append((MM(p.x),MM(p.y),r))
    elif t.GetLayer()==pcbnew.F_Cu and t.GetNetname()!='GND':
        s,e=t.GetStart(),t.GetEnd()
        obs.append((MM(s.x),MM(s.y),MM(e.x),MM(e.y),MM(t.GetWidth())/2))
for fp in board.GetFootprints():
    for p in fp.Pads():
        if p.GetNetname() in ('GND',''): continue
        if not p.IsOnLayer(pcbnew.F_Cu): continue
        pos=p.GetPosition(); x,y=MM(pos.x),MM(pos.y)
        if not (147<=x<=155 and 116<=y<=121): continue
        r=max(MM(p.GetSize().x),MM(p.GetSize().y))/2
        obs.append((x,y,r))

def seg_dist(px,py,x1,y1,x2,y2):
    dx,dy=x2-x1,y2-y1; L2=dx*dx+dy*dy
    if L2<1e-12: return math.hypot(px-x1,py-y1)
    t=max(0,min(1,((px-x1)*dx+(py-y1)*dy)/L2))
    return math.hypot(px-(x1+t*dx),py-(y1+t*dy))
need=0.15+0.05
def free(x,y):
    for o in obs:
        if len(o)==3:
            if math.hypot(x-o[0],y-o[1])<o[2]+need: return False
        else:
            if seg_dist(x,y,o[0],o[1],o[2],o[3])<o[4]+need: return False
    return True
frees=[round(i/10,1) for i in range(1490,1526) if free(i/10,118.52)]
print('free@118.52', frees)
# check continuous
ok=all(free(x,118.52) for x in [i/20 for i in range(1490*2,1525*2)])
print('continuous jump free', ok, 'mid samples', free(150.3,118.52), free(150.0,118.52), free(150.5,118.52))
