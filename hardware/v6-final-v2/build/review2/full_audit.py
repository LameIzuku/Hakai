#!/usr/bin/env python3
"""Independent recheck — read only. No board edits."""
from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
DRC = os.path.join(PROJ, "build", "review2", "drc.json")
ERC = os.path.join(PROJ, "build", "review2", "erc.json")
XML = os.path.join(PROJ, "build", "review2", "from_sch.xml")
MM = 1e-6
HARD = {
    "shorting_items",
    "tracks_crossing",
    "clearance",
    "hole_to_hole",
    "copper_edge_clearance",
    "solder_mask_bridge",
}


def main():
    print("=== FILES ===")
    for p in [PCB, os.path.join(PROJ, "hakai_mouse_v6.kicad_sch")]:
        st = os.stat(p)
        print(f"  {os.path.basename(p)} size={st.st_size}")

    # --- ERC ---
    erc = json.load(open(ERC, encoding="utf-8"))
    allv = []
    for s in erc.get("sheets", []):
        allv.extend(s.get("violations", []))
    if not allv:
        allv = erc.get("violations", [])
    print("\n=== ERC ===")
    print(f"count={len(allv)} sev={dict(Counter(v.get('severity') for v in allv))}")
    print(f"types={dict(Counter(v.get('type') for v in allv).most_common(10))}")

    # --- DRC ---
    drc = json.load(open(DRC, encoding="utf-8"))
    unc = drc.get("unconnected_items", [])
    viol = drc.get("violations", [])
    hard = [
        v
        for v in viol
        if v.get("severity") == "error" and v.get("type") in HARD
    ]
    print("\n=== DRC ===")
    print(
        f"unconnected={len(unc)} viol={len(viol)} "
        f"sev={dict(Counter(v.get('severity') for v in viol))} hard={len(hard)}"
    )
    print(f"types={dict(Counter(v.get('type') for v in viol).most_common())}")
    for v in viol:
        items = v.get("items", [])
        descs = [i.get("description", "")[:90] for i in items]
        pos = items[0].get("pos", {}) if items else {}
        print(
            f"  {v.get('severity')} {v.get('type')}: "
            f"{' | '.join(descs)} @({pos.get('x')},{pos.get('y')})"
        )
    for u in unc:
        items = u.get("items", [])
        print(
            "  UNCONN",
            [i.get("description", "")[:90] for i in items],
            [i.get("pos") for i in items],
        )

    # --- Board ---
    board = pcbnew.LoadBoard(PCB)
    print("\n=== BOARD / OUTLINE ===")
    print("copper layers:", board.GetCopperLayerCount())
    box = board.GetBoardEdgesBoundingBox()
    print(
        f"bbox mm ({box.GetX()*MM:.3f},{box.GetY()*MM:.3f})-"
        f"({box.GetRight()*MM:.3f},{box.GetBottom()*MM:.3f}) "
        f"size {box.GetWidth()*MM:.3f}x{box.GetHeight()*MM:.3f}"
    )
    ds = board.GetDesignSettings()
    print(f"min_clearance={ds.m_MinClearance*MM:.4f} min_track={ds.m_TrackMinWidth*MM:.4f}")
    edge_n = 0
    for d in board.GetDrawings():
        try:
            if int(d.GetLayer()) == int(pcbnew.Edge_Cuts):
                edge_n += 1
        except Exception:
            pass
    print("Edge.Cuts items:", edge_n)
    zones = [(z.GetNetname(), board.GetLayerName(z.GetLayer())) for z in board.Zones()]
    print("zones:", zones)
    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    segs = sum(1 for t in board.GetTracks() if t.GetClass() != "PCB_VIA")
    print(f"vias={len(vias)} track_segs={segs}")

    fps = list(board.GetFootprints())
    print("footprints:", len(fps))

    pcb_pads = {}  # (ref, pin) -> net
    pad_nets = defaultdict(list)
    for fp in fps:
        ref = fp.GetReference()
        for p in fp.Pads():
            num = str(p.GetNumber())
            n = p.GetNetname() or ""
            pcb_pads[(ref, num)] = n
            if n:
                pad_nets[n].append(f"{ref}.{num}")

    single = {
        n: v
        for n, v in pad_nets.items()
        if len(v) == 1 and n and not n.startswith("unconnected")
    }
    print("single-pad named nets:", len(single))
    for n, v in sorted(single.items()):
        print(f"  {n}: {v}")

    # Critical comps
    print("\n=== KEY COMPONENTS (PCB) ===")
    for ref in [
        "C12",
        "C19",
        "C18",
        "Y1",
        "Y2",
        "U4",
        "U3",
        "U2",
        "FB1",
        "ANT1",
        "L3",
        "L4",
        "C22",
        "C23",
        "C24",
        "J1",
        "J2",
        "J3",
    ]:
        for fp in fps:
            if fp.GetReference() != ref:
                continue
            try:
                fpid = fp.GetFPIDAsString()
            except Exception:
                fpid = str(fp.GetFPID())
            pads = [(p.GetNumber(), p.GetNetname()) for p in fp.Pads()]
            pos = fp.GetPosition()
            print(
                f"  {ref} val={fp.GetValue()} fp={fpid} "
                f"@({pos.x*MM:.3f},{pos.y*MM:.3f}) pads={pads}"
            )

    # Pin swaps
    print("\n=== U4 GPIO OF INTEREST (PCB) ===")
    for fp in fps:
        if fp.GetReference() != "U4":
            continue
        want = {
            "BTN_RIGHT",
            "BTN_SIDE_BACK",
            "BTN_LEFT",
            "BTN_SIDE_FWD",
            "VBAT_EN",
            "SWDIO",
            "SWDCLK",
            "nRESET",
            "SPI_MOSI",
            "SPI_SCK",
            "XC1",
            "XC2",
            "ANT",
            "XL1",
            "XL2",
        }
        for p in fp.Pads():
            if p.GetNetname() in want:
                print(f"  U4.{p.GetNumber()} = {p.GetNetname()}")

    # GND vias near C12/C19
    print("\n=== GND VIAS NEAR C12 / C19 ===")
    for t in vias:
        if t.GetNetname() != "GND":
            continue
        p = t.GetPosition()
        x, y = p.x * MM, p.y * MM
        if 146 <= x <= 152 and 108 <= y <= 112:
            print(f"  C12-area ({x:.3f},{y:.3f})")
        if 147 <= x <= 154 and 117 <= y <= 120:
            print(f"  C19-area ({x:.3f},{y:.3f})")

    # Sch netlist from XML
    print("\n=== SCH XML NETLIST vs PCB ===")
    tree = ET.parse(XML)
    root = tree.getroot()
    sch_pads = {}
    for net in root.iter("net"):
        name = net.get("name")
        if name is None:
            n = net.find("name")
            name = n.text if n is not None else ""
        for node in net.findall("node"):
            ref = node.get("ref")
            pin = node.get("pin")
            if ref and pin:
                sch_pads[(ref, pin)] = name or ""

    print(f"sch nodes={len(sch_pads)} pcb pads={len(pcb_pads)}")

    mismatches = []
    only_sch = []
    only_pcb = []
    for key, snet in sch_pads.items():
        ref, pin = key
        if ref.startswith("#"):
            continue
        if key not in pcb_pads:
            only_sch.append((key, snet))
            continue
        pnet = pcb_pads[key]
        sn, pn = snet or "", pnet or ""
        if sn.startswith("unconnected") and (
            not pn or pn.startswith("unconnected")
        ):
            continue
        if sn != pn:
            if sn.startswith("unconnected") and pn.startswith("unconnected"):
                continue
            mismatches.append((key, sn, pn))

    for key, pnet in pcb_pads.items():
        ref, pin = key
        if ref.startswith("#") or not pin:
            continue
        if key not in sch_pads and pnet and not pnet.startswith("unconnected"):
            only_pcb.append((key, pnet))

    print(f"mismatches={len(mismatches)}")
    for item in mismatches:
        print(f"  MISMATCH {item[0]} sch={item[1]!r} pcb={item[2]!r}")
    print(f"sch_only={len(only_sch)}")
    for item in only_sch[:25]:
        print(f"  SCH_ONLY {item[0]} net={item[1]}")
    print(f"pcb_only(named)={len(only_pcb)}")
    for item in only_pcb[:25]:
        print(f"  PCB_ONLY {item[0]} net={item[1]}")

    # Y1 specifically from XML
    print("\n=== Y1 DETAIL ===")
    for net in root.iter("net"):
        name = net.get("name")
        if name is None:
            n = net.find("name")
            name = n.text if n is not None else ""
        nodes = [(n.get("ref"), n.get("pin")) for n in net.findall("node")]
        y1 = [n for n in nodes if n[0] == "Y1"]
        if y1:
            print(f"  sch net {name!r}: Y1 pins {y1}")
    for k, n in sorted(pcb_pads.items()):
        if k[0] == "Y1":
            print(f"  pcb {k} = {n}")

    # RF chain PCB
    print("\n=== RF / 1V9 ===")
    for n in ["ANT", "RF1", "RF_FEED", "1V9", "1V9_A"]:
        print(f"  {n}: {pad_nets.get(n, [])}")

    # Track/via extremes
    widths = [
        t.GetWidth() * MM
        for t in board.GetTracks()
        if t.GetClass() != "PCB_VIA"
    ]
    drills = []
    for t in vias:
        try:
            drills.append(t.GetDrill() * MM)
        except Exception:
            pass
    print(
        f"\ntrack_w min={min(widths):.3f} max={max(widths):.3f} "
        f"via_drill min={min(drills):.3f} max={max(drills):.3f}"
    )

    # Project rules snippet
    pro = json.load(open(os.path.join(PROJ, "hakai_mouse_v6.kicad_pro"), encoding="utf-8"))
    rules = pro["board"]["design_settings"]["rules"]
    print("\n=== PROJECT RULES ===")
    for k in [
        "min_clearance",
        "min_track_width",
        "min_via_diameter",
        "min_through_hole_diameter",
        "min_copper_edge_clearance",
        "min_hole_clearance",
    ]:
        print(f"  {k}: {rules.get(k)}")
    nsc = pro.get("net_settings", {}).get("classes") or []
    if not nsc:
        # alternate path sometimes empty at top
        pass
    # try both
    classes = pro.get("net_settings", {}).get("classes")
    if not classes:
        # file structure from earlier
        try:
            # kicad pro may store under different root
            raw = open(os.path.join(PROJ, "hakai_mouse_v6.kicad_pro"), encoding="utf-8").read()
            if '"classes"' in raw:
                print("  (net classes present in .pro — see prior parse)")
        except Exception:
            pass

    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
