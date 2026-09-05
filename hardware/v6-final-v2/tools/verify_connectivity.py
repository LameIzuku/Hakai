#!/usr/bin/env python3
"""Independent electrical-connectivity verifier for hakai_mouse_v6.kicad_pcb.

No pcbnew / kicad-cli available, so we parse the board s-expression directly and
rebuild the copper connectivity graph (pads + tracks + vias + zone fills) to
answer two questions:

  1. Is every net a single connected copper island? (i.e. no unrouted/isolated
     pad -> that is an open circuit = electrical defect)
  2. Are all GND routes sound (both planes + stitching tie every GND pad)?

Geometry is 2-layer (F.Cu / B.Cu). Approach: per net, union-find over copper
primitives, then verify all pads of the net land in ONE component.
"""
import math
import re
import sys
from collections import defaultdict

PCB = sys.argv[1] if len(sys.argv) > 1 else "hakai_mouse_v6.kicad_pcb"
TOL = 0.02          # mm, endpoint coincidence tolerance
text = open(PCB, encoding="utf-8").read()

# ---------- s-expression parser ----------
def tokenize(s):
    return re.findall(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+', s)

def parse(s):
    stack = [[]]
    for t in tokenize(s):
        if t == '(':
            stack.append([])
        elif t == ')':
            top = stack.pop()
            stack[-1].append(top)
        else:
            if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
                t = t[1:-1]
            stack[-1].append(t)
    return stack[0][0]

root = parse(text)

def kids(node, tag):
    return [e for e in node if isinstance(e, list) and e and e[0] == tag]

def kid(node, tag):
    for e in node:
        if isinstance(e, list) and e and e[0] == tag:
            return e
    return None

def fnum(x):
    return float(x)

# ---------- geometry helpers ----------
def rot(px, py, deg):
    if deg == 0:
        return px, py
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return px * c - py * s, px * s + py * c

def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])

def pt_seg_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return dist(p, a)
    t = ((px - ax) * dx + (py - ay) * dy) / L2
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

def point_in_poly(p, poly):
    x, y = p
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]; xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi):
            inside = not inside
        j = i
    return inside

def poly_min_edge_dist(p, poly):
    n = len(poly)
    return min(pt_seg_dist(p, poly[i], poly[(i + 1) % n]) for i in range(n))

# ---------- collect copper primitives ----------
# Pad: dict(net, layers set, cx, cy, half (max half-extent), pts (corner set), ref, num)
pads = []
CU = {"F.Cu", "B.Cu"}

for fp in kids(root, "footprint"):
    at = kid(fp, "at")
    fx, fy = fnum(at[1]), fnum(at[2])
    frot = fnum(at[3]) if len(at) > 3 else 0.0
    ref = ""
    for prop in kids(fp, "property"):
        if len(prop) > 2 and prop[1] == "Reference":
            ref = prop[2]
    for pad in kids(fp, "pad"):
        num = pad[1]
        ptype = pad[2]           # smd / thru_hole / np_thru_hole / connect
        net = kid(pad, "net")
        netname = net[1] if net else None
        pat = kid(pad, "at")
        lx, ly = fnum(pat[1]), fnum(pat[2])
        # transform pad local coord by footprint rotation.
        # KiCad stores CCW-positive angles but applies them clockwise on the
        # Y-down board coordinate system, so rotate by -frot.
        rx, ry = rot(lx, ly, -frot)
        cx, cy = fx + rx, fy + ry
        size = kid(pad, "size")
        w, h = fnum(size[1]), fnum(size[2])
        lay = kid(pad, "layers")
        laynames = set(lay[1:]) if lay else set()
        # expand wildcard *.Cu and thru-hole
        cu_layers = set()
        for ln in laynames:
            if ln == "*.Cu" or ln.endswith(".Cu") and ln.split(".")[0] in ("F", "B"):
                if ln == "*.Cu":
                    cu_layers |= CU
                else:
                    cu_layers.add(ln)
        if ptype in ("thru_hole", "np_thru_hole"):
            cu_layers |= CU
        half = max(w, h) / 2.0
        pads.append(dict(net=netname, layers=cu_layers, c=(cx, cy),
                         w=w, h=h, half=half, ref=ref, num=num, type=ptype))

# Track segments
segs = []
for sg in kids(root, "segment"):
    st = kid(sg, "start"); en = kid(sg, "end")
    net = kid(sg, "net"); lay = kid(sg, "layer")
    segs.append(dict(net=net[1] if net else None, layer=lay[1],
                     a=(fnum(st[1]), fnum(st[2])), b=(fnum(en[1]), fnum(en[2])),
                     w=fnum(kid(sg, "width")[1])))

# Vias (through unless specified)
vias = []
for v in kids(root, "via"):
    at = kid(v, "at"); net = kid(v, "net"); lay = kid(v, "layers")
    ls = set(lay[1:]) if lay else set()
    vlayers = CU if ("F.Cu" in ls and "B.Cu" in ls) or not ls else (ls & CU)
    if not vlayers:
        vlayers = CU
    vias.append(dict(net=net[1] if net else None, c=(fnum(at[1]), fnum(at[2])),
                     r=fnum(kid(v, "size")[1]) / 2.0, layers=vlayers))

