#!/usr/bin/env python3
"""Fix C19-2 GND island on main hakai_mouse_v6.kicad_pcb (not backup).

Strategy:
  1) Remove XC1 B.Cu diagonal that runs through C19 pad2
     (151.413,119.546)-(153.214,117.746).
  2) Reroute XC1 B around the crystal-area B congestion by going
     WEST first (clear of PGOOD/SWDIO/VBAT_SENSE diagonals), NORTH
     past 1V9/VBAT, EAST past VBAT_SENSE, then SOUTH to the existing
     XC1 B join:
       via @151.413,119.546
         -> H to x=148.50
         -> V to y=114.80
         -> H to x=157.20
         -> V to y=117.746
         -> H to existing join @155.623,117.746
  3) Place GND via-in-pad on C19-2 @152.50,118.52 so F pad
     reaches B.Cu GND pour once XC1 is off the pad.

Does not touch pcb_final_proto_backup.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter

import pcbnew

V6 = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(V6, "hakai_mouse_v6.kicad_pcb")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
OUT = os.path.join(V6, "build", "drc_after_c19_clean.json")

VIA_D, VIA_DRILL = 0.45, 0.20
MM = pcbnew.FromMM
BC = int(pcbnew.B_Cu)

# Detour waypoints (mm)
X_WEST = 148.50
Y_NORTH = 114.80
X_EAST = 157.20
Y_JOIN = 117.746
X_JOIN = 155.623
X_VIA, Y_VIA = 151.413, 119.546


def TOMM(v):
    return v / 1e6


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def near(a, b, eps=0.05):
    return abs(a - b) < eps


def main():
    print("Loading", PCB)
    board = pcbnew.LoadBoard(PCB)

    nets = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if n and n not in nets:
                nets[n] = p.GetNet()
    gnd, xc1 = nets["GND"], nets["XC1"]

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

    # --- 1) Remove XC1 B diagonal under C19 + any prior experimental segs ---
    removed = 0
    for t in list(board.Tracks()):
        if t.GetClass() == "PCB_VIA":
            if t.GetNetname() == "GND":
                p = t.GetPosition()
                if near(TOMM(p.x), 152.50, 0.05) and near(TOMM(p.y), 118.52, 0.05):
                    board.Remove(t)
                    removed += 1
                    print("removed prior GND VIP @ C19-2")
            continue
        if t.GetNetname() != "XC1":
            continue
        if int(t.GetLayer()) != BC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)

        # Original diagonal under C19 pad2
        is_diag = (
            near(sx, 151.413, 0.05)
            and near(sy, 119.546, 0.05)
            and near(ex, 153.214, 0.05)
            and near(ey, 117.746, 0.05)
        ) or (
            near(ex, 151.413, 0.05)
            and near(ey, 119.546, 0.05)
            and near(sx, 153.214, 0.05)
            and near(sy, 117.746, 0.05)
        )
        # Any prior detour / experiment segments we may have added
        is_prior = (
            near(sx, X_WEST, 0.15)
            or near(ex, X_WEST, 0.15)
            or near(sx, X_EAST, 0.15)
            or near(ex, X_EAST, 0.15)
            or near(sy, Y_NORTH, 0.15)
            or near(ey, Y_NORTH, 0.15)
            or near(sy, 115.50, 0.15)
            or near(ey, 115.50, 0.15)
            or near(sx, 156.30, 0.15)
            or near(ex, 156.30, 0.15)
            or (
                near(sx, 153.214, 0.05)
                and near(ex, 153.214, 0.05)
                and min(sy, ey) < 117.2
            )
            or (
                near(sx, 151.413, 0.05)
                and near(ex, 151.413, 0.05)
                and min(sy, ey) < 117.0
            )
            or (
                near(sx, 151.413, 0.05)
                and near(sy, 119.546, 0.05)
                and near(ex, 153.214, 0.08)
                and ey < 118.0
            )
            or (
                near(ex, 151.413, 0.05)
                and near(ey, 119.546, 0.05)
                and near(sx, 153.214, 0.08)
                and sy < 118.0
            )
        )

        if is_diag or is_prior:
            board.Remove(t)
            removed += 1
            print(f"XC1: removed B ({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f})")

    print(f"removed {removed} track(s)")

    # --- 2) XC1 B detour: west -> north -> east -> south to join ---
    add_seg(X_VIA, Y_VIA, X_WEST, Y_VIA, BC, xc1, 0.15)
    add_seg(X_WEST, Y_VIA, X_WEST, Y_NORTH, BC, xc1, 0.15)
    add_seg(X_WEST, Y_NORTH, X_EAST, Y_NORTH, BC, xc1, 0.15)
    add_seg(X_EAST, Y_NORTH, X_EAST, Y_JOIN, BC, xc1, 0.15)
    add_seg(X_EAST, Y_JOIN, X_JOIN, Y_JOIN, BC, xc1, 0.15)
    print(
        f"XC1: B detour west={X_WEST} north={Y_NORTH} east={X_EAST} -> join {X_JOIN},{Y_JOIN}"
    )

    # --- 3) C19-2 GND via-in-pad ---
    add_via(152.50, 118.52, gnd)
    print("C19: GND via-in-pad @ (152.50, 118.52)")

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
            "copper_edge_clearance",
        }:
            hard.append(v)
    for u in unc:
        print(" UNCONN", [i.get("description", "")[:80] for i in u.get("items", [])])

    ok = len(unc) == 0 and not hard
    print("SUCCESS" if ok else f"PARTIAL unc={len(unc)} hard={len(hard)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
