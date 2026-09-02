#!/usr/bin/env python3
"""
HAKAI mouse Rev 5.3 - PCB generator (pcbnew scripting, KiCad 10).

Reads the schematic-exported netlist, builds a .kicad_pcb with:
  * every component's footprint loaded from the KiCad 10 libraries,
  * custom footprints (PAW3311 iDIP-8 incl. aperture/LED board cutouts per
    datasheet Table 9 L0AJ-LSG1 drawing, Kailh GM8/D2F switch, 11mm encoder)
    built from datasheet dimensions and saved to footprints.pretty,
  * all pads net-assigned from the netlist (ratsnest = full connectivity),
  * functional placement (sensor optical center at board center, RF at edge),
  * GND pour on F.Cu/B.Cu shaped to EXCLUDE the antenna keep-out region,
  * board outline 70 x 110 mm, 0.8 mm thickness (sensor requirement).

The board is intentionally UNROUTED: RF routing must copy Nordic's reference
geometry and sensor routing must respect the PixArt clear zone.
"""
import re
import os
import math
import pcbnew

# package-relative: PROJ is the folder above tools/; the netlist comes from
# PROJ/build/net.net (export with:
#   kicad-cli sch export netlist --output build/net.net hakai_mouse_final.kicad_sch)
PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
KFP = r"C:\Program Files\KiCad\10.0\share\kicad\footprints"
NET_FILE = os.path.join(PROJ, "build", "net.net")
OUT_PCB = os.path.join(PROJ, "hakai_mouse_final.kicad_pcb")
CUSTOM_LIB = os.path.join(PROJ, "footprints.pretty")

MM = pcbnew.FromMM


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


# ---------------- netlist parsing -------------------------------------------

