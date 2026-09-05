#!/usr/bin/env python3
"""Re-route SWDIO + VBAT_SENSE around MH3 at original (155,130).

XC1 untouched. Optional minor 1V9_A dodge (expanded NE jog). Local GND via relocate.
VBAT: north/west B corridor then woven F-hop past nRESET/PGOOD/1V9, rejoin south.
No pcbnew ZONE_FILLER (hangs on KiCad 10 here) — kicad-cli --refill-zones does it.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
BAK = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_gnd_closed_ok")
BAK_RUN = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_pre_swdio_vbat")
BEST = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.best_swdio_vbat")
OUT = os.path.join(PROJ, "build", "drc_swdio_vbat.json")
GERBER_DIR = os.path.join(PROJ, "gerbers", "swdio_vbat_clean")
BLOCKER = os.path.join(PROJ, "build", "BLOCKERS_swdio_vbat.txt")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"

MM = pcbnew.FromMM
BC = int(pcbnew.B_Cu)
FC = int(pcbnew.F_Cu)
MH = (155.0, 130.0)
HOLE_R = 1.6
CLEAR = 1.4
TW = 0.15


def TOMM(v):
    return v / 1e6


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def near(a, b, eps=0.12):
    return abs(a - b) < eps


def add_seg(board, x1, y1, x2, y2, lay, net, w):
    if abs(x1 - x2) < 1e-9 and abs(y1 - y2) < 1e-9:
        return None
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1, y1))
    t.SetEnd(V(x2, y2))
    t.SetLayer(lay)
    t.SetWidth(MM(w))
    t.SetNet(net)
    board.Add(t)
    return t


def add_via(board, x, y, net, drill=0.20, width=0.45):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(V(x, y))
    v.SetDrill(MM(drill))
    v.SetWidth(MM(width))
    try:
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
    except Exception:
        pass
    v.SetNet(net)
    board.Add(v)
    return v


def seg_dist(x1, y1, x2, y2, px, py):
    dx, dy = x2 - x1, y2 - y1
    l2 = dx * dx + dy * dy
    if l2 < 1e-18:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / l2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def path_length(board, net):
    total = 0.0
    n_via = 0
    vias = []
    segs = []
    for t in board.Tracks():
        if t.GetNetname() != net:
            continue
        if t.GetClass() == "PCB_VIA":
            n_via += 1
            p = t.GetPosition()
            vias.append((round(TOMM(p.x), 3), round(TOMM(p.y), 3)))
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        total += math.hypot(ex - sx, ey - sy)
        lay = "B" if int(t.GetLayer()) == BC else ("F" if int(t.GetLayer()) == FC else "?")
        segs.append((lay, sx, sy, ex, ey, TOMM(t.GetWidth())))
    return total, n_via, vias, segs


def xc1_metrics(board):
    segs = []
    n_via = 0
    for t in board.Tracks():
        if t.GetNetname() != "XC1":
            continue
        if t.GetClass() == "PCB_VIA":
            n_via += 1
            continue
        if int(t.GetLayer()) != BC:
            continue
        s, e = t.GetStart(), t.GetEnd()
        segs.append((TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)))
    length = sum(math.hypot(ex - sx, ey - sy) for sx, sy, ex, ey in segs)
    pts = [(sx, sy) for sx, sy, ex, ey in segs] + [(ex, ey) for sx, sy, ex, ey in segs]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    pts2 = sorted(set((round(x, 4), round(y, 4)) for x, y in pts))
    if len(pts2) < 3:
        return length, 0.0, n_via
    lower = []
    for p in pts2:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts2):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    area = 0.0
    for i in range(len(hull)):
        x1, y1 = hull[i]
        x2, y2 = hull[(i + 1) % len(hull)]
        area += x1 * y2 - x2 * y1
    return length, abs(area) / 2, n_via


def measure_mh(board):
    min_edge = 1e9
    details = []
    for t in board.Tracks():
        net = t.GetNetname()
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            x, y = TOMM(p.x), TOMM(p.y)
            try:
                wr = TOMM(t.GetWidth()) / 2
            except Exception:
                wr = 0.225
            d = math.hypot(x - MH[0], y - MH[1]) - HOLE_R - wr
            if d < CLEAR + 1.0:
                details.append((d, f"VIA:{net}", x, y, x, y))
            min_edge = min(min_edge, d)
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        d = seg_dist(sx, sy, ex, ey, *MH)
        edge = d - HOLE_R - TOMM(t.GetWidth()) / 2
        if net in ("SWDIO", "VBAT_SENSE") or edge < CLEAR + 0.5:
            details.append((edge, net, sx, sy, ex, ey))
        min_edge = min(min_edge, edge)
    return min_edge, details


def closest_approach_to_box(board, net, box):
    x0, y0, x1, y1 = box
    best = 1e9

    def pt_box(px, py):
        dx = max(x0 - px, 0, px - x1)
        dy = max(y0 - py, 0, py - y1)
        return math.hypot(dx, dy)

    for t in board.Tracks():
        if t.GetNetname() != net:
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            best = min(best, pt_box(TOMM(p.x), TOMM(p.y)))
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        for i in range(41):
            tpar = i / 40
            best = min(best, pt_box(sx + tpar * (ex - sx), sy + tpar * (ey - sy)))
    return best


def closest_approach_to_point(board, net, pt):
    px, py = pt
    best = 1e9
    for t in board.Tracks():
        if t.GetNetname() != net:
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            best = min(best, math.hypot(TOMM(p.x) - px, TOMM(p.y) - py))
            continue
        s, e = t.GetStart(), t.GetEnd()
        best = min(best, seg_dist(TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y), px, py))
    return best


def min_width(board, net):
    ws = [
        TOMM(t.GetWidth())
        for t in board.Tracks()
        if t.GetClass() != "PCB_VIA" and t.GetNetname() == net
    ]
    return (min(ws), max(ws)) if ws else (None, None)


def track_len_net(board, net, layer=None):
    s = 0.0
    for t in board.Tracks():
        if t.GetClass() == "PCB_VIA" or t.GetNetname() != net:
            continue
        if layer is not None and int(t.GetLayer()) != layer:
            continue
        a, b = t.GetStart(), t.GetEnd()
        s += math.hypot(TOMM(b.x) - TOMM(a.x), TOMM(b.y) - TOMM(a.y))
    return s


def run_drc():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
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
    try:
        z.SetZoneName("MH3_copper_keepout")
    except Exception:
        pass
    z.SetHatchStyle(pcbnew.ZONE_BORDER_DISPLAY_STYLE_NO_HATCH)
    board.Add(z)


def fix_silk(fp_by_ref, log):
    # Tuned to clear baseline Q3/R10/R11/J3 warnings without edge clash
    targets = {
        "Q3": (124.0, 141.5),
        "R10": (136.5, 128.0),
        "R11": (112.0, 128.5),
        "R25": (130.5, 143.5),
        "U3": (111.0, 127.0),
        "R3": (108.5, 124.5),
        "R1": (133.0, 144.0),
        "J3": (106.0, 129.5),
    }
    for ref, (nx, ny) in targets.items():
        fp = fp_by_ref.get(ref)
        if fp is None:
            continue
        try:
            r = fp.Reference()
            old = (TOMM(r.GetPosition().x), TOMM(r.GetPosition().y))
            r.SetPosition(V(nx, ny))
            try:
                r.SetVisible(True)
            except Exception:
                pass
            log.append(f"{ref} ({old[0]:.2f},{old[1]:.2f})->({nx:.2f},{ny:.2f})")
        except Exception as e:
            log.append(f"{ref} FAIL {e}")


def delete_old(board, do_1v9_ne):
    to_del = []
    for t in list(board.Tracks()):
        if t.GetClass() == "PCB_VIA":
            if t.GetNetname() == "GND":
                p = t.GetPosition()
                x, y = TOMM(p.x), TOMM(p.y)
                if near(x, 150.0, 0.05) and near(y, 129.5, 0.05):
                    to_del.append(t)
            continue
        net = t.GetNetname()
        lay = int(t.GetLayer())
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        kill = False
        if net == "SWDIO" and lay == BC:
            if near(sx, 154.2) and near(ex, 154.2) and min(sy, ey) < 120 and max(sy, ey) > 130:
                kill = True
            if near(sy, 132.5) and near(ey, 132.5) and near(max(sx, ex), 154.2) and min(sx, ex) < 140:
                kill = True
        if net == "VBAT_SENSE" and lay == BC:
            if near(sx, 155.92) and near(ex, 155.92) and min(sy, ey) < 120 and max(sy, ey) > 130:
                kill = True
            if near(sy, 134.0) and near(ey, 134.0) and near(max(sx, ex), 155.92) and min(sx, ex) < 140:
                kill = True
        if do_1v9_ne and net == "1V9_A" and lay == BC:
            # main diagonal blocking west columns
            if near(min(sx, ex), 138.49, 0.15) and near(max(sx, ex), 152.518, 0.15):
                if near(max(sy, ey), 130.804, 0.15) and near(min(sy, ey), 116.776, 0.15):
                    kill = True
            # NE jog that blocks y~116.2-116.8 west escape
            if near(min(sx, ex), 153.124, 0.15) and near(max(sx, ex), 154.127, 0.15):
                if min(sy, ey) > 115.5 and max(sy, ey) < 117.0:
                    kill = True
            if near(min(sx, ex), 152.518, 0.15) and near(max(sx, ex), 153.124, 0.15):
                if near(min(sy, ey), 116.776, 0.15) and near(max(sy, ey), 116.776, 0.15):
                    kill = True
            if near(min(sx, ex), 154.127, 0.15) and near(max(sx, ex), 156.612, 0.15):
                if near(sy, 115.773, 0.15) and near(ey, 115.773, 0.15):
                    kill = True
        if kill:
            to_del.append(t)
    for t in to_del:
        board.Remove(t)
    return len(to_del)


def apply(cfg):
    shutil.copy2(BAK, PCB)
    board = pcbnew.LoadBoard(PCB)

    fp_by_ref = {}
    nets = {}
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        fp_by_ref[ref] = fp
        for p in fp.Pads():
            n = p.GetNetname()
            if n and n not in nets:
                nets[n] = p.GetNet()

    xc1_before = xc1_metrics(board)
    sw_before = path_length(board, "SWDIO")
    vb_before = path_length(board, "VBAT_SENSE")
    rf0 = track_len_net(board, "RF_FEED", FC)
    w19_0 = min_width(board, "1V9_A")

    do_1v9 = cfg.get("do_1v9", True)
    swdio, vbat, n19, gnd = nets["SWDIO"], nets["VBAT_SENSE"], nets["1V9_A"], nets["GND"]

    silk = []
    fix_silk(fp_by_ref, silk)
    print("  silk:", "; ".join(silk) if silk else "(none)")

    keep_r = cfg.get("keep_r")
    if keep_r:
        try:
            add_keepout(board, keep_r)
            print(f"  keepout r={keep_r}")
        except Exception as e:
            print("  keepout skip:", e)

    n_del = delete_old(board, do_1v9)
    print(f"  deleted {n_del} old segments/vias")

    sw_col = cfg["sw_col"]
    sw_gate = cfg["sw_gate"]
    sw_bus_y = cfg.get("sw_bus_y", 132.5)
    vb_early = cfg["vb_early"]
    vb_col = cfg["vb_col"]
    vb_west = cfg["vb_west"]
    vb_f_y1 = cfg["vb_f_y1"]  # F jog y just north of nRESET H@121.35
    vb_via1 = cfg["vb_via1"]
    vb_via2 = cfg["vb_via2"]
    gnd_via = cfg["gnd_via"]
    v19_x = cfg.get("v19_x", 146.0)
    w19 = cfg.get("w19", 0.15)

    sw_path = []
    vb_path = []
    vb_vias = []

    if do_1v9:
        # U-dodge replacing diagonal
        add_seg(board, 138.490, 130.804, v19_x, 130.804, BC, n19, w19)
        add_seg(board, v19_x, 130.804, v19_x, 116.776, BC, n19, w19)
        add_seg(board, v19_x, 116.776, 152.518, 116.776, BC, n19, w19)
        # NE jog rebuild north of VBAT early corridor
        add_seg(board, 156.612, 115.773, 156.612, 114.500, BC, n19, w19)
        add_seg(board, 156.612, 114.500, 152.518, 114.500, BC, n19, w19)
        add_seg(board, 152.518, 114.500, 152.518, 116.776, BC, n19, w19)
        print(f"  1V9_A U+NE dodge x={v19_x} w={w19}")

    add_via(board, gnd_via[0], gnd_via[1], gnd)
    print(f"  GND via -> ({gnd_via[0]:.2f},{gnd_via[1]:.2f})")

    # SWDIO pure B west column + south bus
    sw_segs = [
        (154.200, 118.469, 154.200, sw_gate),
        (154.200, sw_gate, sw_col, sw_gate),
        (sw_col, sw_gate, sw_col, sw_bus_y),
        (sw_col, sw_bus_y, 128.000, sw_bus_y),
    ]
    for a, b, c, d in sw_segs:
        add_seg(board, a, b, c, d, BC, swdio, TW)
        sw_path.append(((a, b), (c, d), "B"))

    # VBAT: early west on B north of XC1/PGOOD, via to F, weave west of nRESET, south, back to B
    vb_b1 = [
        (155.920, 116.962, 155.920, vb_early),
        (155.920, vb_early, vb_col, vb_early),
    ]
    for a, b, c, d in vb_b1:
        add_seg(board, a, b, c, d, BC, vbat, TW)
        vb_path.append(((a, b), (c, d), "B"))
    add_via(board, vb_via1[0], vb_via1[1], vbat)
    vb_vias.append(tuple(vb_via1))

    vb_f = [
        (vb_via1[0], vb_via1[1], vb_col, vb_via1[1]),
        (vb_col, vb_via1[1], vb_col, vb_f_y1),
        (vb_col, vb_f_y1, vb_west, vb_f_y1),
        (vb_west, vb_f_y1, vb_west, vb_via2[1]),
    ]
    # if via1 already at vb_col, skip zero seg
    for a, b, c, d in vb_f:
        add_seg(board, a, b, c, d, FC, vbat, TW)
        vb_path.append(((a, b), (c, d), "F"))
    add_via(board, vb_via2[0], vb_via2[1], vbat)
    vb_vias.append(tuple(vb_via2))

    vb_b2 = [
        (vb_via2[0], vb_via2[1], vb_via2[0], 134.000),
        (vb_via2[0], 134.000, 129.203, 134.000),
    ]
    for a, b, c, d in vb_b2:
        add_seg(board, a, b, c, d, BC, vbat, TW)
        vb_path.append(((a, b), (c, d), "B"))

    print("  saving (zone fill deferred to kicad-cli)...")
    sys.stdout.flush()
    board.Save(PCB)
    print("  saved", os.path.getsize(PCB))
    # Return routing description only. Post-Remove Track iteration is unsafe in
    # this process; caller must measure+DRC in a fresh Python process.
    return {
        "sw_path": sw_path,
        "vb_path": vb_path,
        "vb_vias": vb_vias,
        "v19_x": v19_x if do_1v9 else None,
        "gnd_via": gnd_via,
        "silk": silk,
        "xc1_before": xc1_before,
        "sw_before": sw_before,
        "vb_before": vb_before,
        "rf0": rf0,
        "w19_0": w19_0,
        "cfg": cfg,
        "do_1v9": do_1v9,
    }


def export_gerbers():
    os.makedirs(GERBER_DIR, exist_ok=True)
    subprocess.run(
        [
            KCLI,
            "pcb",
            "export",
            "gerbers",
            "-o",
            GERBER_DIR,
            "--layers",
            "F.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts",
            PCB,
        ],
        capture_output=True,
    )
    subprocess.run(
        [KCLI, "pcb", "export", "drill", "-o", GERBER_DIR, PCB],
        capture_output=True,
    )
    return sorted(os.listdir(GERBER_DIR))


def write_blocker(text):
    os.makedirs(os.path.dirname(BLOCKER), exist_ok=True)
    with open(BLOCKER, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    if not os.path.exists(BAK_RUN):
        shutil.copy2(BAK, BAK_RUN)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak_ts = os.path.join(PROJ, f"hakai_mouse_v6.kicad_pcb.bak_pre_swdio_vbat_{ts}")
    shutil.copy2(BAK, bak_ts)
    print("Backup:", BAK_RUN)
    print("Backup ts:", bak_ts)
    print("Baseline:", BAK)
    sys.stdout.flush()

    configs = [
        dict(
            name="C1",
            sw_col=151.00,
            sw_gate=126.55,
            sw_bus_y=132.50,
            vb_early=116.25,
            vb_col=143.50,
            vb_west=119.50,
            vb_f_y1=120.80,
            vb_via1=(150.00, 116.25),
            vb_via2=(119.50, 128.50),
            gnd_via=(149.20, 127.80),
            keep_r=3.00,
            do_1v9=True,
            v19_x=146.00,
            w19=0.15,
        ),
        dict(
            name="C2",
            sw_col=151.20,
            sw_gate=126.60,
            sw_bus_y=132.50,
            vb_early=116.20,
            vb_col=143.20,
            vb_west=119.00,
            vb_f_y1=120.70,
            vb_via1=(149.50, 116.20),
            vb_via2=(119.00, 128.80),
            gnd_via=(149.00, 127.50),
            keep_r=3.00,
            do_1v9=True,
            v19_x=145.50,
            w19=0.15,
        ),
        dict(
            name="C3",
            sw_col=150.80,
            sw_gate=126.50,
            sw_bus_y=132.50,
            vb_early=116.30,
            vb_col=142.80,
            vb_west=118.50,
            vb_f_y1=120.90,
            vb_via1=(150.50, 116.30),
            vb_via2=(118.50, 129.00),
            gnd_via=(148.80, 127.20),
            keep_r=3.05,
            do_1v9=True,
            v19_x=146.50,
            w19=0.15,
        ),
        dict(
            name="C4",
            sw_col=151.00,
            sw_gate=126.55,
            sw_bus_y=135.54,
            vb_early=116.25,
            vb_col=143.50,
            vb_west=119.50,
            vb_f_y1=120.80,
            vb_via1=(150.00, 116.25),
            vb_via2=(119.50, 133.00),
            gnd_via=(149.20, 127.80),
            keep_r=3.00,
            do_1v9=True,
            v19_x=146.00,
            w19=0.15,
        ),
        dict(
            name="C5",
            sw_col=151.10,
            sw_gate=126.70,
            sw_bus_y=132.50,
            vb_early=116.15,
            vb_col=144.00,
            vb_west=120.00,
            vb_f_y1=120.60,
            vb_via1=(149.80, 116.15),
            vb_via2=(120.00, 128.20),
            gnd_via=(149.50, 128.00),
            keep_r=None,
            do_1v9=True,
            v19_x=145.80,
            w19=0.15,
        ),
    ]

    # Optional single-config via argv
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only:
        configs = [c for c in configs if c["name"] == only]
        if not configs:
            print("Unknown config", only)
            return 2

    best = None
    for cfg in configs:
        name = cfg["name"]
        print(f"\n========== TRY {name} ==========")
        sys.stdout.flush()
        # Each config in isolation via fresh interpreter would be safer; try in-process
        # with copy from BAK each time.
        try:
            meta = apply(cfg)
        except Exception as e:
            print("  APPLY FAIL", e)
            continue

        unc, errs, warns, viol = run_drc()
        min_edge = meta["min_edge"]
        print(
            f"  min_edge={min_edge:.3f} unc={len(unc)} err={len(errs)} warn={len(warns)} "
            f"XC1={meta['xc1_after'][0]:.3f}/{meta['xc1_after'][1]:.3f} "
            f"dRF={meta['d_rf']:.2f} dDCDC={meta['d_dc']:.2f}"
        )
        print("  types", dict(Counter(v.get("type") for v in viol).most_common()[:12]))
        for v in errs[:20]:
            items = v.get("items", [])
            descs = [i.get("description", "")[:95] for i in items]
            p = items[0].get("pos", {}) if items else {}
            print(f"   ERR {v.get('type')}: {' | '.join(descs)} @({p.get('x')},{p.get('y')})")
        for v in warns[:10]:
            items = v.get("items", [])
            print(f"   WARN {v.get('type')}: {' | '.join(i.get('description','')[:65] for i in items)}")
        sys.stdout.flush()

        sc = (
            (0 if len(unc) == 0 else 1000)
            + len(errs) * 10
            + len(warns) * 3
            + (0 if min_edge >= CLEAR - 1e-3 else 80)
            + (0 if meta["xc1_after"][0] <= 22.359 * 1.10 else 500)
            + (0 if meta["xc1_after"][1] <= meta["xc1_before"][1] + 0.05 else 200)
            + (0 if abs(meta["xc1_after"][0] - meta["xc1_before"][0]) < 0.02 else 50)
            + (0 if meta["d_rf"] >= 2.0 else 5)
            + (0 if meta["d_dc"] >= 1.0 else 5)
        )
        if best is None or sc < best[0]:
            best = (sc, name, meta, unc, errs, warns, viol)
            shutil.copy2(PCB, BEST)
            print(f"  -> best score={sc}")

        if (
            len(unc) == 0
            and len(errs) == 0
            and len(warns) == 0
            and min_edge >= CLEAR - 1e-3
            and meta["xc1_after"][0] <= 22.359 * 1.10 + 1e-6
            and meta["xc1_after"][1] <= meta["xc1_before"][1] + 0.05
        ):
            print("SUCCESS")
            break

        # Next config: force new process cleanliness by only continuing if LoadBoard still works
        # If apply used Remove, subsequent LoadBoard after copy2(BAK) should still work.

    if best is None:
        print("No configs produced a board")
        return 1

    shutil.copy2(BEST, PCB)
    unc, errs, warns, viol = run_drc()
    meta = best[2]
    min_edge = meta["min_edge"]
    details = meta["details"]

    success = (
        len(unc) == 0
        and len(errs) == 0
        and min_edge >= CLEAR - 1e-3
        and meta["xc1_after"][0] <= 22.359 * 1.10 + 1e-6
    )
    silk_clean = len(warns) == 0

    print("\n" + "=" * 60)
    status = (
        "SUCCESS"
        if success and silk_clean
        else ("SUCCESS_DRC" if success else "PARTIAL_BEST")
    )
    print("RESULT:", status)
    print("Config:", best[1], "score", best[0])
    print(f"unc={len(unc)} err={len(errs)} warn={len(warns)} min_edge={min_edge:.3f}")
    xb, xa = meta["xc1_before"], meta["xc1_after"]
    print(f"XC1 before L,A,vias={xb[0]:.3f},{xb[1]:.3f},{xb[2]} after={xa[0]:.3f},{xa[1]:.3f},{xa[2]}")
    print(
        f"SWDIO len {meta['sw_before'][0]:.3f}->{meta['sw_after'][0]:.3f} "
        f"vias {meta['sw_before'][1]}->{meta['sw_after'][1]}"
    )
    print(
        f"VBAT_SENSE len {meta['vb_before'][0]:.3f}->{meta['vb_after'][0]:.3f} "
        f"vias {meta['vb_before'][1]}->{meta['vb_after'][1]}"
    )
    print(f"VBAT vias @ {meta.get('vb_vias')}")
    print(
        f"VBAT_SENSE closest RF box={meta['d_rf']:.3f} DCDC box={meta['d_dc']:.3f} "
        f"L2={meta['d_l2']:.3f}"
    )
    print(f"1V9 width {meta['w19_0']}->{meta['w19_1']} RF dL={meta['rf1']-meta['rf0']:.4f}")
    print("SW path", meta["sw_path"])
    print("VB path", meta["vb_path"])
    print("GND via ->", meta["gnd_via"], "1V9 dodge=", meta["do_1v9"], "x=", meta["v19_x"])
    print("Silk", meta["silk"])
    for edge, net, sx, sy, ex, ey in sorted(details)[:20]:
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

    print("\n=== continuity (subprocess) ===")
    cont_py = f"""
