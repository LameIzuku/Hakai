#!/usr/bin/env python3
"""Close C19 GND island on hakai_mouse_v6.

Result target: unconnected_items = 0 (no open GND).
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys
from collections import Counter
import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
BAK = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_pre_gnd_fjump")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
OUT = os.path.join(PROJ, "build", "drc_after_gnd_close.json")
MM = pcbnew.FromMM
BC = int(pcbnew.B_Cu)

def TOMM(v): return v / 1e6
def V(x, y): return pcbnew.VECTOR2I(MM(x), MM(y))
def near(a, b, eps=0.25): return abs(a - b) < eps
def add_seg(board, x1, y1, x2, y2, lay, net, w):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1, y1)); t.SetEnd(V(x2, y2)); t.SetLayer(lay)
    t.SetWidth(MM(w)); t.SetNet(net); board.Add(t)

def main():
    shutil.copy2(BAK, PCB)
    board = pcbnew.LoadBoard(PCB)
    nets = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if n and n not in nets:
                nets[n] = p.GetNet()
    gnd, swdclk, swdio, xc1, vbat_s = (
        nets["GND"], nets["SWDCLK"], nets["SWDIO"], nets["XC1"], nets["VBAT_SENSE"]
    )
    to_del = []
    for t in list(board.Tracks()):
        if t.GetClass() == "PCB_VIA":
            continue
        if int(t.GetLayer()) != BC:
            continue
        net = t.GetNetname()
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        if net == "SWDCLK" and (
            (near(sx, 140.049) and near(sy, 138.080) and near(ex, 159.662) and near(ey, 118.467))
            or (near(ex, 140.049) and near(ey, 138.080) and near(sx, 159.662) and near(sy, 118.467))
        ):
            to_del.append(t); continue
        if net == "SWDIO":
            if near(sx, 153.778, 0.08) and near(ex, 153.778, 0.08) and min(sy, ey) < 120 and max(sy, ey) > 121:
                to_del.append(t); continue
            if (near(sx, 153.778, 0.15) and near(sy, 123.0, 0.15) and near(ex, 136.707, 0.4) and near(ey, 135.54, 0.4)) or (
                near(ex, 153.778, 0.15) and near(ey, 123.0, 0.15) and near(sx, 136.707, 0.4) and near(sy, 135.54, 0.4)
            ):
                to_del.append(t); continue
        if net == "XC1":
            if near(sy, 119.546, 0.05) and near(ey, 119.546, 0.05) and max(sx, ex) > 152 and min(sx, ex) < 154:
                to_del.append(t); continue
            if near(sx, 153.214, 0.05) and near(ex, 153.214, 0.05) and min(sy, ey) < 118.5 and max(sy, ey) > 118.5:
                to_del.append(t); continue
            if near(sy, 117.746, 0.05) and near(ey, 117.746, 0.05) and min(sx, ex) > 152.5 and max(sx, ex) < 156.5:
                to_del.append(t); continue
        if net == "VBAT_SENSE":
            if (near(sx, 153.329, 0.2) and near(sy, 116.962, 0.2) and near(ex, 146.5, 0.5) and near(ey, 123.5, 0.5)) or (
                near(ex, 153.329, 0.2) and near(ey, 116.962, 0.2) and near(sx, 146.5, 0.5) and near(sy, 123.5, 0.5)
            ):
                to_del.append(t); continue
            if (near(sx, 146.5, 0.5) and near(sy, 123.5, 0.5) and near(ex, 135.380, 0.5) and near(ey, 134.911, 0.5)) or (
                near(ex, 146.5, 0.5) and near(ey, 123.5, 0.5) and near(sx, 135.380, 0.5) and near(sy, 134.911, 0.5)
            ):
                to_del.append(t); continue
            if (near(sx, 135.380, 0.2) and near(sy, 134.911, 0.2) and near(ex, 129.203, 0.2) and near(ey, 134.911, 0.2)) or (
                near(ex, 135.380, 0.2) and near(ey, 134.911, 0.2) and near(sx, 129.203, 0.2) and near(sy, 134.911, 0.2)
            ):
                to_del.append(t); continue
            if (near(sx, 155.920, 0.1) and near(sy, 116.962, 0.1) and near(ex, 153.329, 0.1) and near(ey, 116.962, 0.1)) or (
                near(ex, 155.920, 0.1) and near(ey, 116.962, 0.1) and near(sx, 153.329, 0.1) and near(sy, 116.962, 0.1)
            ):
                to_del.append(t); continue
    for t in to_del:
        board.Remove(t)
    print("removed", len(to_del))

    # VBAT: south from existing T-junction to via (129.203,134.911)
    add_seg(board, 155.920, 116.962, 155.920, 134.00, BC, vbat_s, 0.15)
    add_seg(board, 155.920, 134.00, 129.203, 134.00, BC, vbat_s, 0.15)
    add_seg(board, 129.203, 134.00, 129.203, 134.911, BC, vbat_s, 0.15)
    # XC1 short L (opens corridor at x=152.5); original NE kept
    add_seg(board, 151.413, 119.546, 152.05, 119.546, BC, xc1, 0.15)
    add_seg(board, 152.05, 119.546, 152.05, 117.746, BC, xc1, 0.15)
    add_seg(board, 152.05, 117.746, 155.40, 117.746, BC, xc1, 0.15)
    add_seg(board, 155.40, 117.746, 155.623, 117.746, BC, xc1, 0.12)
    # SWDIO rejoin west bus
    add_seg(board, 153.778, 118.469, 154.20, 118.469, BC, swdio, 0.15)
    add_seg(board, 154.20, 118.469, 154.20, 132.50, BC, swdio, 0.15)
    add_seg(board, 154.20, 132.50, 128.00, 132.50, BC, swdio, 0.15)
    add_seg(board, 128.00, 132.50, 128.00, 135.540, BC, swdio, 0.15)
    add_seg(board, 128.00, 135.540, 136.707, 135.540, BC, swdio, 0.15)
    # SWDCLK rejoin west bus
    add_seg(board, 159.662, 118.467, 158.40, 118.467, BC, swdclk, 0.15)
    add_seg(board, 158.40, 118.467, 158.40, 138.080, BC, swdclk, 0.15)
    add_seg(board, 158.40, 138.080, 140.049, 138.080, BC, swdclk, 0.15)
    # GND close: VIP south to pour via
    add_seg(board, 152.50, 118.52, 152.50, 126.00, BC, gnd, 0.12)
    add_seg(board, 152.50, 126.00, 153.50, 126.00, BC, gnd, 0.12)

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(PCB)
    print("Saved", PCB)

    subprocess.run([KCLI, "pcb", "drc", "--format", "json", "--refill-zones", "-o", OUT, PCB], capture_output=True)
    d = json.load(open(OUT, encoding="utf-8"))
    unc = d.get("unconnected_items", [])
    viol = d.get("violations", [])
    print(f"DRC unconnected={len(unc)} viol={len(viol)}")
    print("types", dict(Counter(v.get("type") for v in viol).most_common()))
    for v in viol:
        if v.get("severity") == "error":
            items = v.get("items", [])
            descs = [i.get("description", "")[:90] for i in items]
            print(f"  ERROR {v.get('type')}: {' | '.join(descs)}")
    print("GND_CLOSED" if len(unc) == 0 else "GND_STILL_OPEN")
    return 0 if len(unc) == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