def parse_sexp(s):
    toks = re.findall(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+', s)
    stack = [[]]
    for t in toks:
        if t == '(':
            stack.append([])
        elif t == ')':
            done = stack.pop()
            stack[-1].append(done)
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


root = parse_sexp(open(NET_FILE, encoding="utf-8").read())

comps = {}   # ref -> (value, footprint)
for c in find_all(root, 'comp'):
    ref = child(c, 'ref')[1]
    val = child(c, 'value')[1] if child(c, 'value') else ""
    fp = child(c, 'footprint')
    comps[ref] = (val, fp[1] if fp and len(fp) > 1 else "")

nets = {}    # name -> [(ref, pad)]
for n in find_all(root, 'net'):
    name = child(n, 'name')[1].lstrip('/')
    nodes = []
    for nd in find_all(n, 'node'):
        nodes.append((child(nd, 'ref')[1], child(nd, 'pin')[1]))
    nets[name] = nodes

print(f"netlist: {len(comps)} components, {len(nets)} nets")

# ---------------- board ------------------------------------------------------

board = pcbnew.CreateEmptyBoard()
bds = board.GetDesignSettings()
bds.SetBoardThickness(MM(0.8))
# BQ24074 footprint carries 0.2mm thermal vias-in-pad; sensor LED pads sit at
# the lens cutout lip per PixArt Table 9 -> relax the two default constraints
bds.m_MinThroughDrill = MM(0.2)
bds.m_CopperEdgeClearance = MM(0.1)

netinfo = {}
for name in nets:
    ni = pcbnew.NETINFO_ITEM(board, name)
    board.Add(ni)
    netinfo[name] = ni

# pad -> net lookup
padnet = {}
for name, nodes in nets.items():
    for ref, pad in nodes:
        padnet[(ref, pad)] = name

# ---------------- custom footprint builders ---------------------------------

def new_fp(name, desc):
    fp = pcbnew.FOOTPRINT(board)
    fp.SetFPID(pcbnew.LIB_ID("hakai_fp", name))
    fp.SetLibDescription(desc)
    return fp


def place_ref(fp, x, y, size=1.0, hide=False):
    """Position the footprint's silk reference text at local (x,y) so it does
    not sit on a pad / cutout (custom footprints default the ref to origin =
    on pad 1). Value is pushed to F.Fab + hidden. hide=True also drops the
    reference to F.Fab (for parts under the lens where silk is pointless)."""
    r = fp.Reference()
    r.SetPosition(V(x, y))
    r.SetTextSize(V(size, size))
    r.SetLayer(pcbnew.F_Fab if hide else pcbnew.F_SilkS)
    v = fp.Value()
    v.SetPosition(V(x, y - (size + 0.4)))
    v.SetTextSize(V(size, size))
    v.SetLayer(pcbnew.F_Fab)
    v.SetVisible(False)


def add_pth(fp, num, x, y, pad_d, drill_d, shape=None):
    p = pcbnew.PAD(fp)
    p.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
    p.SetShape(shape if shape is not None else pcbnew.PAD_SHAPE_CIRCLE)
    p.SetSize(V(pad_d, pad_d))
    p.SetDrillSize(V(drill_d, drill_d))
    p.SetLayerSet(pcbnew.PAD.PTHMask())
    p.SetNumber(str(num))
    p.SetFPRelativePosition(V(x, y))
    fp.Add(p)
    return p


def add_line(fp, x1, y1, x2, y2, layer, w=0.12):
    s = pcbnew.PCB_SHAPE(fp)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(V(x1, y1))
    s.SetEnd(V(x2, y2))
    s.SetLayer(layer)
    s.SetWidth(MM(w))
    fp.Add(s)


def add_rect(fp, x1, y1, x2, y2, layer, w=0.12):
    s = pcbnew.PCB_SHAPE(fp)
    s.SetShape(pcbnew.SHAPE_T_RECT)
    s.SetStart(V(x1, y1))
    s.SetEnd(V(x2, y2))
    s.SetLayer(layer)
    s.SetWidth(MM(w))
    fp.Add(s)


def add_circle(fp, cx, cy, r, layer, w=0.12):
    s = pcbnew.PCB_SHAPE(fp)
    s.SetShape(pcbnew.SHAPE_T_CIRCLE)
    s.SetCenter(V(cx, cy))
    s.SetEnd(V(cx + r, cy))
    s.SetLayer(layer)
    s.SetWidth(MM(w))
    fp.Add(s)


def add_rounded_poly(fp, pts, r, layer, w=0.1, seg=16):
    """Closed rectilinear polygon with every 90-degree corner filleted at
    radius r, emitted as a segment chain (chord error <2um at r=0.9/seg=16,
    far below fab tolerance). Handles the degenerate stadium case where a
    side collapses to zero length between two fillets."""
    n = len(pts)
    chain = []
    for i in range(n):
        pp, p, pn = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        u1 = (p[0] - pp[0], p[1] - pp[1])
        u2 = (pn[0] - p[0], pn[1] - p[1])
        l1 = math.hypot(*u1); l2 = math.hypot(*u2)
        u1 = (u1[0] / l1, u1[1] / l1); u2 = (u2[0] / l2, u2[1] / l2)
        a = (p[0] - u1[0] * r, p[1] - u1[1] * r)      # fillet start
        b = (p[0] + u2[0] * r, p[1] + u2[1] * r)      # fillet end
        c = (a[0] + u2[0] * r, a[1] + u2[1] * r)      # arc center (90 deg)
        a0 = math.atan2(a[1] - c[1], a[0] - c[0])
        a1 = math.atan2(b[1] - c[1], b[0] - c[0])
        cross = u1[0] * u2[1] - u1[1] * u2[0]         # turn direction
        if cross > 0 and a1 < a0:
            a1 += 2 * math.pi
        if cross < 0 and a1 > a0:
            a1 -= 2 * math.pi
        for k in range(seg + 1):
            t = a0 + (a1 - a0) * k / seg
            chain.append((c[0] + r * math.cos(t), c[1] + r * math.sin(t)))
    for i in range(len(chain)):
        x1, y1 = chain[i]
        x2, y2 = chain[(i + 1) % len(chain)]
        if math.hypot(x2 - x1, y2 - y1) < 1e-6:
            continue
        add_line(fp, x1, y1, x2, y2, layer, w)


def build_paw3311():
    """PAW3311DB iDIP-8 with L0AJ-LSG1 SMT-lens board features, v5.3: EXACT
    per datasheet v1.0 Table 9 (page 14, L0AJ-LSG1 column). Origin = pin 1;
    +x toward lens/LED side, +y toward pin row 5-8. 8x PTH 0.80mm holes,
    rows 12.60 apart, 2.00 pitch, 1.00 stagger."""
    fp = new_fp("PAW3311DB_iDIP8_L0AJ",
                "PixArt PAW3311DB 8-pin staggered DIP + L0AJ-LSG1 SMT lens features. "
                "All cutouts/holes per datasheet v1.0 Table 9 (corners R0.40 max): "
                "aperture cutout w/ optical-axis notch, R0.90x2.00 LED stadium, "
                "2x lens guide-post holes (heat-stake capable). PCB must be 0.8mm.")
    # pins 1-4 top row (right to left), pins 5-8 bottom row (left to right).
    # Hole dia 0.80 per Table 9 "8X (D)0.80".
    for num, x in (("1", 0.0), ("2", -2.0), ("3", -4.0), ("4", -6.0)):
        add_pth(fp, num, x, 0.0, 1.5, 0.80)
    for num, x in (("5", -5.0), ("6", -3.0), ("7", -1.0), ("8", 1.0)):
        add_pth(fp, num, x, 12.60, 1.5, 0.80)
    # Aperture board cutout: x -7.86..1.64, y 1.38..11.23, PLUS the optical-axis
    # notch to x=-9.56 between y 5.10..7.50 (all +/-0.05 dims in Table 9).
    # Corners R0.40 max.
    add_rounded_poly(fp, [(-7.86, 1.38), (1.64, 1.38), (1.64, 11.23),
                          (-7.86, 11.23), (-7.86, 7.50), (-9.56, 7.50),
                          (-9.56, 5.10), (-7.86, 5.10)],
                     0.40, pcbnew.Edge_Cuts, 0.1)
    # LED cutout: "R0.90 X 2.00" stadium centered on LED center (3.75, 6.30):
    # 2.00 total length in x (0.20 straight + 2x R0.90 ends), 1.80 tall in y.
    add_rounded_poly(fp, [(2.75, 5.40), (4.75, 5.40), (4.75, 7.20), (2.75, 7.20)],
                     0.90, pcbnew.Edge_Cuts, 0.1)
    # 2x lens guide-post holes: x 4.58..6.58, y 1.50..3.10 and 9.50..11.10,
    # corners R0.40 max. Lens posts heat-stake here (assembly note 8, p.20).
    add_rounded_poly(fp, [(4.58, 1.50), (6.58, 1.50), (6.58, 3.10), (4.58, 3.10)],
                     0.40, pcbnew.Edge_Cuts, 0.1)
    add_rounded_poly(fp, [(4.58, 9.50), (6.58, 9.50), (6.58, 11.10), (4.58, 11.10)],
                     0.40, pcbnew.Edge_Cuts, 0.1)
    # clear zone marking (keep copper out: 1.64..7.48 x, -0.30..12.90 y)
    add_rect(fp, 1.64, -0.30, 7.48, 12.90, pcbnew.F_Fab, 0.1)
    # full package body ghost on F.Fab (documentation, no clearance rules)
    add_rect(fp, -8.0, -1.2, 3.0, 13.8, pcbnew.F_Fab, 0.1)
    # optical center cross at approx (-2.5, 6.30)
    add_line(fp, -3.5, 6.30, -1.5, 6.30, pcbnew.F_Fab)
    add_line(fp, -2.5, 5.30, -2.5, 7.30, pcbnew.F_Fab)
    # SILK: pin-side outline only - open toward the lens (x>0) and split on the
    # left to clear the optical-axis notch (y 5.10..7.50). The old full body
    # rect crossed the notch, the clear zone and the LED stadium cutout.
    # left edge at x=-8.3: >=0.44mm clear of the aperture edge (x=-7.86)
    add_line(fp, -8.3, -1.2, 0.0, -1.2, pcbnew.F_SilkS, 0.15)   # top
    add_line(fp, -8.3, 13.8, 0.0, 13.8, pcbnew.F_SilkS, 0.15)   # bottom
    add_line(fp, -8.3, -1.2, -8.3, 4.60, pcbnew.F_SilkS, 0.15)  # left, above notch
    add_line(fp, -8.3, 8.00, -8.3, 13.8, pcbnew.F_SilkS, 0.15)  # left, below notch
    # pin-1 dot (just outside pin 1 at origin, clear of its annulus)
    add_circle(fp, 1.30, -0.60, 0.15, pcbnew.F_SilkS, 0.2)
    place_ref(fp, -3.5, -2.3)     # ref above the pin rows, off all copper/cutouts
    # courtyard: main body region + a bump over the optical-axis notch,
    # drawn as ONE closed polygon (two touching rects = self-intersecting)
    court = [(-8.5, -1.7), (2.6, -1.7), (2.6, 14.3), (-8.5, 14.3),
             (-8.5, 7.70), (-9.96, 7.70), (-9.96, 4.90), (-8.5, 4.90)]
    for i in range(len(court)):
        x1, y1 = court[i]
        x2, y2 = court[(i + 1) % len(court)]
        add_line(fp, x1, y1, x2, y2, pcbnew.F_CrtYd, 0.05)
    return fp


def build_irled():
    """SMT IR emitter pads per PAW3311 Table 9 'LED Soldering Pad': two pads
    flanking the R0.90x2.00 LED cutout on the y axis, LED center = origin.
    Pad geometry accepts a ~3.0-3.2mm emitter (1206/PLCC-class); confirm
    against the final PixArt-recommended LED P/N before fab.
    Footprint axis = x (pad1 at -x); place at 90deg so pads flank the cutout
    vertically on the board like Table 9."""
    fp = new_fp("IRLED_L0AJ_3311",
                "IR emitter for PAW3311 + L0AJ-LSG1 set. Pads per datasheet Table 9 "
                "LED Soldering Pad positions (0.12 clear of the stadium cutout). "
                "Verify vs final LED P/N reflow pad recommendation.")
    for num, x in (("1", -1.42), ("2", 1.42)):
        p = pcbnew.PAD(fp)
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        p.SetShape(pcbnew.PAD_SHAPE_ROUNDRECT)
        p.SetRoundRectRadiusRatio(0.15)
        p.SetSize(V(0.80, 1.40))     # 0.80 along part axis, 1.40 across
        p.SetLayerSet(pcbnew.PAD.SMDMask())
        p.SetNumber(num)
        p.SetFPRelativePosition(V(x, 0.0))
        fp.Add(p)
    # cathode (pad 2 = SENS_LED -> sensor pin 1 current sink) bar marker
    add_line(fp, 2.05, -0.75, 2.05, 0.75, pcbnew.F_Fab, 0.12)
    # body ghost ~3.2 x 1.6 (emitter package)
    add_rect(fp, -1.6, -0.8, 1.6, 0.8, pcbnew.F_Fab, 0.1)
    # silk polarity tick outside the pads (clear of cutout + mask)
    add_line(fp, 2.35, -0.8, 2.35, 0.8, pcbnew.F_SilkS, 0.15)
    add_rect(fp, -2.1, -1.0, 2.1, 1.0, pcbnew.F_CrtYd, 0.05)
    # D2 sits inside the lens clear zone next to the LED stadium cutout - a
    # silk refdes here would print over the cutout / under the lens. Keep the
    # reference on F.Fab only (assembly uses the pick-and-place file).
    place_ref(fp, 0.0, -1.8, size=0.8, hide=True)
    return fp


def build_kailh():
    """Kailh GM 8.0 (Omron D2F/D2FC drop-in): 3 PTH terminals, 5.08mm pitch.
    1=COM, 2=NO, 3=NC (left to right from plunger end).
    v5.3, verified against official Omron D2F + D2FC datasheets and the Kailh
    GM 8.0 drawing: the switch bottom is FLAT - there are NO locating bosses
    and no boss holes belong in the PCB (the drawings' two small holes are in
    the switch SIDE face, centers 1.5mm above the seating plane - chassis-pin
    features, not PCB features). Official PCB pattern = 3 terminal holes only,
    (D)1.2 at 5.08+/-0.1 pitch; body 12.8 x 5.8 CENTERED on the terminal row.
    Plunger/actuator sits ~1.95mm left of the centre terminal (verified against
    the Kailh GM 8.0 and Omron D2F/D2FC drawings), marked on F.Fab."""
    fp = new_fp("SW_Kailh_GM8_D2F",
                "Kailh GM 8.0 mouse microswitch, D2F/D2FC pattern per official Omron "
                "drawing: 3x 1.2mm holes, 5.08mm pitch, flat bottom (NO boss holes - "
                "side-face holes are chassis features, not PCB features). "
                "Body 12.8x5.8 centered on terminals; plunger ~1.95mm left of centre "
                "terminal (F.Fab circle).")
    for num, x in (("1", -5.08), ("2", 0.0), ("3", 5.08)):
        add_pth(fp, num, x, 0.0, 2.1, 1.2)
    # true top-view body: 12.8 x 5.8 centered on the terminal row
    add_rect(fp, -6.4, -2.9, 6.4, 2.9, pcbnew.F_SilkS, 0.15)
    # plunger position marker at x=-1.95 (verified against the Kailh GM 8.0
    # and Omron D2F drawings; the 5.2 body dimension is not pad-datum'd)
    add_circle(fp, -1.95, 0.0, 1.0, pcbnew.F_Fab, 0.1)
    add_rect(fp, -6.9, -3.4, 6.9, 3.4, pcbnew.F_CrtYd, 0.05)
    place_ref(fp, 0.0, -3.9)     # ref above the body, clear of the 3 terminals
    return fp


def build_encoder():
    """11mm mouse scroll encoder, ROTATION ONLY, standing body with horizontal
    shaft pointing +X (into the wheel bay). Signal pins A/C/B in a vertical
    column at 2.0mm pitch; MP1/MP2 = metal bracket tabs (mechanical).
    VERIFY pin/tab spacing against the chosen vendor drawing (TTC/F-switch)."""
    fp = new_fp("ENC_Mouse_11mm",
                "11mm mouse quadrature encoder (no switch), shaft +X into wheel bay. "
                "A/C/B 2.0mm pitch + 2 bracket tabs. VERIFY vs vendor drawing before fab.")
    for num, y in (("A", -2.0), ("C", 0.0), ("B", 2.0)):
        add_pth(fp, num, 0.0, y, 1.7, 1.0)
    for num, y in (("MP1", -5.5), ("MP2", 5.5)):
        add_pth(fp, num, -3.5, y, 2.3, 1.4)
    # body ghost (full size) on F.Fab; SILK body shrunk to y +/-4.2 so it does
    # not cross the MP1/MP2 bracket-tab pads (at y +/-5.5, dia 2.3 -> +/-6.65)
    add_rect(fp, -8.0, -6.0, 2.0, 6.0, pcbnew.F_Fab, 0.12)
    add_rect(fp, -8.0, -4.2, 2.0, 4.2, pcbnew.F_SilkS, 0.15)
    add_line(fp, 2.0, 0.0, 5.5, 0.0, pcbnew.F_Fab, 0.15)
    add_line(fp, 4.5, -0.8, 5.5, 0.0, pcbnew.F_Fab, 0.15)
    add_line(fp, 4.5, 0.8, 5.5, 0.0, pcbnew.F_Fab, 0.15)
    add_rect(fp, -8.5, -6.5, 2.5, 5.5, pcbnew.F_CrtYd, 0.05)
    place_ref(fp, 0.5, -7.2)     # ref top-right, clear of body/tabs/pads
    return fp


CUSTOM_BUILDERS = {
    "hakai_fp:PAW3311DB_iDIP8_L0AJ": build_paw3311,
    "hakai_fp:IRLED_L0AJ_3311": build_irled,
    "hakai_fp:SW_Kailh_GM8_D2F": build_kailh,
    "hakai_fp:ENC_Mouse_11mm": build_encoder,
}

# ---------------- placement map (absolute mm, board 100..170 x, 40..150 y) ---

PLACE = {
    # ears: main switches flank the top-center wheel bay (notch x 123..147)
    "SW1": (109, 48, 0), "SW2": (160, 50, 0),
    "R15": (103.5, 58, 90), "C28": (106.5, 58, 90),
    "R16": (150, 70, 90), "C29": (153, 70, 90),
    # SPLIT WHEEL: EC1 on the LEFT bay wall (shaft +X into bay, D-socket
    # takes the wheel axle); SW5 tact on the RIGHT wall under the cradle arm
    "EC1": (117, 61, 0),
    "SW5": (155, 62, 0),   # Kailh GM 8.0, plunger end (pin 1) toward the bay
    "R19": (120, 84, 90), "R20": (120, 88.5, 90),
    "R21": (150, 84, 90), "C32": (153.5, 84, 90), "C33": (157, 84, 90),
    # left edge: side buttons. SW4 at x=107.2: the true centered 5.8mm body
    # (v5.3) would overhang the x=104 edge at the old x=106 (SW3 is fine -
    # the edge is at x=100 alongside it)
    "SW3": (106, 82, 90), "SW4": (107.2, 97, 90),
    "R17": (112.5, 88, 90), "C30": (115.5, 88, 90),
    "R18": (112.5, 103, 90), "C31": (115.5, 103, 90),
    # sensor moved down (optical center (135,106)) to clear the encoder
    "U5": (137.5, 99.7, 0), "D2": (141.25, 106, 90),
    # C26/C27 straddle the aperture-notch cutout (y 104.8..107.2 at x>127.84):
    # both moved clear of the notch band (v5.3, Table 9 full-size cutout)
    "C25": (127.5, 100, 90), "C26": (127.5, 103.0, 90), "C27": (127.5, 109.0, 90),
    "C34": (127.5, 112, 90), "R13": (127.5, 116, 90), "R14": (124, 116, 90),
    # v5.3: R22/C35/R23 moved OUT of the PixArt Table 9 clear zone (board
    # x 139.14..144.98, y 99.4..112.6 - lens LED-clip tower + heat-staked
    # guide posts live there) AND out of the x=148 MCU-decoupling column they
    # briefly collided with. Parked in the open band below the sensor (nothing
    # else there until ANT1 at y=140); LED chain to D2 stays short.
    "R22": (138.5, 115.5, 0), "C35": (141.5, 115.5, 0), "R23": (144.5, 115.5, 0),
    # right-center: MCU + clocks + RF (pulled in from the narrowed right edge)
    "U4": (157, 105, 0),
    "C13": (150, 98, 0), "C14": (153.5, 98, 0), "C15": (157, 98, 0),
    "C16": (160.5, 98, 0), "C17": (164, 98, 0),
    "C9": (148, 101, 90), "C10": (148, 104, 90), "C11": (148, 107, 90),
    "C12": (148, 110, 90), "L1": (148, 113, 90), "L2": (148, 116, 90),
    "Y1": (151, 113, 0), "Y2": (159, 113, 0),
    # crystal load caps dropped to y=119 to clear the L1/L2 DC-DC column refs
    "C18": (149, 119, 90), "C19": (152.5, 119, 90),
    "C20": (157, 119, 90), "C21": (160.5, 119, 90),
    "C22": (163.5, 103, 90), "L3": (163.5, 107, 90), "C23": (163.5, 111, 90),
    "L4": (163.5, 115, 90), "C24": (163.5, 119, 90),
    "ANT1": (138, 140, 0),
    # status LED
    # R24 nudged left off R6's refdes (was (117,113) ~1.4mm from R6)
    "R12": (116.5, 108, 90), "D3": (119.5, 108, 90), "Q2": (124, 112, 0), "R24": (114, 113, 90),
    # left-bottom: charger + LDO + rails
    "U2": (112, 120, 0),
    "C1": (106, 126.5, 90), "C2": (109.5, 126.5, 90), "C3": (113, 126.5, 90),
    "R3": (117, 126.5, 90), "R4": (120.5, 126.5, 90), "R5": (124, 126.5, 90),
    "R6": (118, 114, 90), "R7": (121.5, 114, 90),
    "F1": (106.5, 122, 0), "U3": (114, 133, 0),
    "C4": (118, 133, 90), "C5": (121, 133, 90), "C6": (124, 136, 90),
    "FB1": (110.5, 146, 90), "C7": (116, 120, 90), "C8": (119.5, 120, 90),
    # battery + gauge (v5.2: Q3/R25 = high-side divider switch; C36 = BAT bypass)
    "J2": (133, 125, 0), "R8": (126, 133, 90), "R9": (129, 133, 90),
    "R10": (132, 133, 90), "Q1": (140.5, 130, 0),
    # Q3 below the R8/R9/R10 divider row (tight corner; its refdes lightly
    # overlaps R10's - cosmetic silk only, no clearance/electrical issue)
    "C36": (108, 117, 0), "Q3": (131, 136.8, 0), "R25": (127.5, 136.8, 90),
    # USB-C at the tail (bottom edge), CC/TVS beside it
    "J1": (119, 145, 180),
    "R1": (129, 140, 90), "R2": (132, 140, 90), "D1": (129, 146, 0),
    # debug + test points (top-right ear)
    # R11 beside the J3 SWD header (its refdes lightly overlaps J3's silk -
    # cosmetic only; the tight top-left corner leaves no clear alternative)
    "J3": (107, 133, 0), "R11": (109.8, 133, 90),
    # v5.3: TP row raised to y=43.5 - SW2's corrected symmetric courtyard
    # (reaches y=46.55) overlapped the old y=46 row, and the 6.5mm switch
    # body would have blocked probe access
    "TP1": (150, 43.5, 0), "TP2": (153, 43.5, 0), "TP3": (156, 43.5, 0),
    "TP4": (159, 43.5, 0), "TP5": (162, 43.5, 0), "TP6": (165, 43.5, 0),
}

# ---------------- load / build / place footprints ---------------------------

def load_lib_fp(fpid):
    lib, name = fpid.split(":", 1)
    return pcbnew.FootprintLoad(os.path.join(KFP, lib + ".pretty"), name)


custom_saved = {}
fallback_x = 102.0

for ref, (val, fpid) in sorted(comps.items()):
    if not fpid:
        print(f"WARN {ref}: no footprint, skipped")
        continue
    if fpid in CUSTOM_BUILDERS:
        fp = CUSTOM_BUILDERS[fpid]()
        custom_saved[fpid] = fp
    else:
        fp = load_lib_fp(fpid)
        if fp is None:
            raise SystemExit(f"FOOTPRINT NOT FOUND: {fpid} for {ref}")
    fp.SetReference(ref)
    fp.SetValue(val)
    board.Add(fp)

    # net assignment
    fp_pads = {}
    for p in fp.Pads():
        fp_pads.setdefault(p.GetNumber(), []).append(p)
    ref_netpads = {pad: net for (r, pad), net in padnet.items() if r == ref}

    # crystal 4-pad special case: symbol pin 2 -> pad 3; pads 2/4 -> GND
    if ref == "Y1" and "3" in fp_pads and "4" in fp_pads:
        remap = {"1": ref_netpads.get("1"), "3": ref_netpads.get("2"),
                 "2": "GND", "4": "GND"}
        for num, netname in remap.items():
            if netname:
                for p in fp_pads.get(num, []):
                    p.SetNetCode(netinfo[netname].GetNetCode())
    else:
        used = set()
        for num, netname in ref_netpads.items():
            if num in fp_pads:
                for p in fp_pads[num]:
                    p.SetNetCode(netinfo[netname].GetNetCode())
                used.add(num)
        leftover_net = [n for num, n in ref_netpads.items() if num not in fp_pads]
        # unnumbered pads are mechanical (paste apertures / anchors): never netted
        extra_pads = [num for num in fp_pads if num not in ref_netpads and num != ""]
        if leftover_net and extra_pads:
            # e.g. nRF die pad "74" in netlist vs EP pad number in footprint
            nn = leftover_net[0]
            for num in extra_pads:
                for p in fp_pads[num]:
                    p.SetNetCode(netinfo[nn].GetNetCode())
            print(f"note {ref}: netlist pad(s) {[num for num in ref_netpads if num not in fp_pads]} "
                  f"mapped onto footprint pad(s) {extra_pads} -> {nn}")
        elif extra_pads and ref == "ANT1":
            # SWRA117D ground stubs -> GND
            for num in extra_pads:
                for p in fp_pads[num]:
                    p.SetNetCode(netinfo["GND"].GetNetCode())
            print(f"note ANT1: extra pads {extra_pads} -> GND")

    # thermal vias-in-pad (tiny PTH drills) must connect to pours SOLID -
    # a 0.2mm via can't host two thermal-relief spokes (starved_thermal DRC)
    for p in fp.Pads():
        if (p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
                and p.GetDrillSize().x <= MM(0.25)):
            try:
                p.SetZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
            except AttributeError:
                p.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)

    if ref in PLACE:
        x, y, rot = PLACE[ref]
        fp.SetPosition(V(x, y))
        fp.SetOrientationDegrees(rot)
    else:
        fp.SetPosition(V(fallback_x, 145))
        fallback_x += 4.0
        print(f"WARN {ref}: no placement entry, parked at bottom-left")

