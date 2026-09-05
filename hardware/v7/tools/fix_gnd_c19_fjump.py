#!/usr/bin/env python3
"""Close C19 GND island: deepen VBAT_SENSE B bow + short B spoke from VIP.

Restores bak_pre_gnd_fjump (C19 VIP + XC1 L + SWDIO dogleg + mild VBAT bow).
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
BAK = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_pre_gnd_fjump")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
OUT = os.path.join(PROJ, "build", "drc_after_gnd_fjump.json")

MM = pcbnew.FromMM
BC = int(pcbnew.B_Cu)
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


def near(a, b, eps=0.1):
    return abs(a - b) < eps


def add_seg(board, x1, y1, x2, y2, lay, net, w):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1, y1))
    t.SetEnd(V(x2, y2))
    t.SetLayer(lay)
    t.SetWidth(MM(w))
    t.SetNet(net)
    board.Add(t)


def main():
    if os.path.isfile(BAK):
        shutil.copy2(BAK, PCB)
        print("Restored", BAK)

    board = pcbnew.LoadBoard(PCB)
    nets = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if n and n not in nets:
                nets[n] = p.GetNet()
    gnd, vbat_s = nets["GND"], nets["VBAT_SENSE"]

    # Remove existing VBAT bow segments from prior fix
    # (155.920)-(153.329) H may stay; remove (153.329,116.962)-(146.5,123.5)
    # and (146.5,123.5)-far if present
    vbat_far = None
    to_del = []
    for t in list(board.Tracks()):
        if t.GetClass() == "PCB_VIA":
            continue
        if t.GetNetname() != "VBAT_SENSE":
            continue
        if int(t.GetLayer()) != BC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        # bow first leg
        if (
            near(sx, 153.329, 0.15)
            and near(sy, 116.962, 0.15)
            and near(ex, 146.5, 0.3)
            and near(ey, 123.5, 0.3)
        ) or (
            near(ex, 153.329, 0.15)
            and near(ey, 116.962, 0.15)
            and near(sx, 146.5, 0.3)
            and near(sy, 123.5, 0.3)
        ):
            to_del.append(t)
            print(f"rm VBAT bow1 ({sx:.2f},{sy:.2f})-({ex:.2f},{ey:.2f})")
        # bow second leg to far
        elif (near(sx, 146.5, 0.3) and near(sy, 123.5, 0.3)) or (
            near(ex, 146.5, 0.3) and near(ey, 123.5, 0.3)
        ):
            if abs(sx - ex) > 5 or abs(sy - ey) > 5:
                if near(sx, 146.5, 0.3):
                    vbat_far = (ex, ey)
                else:
                    vbat_far = (sx, sy)
                to_del.append(t)
                print(f"rm VBAT bow2 far={vbat_far}")
        # original long diagonal if still present
        elif (
            near(sx, 153.329, 0.15)
            and near(sy, 116.962, 0.15)
            and abs(sx - ex) > 10
        ) or (
            near(ex, 153.329, 0.15)
            and near(ey, 116.962, 0.15)
            and abs(sx - ex) > 10
        ):
            if near(sx, 153.329, 0.15):
                vbat_far = (ex, ey)
            else:
                vbat_far = (sx, sy)
            to_del.append(t)
            print("rm VBAT long diag")

    for t in to_del:
        board.Remove(t)

    if vbat_far is None:
        # default far end from earlier board knowledge
        vbat_far = (135.380, 134.911)
        print("using default vbat_far", vbat_far)

    # Deeper SW bow: at y=118.52 VBAT x ~149.7 so west spoke to 151.5 is free
    add_seg(board, 153.329, 116.962, 145.00, 120.50, BC, vbat_s, 0.15)
    add_seg(board, 145.00, 120.50, vbat_far[0], vbat_far[1], BC, vbat_s, 0.15)
    print(f"VBAT: deeper bow via (145,120.5) -> {vbat_far}")

    # Short B spoke from C19 VIP into pour (west)
    add_seg(board, 152.50, 118.52, 151.40, 118.52, BC, gnd, 0.12)
    print("GND: B spoke west from VIP to x=151.40")

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
    print(
        f"DRC unconnected={len(unc)} viol={len(viol)} "
        f"sev={dict(Counter(v.get('severity') for v in viol))}"
    )
    print("types", dict(Counter(v.get("type") for v in viol).most_common()))
    hard = []
    for v in viol:
        if v.get("severity") != "error":
            continue
        items = v.get("items", [])
        descs = [i.get("description", "")[:95] for i in items]
        p = items[0].get("pos", {}) if items else {}
        print(f" ERR {v.get('type')}: {' | '.join(descs)} @({p.get('x')},{p.get('y')})")
        if v.get("type") in HARD:
            hard.append(v)
    for u in unc:
        print(" UNCONN", [i.get("description", "")[:80] for i in u.get("items", [])])

    ok = len(unc) == 0 and not hard
    print("SUCCESS" if ok else f"PARTIAL unc={len(unc)} hard={len(hard)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
