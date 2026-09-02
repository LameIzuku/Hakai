#!/usr/bin/env python3
"""Map C19 neighborhood geometry on the current PCB."""
import pcbnew

PCB = r"C:\Users\kavya\Documents\hakai\claud\final v2 (v6)\hakai_mouse_v6.kicad_pcb"
board = pcbnew.LoadBoard(PCB)
MM = lambda v: v / 1e6

for ref in ["C19", "C18", "C12", "Y1", "U1", "C20", "C21"]:
    fp = board.FindFootprintByReference(ref)
    if not fp:
        print("missing", ref)
        continue
    print(
        f"=== {ref} @ ({MM(fp.GetPosition().x):.3f},{MM(fp.GetPosition().y):.3f}) "
        f"rot={fp.GetOrientationDegrees()}"
    )
    for p in fp.Pads():
        pos = p.GetPosition()
        print(
            f"  pad{p.GetNumber()} net={p.GetNetname()} "
            f"({MM(pos.x):.3f},{MM(pos.y):.3f}) "
            f"size=({MM(p.GetSize().x):.3f},{MM(p.GetSize().y):.3f})"
        )

print("=== TRACKS/VIAS in ROI 147-156 / 115-125 ===")
for t in board.GetTracks():
    if t.GetClass() == "PCB_VIA":
        p = t.GetPosition()
        x, y = MM(p.x), MM(p.y)
        if 147 <= x <= 156 and 115 <= y <= 125:
            try:
                w = MM(t.GetWidth(pcbnew.F_Cu))
            except Exception:
                w = -1
            print(f" VIA {t.GetNetname()} ({x:.3f},{y:.3f}) d={MM(t.GetDrill()):.2f} w={w:.2f}")
    else:
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = MM(s.x), MM(s.y), MM(e.x), MM(e.y)
        hits = (
            (147 <= sx <= 156 and 115 <= sy <= 125)
            or (147 <= ex <= 156 and 115 <= ey <= 125)
            or (147 <= (sx + ex) / 2 <= 156 and 115 <= (sy + ey) / 2 <= 125)
        )
        if hits:
            lay = (
                "F"
                if t.GetLayer() == pcbnew.F_Cu
                else ("B" if t.GetLayer() == pcbnew.B_Cu else str(t.GetLayer()))
            )
            print(
                f" TRK {t.GetNetname()} {lay} "
                f"({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f}) w={MM(t.GetWidth()):.3f}"
            )

print("=== GND vias wider 145-158 / 112-128 ===")
for t in board.GetTracks():
    if t.GetClass() != "PCB_VIA" or t.GetNetname() != "GND":
        continue
    p = t.GetPosition()
    x, y = MM(p.x), MM(p.y)
    if 145 <= x <= 158 and 112 <= y <= 128:
        print(f" GND via ({x:.3f},{y:.3f})")

# List nets on F/B tracks near C19 pad2
print("=== F.Cu tracks near C19 pad2 (151-154, 117-120) ===")
for t in board.GetTracks():
    if t.GetClass() == "PCB_VIA":
        continue
    if t.GetLayer() != pcbnew.F_Cu:
        continue
    s, e = t.GetStart(), t.GetEnd()
    sx, sy, ex, ey = MM(s.x), MM(s.y), MM(e.x), MM(e.y)
    if (
        (151 <= sx <= 154 and 117 <= sy <= 120)
        or (151 <= ex <= 154 and 117 <= ey <= 120)
    ):
        print(
            f" F {t.GetNetname()} ({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f}) w={MM(t.GetWidth()):.3f}"
        )

print("=== B.Cu tracks near C19 pad2 (151-154, 117-120) ===")
for t in board.GetTracks():
    if t.GetClass() == "PCB_VIA":
        continue
    if t.GetLayer() != pcbnew.B_Cu:
        continue
    s, e = t.GetStart(), t.GetEnd()
    sx, sy, ex, ey = MM(s.x), MM(s.y), MM(e.x), MM(e.y)
    if (
        (151 <= sx <= 154 and 117 <= sy <= 120)
        or (151 <= ex <= 154 and 117 <= ey <= 120)
    ):
        print(
            f" B {t.GetNetname()} ({sx:.3f},{sy:.3f})-({ex:.3f},{ey:.3f}) w={MM(t.GetWidth()):.3f}"
        )