# v5.3: C35's relocation out of the PixArt clear zone leaves the GND zone
# west of C11 pad 2 room for only one thermal spoke (starved_thermal at the
# min-2 rule). Connect that pad SOLID - lower inductance for a DEC4_6
# decoupling return anyway.
for _fp in board.GetFootprints():
    if _fp.GetReference() == "C11":
        for _p in _fp.Pads():
            if _p.GetNumber() == "2":
                try:
                    _p.SetZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
                except AttributeError:
                    _p.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)

# ---------------- board outline, zones, text --------------------------------

def outline_poly(points):
    """Closed board outline from a point list (Edge.Cuts segments)."""
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(V(x1, y1))
        s.SetEnd(V(x2, y2))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(MM(0.1))
        board.Add(s)


# Mouse-plate outline modeled on the reference board:
#  - U-shaped wheel bay open at the top edge (x 123..147, down to y 78)
#  - switch "ears" either side of the bay, chamfered top corners
#  - sides step in at mid-height -> narrower tail, chamfered tail corners
OUTLINE = [
    (104, 40), (123, 40),               # top edge, left ear
    (123, 78), (147, 78),               # wheel bay (open U)
    (147, 40), (166, 40),               # top edge, right ear
    (170, 44),                          # chamfer TR
    (170, 88), (166, 96),               # right side + step-in
    (166, 144), (160, 150),             # right tail + chamfer BR
    (110, 150), (104, 144),             # bottom edge + chamfer BL
    (104, 96), (100, 88),               # left tail + step-out
    (100, 44),                          # left side; closes via chamfer TL
]
outline_poly(OUTLINE)

