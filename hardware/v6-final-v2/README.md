# HAKAI Wireless Gaming Mouse — v6.0 ROUTED Release Package

> **v6.0 = v5.3 + full routing.** The deliberately-unrouted v5.3 board is now
> **routed: all 138 signal connections placed and DRC-clean**, GND poured and
> stitched (280+ vias), with manufacturing design rules baked into the project.
> Two small GND spokes remain as documented hand-fixes (below) — everything
> else is fab-ready copper.

## ⚠️ v6.0 PIN SWAPS (firmware-relevant!)

The nRF52833's aQFN-73 west face physically cannot escape six signals on a
2-layer board (0.25 mm ball channels; vias do not fit between escape lines).
Three GPIOs moved to free balls with open escapes — **schematic + netlist +
board all updated and re-verified**; only firmware pin constants change:

| Signal | was (v5.3) | **now (v6.0)** |
|---|---|---|
| BTN_RIGHT | P0.05 (K2) | **P1.02 (W24)** |
| BTN_SIDE_BACK | P0.06 (L1) | **P1.04 (U24)** |
| VBAT_EN | P0.03 (B13) | **P1.00 (AD22)** |

(BTN_LEFT stays P0.04, BTN_SIDE_FWD stays P0.07, encoder/SPI/etc. unchanged.)

## Final verification state (all shipped in `verification/`)

- **ERC: 0 violations.** Netlist cross-check: 45 signal nets + 6 rails exact.
- **Pad audit: 306 pad↔net assignments, 0 mismatches** (post-pin-swap).
- **DRC: 0 error-severity violations.** 4 cosmetic silkscreen warnings
  (refdes overlaps, same class v5.3 documented).
- **2 unconnected items — the documented hand-fixes:** the GND pour tongues
  under **C12-2** and **C19-2** connect to their pads but not to the GND
  mainland (each pocket is sealed by routed tracks on both layers at rule
  clearance; automated repair verified-impossible without moving neighbors).
  **Fix interactively in KiCad (~5 min each):** push-and-shove the crossing
  track (STAT's B.Cu run near C12; the XL2-area diagonal near C19) a few
  tenths, then drop a GND via in the freed tongue, or drag a short GND spoke.
  Until fixed, C12 (47 nF DEC4_6 bypass) and C19 (12 pF XC2 load) are
  electrically floating — **do not fab before closing these two**.

## How it was routed (reproducible)

1. `tools/set_rules.py` — netclasses: Default 0.15/0.15 mm, power 0.30 mm,
   fine 0.10/0.075 mm (aQFN ring-2 escapes); vias 0.45/0.20; plus
   `hakai_mouse_v6.kicad_dru` courtyard relaxations.
2. **Freerouting 2.2.4** (Java 25) over a Specctra DSN export, seeded with
   deterministic ball-escape stubs: ~130 of 138 connections.
   `tools/fr_import.py` reimports the SES.
3. Local grid A* + exact-geometry checkers (`tools/routes*.py`,
   `tools/*_finish.py`) for the remaining spans, GND stitching (3.5 mm grid,
   pour-validated), the nRF EP ground tie, and pad-tongue spokes.
4. `tools/package_v6.sh` — gerbers/drill/zip/render + full verify suite.

## Fab notes

- 2 layers, **0.8 mm** (sensor lens stack requirement), gerbers in
  `GERBERS_hakai_v6_PROTO.zip` (X2, with job file).
- **Copper weight: 1 oz (35 µm) outer copper on both F.Cu and B.Cu.**
  Specify this on the fab drawing / order form (not left to fab default).
- **Advanced-prototype class**: min track 0.10 mm, min clearance 0.075 mm
  (only inside the two QFN courtyards), vias 0.45/0.20 mm, hole-to-copper
  0.20 mm. JLCPCB/PCBWay "advanced" 2-layer services cover this; confirm
  3.5 mil capability when ordering.
- RF: the antenna feed keeps the Nordic-verbatim match chain; the tail
  antenna zone is copper-free. **VNA-tune C24 (DNP) after assembly.**
- **MH3 (NPTH Ø3.2 @ 155,130) assembly: use a nylon or other insulating
  washer / standoff under the screw.** Do **not** use a bare metal washer
  that could bridge copper inside ~r=4.5 mm of the hole (SWDCLK and nearby
  copper remain in that mechanical envelope by design).
- v5.3's "before fab" list still applies: verify EC1 encoder drawing, SW5
  plunger travel, IR-LED P/N pads, and battery pigtail polarity (pin 1 = BAT+).

## Firmware bring-up deltas vs v5.3

- Buttons: right = **P1.02**, side-back = **P1.04** (active-low, 10 k pull-ups).
- Battery sampling: drive **P1.00** high (was P0.03) → Q1 → Q3 connects the
  divider; AIN0 (P0.02) unchanged.
- Everything else per v5.3 notes (SPI mode 3 ≤2 MHz start, QDEC on
  P0.08/P0.11, nRESET P0.18, DC/DC enabled).

## Contents

| File | What |
|---|---|
| `hakai_mouse_v6.kicad_pro/sch/pcb` | Rev 6.0 project — **routed** board |
| `hakai_mouse_v6_schematic.pdf` | Plotted schematic (rev 6.0, pin swaps in) |
| `board_top_render.png` | 3D render of the routed board |
| `GERBERS_hakai_v6_PROTO.zip` + `gerbers/` | Fab outputs (12 files) |
| `BOM_hakai_mouse_v6.csv`, `Cost_Estimate_hakai_mouse_v6.csv` | unchanged BOM/cost (≈$18.39/$24.89) |
| `verification/` | ERC, DRC, netlist cross-check, pad audit |
| `tools/` | generators, routers, checkers (KiCad 10 bundled python) |
| `datasheets/` | PixArt PAW3311DB, TI BQ24074, Torex XC6219 |
