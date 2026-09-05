#!/usr/bin/env python3
"""Set v6 manufacturing design rules: global minimums, three netclasses
(Default / power / fine), and a .kicad_dru that relaxes clearance inside the
two fine-pitch QFN courtyards. The netclasses feed the Specctra DSN export, so
Freerouting routes with exactly these rules.

fine class: the aQFN-73 ring-2 balls sit 1.0 mm inside the package edge; their
escape must pass the 0.25 mm channel between ring-0 pads -> 0.10 mm track with
0.075 mm clearance (0.10 + 2*0.075 = 0.25). Nets: every signal on a ring-2
ball, plus 1V9_A (ball Y2 is ring-2; 0.10 mm is ample for its ~50 mA).
"""
import json, os
PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PRO = os.path.join(PROJ, "hakai_mouse_v6.kicad_pro")
DRU = os.path.join(PROJ, "hakai_mouse_v6.kicad_dru")

FINE_NETS = ["STAT", "nRESET", "DCC", "DEC4_6", "VBAT_EN", "XL1", "DEC3",
             "XL2", "ANT", "BTN_RIGHT", "BTN_SIDE_FWD", "ENC_B", "1V9_A"]
POWER_NETS = ["VBUS", "VSYS", "VBAT", "1V9", "LDO_IN"]

d = json.load(open(PRO, encoding="utf-8"))
ds = d["board"]["design_settings"]
r = ds["rules"]
r["min_clearance"] = 0.07
r["min_track_width"] = 0.09
r["min_via_diameter"] = 0.40
r["min_via_annular_width"] = 0.10
r["min_through_hole_diameter"] = 0.20
r["min_hole_to_hole"] = 0.20
r["min_hole_clearance"] = 0.20
r["min_resolved_spokes"] = 1
# 0.10 = the value the v5.3 board was built and verified with (pours + antenna
# footprint legitimately sit closer than 0.15)
r["min_copper_edge_clearance"] = 0.10

base = None
for c in d["net_settings"]["classes"]:
    if c["name"] == "Default":
        c["clearance"] = 0.15
        c["track_width"] = 0.15
        c["via_diameter"] = 0.45
        c["via_drill"] = 0.20
        base = c
def mkclass(name, clearance, width):
    c = dict(base)
    c["name"] = name
    c["clearance"] = clearance
    c["track_width"] = width
    c["via_diameter"] = 0.45
    c["via_drill"] = 0.20
    return c
classes = [c for c in d["net_settings"]["classes"] if c["name"] in ("Default",)]
classes.append(mkclass("power", 0.15, 0.30))
classes.append(mkclass("fine", 0.075, 0.10))
d["net_settings"]["classes"] = classes
d["net_settings"]["netclass_patterns"] = (
    [{"netclass": "power", "pattern": n} for n in POWER_NETS] +
    [{"netclass": "fine", "pattern": n} for n in FINE_NETS])
json.dump(d, open(PRO, "w", encoding="utf-8"), indent=2)
print("updated", PRO)

dru = '''(version 1)

# nRF52833 aQFN-73 and BQ24074 VQFN-16: 0.5 mm pitch / 0.25 mm pads force the
# ring-2 escape through a 0.25 mm channel (0.10 mm trace + 0.072 mm clearance).
# Confined to the two QFN courtyards; the rest of the board is standard.
(rule "qfn_escape_clearance"
  (condition "A.insideCourtyard('U4') || A.insideCourtyard('U2')")
  (constraint clearance (min 0.072mm)))

(rule "qfn_escape_track"
  (condition "A.insideCourtyard('U4') || A.insideCourtyard('U2')")
  (constraint track_width (min 0.09mm)))
'''
open(DRU, "w", encoding="utf-8", newline="\n").write(dru)
print("wrote", DRU)
