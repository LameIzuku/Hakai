#!/usr/bin/env python3
"""v3: Surgical fix for C12-2 / C19-2 GND islands.

C12 strategy
  - Only move BTN_SIDE_BACK *upper* B.Cu cage (y≈109.55) further south to
    y=110.55 so pad (148,109.52) sits in a free band between lower BS-BACK
    (y=109.10) and the moved upper rail — without touching STAT or the
    existing GND via at (150.55,110.18).
  - Via-in-pad on C12-2 + short B.Cu spoke east to that GND via at y=109.52
    (stays clear of the moved rail).

C19 strategy
  - F.Cu spoke north then west to existing GND via (147.70,118.52), skirting
    XC1 at y≈118.64 and SPI_MOSI at y≈120.0.
  - Optional via at the destination only if already present (no new via in
    the dense crystal cage unless clearance allows).

Runs DRC; exits 0 only if unconnected==0 and no error-severity shorts.
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
    # Start from clean backup if present
    if os.path.isfile(BAK):
        import shutil

        shutil.copy2(BAK, PCB)
        print("Restored clean PCB from backup")

    board = pcbnew.LoadBoard(PCB)
    gnd = None
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname() == "GND":
                gnd = p.GetNet()
                break
        if gnd:
            break
    assert gnd

    # ------------------------------------------------------------------
    # 1) Move BS-BACK upper cage: y=109.55 -> y=110.55
    # ------------------------------------------------------------------
    NEW_Y = 110.55
    OLD_Y = 109.55
    moved = 0

    for t in board.GetTracks():
        if t.GetNetname() != "BTN_SIDE_BACK":
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            x, y = TOMM(p.x), TOMM(p.y)
            # only the cage via on the upper horizontal
            if near(x, 150.10, 0.06) and near(y, OLD_Y, 0.04):
                t.SetPosition(V(x, NEW_Y))
                moved += 1
                print(f"  BS via ({x:.2f},{y:.2f}) -> ({x:.2f},{NEW_Y:.2f})")
            continue

        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        nsy, ney = sy, ey
        ch = False
        lay = int(t.GetLayer())

        if lay == BC:
            # upper horizontal
            if near(sy, OLD_Y) and near(ey, OLD_Y) and abs(sx - ex) > 1.0:
                if min(sx, ex) < 150.5 and max(sx, ex) > 146.0:
                    nsy = ney = NEW_Y
                    ch = True
            # vertical stub 146.75: bottom was OLD_Y
            if near(sx, 146.75, 0.08) and near(ex, 146.75, 0.08):
                if near(sy, OLD_Y):
                    nsy = NEW_Y
                    ch = True
                if near(ey, OLD_Y):
                    ney = NEW_Y
                    ch = True
                # if top is 110.0 and bottom moves to 110.55, OK (short south stub)
        if lay == FC:
            # F attachments that sat on via y=109.55 near x=150.1
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
            print(
                f"  BS seg ({sx:.2f},{sy:.2f})-({ex:.2f},{ey:.2f}) "
                f"-> ({sx:.2f},{nsy:.2f})-({ex:.2f},{ney:.2f})"
            )

    # Ensure vertical 146.75 still connects: via at 110.0 to horizontal at NEW_Y
    # If gap, add a B stub
    has_stub = False
    for t in board.GetTracks():
        if t.GetNetname() != "BTN_SIDE_BACK" or t.GetClass() == "PCB_VIA":
            continue
        if int(t.GetLayer()) != BC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        if near(sx, 146.75, 0.08) and near(ex, 146.75, 0.08):
            if (near(sy, 110.0, 0.05) or near(ey, 110.0, 0.05)) and (
                near(sy, NEW_Y, 0.05) or near(ey, NEW_Y, 0.05)
            ):
                has_stub = True
    if not has_stub:
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(146.75, 110.0))
        t.SetEnd(V(146.75, NEW_Y))
        t.SetLayer(BC)
        t.SetWidth(MM(0.10))
        # find BS-BACK net
        bs = None
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if p.GetNetname() == "BTN_SIDE_BACK":
                    bs = p.GetNet()
                    break
            if bs:
                break
        if bs is None:
            for tr in board.GetTracks():
                if tr.GetNetname() == "BTN_SIDE_BACK":
                    bs = tr.GetNet()
                    break
        t.SetNet(bs)
        board.Add(t)
        print("  added BS B stub 146.75: 110.00->110.55")
        moved += 1

    print(f"BS-BACK upper cage moves: {moved}")

    # ------------------------------------------------------------------
    # 2) C12 copper: via-in-pad + B to GND via (150.55, 110.18)
    # ------------------------------------------------------------------
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

    def add_seg(x1, y1, x2, y2, lay, net, w):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(x1, y1))
        t.SetEnd(V(x2, y2))
        t.SetLayer(lay)
        t.SetWidth(MM(w))
        t.SetNet(net)
        board.Add(t)
        return t

    print("=== C12 copper ===")
    # Via in pad
    add_via(148.00, 109.52, gnd)
    # B east along free band (between 109.10 and 110.55), stop short of
    # GND via x then north to via
    # Use 0.12 mm width for a bit more clearance budget
    w = 0.12
    add_seg(148.00, 109.52, 150.55, 109.52, BC, gnd, w)
    add_seg(150.55, 109.52, 150.55, 110.18, BC, gnd, w)
    print("  via-in-pad + B (148,109.52)->(150.55,109.52)->(150.55,110.18)")

    # ------------------------------------------------------------------
    # 3) C19 copper: F detour north of pad then west to GND via 147.70,118.52
    #    Keep y <= 118.20 to clear XC1 at 118.64; keep y >= 117.0 to clear
    #    1V9_A fanout ~116.8
    # ------------------------------------------------------------------
    print("=== C19 copper ===")
    # Waypoints (F.Cu, 0.12 mm)
    # pad (152.50, 118.52) -> (152.50, 117.80) -> (147.70, 117.80) -> (147.70, 118.52)
    wpts = [
        (152.50, 118.52),
        (152.50, 117.80),
        (147.70, 117.80),
        (147.70, 118.52),
    ]
    for i in range(len(wpts) - 1):
        a, b = wpts[i], wpts[i + 1]
        add_seg(a[0], a[1], b[0], b[1], FC, gnd, 0.12)
        print(f"  F ({a[0]:.2f},{a[1]:.2f})-({b[0]:.2f},{b[1]:.2f})")

    # Also via under C19 pad + B hop west if F alone isn't enough for zone
    # Only if we can stay clear: try B path at y=117.80 to via (147.70,118.52)
    add_via(152.50, 118.52, gnd)
    add_seg(152.50, 118.52, 152.50, 117.80, BC, gnd, 0.12)
    add_seg(152.50, 117.80, 147.70, 117.80, BC, gnd, 0.12)
    add_seg(147.70, 117.80, 147.70, 118.52, BC, gnd, 0.12)
    print("  via-in-pad C19 + B detour to (147.70,118.52)")

    # ------------------------------------------------------------------
    # 4) Zone fill + DRC
    # ------------------------------------------------------------------
    print("=== Zone fill ===")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(PCB)
    print("Saved", PCB)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    r = subprocess.run(
        [KCLI, "pcb", "drc", "--format", "json", "-o", OUT, PCB],
        capture_output=True,
        text=True,
    )
    print("kicad-cli exit", r.returncode)
    d = json.load(open(OUT, encoding="utf-8"))
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
    err_n = 0
    for v in viol:
        if v.get("severity") != "error":
            continue
        err_n += 1
        it = v.get("items", [{}])[0]
        p = it.get("pos", {})
        print(
            f"  ERR {v.get('type')}: {v.get('description', '')[:100]} "
            f"@({p.get('x')},{p.get('y')})"
        )

    # Success criteria: no unconnected, no shorting/tracks_crossing/clearance errors
    bad_types = {"shorting_items", "tracks_crossing", "clearance", "hole_to_hole"}
    hard = [
        v
        for v in viol
        if v.get("severity") == "error" and v.get("type") in bad_types
    ]
    if len(unc) == 0 and len(hard) == 0:
        print("SUCCESS: GND islands closed, no hard DRC errors")
        return 0
    print(f"PARTIAL: unc={len(unc)} hard_errors={len(hard)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
