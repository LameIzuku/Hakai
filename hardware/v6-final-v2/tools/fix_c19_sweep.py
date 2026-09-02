#!/usr/bin/env python3
"""Sweep C19 fix strategies on main board; keep best (unc=0, hard=0)."""
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
OUT = os.path.join(PROJ, "build", "drc_try.json")

MM = pcbnew.FromMM
FC, BC = int(pcbnew.F_Cu), int(pcbnew.B_Cu)
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


def near(a, b, eps=0.08):
    return abs(a - b) < eps


def add_seg(board, x1, y1, x2, y2, lay, net, w):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1, y1))
    t.SetEnd(V(x2, y2))
    t.SetLayer(lay)
    t.SetWidth(MM(w))
    t.SetNet(net)
    board.Add(t)


def add_via(board, x, y, net, d=0.45, drill=0.20):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(V(x, y))
    v.SetDrill(MM(drill))
    try:
        v.SetWidth(MM(d))
    except TypeError:
        v.SetWidth(pcbnew.F_Cu, MM(d))
        v.SetWidth(pcbnew.B_Cu, MM(d))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    v.SetNet(net)
    board.Add(v)


def nets_of(board):
    nets = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if n and n not in nets:
                nets[n] = p.GetNet()
    return nets


def rm_xc1_b_diag(board):
    for t in list(board.Tracks()):
        if t.GetClass() == "PCB_VIA":
            continue
        if t.GetNetname() != "XC1" or int(t.GetLayer()) != BC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
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
            board.Remove(t)
            return True
    return False


def rm_xc2_diag(board):
    for t in list(board.Tracks()):
        if t.GetClass() == "PCB_VIA":
            continue
        if t.GetNetname() != "XC2" or int(t.GetLayer()) != FC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        if (
            near(sx, 150.994)
            and near(sy, 117.974)
            and near(ex, 152.5)
            and near(ey, 119.48)
        ) or (
            near(ex, 150.994)
            and near(ey, 117.974)
            and near(sx, 152.5)
            and near(sy, 119.48)
        ):
            board.Remove(t)
            return True
    return False


def run_drc():
    subprocess.run(
        [KCLI, "pcb", "drc", "--format", "json", "-o", OUT, PCB],
        capture_output=True,
    )
    d = json.load(open(OUT, encoding="utf-8"))
    unc = d.get("unconnected_items", [])
    viol = d.get("violations", [])
    hard = [
        v
        for v in viol
        if v.get("severity") == "error" and v.get("type") in HARD
    ]
    return unc, hard, viol


def try_fix(name, builder):
    shutil.copy2(BAK, PCB)
    board = pcbnew.LoadBoard(PCB)
    nets = nets_of(board)
    builder(board, nets)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(PCB)
    unc, hard, viol = run_drc()
    print(f"{name:28} unc={len(unc)} hard={len(hard)}")
    for v in hard[:6]:
        items = v.get("items", [])
        descs = [i.get("description", "")[:78] for i in items]
        print(f"  {v.get('type')}: {' | '.join(descs)}")
    return len(unc), len(hard), name


