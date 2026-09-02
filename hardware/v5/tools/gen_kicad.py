#!/usr/bin/env python3
"""
HAKAI Wireless Gaming Mouse Rev 2.0 - KiCad schematic generator.
Emits a flat single-sheet .kicad_sch (file version 20231120, KiCad 8 format;
opens in KiCad 8/9/10) plus a minimal .kicad_pro.

Connectivity model: no drawn wires -- every pin is connected either to a
global label, a power symbol, or a no_connect marker placed exactly on the
pin's electrical endpoint. Netlist-exact and ERC-checkable.

Data provenance:
  nRF52833-QIAA ball map + all decoupling/RF values: Nordic PS v1.7 Table 62 +
    sect. 7.3, cross-checked against PCA10100 DK 2.0.0 design files.
  BQ24074: TI SLUS810N.  XC6219B332MR: Torex datasheet.
  USB4105 / PEC11R / D2F / 2N7002 / PESD5V0S1BA / JST PH: vendor datasheets.
  PAW3311DB: VERIFIED against PixArt datasheet v1.0 (1A009EN, 15 Nov 2022):
    8-pin DB, VDD 1.8-2.1V (ABS MAX 2.1V), 3-wire SDIO SPI (Fig.6 MISO/MOSI-R1
    bridge), VDDREG bypass-only, MOTION push-pull, LED chain VLED->18R->IR->pin1.
  System consequence: whole design runs on a single 1.9V rail (XC6219B192MR);
    nRF52833 operates 1.7-3.6V so MCU and sensor share it with no level shift.
"""
import uuid as _uuid
import os

def u():
    return str(_uuid.uuid4())

ROOT_UUID = u()
PROJECT = "hakai_mouse_v5"
OUT_DIR = r"C:\Users\izuku\Documents\hakai\claud\hakai_mouse_v5"

F = '(effects (font (size 1.27 1.27)))'
FH = '(effects (font (size 1.27 1.27)) (hide yes))'
GRID = 1.27


def snap(v):
    return round(round(v / GRID) * GRID, 4)


def fmt(v):
    r = round(v, 4)
    if r == int(r):
        return str(int(r))
    return f"{r:g}"


# --------------------------------------------------------------------------
# Library symbols
# --------------------------------------------------------------------------

class LibPin:
    def __init__(self, number, name, side, row, etype="passive"):
        self.number = str(number)
        self.name = name
        self.side = side
        self.row = row
        self.etype = etype


class LibPart:
    """IC / multi-pin part, pins on left/right sides of a rectangle."""

    def __init__(self, name, ref_prefix, halfwidth, description="", pin_len=2.54):
        self.name = name
        self.ref = ref_prefix
        self.w2 = snap(halfwidth)
        self.desc = description
        self.pin_len = pin_len
        self.pins = []

    def pin(self, number, name, side, row, etype="passive"):
        self.pins.append(LibPin(number, name, side, row, etype))
        return self

    def _geom(self):
        rows = 1 + max(p.row for p in self.pins)
        h2 = snap((rows + 1) * 2.54 / 2.0)
        top_y = h2 - 2.54
        return h2, top_y

    def pin_local(self, number):
        p = next(q for q in self.pins if q.number == str(number))
        h2, top_y = self._geom()
        py = top_y - p.row * 2.54
        if p.side == 'L':
            px = -(self.w2 + self.pin_len)
        else:
            px = self.w2 + self.pin_len
        return px, py, p.side

    def sexpr(self):
        h2, _ = self._geom()
        s = []
        s.append(f'    (symbol "hakai:{self.name}"')
        s.append('      (pin_names (offset 1.016)) (exclude_from_sim no) (in_bom yes) (on_board yes)')
        s.append(f'      (property "Reference" "{self.ref}" (at 0 {fmt(h2 + 2.54)} 0) {F})')
        s.append(f'      (property "Value" "{self.name}" (at 0 {fmt(-(h2 + 2.54))} 0) {F})')
        s.append(f'      (property "Footprint" "" (at 0 0 0) {FH})')
        s.append(f'      (property "Datasheet" "" (at 0 0 0) {FH})')
        s.append(f'      (property "Description" "{self.desc}" (at 0 0 0) {FH})')
        s.append(f'      (symbol "{self.name}_0_1"')
        s.append(f'        (rectangle (start {fmt(-self.w2)} {fmt(h2)}) (end {fmt(self.w2)} {fmt(-h2)})'
                 ' (stroke (width 0.254) (type default)) (fill (type background)))')
        s.append('      )')
        s.append(f'      (symbol "{self.name}_1_1"')
        for p in self.pins:
            px, py, side = self.pin_local(p.number)
            ang = 0 if side == 'L' else 180
            s.append(f'        (pin {p.etype} line (at {fmt(px)} {fmt(py)} {ang}) (length {fmt(self.pin_len)})')
            s.append(f'          (name "{p.name}" {F})')
            s.append(f'          (number "{p.number}" {F})')
            s.append('        )')
        s.append('      )')
        s.append('    )')
        return "\n".join(s)