# Zone filled polygons -> one node per (zone,layer,island)
zones = []
for z in kids(root, "zone"):
    net = kid(z, "net")
    netname = net[1] if net else None
    for fp in kids(z, "filled_polygon"):
        lay = kid(fp, "layer")
        layer = lay[1] if lay else None
        pts_node = kid(fp, "pts")
        poly = []
        if pts_node:
            for xy in kids(pts_node, "xy"):
                poly.append((fnum(xy[1]), fnum(xy[2])))
        if len(poly) >= 3 and layer in CU:
            xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
            zones.append(dict(net=netname, layer=layer, poly=poly,
                              bbox=(min(xs), min(ys), max(xs), max(ys))))

print(f"Parsed: {len(pads)} pads, {len(segs)} segments, {len(vias)} vias, "
      f"{len(zones)} zone-fill islands")

# ---------- build primitive list & union-find per net ----------
# Node types tagged with net; we only union within a net.
class DSU:
    def __init__(self, n):
        self.p = list(range(n))
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb

# group primitives by net
by_net = defaultdict(lambda: dict(pads=[], segs=[], vias=[], zones=[]))
for i, p in enumerate(pads):
    if p["net"]:
        by_net[p["net"]]["pads"].append(p)
for s in segs:
    if s["net"]:
        by_net[s["net"]]["segs"].append(s)
for v in vias:
    if v["net"]:
        by_net[v["net"]]["vias"].append(v)
for z in zones:
    if z["net"]:
        by_net[z["net"]]["zones"].append(z)

def pad_covers_point(pad, pt, layer, extra=TOL):
    if layer not in pad["layers"]:
        return False
    # axis-aligned approximation using max half-extent (roundrect/oval/rect/circle)
    dx = abs(pt[0] - pad["c"][0]); dy = abs(pt[1] - pad["c"][1])
    return dx <= pad["w"] / 2.0 + extra and dy <= pad["h"] / 2.0 + extra \
        or dist(pt, pad["c"]) <= pad["half"] + extra

def zone_touches_point(z, pt, layer, reach=0.0):
    if z["layer"] != layer:
        return False
    x0, y0, x1, y1 = z["bbox"]
    if not (x0 - reach - TOL <= pt[0] <= x1 + reach + TOL and
            y0 - reach - TOL <= pt[1] <= y1 + reach + TOL):
        return False
    if point_in_poly(pt, z["poly"]):
        return True
    if reach > 0 and poly_min_edge_dist(pt, z["poly"]) <= reach:
        return True
    return False

