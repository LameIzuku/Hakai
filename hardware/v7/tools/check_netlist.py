#!/usr/bin/env python3
"""Cross-check the KiCad-exported netlist against the Rev 5.2 design intent.

Usage: python check_netlist.py [path-to-net.net]
Default netlist: <package>/build/net.net  (export with
  kicad-cli sch export netlist --output build/net.net hakai_mouse_v6.kicad_sch)
"""
import os
import re
import sys

NET = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "build", "net.net")

text = open(NET, encoding="utf-8").read()


def parse_sexp(s):
    """Minimal s-expression parser: returns nested lists of str."""
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


root = parse_sexp(text)
nets = {}
for netblk in find_all(root, 'net'):
    namef = child(netblk, 'name')
    if not namef:
        continue
    name = namef[1].lstrip('/')
    nodes = set()
    for node in find_all(netblk, 'node'):
        ref = child(node, 'ref')
        pin = child(node, 'pin')
        if ref and pin:
            nodes.add((ref[1], pin[1]))
    nets[name] = nodes

EXPECT = {
    "SPI_SCK":      {("U4", "AD16"), ("U5", "4"), ("TP1", "1")},
    "SPI_MOSI":     {("U4", "AD18"), ("R23", "1"), ("TP3", "1")},
    "SENS_SDIO":    {("U4", "AD20"), ("U5", "7"), ("R23", "2"), ("TP2", "1")},
    "VDDREG":       {("U5", "2"), ("C27", "1"), ("C34", "1")},
    "SENS_NCS":     {("U4", "AD12"), ("U5", "8"), ("R13", "2")},
    "SENS_MOTION":  {("U4", "A14"), ("U5", "5"), ("R14", "2"), ("TP4", "1")},
    "SENS_LED":     {("U5", "1"), ("D2", "2")},
    "LED_DRV":      {("R22", "2"), ("D2", "1")},
    "BTN_LEFT":     {("U4", "J1"), ("SW1", "2"), ("R15", "2"), ("C28", "1")},
    "BTN_RIGHT":    {("U4", "W24"), ("SW2", "2"), ("R16", "2"), ("C29", "1")},
    "BTN_SIDE_BACK": {("U4", "U24"), ("SW3", "2"), ("R17", "2"), ("C30", "1")},
    "BTN_SIDE_FWD": {("U4", "M2"), ("SW4", "2"), ("R18", "2"), ("C31", "1")},
    "ENC_A":        {("U4", "N1"), ("EC1", "A"), ("R19", "2"), ("C32", "1")},
    "ENC_B":        {("U4", "T2"), ("EC1", "B"), ("R20", "2"), ("C33", "1")},
    "ENC_SW":       {("U4", "U1"), ("SW5", "2"), ("R21", "2")},
    "LED_STAT":     {("U4", "AD8"), ("Q2", "1"), ("R24", "1")},
    "LED_A":        {("R12", "2"), ("D3", "1")},
    "LED_K":        {("D3", "2"), ("Q2", "3")},
    "STAT":         {("U4", "AC9"), ("U2", "9"), ("R6", "2")},
    "PGOOD":        {("U4", "AD10"), ("U2", "7"), ("R7", "2")},
    "nRESET":       {("U4", "AC13"), ("J3", "4"), ("R11", "2")},
    "SWDIO":        {("U4", "AC24"), ("J3", "2")},
    "SWDCLK":       {("U4", "AA24"), ("J3", "3")},
    "VBAT_SENSE":   {("U4", "A12"), ("R8", "2"), ("R9", "1")},
    "VBAT_EN":      {("U4", "AD22"), ("Q1", "1"), ("R10", "1")},
    # v5.2 high-side divider switch: Q3 (P-FET) feeds R8; Q1 pulls Q3's gate
    "VBAT_SW":      {("Q3", "3"), ("R8", "1")},
    "VBAT_SW_G":    {("Q3", "1"), ("R25", "2"), ("Q1", "3")},
    "DEC1":         {("U4", "C1"), ("C9", "1")},
    "DEC3":         {("U4", "D23"), ("C10", "1")},
    "DEC4_6":       {("U4", "B5"), ("U4", "E24"), ("C11", "1"), ("C12", "1"), ("L2", "2")},
    "DCC":          {("U4", "B3"), ("L1", "1")},
    "DCC_L":        {("L1", "2"), ("L2", "1")},
    "XC1":          {("U4", "B24"), ("Y1", "1"), ("C18", "1")},
    "XC2":          {("U4", "A23"), ("Y1", "2"), ("C19", "1")},
    "XL1":          {("U4", "D2"), ("Y2", "1"), ("C20", "1")},
    "XL2":          {("U4", "F2"), ("Y2", "2"), ("C21", "1")},
    "ANT":          {("U4", "H23"), ("C22", "1"), ("L3", "1")},
    "RF1":          {("L3", "2"), ("C23", "1"), ("L4", "1")},
    "RF_FEED":      {("L4", "2"), ("C24", "1"), ("ANT1", "1")},
    "CC1":          {("J1", "A5"), ("R1", "1")},
    "CC2":          {("J1", "B5"), ("R2", "1")},
    "TS":           {("U2", "1"), ("R3", "1")},
    "ILIM":         {("U2", "12"), ("R4", "1")},
    "ISET":         {("U2", "16"), ("R5", "1")},
    "LDO_IN":       {("F1", "2"), ("U3", "1"), ("U3", "3"), ("C4", "1")},
}

