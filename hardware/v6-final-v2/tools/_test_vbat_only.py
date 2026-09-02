#!/usr/bin/env python3
"""Test VBAT-only west U-jog around MH; leave SWDIO as baseline."""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from collections import Counter

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
BAK = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_gnd_closed_ok")
OUT = os.path.join(PROJ, "build", "drc_vbat_only.json")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
MM = pcbnew.FromMM
BC = int(pcbnew.B_Cu)
TOMM = lambda v: v / 1e6
MH = (155.0, 130.0)


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
    vbat = nets["VBAT_SENSE"]

    to_del = []
    for t in list(board.Tracks()):
        if t.GetClass() == "PCB_VIA" or int(t.GetLayer()) != BC:
            continue
        net = t.GetNetname()
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        if net == "VBAT_SENSE" and near(sx, 155.920) and near(ex, 155.920) and min(sy, ey) < 120 and max(sy, ey) > 130:
            to_del.append(t)
        if net == "VBAT_SENSE" and near(sy, 134.00) and near(ey, 134.00) and near(max(sx, ex), 155.920) and min(sx, ex) < 140:
            to_del.append(t)
    for t in to_del:
        board.Remove(t)

    # U-jog west of MH: approach, west, south past MH, east back? then west to via
    # Try column 151.5, gates 126.5 / 133.5, then to via stub
    path = [
        (155.920, 116.962, 155.920, 126.50),
        (155.920, 126.50, 151.50, 126.50),
        (151.50, 126.50, 151.50, 133.50),
        (151.50, 133.50, 155.920, 133.50),  # east back? may hit MH
        # better stay west to via:
    ]
    # pure west column to y=134 then to 129.203
    path = [
        (155.920, 116.962, 155.920, 126.50),
        (155.920, 126.50, 151.50, 126.50),
        (151.50, 126.50, 151.50, 134.00),
        (151.50, 134.00, 129.203, 134.00),
    ]
    for a, b, c, d in path:
        add_seg(board, a, b, c, d, BC, vbat, 0.15)
    print("path", path)

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
        p = items[0].get("pos", {}) if items else {}
        print(f" ERR {v.get('type')}: {' | '.join(descs)} @({p.get('x')},{p.get('y')})")


if __name__ == "__main__":
    main()
