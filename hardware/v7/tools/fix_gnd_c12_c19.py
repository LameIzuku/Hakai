#!/usr/bin/env python3
"""Fix the two fab-blocking GND islands: C12-2 and C19-2.

Strategy (from USAGE_MANUAL §6 + geometry probe):
  C12-2 (148.000, 109.520) is boxed by BTN_SIDE_BACK B.Cu horizontals at
  y≈109.10 / 109.55 and STAT B.Cu at y≈108.60. Shove the BS-BACK pair, then
  via-in-pad + B hop and/or F spoke to nearby GND vias.
  C19-2 (152.500, 118.520) gets an F.Cu spoke south-east toward the existing
  GND via at (153.500, 122.500), with alternate via-in-pad plans.

Safe: backs up first externally. Refills zones. Reports DRC unconnected count.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
OUT_DRC = os.path.join(PROJ, "build", "drc_after_gnd_fix.json")

VIA_D, VIA_DRILL = 0.45, 0.20
CLR = 0.15
FINE_NETS = {
    "STAT", "nRESET", "DCC", "DEC4_6", "VBAT_EN", "XL1", "DEC3", "XL2", "ANT",
    "BTN_RIGHT", "BTN_SIDE_FWD", "BTN_SIDE_BACK", "ENC_B", "1V9_A", "XC1", "XC2",
}
FC, BC = int(pcbnew.F_Cu), int(pcbnew.B_Cu)
MM = pcbnew.FromMM


def TOMM(v):
    return v / 1e6


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _ccw(A, B, C):
    return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])


def _inter(A, B, C, D):
    return _ccw(A, C, D) != _ccw(B, C, D) and _ccw(A, B, C) != _ccw(A, B, D)


def seg_seg_dist(a1, a2, b1, b2):
    if _inter(a1, a2, b1, b2):
        return 0.0
    return min(
        seg_dist(*b1, *a1, *a2),
        seg_dist(*b2, *a1, *a2),
        seg_dist(*a1, *b1, *b2),
        seg_dist(*a2, *b1, *b2),
    )


def box_pt_dist(px, py, cx, cy, hx, hy):
    dx = max(abs(px - cx) - hx, 0.0)
    dy = max(abs(py - cy) - hy, 0.0)
    return math.hypot(dx, dy)


def box_seg_dist(x1, y1, x2, y2, cx, cy, hx, hy):
    L = math.hypot(x2 - x1, y2 - y1)
    n = max(2, int(L / 0.05) + 1)
    return min(
        box_pt_dist(x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n, cx, cy, hx, hy)
        for k in range(n + 1)
    )


class BoardModel:
    def __init__(self, board: pcbnew.BOARD):
        self.board = board
        self.netobj: dict[str, pcbnew.NETINFO_ITEM] = {}
        self.items: list = []
        self.holes: list = []
        self.courts: list = []
        self._rebuild()
        for ref, half in (("U4", 3.9), ("U2", 2.1), ("U5", 3.0)):
            for fp in board.GetFootprints():
                if fp.GetReference() == ref:
                    bb = fp.GetBoundingBox(False, False)
                    cx, cy = TOMM(bb.GetCenter().x), TOMM(bb.GetCenter().y)
                    self.courts.append((cx - half, cy - half, cx + half, cy + half))

    def _rebuild(self):
        self.items.clear()
        self.holes.clear()
        self.netobj.clear()
        for t in self.board.GetTracks():
            net = t.GetNetname() or ""
            if net:
                self.netobj[net] = t.GetNet()
            if t.GetClass() == "PCB_VIA":
                p = t.GetPosition()
                # KiCad 10: GetWidth needs layer; use GetWidth(F_Cu) fallback
                try:
                    w = TOMM(t.GetWidth(pcbnew.F_Cu))
                except Exception:
                    w = VIA_D
                self.items.append(("disk", TOMM(p.x), TOMM(p.y), w / 2, net))
                self.holes.append((TOMM(p.x), TOMM(p.y), VIA_DRILL / 2))
            else:
                s, e = t.GetStart(), t.GetEnd()
                self.items.append(
                    (
                        "seg",
                        int(t.GetLayer()),
                        TOMM(s.x),
                        TOMM(s.y),
                        TOMM(e.x),
                        TOMM(e.y),
                        TOMM(t.GetWidth()) / 2,
                        net,
                    )
                )
        for fp in self.board.GetFootprints():
            for p in fp.Pads():
                net = p.GetNetname() or "#NC"
                if p.GetNetname():
                    self.netobj[p.GetNetname()] = p.GetNet()
                pos = p.GetPosition()
                bb = p.GetBoundingBox()
                dr = p.GetDrillSize()
                if dr.x > 0:
                    self.holes.append(
                        (TOMM(pos.x), TOMM(pos.y), max(TOMM(dr.x), TOMM(dr.y)) / 2)
                    )
                lays = [l for l in (FC, BC) if p.IsOnLayer(l)]
                self.items.append(
                    (
                        "box",
                        TOMM(pos.x),
                        TOMM(pos.y),
                        TOMM(bb.GetWidth()) / 2,
                        TOMM(bb.GetHeight()) / 2,
                        net,
                        tuple(lays),
                    )
                )

    def in_court(self, x, y):
        return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in self.courts)

    def req(self, net, other, x, y):
        if self.in_court(x, y):
            return 0.072
        a = 0.075 if net in FINE_NETS else CLR
        b = 0.075 if other in FINE_NETS else CLR
        return max(a, b)

    def seg_clear(self, lay, x1, y1, x2, y2, hw, net, margin=0.015, skip_nets=None):
        skip_nets = skip_nets or set()
        worst = None
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        for it in self.items:
            if it[0] == "seg":
                _, l2, a1, b1, a2, b2, hw2, net2 = it
                if l2 != lay or net2 == net or net2 in skip_nets:
                    continue
                d = seg_seg_dist((x1, y1), (x2, y2), (a1, b1), (a2, b2)) - hw - hw2
            elif it[0] == "disk":
                _, x, y, r, net2 = it
                if net2 == net or net2 in skip_nets:
                    continue
                d = seg_dist(x, y, x1, y1, x2, y2) - hw - r
            else:
                _, x, y, hx2, hy2, net2, lays = it
                if net2 == net or net2 in skip_nets or lay not in lays:
                    continue
                # Own-net pads allowed to touch; other pads must clear
                d = box_seg_dist(x1, y1, x2, y2, x, y, hx2, hy2) - hw
            need = self.req(net, net2, mx, my) + margin
            if d < need and (worst is None or d < worst[0]):
                worst = (d, need, it)
        return worst

    def via_clear(self, x, y, net, margin=0.015, skip_nets=None):
        skip_nets = skip_nets or set()
        worst = None
        for it in self.items:
            if it[0] == "seg":
                _, l2, a1, b1, a2, b2, hw2, net2 = it
                if net2 == net or net2 in skip_nets:
                    continue
                d = seg_dist(x, y, a1, b1, a2, b2) - VIA_D / 2 - hw2
            elif it[0] == "disk":
                _, ax, ay, r, net2 = it
                if net2 == net or net2 in skip_nets:
                    continue
                d = math.hypot(x - ax, y - ay) - VIA_D / 2 - r
            else:
                _, ax, ay, hx2, hy2, net2, lays = it
                if net2 == net or net2 in skip_nets:
                    continue
                d = box_pt_dist(x, y, ax, ay, hx2, hy2) - VIA_D / 2
            need = self.req(net, net2, x, y) + margin
            if d < need and (worst is None or d < worst[0]):
                worst = (d, need, it)
        for hx, hy, hr in self.holes:
            d = math.hypot(x - hx, y - hy) - VIA_DRILL / 2 - hr
            if d < 0.20 + margin and (worst is None or d < worst[0]):
                worst = (d, 0.20 + margin, "hole")
        return worst

    def add_seg(self, x1, y1, x2, y2, lay, net, w):
        t = pcbnew.PCB_TRACK(self.board)
        t.SetStart(V(x1, y1))
        t.SetEnd(V(x2, y2))
        t.SetLayer(lay)
        t.SetWidth(MM(w))
        t.SetNet(self.netobj[net])
        self.board.Add(t)
        self.items.append(("seg", lay, x1, y1, x2, y2, w / 2, net))

    def add_via(self, x, y, net):
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(V(x, y))
        v.SetDrill(MM(VIA_DRILL))
        try:
            v.SetWidth(MM(VIA_D))
        except TypeError:
            # KiCad 10 layer-aware width
            v.SetWidth(pcbnew.F_Cu, MM(VIA_D))
            v.SetWidth(pcbnew.B_Cu, MM(VIA_D))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(self.netobj[net])
        self.board.Add(v)
        self.items.append(("disk", x, y, VIA_D / 2, net))
        self.holes.append((x, y, VIA_DRILL / 2))


def shove_btn_side_back(board):
    """Push BTN_SIDE_BACK B.Cu horizontals that trap C12-2."""
    # Target: move y=109.10 -> 108.70 and y=109.55 -> 109.95 to open band ~109.2-109.7
    moves = [(109.10, 108.70), (109.55, 109.95)]
    sh = 0
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA" or t.GetNetname() != "BTN_SIDE_BACK":
            continue
        if int(t.GetLayer()) != BC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        for oldy, newy in moves:
            # full horizontal at oldy in C12 corridor
            if abs(sy - oldy) < 0.03 and abs(ey - oldy) < 0.03 and abs(sx - ex) > 1.0:
                # only if spans x near C12
                if min(sx, ex) < 149.5 and max(sx, ex) > 146.0:
                    t.SetStart(V(sx, newy))
                    t.SetEnd(V(ex, newy))
                    sh += 1
                    continue
            if abs(sy - oldy) < 0.03 and 145.5 < sx < 151.0:
                t.SetStart(V(sx, newy))
                sh += 1
            if abs(ey - oldy) < 0.03 and 145.5 < ex < 151.0:
                t.SetEnd(V(ex, newy))
                sh += 1
    # Also nudge STAT B.Cu south a hair if present at 108.60 spanning C12
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA" or t.GetNetname() != "STAT":
            continue
        if int(t.GetLayer()) != BC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        if abs(sy - 108.60) < 0.03 and abs(ey - 108.60) < 0.03 and abs(sx - ex) > 2.0:
            if min(sx, ex) < 148.5 and max(sx, ex) > 145.0:
                t.SetStart(V(sx, 108.25))
                t.SetEnd(V(ex, 108.25))
                sh += 1
                print(f"  STAT B horizontal shifted 108.60 -> 108.25")
    print(f"shoves applied: {sh}")
    return sh


def try_plans(m: BoardModel, net, w, plans, label):
    for pi, plan in enumerate(plans):
        ok = True
        for step in plan:
            if step[0] == "via":
                wr = m.via_clear(step[1], step[2], net, margin=0.01)
            else:
                # ("seg", lay, x1,y1,x2,y2)
                wr = m.seg_clear(
                    step[1], step[2], step[3], step[4], step[5], w / 2, net, margin=0.01
                )
            if wr is not None:
                desc = str(wr[2])[:60]
                print(f"  {label} p{pi} blocked: {desc} d={wr[0]:.3f}<{wr[1]:.3f}")
                ok = False
                break
        if ok:
            for step in plan:
                if step[0] == "via":
                    m.add_via(step[1], step[2], net)
                    print(f"  + VIA GND @ ({step[1]:.3f},{step[2]:.3f})")
                else:
                    m.add_seg(step[2], step[3], step[4], step[5], step[1], net, w)
                    print(
                        f"  + SEG GND L{step[1]} "
                        f"({step[2]:.3f},{step[3]:.3f})-({step[4]:.3f},{step[5]:.3f}) w={w}"
                    )
            print(f"  {label}: plan {pi} COMMITTED")
            return True
    return False


def main():
    print(f"Loading {PCB}")
    board = pcbnew.LoadBoard(PCB)
    # Ensure GND net exists
    gnd = None
    for n in board.GetNetInfo().NetsByName():
        if str(n) == "GND" or (hasattr(n, "GetNetname") and n.GetNetname() == "GND"):
            gnd = n
    # NetsByName returns map-like; use footprint pad
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname() == "GND":
                gnd = p.GetNet()
                break
        if gnd:
            break
    if gnd is None:
        print("ERROR: no GND net")
        return 2

    print("=== Shove blocking tracks ===")
    shove_btn_side_back(board)

    m = BoardModel(board)
    if "GND" not in m.netobj:
        m.netobj["GND"] = gnd

    # Pad centers from pcbnew:
    # C12-2 GND (148.000, 109.520)
    # C19-2 GND (152.500, 118.520)
    # Nearby GND vias: (150.55,110.18), (151.60,109.58), (152.642,109.48),
    #                  (153.5,122.5), (147.7,118.52), (147.1,119.32)

    print("=== C12-2 GND plans ===")
    c12_ok = try_plans(
        m,
        "GND",
        0.15,
        [
            # via-in-pad on C12-2 + B east to existing GND via neighborhood
            [
                ("via", 148.00, 109.52),
                ("seg", BC, 148.00, 109.52, 150.55, 109.52),
                ("seg", BC, 150.55, 109.52, 150.55, 110.18),
            ],
            [
                ("via", 148.00, 109.52),
                ("seg", BC, 148.00, 109.52, 151.60, 109.52),
                ("seg", BC, 151.60, 109.52, 151.60, 109.58),
            ],
            [
                ("via", 148.00, 109.52),
                ("seg", BC, 148.00, 109.52, 152.64, 109.52),
                ("seg", BC, 152.64, 109.52, 152.64, 109.48),
            ],
            # F.Cu spoke east to existing F GND track/via at (150.55,110.18)
            [
                ("seg", FC, 148.00, 109.52, 148.00, 110.18),
                ("seg", FC, 148.00, 110.18, 150.55, 110.18),
            ],
            [
                ("seg", FC, 148.00, 109.52, 150.55, 109.52),
                ("seg", FC, 150.55, 109.52, 150.55, 110.18),
            ],
            # via slightly south of pad into freed band
            [
                ("via", 148.00, 109.30),
                ("seg", FC, 148.00, 109.52, 148.00, 109.30),
                ("seg", BC, 148.00, 109.30, 150.55, 109.30),
                ("seg", BC, 150.55, 109.30, 150.55, 110.18),
            ],
            [
                ("via", 148.00, 109.70),
                ("seg", FC, 148.00, 109.52, 148.00, 109.70),
                ("seg", BC, 148.00, 109.70, 150.55, 109.70),
                ("seg", BC, 150.55, 109.70, 150.55, 110.18),
            ],
            # west hop to GND via (146.5, 105) region — longer
            [
                ("via", 147.40, 109.52),
                ("seg", FC, 148.00, 109.52, 147.40, 109.52),
                ("seg", BC, 147.40, 109.52, 147.40, 106.23),
                ("seg", BC, 147.40, 106.23, 147.75, 106.23),
            ],
        ],
        "C12",
    )

    print("=== C19-2 GND plans ===")
    c19_ok = try_plans(
        m,
        "GND",
        0.15,
        [
            # direct SE to documented GND via (153.5, 122.5)
            [
                ("seg", FC, 152.50, 118.52, 153.50, 118.52),
                ("seg", FC, 153.50, 118.52, 153.50, 122.50),
            ],
            [
                ("seg", FC, 152.50, 118.52, 152.50, 122.50),
                ("seg", FC, 152.50, 122.50, 153.50, 122.50),
            ],
            [
                ("via", 152.50, 118.52),
                ("seg", BC, 152.50, 118.52, 153.50, 118.52),
                ("seg", BC, 153.50, 118.52, 153.50, 122.50),
            ],
            [
                ("via", 152.50, 118.52),
                ("seg", BC, 152.50, 118.52, 152.50, 122.50),
                ("seg", BC, 152.50, 122.50, 153.50, 122.50),
            ],
            # west to GND vias at (147.7, 118.52)
            [
                ("seg", FC, 152.50, 118.52, 147.70, 118.52),
            ],
            [
                ("via", 152.50, 118.52),
                ("seg", BC, 152.50, 118.52, 147.70, 118.52),
            ],
            # south then east avoiding SPI_MOSI at y≈120
            [
                ("seg", FC, 152.50, 118.52, 152.50, 121.00),
                ("seg", FC, 152.50, 121.00, 153.50, 121.00),
                ("seg", FC, 153.50, 121.00, 153.50, 122.50),
            ],
            [
                ("seg", FC, 152.50, 118.52, 151.20, 118.52),
                ("seg", FC, 151.20, 118.52, 151.20, 122.50),
                ("seg", FC, 151.20, 122.50, 153.50, 122.50),
            ],
            # via south of pad
            [
                ("via", 152.50, 120.00),
                ("seg", FC, 152.50, 118.52, 152.50, 120.00),
                ("seg", BC, 152.50, 120.00, 153.50, 120.00),
                ("seg", BC, 153.50, 120.00, 153.50, 122.50),
            ],
            [
                ("via", 153.00, 118.52),
                ("seg", FC, 152.50, 118.52, 153.00, 118.52),
                ("seg", BC, 153.00, 118.52, 153.50, 122.50),
            ],
        ],
        "C19",
    )

    # Brute force grid: place a GND via near each pad and short track if clearance ok
    if not c12_ok:
        print("=== C12 brute via grid ===")
        c12_ok = brute_via_spoke(m, 148.00, 109.52, "C12")
    if not c19_ok:
        print("=== C19 brute via grid ===")
        c19_ok = brute_via_spoke(m, 152.50, 118.52, "C19")

    print(f"Results: C12={c12_ok} C19={c19_ok}")

    # Zone refill
    print("=== Zone fill ===")
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    board.Save(PCB)
    print(f"Saved {PCB}")

    # DRC
    os.makedirs(os.path.dirname(OUT_DRC), exist_ok=True)
    r = subprocess.run(
        [KCLI, "pcb", "drc", "--format", "json", "-o", OUT_DRC, PCB],
        capture_output=True,
        text=True,
    )
    print(f"kicad-cli drc exit={r.returncode}")
    if r.stderr:
        print(r.stderr[-500:])
    if not os.path.isfile(OUT_DRC):
        print("No DRC file produced")
        return 1
    d = json.load(open(OUT_DRC, encoding="utf-8"))
    unc = d.get("unconnected_items", [])
    viol = d.get("violations", [])
    from collections import Counter

    sev = Counter(v.get("severity") for v in viol)
    typ = Counter(v.get("type") for v in viol)
    print(f"DRC unconnected={len(unc)} violations={len(viol)} sev={dict(sev)}")
    for k, n in typ.most_common(12):
        print(f"  {k}: {n}")
    for u in unc[:10]:
        ds = [i.get("description", "")[:50] for i in u.get("items", [])]
        print("  UNCONN:", " | ".join(ds))
    for v in viol:
        if v.get("severity") == "error":
            print("  ERR:", v.get("type"), v.get("description", "")[:80])

    if len(unc) == 0:
        print("SUCCESS: unconnected=0")
        return 0
    print("PARTIAL: still have unconnected items")
    return 1


def brute_via_spoke(m: BoardModel, px, py, label):
    """Search nearby for a free via site + short F/B spoke from pad."""
    candidates = []
    for dx in [i * 0.15 for i in range(-12, 13)]:
        for dy in [i * 0.15 for i in range(-12, 13)]:
            if abs(dx) < 0.05 and abs(dy) < 0.05:
                # via-in-pad
                candidates.append((px, py, True))
            else:
                candidates.append((px + dx, py + dy, False))
    # prefer closer first
    candidates.sort(key=lambda c: math.hypot(c[0] - px, c[1] - py))

    for vx, vy, vip in candidates:
        for layer, w in ((FC, 0.15), (BC, 0.15), (FC, 0.10), (BC, 0.10)):
            # via clear
            if m.via_clear(vx, vy, "GND", margin=0.008) is not None:
                continue
            # spoke from pad to via on F always (pad is F.Cu SMD)
            if vip:
                # via-in-pad: just via; zone/B should connect — still need B escape
                # try free B ray to nearest existing GND via-ish region
                escapes = [
                    (vx + 2.0, vy),
                    (vx - 2.0, vy),
                    (vx, vy + 2.0),
                    (vx, vy - 2.0),
                    (vx + 2.5, vy + 0.5),
                    (150.55, 110.18),
                    (151.60, 109.58),
                    (153.50, 122.50),
                    (147.70, 118.52),
                ]
                for ex, ey in escapes:
                    if m.seg_clear(BC, vx, vy, ex, ey, w / 2, "GND", margin=0.008) is None:
                        m.add_via(vx, vy, "GND")
                        m.add_seg(vx, vy, ex, ey, BC, "GND", w)
                        print(f"  {label} brute VIP+B ({vx:.2f},{vy:.2f})->({ex:.2f},{ey:.2f})")
                        return True
                # via alone (zone may connect after refill if pour can reach)
                m.add_via(vx, vy, "GND")
                print(f"  {label} brute VIP only ({vx:.2f},{vy:.2f}) — zone may connect")
                return True
            else:
                # F spoke pad->via then hope zone on B, or B spokes from via
                if m.seg_clear(FC, px, py, vx, vy, w / 2, "GND", margin=0.008) is not None:
                    continue
                # Prefer ending near existing GND copper — always add via so B pour ties in
                m.add_seg(px, py, vx, vy, FC, "GND", w)
                m.add_via(vx, vy, "GND")
                print(f"  {label} brute F+via ({px:.2f},{py:.2f})->({vx:.2f},{vy:.2f})")
                return True
    print(f"  {label} brute FAILED")
    return False


if __name__ == "__main__":
    sys.exit(main())