class LibPassive:
    """Vertical 2-pin part: pin 1 endpoint (0,+ext), pin 2 (0,-ext), lib Y-up."""

    def __init__(self, name, ref_prefix, description="", body="rect",
                 ext=5.08, pin_len=2.54, p1name="1", p2name="2"):
        self.name = name
        self.ref = ref_prefix
        self.desc = description
        self.body = body
        self.ext = ext
        self.pin_len = pin_len
        self.p1name, self.p2name = p1name, p2name

    def pin_local(self, number):
        if str(number) == "1":
            return 0.0, self.ext, 'T'
        return 0.0, -self.ext, 'B'

    def _body_sexpr(self):
        b = self.ext - self.pin_len
        st = '(stroke (width 0.254) (type default)) (fill (type none))'
        if self.body == "rect":
            return [f'        (rectangle (start -1.016 {fmt(b)}) (end 1.016 {fmt(-b)}) {st})']
        if self.body == "cap":
            return [f'        (polyline (pts (xy -1.905 0.635) (xy 1.905 0.635)) {st})',
                    f'        (polyline (pts (xy -1.905 -0.635) (xy 1.905 -0.635)) {st})',
                    f'        (polyline (pts (xy 0 {fmt(b)}) (xy 0 0.635)) {st})',
                    f'        (polyline (pts (xy 0 -0.635) (xy 0 {fmt(-b)})) {st})']
        if self.body == "ind":
            return [f'        (arc (start 0 {fmt(b)}) (mid 0.889 {fmt(b/2)}) (end 0 0) {st})',
                    f'        (arc (start 0 0) (mid 0.889 {fmt(-b/2)}) (end 0 {fmt(-b)}) {st})']
        if self.body == "diode":  # pin1 = anode (top), pin2 = cathode (bottom)
            return [f'        (polyline (pts (xy 0 {fmt(b)}) (xy 0 {fmt(-b)})) {st})',
                    f'        (polyline (pts (xy -1.27 1.27) (xy 1.27 1.27) (xy 0 -1.27) (xy -1.27 1.27)) {st})',
                    f'        (polyline (pts (xy -1.27 -1.27) (xy 1.27 -1.27)) {st})']
        if self.body == "led":
            return [f'        (polyline (pts (xy 0 {fmt(b)}) (xy 0 {fmt(-b)})) {st})',
                    f'        (polyline (pts (xy -1.27 1.27) (xy 1.27 1.27) (xy 0 -1.27) (xy -1.27 1.27)) {st})',
                    f'        (polyline (pts (xy -1.27 -1.27) (xy 1.27 -1.27)) {st})',
                    f'        (polyline (pts (xy 1.778 0.508) (xy 2.794 -0.508)) {st})',
                    f'        (polyline (pts (xy 2.286 1.016) (xy 3.302 0)) {st})']
        if self.body == "tvs":
            return [f'        (polyline (pts (xy 0 {fmt(b)}) (xy 0 {fmt(-b)})) {st})',
                    f'        (polyline (pts (xy -1.27 1.905) (xy 1.27 1.905) (xy 0 0) (xy -1.27 1.905)) {st})',
                    f'        (polyline (pts (xy -1.27 -1.905) (xy 1.27 -1.905) (xy 0 0) (xy -1.27 -1.905)) {st})',
                    f'        (polyline (pts (xy -1.27 0) (xy 1.27 0)) {st})']
        if self.body == "xtal":
            return [f'        (rectangle (start -1.905 1.016) (end 1.905 -1.016) {st})',
                    f'        (polyline (pts (xy -1.905 1.778) (xy 1.905 1.778)) {st})',
                    f'        (polyline (pts (xy -1.905 -1.778) (xy 1.905 -1.778)) {st})',
                    f'        (polyline (pts (xy 0 {fmt(b)}) (xy 0 1.778)) {st})',
                    f'        (polyline (pts (xy 0 -1.778) (xy 0 {fmt(-b)})) {st})']
        if self.body == "fuse":
            return [f'        (rectangle (start -1.016 {fmt(b)}) (end 1.016 {fmt(-b)}) {st})',
                    f'        (polyline (pts (xy 0 {fmt(b)}) (xy 0 {fmt(-b)})) {st})']
        if self.body == "fb":
            return [f'        (rectangle (start -1.016 {fmt(b)}) (end 1.016 {fmt(-b)})'
                    ' (stroke (width 0.254) (type default)) (fill (type background))']
        return []

    def sexpr(self):
        s = []
        s.append(f'    (symbol "hakai:{self.name}"')
        s.append('      (pin_numbers hide) (pin_names (offset 0.254) hide)')
        s.append('      (exclude_from_sim no) (in_bom yes) (on_board yes)')
        s.append(f'      (property "Reference" "{self.ref}" (at 2.54 1.27 0) {F})')
        s.append(f'      (property "Value" "{self.name}" (at 2.54 -1.27 0) {F})')
        s.append(f'      (property "Footprint" "" (at 0 0 0) {FH})')
        s.append(f'      (property "Datasheet" "" (at 0 0 0) {FH})')
        s.append(f'      (property "Description" "{self.desc}" (at 0 0 0) {FH})')
        s.append(f'      (symbol "{self.name}_0_1"')
        body = self._body_sexpr()
        # fb body needs closing paren fix
        if self.body == "fb":
            body = [f'        (rectangle (start -1.016 {fmt(self.ext - self.pin_len)}) (end 1.016 {fmt(-(self.ext - self.pin_len))})'
                    ' (stroke (width 0.254) (type default)) (fill (type none)))']
        s.extend(body)
        s.append('      )')
        s.append(f'      (symbol "{self.name}_1_1"')
        for num, name, ext, ang in (("1", self.p1name, self.ext, 270),
                                    ("2", self.p2name, -self.ext, 90)):
            s.append(f'        (pin passive line (at 0 {fmt(ext)} {ang}) (length {fmt(self.pin_len)})')
            s.append(f'          (name "{name}" {F})')
            s.append(f'          (number "{num}" {F})')
            s.append('        )')
        s.append('      )')
        s.append('    )')
        return "\n".join(s)


def power_symbol_lib(name, style):
    """style: 'rail' (arrow above), 'gnd' (triangle below), 'flag' (PWR_FLAG)."""
    s = []
    s.append(f'    (symbol "hakai:{name}"')
    s.append('      (power) (pin_names (offset 0)) (exclude_from_sim no) (in_bom yes) (on_board yes)')
    ref_y = -6.35 if style == "gnd" else -3.81
    val_y = -3.81 if style == "gnd" else 3.556
    s.append(f'      (property "Reference" "#PWR" (at 0 {fmt(ref_y)} 0) {FH})')
    s.append(f'      (property "Value" "{name}" (at 0 {fmt(val_y)} 0) {F})')
    s.append(f'      (property "Footprint" "" (at 0 0 0) {FH})')
    s.append(f'      (property "Datasheet" "" (at 0 0 0) {FH})')
    s.append(f'      (property "Description" "power symbol: net {name}" (at 0 0 0) {FH})')
    st = '(stroke (width 0) (type default)) (fill (type none))'
    s.append(f'      (symbol "{name}_0_1"')
    if style == "gnd":
        s.append(f'        (polyline (pts (xy 0 0) (xy 0 -1.27) (xy 1.27 -1.27) (xy 0 -2.54) (xy -1.27 -1.27) (xy 0 -1.27)) {st})')
    elif style == "flag":
        s.append(f'        (polyline (pts (xy 0 0) (xy 0 1.27) (xy -1.016 1.905) (xy 0 2.54) (xy 1.016 1.905) (xy 0 1.27)) {st})')
    else:
        s.append(f'        (polyline (pts (xy -0.762 1.27) (xy 0 2.54)) {st})')
        s.append(f'        (polyline (pts (xy 0 0) (xy 0 2.54)) {st})')
        s.append(f'        (polyline (pts (xy 0 2.54) (xy 0.762 1.27)) {st})')
    s.append('      )')
    ptype = "power_out" if style == "flag" else "power_in"
    ang = 270 if style == "gnd" else 90
    s.append(f'      (symbol "{name}_1_1"')
    s.append(f'        (pin {ptype} line (at 0 0 {ang}) (length 0) hide')
    s.append(f'          (name "{name}" {F})')
    s.append(f'          (number "1" {F})')
    s.append('        )')
    s.append('      )')
    s.append('    )')
    return "\n".join(s)


# --------------------------------------------------------------------------
# Sheet
# --------------------------------------------------------------------------

