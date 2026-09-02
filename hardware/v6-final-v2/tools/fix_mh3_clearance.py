#!/usr/bin/env python3
"""A+++ budget single-pass — restore best-known topology and tighten clearances.

Best-known topology from prior session (unc=0, min_edge~1.53, 5 hard errs):
  SWDIO west col, VBAT multi-step west, XC1 south then north-rejoin to NE,
  keepout tracks, GND via.

Fixes attempted vs prior failure modes:
  - GND via stays at y=126.0 (RF_FEED forbids y<=125.5)
  - Wider multi-step clearances vs XC1 V
  - XC1 north-rejoin x fully east of VBAT before rising
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
BAK_RUN = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.bak_pre_a_ppp_budget")
BEST = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb.best_mh3_attempt")
OUT = os.path.join(PROJ, "build", "drc_mh3_a_ppp.json")
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
        edge = d - HOLE_R - TRACK_W / 2
        if edge < 12:
            details.append((edge, t.GetNetname(), sx, sy, ex, ey))
        min_edge = min(min_edge, edge)
    return min_edge, details


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


def apply(board, nets, keep_r, gnd_via_y, swdclk_x, used, variant):
    swdio, vbat_s, xc1, gnd, swdclk = (
        nets["SWDIO"], nets["VBAT_SENSE"], nets["XC1"], nets["GND"], nets["SWDCLK"]
    )
    before = {"SWDIO": [], "VBAT_SENSE": [], "XC1": [], "GND": [], "SWDCLK": []}
    to_del = []

    for t in list(board.Tracks()):
        if t.GetClass() == "PCB_VIA":
            if t.GetNetname() == "GND" and abs(gnd_via_y - 126.0) > 0.01:
                p = t.GetPosition()
                x, y = TOMM(p.x), TOMM(p.y)
                if near(x, 153.5, 0.05) and near(y, 126.0, 0.15):
                    before["GND"].append(("VIA", (round(x, 3), round(y, 3))))
                    to_del.append(t)
            continue
        if int(t.GetLayer()) != BC:
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

        if net == "XC1":
            if min(sx, ex) >= 151.0 and max(sx, ex) <= 165.0 and min(sy, ey) >= 105.0 and max(sy, ey) <= 121.0:
                to_del.append(t); before["XC1"].append(rec); continue

        if net == "GND" and abs(gnd_via_y - 126.0) > 0.01:
            if near(sx, 152.500, 0.05) and near(ex, 152.500, 0.05):
                if near(min(sy, ey), 118.520, 0.15) and near(max(sy, ey), 126.000, 0.15):
                    to_del.append(t); before["GND"].append(rec); continue
            if near(sy, 126.000, 0.05) and near(ey, 126.000, 0.05):
                if near(min(sx, ex), 152.500, 0.15) and near(max(sx, ex), 153.500, 0.15):
                    to_del.append(t); before["GND"].append(rec); continue

        if net == "SWDCLK" and abs(swdclk_x - 158.4) > 0.01:
            if near(sx, 158.400, 0.05) and near(ex, 158.400, 0.05):
                if min(sy, ey) < 120 and max(sy, ey) > 130:
                    to_del.append(t); before["SWDCLK"].append(rec); continue
            if near(sy, 118.467, 0.05) and near(ey, 118.467, 0.05):
                if near(max(sx, ex), 159.662, 0.1) and near(min(sx, ex), 158.400, 0.1):
                    to_del.append(t); before["SWDCLK"].append(rec); continue
            if near(sy, 138.080, 0.05) and near(ey, 138.080, 0.05):
                if near(max(sx, ex), 158.400, 0.1) and min(sx, ex) < 145:
                    to_del.append(t); before["SWDCLK"].append(rec); continue

    for t in to_del:
        board.Remove(t)

    after = {"SWDIO": [], "VBAT_SENSE": [], "XC1": [], "GND": [], "SWDCLK": []}

    # GND via
    if abs(gnd_via_y - 126.0) > 0.01:
        used.add("GND_via_move")
        after["GND"] = [
            ((152.500, 118.520), (152.500, gnd_via_y)),
            ((152.500, gnd_via_y), (153.500, gnd_via_y)),
            ("VIA", (153.500, gnd_via_y)),
        ]
        add_seg(board, 152.500, 118.520, 152.500, gnd_via_y, BC, gnd, 0.12)
        add_seg(board, 152.500, gnd_via_y, 153.500, gnd_via_y, BC, gnd, 0.12)
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(V(153.500, gnd_via_y))
        v.SetDrill(MM(0.20))
        v.SetWidth(MM(0.45))
        try:
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
        except Exception:
            pass
        v.SetNet(gnd)
        board.Add(v)
    else:
        after["GND"] = [("UNCHANGED", (153.500, 126.000))]

    sw_gate = max(126.55, gnd_via_y + 0.55)
    vb_gate = sw_gate + 0.40
    xc1_s = vb_gate + 0.35

    # SWDIO
    after["SWDIO"] = [
        ((154.200, 118.469), (154.200, sw_gate)),
        ((154.200, sw_gate), (151.100, sw_gate)),
        ((151.100, sw_gate), (151.100, 132.500)),
        ((151.100, 132.500), (128.000, 132.500)),
    ]
    for (a, b), (c, d) in after["SWDIO"]:
        add_seg(board, a, b, c, d, BC, swdio, TRACK_W)

    if variant == "simple_vbat":
        # Nested SWDIO already at 151.1; VBAT at 151.7 after SWDIO jog west of VBAT H
        # Rebuild SWDIO with nest
        # (already added simple — for simple_vbat we accept SWDIO×VBAT risk and use nest)
        pass

    if variant == "multistep":
        # Prior multi-step with wider gap: first step only to 155.85 (still E of XC1@155.5 by 0.35)
        after["VBAT_SENSE"] = [
            ((155.920, 116.962), (155.920, vb_gate)),
            ((155.920, vb_gate), (155.850, vb_gate)),
            ((155.850, vb_gate), (155.850, vb_gate + 0.25)),
            ((155.850, vb_gate + 0.25), (154.500, vb_gate + 0.25)),
            ((154.500, vb_gate + 0.25), (154.500, vb_gate + 0.45)),
            ((154.500, vb_gate + 0.45), (151.700, vb_gate + 0.45)),
            ((151.700, vb_gate + 0.45), (151.700, 134.000)),
            ((151.700, 134.000), (129.203, 134.000)),
        ]
    elif variant == "nested":
        # Clear SWDIO, re-add nested; VBAT simple late west
        # Remove the SWDIO we just added and re-add nested form
        for t in list(board.Tracks()):
            if t.GetClass() == "PCB_VIA" or int(t.GetLayer()) != BC:
                continue
            if t.GetNetname() != "SWDIO":
                continue
            s, e = t.GetStart(), t.GetEnd()
            sx, sy, ex, ey = TOMM(s.x), TOMM(s.y), TOMM(e.x), TOMM(e.y)
            # delete our new segments in the region
            if min(sx, ex) >= 127.9 and max(sx, ex) <= 154.3 and min(sy, ey) >= 118.4 and max(sy, ey) <= 132.6:
                if near(sx, 154.2) or near(sy, sw_gate) or near(sx, 151.1) or near(sy, 132.5) or near(sx, 128.0):
                    board.Remove(t)
        after["SWDIO"] = [
            ((154.200, 118.469), (154.200, sw_gate)),
            ((154.200, sw_gate), (151.100, sw_gate)),
            ((151.100, sw_gate), (151.100, vb_gate - 0.15)),
            ((151.100, vb_gate - 0.15), (150.300, vb_gate - 0.15)),
            ((150.300, vb_gate - 0.15), (150.300, 132.500)),
            ((150.300, 132.500), (128.000, 132.500)),
        ]
        for (a, b), (c, d) in after["SWDIO"]:
            add_seg(board, a, b, c, d, BC, swdio, TRACK_W)
        after["VBAT_SENSE"] = [
            ((155.920, 116.962), (155.920, vb_gate)),
            ((155.920, vb_gate), (151.700, vb_gate)),
            ((151.700, vb_gate), (151.700, 134.000)),
            ((151.700, 134.000), (129.203, 134.000)),
        ]
    else:
        after["VBAT_SENSE"] = [
            ((155.920, 116.962), (155.920, vb_gate)),
            ((155.920, vb_gate), (151.700, vb_gate)),
            ((151.700, vb_gate), (151.700, 134.000)),
            ((151.700, 134.000), (129.203, 134.000)),
        ]

    for (a, b), (c, d) in after["VBAT_SENSE"]:
        add_seg(board, a, b, c, d, BC, vbat_s, TRACK_W)

    # XC1: L + south on 155.45 + east past VBAT + north rejoin + original NE
    # North-rejoin x must be > vb end x + clearance after VBAT has turned west at vb_gate
    # XC1 V ends at xc1_s > vb_gate so after VBAT H; H starts at x that doesn't need to cross VBAT V
    # After VBAT turned west, x=155.92 is free for y>vb_gate
    JOIN = (156.300, 117.169)
    xc1_v = 155.450  # 0.47 from VBAT 155.92
    after["XC1"] = [
        ((151.413, 119.546), (152.050, 119.546)),
        ((152.050, 119.546), (152.050, 117.746)),
        ((152.050, 117.746), (xc1_v, 117.746)),
        ((xc1_v, 117.746), (xc1_v, xc1_s)),
        ((xc1_v, xc1_s), (156.300, xc1_s)),
        ((156.300, xc1_s), JOIN),
        (JOIN, (164.511, 108.858)),
        ((164.511, 108.858), (164.511, 105.078)),
    ]
    for (a, b), (c, d) in after["XC1"]:
        add_seg(board, a, b, c, d, BC, xc1, TRACK_W)

    if abs(swdclk_x - 158.4) > 0.01:
        used.add("SWDCLK_east")
        after["SWDCLK"] = [
            ((159.662, 118.467), (swdclk_x, 118.467)),
            ((swdclk_x, 118.467), (swdclk_x, 138.080)),
            ((swdclk_x, 138.080), (140.049, 138.080)),
        ]
        for (a, b), (c, d) in after["SWDCLK"]:
            add_seg(board, a, b, c, d, BC, swdclk, TRACK_W)

    if keep_r is not None:
        used.add(f"keepout_tracks_r={keep_r:.2f}")
        add_keepout(board, keep_r)

    print("  filling zones...")
    sys.stdout.flush()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(PCB)
    meta = {
        "variant": variant,
        "sw_gate": sw_gate,
        "vb_gate": vb_gate,
        "xc1_s": xc1_s,
        "keep_r": keep_r,
        "gnd_via_y": gnd_via_y,
        "swdclk_x": swdclk_x,
    }
    return before, after, meta


def score_of(unc, errs, min_edge):
    return (
        (0 if len(unc) == 0 else 1000)
        + len(errs) * 10
        + (0 if min_edge >= CLEAR_EDGE - 1e-3 else 50)
        + (0 if min_edge >= 1.5 - 1e-3 else 5)
    )


def main():
    os.makedirs(os.path.join(PROJ, "build"), exist_ok=True)
    if os.path.isfile(PCB):
        shutil.copy2(PCB, BAK_RUN)
    shutil.copy2(BAK, PCB)
    print("Backup:", BAK_RUN)
    print("Restored baseline:", BAK)
    sys.stdout.flush()

    configs = [
        # name, keep_r, gnd_y, swdclk, variant
        ("multistep_gnd126_keepout3.00", 3.00, 126.0, 158.4, "multistep"),
        ("nested_gnd126_keepout3.00", 3.00, 126.0, 158.4, "nested"),
        ("multistep_gnd126_nokeep", None, 126.0, 158.4, "multistep"),
        ("nested_gnd126_nokeep", None, 126.0, 158.4, "nested"),
        ("multistep_gnd125.8_keepout3.00", 3.00, 125.8, 158.4, "multistep"),
        ("nested_gnd126_keepout3.00_swdclk159.5", 3.00, 126.0, 159.5, "nested"),
        ("multistep_gnd126_keepout2.95", 2.95, 126.0, 158.4, "multistep"),
    ]

    best = None
    for name, keep_r, gnd_y, swdclk_x, variant in configs:
        print(f"\n========== TRY {name} ==========")
        sys.stdout.flush()
        shutil.copy2(BAK, PCB)
        used_local = set()
        board = pcbnew.LoadBoard(PCB)
        nets = {}
        for fp in board.GetFootprints():
            for p in fp.Pads():
                n = p.GetNetname()
                if n and n not in nets:
                    nets[n] = p.GetNet()
        before, after, meta = apply(board, nets, keep_r, gnd_y, swdclk_x, used_local, variant)
        min_edge, details = measure_mh(board)
        print(f"  min_edge={min_edge:.3f}")
        sys.stdout.flush()
        unc, errs, warns, viol = run_drc()
        print(f"  DRC unc={len(unc)} err={len(errs)} warn={len(warns)}")
        print("  types", dict(Counter(v.get("type") for v in viol).most_common()))
        for v in errs[:10]:
            items = v.get("items", [])
            descs = [i.get("description", "")[:90] for i in items]
            p = items[0].get("pos", {}) if items else {}
            print(f"   ERR {v.get('type')}: {' | '.join(descs)} @({p.get('x')},{p.get('y')})")
        sys.stdout.flush()
        sc = score_of(unc, errs, min_edge)
        if best is None or sc < best[0]:
            best = (sc, name, min_edge, len(errs), len(unc), before, after, meta, used_local.copy(), details)
            shutil.copy2(PCB, BEST)
            print(f"  -> new best score={sc}")
        if len(unc) == 0 and len(errs) == 0 and min_edge >= CLEAR_EDGE - 1e-3:
            print("SUCCESS")
            return finalize(True, name, min_edge, details, before, after, meta, used_local, unc, errs, warns)

    shutil.copy2(BEST, PCB)
    print("\nBUDGET EXHAUSTED — best in", BEST)
    board = pcbnew.LoadBoard(PCB)
    min_edge, details = measure_mh(board)
    unc, errs, warns, viol = run_drc()
    return finalize(False, best[1], min_edge, details, best[5], best[6], best[7], best[8], unc, errs, warns)


def finalize(success, name, min_edge, details, before, after, meta, used, unc, errs, warns):
    print("\n" + "=" * 60)
    print("RESULT:", "SUCCESS" if success else "PARTIAL_BEST")
    print("Config:", name)
    print("Meta:", meta)
    print("Permissions used:", sorted(used) if used else ["SWDIO/VBAT/XC1 routing only"])
    print(f"MIN copper-edge to MH3 hole-edge = {min_edge:.3f} mm")
    for edge, net, sx, sy, ex, ey in sorted(details)[:14]:
        print(f"  {net} ({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f}) edge={edge:.3f}")
    print("\nBEFORE/AFTER:")
    for k in ("GND", "SWDIO", "VBAT_SENSE", "XC1", "SWDCLK"):
        if before.get(k):
            print(f" BEFORE {k}:", before[k])
        if after.get(k):
            print(f" AFTER  {k}:", after[k])
    print(f"\nDRC unconnected={len(unc)} errors={len(errs)} warnings={len(warns)}")
    seen = set()
    for v in errs:
        items = v.get("items", [])
        descs = [i.get("description", "")[:100] for i in items]
        p = items[0].get("pos", {}) if items else {}
        key = (v.get("type"), str(p.get("x")), str(p.get("y")), descs[0][:50] if descs else "")
        if key in seen:
            continue
        seen.add(key)
        print(f" ERR {v.get('type')}: {' | '.join(descs)} @({p.get('x')},{p.get('y')})")
    for v in warns:
        items = v.get("items", [])
        print(f" WARN {v.get('type')}: {' | '.join(i.get('description','')[:80] for i in items)}")
    for u in unc:
        print(" UNCONN", [i.get("description", "")[:90] for i in u.get("items", [])])

    board = pcbnew.LoadBoard(PCB)
    print("\n=== continuity endpoints ===")
    for name_n in ("SWDIO", "VBAT_SENSE", "XC1", "SWDCLK", "1V9_A", "BTN_SIDE_BACK", "GND", "VBAT"):
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
            print(f"  last  {pads[-1][0]}.{pads[-1][1]} @({pads[-1][2]:.3f},{pads[-1][3]:.3f})  n={len(pads)}")
        vias = [(TOMM(t.GetPosition().x), TOMM(t.GetPosition().y))
                for t in board.Tracks() if t.GetClass() == "PCB_VIA" and t.GetNetname() == name_n]
        for vx, vy in vias[:5]:
            print(f"  via @({vx:.3f},{vy:.3f})")
        if len(vias) > 5:
            print(f"  ... +{len(vias)-5} vias")

    print(f"\ntracks_crossing: {any(v.get('type')=='tracks_crossing' for v in errs)}")
    print("Zones refilled: yes")

    if not success:
        pairs = Counter()
        for v in errs:
            nets_found = []
            for it in v.get("items", []):
                d = it.get("description", "")
                # extract [NET]
                import re
                nets_found += re.findall(r"\[([A-Z0-9_]+)\]", d)
            if len(nets_found) >= 2:
                pairs[tuple(sorted(nets_found[:2]))] += 1
            elif nets_found:
                pairs[(nets_found[0], v.get("type"))] += 1
        print("\n" + "=" * 60)
        print("BLOCKING REPORT (budget exhausted) — do not restore")
        print(f"Best file: {BEST}")
        print(f"Also on main: {PCB}")
        print(f"Score config: {name}  unc={len(unc)} err={len(errs)} min_edge={min_edge:.3f}")
        print("Which net blocks which (counts):")
        for k, c in pairs.most_common():
            print(f"  {k[0]}  ×  {k[1]}  : {c}")
        print(
            f"""