# mounting holes (M3, board-only footprints - not in the schematic netlist)
for i, (mx, my) in enumerate(((114, 72), (160, 74), (155, 130)), start=1):
    mh = pcbnew.FootprintLoad(os.path.join(KFP, "MountingHole.pretty"),
                              "MountingHole_3.2mm_M3")
    mh.SetReference(f"MH{i}")
    mh.SetValue("M3")
    mh.SetAttributes(mh.GetAttributes() | pcbnew.FP_BOARD_ONLY)
    # board-only holes: keep the refdes off silk (MH1's ref sat over EC1's
    # bracket tab). Reference lives on F.Fab for documentation only.
    mh.Reference().SetLayer(pcbnew.F_Fab)
    mh.Reference().SetVisible(False)
    board.Add(mh)
    mh.SetPosition(V(mx, my))

# GND pours: cover the whole plate except the antenna keep-out (bottom-right);
# the zone auto-clips to the board outline (notch/chamfers handled by KiCad)
KEEPOUT_POLY = [(100, 40), (170, 40), (170, 135), (135, 135), (135, 150), (100, 150)]
for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNetCode(netinfo["GND"].GetNetCode())
    z.Outline().NewOutline()
    for x, y in KEEPOUT_POLY:
        z.Outline().Append(MM(x), MM(y))
    z.SetLocalClearance(MM(0.3))
    z.SetMinThickness(MM(0.25))
    board.Add(z)


