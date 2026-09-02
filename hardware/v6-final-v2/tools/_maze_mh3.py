#!/usr/bin/env python3
"""Sample B.Cu occupancy near MH3 to find free channels for SWDIO/VBAT."""
from __future__ import annotations

import math
import os
import shutil

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
BAK = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_gnd_closed_ok")

TOMM = lambda v: v / 1e6
BC = int(pcbnew.B_Cu)
MH = (155.0, 130.0)


def main():
    shutil.copy2(BAK, PCB)
    board = pcbnew.LoadBoard(PCB)

    # Collect B tracks/vias (excluding SWDIO long and VBAT long we'll remove)
    segs = []  # (net, x1,y1,x2,y2,w)
    vias = []  # (net, x, y, drill, width_approx)

    for t in board.Tracks():
        net = t.GetNetname()
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            x, y = TOMM(p.x), TOMM(p.y)
            if 120 < x < 165 and 110 < y < 145:
                vias.append((net, x, y, TOMM(t.GetDrill()), 0.45))
            continue
        if int(t.GetLayer()) != BC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        w = TOMM(t.GetWidth())
        # skip violator segments
        if net == "SWDIO" and abs(sx - 154.2) < 0.15 and abs(ex - 154.2) < 0.15:
            if min(sy, ey) < 120 and max(sy, ey) > 130:
                continue
        if net == "SWDIO" and abs(sy - 132.5) < 0.15 and abs(ey - 132.5) < 0.15:
            if max(sx, ex) > 150 and min(sx, ex) < 140:
                continue
        if net == "VBAT_SENSE" and abs(sx - 155.92) < 0.15 and abs(ex - 155.92) < 0.15:
            if min(sy, ey) < 120 and max(sy, ey) > 130:
                continue
        if net == "VBAT_SENSE" and abs(sy - 134.0) < 0.15 and abs(ey - 134.0) < 0.15:
            if max(sx, ex) > 150 and min(sx, ex) < 140:
                continue
        if 120 < max(sx, ex) and min(sx, ex) < 165 and 110 < max(sy, ey) and min(sy, ey) < 145:
            segs.append((net, sx, sy, ex, ey, w))

    def pt_clear(x, y, our_w=0.15, clear=0.10, ignore_nets=()):
        """Min edge-edge clearance to foreign copper; return min edge clear."""
        best = 1e9
        half = our_w / 2
        for net, x1, y1, x2, y2, w in segs:
            if net in ignore_nets:
                continue
            dx, dy = x2 - x1, y2 - y1
            l2 = dx * dx + dy * dy
            if l2 < 1e-18:
                d = math.hypot(x - x1, y - y1)
            else:
                t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / l2))
                d = math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))
            edge = d - half - w / 2
            best = min(best, edge)
        for net, vx, vy, drill, diam in vias:
            if net in ignore_nets:
                continue
            d = math.hypot(x - vx, y - vy)
            edge = d - half - diam / 2
            best = min(best, edge)
        # MH hole
        d = math.hypot(x - MH[0], y - MH[1])
        edge = d - half - 1.6
        best = min(best, edge)
        return best

    # Sample grid
    print("=== free grid sample (edge clear >= 0.10) for SWDIO ===")
    for y in [118.5, 120, 122, 124, 126, 126.5, 128, 130, 132, 132.5, 134, 135.5]:
        row = []
        for x in [147, 148, 148.5, 149, 149.5, 150, 150.5, 151, 151.5, 152, 152.5, 153, 153.5, 154, 154.2, 155, 156, 157, 158, 158.4, 159]:
            c = pt_clear(x, y, ignore_nets=("SWDIO",))
            row.append("." if c >= 0.10 else ("#" if c < 0 else "x"))
        print(f"y={y:6.1f} {''.join(row)}  (.=ok x=tight #=hit)")

    print("\n=== free grid for VBAT_SENSE ===")
    for y in [115.5, 116.0, 116.2, 116.5, 116.8, 117.0, 117.5, 118, 120, 122, 124, 126, 128, 130, 132, 134, 134.9]:
        row = []
        xs = [127, 128, 129, 129.2, 130, 132, 134, 136, 138, 140, 142, 144, 146, 148, 150, 151.5, 152.5, 154, 155.5, 155.92, 157, 158.5]
        for x in xs:
            c = pt_clear(x, y, ignore_nets=("VBAT_SENSE",))
            row.append("." if c >= 0.10 else ("#" if c < 0 else "x"))
        print(f"y={y:6.1f} {''.join(row)}")

    print("\n=== detailed clears along candidate columns ===")
    for x, net in [(150.0, "SWDIO"), (151.5, "SWDIO"), (148.5, "SWDIO"), (149.0, "SWDIO"),
                   (127.5, "VBAT_SENSE"), (129.203, "VBAT_SENSE"), (151.5, "VBAT_SENSE"),
                   (152.8, "VBAT_SENSE"), (157.5, "VBAT_SENSE"), (159.0, "VBAT_SENSE")]:
        print(f"\n column x={x} for {net}:")
        for y in [116.2, 116.5, 117, 118, 120, 122, 124, 126, 126.5, 128, 129.5, 130, 132, 132.5, 134, 134.9, 135.5]:
            c = pt_clear(x, y, ignore_nets=(net,))
            mh = math.hypot(x - MH[0], y - MH[1]) - 1.6 - 0.075
            mark = "OK" if c >= 0.10 and mh >= 1.5 else ("MH" if mh < 1.5 else "BLK")
            if mark != "OK":
                print(f"  y={y:6.1f} clear={c:6.3f} mh_edge={mh:6.3f} {mark}")


if __name__ == "__main__":
    main()