import pcbnew
b = pcbnew.LoadBoard(r"{PCB}")
TOMM = lambda v: v/1e6
for name_n in ("SWDIO","VBAT_SENSE","XC1","1V9_A","GND","RF_FEED","SWDCLK","PGOOD"):
    pads=[]
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname()==name_n:
                pp=p.GetPosition()
                pads.append((fp.GetReference(), p.GetNumber(), TOMM(pp.x), TOMM(pp.y)))
    pads.sort(key=lambda x:(x[2],x[3]))
    if pads:
        print(f"{{name_n}}: {{pads[0][0]}}.{{pads[0][1]}}@({{pads[0][2]:.3f}},{{pads[0][3]:.3f}}) .. {{pads[-1][0]}}.{{pads[-1][1]}}@({{pads[-1][2]:.3f}},{{pads[-1][3]:.3f}}) n={{len(pads)}}")
"""
    subprocess.run([sys.executable, "-c", cont_py], cwd=PROJ)

    print("\n=== SWDIO segs ===")
    for lay, sx, sy, ex, ey, w in meta["sw_after"][3]:
        print(f"  {lay} ({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f}) w={w:.3f}")
    print("=== VBAT_SENSE segs ===")
    for lay, sx, sy, ex, ey, w in meta["vb_after"][3]:
        print(f"  {lay} ({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f}) w={w:.3f}")
    print("SWDIO vias", meta["sw_after"][2])
    print("VBAT vias", meta["vb_after"][2])

    gerbers = []
    if success and silk_clean:
        print("\nExporting gerbers...")
        gerbers = export_gerbers()
        print("GERBERS:", gerbers)
    elif success:
        print("\nDRC errors=0 but silk warnings remain — no gerber export")
    else:
        print("\nBUDGET/PARTIAL — best in", BEST)

    lines = [
        f"RESULT={status} config={best[1]} score={best[0]}",
        f"unc={len(unc)} err={len(errs)} warn={len(warns)} min_edge={min_edge:.3f}",
        f"XC1 before L={xb[0]:.3f} A={xb[1]:.3f} vias={xb[2]} after L={xa[0]:.3f} A={xa[1]:.3f} vias={xa[2]}",
        f"SWDIO {meta['sw_before'][0]:.3f}->{meta['sw_after'][0]:.3f} vias {meta['sw_before'][1]}->{meta['sw_after'][1]}",
        f"VBAT {meta['vb_before'][0]:.3f}->{meta['vb_after'][0]:.3f} vias {meta['vb_before'][1]}->{meta['vb_after'][1]}",
        f"VBAT dRF={meta['d_rf']:.3f} dDCDC={meta['d_dc']:.3f} dL2={meta['d_l2']:.3f}",
        f"1V9 {meta['w19_0']}->{meta['w19_1']} RF_dL={meta['rf1']-meta['rf0']:.4f}",
        f"GND via {meta['gnd_via']} 1V9_dodge={meta['do_1v9']}",
        f"best file: {BEST}",
        f"gerbers: {gerbers}",
    ]
    for v in errs + warns:
        items = v.get("items", [])
        descs = " | ".join(i.get("description", "")[:100] for i in items)
        p = items[0].get("pos", {}) if items else {}
        lines.append(f"{v.get('severity')} {v.get('type')}: {descs} @({p.get('x')},{p.get('y')})")
    for u in unc:
        lines.append("UNCONN " + " | ".join(i.get("description", "")[:90] for i in u.get("items", [])))
    write_blocker("\n".join(lines) + "\n")
    print("Wrote", BLOCKER)
    return 0 if success and silk_clean else (0 if success else 1)


if __name__ == "__main__":
    sys.exit(main())
