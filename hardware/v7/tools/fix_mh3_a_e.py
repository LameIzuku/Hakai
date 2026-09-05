#!/usr/bin/env python3
"""A+E pass v2: 1V9 shove + XC1 north-wrap + late-west dual column + silk.

GND via stays (153.5,126) — RF_FEED not moved.
XC1 B only (no vias). 1V9 width >=0.10, detour widened to 0.15.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections import Counter

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
BAK = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_gnd_closed_ok")
BAK_RUN = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_pre_a_e")
BEST = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.best_a_e_attempt")
OUT = os.path.join(PROJ, "build", "drc_mh3_a_e.json")
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"

MM = pcbnew.FromMM
BC = int(pcbnew.B_Cu)
FC = int(pcbnew.F_Cu)
MH = (155.0, 130.0)
HOLE_R = 1.6
CLEAR_EDGE = 1.4
TRACK_W = 0.15


def TOMM(v):
    return v / 1e6


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
        if t.GetClass() == "PCB_VIA":
            continue
        if t.GetNetname() not in ("SWDIO", "VBAT_SENSE"):
            continue
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        d = seg_min_dist(sx, sy, ex, ey, *MH)
        edge = d - HOLE_R - TOMM(t.GetWidth()) / 2
        if edge < 12:
            details.append((edge, t.GetNetname(), sx, sy, ex, ey))
        min_edge = min(min_edge, edge)
    return min_edge, details


def track_length(board, netname, layer=None):
    total = 0.0
    for t in board.Tracks():
        if t.GetClass() == "PCB_VIA" or t.GetNetname() != netname:
            continue
        if layer is not None and int(t.GetLayer()) != layer:
            continue
        s, e = t.GetStart(), t.GetEnd()
        total += math.hypot(TOMM(e.x) - TOMM(s.x), TOMM(e.y) - TOMM(s.y))
    return total


def min_width(board, netname):
    ws = [TOMM(t.GetWidth()) for t in board.Tracks()
          if t.GetClass() != "PCB_VIA" and t.GetNetname() == netname]
    return (min(ws) if ws else None, max(ws) if ws else None)


def run_drc():
    subprocess.run(
        [KCLI, "pcb", "drc", "--format", "json", "--refill-zones", "-o", OUT, PCB],
        capture_output=True,
    )
    d = json.load(open(OUT, encoding="utf-8"))
    unc = d.get("unconnected_items", [])
    viol = d.get("violations", [])
    errs = [v for v in viol if v.get("severity") == "error"]
    warns = [v for v in viol if v.get("severity") == "warning"]
    return unc, errs, warns, viol


def add_keepout(board, keep_r):
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
        chain.Append(MM(MH[0] + keep_r * math.cos(ang)), MM(MH[1] + keep_r * math.sin(ang)))
    chain.SetClosed(True)
    z.Outline().AddOutline(chain)
    z.SetHatchStyle(pcbnew.ZONE_BORDER_DISPLAY_STYLE_NO_HATCH)
    try:
        z.SetZoneName("MH3_copper_keepout")
    except Exception:
        pass
    board.Add(z)


def fix_silk(board, log):
    # Move refs well clear of body silk and copper / each other / J2-J3
    targets = {
        "Q3": (128.00, 137.50),
        "R10": (134.50, 131.00),
        "R11": (112.50, 130.00),
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
        log.append(f"SILK {ref} ref ({old[0]:.2f},{old[1]:.2f}) -> ({nx:.2f},{ny:.2f})")


def apply(cfg):
    shutil.copy2(BAK, PCB)
    board = pcbnew.LoadBoard(PCB)
    nets = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if n and n not in nets:
                nets[n] = p.GetNet()

    used = set()
    before = {k: [] for k in ("SWDIO", "VBAT_SENSE", "1V9_A", "XC1", "GND", "RF_FEED", "PGOOD")}
    after = {k: [] for k in before}
    silk_log = []
    to_del = []

    rf_len_before = track_length(board, "RF_FEED", FC)
    w19_before = min_width(board, "1V9_A")

    for t in list(board.Tracks()):
        if t.GetClass() == "PCB_VIA" or int(t.GetLayer()) != BC:
            continue
        net = t.GetNetname()
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
        rec = ((round(sx, 3), round(sy, 3)), (round(ex, 3), round(ey, 3)))

        if net == "SWDIO" and near(sx, 154.20) and near(ex, 154.20):
            if min(sy, ey) < 120 and max(sy, ey) > 130:
                to_del.append(t); before["SWDIO"].append(rec); continue
        if net == "SWDIO" and near(sy, 132.50) and near(ey, 132.50):
            if near(max(sx, ex), 154.20) and min(sx, ex) < 140:
                to_del.append(t); before["SWDIO"].append(rec); continue

        if net == "VBAT_SENSE" and near(sx, 155.920) and near(ex, 155.920):
            if min(sy, ey) < 120 and max(sy, ey) > 130:
                to_del.append(t); before["VBAT_SENSE"].append(rec); continue
        if net == "VBAT_SENSE" and near(sy, 134.00) and near(ey, 134.00):
            if near(max(sx, ex), 155.920) and min(sx, ex) < 140:
                to_del.append(t); before["VBAT_SENSE"].append(rec); continue

        if net == "1V9_A":
            if (near(min(sx, ex), 138.490, 0.08) and near(max(sx, ex), 152.518, 0.08)
                    and near(max(sy, ey), 130.804, 0.08) and near(min(sy, ey), 116.776, 0.08)):
                to_del.append(t); before["1V9_A"].append(rec); continue

        if net == "XC1":
            if min(sx, ex) >= 150.5 and max(sx, ex) <= 165.0 and min(sy, ey) >= 105.0 and max(sy, ey) <= 121.0:
                to_del.append(t); before["XC1"].append(rec); continue

    for t in to_del:
        board.Remove(t)

    swdio, vbat, n19, xc1 = nets["SWDIO"], nets["VBAT_SENSE"], nets["1V9_A"], nets["XC1"]

    sw_gate = cfg["sw_gate"]
    vb_gate = cfg["vb_gate"]
    sw_col = cfg["sw_col"]
    sw_col2 = cfg["sw_col2"]
    vb_col = cfg["vb_col"]
    v19_x = cfg["v19_x"]
    w19 = cfg["w19"]
    keep_r = cfg["keep_r"]
    xc1_west = cfg["xc1_west"]
    xc1_ny = cfg["xc1_ny"]
    xc1_east = cfg["xc1_east"]

    # SWDIO nested late: H first at sw_gate, then jog west of VBAT before VBAT H
    used.add("SWDIO_west_MH")
    after["SWDIO"] = [
        ((154.200, 118.469), (154.200, sw_gate)),
        ((154.200, sw_gate), (sw_col, sw_gate)),
        ((sw_col, sw_gate), (sw_col, vb_gate - 0.25)),
        ((sw_col, vb_gate - 0.25), (sw_col2, vb_gate - 0.25)),
        ((sw_col2, vb_gate - 0.25), (sw_col2, 132.500)),
        ((sw_col2, 132.500), (128.000, 132.500)),
    ]
    for (a, b), (c, d) in after["SWDIO"]:
        add_seg(board, a, b, c, d, BC, swdio, TRACK_W)

    # VBAT late west — after SWDIO H; original XC1 replaced so NE no longer crosses 155.92
    used.add("VBAT_late_west")
    after["VBAT_SENSE"] = [
        ((155.920, 116.962), (155.920, vb_gate)),
        ((155.920, vb_gate), (vb_col, vb_gate)),
        ((vb_col, vb_gate), (vb_col, 134.000)),
        ((vb_col, 134.000), (129.203, 134.000)),
    ]
    for (a, b), (c, d) in after["VBAT_SENSE"]:
        add_seg(board, a, b, c, d, BC, vbat, TRACK_W)

    # XC1 north-wrap (B only) — opens 155.92 for late VBAT
    used.add("XC1_B_northwrap")
    after["XC1"] = [
        ((151.413, 119.546), (152.050, 119.546)),
        ((152.050, 119.546), (152.050, 117.746)),
        ((152.050, 117.746), (xc1_west, 117.746)),
        ((xc1_west, 117.746), (xc1_west, xc1_ny)),
        ((xc1_west, xc1_ny), (xc1_east, xc1_ny)),
        ((xc1_east, xc1_ny), (164.511, 108.858)),
        ((164.511, 108.858), (164.511, 105.078)),
    ]
    for (a, b), (c, d) in after["XC1"]:
        add_seg(board, a, b, c, d, BC, xc1, TRACK_W)

    # 1V9_A shove — free north-wrap + west columns
    used.add("1V9_A_fullwidth_shove")
    after["1V9_A"] = [
        ((138.490, 130.804), (v19_x, 130.804)),
        ((v19_x, 130.804), (v19_x, 116.776)),
        ((v19_x, 116.776), (152.518, 116.776)),
    ]
    for (a, b), (c, d) in after["1V9_A"]:
        add_seg(board, a, b, c, d, BC, n19, w19)

    after["GND"] = [("UNCHANGED_VIA", (153.500, 126.000))]
    after["RF_FEED"] = [("UNCHANGED", "delta_0")]
    after["PGOOD"] = [("UNCHANGED", "original_diagonal")]

    if keep_r is not None:
        used.add(f"keepout_tracks_r={keep_r:.2f}")
        add_keepout(board, keep_r)

    fix_silk(board, silk_log)
    used.add("silk_fix")

    print("  filling zones...")
    sys.stdout.flush()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(PCB)

    meta = {
        "cfg": cfg,
        "rf_len_before": rf_len_before,
        "rf_len_after": track_length(board, "RF_FEED", FC),
        "w19_before": w19_before,
        "w19_after": min_width(board, "1V9_A"),
        "silk_log": silk_log,
        "used": sorted(used),
    }
    meta["rf_delta"] = meta["rf_len_after"] - meta["rf_len_before"]
    min_edge, details = measure_mh(board)
    return before, after, meta, min_edge, details


def score_of(unc, errs, min_edge):
    return (
        (0 if len(unc) == 0 else 1000)
        + len(errs) * 10
        + (0 if min_edge >= CLEAR_EDGE - 1e-3 else 50)
        + (0 if min_edge >= 1.5 - 1e-3 else 5)
    )


def main():
    os.makedirs(os.path.join(PROJ, "build"), exist_ok=True)
    print("Backup:", BAK_RUN)
    print("Baseline:", BAK)
    sys.stdout.flush()

    configs = [
        # name embedded
        dict(name="nw_v19_147.5_sw149.6_vb151.6_k3.00",
             keep_r=3.00, sw_gate=126.55, vb_gate=127.10,
             sw_col=151.10, sw_col2=149.60, vb_col=151.60,
             v19_x=147.50, w19=0.15, xc1_west=150.60, xc1_ny=116.15, xc1_east=156.10),
        dict(name="nw_v19_147.0_sw149.5_vb151.5_k3.00",
             keep_r=3.00, sw_gate=126.55, vb_gate=127.15,
             sw_col=151.05, sw_col2=149.50, vb_col=151.55,
             v19_x=147.00, w19=0.15, xc1_west=150.50, xc1_ny=116.10, xc1_east=156.00),
        dict(name="nw_v19_146.5_sw149.4_vb151.5_k3.00",
             keep_r=3.00, sw_gate=126.55, vb_gate=127.20,
             sw_col=151.00, sw_col2=149.40, vb_col=151.50,
             v19_x=146.50, w19=0.15, xc1_west=150.40, xc1_ny=116.05, xc1_east=155.95),
        dict(name="nw_v19_147.5_sw149.6_vb151.6_k3.00_w10",
             keep_r=3.00, sw_gate=126.55, vb_gate=127.10,
             sw_col=151.10, sw_col2=149.60, vb_col=151.60,
             v19_x=147.50, w19=0.10, xc1_west=150.60, xc1_ny=116.15, xc1_east=156.10),
        dict(name="nw_v19_147.8_sw149.7_vb151.7_nokeep",
             keep_r=None, sw_gate=126.55, vb_gate=127.05,
             sw_col=151.10, sw_col2=149.70, vb_col=151.70,
             v19_x=147.80, w19=0.15, xc1_west=150.70, xc1_ny=116.20, xc1_east=156.20),
        dict(name="nw_v19_147.5_sw149.2_vb151.4_k3.00",
             keep_r=3.00, sw_gate=126.60, vb_gate=127.25,
             sw_col=151.00, sw_col2=149.20, vb_col=151.40,
             v19_x=147.50, w19=0.15, xc1_west=150.30, xc1_ny=116.00, xc1_east=156.30),
        dict(name="nw_v19_148.0_xc1_150.8_k3.00",
             keep_r=3.00, sw_gate=126.55, vb_gate=127.10,
             sw_col=151.10, sw_col2=149.55, vb_col=151.55,
             v19_x=148.00, w19=0.15, xc1_west=150.80, xc1_ny=116.25, xc1_east=155.90),
    ]

    best = None
    for cfg in configs:
        name = cfg["name"]
        print(f"\n========== TRY {name} ==========")
        sys.stdout.flush()
        before, after, meta, min_edge, details = apply(cfg)
        print(f"  min_edge={min_edge:.3f} rf_d={meta['rf_delta']:.4f} w19={meta['w19_after']}")
        sys.stdout.flush()
        unc, errs, warns, viol = run_drc()
        print(f"  DRC unc={len(unc)} err={len(errs)} warn={len(warns)}")
        print("  types", dict(Counter(v.get("type") for v in viol).most_common()))
        for v in errs[:10]:
            items = v.get("items", [])
            descs = [i.get("description", "")[:85] for i in items]
            p = items[0].get("pos", {}) if items else {}
            print(f"   ERR {v.get('type')}: {' | '.join(descs)} @({p.get('x')},{p.get('y')})")
        sys.stdout.flush()
        sc = score_of(unc, errs, min_edge)
        if best is None or sc < best[0]:
            best = (sc, name, min_edge, before, after, meta, details)
            shutil.copy2(PCB, BEST)
            print(f"  -> best score={sc}")
        if len(unc) == 0 and len(errs) == 0 and min_edge >= CLEAR_EDGE - 1e-3:
            print("SUCCESS")
            return finalize(True, name, min_edge, details, before, after, meta, unc, errs, warns)

    shutil.copy2(BEST, PCB)
    print("\nBUDGET EXHAUSTED — best on", BEST)
    unc, errs, warns, viol = run_drc()
    board = pcbnew.LoadBoard(PCB)
    min_edge, details = measure_mh(board)
    return finalize(False, best[1], min_edge, details, best[3], best[4], best[5], unc, errs, warns)


def finalize(success, name, min_edge, details, before, after, meta, unc, errs, warns):
    print("\n" + "=" * 60)
    print("RESULT:", "SUCCESS" if success else "PARTIAL_BEST")
    print("Config:", name)
    print("Permissions used:", meta.get("used"))
    print(f"MIN copper-edge to MH3 = {min_edge:.3f} mm")
    for edge, net, sx, sy, ex, ey in sorted(details)[:14]:
        print(f"  {net} ({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f}) edge={edge:.3f}")
    print(f"1V9_A width before={meta.get('w19_before')} after={meta.get('w19_after')}")
    print(f"RF_FEED L before={meta.get('rf_len_before'):.4f} after={meta.get('rf_len_after'):.4f} delta={meta.get('rf_delta'):.4f}")
    print("Silk:", meta.get("silk_log"))
    print("\nBEFORE/AFTER:")
    for k in before:
        if before.get(k):
            print(f" BEFORE {k}:", before[k])
        if after.get(k):
            print(f" AFTER  {k}:", after[k])
    print(f"\nDRC unconnected={len(unc)} errors={len(errs)} warnings={len(warns)}")
    seen = set()
    for v in errs:
        items = v.get("items", [])
        descs = [i.get("description", "")[:110] for i in items]
        p = items[0].get("pos", {}) if items else {}
        key = (v.get("type"), str(p.get("x")), str(p.get("y")), descs[0][:40] if descs else "")
        if key in seen:
            continue
        seen.add(key)
        print(f" ERR {v.get('type')}: {' | '.join(descs)} @({p.get('x')},{p.get('y')})")
    for v in warns:
        items = v.get("items", [])
        print(f" WARN {v.get('type')}: {' | '.join(i.get('description','')[:90] for i in items)}")
    for u in unc:
        print(" UNCONN", [i.get("description", "")[:90] for i in u.get("items", [])])

    board = pcbnew.LoadBoard(PCB)
    print("\n=== continuity endpoints ===")
    for name_n in ("SWDIO", "VBAT_SENSE", "XC1", "SWDCLK", "1V9_A", "RF_FEED", "BTN_SIDE_BACK", "GND", "VBAT", "PGOOD"):
        pads = []
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if p.GetNetname() == name_n:
                    pp = p.GetPosition()
                    pads.append((fp.GetReference(), p.GetNumber(), TOMM(pp.x), TOMM(pp.y)))
        pads.sort(key=lambda x: (x[2], x[3]))
        print(f"{name_n}:")
        if pads:
            print(f"  first {pads[0][0]}.{pads[0][1]} @({pads[0][2]:.3f},{pads[0][3]:.3f})")
            print(f"  last  {pads[-1][0]}.{pads[-1][1]} @({pads[-1][2]:.3f},{pads[-1][3]:.3f}) n={len(pads)}")
        vias = [(TOMM(t.GetPosition().x), TOMM(t.GetPosition().y))
                for t in board.Tracks() if t.GetClass() == "PCB_VIA" and t.GetNetname() == name_n]
        for vx, vy in vias[:4]:
            print(f"  via @({vx:.3f},{vy:.3f})")
        if len(vias) > 4:
            print(f"  ... +{len(vias)-4} vias")

    print(f"\ntracks_crossing: {any(v.get('type')=='tracks_crossing' for v in errs)}")
    print("Zones refilled: yes")
    print("RF_FEED not moved; GND via stays (153.5,126.0); pour refilled under RF_FEED")

    if not success:
        pairs = Counter()
        for v in errs:
            nets_found = []
            for it in v.get("items", []):
                nets_found += re.findall(r"\[([A-Z0-9_]+)\]", it.get("description", ""))
            if len(nets_found) >= 2:
                pairs[tuple(sorted(nets_found[:2]))] += 1
        print("\n" + "=" * 60)
        print("BLOCKING REPORT — not restored")
        print(f"Best: {BEST}")
        print(f"Config {name} unc={len(unc)} err={len(errs)} min_edge={min_edge:.3f}")
        for k, c in pairs.most_common():
            print(f"  {k[0]} × {k[1]}: {c}")
        if pairs:
            top = pairs.most_common(1)[0][0]
            print(f"\nDominant: {top[0]} × {top[1]}")
            print(
                "Single minimum unlock to close: "
                "authorize micro-nudge of the non-critical net in the dominant pair "
                "(or XC1 F-hop only if crystal via ban is lifted after reviewing Q1)."
            )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