def note(text, x, y, size=1.5):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text)
    t.SetPosition(V(x, y))
    t.SetLayer(pcbnew.Cmts_User)
    t.SetTextSize(V(size, size))
    board.Add(t)


note("HAKAI MOUSE REV 5.3 - SPLIT WHEEL, UNROUTED", 135, 36, 2.0)
note("Wheel bay 24x38mm: EC1 encoder on LEFT wall (D-socket, shaft +X); SW5 Kailh GM 8.0 on RIGHT wall = middle click", 135, 164.5)
note("Sensor aperture + LED cutouts inside U5 footprint; USB-C charge port at tail edge; 3x M3 holes", 135, 168)
note("RF: copy Nordic PCA10100 layout geometry verbatim; antenna zone kept copper-free", 135, 154)
note("Sensor: PCB 0.8mm; clear zone right of sensor must stay copper-free (F.Fab marking)", 135, 157.5)
note("Route SPI/battery away from RF; length-match nothing; GND stitch vias around RF", 135, 161)

# title block -> carried into gerber X2 ProjectId metadata (no more "rev?")
tb = board.GetTitleBlock()
tb.SetTitle("HAKAI Wireless Gaming Mouse")
tb.SetRevision("5.3")
tb.SetDate("2026-07-09")
tb.SetCompany("HAKAI Engineering")

pcbnew.SaveBoard(OUT_PCB, board)
print("wrote", OUT_PCB)

# save custom footprints to project lib
os.makedirs(CUSTOM_LIB, exist_ok=True)
io = pcbnew.PCB_IO_KICAD_SEXPR()
for fpid, proto in CUSTOM_BUILDERS.items():
    fp = proto()
    fp.SetReference("REF**")
    io.FootprintSave(CUSTOM_LIB, fp)
print("custom footprints saved to", CUSTOM_LIB)

# project fp-lib-table so schematic<->pcb sync resolves hakai_fp:*
with open(os.path.join(PROJ, "fp-lib-table"), "w", encoding="utf-8") as f:
    f.write('(fp_lib_table\n  (version 7)\n'
            '  (lib (name "hakai_fp")(type "KiCad")(uri "${KIPRJMOD}/footprints.pretty")'
            '(options "")(descr "Hakai custom footprints"))\n)\n')
print("fp-lib-table written")
