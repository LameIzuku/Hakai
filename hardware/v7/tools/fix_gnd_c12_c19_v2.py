#!/usr/bin/env python3
"""Surgical fix for C12-2 and C19-2 GND islands.

C12: Open the BTN_SIDE_BACK B.Cu cage (horizontals at y=109.10 / 109.55)
     by translating the whole local cage south (+Y) so pad (148,109.52)
     sits in free copper; drop via-in-pad + B spoke to existing GND vias.
C19: Short F.Cu GND spoke pad2 -> C18 pad2 (same Y), else detour to
     GND via (153.5, 122.5).

Does not touch STAT. Restores connectivity of BS-BACK by moving vias + segs together.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from collections import Counter

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
OUT_DRC = os.path.join(PROJ, "build", "drc_after_gnd_fix.json")

VIA_D, VIA_DRILL = 0.45, 0.20
MM = pcbnew.FromMM
FC, BC = int(pcbnew.F_Cu), int(pcbnew.B_Cu)


def TOMM(v):
    return v / 1e6


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def near(a, b, eps=0.04):
    return abs(a - b) < eps


def main():
    print("Load", PCB)
    board = pcbnew.LoadBoard(PCB)

    # ---- locate nets ----
    gnd_net = None
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname() == "GND":
                gnd_net = p.GetNet()
                break
        if gnd_net:
            break
    assert gnd_net is not None

    # ============================================================
    # C12: translate local BTN_SIDE_BACK B cage south (+dy)
    # Cage elements (from probe):
    #   B H (146.10,109.10)-(150.10,109.10)
    #   B H (146.75,109.55)-(150.10,109.55)
    #   B V (146.10,110.65)-(146.10,109.10)
    #   B V (146.75,110.00)-(146.75,109.55)
    #   VIA (150.10,109.10), (150.10,109.55), (146.75,110.00), (146.10,110.65)
    # Also F segs that end on those vias near the cage.
    # Target: shift y=109.10 -> 109.80 and y=109.55 -> 110.25  (dy=+0.70)
    # so pad at 109.52 is north of both horizontals (free band to STAT at 108.6).
    # ============================================================
    DY = 0.70
    y_map = {109.10: 109.10 + DY, 109.55: 109.55 + DY}  # 109.80, 110.25

    def map_y(y):
        for old, new in y_map.items():
            if near(y, old, 0.03):
                return new
        return None

    moved = 0
    # Move B.Cu tracks of BTN_SIDE_BACK in the cage x-range
    for t in board.GetTracks():
        if t.GetNetname() != "BTN_SIDE_BACK":
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            x, y = TOMM(p.x), TOMM(p.y)
            # only cage vias
            if 145.8 <= x <= 150.3 and 108.9 <= y <= 110.8:
                ny = map_y(y)
                if ny is None and near(y, 110.00, 0.03) and near(x, 146.75, 0.05):
                    ny = 110.00 + DY  # 110.70 — vertical top via
                if ny is None and near(y, 110.65, 0.03) and near(x, 146.10, 0.05):
                    ny = 110.65 + DY
                if ny is not None:
                    t.SetPosition(V(x, ny))
                    moved += 1
                    print(f"  via BS-BACK ({x:.2f},{y:.2f})->({x:.2f},{ny:.2f})")
            continue
        if int(t.GetLayer()) != BC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        # cage region
        if not (min(sx, ex) < 150.5 and max(sx, ex) > 145.5 and min(sy, ey) < 111.5 and max(sy, ey) > 108.5):
            continue
        nsy, ney = sy, ey
        my = map_y(sy)
        if my is not None:
            nsy = my
        my = map_y(ey)
        if my is not None:
            ney = my
        # also shift vertical tops that were 110.00 / 110.65 in cage
        if near(sx, ex, 0.02):  # vertical
            if near(sy, 110.00, 0.03) and near(sx, 146.75, 0.1):
                nsy = 110.00 + DY
            if near(ey, 110.00, 0.03) and near(ex, 146.75, 0.1):
                ney = 110.00 + DY
            if near(sy, 110.65, 0.03) and near(sx, 146.10, 0.1):
                nsy = 110.65 + DY
            if near(ey, 110.65, 0.03) and near(ex, 146.10, 0.1):
                ney = 110.65 + DY
            # bottoms already via map_y for 109.10/109.55
        if nsy != sy or ney != ey:
            t.SetStart(V(sx, nsy))
            t.SetEnd(V(ex, ney))
            moved += 1
            print(f"  B seg ({sx:.2f},{sy:.2f})-({ex:.2f},{ey:.2f}) -> ({sx:.2f},{nsy:.2f})-({ex:.2f},{ney:.2f})")

    # F.Cu segments of BS-BACK that attach to cage vias — extend/shift endpoints
    for t in board.GetTracks():
        if t.GetNetname() != "BTN_SIDE_BACK" or t.GetClass() == "PCB_VIA":
            continue
        if int(t.GetLayer()) != FC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        changed = False
        nsy, ney = sy, ey
        # endpoints on old via Ys in cage x
        for old, new in list(y_map.items()) + [(110.00, 110.00 + DY), (110.65, 110.65 + DY)]:
            if near(sy, old, 0.03) and 145.8 <= sx <= 150.6:
                nsy = new
                changed = True
            if near(ey, old, 0.03) and 145.8 <= ex <= 150.6:
                ney = new
                changed = True
        if changed:
            t.SetStart(V(sx, nsy))
            t.SetEnd(V(ex, ney))
            moved += 1
            print(f"  F seg endpoint shift ({sx:.2f},{sy:.2f})-({ex:.2f},{ey:.2f}) -> y {nsy:.2f}/{ney:.2f}")

    print(f"BS-BACK cage moves: {moved}")

    # ---- Add C12 GND via-in-pad + B spoke to GND via (150.55, 110.18) ----
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
        return v

    def add_seg(x1, y1, x2, y2, layer, net, w=0.15):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(x1, y1))
        t.SetEnd(V(x2, y2))
        t.SetLayer(layer)
        t.SetWidth(MM(w))
        t.SetNet(net)
        board.Add(t)
        return t

    print("=== C12 copper ===")
    # Via in pad C12-2
    add_via(148.00, 109.52, gnd_net)
    # B.Cu east then north to existing GND via cluster
    # After cage move, B at y=109.52 should be free between 108.6 STAT and 109.80 BS-BACK
    add_seg(148.00, 109.52, 150.55, 109.52, BC, gnd_net, 0.15)
    add_seg(150.55, 109.52, 150.55, 110.18, BC, gnd_net, 0.15)
    print("  via+B path C12-2 -> (150.55,110.18)")

    # ============================================================
    # C19: connect GND pad to C18 GND pad (same Y=118.52)
    # C18-2 (149.000, 118.520), C19-2 (152.500, 118.520)
    # ============================================================
    print("=== C19 copper ===")
    # Direct horizontal between C18-2 and C19-2
    add_seg(149.00, 118.52, 152.50, 118.52, FC, gnd_net, 0.15)
    print("  F spoke C19-2 <-> C18-2")

    # Also stitch C18/C19 area down to known GND via (153.5,122.5) with B via under C18
    # via at C18 pad2 + B to (153.5,122.5) for zone reliability
    add_via(149.00, 118.52, gnd_net)
    add_seg(149.00, 118.52, 149.00, 122.50, BC, gnd_net, 0.15)
    add_seg(149.00, 122.50, 153.50, 122.50, BC, gnd_net, 0.15)
    print("  via under C18 + B to (153.5,122.5)")

    # Extra: via under C19 + short B south if clear path needed
    add_via(152.50, 118.52, gnd_net)
    add_seg(152.50, 118.52, 152.50, 122.50, BC, gnd_net, 0.15)
    add_seg(152.50, 122.50, 153.50, 122.50, BC, gnd_net, 0.15)
    print("  via under C19 + B to (153.5,122.5)")

    print("=== Zone fill ===")
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    board.Save(PCB)
    print("Saved")

    print("=== DRC ===")
    os.makedirs(os.path.dirname(OUT_DRC), exist_ok=True)
    r = subprocess.run(
        [KCLI, "pcb", "drc", "--format", "json", "-o", OUT_DRC, PCB],
        capture_output=True,
        text=True,
    )
    print("cli exit", r.returncode)
    d = json.load(open(OUT_DRC, encoding="utf-8"))
    unc = d.get("unconnected_items", [])
    viol = d.get("violations", [])
    sev = Counter(v.get("severity") for v in viol)
    typ = Counter(v.get("type") for v in viol)
    print(f"unconnected={len(unc)} violations={len(viol)} sev={dict(sev)}")
    for k, n in typ.most_common():
        print(f"  {k}: {n}")
    for u in unc:
        ds = [i.get("description", "")[:55] for i in u.get("items", [])]
        print("  UNCONN:", " | ".join(ds))
    for v in viol:
        if v.get("severity") == "error":
            items = v.get("items", [])
            pos = ""
            if items:
                p = items[0].get("pos", {})
                pos = f" @({p.get('x')},{p.get('y')})"
            print(f"  ERR {v.get('type')}: {v.get('description','')[:90]}{pos}")

    # connectivity check pads
    board2 = pcbnew.LoadBoard(PCB)
    # refill already saved
    conn = board2.GetConnectivity()
    conn.RecalculateRatsnest()
    for ref in ("C12", "C19", "C18", "C11"):
        for fp in board2.GetFootprints():
            if fp.GetReference() != ref:
                continue
            for p in fp.Pads():
                if p.GetNetname() != "GND":
                    continue
                # count copper items on net near pad — rough
                print(f"  {ref} pad{p.GetNumber()} GND pos=({TOMM(p.GetPosition().x):.3f},{TOMM(p.GetPosition().y):.3f})")

    return 0 if len(unc) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