report = {}
for net, g in by_net.items():
    prims = []
    for p in g["pads"]:
        prims.append(("pad", p))
    for s in g["segs"]:
        prims.append(("seg", s))
    for v in g["vias"]:
        prims.append(("via", v))
    for z in g["zones"]:
        prims.append(("zone", z))
    n = len(prims)
    dsu = DSU(n)

    # index helpers
    for i in range(n):
        ti, oi = prims[i]
        for j in range(i + 1, n):
            tj, oj = prims[j]
            connected = False
            # ---- pad-pad (overlapping pads / same location) ----
            if ti == "pad" and tj == "pad":
                shared = oi["layers"] & oj["layers"]
                if shared and dist(oi["c"], oj["c"]) <= (oi["half"] + oj["half"]):
                    # only if actually overlapping footprints - rare; skip to avoid FP
                    connected = False
            # ---- seg-seg ----
            elif ti == "seg" and tj == "seg":
                if oi["layer"] == oj["layer"]:
                    # copper touches when centreline gap <= sum of half-widths
                    thr = oi["w"] / 2.0 + oj["w"] / 2.0 + TOL
                    for e1 in (oi["a"], oi["b"]):
                        if pt_seg_dist(e1, oj["a"], oj["b"]) <= thr:
                            connected = True; break
                    if not connected:
                        for e2 in (oj["a"], oj["b"]):
                            if pt_seg_dist(e2, oi["a"], oi["b"]) <= thr:
                                connected = True; break
            # ---- seg-pad ----
            elif {ti, tj} == {"seg", "pad"}:
                seg, pad = (oi, oj) if ti == "seg" else (oj, oi)
                if seg["layer"] in pad["layers"]:
                    if pad_covers_point(pad, seg["a"], seg["layer"]) or \
                       pad_covers_point(pad, seg["b"], seg["layer"]) or \
                       pt_seg_dist(pad["c"], seg["a"], seg["b"]) <= pad["half"] + TOL:
                        connected = True
            # ---- seg-via ----
            elif {ti, tj} == {"seg", "via"}:
                seg, via = (oi, oj) if ti == "seg" else (oj, oi)
                if seg["layer"] in via["layers"]:
                    if pt_seg_dist(via["c"], seg["a"], seg["b"]) <= via["r"] + TOL:
                        connected = True
            # ---- seg-zone ----
            elif {ti, tj} == {"seg", "zone"}:
                seg, z = (oi, oj) if ti == "seg" else (oj, oi)
                if seg["layer"] == z["layer"]:
                    if zone_touches_point(z, seg["a"], seg["layer"]) or \
                       zone_touches_point(z, seg["b"], seg["layer"]):
                        connected = True
            # ---- pad-via ----
            elif {ti, tj} == {"pad", "via"}:
                pad, via = (oi, oj) if ti == "pad" else (oj, oi)
                shared = pad["layers"] & via["layers"]
                if shared and pad_covers_point(pad, via["c"], next(iter(shared)),
                                               extra=via["r"] + TOL):
                    connected = True
            # ---- pad-zone ----
            elif {ti, tj} == {"pad", "zone"}:
                pad, z = (oi, oj) if ti == "pad" else (oj, oi)
                if z["layer"] in pad["layers"]:
                    # thermal reach: half pad + a thermal bridge span
                    if zone_touches_point(z, pad["c"], z["layer"],
                                          reach=pad["half"] + 0.6):
                        connected = True
            # ---- via-via ----
            elif ti == "via" and tj == "via":
                if (oi["layers"] & oj["layers"]) and \
                   dist(oi["c"], oj["c"]) <= oi["r"] + oj["r"] + TOL:
                    connected = True
            # ---- via-zone ----
            elif {ti, tj} == {"via", "zone"}:
                via, z = (oi, oj) if ti == "via" else (oj, oi)
                if z["layer"] in via["layers"]:
                    if zone_touches_point(z, via["c"], z["layer"], reach=via["r"]):
                        connected = True
            # ---- zone-zone (same layer overlap) ----
            elif ti == "zone" and tj == "zone":
                if oi["layer"] == oj["layer"]:
                    # cheap overlap: any vertex of one inside the other
                    bx = oi["bbox"]; by = oj["bbox"]
                    if not (bx[2] < by[0] or by[2] < bx[0] or
                            bx[3] < by[1] or by[3] < bx[1]):
                        if any(point_in_poly(pt, oj["poly"]) for pt in oi["poly"][::7]) or \
                           any(point_in_poly(pt, oi["poly"]) for pt in oj["poly"][::7]):
                            connected = True
            if connected:
                dsu.union(i, j)

    # components that contain at least one pad
    pad_comp = defaultdict(list)
    for i, (t, o) in enumerate(prims):
        if t == "pad":
            pad_comp[dsu.find(i)].append(o)
    ncomp = len(pad_comp)
    npads = len(g["pads"])
    report[net] = dict(npads=npads, ncomp=ncomp, comps=pad_comp, nprims=n,
                       nseg=len(g["segs"]), nvia=len(g["vias"]),
                       nzone=len(g["zones"]))

# ---------- print results ----------
bad = []
single_pad = []
for net, r in sorted(report.items()):
    if r["npads"] <= 1:
        single_pad.append(net)
        continue
    if r["ncomp"] != 1:
        bad.append(net)

print("\n" + "=" * 68)
print("CONNECTIVITY RESULT (per net, pads must be in ONE copper island)")
print("=" * 68)
print(f"nets with >1 pad checked : {sum(1 for n,r in report.items() if r['npads']>1)}")
print(f"nets FULLY connected     : {sum(1 for n,r in report.items() if r['npads']>1 and r['ncomp']==1)}")
print(f"nets with ISLANDS (open) : {len(bad)}")
print(f"single-pad/no-net nets   : {len(single_pad)}")

if bad:
    print("\n--- NETS WITH DISCONNECTED ISLANDS (potential opens) ---")
    for net in bad:
        r = report[net]
        print(f"\n[{net}] pads={r['npads']} split into {r['ncomp']} islands "
              f"(segs={r['nseg']} vias={r['nvia']} zones={r['nzone']})")
        for ci, (comp, plist) in enumerate(r["comps"].items(), 1):
            tags = ", ".join(sorted(f"{p['ref']}.{p['num']}" for p in plist))
            print(f"   island {ci}: {tags}")

# GND focus
print("\n" + "=" * 68)
print("GND ROUTE CHECK")
print("=" * 68)
g = report.get("GND")
if g:
    print(f"GND pads              : {g['npads']}")
    print(f"GND copper islands    : {g['ncomp']}  (1 = all GND pads tied together)")
    print(f"GND tracks / vias     : {g['nseg']} segments, {g['nvia']} vias")
    print(f"GND zone fill islands : {g['nzone']}")
    fzones = [z for z in zones if z['net'] == 'GND' and z['layer'] == 'F.Cu']
    bzones = [z for z in zones if z['net'] == 'GND' and z['layer'] == 'B.Cu']
    print(f"GND pour: F.Cu islands={len(fzones)}  B.Cu islands={len(bzones)}")
    if g['ncomp'] == 1:
        print("RESULT: PASS - every GND pad reaches the same copper island.")
    else:
        print("RESULT: FAIL - GND pads split across islands:")
        for ci, (comp, plist) in enumerate(g["comps"].items(), 1):
            tags = ", ".join(sorted(f"{p['ref']}.{p['num']}" for p in plist))
            print(f"   island {ci} ({len(plist)} pads): {tags}")

print("\nDONE.")