class Sheet:
    def __init__(self):
        self.lib = {}
        self.raw_lib = []
        self.items = []
        self.pwr_count = 0
        self.label_nets = {}

    def register(self, libobj):
        self.lib[libobj.name] = libobj

    def register_power(self, name, style):
        self.raw_lib.append(power_symbol_lib(name, style))

    def _instances(self, ref):
        return (f'    (instances (project "{PROJECT}"\n'
                f'      (path "/{ROOT_UUID}" (reference "{ref}") (unit 1))\n'
                '    ))')

    def place(self, libname, ref, value, x, y, dnp=False, footprint=""):
        lp = self.lib[libname]
        x, y = snap(x), snap(y)
        s = []
        s.append(f'  (symbol (lib_id "hakai:{libname}") (at {fmt(x)} {fmt(y)} 0) (unit 1)')
        s.append(f'    (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp {"yes" if dnp else "no"})')
        s.append('    (fields_autoplaced yes)')
        s.append(f'    (uuid "{u()}")')
        if isinstance(lp, LibPart):
            h2, _ = lp._geom()
            ref_y, val_y, rx, just = y - h2 - 2.54, y + h2 + 2.54, x, ''
        else:
            ref_y, val_y, rx, just = y - 1.27, y + 1.27, x + 2.54, ' (justify left)'
        s.append(f'    (property "Reference" "{ref}" (at {fmt(rx)} {fmt(ref_y)} 0) (effects (font (size 1.27 1.27)){just}))')
        s.append(f'    (property "Value" "{value}" (at {fmt(rx)} {fmt(val_y)} 0) (effects (font (size 1.27 1.27)){just}))')
        s.append(f'    (property "Footprint" "{footprint}" (at {fmt(x)} {fmt(y)} 0) {FH})')
        s.append(f'    (property "Datasheet" "" (at {fmt(x)} {fmt(y)} 0) {FH})')
        s.append(f'    (property "Description" "" (at {fmt(x)} {fmt(y)} 0) {FH})')
        pinmap = {}
        numbers = [p.number for p in lp.pins] if isinstance(lp, LibPart) else ["1", "2"]
        for n in numbers:
            px, py, side = lp.pin_local(n)
            pinmap[n] = (snap(x + px), snap(y - py), side)
            s.append(f'    (pin "{n}" (uuid "{u()}"))')
        s.append(self._instances(ref))
        s.append('  )')
        self.items.append("\n".join(s))
        return pinmap

    def power(self, name, x, y):
        x, y = snap(x), snap(y)
        self.pwr_count += 1
        ref = f"#PWR{self.pwr_count:04d}"
        off = -3.81 if name == "GND" else 3.81
        s = []
        s.append(f'  (symbol (lib_id "hakai:{name}") (at {fmt(x)} {fmt(y)} 0) (unit 1)')
        s.append('    (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)')
        s.append('    (fields_autoplaced yes)')
        s.append(f'    (uuid "{u()}")')
        s.append(f'    (property "Reference" "{ref}" (at {fmt(x)} {fmt(y - off - 2.54)} 0) {FH})')
        s.append(f'    (property "Value" "{name}" (at {fmt(x)} {fmt(y - off)} 0) {F})')
        s.append(f'    (property "Footprint" "" (at {fmt(x)} {fmt(y)} 0) {FH})')
        s.append(f'    (property "Datasheet" "" (at {fmt(x)} {fmt(y)} 0) {FH})')
        s.append(f'    (property "Description" "" (at {fmt(x)} {fmt(y)} 0) {FH})')
        s.append(f'    (pin "1" (uuid "{u()}"))')
        s.append(self._instances(ref))
        s.append('  )')
        self.items.append("\n".join(s))
        self.label_nets[name] = self.label_nets.get(name, 0) + 2  # power nets always ok

    def label(self, net, x, y, side):
        x, y = snap(x), snap(y)
        ang = 180 if side in ('L', 'B') else 0
        just = 'right' if ang == 180 else 'left'
        s = []
        s.append(f'  (global_label "{net}" (shape bidirectional) (at {fmt(x)} {fmt(y)} {ang})')
        s.append(f'    (effects (font (size 1.27 1.27)) (justify {just}))')
        s.append(f'    (uuid "{u()}")')
        s.append(f'    (property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at {fmt(x)} {fmt(y)} 0) {FH})')
        s.append('  )')
        self.items.append("\n".join(s))
        self.label_nets[net] = self.label_nets.get(net, 0) + 1

    def nc(self, x, y):
        self.items.append(f'  (no_connect (at {fmt(snap(x))} {fmt(snap(y))}) (uuid "{u()}"))')

    def text(self, txt, x, y, size=1.27):
        t = txt.replace('"', "'")
        self.items.append(
            f'  (text "{t}" (exclude_from_sim no) (at {fmt(snap(x))} {fmt(snap(y))} 0)\n'
            f'    (effects (font (size {size} {size})) (justify left))\n'
            f'    (uuid "{u()}")\n  )')

    def connect(self, pinmap, conns):
        listed = set(str(k) for k in conns)
        for n, spec in conns.items():
            ax, ay, side = pinmap[str(n)]
            if spec[0] == 'label':
                self.label(spec[1], ax, ay, side)
            elif spec[0] == 'power':
                self.power(spec[1], ax, ay)
            elif spec[0] == 'nc':
                self.nc(ax, ay)
        for n, (ax, ay, side) in pinmap.items():
            if n not in listed:
                self.nc(ax, ay)

    def check(self):
        bad = [k for k, v in self.label_nets.items() if v < 2]
        if bad:
            raise SystemExit(f"SINGLE-ENDED NETS (label appears once): {bad}")

    def emit(self, title):
        s = []
        s.append('(kicad_sch (version 20231120) (generator "eeschema") (generator_version "8.0")')
        s.append(f'  (uuid "{ROOT_UUID}")')
        s.append('  (paper "A3")')
        s.append('  (title_block')
        s.append(f'    (title "{title}")')
        s.append('    (date "2026-07-05")')
        s.append('    (rev "5.0")')
        s.append('    (company "HAKAI Engineering")')
        s.append('    (comment 1 "Values verified: Nordic PS v1.7 + PCA10100 DK 2.0.0, TI SLUS810N, Torex, GCT")')
        s.append('    (comment 2 "PAW3311 wiring VERIFIED against PixArt datasheet v1.0 1A009EN (15 Nov 2022)")')
        s.append('  )')
        s.append('  (lib_symbols')
        for lp in self.lib.values():
            s.append(lp.sexpr())
        s.extend(self.raw_lib)
        s.append('  )')
        s.extend(self.items)
        s.append('  (sheet_instances (path "/" (page "1")))')
        s.append(')')
        return "\n".join(s) + "\n"


# ==========================================================================
# Library definitions (verified pinouts)
# ==========================================================================

