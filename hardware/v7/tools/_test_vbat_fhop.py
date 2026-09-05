#!/usr/bin/env python3
"""VBAT via at T + F north-then-west hop; SWDIO pure B west. Combined."""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from collections import Counter

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
BAK = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_gnd_closed_ok")
OUT = os.path.join(PROJ, "build", "drc_fhop.json")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
MM = pcbnew.FromMM
BC = int(pcbnew.B_Cu)
FC = int(pcbnew.F_Cu)
TOMM = lambda v: v / 1e6
MH = (155.0, 130.0)


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def near(a, b, eps=0.12):
    return abs(a - b) < eps


def add_seg(board, x1, y1, x2, y2, lay, net, w):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1, y1))
    t.SetEnd(V(x2, y2))
    t.SetLayer(lay)
    t.SetWidth(MM(w))
    t.SetNet(net)
    board.Add(t)


def add_via(board, x, y, net):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(V(x, y))
    v.SetDrill(MM(0.2))
    v.SetWidth(MM(0.45))
    try:
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
    except Exception:
        pass
    v.SetNet(net)
    board.Add(v)


def main():
    shutil.copy2(BAK, PCB)
    board = pcbnew.LoadBoard(PCB)
    nets = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if n and n not in nets:
                nets[n] = p.GetNet()
    swdio, vbat = nets["SWDIO"], nets["VBAT_SENSE"]

    to_del = []
    for t in list(board.Tracks()):
        if t.GetClass() == "PCB_VIA":
            continue
        if int(t.GetLayer()) != BC:
            continue
        net = t.GetNetname()
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        if net == "SWDIO" and near(sx, 154.20) and near(ex, 154.20) and min(sy, ey) < 120 and max(sy, ey) > 130:
            to_del.append(t)
        elif net == "SWDIO" and near(sy, 132.50) and near(ey, 132.50) and near(max(sx, ex), 154.20) and min(sx, ex) < 140:
            to_del.append(t)
        elif net == "VBAT_SENSE" and near(sx, 155.920) and near(ex, 155.920) and min(sy, ey) < 120 and max(sy, ey) > 130:
            to_del.append(t)
        elif net == "VBAT_SENSE" and near(sy, 134.00) and near(ey, 134.00) and near(max(sx, ex), 155.920) and min(sx, ex) < 140:
            to_del.append(t)
        elif net == "VBAT_SENSE" and near(sx, 129.203) and near(ex, 129.203) and near(min(sy, ey), 134.0) and near(max(sy, ey), 134.911):
            to_del.append(t)
    for t in to_del:
        board.Remove(t)
    print("removed", len(to_del))

    # SWDIO pure B — no VBAT H at 134 anymore, so west column free through y=134
    # Column 148.5 avoids GND via@150; join bus at 135.54; also stitch dangling spur
    add_seg(board, 154.2, 118.469, 154.2, 126.5, BC, swdio, 0.15)
    add_seg(board, 154.2, 126.5, 148.5, 126.5, BC, swdio, 0.15)
    add_seg(board, 148.5, 126.5, 148.5, 135.54, BC, swdio, 0.15)
    add_seg(board, 148.5, 135.54, 136.707, 135.54, BC, swdio, 0.15)
    # reconnect spur at 128 so not dangling (already on bus via 135.54 H existing)
    # existing (128,135.54)-(136.707,135.54) remains

    # VBAT: via at T, F north then west then south to existing via
    # Place via slightly offset if T is crowded: use (155.92, 116.962)
    add_via(board, 155.92, 116.962, vbat)
    # F path - try several corridors
    # North to y=112 (above crystal mess?), west, south
    fpath = [
        # stay near y=116.0 going west carefully — or go north first
        (155.92, 116.962, 155.92, 115.0),
        (155.92, 115.0, 148.0, 115.0),
        (148.0, 115.0, 148.0, 125.0),
        (148.0, 125.0, 140.0, 125.0),
        (140.0, 125.0, 140.0, 134.911),
        (140.0, 134.911, 129.203, 134.911),
    ]
    for a, b, c, d in fpath:
        add_seg(board, a, b, c, d, FC, vbat, 0.15)
    print("VBAT F", fpath)

    # Keepout
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks(True)
    z.SetDoNotAllowVias(False)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowZoneFills(True)
    z.SetDoNotAllowFootprints(False)
    ls = pcbnew.LSET()
    ls.AddLayer(BC)
    ls.AddLayer(FC)
    z.SetLayerSet(ls)
    chain = pcbnew.SHAPE_LINE_CHAIN()
    for i in range(64):
        ang = 2 * math.pi * i / 64
        chain.Append(MM(155 + 3.1 * math.cos(ang)), MM(130 + 3.1 * math.sin(ang)))
    chain.SetClosed(True)
    z.Outline().AddOutline(chain)
    z.SetHatchStyle(pcbnew.ZONE_BORDER_DISPLAY_STYLE_NO_HATCH)
    try:
        z.SetZoneName("MH3_copper_keepout")
    except Exception:
        pass
    board.Add(z)

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(PCB)

    # min edge
    min_edge = 1e9
    for t in board.Tracks():
        if t.GetNetname() not in ("SWDIO", "VBAT_SENSE"):
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            x, y = TOMM(p.x), TOMM(p.y)
            edge = math.hypot(x - 155, y - 130) - 1.6 - 0.225
            min_edge = min(min_edge, edge)
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        dx, dy = ex - sx, ey - sy
        l2 = dx * dx + dy * dy
        if l2 < 1e-18:
            d = math.hypot(sx - 155, sy - 130)
        else:
            tt = max(0, min(1, ((155 - sx) * dx + (130 - sy) * dy) / l2))
            d = math.hypot(155 - (sx + tt * dx), 130 - (sy + tt * dy))
        edge = d - 1.6 - 0.075
        min_edge = min(min_edge, edge)
    print(f"MIN edge={min_edge:.3f}")

    subprocess.run([KCLI, "pcb", "drc", "--format", "json", "--refill-zones", "-o", OUT, PCB], capture_output=True)
    d = json.load(open(OUT, encoding="utf-8"))
    unc = d.get("unconnected_items", [])
    viol = d.get("violations", [])
    errs = [v for v in viol if v.get("severity") == "error"]
    print(f"unc={len(unc)} err={len(errs)}")
    print("types", dict(Counter(v.get("type") for v in viol).most_common()))
    for v in errs:
        items = v.get("items", [])
        descs = [i.get("description", "")[:100] for i in items]
        p = items[0].get("pos", {}) if items else {}
        print(f" ERR {v.get('type')}: {' | '.join(descs)} @({p.get('x')},{p.get('y')})")
    for u in unc[:5]:
        print(" UNCONN", [i.get("description", "")[:80] for i in u.get("items", [])])


if __name__ == "__main__":
    main()
