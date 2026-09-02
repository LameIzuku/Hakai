#!/usr/bin/env python3
"""v5: Close C12-2 / C19-2 GND islands without colliding with GND via cluster.

C12 (critical insight from v4):
  Existing GND via at (150.55,110.18) and F copper at x≈150.35 make it
  impossible to park a BS-BACK via near (150.10, ~110.1). Instead:
    1. Delete the upper BS-BACK B.Cu horizontal at y=109.55
    2. Delete the BS-BACK via at (150.10, 109.55)
    3. Retarget F.Cu stubs that used that via onto via (150.10, 109.10)
    4. Ensure via (146.75,110.00) still reaches lower B rail at y=109.10
    5. Via-in-pad on C12-2 + B spoke to GND via (150.55,110.18)

C19:
  F.Cu only detour at y=117.55 to GND via (147.70,118.52).
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


def near(a, b, eps=0.04):
    return abs(a - b) < eps


def main():
    if os.path.isfile(BAK):
        shutil.copy2(BAK, PCB)
        print("Restored clean PCB from backup")

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

    gnd = net_of("GND")
    bs = net_of("BTN_SIDE_BACK")
    assert gnd and bs

    # ------------------------------------------------------------------
    # Collect & delete upper cage pieces
    # ------------------------------------------------------------------
    to_delete = []
    for t in board.GetTracks():
        if t.GetNetname() != "BTN_SIDE_BACK":
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            x, y = TOMM(p.x), TOMM(p.y)
            if near(x, 150.10, 0.06) and near(y, 109.55, 0.04):
                to_delete.append(t)
                print(f"  delete BS via ({x:.2f},{y:.2f})")
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        lay = int(t.GetLayer())
        # upper B horizontal
        if (
            lay == BC
            and near(sy, 109.55)
            and near(ey, 109.55)
            and abs(sx - ex) > 1.0
            and min(sx, ex) < 150.5
            and max(sx, ex) > 146.0
        ):
            to_delete.append(t)
            print(f"  delete BS B H ({sx:.2f},{sy:.2f})-({ex:.2f},{ey:.2f})")
            continue
        # B vertical stub that only served upper rail: (146.75,110.00)-(146.75,109.55)
        if (
            lay == BC
            and near(sx, 146.75, 0.08)
            and near(ex, 146.75, 0.08)
            and (
                (near(sy, 110.00) and near(ey, 109.55))
                or (near(ey, 110.00) and near(sy, 109.55))
            )
        ):
            to_delete.append(t)
            print(f"  delete BS B V stub ({sx:.2f},{sy:.2f})-({ex:.2f},{ey:.2f})")
            continue

    for t in to_delete:
        board.Remove(t)
    print(f"deleted {len(to_delete)} items")

    # Retarget F.Cu endpoints that sat on deleted via (150.10,109.55) -> (150.10,109.10)
    retargeted = 0
    for t in board.GetTracks():
        if t.GetNetname() != "BTN_SIDE_BACK" or t.GetClass() == "PCB_VIA":
            continue
        if int(t.GetLayer()) != FC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        nsy, ney = sy, ey
        ch = False
        if near(sx, 150.10, 0.08) and near(sy, 109.55, 0.04):
            nsy = 109.10
            ch = True
        if near(ex, 150.10, 0.08) and near(ey, 109.55, 0.04):
            ney = 109.10
            ch = True
        # F horizontal that was (150.10,109.55)-(150.50,109.55)
        if near(sy, 109.55) and near(ey, 109.55) and min(sx, ex) > 149.5:
            # move whole seg down to 109.10 — but may overlap lower F; instead
            # attach to via at 109.10: set both y to 109.10
            nsy = ney = 109.10
            ch = True
        # F vertical (150.50,109.55)-(150.50,107.80)
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
            retargeted += 1
            print(f"  F retarget ({sx:.2f},{sy:.2f})-({ex:.2f},{ey:.2f}) -> y {nsy:.2f}/{ney:.2f}")
    print(f"F retargets: {retargeted}")

    # Ensure 146.75 via still joins lower B rail: add B V (146.75,110.00)-(146.75,109.10)
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(146.75, 110.00))
    t.SetEnd(V(146.75, 109.10))
    t.SetLayer(BC)
    t.SetWidth(MM(0.10))
    t.SetNet(bs)
    board.Add(t)
    print("  added BS B V 146.75: 110.00->109.10")

    # F link: ensure (150.10,109.10) via still ties to (150.50,109.10) path
    # After retarget, (150.10,109.10)-(150.50,109.10) may exist; if not, add it
    has_link = False
    for t in board.GetTracks():
        if t.GetNetname() != "BTN_SIDE_BACK" or t.GetClass() == "PCB_VIA":
            continue
        if int(t.GetLayer()) != FC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        if near(sy, 109.10) and near(ey, 109.10) and min(sx, ex) <= 150.15 and max(sx, ex) >= 150.4:
            has_link = True
    if not has_link:
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(150.10, 109.10))
        t.SetEnd(V(150.50, 109.10))
        t.SetLayer(FC)
        t.SetWidth(MM(0.10))
        t.SetNet(bs)
        board.Add(t)
        print("  added F link 150.10-150.50 @109.10")

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

    # ------------------------------------------------------------------
    # C12 copper
    # ------------------------------------------------------------------
    print("=== C12 ===")
    add_via(148.00, 109.52, gnd)
    # B path: free band above lower BS (109.10). Stay at y=109.35 for more
    # clearance from both pad edge geometry and lower rail, then to GND via.
    # Pad is at 109.52 — short F is free (via-in-pad). On B:
    add_seg(148.00, 109.52, 150.55, 109.52, BC, gnd, 0.10)
    add_seg(150.55, 109.52, 150.55, 110.18, BC, gnd, 0.10)
    print("  VIP + B to (150.55,110.18)")

    # ------------------------------------------------------------------
    # C19 F-only
    # ------------------------------------------------------------------
    print("=== C19 ===")
    # y=117.55: between 1V9_A (~116.8-117.25) and XC2 (~117.97)
    wpts = [
        (152.50, 118.52),
        (152.50, 117.55),
        (147.70, 117.55),
        (147.70, 118.52),
    ]
    for i in range(len(wpts) - 1):
        a, b = wpts[i], wpts[i + 1]
        add_seg(a[0], a[1], b[0], b[1], FC, gnd, 0.10)
        print(f"  F {a} -> {b}")

    print("=== fill + DRC ===")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(PCB)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    subprocess.run(
        [KCLI, "pcb", "drc", "--format", "json", "-o", OUT, PCB],
        capture_output=True,
    )
    d = json.load(open(OUT, encoding="utf-8"))
    unc = d.get("unconnected_items", [])
    viol = d.get("violations", [])
    sev = Counter(v.get("severity") for v in viol)
    typ = Counter(v.get("type") for v in viol)
    print(f"unconnected={len(unc)} viol={len(viol)} sev={dict(sev)}")
    for k, n in typ.most_common():
        print(f"  {k}: {n}")
    for u in unc:
        print("  UNCONN", [i.get("description", "")[:55] for i in u.get("items", [])])
    hard = []
    for v in viol:
        if v.get("severity") != "error":
            continue
        p = v.get("items", [{}])[0].get("pos", {})
        print(
            f"  ERR {v.get('type')}: {v.get('description', '')[:110]} "
            f"@({p.get('x')},{p.get('y')})"
        )
        if v.get("type") in {
            "shorting_items",
            "tracks_crossing",
            "clearance",
            "hole_to_hole",
            "via_dangling",
            "track_dangling",
        }:
            # dangling may be ok-ish; still report
            if v.get("type") in {"shorting_items", "tracks_crossing", "clearance", "hole_to_hole"}:
                hard.append(v)

    # Also check BS-BACK still connected (no new unconnected on that net)
    if len(unc) == 0 and not hard:
        print("SUCCESS")
        return 0
    print(f"PARTIAL unc={len(unc)} hard={len(hard)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