def make_libs(sh):
    # nRF52833-QIAA -- all 73 balls + die pad (PS v1.7 Table 62)
    nrf = LibPart("nRF52833-QIAA", "U", 20.32,
                  "Nordic nRF52833 BLE/2.4GHz SoC, aQFN73")
    L = [  # (ball, name, etype)
        ("A22", "VDD", "power_in"), ("B1", "VDD", "power_in"),
        ("W1", "VDD", "power_in"), ("AD14", "VDD", "power_in"),
        ("AD23", "VDD", "power_in"), ("Y2", "VDDH", "power_in"),
        ("C1", "DEC1", "passive"), ("D23", "DEC3", "passive"),
        ("B5", "DEC4", "passive"), ("N24", "DEC5", "passive"),
        ("E24", "DEC6", "passive"), ("B3", "DCC", "passive"),
        ("AD2", "VBUS", "passive"), ("AD4", "D-", "passive"),
        ("AD6", "D+", "passive"), ("AC5", "DECUSB", "passive"),
        ("B24", "XC1", "passive"), ("A23", "XC2", "passive"),
        ("D2", "P0.00/XL1", "passive"), ("F2", "P0.01/XL2", "passive"),
        ("H23", "ANT", "passive"),
        ("AC24", "SWDIO", "passive"), ("AA24", "SWDCLK", "passive"),
        ("AC13", "P0.18/nRESET", "passive"),
        ("B7", "VSS", "power_in"), ("F23", "VSS_PA", "power_in"),
        ("74", "VSS(PAD)", "power_in"),
        ("A18", "N.C.", "passive"), ("B19", "N.C.", "passive"),
        ("T23", "N.C.", "passive"), ("V23", "N.C.", "passive"),
        ("AB2", "N.C.", "passive"), ("AC15", "N.C.", "passive"),
        ("AC19", "N.C.", "passive"), ("AC21", "N.C.", "passive"),
    ]
    for i, (num, nm, et) in enumerate(L):
        nrf.pin(num, nm, 'L', i, et)
    R = [
        ("A12", "P0.02/AIN0"), ("B13", "P0.03/AIN1"), ("J1", "P0.04/AIN2"),
        ("K2", "P0.05/AIN3"), ("L1", "P0.06"), ("M2", "P0.07"),
        ("N1", "P0.08"), ("L24", "P0.09/NFC1"), ("J24", "P0.10/NFC2"),
        ("T2", "P0.11"), ("U1", "P0.12"), ("AD8", "P0.13"),
        ("AC9", "P0.14"), ("AD10", "P0.15"), ("AC11", "P0.16"),
        ("AD12", "P0.17"), ("A14", "P0.19"), ("AD16", "P0.20"),
        ("AC17", "P0.21"), ("AD18", "P0.22"), ("B17", "P0.23"),
        ("AD20", "P0.24"), ("A20", "P0.25"), ("G1", "P0.26"),
        ("H2", "P0.27"), ("B11", "P0.28/AIN4"), ("A10", "P0.29/AIN5"),
        ("B9", "P0.30/AIN6"), ("A8", "P0.31/AIN7"), ("AD22", "P1.00"),
        ("Y23", "P1.01"), ("W24", "P1.02"), ("B15", "P1.03"),
        ("U24", "P1.04"), ("A16", "P1.05"), ("R24", "P1.06"),
        ("P23", "P1.07"), ("P2", "P1.08"), ("R1", "P1.09"),
    ]
    for i, (num, nm) in enumerate(R):
        nrf.pin(num, nm, 'R', i, "passive")
    sh.register(nrf)

    # PAW3311DB -- VERIFIED per PixArt datasheet v1.0 Table 1
    paw = LibPart("PAW3311DB-T2MU", "U", 13.97,
                  "PixArt low-power optical gaming sensor, 8-pin DB, VDD 1.8-2.1V, 3-wire SPI (datasheet 1A009EN v1.0)")
    paw.pin("3", "VDD", 'L', 0, "power_in")
    paw.pin("2", "VDDREG", 'L', 1)
    paw.pin("1", "LED", 'L', 2)
    paw.pin("6", "GND", 'L', 3, "power_in")
    paw.pin("8", "NCS", 'R', 0)
    paw.pin("4", "SCLK", 'R', 1)
    paw.pin("7", "SDIO", 'R', 2)
    paw.pin("5", "MOTION", 'R', 3)
    sh.register(paw)

    # BQ24074 (TI SLUS810N, VQFN-16 RGT)
    bq = LibPart("BQ24074", "U", 12.7, "TI Li-ion charger + power path, VQFN-16")
    for i, (num, nm) in enumerate([("13", "IN"), ("5", "EN2"), ("6", "EN1"),
                                   ("4", "/CE"), ("1", "TS"), ("12", "ILIM"),
                                   ("16", "ISET"), ("14", "TMR"), ("15", "ITERM")]):
        bq.pin(num, nm, 'L', i)
    for i, (num, nm) in enumerate([("10", "OUT"), ("11", "OUT"), ("2", "BAT"),
                                   ("3", "BAT"), ("9", "/CHG"), ("7", "/PGOOD"),
                                   ("8", "VSS"), ("17", "PAD")]):
        bq.pin(num, nm, 'R', i)
    sh.register(bq)

    # XC6219B192MR (Torex, SOT-25, 1.9V). CE active-HIGH, no internal pull.
    ldo = LibPart("XC6219B192MR", "U", 11.43, "Torex 1.9V 240mA LDO, SOT-25 (system rail: PAW3311 abs max 2.1V)")
    ldo.pin("1", "VIN", 'L', 0)
    ldo.pin("3", "CE", 'L', 1)
    ldo.pin("2", "VSS", 'L', 2, "power_in")
    ldo.pin("5", "VOUT", 'R', 0)
    ldo.pin("4", "NC", 'R', 1)
    sh.register(ldo)

    # USB-C 16-pin (GCT USB4105-GF-A)
    usb = LibPart("USB4105-GF-A", "J", 11.43, "USB-C receptacle 16-pin, charge-only use")
    rows = [("A1", "GND"), ("A4", "VBUS"), ("A9", "VBUS"), ("B4", "VBUS"),
            ("B9", "VBUS"), ("A5", "CC1"), ("B5", "CC2"), ("A6", "D+1"),
            ("A7", "D-1"), ("B6", "D+2"), ("B7", "D-2"), ("A8", "SBU1"),
            ("B8", "SBU2"), ("B1", "GND"), ("A12", "GND"), ("B12", "GND"),
            ("S1", "SHIELD")]
    for i, (num, nm) in enumerate(rows):
        usb.pin(num, nm, 'R', i)
    sh.register(usb)

    # Kailh GM 8.0 (D2FC form factor: COM/NO/NC)
    sw = LibPart("SW_Kailh_GM8", "SW", 8.89, "Kailh GM 8.0 mouse microswitch, SPDT")
    sw.pin("1", "COM", 'L', 0)
    sw.pin("2", "NO", 'R', 0)
    sw.pin("3", "NC", 'R', 1)
    sh.register(sw)

    # 11mm mouse scroll encoder, ROTATION ONLY (split-wheel arrangement:
    # the middle click is a separate tact switch SW5 on the other bay wall)
    enc = LibPart("ENC_MOUSE_11MM", "EC", 10.16,
                  "11mm mouse scroll encoder, rotation only; D-socket accepts the wheel axle")
    enc.pin("A", "A", 'L', 0)
    enc.pin("C", "C(COM)", 'L', 1)
    enc.pin("B", "B", 'L', 2)
    sh.register(enc)

    # AO3400A SOT-23 (1=G 2=S 3=D) -- low Vth, fully enhanced at 1.9V gate
    fet = LibPart("AO3400A", "Q", 7.62, "N-MOSFET SOT-23: 1=G 2=S 3=D. Low-Vth (2N7002 marginal at 1.9V gate)")
    fet.pin("1", "G", 'L', 0)
    fet.pin("3", "D", 'R', 0)
    fet.pin("2", "S", 'R', 1)
    sh.register(fet)

    # Battery connector JST PH 2-pin
    bat = LibPart("CONN_BATT_PH2", "J", 10.16, "JST PH 2-pin battery. NO JST polarity standard - verify pack!")
    bat.pin("1", "BAT+", 'R', 0)
    bat.pin("2", "BAT-", 'R', 1)
    sh.register(bat)

    # SWD header 1x05
    swd = LibPart("CONN_SWD_05", "J", 10.16, "SWD debug header 1x05 (1.9V logic - set probe VTref accordingly)")
    for i, nm in enumerate(["1V9", "SWDIO", "SWDCLK", "nRESET", "GND"]):
        swd.pin(str(i + 1), nm, 'R', i)
    sh.register(swd)

    # PCB antenna (1 pin)
    ant = LibPart("ANT_PCB_2G4", "ANT", 7.62, "2.4GHz PCB/chip antenna, 50R feed")
    ant.pin("1", "FEED", 'L', 0)
    sh.register(ant)

    # Test point
    tp = LibPart("TP", "TP", 2.54, "Test point")
    tp.pin("1", "TP", 'L', 0)
    sh.register(tp)

    # Passives
    sh.register(LibPassive("R", "R", "Resistor", "rect"))
    sh.register(LibPassive("C", "C", "Capacitor", "cap"))
    sh.register(LibPassive("L", "L", "Inductor", "ind"))
    sh.register(LibPassive("LED", "D", "LED (1=A top, 2=K bottom)", "led"))
    sh.register(LibPassive("D_TVS", "D", "Bidirectional TVS", "tvs"))
    sh.register(LibPassive("XTAL", "Y", "Crystal", "xtal"))
    sh.register(LibPassive("FUSE_PTC", "F", "PTC resettable fuse", "fuse"))
    sh.register(LibPassive("SW_TACT", "SW", "Tact switch (wheel middle click)", "switch"))
    sh.register(LibPassive("FERRITE", "FB", "Ferrite bead", "fb"))

    # Power symbols
    for name in ("VBUS", "VBAT", "VSYS", "1V9", "1V9_A"):
        sh.register_power(name, "rail")
    sh.register_power("GND", "gnd")
    sh.register_power("PWR_FLAG", "flag")