# power rails: expected MEMBERS (subset check)
RAIL_SUBSET = {
    "VBUS": {("J1", "A4"), ("J1", "A9"), ("J1", "B4"), ("J1", "B9"),
             ("U2", "13"), ("D1", "1"), ("C1", "1"), ("C2", "1")},
    "VBAT": {("U2", "2"), ("U2", "3"), ("J2", "1"), ("TP5", "1"),
             ("C36", "1"), ("Q3", "2"), ("R25", "1")},
    "VSYS": {("U2", "10"), ("U2", "11"), ("U2", "5"), ("F1", "1"), ("C3", "1"),
             ("TP6", "1"), ("R12", "1")},
    "1V9":  {("U3", "5"), ("C5", "1"), ("C6", "1"), ("FB1", "1")},
    "1V9_A": {("FB1", "2"), ("C7", "1"), ("C8", "1"),
              ("U4", "A22"), ("U4", "B1"), ("U4", "W1"), ("U4", "AD14"),
              ("U4", "AD23"), ("U4", "Y2"),
              ("C13", "1"), ("C14", "1"), ("C15", "1"), ("C16", "1"), ("C17", "1"),
              ("U5", "3"), ("C25", "1"), ("C26", "1"), ("C35", "1"), ("R22", "1"),
              ("R13", "1"), ("R14", "1"), ("R11", "1"),
              ("R15", "1"), ("R16", "1"), ("R17", "1"), ("R18", "1"),
              ("R19", "1"), ("R20", "1"), ("R21", "1"),
              ("R6", "1"), ("R7", "1"), ("J3", "1")},
    "GND":  {("U4", "B7"), ("U4", "F23"), ("U4", "74"),
             ("U2", "8"), ("U2", "17"), ("U2", "4"), ("U2", "6"),
             ("U3", "2"), ("U5", "6"), ("J2", "2"), ("J3", "5"),
             ("J1", "A1"), ("J1", "B1"), ("J1", "A12"), ("J1", "B12"), ("J1", "S1"),
             ("Q1", "2"), ("Q2", "2"), ("EC1", "C"), ("SW5", "1"),
             ("SW1", "1"), ("SW2", "1"), ("SW3", "1"), ("SW4", "1"),
             ("D1", "2"), ("R1", "2"), ("R2", "2"), ("R3", "2"), ("R4", "2"),
             ("R5", "2"), ("R9", "2"), ("R10", "2"), ("R24", "2"), ("C36", "2"),
             ("C9", "2"), ("C10", "2"), ("C11", "2"), ("C12", "2"),
             ("C18", "2"), ("C19", "2"), ("C20", "2"), ("C21", "2"),
             ("C22", "2"), ("C23", "2"), ("C24", "2"), ("C25", "2"),
             ("C26", "2"), ("C27", "2"), ("C34", "2"), ("C35", "2")},
}

fail = 0
for net, exp in EXPECT.items():
    got = nets.get(net)
    if got is None:
        print(f"FAIL {net}: net missing entirely"); fail += 1; continue
    if got != exp:
        extra = got - exp
        missing = exp - got
        print(f"FAIL {net}: missing={sorted(missing)} extra={sorted(extra)}"); fail += 1

for net, subset in RAIL_SUBSET.items():
    got = nets.get(net, set())
    missing = subset - got
    if missing:
        print(f"FAIL rail {net}: missing members {sorted(missing)}"); fail += 1

# sanity: no unexpected merged nets (each expected net must exist independently)
if fail == 0:
    print(f"ALL CHECKS PASS: {len(EXPECT)} signal nets exact-match, {len(RAIL_SUBSET)} rails verified, {len(nets)} total nets in netlist")
sys.exit(1 if fail else 0)
