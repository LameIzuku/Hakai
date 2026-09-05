#!/usr/bin/env python3
"""F.Cu C19-2 -> C18-2 GND jump on pcb_final_proto_backup."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections import Counter

import pcbnew

V6 = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SRC = os.path.join(V6, "hakai_mouse_v6.kicad_pcb")
PCB = os.path.join(V6, "pcb_final_proto_backup.kicad_pcb")
PRO_SRC = os.path.join(V6, "hakai_mouse_v6.kicad_pro")
PRO = os.path.join(V6, "pcb_final_proto_backup.kicad_pro")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
OUT = os.path.join(V6, "build", "drc_pcb_final_proto_backup.json")

MM = pcbnew.FromMM
FC = int(pcbnew.F_Cu)


def TOMM(v):
    return v / 1e6


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def near(a, b, eps=0.06):
    return abs(a - b) < eps


def main():
    shutil.copy2(SRC, PCB)
    shutil.copy2(PRO_SRC, PRO)
    print("Copied -> pcb_final_proto_backup.kicad_pcb")

    board = pcbnew.LoadBoard(PCB)
    nets = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if n and n not in nets:
                nets[n] = p.GetNet()
    gnd, xc2, xc1 = nets["GND"], nets["XC2"], nets["XC1"]

    def add_seg(x1, y1, x2, y2, net, w):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(x1, y1))
        t.SetEnd(V(x2, y2))
        t.SetLayer(FC)
        t.SetWidth(MM(w))
        t.SetNet(net)
        board.Add(t)

    to_del = []
    for t in list(board.Tracks()):
        if t.GetClass() == "PCB_VIA":
            continue
        if int(t.GetLayer()) != FC:
            continue
        net = t.GetNetname()
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)

        if net == "XC2" and (
            (
                near(sx, 150.994)
                and near(sy, 117.975)
                and near(ex, 152.5)
                and near(ey, 119.48)
            )
            or (
                near(ex, 150.994)
                and near(ey, 117.975)
                and near(sx, 152.5)
                and near(sy, 119.48)
            )
        ):
            to_del.append(t)
            continue

        if net == "XC1" and near(sx, 150.30, 0.05) and near(ex, 150.30, 0.05):
            if min(sy, ey) < 115 and max(sy, ey) > 118:
                to_del.append(t)
                print(f"XC1: remove vertical ({sy:.2f}-{ey:.2f})")
                continue

    for t in to_del:
        board.Remove(t)
    print(f"removed {len(to_del)}")

    # XC2: go north-east first (y=117.50), vertical far east (x=154.40), then to pad1
    # so it never crosses the GND jump rectangle at y=118.25, x=149..152.5
    add_seg(150.9945, 117.9745, 154.40, 117.50, xc2, 0.12)
    add_seg(154.40, 117.50, 154.40, 119.48, xc2, 0.12)
    add_seg(154.40, 119.48, 152.50, 119.48, xc2, 0.12)
    print("XC2: far-east dogleg x=154.40")

    # XC1 detour rejoin via
    add_seg(150.30, 113.55, 150.30, 117.85, xc1, 0.15)
    add_seg(150.30, 117.85, 148.00, 117.85, xc1, 0.15)
    add_seg(148.00, 117.85, 148.00, 119.15, xc1, 0.15)
    add_seg(148.00, 119.15, 151.4135, 119.5459, xc1, 0.15)
    print("XC1: detour x=148.00 -> via")

    # GND jump
    add_seg(152.50, 118.52, 152.50, 118.25, gnd, 0.10)
    add_seg(152.50, 118.25, 149.00, 118.25, gnd, 0.10)
    add_seg(149.00, 118.25, 149.00, 118.52, gnd, 0.10)
    print("GND: F-jump C19-2 -> C18-2 @ y=118.25")

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
    sev = Counter(v.get("severity") for v in viol)
    typ = Counter(v.get("type") for v in viol)
    print(f"DRC unconnected={len(unc)} viol={len(viol)} sev={dict(sev)}")
    for k, n in typ.most_common():
        print(f"  {k}: {n}")
    hard = []
    for v in viol:
        if v.get("severity") != "error":
            continue
        items = v.get("items", [])
        descs = [i.get("description", "")[:90] for i in items]
        p = items[0].get("pos", {}) if items else {}
        print(f" ERR {v.get('type')}: {' | '.join(descs)} @({p.get('x')},{p.get('y')})")
        if v.get("type") in {
            "shorting_items",
            "tracks_crossing",
            "clearance",
            "hole_to_hole",
        }:
            hard.append(v)

    ok = len(unc) == 0 and not hard
    print("SUCCESS" if ok else f"PARTIAL unc={len(unc)} hard={len(hard)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