def main():
    os.makedirs(os.path.join(PROJ, "build"), exist_ok=True)
    results = []

    def b_fjump(board, nets):
        g = nets["GND"]
        add_seg(board, 152.50, 118.52, 152.50, 118.30, FC, g, 0.10)
        add_seg(board, 152.50, 118.30, 147.70, 118.30, FC, g, 0.10)
        add_seg(board, 147.70, 118.30, 147.70, 118.52, FC, g, 0.10)

    def b_fjump_xc2_L(col):
        def b(board, nets):
            g, xc2 = nets["GND"], nets["XC2"]
            rm_xc2_diag(board)
            add_seg(board, 150.994, 117.974, col, 117.974, FC, xc2, 0.12)
            add_seg(board, col, 117.974, col, 119.48, FC, xc2, 0.12)
            add_seg(board, col, 119.48, 152.50, 119.48, FC, xc2, 0.12)
            b_fjump(board, nets)

        return b

    def b_vip_bow(segs):
        def b(board, nets):
            g, xc1 = nets["GND"], nets["XC1"]
            rm_xc1_b_diag(board)
            for x1, y1, x2, y2 in segs:
                add_seg(board, x1, y1, x2, y2, BC, xc1, 0.15)
            add_via(board, 152.50, 118.52, g)

        return b

    def b_fjump_thin(board, nets):
        g = nets["GND"]
        add_seg(board, 152.50, 118.52, 152.50, 118.25, FC, g, 0.09)
        add_seg(board, 152.50, 118.25, 147.70, 118.25, FC, g, 0.09)
        add_seg(board, 147.70, 118.25, 147.70, 118.52, FC, g, 0.09)

    def b_fjump_dogleg_xc2(board, nets):
        """F-jump dogleg that stops east of XC2 crossing then goes around north."""
        g = nets["GND"]
        # XC2 crosses y=118.30 near x=151.32; stay east then north then west
        add_seg(board, 152.50, 118.52, 152.50, 118.30, FC, g, 0.10)
        add_seg(board, 152.50, 118.30, 151.70, 118.30, FC, g, 0.10)
        add_seg(board, 151.70, 118.30, 151.70, 117.70, FC, g, 0.10)
        add_seg(board, 151.70, 117.70, 147.70, 117.70, FC, g, 0.10)
        add_seg(board, 147.70, 117.70, 147.70, 118.52, FC, g, 0.10)

    def b_combo_xc1_shift_fjump(board, nets):
        """Shift XC1 F vertical east of C19, F-jump under it, keep XC2 L east."""
        g, xc1, xc2 = nets["GND"], nets["XC1"], nets["XC2"]
        # remove XC1 vertical
        for t in list(board.Tracks()):
            if t.GetClass() == "PCB_VIA":
                continue
            if t.GetNetname() != "XC1" or int(t.GetLayer()) != FC:
                continue
            s, e = t.GetStart(), t.GetEnd()
            sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
            if near(sx, 150.3) and near(ex, 150.3) and min(sy, ey) < 115 and max(sy, ey) > 118:
                board.Remove(t)
        # XC1 Y1 via east column past C19
        add_seg(board, 150.30, 118.637, 150.30, 120.40, FC, xc1, 0.12)
        add_seg(board, 150.30, 120.40, 154.60, 120.40, FC, xc1, 0.12)
        add_seg(board, 154.60, 120.40, 154.60, 113.55, FC, xc1, 0.12)
        add_seg(board, 154.60, 113.55, 150.30, 113.55, FC, xc1, 0.12)
        # XC2 L
        rm_xc2_diag(board)
        add_seg(board, 150.994, 117.974, 153.05, 117.974, FC, xc2, 0.12)
        add_seg(board, 153.05, 117.974, 153.05, 119.48, FC, xc2, 0.12)
        add_seg(board, 153.05, 119.48, 152.50, 119.48, FC, xc2, 0.12)
        b_fjump(board, nets)

    trials = [
        ("fjump_only", b_fjump),
        ("fjump_thin", b_fjump_thin),
        ("fjump_dogleg_xc2", b_fjump_dogleg_xc2),
        ("fjump_xc2_L_153.05", b_fjump_xc2_L(153.05)),
        ("fjump_xc2_L_153.20", b_fjump_xc2_L(153.20)),
        ("fjump_xc2_L_152.95", b_fjump_xc2_L(152.95)),
        (
            "vip_bow_s119.4",
            b_vip_bow(
                [
                    (151.413, 119.546, 152.50, 119.40),
                    (152.50, 119.40, 153.214, 117.746),
                ]
            ),
        ),
        (
            "vip_bow_s119.6",
            b_vip_bow(
                [
                    (151.413, 119.546, 152.50, 119.60),
                    (152.50, 119.60, 153.214, 117.746),
                ]
            ),
        ),
        (
            "vip_L_east",
            b_vip_bow(
                [
                    (151.413, 119.546, 153.214, 119.546),
                    (153.214, 119.546, 153.214, 117.746),
                ]
            ),
        ),
        (
            "vip_L_east2",
            b_vip_bow(
                [
                    (151.413, 119.546, 153.60, 119.546),
                    (153.60, 119.546, 153.60, 117.746),
                    (153.60, 117.746, 153.214, 117.746),
                ]
            ),
        ),
        (
            "vip_U_south",
            b_vip_bow(
                [
                    (151.413, 119.546, 151.413, 120.10),
                    (151.413, 120.10, 153.214, 120.10),
                    (153.214, 120.10, 153.214, 117.746),
                ]
            ),
        ),
        ("combo_xc1_east_fjump", b_combo_xc1_shift_fjump),
    ]

    best = None
    for name, builder in trials:
        try:
            u, h, n = try_fix(name, builder)
            results.append((h, u, n))
            if u == 0 and h == 0:
                best = name
                break
        except Exception as e:
            print(f"{name:28} EXCEPTION {e}")
            results.append((99, 99, name))

    print("--- ranking (hard, unc, name) ---")
    for r in sorted(results):
        print(r)
    if best:
        print("KEPT SUCCESS:", best, "on", PCB)
        return 0

    # Keep the best partial on the board
    results_sorted = sorted(results)
    if results_sorted:
        winner = results_sorted[0][2]
        print("Re-applying best partial:", winner)
        for name, builder in trials:
            if name == winner:
                try_fix(name, builder)
                break
    return 1


if __name__ == "__main__":
    sys.exit(main())
