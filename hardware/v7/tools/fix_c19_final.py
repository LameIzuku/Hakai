#!/usr/bin/env python3
"""C19-2 GND fix on main hakai_mouse_v6.kicad_pcb (not backup).

Result (KiCad 10 DRC): hard error-severity = 0 (silk warnings only);
unconnected count matches C12-fixed baseline (1 zone-corner report).

Changes:
  1) SWDIO B: south dogleg so XC1 can L-route
  2) XC1 B: L-east off C19 pad2 (was diagonal through pad)
  3) VBAT_SENSE B: diagonal bowed SW (was pocketing C19)
  4) GND via-in-pad on C19-2 @ (152.50, 118.52)

Usage:
  "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" tools/fix_c19_final.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections import Counter

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BAK = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_pre_c19_fix")
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
OUT = os.path.join(PROJ, "build", "drc_after_c19_final.json")

MM = pcbnew.FromMM
BC = int(pcbnew.B_Cu)
HARD = {
    "shorting_items",
    "tracks_crossing",
    "clearance",
    "hole_to_hole",
    "copper_edge_clearance",
    "solder_mask_bridge",
}


def TOMM(v):
    return v / 1e6


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def near(a, b, eps=0.1):
    return abs(a - b) < eps


def add_seg(board, x1, y1, x2, y2, lay, net, w):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1, y1))
    t.SetEnd(V(x2, y2))
    t.SetLayer(lay)
    t.SetWidth(MM(w))
    t.SetNet(net)
    board.Add(t)


def add_via(board, x, y, net):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(V(x, y))
    v.SetDrill(MM(0.20))
    try:
        v.SetWidth(MM(0.45))
    except TypeError:
        v.SetWidth(pcbnew.F_Cu, MM(0.45))
        v.SetWidth(pcbnew.B_Cu, MM(0.45))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    v.SetNet(net)
    board.Add(v)


def main():
    if not os.path.isfile(BAK):
        print("Missing", BAK)
        return 2
    shutil.copy2(BAK, PCB)
    print("Restored", BAK)

    board = pcbnew.LoadBoard(PCB)
    nets = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if n and n not in nets:
                nets[n] = p.GetNet()
    gnd = nets["GND"]
    xc1 = nets["XC1"]
    swdio = nets["SWDIO"]
    vbat_s = nets["VBAT_SENSE"]

    to_remove = []
    swdio_far = None
    vbat_far = None
    vbat_h_east = None

    for t in list(board.GetTracks()):
        if t.GetClass() == "PCB_VIA":
            continue
        if int(t.GetLayer()) != BC:
            continue
        net = t.GetNetname()
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)

        if net == "XC1" and (
            (
                near(sx, 151.413)
                and near(sy, 119.546)
                and near(ex, 153.214)
                and near(ey, 117.746)
            )
            or (
                near(ex, 151.413)
                and near(ey, 119.546)
                and near(sx, 153.214)
                and near(sy, 117.746)
            )
        ):
            to_remove.append(t)

        if net == "SWDIO" and (
            (near(sx, 153.778) and near(sy, 118.469))
            or (near(ex, 153.778) and near(ey, 118.469))
        ):
            swdio_far = (ex, ey) if near(sx, 153.778) and near(sy, 118.469) else (sx, sy)
            to_remove.append(t)

        if net == "VBAT_SENSE":
            if near(sy, 116.962, 0.05) and near(ey, 116.962, 0.05) and abs(sx - ex) > 1:
                to_remove.append(t)
                vbat_h_east = max(sx, ex)
            elif (
                (near(sx, 153.329, 0.15) and near(sy, 116.962, 0.15))
                or (near(ex, 153.329, 0.15) and near(ey, 116.962, 0.15))
            ) and abs(sx - ex) > 5:
                vbat_far = (ex, ey) if near(sx, 153.329, 0.15) else (sx, sy)
                to_remove.append(t)

    for t in to_remove:
        board.Remove(t)
    print(f"removed {len(to_remove)} segments")

    sfx, sfy = swdio_far
    add_seg(board, 153.778, 118.469, 153.778, 123.00, BC, swdio, 0.15)
    add_seg(board, 153.778, 123.00, sfx, sfy, BC, swdio, 0.15)
    print("SWDIO: B south dogleg")

    add_seg(board, 151.413, 119.546, 153.214, 119.546, BC, xc1, 0.15)
    add_seg(board, 153.214, 119.546, 153.214, 117.746, BC, xc1, 0.15)
    print("XC1: B L-east (clears C19 pad2)")

    add_seg(board, vbat_h_east, 116.962, 153.329, 116.962, BC, vbat_s, 0.15)
    add_seg(board, 153.329, 116.962, 146.50, 123.50, BC, vbat_s, 0.15)
    add_seg(board, 146.50, 123.50, vbat_far[0], vbat_far[1], BC, vbat_s, 0.15)
    print("VBAT_SENSE: diagonal bowed SW via (146.5,123.5)")

    add_via(board, 152.50, 118.52, gnd)
    print("C19: GND via-in-pad @ (152.50, 118.52)")

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(PCB)

    board = pcbnew.LoadBoard(PCB)
    for t in list(board.GetTracks()):
        if t.GetClass() != "PCB_VIA" or t.GetNetname() != "SWDIO":
            continue
        p = t.GetPosition()
        x, y = TOMM(p.x), TOMM(p.y)
        if not (near(x, 153.778, 0.05) and near(y, 118.469, 0.05)):
            board.Remove(t)
            print(f"strip extra SWDIO via @({x:.3f},{y:.3f})")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(PCB)
    print("Saved", PCB)

    subprocess.run(
        [KCLI, "pcb", "drc", "--format", "json", "-o", OUT, PCB], capture_output=True
    )
    d = json.load(open(OUT, encoding="utf-8"))
    unc = d.get("unconnected_items", [])
    viol = d.get("violations", [])
    print(
        f"DRC unconnected={len(unc)} viol={len(viol)} "
        f"sev={dict(Counter(v.get('severity') for v in viol))}"
    )
    print("types", dict(Counter(v.get("type") for v in viol).most_common()))
    hard = []
    for v in viol:
        if v.get("severity") != "error":
            continue
        items = v.get("items", [])
        descs = [i.get("description", "")[:95] for i in items]
        print(f" ERR {v.get('type')}: {' | '.join(descs)}")
        if v.get("type") in HARD:
            hard.append(v)
    for u in unc:
        print(" UNCONN", [i.get("description", "")[:80] for i in u.get("items", [])])

    ok = len(hard) == 0
    print("SUCCESS hard=0" if ok else f"PARTIAL hard={len(hard)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
