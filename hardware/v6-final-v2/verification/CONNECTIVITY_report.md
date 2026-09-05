# v6-final-v2 — Electrical Connectivity Verification

**Board:** `hardware/v6-final-v2/hakai_mouse_v6.kicad_pcb`
**Date:** 2026-09-05
**Method:** Independent copper-connectivity solver (`tools/verify_connectivity.py`)
parsing the board s-expression directly — no `pcbnew`/`kicad-cli` required.
Rebuilds the copper graph from pads + tracks + vias + zone fills and checks
that every net forms a single connected copper island.

> Scope note: this verifies **connectivity** (opens and net-assignment
> integrity). It does **not** check **clearance** (copper-to-copper shorts),
> which requires KiCad's DRC geometry engine. The committed board's own pcbnew
> DRC reported 0 clearance violations after the 2026-09-02 zone refill.

## Parsed geometry

| Element | Count |
|---|---|
| Pads | 332 |
| Track segments | 1780 |
| Vias | 431 |
| Zone-fill islands | 42 |
| Nets (total) | 100 |

## Result — every connection: PASS

| Check | Result |
|---|---|
| Multi-pad nets | **51 / 51 fully connected** — one copper island each, no opens |
| Single-node nets | 49, **all** KiCad `unconnected-*` intentional no-connects (0 orphaned pads) |
| Net-assignment integrity | Matches design intent (see naming notes) |

## Result — all GND routes: PASS

| GND metric | Value |
|---|---|
| GND pads | **80, all in ONE copper island** |
| Tie network | 205 GND track segments + **306 stitching / connect vias** |
| Pour | F.Cu + B.Cu poured (30 + 12 fill islands), both planes tied together |
| Verified members | U4 exposed thermal pad (`EP`), J1 USB-C shield (4× `SH` tabs), both crystal case pads (Y1.2 / Y1.4) all reach GND |

This confirms the 2026-09-02 refill fixed the pre-refill GND-zone opens. The
older `verification/DRC_report.rpt` (2026-07-12) predates that refill and shows
2 unconnected-GND errors — stale.

## Notes on the analysis

- **ENC_B / U4.T2** first flagged as a separate island. False alarm: the escape
  trace meets the next segment at a 45° jog with endpoints 70.7 µm apart, but
  two 0.10 mm traces overlap in copper out to 100 µm, so it is a valid joint.
  Confirmed at the coordinate level. Two solver corrections were needed and
  validated against raw coordinates before trusting the result:
  1. Footprint rotation is applied clockwise on the Y-down board system
     (rotate pad-local coordinates by `-angle`).
  2. Track-to-track joints must use copper geometry: two segments connect when
     their centreline gap ≤ the sum of their half-widths, not merely when
     endpoints coincide.

- **Two apparent net-assignment mismatches vs. the design-intent table in
  `tools/check_netlist.py` — both are pad-label naming only, electrically
  correct:**
  - `XC2 → Y1.3` (not `Y1.2`): the 4-pin crystal footprint is 1=XC1, 2=GND,
    3=XC2, 4=GND (pads 2/4 are the case-ground tabs).
  - GND: U4 thermal pad is named `EP` (table called it `74`); J1 shield is `SH`
    (table called it `S1`). Both are on GND.

## Reproduce

```
cd hardware/v6-final-v2
python3 tools/verify_connectivity.py            # defaults to hakai_mouse_v6.kicad_pcb
python3 tools/verify_connectivity.py <board.kicad_pcb>
```

**Bottom line:** every connection on v6-final-v2 has electrical validity, and
all GND routes are sound — 80/80 GND pads tied across both planes.
