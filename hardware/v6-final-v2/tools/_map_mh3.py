#!/usr/bin/env python3
"""Map copper/pads near MH3 for clearance routing."""
from __future__ import annotations

import math
import os
import shutil

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
BAK = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_gnd_closed_ok")

TOMM = lambda v: v / 1e6
MH = (155.0, 130.0)
BC = int(pcbnew.B_Cu)
FC = int(pcbnew.F_Cu)


def near_box(x, y, x0=145, x1=165, y0=110, y1=145):
    return x0 <= x <= x1 and y0 <= y <= y1


def main():
    if os.path.isfile(BAK):
        shutil.copy2(BAK, PCB)
        print("Restored", BAK)
    board = pcbnew.LoadBoard(PCB)
    if board is None:
        raise SystemExit(f"LoadBoard failed: {PCB}")

    print("=== FOOTPRINTS near MH3 ===")
    for fp in board.GetFootprints():
        p = fp.GetPosition()
        x, y = TOMM(p.x), TOMM(p.y)
        if near_box(x, y, 145, 165, 110, 145):
            print(f"  {fp.GetReference():8s} @({x:.3f},{y:.3f}) {fp.GetFPIDAsString()}")
            for pad in fp.Pads():
                pp = pad.GetPosition()
                px, py = TOMM(pp.x), TOMM(pp.y)
                sz = pad.GetSize()
                print(
                    f"    pad#{pad.GetNumber():4s} net={pad.GetNetname():16s} "
                    f"@({px:.3f},{py:.3f}) size=({TOMM(sz.x):.3f}x{TOMM(sz.y):.3f})"
                )

    print("\n=== VIAS within 12mm of MH3 ===")
    for t in board.Tracks():
        if t.GetClass() != "PCB_VIA":
            continue
        p = t.GetPosition()
        x, y = TOMM(p.x), TOMM(p.y)
        if math.hypot(x - MH[0], y - MH[1]) < 12:
            print(f"  VIA {t.GetNetname():16s} @({x:.3f},{y:.3f}) drill={TOMM(t.GetDrill()):.3f}")

    print("\n=== TRACKS near MH3 band ===")
    for t in board.Tracks():
        if t.GetClass() == "PCB_VIA":
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        if not (
            near_box(sx, sy, 148, 162, 115, 142)
            or near_box(ex, ey, 148, 162, 115, 142)
            or near_box((sx + ex) / 2, (sy + ey) / 2, 148, 162, 115, 142)
        ):
            continue
        lay = "B" if int(t.GetLayer()) == BC else ("F" if int(t.GetLayer()) == FC else str(t.GetLayer()))
        print(
            f"  {lay} {t.GetNetname():16s} ({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f}) "
            f"w={TOMM(t.GetWidth()):.3f}"
        )

    print("\n=== SWDIO all ===")
    for t in board.Tracks():
        if t.GetNetname() != "SWDIO":
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            print(f"  VIA @({TOMM(p.x):.3f},{TOMM(p.y):.3f})")
            continue
        s, e = t.GetStart(), t.GetEnd()
        lay = "B" if int(t.GetLayer()) == BC else "F"
        print(f"  {lay} ({TOMM(s.x):.3f},{TOMM(s.y):.3f})-({TOMM(e.x):.3f},{TOMM(e.y):.3f})")

    print("\n=== VBAT_SENSE all ===")
    for t in board.Tracks():
        if t.GetNetname() != "VBAT_SENSE":
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            print(f"  VIA @({TOMM(p.x):.3f},{TOMM(p.y):.3f})")
            continue
        s, e = t.GetStart(), t.GetEnd()
        lay = "B" if int(t.GetLayer()) == BC else "F"
        print(f"  {lay} ({TOMM(s.x):.3f},{TOMM(s.y):.3f})-({TOMM(e.x):.3f},{TOMM(e.y):.3f})")

    print("\n=== XC1 all B/F ===")
    for t in board.Tracks():
        if t.GetNetname() != "XC1":
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            print(f"  VIA @({TOMM(p.x):.3f},{TOMM(p.y):.3f})")
            continue
        s, e = t.GetStart(), t.GetEnd()
        lay = "B" if int(t.GetLayer()) == BC else "F"
        print(f"  {lay} ({TOMM(s.x):.3f},{TOMM(s.y):.3f})-({TOMM(e.x):.3f},{TOMM(e.y):.3f})")

    print("\n=== GND tracks near MH3 ===")
    for t in board.Tracks():
        if t.GetNetname() != "GND" or t.GetClass() == "PCB_VIA":
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        if near_box(sx, sy, 148, 160, 115, 140) or near_box(ex, ey, 148, 160, 115, 140):
            lay = "B" if int(t.GetLayer()) == BC else "F"
            print(f"  {lay} ({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f})")


if __name__ == "__main__":
    main()