# ==========================================================================
# Placement + netlist
# ==========================================================================

R_FP = "Resistor_SMD:R_0402_1005Metric"
C_FP = "Capacitor_SMD:C_0402_1005Metric"
C_FP6 = "Capacitor_SMD:C_0603_1608Metric"


def build():
    sh = Sheet()
    make_libs(sh)
    P, LBL, NC = 'power', 'label', 'nc'

    # ---- titles / notes -------------------------------------------------
    sh.text("HAKAI WIRELESS GAMING MOUSE - REV 2.0", 20.32, 15.24, 3.81)
    sh.text("nRF52833 (integrated 2.4GHz radio) + PAW3311 + BQ24074 + 4x Kailh + scroll encoder | SINGLE 1.9V SYSTEM RAIL", 20.32, 21.59, 1.778)
    sh.text("SYSTEM RAIL = 1.9V: PAW3311 VDD abs max 2.1V -> MCU + sensor share 1V9", 120.65, 103.19)
    sh.text("(nRF52833 runs 1.7-3.6V, no level shift). Status LED from VSYS via Q2.", 120.65, 106.99)
    sh.text("USB-C: CHARGE-ONLY. D+/D-/SBU float; CC1/CC2 separate 5.1k pulldowns. nRF USB pins unconnected per Nordic no-USB reference (config 6).", 20.32, 96.52)
    sh.text("BQ24074: EN2=VSYS, EN1=GND -> input limit ILIM = 1610/3.24k = 497mA. ISET 2.0k -> ICHG = 445mA.", 20.32, 178.5)
    sh.text("TS = 10k fixed to GND (always-valid). For pack temp sensing fit 10k NTC (103AT) instead. TMR/ITERM float = default timers / 10% term.", 20.32, 182.5)
    sh.text("JST PH HAS NO POLARITY STANDARD - verify battery pigtail with a DMM.", 20.32, 249.86)
    sh.text("Pin1 = BAT+ is THIS design's convention. Use a PROTECTED cell (or add DW01A+8205A).", 20.32, 253.67)
    sh.text("nRF52833 notes: DEC3 = 100pF NP0 (NOT 100nF). DEC4+DEC6 tied = DEC4_6 net. DEC5 N.C. on build codes Bxx+ (spec QIAAB0+).", 148.59, 110.49)
    sh.text("DC/DC REG1: DCC -> 10uH + 15nH -> DEC4_6 (halves radio current vs LDO mode). nRESET = P0.18 via UICR PSELRESET.", 148.59, 114.49)
    sh.text("RF match per Nordic PS/PCA10100 (VERBATIM): shunt 1.0pF -> series 4.7nH ->", 292.1, 105.41)
    sh.text("shunt 1.2pF -> series 2.2nH -> 50R feed. COPY the reference LAYOUT geometry.", 292.1, 109.22)
    sh.text("C24 = antenna-dependent tune (DNP, set with VNA). Keep-out under antenna.", 292.1, 113.03)
    sh.text("U5 PAW3311DB - VERIFIED per PixArt datasheet v1.0 (1A009EN):", 303.53, 158.75)
    sh.text("VDD 1.8-2.1V, ABS MAX 2.1V. 3-wire SPI: MCU MISO -> SDIO direct;", 303.53, 162.56)
    sh.text("MCU MOSI -> R23 -> SDIO. R23: 3.3k@2MHz / 1k@4MHz / 240R@8MHz.", 303.53, 166.37)
    sh.text("MOTION = push-pull active-low (R14 optional). VDDREG = bypass only.", 303.53, 170.18)
    sh.text("LED: 1V9_A -> 18R 1% -> IR LED -> pin1 (24mA internal control).", 303.53, 173.99)
    sh.text("Lens: LM31-LNG/LM33-LSG/L0AL-LSG1 (5mm IR) or L0AJ-LSG1 (SMT IR). Z = 2.2-2.6mm.", 302.26, 224.79)
    sh.text("Kailh GM 8.0: COM->GND, NO->MCU (active-low). Debounce caps DNP - firmware debounces.", 121.92, 256.54)
    sh.text("PWR_FLAG tie points", 25.4, 267.97)

    # ---- USB-C + CC + TVS ----------------------------------------------
    j1 = sh.place("USB4105-GF-A", "J1", "USB4105-GF-A", 38.1, 63.5,
                  footprint="Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12")
    sh.connect(j1, {
        "A1": (P, "GND"), "B1": (LBL, "GND"), "A12": (LBL, "GND"), "B12": (LBL, "GND"),
        "S1": (P, "GND"),
        "A4": (P, "VBUS"), "A9": (LBL, "VBUS"), "B4": (LBL, "VBUS"), "B9": (LBL, "VBUS"),
        "A5": (LBL, "CC1"), "B5": (LBL, "CC2"),
        "A6": (NC,), "A7": (NC,), "B6": (NC,), "B7": (NC,), "A8": (NC,), "B8": (NC,),
    })
    d1 = sh.place("D_TVS", "D1", "PESD5V0S1BA", 63.5, 38.1,
                  footprint="Diode_SMD:D_SOD-323")
    sh.connect(d1, {"1": (P, "VBUS"), "2": (P, "GND")})
    r1 = sh.place("R", "R1", "5.1k", 78.74, 63.5, footprint=R_FP)
    sh.connect(r1, {"1": (LBL, "CC1"), "2": (P, "GND")})
    r2 = sh.place("R", "R2", "5.1k", 91.44, 63.5, footprint=R_FP)
    sh.connect(r2, {"1": (LBL, "CC2"), "2": (P, "GND")})

    # ---- Charger --------------------------------------------------------
    u2 = sh.place("BQ24074", "U2", "BQ24074", 50.8, 137.16,
                  footprint="Package_DFN_QFN:VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm_ThermalVias")
    sh.connect(u2, {
        "13": (P, "VBUS"), "5": (P, "VSYS"), "6": (P, "GND"), "4": (P, "GND"),
        "1": (LBL, "TS"), "12": (LBL, "ILIM"), "16": (LBL, "ISET"),
        "14": (NC,), "15": (NC,),
        "10": (P, "VSYS"), "11": (LBL, "VSYS"), "2": (P, "VBAT"), "3": (LBL, "VBAT"),
        "9": (LBL, "STAT"), "7": (LBL, "PGOOD"), "8": (P, "GND"), "17": (LBL, "GND"),
    })
    for ref, val, x, net in (("R3", "10k", 27.94, "TS"), ("R4", "3.24k", 40.64, "ILIM"),
                             ("R5", "2.0k", 53.34, "ISET")):
        pm = sh.place("R", ref, val, x, 165.1, footprint=R_FP)
        sh.connect(pm, {"1": (LBL, net), "2": (P, "GND")})
    for ref, val, x, net in (("R6", "100k", 109.22, "STAT"), ("R7", "100k", 121.92, "PGOOD")):
        pm = sh.place("R", ref, val, x, 165.1, footprint=R_FP)
        sh.connect(pm, {"1": (P, "1V9_A"), "2": (LBL, net)})
    c1 = sh.place("C", "C1", "1uF", 78.74, 111.76, footprint=C_FP)
    sh.connect(c1, {"1": (P, "VBUS"), "2": (P, "GND")})
    c2 = sh.place("C", "C2", "10uF", 91.44, 111.76, footprint=C_FP6)
    sh.connect(c2, {"1": (LBL, "VBUS"), "2": (P, "GND")})
    c3 = sh.place("C", "C3", "10uF", 104.14, 111.76, footprint=C_FP6)
    sh.connect(c3, {"1": (P, "VSYS"), "2": (P, "GND")})

    # ---- Battery + fuel gauge -------------------------------------------
    j2 = sh.place("CONN_BATT_PH2", "J2", "JST S2B-PH-K", 38.1, 205.74,
                  footprint="Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Horizontal")
    sh.connect(j2, {"1": (P, "VBAT"), "2": (P, "GND")})
    r8 = sh.place("R", "R8", "200k", 63.5, 205.74, footprint=R_FP)
    sh.connect(r8, {"1": (P, "VBAT"), "2": (LBL, "VBAT_SENSE")})
    r9 = sh.place("R", "R9", "100k", 63.5, 226.06, footprint=R_FP)
    sh.connect(r9, {"1": (LBL, "VBAT_SENSE"), "2": (LBL, "VBAT_DIV_LO")})
    q1 = sh.place("AO3400A", "Q1", "AO3400A", 88.9, 231.14,
                  footprint="Package_TO_SOT_SMD:SOT-23")
    sh.connect(q1, {"1": (LBL, "VBAT_EN"), "3": (LBL, "VBAT_DIV_LO"), "2": (P, "GND")})
    r10 = sh.place("R", "R10", "100k", 109.22, 231.14, footprint=R_FP)
    sh.connect(r10, {"1": (LBL, "VBAT_EN"), "2": (P, "GND")})

    # ---- LDO + rails -----------------------------------------------------
    f1 = sh.place("FUSE_PTC", "F1", "PTC 1A", 134.62, 38.1,
                  footprint="Fuse:Fuse_1206_3216Metric")
    sh.connect(f1, {"1": (P, "VSYS"), "2": (LBL, "LDO_IN")})
    u3 = sh.place("XC6219B192MR", "U3", "XC6219B192MR", 160.02, 53.34,
                  footprint="Package_TO_SOT_SMD:SOT-23-5")
    sh.connect(u3, {"1": (LBL, "LDO_IN"), "3": (LBL, "LDO_IN"), "2": (P, "GND"),
                    "5": (P, "1V9"), "4": (NC,)})
    c4 = sh.place("C", "C4", "1uF", 134.62, 83.82, footprint=C_FP)
    sh.connect(c4, {"1": (LBL, "LDO_IN"), "2": (P, "GND")})
    c5 = sh.place("C", "C5", "1uF", 147.32, 83.82, footprint=C_FP)
    sh.connect(c5, {"1": (P, "1V9"), "2": (P, "GND")})
    c6 = sh.place("C", "C6", "10uF", 160.02, 83.82, footprint=C_FP6)
    sh.connect(c6, {"1": (LBL, "1V9"), "2": (P, "GND")})
    fb1 = sh.place("FERRITE", "FB1", "600R@100MHz", 185.42, 38.1,
                   footprint="Inductor_SMD:L_1206_3216Metric")
    sh.connect(fb1, {"1": (P, "1V9"), "2": (P, "1V9_A")})
    c7 = sh.place("C", "C7", "100nF", 185.42, 83.82, footprint=C_FP)
    sh.connect(c7, {"1": (P, "1V9_A"), "2": (P, "GND")})
    c8 = sh.place("C", "C8", "10uF", 198.12, 83.82, footprint=C_FP6)
    sh.connect(c8, {"1": (LBL, "1V9_A"), "2": (P, "GND")})

    # ---- PWR_FLAG tie points --------------------------------------------
    for i, rail in enumerate(("GND", "VBUS", "VBAT", "VSYS", "1V9", "1V9_A")):
        x = 25.4 + i * 12.7
        sh.power(rail, x, 279.4)
        # PWR_FLAG placed on the exact same point -> drives the net for ERC
        pfref_x = x
        sh.pwr_count += 1
        ref = f"#FLG{sh.pwr_count:04d}"
        sh.items.append("\n".join([
            f'  (symbol (lib_id "hakai:PWR_FLAG") (at {fmt(snap(pfref_x))} {fmt(snap(279.4))} 0) (unit 1)',
            '    (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)',
            '    (fields_autoplaced yes)',
            f'    (uuid "{u()}")',
            f'    (property "Reference" "{ref}" (at {fmt(snap(pfref_x))} {fmt(snap(279.4) - 5.08)} 0) {FH})',
            f'    (property "Value" "PWR_FLAG" (at {fmt(snap(pfref_x))} {fmt(snap(279.4) - 3.81)} 0) {FH})',
            f'    (property "Footprint" "" (at {fmt(snap(pfref_x))} {fmt(snap(279.4))} 0) {FH})',
            f'    (property "Datasheet" "" (at {fmt(snap(pfref_x))} {fmt(snap(279.4))} 0) {FH})',
            f'    (property "Description" "" (at {fmt(snap(pfref_x))} {fmt(snap(279.4))} 0) {FH})',
            f'    (pin "1" (uuid "{u()}"))',
            sh._instances(ref),
            '  )']))

    # ---- MCU -------------------------------------------------------------
    u4 = sh.place("nRF52833-QIAA", "U4", "nRF52833-QIAA (Bxx+)", 256.54, 172.72,
                  footprint="Package_DFN_QFN:Nordic_AQFN-73-1EP_7x7mm_P0.5mm")
    sh.connect(u4, {
        "A22": (P, "1V9_A"), "B1": (LBL, "1V9_A"), "W1": (LBL, "1V9_A"),
        "AD14": (LBL, "1V9_A"), "AD23": (LBL, "1V9_A"), "Y2": (LBL, "1V9_A"),
        "C1": (LBL, "DEC1"), "D23": (LBL, "DEC3"), "B5": (LBL, "DEC4_6"),
        "N24": (NC,), "E24": (LBL, "DEC4_6"), "B3": (LBL, "DCC"),
        "AD2": (NC,), "AD4": (NC,), "AD6": (NC,), "AC5": (NC,),
        "B24": (LBL, "XC1"), "A23": (LBL, "XC2"),
        "D2": (LBL, "XL1"), "F2": (LBL, "XL2"),
        "H23": (LBL, "ANT"),
        "AC24": (LBL, "SWDIO"), "AA24": (LBL, "SWDCLK"), "AC13": (LBL, "nRESET"),
        "B7": (P, "GND"), "F23": (LBL, "GND"), "74": (LBL, "GND"),
        "A18": (NC,), "B19": (NC,), "T23": (NC,), "V23": (NC,),
        "AB2": (NC,), "AC15": (NC,), "AC19": (NC,), "AC21": (NC,),
        # right side GPIO
        "A12": (LBL, "VBAT_SENSE"), "B13": (LBL, "VBAT_EN"),
        "J1": (LBL, "BTN_LEFT"), "K2": (LBL, "BTN_RIGHT"),
        "L1": (LBL, "BTN_SIDE_BACK"), "M2": (LBL, "BTN_SIDE_FWD"),
        "N1": (LBL, "ENC_A"), "T2": (LBL, "ENC_B"), "U1": (LBL, "ENC_SW"),
        "AD8": (LBL, "LED_STAT"), "AC9": (LBL, "STAT"), "AD10": (LBL, "PGOOD"),
        "AD12": (LBL, "SENS_NCS"), "A14": (LBL, "SENS_MOTION"),
        "AD16": (LBL, "SPI_SCK"), "AD18": (LBL, "SPI_MOSI"), "AD20": (LBL, "SENS_SDIO"),
        # unused GPIO -> nc (auto via connect() default is only for unlisted;
        # list them explicitly for clarity)
        "L24": (NC,), "J24": (NC,), "AC11": (NC,), "AC17": (NC,), "B17": (NC,),
        "A20": (NC,), "G1": (NC,), "H2": (NC,), "B11": (NC,), "A10": (NC,),
        "B9": (NC,), "A8": (NC,), "AD22": (NC,), "Y23": (NC,), "W24": (NC,),
        "B15": (NC,), "U24": (NC,), "A16": (NC,), "R24": (NC,), "P23": (NC,),
        "P2": (NC,), "R1": (NC,),
    })

    # VDD decoupling row (per Nordic ref: 4.7u bulk + 1u + 3x 100n)
    for ref, val, x, fp in (("C13", "4.7uF", 218.44, C_FP6), ("C14", "1uF", 231.14, C_FP),
                            ("C15", "100nF", 243.84, C_FP), ("C16", "100nF", 256.54, C_FP),
                            ("C17", "100nF", 269.24, C_FP)):
        pm = sh.place("C", ref, val, x, 99.06, footprint=fp)
        sh.connect(pm, {"1": (P, "1V9_A"), "2": (P, "GND")})

    # DEC + DC/DC chain
    c9 = sh.place("C", "C9", "100nF", 203.2, 127.0, footprint=C_FP)
    sh.connect(c9, {"1": (LBL, "DEC1"), "2": (P, "GND")})
    c10 = sh.place("C", "C10", "100pF NP0", 203.2, 149.86, footprint=C_FP)
    sh.connect(c10, {"1": (LBL, "DEC3"), "2": (P, "GND")})
    c11 = sh.place("C", "C11", "1uF", 190.5, 172.72, footprint=C_FP6)
    sh.connect(c11, {"1": (LBL, "DEC4_6"), "2": (P, "GND")})
    c12 = sh.place("C", "C12", "47nF", 203.2, 172.72, footprint=C_FP)
    sh.connect(c12, {"1": (LBL, "DEC4_6"), "2": (P, "GND")})
    l1 = sh.place("L", "L1", "10uH", 190.5, 198.12,
                  footprint="Inductor_SMD:L_0603_1608Metric")
    sh.connect(l1, {"1": (LBL, "DCC"), "2": (LBL, "DCC_L")})
    l2 = sh.place("L", "L2", "15nH", 203.2, 198.12,
                  footprint="Inductor_SMD:L_0402_1005Metric")
    sh.connect(l2, {"1": (LBL, "DCC_L"), "2": (LBL, "DEC4_6")})

    # Crystals (clear zone below the charger, left of the DEC column)
    y1 = sh.place("XTAL", "Y1", "32MHz CL=8pF", 134.62, 198.12,
                  footprint="Crystal:Crystal_SMD_2016-4Pin_2.0x1.6mm")
    sh.connect(y1, {"1": (LBL, "XC1"), "2": (LBL, "XC2")})
    c18 = sh.place("C", "C18", "12pF NP0", 156.21, 198.12, footprint=C_FP)
    sh.connect(c18, {"1": (LBL, "XC1"), "2": (P, "GND")})
    c19 = sh.place("C", "C19", "12pF NP0", 168.91, 198.12, footprint=C_FP)
    sh.connect(c19, {"1": (LBL, "XC2"), "2": (P, "GND")})
    y2 = sh.place("XTAL", "Y2", "32.768kHz CL=9pF", 134.62, 220.98,
                  footprint="Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm")
    sh.connect(y2, {"1": (LBL, "XL1"), "2": (LBL, "XL2")})
    c20 = sh.place("C", "C20", "12pF NP0", 156.21, 220.98, footprint=C_FP)
    sh.connect(c20, {"1": (LBL, "XL1"), "2": (P, "GND")})
    c21 = sh.place("C", "C21", "12pF NP0", 168.91, 220.98, footprint=C_FP)
    sh.connect(c21, {"1": (LBL, "XL2"), "2": (P, "GND")})

    # nRESET pull-up
    r11 = sh.place("R", "R11", "10k", 177.8, 246.38, footprint=R_FP)
    sh.connect(r11, {"1": (P, "1V9_A"), "2": (LBL, "nRESET")})

    # ---- RF chain (Nordic PCA10100 verbatim) -----------------------------
    c22 = sh.place("C", "C22", "1.0pF NP0", 307.34, 127.0, footprint=C_FP)
    sh.connect(c22, {"1": (LBL, "ANT"), "2": (P, "GND")})
    l3 = sh.place("L", "L3", "4.7nH", 320.04, 127.0,
                  footprint="Inductor_SMD:L_0402_1005Metric")
    sh.connect(l3, {"1": (LBL, "ANT"), "2": (LBL, "RF1")})
    c23 = sh.place("C", "C23", "1.2pF NP0", 332.74, 127.0, footprint=C_FP)
    sh.connect(c23, {"1": (LBL, "RF1"), "2": (P, "GND")})
    l4 = sh.place("L", "L4", "2.2nH", 345.44, 127.0,
                  footprint="Inductor_SMD:L_0402_1005Metric")
    sh.connect(l4, {"1": (LBL, "RF1"), "2": (LBL, "RF_FEED")})
    c24 = sh.place("C", "C24", "1.2pF (DNP)", 358.14, 127.0, dnp=True, footprint=C_FP)
    sh.connect(c24, {"1": (LBL, "RF_FEED"), "2": (P, "GND")})
    ant1 = sh.place("ANT_PCB_2G4", "ANT1", "PCB IFA 2.4GHz", 383.54, 121.92,
                    footprint="RF_Antenna:Texas_SWRA117D_2.4GHz_Right")
    sh.connect(ant1, {"1": (LBL, "RF_FEED")})

    # ---- Sensor (wiring per PixArt datasheet v1.0 Figure 6) ----------------
    u5 = sh.place("PAW3311DB-T2MU", "U5", "PAW3311DB-T2MU", 355.6, 187.96,
                  footprint="hakai_fp:PAW3311DB_iDIP8_L0AJ")
    sh.connect(u5, {
        "3": (P, "1V9_A"), "2": (LBL, "VDDREG"), "1": (LBL, "SENS_LED"),
        "6": (P, "GND"),
        "8": (LBL, "SENS_NCS"), "4": (LBL, "SPI_SCK"),
        "7": (LBL, "SENS_SDIO"), "5": (LBL, "SENS_MOTION"),
    })
    # LED chain: 1V9_A(VLED) -> RLED 18R -> IR LED -> pin 1 (24mA internal control)
    c35 = sh.place("C", "C35", "33uF", 302.26, 149.86,
                   footprint="Capacitor_SMD:C_0805_2012Metric")
    sh.connect(c35, {"1": (P, "1V9_A"), "2": (P, "GND")})
    r22 = sh.place("R", "R22", "18R 1%", 314.96, 149.86, footprint=R_FP)
    sh.connect(r22, {"1": (P, "1V9_A"), "2": (LBL, "LED_DRV")})
    d2 = sh.place("LED", "D2", "IR LED (SMT / L0AJ-LSG1 set)", 330.2, 149.86,
                  footprint="LED_SMD:LED_1206_3216Metric")
    sh.connect(d2, {"1": (LBL, "LED_DRV"), "2": (LBL, "SENS_LED")})
    # VDD bypass 10uF+100nF; VDDREG bypass 4.7uF/10V+100nF (Fig.6 values)
    c25 = sh.place("C", "C25", "100nF", 330.2, 213.36, footprint=C_FP)
    sh.connect(c25, {"1": (P, "1V9_A"), "2": (P, "GND")})
    c26 = sh.place("C", "C26", "10uF", 342.9, 213.36, footprint=C_FP6)
    sh.connect(c26, {"1": (LBL, "1V9_A"), "2": (P, "GND")})
    c27 = sh.place("C", "C27", "4.7uF/10V", 355.6, 213.36, footprint=C_FP6)
    sh.connect(c27, {"1": (LBL, "VDDREG"), "2": (P, "GND")})
    c34 = sh.place("C", "C34", "100nF", 368.3, 213.36, footprint=C_FP)
    sh.connect(c34, {"1": (LBL, "VDDREG"), "2": (P, "GND")})
    r13 = sh.place("R", "R13", "10k", 381.0, 213.36, footprint=R_FP)
    sh.connect(r13, {"1": (P, "1V9_A"), "2": (LBL, "SENS_NCS")})
    r14 = sh.place("R", "R14", "10k (DNP)", 393.7, 213.36, dnp=True, footprint=R_FP)
    sh.connect(r14, {"1": (LBL, "1V9_A"), "2": (LBL, "SENS_MOTION")})
    # 3-wire SDIO bridge (Fig.6): MCU MISO direct on SDIO; MCU MOSI via R23
    r23 = sh.place("R", "R23", "3.3k 1%", 396.24, 187.96, footprint=R_FP)
    sh.connect(r23, {"1": (LBL, "SPI_MOSI"), "2": (LBL, "SENS_SDIO")})

    # ---- Status LED (from VSYS via Q2 - a 1.9V rail cannot light a blue LED)
    # placed in the open band above the MCU, clear of the RF notes
    r12 = sh.place("R", "R12", "1k", 236.22, 43.18, footprint=R_FP)
    sh.connect(r12, {"1": (P, "VSYS"), "2": (LBL, "LED_A")})
    d3 = sh.place("LED", "D3", "BLUE", 236.22, 63.5,
                  footprint="LED_SMD:LED_0603_1608Metric")
    sh.connect(d3, {"1": (LBL, "LED_A"), "2": (LBL, "LED_K")})
    q2 = sh.place("AO3400A", "Q2", "AO3400A", 254.0, 71.12,
                  footprint="Package_TO_SOT_SMD:SOT-23")
    sh.connect(q2, {"1": (LBL, "LED_STAT"), "3": (LBL, "LED_K"), "2": (P, "GND")})
    r24 = sh.place("R", "R24", "100k", 279.4, 71.12, footprint=R_FP)
    sh.connect(r24, {"1": (LBL, "LED_STAT"), "2": (P, "GND")})

    # ---- Buttons (45.7mm pitch so net labels never reach the next switch) ----
    btns = [("SW1", "BTN_LEFT", 121.92), ("SW2", "BTN_RIGHT", 167.64),
            ("SW3", "BTN_SIDE_BACK", 213.36), ("SW4", "BTN_SIDE_FWD", 259.08)]
    for i, (ref, net, x) in enumerate(btns):
        pm = sh.place("SW_Kailh_GM8", ref, "Kailh GM 8.0", x, 266.7,
                      footprint="hakai_fp:SW_Kailh_GM8_D2F")
        sh.connect(pm, {"1": (P, "GND"), "2": (LBL, net), "3": (NC,)})
        rp = sh.place("R", f"R{15 + i}", "10k", x, 241.3, footprint=R_FP)
        sh.connect(rp, {"1": (P, "1V9_A"), "2": (LBL, net)})
        cd = sh.place("C", f"C{28 + i}", "100nF (DNP)", x, 285.75,
                      dnp=True, footprint=C_FP)
        sh.connect(cd, {"1": (LBL, net), "2": (P, "GND")})

    # ---- Split wheel: EC1 = rotation (left bay wall), SW5 = click (right) ---
    ec1 = sh.place("ENC_MOUSE_11MM", "EC1", "11mm encoder", 294.64, 243.84,
                   footprint="hakai_fp:ENC_Mouse_11mm")
    sh.connect(ec1, {"A": (LBL, "ENC_A"), "C": (P, "GND"), "B": (LBL, "ENC_B")})
    sw5 = sh.place("SW_TACT", "SW5", "TACT_6x6", 287.02, 266.7,
                   footprint="Button_Switch_THT:SW_TH_Tactile_Omron_B3F-100x")
    sh.connect(sw5, {"1": (LBL, "ENC_SW"), "2": (P, "GND")})
    sh.text("Wheel: EC1 = rotation (left bay wall, D-socket); SW5 tact = middle click (right).", 20.32, 261.62)
    sh.text("Wheel / axle / cradle are shell parts, not PCB items.", 20.32, 265.43)
    for ref, net, x in (("R19", "ENC_A", 302.26), ("R20", "ENC_B", 314.96),
                        ("R21", "ENC_SW", 327.66)):
        pm = sh.place("R", ref, "10k", x, 234.95, footprint=R_FP)
        sh.connect(pm, {"1": (P, "1V9_A"), "2": (LBL, net)})
    for ref, net, x in (("C32", "ENC_A", 274.32), ("C33", "ENC_B", 287.02)):
        pm = sh.place("C", ref, "10nF", x, 285.75, footprint=C_FP)
        sh.connect(pm, {"1": (LBL, net), "2": (P, "GND")})

    # ---- SWD + test points ---------------------------------------------------
    j3 = sh.place("CONN_SWD_05", "J3", "SWD 1x05", 340.36, 243.84,
                  footprint="Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical")
    sh.connect(j3, {"1": (P, "1V9_A"), "2": (LBL, "SWDIO"), "3": (LBL, "SWDCLK"),
                    "4": (LBL, "nRESET"), "5": (P, "GND")})
    tps = [("TP1", "SPI_SCK", 396.24, 63.5), ("TP2", "SENS_SDIO", 396.24, 76.2),
           ("TP3", "SPI_MOSI", 396.24, 88.9), ("TP4", "SENS_MOTION", 396.24, 101.6)]
    for ref, net, x, y in tps:
        pm = sh.place("TP", ref, ref, x, y, footprint="TestPoint:TestPoint_Pad_1.0x1.0mm")
        sh.connect(pm, {"1": (LBL, net)})
    tp5 = sh.place("TP", "TP5", "TP5", 345.44, 63.5, footprint="TestPoint:TestPoint_Pad_1.0x1.0mm")
    sh.connect(tp5, {"1": (P, "VBAT")})
    tp6 = sh.place("TP", "TP6", "TP6", 345.44, 76.2, footprint="TestPoint:TestPoint_Pad_1.0x1.0mm")
    sh.connect(tp6, {"1": (P, "VSYS")})

    sh.check()
    return sh


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    sh = build()
    sch = sh.emit("HAKAI Wireless Gaming Mouse - Rev 5.0")
    sch_path = os.path.join(OUT_DIR, PROJECT + ".kicad_sch")
    with open(sch_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(sch)
    pro = (
        '{\n'
        '  "board": { "design_settings": {} },\n'
        f'  "meta": {{ "filename": "{PROJECT}.kicad_pro", "version": 1 }},\n'
        '  "schematic": { "legacy_lib_dir": "", "legacy_lib_list": [] },\n'
        f'  "sheets": [ [ "{ROOT_UUID}", "" ] ],\n'
        '  "text_variables": {}\n'
        '}\n'
    )
    with open(os.path.join(OUT_DIR, PROJECT + ".kicad_pro"), "w", encoding="utf-8", newline="\n") as f:
        f.write(pro)
    print("wrote", sch_path)
    # quick stats
    print("labels:", sum(sh.label_nets.values()), "nets:", len(sh.label_nets))


if __name__ == "__main__":
    main()
