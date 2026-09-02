#!/usr/bin/env python3
"""v6: Final polish on v5 approach.

C12: delete upper BS-BACK cage (as v5); place GND via at (148.0, 109.65)
     with F spoke from pad (148.0, 109.52) so clearance to BS rail y=109.10
     is 0.55 mm; B spoke to GND via (150.55, 110.18).

C19: F path to Y1 GND pad (151.70, 113.55) via x=152.0 corridor — avoids
     crossing XC2 vertical at x≈150.99.
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
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
BAK = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_pre_gnd_fix")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
OUT = os.path.join(PROJ, "build", "drc_after_gnd_fix.json")

VIA_D, VIA_DRILL = 0.45, 0.20
MM = pcbnew.FromMM
FC, BC = int(pcbnew.F_Cu), int(pcbnew.B_Cu)


def TOMM(v):
    return v / 1e6


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def near(a, b, eps=0.04):
    return abs(a - b) < eps


def main():
    if os.path.isfile(BAK):
        shutil.copy2(BAK, PCB)
        print("Restored clean PCB from backup")

    board = pcbnew.LoadBoard(PCB)

    def net_of(name):
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if p.GetNetname() == name:
                    return p.GetNet()
        for t in board.GetTracks():
            if t.GetNetname() == name:
                return t.GetNet()
        return None

    gnd = net_of("GND")
    bs = net_of("BTN_SIDE_BACK")
    assert gnd and bs

    # ---- delete upper BS-BACK cage ----
    to_delete = []
    for t in board.GetTracks():
        if t.GetNetname() != "BTN_SIDE_BACK":
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            x, y = TOMM(p.x), TOMM(p.y)
            if near(x, 150.10, 0.06) and near(y, 109.55, 0.04):
                to_delete.append(t)
                print(f"  del via ({x:.2f},{y:.2f})")
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        lay = int(t.GetLayer())
        if (
            lay == BC
            and near(sy, 109.55)
            and near(ey, 109.55)
            and abs(sx - ex) > 1.0
            and min(sx, ex) < 150.5
            and max(sx, ex) > 146.0
        ):
            to_delete.append(t)
            print(f"  del B H ({sx:.2f},{sy:.2f})-({ex:.2f},{ey:.2f})")
        elif (
            lay == BC
            and near(sx, 146.75, 0.08)
            and near(ex, 146.75, 0.08)
            and (
                (near(sy, 110.00) and near(ey, 109.55))
                or (near(ey, 110.00) and near(sy, 109.55))
            )
        ):
            to_delete.append(t)
            print(f"  del B V ({sx:.2f},{sy:.2f})-({ex:.2f},{ey:.2f})")

    for t in to_delete:
        board.Remove(t)

    # retarget F from deleted via to lower via
    for t in board.GetTracks():
        if t.GetNetname() != "BTN_SIDE_BACK" or t.GetClass() == "PCB_VIA":
            continue
        if int(t.GetLayer()) != FC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        nsy, ney = sy, ey
        ch = False
        if near(sx, 150.10, 0.08) and near(sy, 109.55, 0.04):
            nsy = 109.10
            ch = True
        if near(ex, 150.10, 0.08) and near(ey, 109.55, 0.04):
            ney = 109.10
            ch = True
        if near(sy, 109.55) and near(ey, 109.55) and min(sx, ex) > 149.5:
            nsy = ney = 109.10
            ch = True
        if near(sx, 150.50, 0.08) and near(ex, 150.50, 0.08):
            if near(sy, 109.55):
                nsy = 109.10
                ch = True
            if near(ey, 109.55):
                ney = 109.10
                ch = True
        if ch:
            t.SetStart(V(sx, nsy))
            t.SetEnd(V(ex, ney))
            print(f"  F retarget -> y {nsy:.2f}/{ney:.2f}")

    # reconnect 146.75 via to lower rail
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(146.75, 110.00))
    t.SetEnd(V(146.75, 109.10))
    t.SetLayer(BC)
    t.SetWidth(MM(0.10))
    t.SetNet(bs)
    board.Add(t)

    def add_via(x, y, net):
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(V(x, y))
        v.SetDrill(MM(VIA_DRILL))
        try:
            v.SetWidth(MM(VIA_D))
        except TypeError:
            v.SetWidth(pcbnew.F_Cu, MM(VIA_D))
            v.SetWidth(pcbnew.B_Cu, MM(VIA_D))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(net)
        board.Add(v)

    def add_seg(x1, y1, x2, y2, lay, net, w):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(x1, y1))
        t.SetEnd(V(x2, y2))
        t.SetLayer(lay)
        t.SetWidth(MM(w))
        t.SetNet(net)
        board.Add(t)

    print("=== C12 ===")
    # Via slightly south of pad for clearance to BS rail @109.10
    add_via(148.00, 109.65, gnd)
    add_seg(148.00, 109.52, 148.00, 109.65, FC, gnd, 0.10)  # pad -> via
    add_seg(148.00, 109.65, 150.55, 109.65, BC, gnd, 0.10)
    add_seg(150.55, 109.65, 150.55, 110.18, BC, gnd, 0.10)
    print("  via@109.65 + B to GND via 150.55,110.18")

    print("=== C19 ===")
    # To Y1 pad2 GND (151.70, 113.55) via x=152.0 corridor
    wpts = [
        (152.50, 118.52),  # C19-2
        (152.00, 118.52),
        (152.00, 113.55),
        (151.70, 113.55),  # Y1 GND
    ]
    for i in range(len(wpts) - 1):
        a, b = wpts[i], wpts[i + 1]
        add_seg(a[0], a[1], b[0], b[1], FC, gnd, 0.10)
        print(f"  F {a} -> {b}")

    print("=== fill + DRC ===")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(PCB)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    subprocess.run(
        [KCLI, "pcb", "drc", "--format", "json", "-o", OUT, PCB],
        capture_output=True,
    )
    d = json.load(open(OUT, encoding="utf-8"))
    unc = d.get("unconnected_items", [])
    viol = d.get("violations", [])
    sev = Counter(v.get("severity") for v in viol)
    typ = Counter(v.get("type") for v in viol)
    print(f"unconnected={len(unc)} viol={len(viol)} sev={dict(sev)}")
    for k, n in typ.most_common():
        print(f"  {k}: {n}")
    for u in unc:
        print("  UNCONN", [i.get("description", "")[:55] for i in u.get("items", [])])
    hard = []
    for v in viol:
        if v.get("severity") != "error":
            continue
        items = v.get("items", [])
        descs = [i.get("description", "")[:60] for i in items]
        p = items[0].get("pos", {}) if items else {}
        print(f"  ERR {v.get('type')}: {' | '.join(descs)} @({p.get('x')},{p.get('y')})")
        if v.get("type") in {
            "shorting_items",
            "tracks_crossing",
            "clearance",
            "hole_to_hole",
        }:
            hard.append(v)

    if len(unc) == 0 and not hard:
        print("SUCCESS")
        return 0
    print(f"PARTIAL unc={len(unc)} hard={len(hard)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
