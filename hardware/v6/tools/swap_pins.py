#!/usr/bin/env python3
"""Board-side v6.0 pin swap: reassign U4 pad nets to match the regenerated
netlist (BTN_RIGHT->W24, BTN_SIDE_BACK->U24, VBAT_EN->AD22; K2/L1/B13 -> NC),
rip the now-orphaned west-face stubs, save."""
import os, re
import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
NET = os.path.join(PROJ, "build", "net.net")
MM = pcbnew.FromMM
def TOMM(v): return v/1e6

# exact net names per pad from the fresh netlist
text=open(NET,encoding="utf-8").read()
def parse_sexp(s):
    toks=re.findall(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+',s)
    stack=[[]]
    for t in toks:
        if t=='(': stack.append([])
        elif t==')':
            d=stack.pop(); stack[-1].append(d)
        else:
            if t.startswith('"') and t.endswith('"') and len(t)>=2: t=t[1:-1]
            stack[-1].append(t)
    return stack[0]
def find_all(tree,tag):
    out=[]
    if isinstance(tree,list):
        if tree and tree[0]==tag: out.append(tree)
        for el in tree: out.extend(find_all(el,tag))
    return out
def child(tree,tag):
    for el in tree:
        if isinstance(el,list) and el and el[0]==tag: return el
    return None
root=parse_sexp(text)
padnet={}
for n in find_all(root,'net'):
    name=child(n,'name')[1].lstrip('/')
    for nd in find_all(n,'node'):
        padnet[(child(nd,'ref')[1],child(nd,'pin')[1])]=name

SWAP=["K2","L1","B13","W24","U24","AD22"]
board=pcbnew.LoadBoard(PCB)
for pad in SWAP:
    want=padnet[("U4",pad)]
    ni=board.FindNet(want)
    if ni is None:
        ni=pcbnew.NETINFO_ITEM(board,want)
        board.Add(ni)
    for fp in board.GetFootprints():
        if fp.GetReference()!="U4": continue
        for p in fp.Pads():
            if p.GetNumber()==pad:
                old=p.GetNetname()
                p.SetNet(ni)
                print(f"  U4-{pad}: '{old[:38]}' -> '{want[:38]}'")

# rip orphaned west-face stubs (K2 + B13 verticals laid by earlier passes)
def near(a,b,x,y,eps=0.03): return abs(a-x)<eps and abs(b-y)<eps
rm=0
for t in list(board.GetTracks()):
    if t.GetClass()=="PCB_VIA": continue
    s,e=t.GetStart(),t.GetEnd()
    sx,sy,ex,ey=TOMM(s.x),TOMM(s.y),TOMM(e.x),TOMM(e.y)
    if t.GetNetname()=="BTN_RIGHT" and (near(sx,sy,154.25,104.50) or near(ex,ey,154.25,104.50)):
        board.Remove(t); rm+=1
    elif t.GetNetname()=="VBAT_EN" and (near(sx,sy,157.00,102.25) or near(ex,ey,157.00,102.25)):
        board.Remove(t); rm+=1
print(f"orphaned stubs ripped: {rm}")
board.Save(PCB)
print("saved")
