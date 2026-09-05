#!/usr/bin/env python3
"""Fix C19-2 GND island on main hakai_mouse_v6.kicad_pcb.

Strategy (B.Cu + via, minimal):
  1) Reroute XC1 B diagonal that runs under C19 pad2 into an L-shape
     that stays west of SWDIO's B diagonal crossing (~x=152.7 @ y=119.55).
  2) Place GND via-in-pad on C19-2.
  3) Short B.Cu spoke west to existing GND via cluster (147.70, 118.52)
     if zone fill alone is not enough.

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
OUT = os.path.join(V6, "build", "drc_after_c19_fix.json")

VIA_D, VIA_DRILL = 0.45, 0.20
MM = pcbnew.FromMM
FC, BC = int(pcbnew.F_Cu), int(pcbnew.B_Cu)


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

    # --- 1) Remove XC1 B diagonal under C19 ---
    removed = 0
    for t in list(board.Tracks()):
        if t.GetClass() == "PCB_VIA":
            continue
        if t.GetNetname() != "XC1":
            continue
        if int(t.GetLayer()) != BC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        # diagonal (151.413,119.546)-(153.214,117.746)
        if (
            near(sx, 151.413, 0.05)
            and near(sy, 119.546, 0.05)
            and near(ex, 153.214, 0.05)
            and near(ey, 117.746, 0.05)
        ) or (
            near(ex, 151.413, 0.05)
            and near(ey, 119.546, 0.05)
            and near(sx, 153.214, 0.05)
            and near(sy, 117.746, 0.05)
        ):
            board.Remove(t)
            removed += 1
            print(f"XC1: removed B diagonal ({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f})")
    print(f"removed {removed} XC1 diagonal(s)")

    # L-shape: H short (clear of SWDIO ~x=152.7 @ y=119.55), V down, H to old joint
    # Join point (153.214, 117.746) still has existing H eastward.
    add_seg(151.413, 119.546, 152.00, 119.546, BC, xc1, 0.15)
    add_seg(152.00, 119.546, 152.00, 117.746, BC, xc1, 0.15)
    add_seg(152.00, 117.746, 153.214, 117.746, BC, xc1, 0.15)
    print("XC1: B L-shape (152.00 column) — clears C19 pad2")

    # --- 2) C19-2 GND via-in-pad ---
    add_via(152.50, 118.52, gnd)
    print("C19: GND via-in-pad @ (152.50, 118.52)")

    # --- 3) Short B spokes toward known GND (try west to 147.7 first — short hops) ---
    # Go west at y=118.52 but stop/start carefully; use dogleg north of PGOOD/1V9 if needed.
    # First attempt: direct B to existing GND via (147.70, 118.52)
    add_seg(152.50, 118.52, 147.70, 118.52, BC, gnd, 0.12)
    print("C19: B spoke west to GND via (147.70, 118.52)")

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
        descs = [i.get("description", "")[:85] for i in items]
        p = items[0].get("pos", {}) if items else {}
        print(f" ERR {v.get('type')}: {' | '.join(descs)} @({p.get('x')},{p.get('y')})")
        if v.get("type") in {
            "shorting_items",
            "tracks_crossing",
            "clearance",
            "hole_to_hole",
        }:
            hard.append(v)
    for u in unc:
        print(" UNCONN", [i.get("description", "")[:60] for i in u.get("items", [])])

    ok = len(unc) == 0 and not hard
    print("SUCCESS" if ok else f"PARTIAL unc={len(unc)} hard={len(hard)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
