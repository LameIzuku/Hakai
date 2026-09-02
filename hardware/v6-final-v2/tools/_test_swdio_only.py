#!/usr/bin/env python3
"""Test SWDIO-only jog; leave VBAT as baseline."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import Counter

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
BAK = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_gnd_closed_ok")
OUT = os.path.join(PROJ, "build", "drc_swdio_only.json")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
MM = pcbnew.FromMM
BC = int(pcbnew.B_Cu)
TOMM = lambda v: v / 1e6


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def near(a, b, eps=0.12):
    return abs(a - b) < eps


def add_seg(board, x1, y1, x2, y2, lay, net, w):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1, y1))
    t.SetEnd(V(x2, y2))
    t.SetLayer(lay)
    t.SetWidth(MM(w))
    t.SetNet(net)
    board.Add(t)


def main():
    shutil.copy2(BAK, PCB)
    board = pcbnew.LoadBoard(PCB)
    nets = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if n and n not in nets:
                nets[n] = p.GetNet()
    swdio = nets["SWDIO"]

    to_del = []
    for t in list(board.Tracks()):
        if t.GetClass() == "PCB_VIA" or int(t.GetLayer()) != BC:
            continue
        net = t.GetNetname()
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        if net == "SWDIO" and near(sx, 154.20) and near(ex, 154.20) and min(sy, ey) < 120 and max(sy, ey) > 130:
            to_del.append(t)
        if net == "SWDIO" and near(sy, 132.50) and near(ey, 132.50) and near(max(sx, ex), 154.20) and min(sx, ex) < 140:
            to_del.append(t)
    for t in to_del:
        board.Remove(t)

    # SWDIO west jog only - column clears vias
    add_seg(board, 154.2, 118.469, 154.2, 126.5, BC, swdio, 0.15)
    add_seg(board, 154.2, 126.5, 151.5, 126.5, BC, swdio, 0.15)
    add_seg(board, 151.5, 126.5, 151.5, 135.54, BC, swdio, 0.15)
    add_seg(board, 151.5, 135.54, 136.707, 135.54, BC, swdio, 0.15)

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(PCB)
    subprocess.run([KCLI, "pcb", "drc", "--format", "json", "--refill-zones", "-o", OUT, PCB], capture_output=True)
    d = json.load(open(OUT, encoding="utf-8"))
    unc = d.get("unconnected_items", [])
    viol = d.get("violations", [])
    errs = [v for v in viol if v.get("severity") == "error"]
    print(f"unc={len(unc)} err={len(errs)}")
    print("types", dict(Counter(v.get("type") for v in viol).most_common()))
    for v in errs:
        items = v.get("items", [])
        descs = [i.get("description", "")[:100] for i in items]
        print(f" ERR {v.get('type')}: {' | '.join(descs)}")


if __name__ == "__main__":
    main()