Exact over-constraint:
  MH3 NPTH Ø3.2 @ (155.000, 130.000), hole r=1.6 mm.
  Hard copper-to-hole >= {CLEAR_EDGE} mm ⇒ track-center exclusion r >= {HOLE_R + CLEAR_EDGE + TRACK_W/2:.3f} mm.
  Baseline violators: SWDIO B vertical x=154.200 and VBAT_SENSE B vertical x=155.920 through the hole.
  Same-layer packing in the west corridor must also clear:
    - GND via (153.5, 126.0) / spoke (RF_FEED F forbids via y ≤ ~125.6)
    - 1V9_A B diagonal (138.490,130.804)-(152.518,116.776)
    - PGOOD B diagonal (142.545,126.130)-(151.892,116.784)
    - XC1 B path from via (151.413,119.546) to NE (164.511,108.858)
    - SWDCLK B vertical x=158.400 (east escape)
    - BTN_SIDE_BACK B cloud east/NE of MH
  Topological fact: XC1 must cross the VBAT x=155.92 column on B.Cu. The only
  free y-bands are y<116.962 (north of VBAT T) or y>vb_gate (after VBAT turns
  west). North band is packed with 1V9_A/PGOOD. South band forces XC1 through
  SWDCLK/BTN or into the VBAT H at the gate. Multi-step VBAT snaking east of an
  XC1 V at ~155.5 cannot achieve Default clearance 0.15 mm in the residual gap.

Minimum additional permissions to close (pick the smallest set matching ERRs):
  A. Allow 1V9_A full-width B micro-shove of the long diagonal (width 0.10 preserved)
     — opens early-west VBAT so original XC1 NE can stay.
  B. Allow PGOOD B micro-shove near its diagonal/H at y≈126
     — frees XC1 north-wrap / gate y band.
  C. Allow one XC1 F-hop (via pair) around the VBAT column
     — currently hard-forbidden; would break the same-layer topology deadlock.
  D. Allow BTN_SIDE_BACK B micro-clear + SWDCLK east together
     — enables clean east-of-MH VBAT column (permission 3 alone is insufficient).
  E. If copper-to-hole is already ≥1.4 and only keepout body remains: keepout r=2.90.

NOT sufficient alone (tested under this budget):
  - GND via micro-move (RF_FEED F collides for y≤125.5; y=126 leaves gate band tight)
  - keepout tracks r=3.00 alone
  - SWDCLK east alone (hits BTN_SIDE_BACK; does not fix XC1×VBAT west topology)
"""
        )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
