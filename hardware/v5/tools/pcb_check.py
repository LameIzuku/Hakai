#!/usr/bin/env python3
"""Full electrical-connection audit: every pad on the saved .kicad_pcb must
carry exactly the net the schematic netlist assigns it (including the
'unconnected-*' single-pad nets for NC pins). Intentional board-side extras
(die pad, USB shield, crystal shell, antenna ground stub, mounting holes)
are whitelisted explicitly - anything else is a failure."""
import re
import os
import sys
import pcbnew

SP = r"C:\Users\izuku\AppData\Local\Temp\claude\C--Users-izuku-Documents-hakai-claud\5b48d870-2552-4ee6-a329-7bb2248b20f1\scratchpad"
PCB = r"C:\Users\izuku\Documents\hakai\claud\hakai_mouse_v5\hakai_mouse_v5.kicad_pcb"


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


root = parse_sexp(open(os.path.join(SP, "net.net"), encoding="utf-8").read())
want = {}                       # (ref, pad) -> netname
for n in find_all(root, 'net'):
    name = child(n, 'name')[1].lstrip('/')
    for nd in find_all(n, 'node'):
        want[(child(nd, 'ref')[1], child(nd, 'pin')[1])] = name

# generator-intentional board-side extras: (ref, pad) -> expected net
EXTRA = {
    ("Y1", "2"): "GND", ("Y1", "4"): "GND",          # 4-pad crystal shell
    ("ANT1", "2"): "GND",                             # IFA ground stub
    ("EC1", "MP1"): "", ("EC1", "MP2"): "",           # encoder bracket tabs (mechanical)
}
# symbol-pin -> footprint-pad remaps the generator applies
REMAP = {
    ("Y1", "2"): ("Y1", "3"),    # 4-pad crystal: xtal out is pad 3
    ("U4", "74"): ("U4", "EP"),  # nRF die pad
    ("J1", "S1"): ("J1", "SH"),  # USB shield stakes
}
for old, new in REMAP.items():
    want[new] = want.pop(old)

BOARD_ONLY_REFS = {"MH1", "MH2", "MH3"}

board = pcbnew.LoadBoard(PCB)
pads = []                       # (ref, padnum, netname)
for fp in board.GetFootprints():
    ref = fp.GetReference()
    for p in fp.Pads():
        pads.append((ref, p.GetNumber(), p.GetNetname().lstrip('/')))

errors = []
checked = 0
covered = set()
for ref, num, net in pads:
    if num == "":
        continue  # unnumbered = mechanical (paste aperture / anchor), never netted
    if ref in BOARD_ONLY_REFS:
        if net not in ("", None):
            errors.append(f"{ref} pad {num}: mounting hole has net '{net}'")
        continue
    key = (ref, num)
    if key in want:
        if net != want[key]:
            errors.append(f"{ref} pad {num}: PCB net '{net}' != netlist '{want[key]}'")
        covered.add(key)
        checked += 1
    elif key in EXTRA:
        if net != EXTRA[key]:
            errors.append(f"{ref} pad {num}: extra pad net '{net}' != expected '{EXTRA[key]}'")
        checked += 1
    else:
        errors.append(f"{ref} pad {num}: pad not in netlist and not whitelisted (net '{net}')")

missing = [k for k in want if k not in covered]
for ref, num in missing:
    errors.append(f"{ref} pad {num}: in netlist ({want[(ref, num)]}) but NOT found on PCB")

named = sum(1 for k, v in want.items() if not v.startswith("unconnected-"))
ncs = len(want) - named
print(f"netlist pad assignments: {len(want)} ({named} on named nets, {ncs} no-connects)")
print(f"PCB pads audited: {checked} (+{sum(1 for r,_,_ in pads if r in BOARD_ONLY_REFS)} mounting-hole pads)")
if errors:
    print(f"\nFAILURES: {len(errors)}")
    for e in errors[:30]:
        print(" ", e)
    sys.exit(1)
print("EVERY ELECTRICAL CONNECTION VERIFIED: PCB pad nets == schematic netlist (0 mismatches)")
