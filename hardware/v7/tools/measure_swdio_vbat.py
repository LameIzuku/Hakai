#!/usr/bin/env python3
"""Fresh-process board metrics for SWDIO/VBAT MH3 work. Prints one JSON object."""
from __future__ import annotations

import json
import math
import os
import sys

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")

BC = int(pcbnew.B_Cu)
FC = int(pcbnew.F_Cu)
MH = (155.0, 130.0)
HOLE_R = 1.6
CLEAR = 1.4


def TOMM(v):
    return v / 1e6


def seg_dist(x1, y1, x2, y2, px, py):
    dx, dy = x2 - x1, y2 - y1
    l2 = dx * dx + dy * dy
    if l2 < 1e-18:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / l2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def path_length(board, net):
    total = 0.0
    n_via = 0
    vias = []
    segs = []
    for t in board.Tracks():
        if t.GetNetname() != net:
            continue
        if t.GetClass() == "PCB_VIA":
            n_via += 1
            p = t.GetPosition()
            vias.append([round(TOMM(p.x), 3), round(TOMM(p.y), 3)])
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        total += math.hypot(ex - sx, ey - sy)
        lay = "B" if int(t.GetLayer()) == BC else ("F" if int(t.GetLayer()) == FC else "?")
        segs.append([lay, sx, sy, ex, ey, TOMM(t.GetWidth())])
    return [total, n_via, vias, segs]


def xc1_metrics(board):
    segs = []
    n_via = 0
    for t in board.Tracks():
        if t.GetNetname() != "XC1":
            continue
        if t.GetClass() == "PCB_VIA":
            n_via += 1
            continue
        if int(t.GetLayer()) != BC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        segs.append((TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)))
    length = sum(math.hypot(ex - sx, ey - sy) for sx, sy, ex, ey in segs)
    pts = [(sx, sy) for sx, sy, ex, ey in segs] + [(ex, ey) for sx, sy, ex, ey in segs]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    pts2 = sorted(set((round(x, 4), round(y, 4)) for x, y in pts))
    if len(pts2) < 3:
        return [length, 0.0, n_via]
    lower = []
    for p in pts2:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts2):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    area = 0.0
    for i in range(len(hull)):
        x1, y1 = hull[i]
        x2, y2 = hull[(i + 1) % len(hull)]
        area += x1 * y2 - x2 * y1
    return [length, abs(area) / 2, n_via]


def measure_mh(board):
    min_edge = 1e9
    details = []
    for t in board.Tracks():
        net = t.GetNetname()
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            x, y = TOMM(p.x), TOMM(p.y)
            try:
                wr = TOMM(t.GetWidth()) / 2
            except Exception:
                wr = 0.225
            d = math.hypot(x - MH[0], y - MH[1]) - HOLE_R - wr
            if d < CLEAR + 1.0:
                details.append([d, f"VIA:{net}", x, y, x, y])
            min_edge = min(min_edge, d)
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        edge = seg_dist(sx, sy, ex, ey, *MH) - HOLE_R - TOMM(t.GetWidth()) / 2
        if net in ("SWDIO", "VBAT_SENSE") or edge < CLEAR + 0.5:
            details.append([edge, net, sx, sy, ex, ey])
        min_edge = min(min_edge, edge)
    return min_edge, details


def closest_box(board, net, box):
    x0, y0, x1, y1 = box
    best = 1e9

    def pt_box(px, py):
        return math.hypot(max(x0 - px, 0, px - x1), max(y0 - py, 0, py - y1))

    for t in board.Tracks():
        if t.GetNetname() != net:
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            best = min(best, pt_box(TOMM(p.x), TOMM(p.y)))
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        for i in range(41):
            tpar = i / 40
            best = min(best, pt_box(sx + tpar * (ex - sx), sy + tpar * (ey - sy)))
    return best


def closest_pt(board, net, pt):
    px, py = pt
    best = 1e9
    for t in board.Tracks():
        if t.GetNetname() != net:
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            best = min(best, math.hypot(TOMM(p.x) - px, TOMM(p.y) - py))
            continue
        s, e = t.GetStart(), t.GetEnd()
        best = min(best, seg_dist(TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y), px, py))
    return best


def min_width(board, net):
    ws = [
        TOMM(t.GetWidth())
        for t in board.Tracks()
        if t.GetClass() != "PCB_VIA" and t.GetNetname() == net
    ]
    return [min(ws), max(ws)] if ws else [None, None]


def track_len(board, net, layer=None):
    s = 0.0
    for t in board.Tracks():
        if t.GetClass() == "PCB_VIA" or t.GetNetname() != net:
            continue
        if layer is not None and int(t.GetLayer()) != layer:
            continue
        a, b = t.GetStart(), t.GetEnd()
        s += math.hypot(TOMM(b.x) - TOMM(a.x), TOMM(b.y) - TOMM(a.y))
    return s


def main():
    board = pcbnew.LoadBoard(PCB)
    me, det = measure_mh(board)
    out = {
        "xc1": xc1_metrics(board),
        "sw": path_length(board, "SWDIO"),
        "vb": path_length(board, "VBAT_SENSE"),
        "rf": track_len(board, "RF_FEED", FC),
        "w19": min_width(board, "1V9_A"),
        "min_edge": me,
        "details": det,
        "d_rf": closest_box(board, "VBAT_SENSE", (160.0, 100.0, 168.0, 120.0)),
        "d_dc": closest_box(board, "VBAT_SENSE", (146.0, 111.0, 150.5, 118.5)),
        "d_l2": closest_pt(board, "VBAT_SENSE", (148.0, 116.0)),
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
