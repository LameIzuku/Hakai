#!/usr/bin/env python3
"""Independent design-review audit — read-only."""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict

import pcbnew

PROJ = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
PCB = os.path.join(PROJ, "hakai_mouse_v6.kicad_pcb")
SCH_NET = os.path.join(PROJ, "build", "review", "from_sch.net")
MM = 1e-6


def main():
    board = pcbnew.LoadBoard(PCB)
    print("=== BOARD STACK / OUTLINE ===")
    print("copper layers:", board.GetCopperLayerCount())
    box = board.GetBoardEdgesBoundingBox()
    print(
        f"edge bbox mm: ({box.GetX()*MM:.3f},{box.GetY()*MM:.3f})-"
        f"({box.GetRight()*MM:.3f},{box.GetBottom()*MM:.3f})"
    )
    print(f"size mm: {box.GetWidth()*MM:.3f} x {box.GetHeight()*MM:.3f}")
    ds = board.GetDesignSettings()
    print(f"min clearance mm: {ds.m_MinClearance*MM:.4f}")
    print(f"min track mm: {ds.m_TrackMinWidth*MM:.4f}")

    edge_n = 0
    for d in board.GetDrawings():
        try:
            if int(d.GetLayer()) == int(pcbnew.Edge_Cuts):
                edge_n += 1
        except Exception:
            pass
    print("Edge.Cuts drawings:", edge_n)

    fps = list(board.GetFootprints())
    print("footprints:", len(fps))

    pad_nets: dict[str, list] = defaultdict(list)
    fp_info = {}
    for fp in fps:
        ref = fp.GetReference()
        try:
            fpid = fp.GetFPIDAsString()
        except Exception:
            fpid = str(fp.GetFPID())
        fp_info[ref] = {"fp": fpid, "val": fp.GetValue(), "pads": []}
        for p in fp.Pads():
            n = p.GetNetname() or ""
            num = p.GetNumber()
            fp_info[ref]["pads"].append((num, n))
            if n:
                pad_nets[n].append((ref, num))

    single = {
        n: v
        for n, v in pad_nets.items()
        if len(v) == 1 and not n.startswith("unconnected")
    }
    print("nets with only 1 pad (excl unconnected*):", len(single))
    for n, v in sorted(single.items()):
        print(f"  SINGLE {n}: {v}")

    for rail in [
        "GND",
        "1V9_A",
        "VBAT",
        "VBUS",
        "VSYS",
        "LDO_IN",
        "DEC4_6",
        "XC1",
        "XC2",
        "VBAT_EN",
        "BTN_RIGHT",
        "BTN_SIDE_BACK",
    ]:
        if rail in pad_nets:
            print(f"rail {rail}: {len(pad_nets[rail])} pads")

    for ref in ["C12", "C19", "C18", "Y1", "U4", "U1", "U2", "U3", "J1", "J2", "J3"]:
        if ref in fp_info:
            print(
                f"{ref} fp={fp_info[ref]['fp']} val={fp_info[ref]['val']} "
                f"pads={fp_info[ref]['pads']}"
            )

    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    print("vias:", len(vias))
    print(
        "track segs:",
        sum(1 for t in board.GetTracks() if t.GetClass() != "PCB_VIA"),
    )
    zones = list(board.Zones())
    print(
        "zones:",
        [(z.GetNetname(), board.GetLayerName(z.GetLayer())) for z in zones],
    )

    for ref in ["C12", "C19", "C18"]:
        for fp in fps:
            if fp.GetReference() != ref:
                continue
            for p in fp.Pads():
                pos = p.GetPosition()
                print(
                    f"{ref} pad{p.GetNumber()} net={p.GetNetname()} "
                    f"@({pos.x*MM:.3f},{pos.y*MM:.3f})"
                )

    # GND vias near C12 / C19
    print("--- GND vias near C12 (x 146-152, y 108-112) ---")
    for t in vias:
        if t.GetNetname() != "GND":
            continue
        p = t.GetPosition()
        x, y = p.x * MM, p.y * MM
        if 146 <= x <= 152 and 108 <= y <= 112:
            print(f"  GND via ({x:.3f},{y:.3f})")
    print("--- GND vias near C19 (x 147-154, y 117-120) ---")
    for t in vias:
        if t.GetNetname() != "GND":
            continue
        p = t.GetPosition()
        x, y = p.x * MM, p.y * MM
        if 147 <= x <= 154 and 117 <= y <= 120:
            print(f"  GND via ({x:.3f},{y:.3f})")

    # Parse schematic netlist pad assignments
    print("\n=== NETLIST CROSSCHECK sch vs pcb ===")
    if not os.path.isfile(SCH_NET):
        print("missing sch netlist")
        return
    text = open(SCH_NET, encoding="utf-8", errors="replace").read()

    # KiCad s-expr netlist: (nets (net (code "1") (name "GND") (node (ref "C1") (pin "1")) ...))
    sch_pads = {}  # (ref, pin) -> net
    # crude parse
    for m in re.finditer(
        r'\(net\s+\(code\s+"?\d+"?\)\s+\(name\s+"([^"]*)"\)(.*?)(?=\(net\s+\(code|\(classes|\Z)',
        text,
        re.S,
    ):
        netname = m.group(1)
        body = m.group(2)
        for n in re.finditer(
            r'\(node\s+\(ref\s+"([^"]+)"\)\s+\(pin\s+"([^"]+)"\)', body
        ):
            sch_pads[(n.group(1), n.group(2))] = netname

    print("sch pad nodes parsed:", len(sch_pads))
    pcb_pads = {}
    for ref, info in fp_info.items():
        for num, n in info["pads"]:
            pcb_pads[(ref, str(num))] = n

    print("pcb pad entries:", len(pcb_pads))

    mismatches = []
    only_sch = []
    only_pcb = []
    # compare common refs that look like components (not power symbols)
    for key, snet in sch_pads.items():
        ref, pin = key
        if ref.startswith("#"):
            continue
        if key not in pcb_pads:
            only_sch.append((key, snet))
            continue
        pnet = pcb_pads[key]
        # normalize empty / unconnected
        sn = snet or ""
        pn = pnet or ""
        if sn.startswith("unconnected") and (not pn or pn.startswith("unconnected")):
            continue
        if sn != pn:
            # allow pcb unconnected naming differences
            if sn.startswith("unconnected") and pn.startswith("unconnected"):
                continue
            mismatches.append((key, sn, pn))

    for key, pnet in pcb_pads.items():
        ref, pin = key
        if ref.startswith("#"):
            continue
        if key not in sch_pads and pnet and not pnet.startswith("unconnected"):
            only_pcb.append((key, pnet))

    print("pad net mismatches:", len(mismatches))
    for item in mismatches[:40]:
        print(f"  MISMATCH {item[0]} sch={item[1]!r} pcb={item[2]!r}")
    print("only in sch (no pcb pad):", len(only_sch))
    for item in only_sch[:20]:
        print(f"  SCH_ONLY {item[0]} net={item[1]}")
    print("only in pcb (no sch node, has net):", len(only_pcb))
    for item in only_pcb[:20]:
        print(f"  PCB_ONLY {item[0]} net={item[1]}")

    # Pin swap verification on U4 if present
    print("\n=== U4 / pin-swap related pads ===")
    for ref in ["U4", "U1"]:
        if ref not in fp_info:
            continue
        for num, n in fp_info[ref]["pads"]:
            if n in (
                "BTN_RIGHT",
                "BTN_SIDE_BACK",
                "VBAT_EN",
                "BTN_LEFT",
                "BTN_SIDE_FWD",
                "SPI_MOSI",
                "SPI_MISO",
                "SPI_SCK",
                "SWDIO",
                "SWDCLK",
                "nRESET",
            ):
                print(f"  {ref}.{num} = {n}")

    # Track width extremes
    widths = []
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            continue
        widths.append(t.GetWidth() * MM)
    if widths:
        print(f"\ntrack width mm min={min(widths):.3f} max={max(widths):.3f}")

    # Via sizes
    drills = []
    for t in vias:
        try:
            drills.append(t.GetDrill() * MM)
        except Exception:
            pass
    if drills:
        print(f"via drill mm min={min(drills):.3f} max={max(drills):.3f} count={len(drills)}")

    # Check for overlapping footprints roughly
    print("\n=== FOOTPRINT LIB IDs (unique) ===")
    libs = Counter(v["fp"].split(":")[0] if ":" in v["fp"] else v["fp"] for v in fp_info.values())
    for k, n in libs.most_common():
        print(f"  {k}: {n}")


if __name__ == "__main__":
    main()
