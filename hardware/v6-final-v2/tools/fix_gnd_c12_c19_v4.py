#!/usr/bin/env python3
"""v4: Fix C12-2 / C19-2 without shorting nRESET or XC1.

C12:
  Move BS-BACK upper B rail 109.55 -> 110.15 (between pad band and nRESET
  at 110.65). Via-in-pad + B spoke to GND via (150.55, 110.18) along y=109.52.

C19:
  F.Cu ONLY (B under pad is XC1 — no via-in-pad).
  Detour: pad -> (152.50,117.40) -> (147.70,117.40) -> existing GND via
  (147.70,118.52). Stays below XC1 (y≈118.64) and above 1V9_A (~116.8),
  clear of XC2 corner at ~118.0.
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


def near(a, b, eps=0.035):
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

    # ---- C12: move upper BS-BACK cage 109.55 -> 110.15 ----
    NEW_Y = 110.15
    OLD_Y = 109.55
    moved = 0

    for t in board.GetTracks():
        if t.GetNetname() != "BTN_SIDE_BACK":
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            x, y = TOMM(p.x), TOMM(p.y)
            if near(x, 150.10, 0.06) and near(y, OLD_Y, 0.04):
                t.SetPosition(V(x, NEW_Y))
                moved += 1
                print(f"  BS via -> ({x:.2f},{NEW_Y:.2f})")
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        nsy, ney = sy, ey
        ch = False
        lay = int(t.GetLayer())
        if lay == BC:
            if near(sy, OLD_Y) and near(ey, OLD_Y) and abs(sx - ex) > 1.0:
                if min(sx, ex) < 150.5 and max(sx, ex) > 146.0:
                    nsy = ney = NEW_Y
                    ch = True
            if near(sx, 146.75, 0.08) and near(ex, 146.75, 0.08):
                if near(sy, OLD_Y):
                    nsy = NEW_Y
                    ch = True
                if near(ey, OLD_Y):
                    ney = NEW_Y
                    ch = True
        if lay == FC:
            if near(sy, OLD_Y) and 149.7 <= sx <= 151.0:
                nsy = NEW_Y
                ch = True
            if near(ey, OLD_Y) and 149.7 <= ex <= 151.0:
                ney = NEW_Y
                ch = True
            if near(sy, OLD_Y) and near(ey, OLD_Y) and min(sx, ex) > 149.5:
                nsy = ney = NEW_Y
                ch = True
        if ch:
            t.SetStart(V(sx, nsy))
            t.SetEnd(V(ex, ney))
            moved += 1
            print(f"  BS ({sx:.2f},{sy:.2f})-({ex:.2f},{ey:.2f}) -> y {nsy:.2f}/{ney:.2f}")

    # Connect via@110.00 to horizontal@NEW_Y if needed
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(146.75, 110.0))
    t.SetEnd(V(146.75, NEW_Y))
    t.SetLayer(BC)
    t.SetWidth(MM(0.10))
    t.SetNet(bs)
    board.Add(t)
    print(f"  BS stub 146.75: 110.00->{NEW_Y:.2f}")
    print(f"BS moves: {moved}+stub")

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

    print("=== C12 ===")
    add_via(148.00, 109.52, gnd)
    # B path: stay at y=109.52 (band 109.10..110.15), then up to GND via
    # Stop horizontal at x=150.20 to keep off BS via at 150.10,110.15, then
    # dogleg to (150.55,110.18)
    add_seg(148.00, 109.52, 150.20, 109.52, BC, gnd, 0.10)
    add_seg(150.20, 109.52, 150.55, 109.52, BC, gnd, 0.10)
    add_seg(150.55, 109.52, 150.55, 110.18, BC, gnd, 0.10)
    print("  VIP + B dogleg to GND via 150.55,110.18")

    print("=== C19 (F only) ===")
    # Avoid XC1 B under pad — no via
    # y=117.40 clears XC2 (~117.97+) with 0.10 track better than 117.80
    wpts = [
        (152.50, 118.52),
        (152.50, 117.40),
        (147.70, 117.40),
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
        print("  UNCONN", [i.get("description", "")[:50] for i in u.get("items", [])])
    hard = []
    for v in viol:
        if v.get("severity") != "error":
            continue
        p = v.get("items", [{}])[0].get("pos", {})
        print(
            f"  ERR {v.get('type')}: {v.get('description', '')[:100]} "
            f"@({p.get('x')},{p.get('y')})"
        )
        if v.get("type") in {
            "shorting_items",
            "tracks_crossing",
            "clearance",
            "hole_to_hole",
        }:
            hard.append(v)

    if len(unc) == 0 and not hard:
        print("SUCCESS")
        return 0
    # Allow only pre-existing silk warnings; hard errors fail
    print(f"PARTIAL unc={len(unc)} hard={len(hard)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
