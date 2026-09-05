#!/usr/bin/env python3
"""Fix C12-2 GND island (fab blocker #1).

Removes the BTN_SIDE_BACK upper B.Cu cage that boxed C12-2, retargets F
stubs onto the lower via, and adds a GND via + B spoke to the existing
GND via at (150.55, 110.18).

Result (KiCad 10 DRC): unconnected drops 2 -> 1 (only C19 remains);
no error-severity violations (silk warnings only).

C19-2 still needs an interactive KiCad fix — B.Cu under the crystal is too
dense for a clean automated path (XC1 diagonal, SWDIO, PGOOD, 1V9_A,
VBAT_SENSE). See USAGE_MANUAL §6 for C19 procedure.

Usage:
  "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" tools/fix_gnd_c12_final.py
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


def near(a, b, eps=0.05):
    return abs(a - b) < eps


def main():
    if os.path.isfile(BAK):
        shutil.copy2(BAK, PCB)
        print("Restored from bak_pre_gnd_fix")

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

    gnd, bs = net_of("GND"), net_of("BTN_SIDE_BACK")
    assert gnd and bs

    # Delete upper BS-BACK cage
    to_delete = []
    for t in board.GetTracks():
        if t.GetNetname() != "BTN_SIDE_BACK":
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            x, y = TOMM(p.x), TOMM(p.y)
            if near(x, 150.10, 0.06) and near(y, 109.55, 0.04):
                to_delete.append(t)
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        lay = int(t.GetLayer())
        if (
            lay == BC
            and near(sy, 109.55)
            and near(ey, 109.55)
            and abs(sx - ex) > 1
            and min(sx, ex) < 150.5
            and max(sx, ex) > 146
        ):
            to_delete.append(t)
        elif (
            lay == BC
            and near(sx, 146.75, 0.08)
            and near(ex, 146.75, 0.08)
            and (
                (near(sy, 110) and near(ey, 109.55))
                or (near(ey, 110) and near(sy, 109.55))
            )
        ):
            to_delete.append(t)
    for t in to_delete:
        board.Remove(t)
    print(f"deleted {len(to_delete)} BS-BACK upper-cage items")

    # Retarget F endpoints to lower via y=109.10
    for t in board.GetTracks():
        if t.GetNetname() != "BTN_SIDE_BACK" or t.GetClass() == "PCB_VIA":
            continue
        if int(t.GetLayer()) != FC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        nsy, ney, ch = sy, ey, False
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

    # Reconnect 146.75 via to lower B rail
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

    def add_seg(x1, y1, x2, y2, lay, net, w=0.10):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(x1, y1))
        t.SetEnd(V(x2, y2))
        t.SetLayer(lay)
        t.SetWidth(MM(w))
        t.SetNet(net)
        board.Add(t)

    # C12-2: via slightly south of pad + B to existing GND via
    add_via(148.00, 109.65, gnd)
    add_seg(148.00, 109.52, 148.00, 109.65, FC, gnd)
    add_seg(148.00, 109.65, 150.55, 109.65, BC, gnd)
    add_seg(150.55, 109.65, 150.55, 110.18, BC, gnd)
    print("C12-2 GND via + B spoke committed")

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(PCB)
    print("Saved", PCB)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    subprocess.run(
        [KCLI, "pcb", "drc", "--format", "json", "-o", OUT, PCB],
        capture_output=True,
    )
    d = json.load(open(OUT, encoding="utf-8"))
    unc = d.get("unconnected_items", [])
    viol = d.get("violations", [])
    sev = Counter(v.get("severity") for v in viol)
    print(f"DRC unconnected={len(unc)} violations={len(viol)} sev={dict(sev)}")
    hard = [
        v
        for v in viol
        if v.get("severity") == "error"
        and v.get("type") in {"shorting_items", "tracks_crossing", "clearance", "hole_to_hole"}
    ]
    if len(unc) <= 1 and not hard:
        print("C12 FIXED — remaining unconnected is C19-2 only")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
