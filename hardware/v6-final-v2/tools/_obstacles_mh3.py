#!/usr/bin/env python3
"""List B.Cu obstacles that intersect candidate corridors."""
from __future__ import annotations

import os
import shutil

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
BAK = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_gnd_closed_ok")
TOMM = lambda v: v / 1e6
BC = int(pcbnew.B_Cu)


def main():
    shutil.copy2(BAK, PCB)
    board = pcbnew.LoadBoard(PCB)

    print("=== ALL B tracks with any point in x=125-162 y=114-140 (excl violator segs) ===")
    for t in board.Tracks():
        net = t.GetNetname()
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            x, y = TOMM(p.x), TOMM(p.y)
            if 125 <= x <= 162 and 114 <= y <= 140:
                print(f"VIA {net:16s} ({x:.3f},{y:.3f}) drill={TOMM(t.GetDrill()):.3f}")
            continue
        if int(t.GetLayer()) != BC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        w = TOMM(t.GetWidth())
        # skip violators
        if net == "SWDIO" and abs(sx - 154.2) < 0.15 and abs(ex - 154.2) < 0.15 and min(sy, ey) < 120 and max(sy, ey) > 130:
            continue
        if net == "SWDIO" and abs(sy - 132.5) < 0.15 and abs(ey - 132.5) < 0.15 and max(sx, ex) > 150:
            continue
        if net == "VBAT_SENSE" and abs(sx - 155.92) < 0.15 and abs(ex - 155.92) < 0.15 and min(sy, ey) < 120 and max(sy, ey) > 130:
            continue
        if net == "VBAT_SENSE" and abs(sy - 134.0) < 0.15 and abs(ey - 134.0) < 0.15 and max(sx, ex) > 150:
            continue
        # bbox overlap
        if max(sx, ex) < 125 or min(sx, ex) > 162:
            continue
        if max(sy, ey) < 114 or min(sy, ey) > 140:
            continue
        print(f"B {net:16s} ({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f}) w={w:.3f}")


if __name__ == "__main__":
    main()
