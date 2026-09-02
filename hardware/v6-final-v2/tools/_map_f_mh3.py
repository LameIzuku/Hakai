#!/usr/bin/env python3
"""Map F.Cu near MH3 for possible VBAT via hop."""
from __future__ import annotations

import os
import shutil

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
BAK = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_gnd_closed_ok")
TOMM = lambda v: v / 1e6
FC = int(pcbnew.F_Cu)


def main():
    shutil.copy2(BAK, PCB)
    board = pcbnew.LoadBoard(PCB)
    print("=== F tracks x=145-162 y=114-140 ===")
    for t in board.Tracks():
        if t.GetClass() == "PCB_VIA":
            continue
        if int(t.GetLayer()) != FC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        if max(sx, ex) < 145 or min(sx, ex) > 162:
            continue
        if max(sy, ey) < 114 or min(sy, ey) > 140:
            continue
        print(
            f"F {t.GetNetname():16s} ({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f}) "
            f"w={TOMM(t.GetWidth()):.3f}"
        )


if __name__ == "__main__":
    main()
