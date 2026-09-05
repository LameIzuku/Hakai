#!/usr/bin/env python3
"""C19 fix: shove SWDIO B, XC1 B L-east, GND VIP on C19-2."""
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
    shutil.copy2(BAK, PCB)
    print("Restored baseline")
    board = pcbnew.LoadBoard(PCB)

    nets = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if n and n not in nets:
                nets[n] = p.GetNet()
    gnd, xc1, swdio = nets["GND"], nets["XC1"], nets["SWDIO"]

    tracks = list(board.GetTracks())
    to_remove = []
    swdio_far = None

    for t in tracks:
        cls = t.GetClass()
        if cls == "PCB_VIA":
            continue
        net = t.GetNetname()
        lay = int(t.GetLayer())
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)

        if net == "XC1" and lay == BC:
            if (
                near(sx, 151.413)
                and near(sy, 119.546)
                and near(ex, 153.214)
                and near(ey, 117.746)
            ) or (
                near(ex, 151.413)
                and near(ey, 119.546)
                and near(sx, 153.214)
                and near(sy, 117.746)
            ):
                to_remove.append(t)
                print(f"mark XC1 diag ({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f})")

        if net == "SWDIO" and lay == BC:
            if (near(sx, 153.778) and near(sy, 118.469)) or (
                near(ex, 153.778) and near(ey, 118.469)
            ):
                if near(sx, 153.778) and near(sy, 118.469):
                    swdio_far = (ex, ey)
                else:
                    swdio_far = (sx, sy)
                to_remove.append(t)
                print(f"mark SWDIO B ({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f})")

    for t in to_remove:
        board.Remove(t)
    print(f"removed {len(to_remove)}")

    if swdio_far is None:
        print("ERROR: SWDIO B segment not found")
        return 2

    # SWDIO: south first to clear crystal B corridor, then to original far end
    fx, fy = swdio_far
    add_seg(board, 153.778, 118.469, 153.778, 122.50, BC, swdio, 0.15)
    add_seg(board, 153.778, 122.50, fx, fy, BC, swdio, 0.15)
    print(f"SWDIO B dogleg via y=122.50 -> ({fx:.3f},{fy:.3f})")

    # XC1 L-east (corridor freed)
    add_seg(board, 151.413, 119.546, 153.214, 119.546, BC, xc1, 0.15)
    add_seg(board, 153.214, 119.546, 153.214, 117.746, BC, xc1, 0.15)
    print("XC1 B L-east")

    # C19-2 VIP
    add_via(board, 152.50, 118.52, gnd)
    print("C19 GND VIP")

    print("zone fill...")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(PCB)
    print("Saved", PCB)

    subprocess.run(
        [KCLI, "pcb", "drc", "--format", "json", "-o", OUT, PCB],
        capture_output=True,
    )
    d = json.load(open(OUT, encoding="utf-8"))
    unc = d.get("unconnected_items", [])
    viol = d.get("violations", [])
    print(f"DRC unconnected={len(unc)} viol={len(viol)} sev={dict(Counter(v.get('severity') for v in viol))}")
    print("types", dict(Counter(v.get("type") for v in viol).most_common()))
    hard = []
    for v in viol:
        if v.get("severity") != "error":
            continue
        items = v.get("items", [])
        descs = [i.get("description", "")[:95] for i in items]
        p = items[0].get("pos", {}) if items else {}
        print(f" ERR {v.get('type')}: {' | '.join(descs)} @({p.get('x')},{p.get('y')})")
        if v.get("type") in HARD:
            hard.append(v)
    for u in unc:
        print(" UNCONN", [i.get("description", "")[:90] for i in u.get("items", [])])
    ok = len(unc) == 0 and not hard
    print("SUCCESS" if ok else f"PARTIAL unc={len(unc)} hard={len(hard)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
