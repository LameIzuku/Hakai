#!/usr/bin/env python3
"""v5.3 package-level verification: pad containment, BOM reconciliation
against the netlist, cost-CSV arithmetic, and file inventory."""
import csv
import os
import re
import sys
import pcbnew

# package-relative (the folder above tools/); netlist from <package>/build/net.net
PKG = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
fails = []

# --- 6. pad containment ------------------------------------------------------
OUT = [(104, 40), (123, 40), (123, 78), (147, 78), (147, 40), (166, 40),
       (170, 44), (170, 88), (166, 96), (166, 144), (160, 150), (110, 150),
       (104, 144), (104, 96), (100, 88), (100, 44)]


def inside(px, py):
    n = len(OUT); c = False; j = n - 1
    for i in range(n):
        xi, yi = OUT[i]; xj, yj = OUT[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            c = not c
        j = i
    return c


board = pcbnew.LoadBoard(os.path.join(PKG, "hakai_mouse_final.kicad_pcb"))
bad = [(fp.GetReference(), p.GetNumber())
       for fp in board.GetFootprints() for p in fp.Pads()
       if not inside(p.GetPosition().x / 1e6, p.GetPosition().y / 1e6)]
print(f"6. containment: {'PASS - all pads inside shaped outline' if not bad else 'FAIL ' + str(bad[:5])}")
if bad:
    fails.append("containment")

# --- 7. BOM vs netlist reconciliation ----------------------------------------
def parse_sexp(s):
    toks = re.findall(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+', s)
    stack = [[]]
    for t in toks:
        if t == '(':
            stack.append([])
        elif t == ')':
            d = stack.pop(); stack[-1].append(d)
        else:
            if t.startswith('"') and t.endswith('"') and len(t) >= 2:
                t = t[1:-1]
            stack[-1].append(t)
    return stack[0]


def find_all(tree, tag):
    out = []
    if isinstance(tree, list):
        if tree and tree[0] == tag:
            out.append(tree)
        for el in tree:
            out.extend(find_all(el, tag))
    return out


def child(tree, tag):
    for el in tree:
        if isinstance(el, list) and el and el[0] == tag:
            return el
    return None


root = parse_sexp(open(os.path.join(PKG, "build", "net.net"), encoding="utf-8").read())
net_refs = {child(c, 'ref')[1] for c in find_all(root, 'comp')}

bom_refs = set()
with open(os.path.join(PKG, "BOM_hakai_mouse_final.csv"), newline='', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        for part in row["Refs"].split(","):
            part = part.strip()
            m = re.match(r'([A-Za-z]+)(\d+)-([A-Za-z]+)(\d+)$', part)
            if m and m.group(1) == m.group(3):
                for i in range(int(m.group(2)), int(m.group(4)) + 1):
                    bom_refs.add(f"{m.group(1)}{i}")
            elif part:
                bom_refs.add(part)

missing_in_bom = net_refs - bom_refs
extra_in_bom = bom_refs - net_refs
ok7 = not missing_in_bom and not extra_in_bom
print(f"7. BOM reconciliation: {'PASS' if ok7 else 'FAIL'} - "
      f"{len(bom_refs)} BOM refs == {len(net_refs)} netlist components"
      + ("" if ok7 else f" missing={sorted(missing_in_bom)} extra={sorted(extra_in_bom)}"))
if not ok7:
    fails.append("bom")

# --- 8. cost CSV arithmetic ---------------------------------------------------
rows = list(csv.reader(open(os.path.join(PKG, "Cost_Estimate_hakai_mouse_final.csv"),
                            newline='', encoding='utf-8-sig')))
part_sum = 0.0
stated = {}
for r in rows[1:]:
    if len(r) < 6 or not r[5]:
        continue
    if r[0] == "TOTAL":
        stated[r[2]] = float(r[5])
    elif r[0] not in ("PCB", "Off-board", "NOTE", ""):
        part_sum += float(r[5])
part_sum = round(part_sum, 2)
comp_total = stated.get("PCB components only (one board)")
ok8 = comp_total == part_sum
proto = stated.get("One assembled prototype (components + PCB share + stencil share)")
full = stated.get("Complete unit incl. battery")
ok8b = proto == round(part_sum + 7.00 / 5 + 8.00 / 5, 2) and full == round(proto + 3.50, 2)
print(f"8. cost arithmetic: {'PASS' if ok8 and ok8b else 'FAIL'} - parts sum {part_sum} "
      f"(stated {comp_total}); prototype {proto}; full {full}")
if not (ok8 and ok8b):
    fails.append("cost")

# --- 9. package inventory ------------------------------------------------------
required = ["hakai_mouse_final.kicad_pro", "hakai_mouse_final.kicad_sch",
            "hakai_mouse_final.kicad_pcb", "hakai_mouse_final_schematic.pdf",
            "board_top_render.png", "BOM_hakai_mouse_final.csv",
            "Cost_Estimate_hakai_mouse_final.csv", "README.md", "fp-lib-table",
            os.path.join("footprints.pretty", "PAW3311DB_iDIP8_L0AJ.kicad_mod"),
            os.path.join("footprints.pretty", "SW_Kailh_GM8_D2F.kicad_mod"),
            os.path.join("footprints.pretty", "ENC_Mouse_11mm.kicad_mod"),
            os.path.join("datasheets", "PAW3311DB-T2MU_v1.0.pdf"),
            os.path.join("verification", "ERC_report.rpt"),
            os.path.join("verification", "DRC_report.rpt"),
            os.path.join("verification", "netlist_crosscheck.txt"),
            os.path.join("verification", "pad_audit.txt"),
            os.path.join("tools", "gen_kicad.py"), os.path.join("tools", "pcb_gen.py")]
gone = [f for f in required if not os.path.isfile(os.path.join(PKG, f))]
print(f"9. inventory: {'PASS - all ' + str(len(required)) + ' required files present' if not gone else 'FAIL missing ' + str(gone)}")
if gone:
    fails.append("inventory")

print("\n" + ("PACKAGE VERIFICATION FAILED: " + ", ".join(fails) if fails
      else "V5.3 PACKAGE FULLY VERIFIED"))
sys.exit(1 if fails else 0)
