#!/usr/bin/env python3
"""MH3 region solve: surgical rip of known segments + whole-region re-route.

Does NOT mass-delete vias. XC1 frozen. GND pour via at (153.5,126.0) RF-safe.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from collections import Counter

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
BAK = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_gnd_closed_ok")
BAK_RUN = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_pre_region_ripup")
BEST = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.best_region_attempt")
OUT = os.path.join(PROJ, "build", "drc_mh3_region.json")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"

MM = pcbnew.FromMM
BC = int(pcbnew.B_Cu)
FC = int(pcbnew.F_Cu)
MH = (155.0, 130.0)
HOLE_R = 1.6
CLEAR_EDGE = 1.4
TW = 0.15

# Stated region (for report)
REGION = "x=[147,161] y=[108,136]"


def TOMM(v):
    return v / 1e6


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def near(a, b, eps=0.15):
    return abs(a - b) < eps


def add_seg(board, x1, y1, x2, y2, lay, net, w):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1, y1))
    t.SetEnd(V(x2, y2))
    t.SetLayer(lay)
    t.SetWidth(MM(w))
    t.SetNet(net)
    board.Add(t)
    return t


def seg_min_dist(x1, y1, x2, y2, px, py):
    dx, dy = x2 - x1, y2 - y1
    l2 = dx * dx + dy * dy
    if l2 < 1e-18:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / l2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def measure_mh(board):
    min_edge = 1e9
    details = []
    for t in board.Tracks():
        if t.GetClass() == "PCB_VIA" or t.GetNetname() not in ("SWDIO", "VBAT_SENSE"):
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        d = seg_min_dist(sx, sy, ex, ey, *MH)
        edge = d - HOLE_R - TOMM(t.GetWidth()) / 2
        if edge < 15:
            details.append((edge, t.GetNetname(), sx, sy, ex, ey))
        min_edge = min(min_edge, edge)
    return min_edge, details


def track_len(board, net, layer=None):
    s = 0.0
    for t in board.Tracks():
        if t.GetClass() == "PCB_VIA" or t.GetNetname() != net:
            continue
        if layer is not None and int(t.GetLayer()) != layer:
            continue
        a, b = t.GetStart(), t.GetEnd()
        s += math.hypot(TOMM(b.x) - TOMM(a.x), TOMM(b.y) - TOMM(a.y))
    return s


def xc1_metrics(board):
    segs = []
    for t in board.Tracks():
        if t.GetClass() == "PCB_VIA" or t.GetNetname() != "XC1" or int(t.GetLayer()) != BC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        segs.append((TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)))
    length = sum(math.hypot(ex - sx, ey - sy) for sx, sy, ex, ey in segs)
    xs = [c for s in segs for c in (s[0], s[2])]
    ys = [c for s in segs for c in (s[1], s[3])]
    bbox = (max(xs) - min(xs)) * (max(ys) - min(ys)) if xs else 0.0
    return length, bbox


def min_w(board, net):
    ws = [TOMM(t.GetWidth()) for t in board.Tracks() if t.GetClass() != "PCB_VIA" and t.GetNetname() == net]
    return (min(ws), max(ws)) if ws else (None, None)


def run_drc():
    subprocess.run(
        [KCLI, "pcb", "drc", "--format", "json", "--refill-zones", "-o", OUT, PCB],
        capture_output=True,
    )
    d = json.load(open(OUT, encoding="utf-8"))
    unc = d.get("unconnected_items", [])
    viol = d.get("violations", [])
    return (
        unc,
        [v for v in viol if v.get("severity") == "error"],
        [v for v in viol if v.get("severity") == "warning"],
        viol,
    )


def add_keepout(board, r):
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
        chain.Append(MM(MH[0] + r * math.cos(ang)), MM(MH[1] + r * math.sin(ang)))
    chain.SetClosed(True)
    z.Outline().AddOutline(chain)
    z.SetHatchStyle(pcbnew.ZONE_BORDER_DISPLAY_STYLE_NO_HATCH)
    try:
        z.SetZoneName("MH3_copper_keepout")
    except Exception:
        pass
    board.Add(z)


def surgical_delete(board):
    """Delete only the baseline segments we replace. Preserve all vias except
    recreate GND pour via (153.5,126)."""
    to_del = []
    n = 0
    for t in list(board.Tracks()):
        if t.GetClass() == "PCB_VIA":
            if t.GetNetname() == "GND":
                p = t.GetPosition()
                x, y = TOMM(p.x), TOMM(p.y)
                if near(x, 153.5, 0.05) and near(y, 126.0, 0.15):
                    to_del.append(t)
            continue
        if int(t.GetLayer()) != BC:
            continue
        net = t.GetNetname()
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)

        kill = False
        if net == "SWDIO":
            if near(sx, 154.2) and near(ex, 154.2) and min(sy, ey) < 120 and max(sy, ey) > 130:
                kill = True
            if near(sy, 132.5) and near(ey, 132.5) and near(max(sx, ex), 154.2) and min(sx, ex) < 140:
                kill = True
        if net == "VBAT_SENSE":
            if near(sx, 155.92) and near(ex, 155.92) and min(sy, ey) < 120 and max(sy, ey) > 130:
                kill = True
            if near(sy, 134.0) and near(ey, 134.0) and near(max(sx, ex), 155.92) and min(sx, ex) < 140:
                kill = True
        if net == "1V9_A":
            if near(min(sx, ex), 138.49, 0.15) and near(max(sx, ex), 152.518, 0.15):
                if near(max(sy, ey), 130.804, 0.15) and near(min(sy, ey), 116.776, 0.15):
                    kill = True
        if net == "PGOOD":
            if near(min(sx, ex), 142.545, 0.15) and near(max(sx, ex), 151.892, 0.15):
                if abs(max(sy, ey) - 126.13) < 0.15 and abs(min(sy, ey) - 116.784) < 0.15:
                    kill = True
        if net == "GND":
            if near(sx, 152.5) and near(ex, 152.5):
                if near(min(sy, ey), 118.52, 0.2) and near(max(sy, ey), 126.0, 0.2):
                    kill = True
            if near(sy, 126.0) and near(ey, 126.0):
                if near(min(sx, ex), 152.5, 0.2) and near(max(sx, ex), 153.5, 0.2):
                    kill = True
        if kill:
            to_del.append(t)
            n += 1
    for t in to_del:
        board.Remove(t)
    return n


def rebuild(board, nets, cfg):
    """
    Whole-region topology (designed together):

    XC1: UNTOUCHED original B path (length/loop unchanged).

    VBAT_SENSE: leave 155.92 immediately west at y=vb_y (<=116.40) BEFORE
      XC1 NE crosses x=155.92 at ~y=117.45. Column vb_col (~149.3) clears MH
      and sits WEST of SWDIO.

    SWDIO: from (154.2,118.469) horizontal west at sw_hy to sw_col (~150.6)
      EAST of VBAT so H does not cross VBAT V; vertical to sw_south (~135.2)
      BELOW VBAT south H at 134; then west to 128. Avoids GND via (150.0,129.5)
      by using x>=150.5.

    1V9_A: U-detour at v19_x (~147.1) width 0.15, floor y=115.2 — west of both
      columns and of PGOOD V, south of early VBAT H.

    PGOOD (explicit): no diagonal through west columns. Path:
      (142.545,126.13) -> (pg_x,126.13) -> (pg_x,115.2) -> (151.892,115.2)
      -> (151.892,116.784). pg_x ~148.0 is east of nRESET x=146.6 (no cross of
      nRESET V 116.1-121.35), west of VBAT col, and separated from 1V9 V.

    GND: spoke VIP (152.5,118.52)->(152.5,126)->(153.5,126) + via (153.5,126).
      RF-safe (no south move).

    SWDCLK / nRESET / BTN: left intact (not surgically deleted).
    """
    swdio, vbat, n19, pgood, gnd = (
        nets["SWDIO"],
        nets["VBAT_SENSE"],
        nets["1V9_A"],
        nets["PGOOD"],
        nets["GND"],
    )
    vb_col = cfg["vb_col"]
    sw_col = cfg["sw_col"]
    v19_x = cfg["v19_x"]
    pg_x = cfg["pg_x"]
    vb_y = cfg["vb_y"]
    sw_hy = cfg["sw_hy"]
    sw_south = cfg["sw_south"]
    vb_south = cfg["vb_south"]
    w19 = cfg["w19"]

    paths = {}

    # GND
    paths["GND"] = [
        ((152.500, 118.520), (152.500, 126.000)),
        ((152.500, 126.000), (153.500, 126.000)),
    ]
    for (a, b), (c, d) in paths["GND"]:
        add_seg(board, a, b, c, d, BC, gnd, 0.12)
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(V(153.500, 126.000))
    v.SetDrill(MM(0.20))
    v.SetWidth(MM(0.45))
    try:
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
    except Exception:
        pass
    v.SetNet(gnd)
    board.Add(v)

    # SWDIO
    paths["SWDIO"] = [
        ((154.200, 118.469), (154.200, sw_hy)),
        ((154.200, sw_hy), (sw_col, sw_hy)),
        ((sw_col, sw_hy), (sw_col, sw_south)),
        ((sw_col, sw_south), (128.000, sw_south)),
    ]
    for (a, b), (c, d) in paths["SWDIO"]:
        add_seg(board, a, b, c, d, BC, swdio, TW)

    # VBAT_SENSE
    paths["VBAT_SENSE"] = [
        ((155.920, 116.962), (155.920, vb_y)),
        ((155.920, vb_y), (vb_col, vb_y)),
        ((vb_col, vb_y), (vb_col, vb_south)),
        ((vb_col, vb_south), (129.203, vb_south)),
    ]
    # If vb_y == 116.962, first seg zero — skip
    for (a, b), (c, d) in paths["VBAT_SENSE"]:
        if abs(a - c) < 1e-9 and abs(b - d) < 1e-9:
            continue
        add_seg(board, a, b, c, d, BC, vbat, TW)

    # 1V9
    paths["1V9_A"] = [
        ((138.490, 130.804), (v19_x, 130.804)),
        ((v19_x, 130.804), (v19_x, 115.200)),
        ((v19_x, 115.200), (152.518, 115.200)),
        ((152.518, 115.200), (152.518, 116.776)),
    ]
    for (a, b), (c, d) in paths["1V9_A"]:
        add_seg(board, a, b, c, d, BC, n19, w19)

    # PGOOD — designed around columns + nRESET
    paths["PGOOD"] = [
        ((142.545, 126.130), (pg_x, 126.130)),
        ((pg_x, 126.130), (pg_x, 115.200)),
        ((pg_x, 115.200), (151.892, 115.200)),
        ((151.892, 115.200), (151.892, 116.784)),
    ]
    for (a, b), (c, d) in paths["PGOOD"]:
        if abs(a - c) < 1e-9 and abs(b - d) < 1e-9:
            continue
        add_seg(board, a, b, c, d, BC, pgood, TW)

    if cfg.get("keep_r"):
        add_keepout(board, cfg["keep_r"])

    return paths


def fix_silk(board, log):
    targets = {
        "Q3": (125.50, 140.00),
        "R10": (136.50, 128.50),
        "R11": (115.00, 127.50),
        "R25": (128.00, 141.00),
        "U3": (117.00, 124.00),
    }
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref not in targets:
            continue
        r = fp.Reference()
        old = (TOMM(r.GetPosition().x), TOMM(r.GetPosition().y))
        nx, ny = targets[ref]
        r.SetPosition(V(nx, ny))
        try:
            r.SetVisible(True)
        except Exception:
            pass
        log.append(f"{ref} ({old[0]:.2f},{old[1]:.2f})->({nx:.2f},{ny:.2f})")


def main():
    os.makedirs(os.path.join(PROJ, "build"), exist_ok=True)
    if not os.path.isfile(BAK_RUN):
        if os.path.isfile(PCB):
            shutil.copy2(PCB, BAK_RUN)
    print("Backup:", BAK_RUN)
    print("Region:", REGION)
    print(
        "Baseline judgment: best_mh3 residual EASIER than best_a_e "
        "(1 packing cluster + via y vs RF, vs multi-net PGOOD cascade). "
        "Rebuild from bak_gnd_closed_ok with surgical rip + region topology."
    )
    sys.stdout.flush()

    configs = [
        dict(
            name="R1",
            vb_col=149.30,
            sw_col=150.60,
            v19_x=147.10,
            pg_x=148.00,
            vb_y=116.35,
            sw_hy=118.55,
            sw_south=135.20,
            vb_south=134.00,
            w19=0.15,
            keep_r=3.00,
        ),
        dict(
            name="R2",
            vb_col=149.20,
            sw_col=150.55,
            v19_x=147.00,
            pg_x=147.90,
            vb_y=116.30,
            sw_hy=118.60,
            sw_south=135.30,
            vb_south=134.00,
            w19=0.15,
            keep_r=3.00,
        ),
        dict(
            name="R3",
            vb_col=149.40,
            sw_col=150.70,
            v19_x=147.20,
            pg_x=148.10,
            vb_y=116.40,
            sw_hy=118.50,
            sw_south=135.10,
            vb_south=134.00,
            w19=0.15,
            keep_r=3.00,
        ),
        dict(
            name="R4",
            vb_col=149.10,
            sw_col=150.50,
            v19_x=146.90,
            pg_x=147.80,
            vb_y=116.35,
            sw_hy=118.55,
            sw_south=135.40,
            vb_south=134.00,
            w19=0.15,
            keep_r=None,
        ),
        dict(
            name="R5",
            vb_col=149.50,
            sw_col=150.80,
            v19_x=147.30,
            pg_x=148.20,
            vb_y=116.25,
            sw_hy=118.70,
            sw_south=135.20,
            vb_south=134.00,
            w19=0.15,
            keep_r=3.00,
        ),
        dict(
            name="R6",
            vb_col=149.00,
            sw_col=150.40,
            v19_x=146.80,
            pg_x=147.70,
            vb_y=116.35,
            sw_hy=118.55,
            sw_south=135.50,
            vb_south=134.00,
            w19=0.15,
            keep_r=3.10,
        ),
    ]

    best = None
    for cfg in configs:
        name = cfg["name"]
        print(f"\n========== TRY {name} ==========")
        sys.stdout.flush()
        shutil.copy2(BAK, PCB)
        board = pcbnew.LoadBoard(PCB)
        nets = {}
        for fp in board.GetFootprints():
            for p in fp.Pads():
                n = p.GetNetname()
                if n and n not in nets:
                    nets[n] = p.GetNet()

        xc1_0 = xc1_metrics(board)
        rf0 = track_len(board, "RF_FEED", FC)
        w0 = min_w(board, "1V9_A")

        ndel = surgical_delete(board)
        print(f"  surgical deleted segs/vias: {ndel}")
        paths = rebuild(board, nets, cfg)
        silk = []
        fix_silk(board, silk)

        print("  filling...")
        sys.stdout.flush()
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        board.Save(PCB)

        xc1_1 = xc1_metrics(board)
        rf1 = track_len(board, "RF_FEED", FC)
        w1 = min_w(board, "1V9_A")
        min_edge, details = measure_mh(board)
        unc, errs, warns, viol = run_drc()

        print(f"  min_edge={min_edge:.3f} unc={len(unc)} err={len(errs)} warn={len(warns)}")
        print(f"  XC1 len {xc1_0[0]:.3f}->{xc1_1[0]:.3f} loop {xc1_0[1]:.3f}->{xc1_1[1]:.3f}")
        print(f"  RF dL={rf1-rf0:.4f} 1V9w {w0}->{w1}")
        print("  types", dict(Counter(v.get("type") for v in viol).most_common()[:10]))
        for v in errs[:15]:
            items = v.get("items", [])
            descs = [i.get("description", "")[:80] for i in items]
            p = items[0].get("pos", {}) if items else {}
            print(f"   ERR {v.get('type')}: {' | '.join(descs)} @({p.get('x')},{p.get('y')})")
        for v in warns[:8]:
            items = v.get("items", [])
            print(f"   WARN {v.get('type')}: {' | '.join(i.get('description','')[:55] for i in items)}")
        sys.stdout.flush()

        sc = (
            (0 if len(unc) == 0 else 1000)
            + len(errs) * 10
            + len(warns) * 3
            + (0 if min_edge >= CLEAR_EDGE - 1e-3 else 50)
            + abs(rf1 - rf0) * 100
            + abs(xc1_1[0] - xc1_0[0]) * 100
        )
        meta = {
            "cfg": cfg,
            "paths": paths,
            "silk": silk,
            "xc1": (xc1_0, xc1_1),
            "rf": (rf0, rf1),
            "w19": (w0, w1),
        }
        if best is None or sc < best[0]:
            best = (sc, name, min_edge, meta, details)
            shutil.copy2(PCB, BEST)
            print(f"  -> best score={sc}")

        if len(unc) == 0 and len(errs) == 0 and min_edge >= CLEAR_EDGE - 1e-3 and len(warns) == 0:
            print("SUCCESS")
            break

    shutil.copy2(BEST, PCB)
    unc, errs, warns, viol = run_drc()
    board = pcbnew.LoadBoard(PCB)
    min_edge, details = measure_mh(board)
    meta = best[3]

    print("\n" + "=" * 60)
    success = len(unc) == 0 and len(errs) == 0 and min_edge >= CLEAR_EDGE - 1e-3 and len(warns) == 0
    print("RESULT:", "SUCCESS" if success else "PARTIAL_BEST")
    print("Config:", best[1])
    print(f"min_edge={min_edge:.3f} unc={len(unc)} err={len(errs)} warn={len(warns)}")
    print("XC1 before/after (len, loop_bbox):", meta["xc1"])
    print("RF:", meta["rf"], "delta", meta["rf"][1] - meta["rf"][0])
    print("1V9 widths:", meta["w19"])
    print("Silk moves:", meta["silk"])
    print("Topology paths:", meta["paths"])
    for edge, net, sx, sy, ex, ey in sorted(details)[:14]:
        print(f"  MH {net} ({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f}) edge={edge:.3f}")
    for v in errs:
        items = v.get("items", [])
        descs = [i.get("description", "")[:100] for i in items]
        p = items[0].get("pos", {}) if items else {}
        print(f" ERR {v.get('type')}: {' | '.join(descs)} @({p.get('x')},{p.get('y')})")
    for v in warns:
        items = v.get("items", [])
        print(f" WARN {v.get('type')}: {' | '.join(i.get('description','')[:80] for i in items)}")
    for u in unc:
        print(" UNCONN", [i.get("description", "")[:90] for i in u.get("items", [])])

    print("\n=== continuity ===")
    for name_n in (
        "SWDIO",
        "SWDCLK",
        "VBAT_SENSE",
        "VBAT",
        "1V9_A",
        "PGOOD",
        "nRESET",
        "BTN_SIDE_BACK",
        "XC1",
        "RF_FEED",
        "GND",
    ):
        pads = []
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if p.GetNetname() == name_n:
                    pp = p.GetPosition()
                    pads.append((fp.GetReference(), p.GetNumber(), TOMM(pp.x), TOMM(pp.y)))
        pads.sort(key=lambda x: (x[2], x[3]))
        if pads:
            print(
                f"{name_n}: {pads[0][0]}.{pads[0][1]}@({pads[0][2]:.3f},{pads[0][3]:.3f}) .. "
                f"{pads[-1][0]}.{pads[-1][1]}@({pads[-1][2]:.3f},{pads[-1][3]:.3f}) n={len(pads)}"
            )

    if not success:
        print("\nBLOCKER ASSESSMENT: see user report.")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
