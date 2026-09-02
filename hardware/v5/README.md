# HAKAI Wireless Gaming Mouse — v5.1 Release Package

> **v5.1:** the wheel's middle-click switch is now a **5th Kailh GM 8.0** (SW5) instead of a
> 6×6 tact — same crisp tactility as the main clicks, one switch part number for the whole
> mouse (BOM groups SW1–SW5, qty 5). Plunger end faces the wheel bay; match the shell
> cradle's press travel to the Kailh's actuation height. Nets/pins unchanged (`ENC_SW` → P0.12).

nRF52833 (integrated 2.4 GHz radio) · PixArt PAW3311DB (datasheet-verified wiring) ·
4× Kailh GM 8.0 · **split scroll wheel** (EC1 encoder + SW5 tact) · BQ24074 charger ·
**single 1.9 V system rail** · shaped mouse-plate PCB with open wheel bay.

## Contents

| File | What |
|---|---|
| `hakai_mouse_v5.kicad_pro` | **Open this** in KiCad 8/9/10 |
| `hakai_mouse_v5.kicad_sch` | Schematic, Rev 5.0. ERC = 0 |
| `hakai_mouse_v5.kicad_pcb` | Shaped board: all footprints placed + full net assignment. **UNROUTED** |
| `hakai_mouse_v5_schematic.pdf` | Plotted schematic for review |
| `board_top_render.png` | 3D top view of the board |
| `BOM_hakai_mouse_v5.csv` | Grouped bill of materials (kicad-cli export) |
| `Cost_Estimate_hakai_mouse_v5.csv` | Per-part cost estimates + totals (≈$17.72 parts / ≈$24.22 w/ battery) |
| `footprints.pretty/` + `fp-lib-table` | Custom footprints: PAW3311 iDIP-8 (aperture/LED cutouts per datasheet Table 9), Kailh GM8/D2F, 11 mm encoder |
| `datasheets/PAW3311DB-T2MU_v1.0.pdf` | PixArt datasheet — source of all sensor wiring |
| `verification/` | ERC report, DRC report, netlist cross-check, pad-by-pad electrical audit |
| `tools/` | Python generators + checkers that build this project (run with KiCad's bundled python) |

## v5 design highlights

- **Split scroll wheel (type B, like commercial mice):** EC1 = 11 mm rotation-only encoder on the
  **left wheel-bay wall** (D-socket accepts the wheel axle, shaft points into the bay);
  SW5 = **Kailh GM 8.0** on the **right wall** — the wheel cradle presses it for middle click,
  giving M3 the same tactility as the main buttons.
  Nets/pins: `ENC_A`→P0.08, `ENC_B`→P0.11 (nRF QDEC-compatible), `ENC_SW`→P0.12, all with 10 k pull-ups.
  Wheel/axle/cradle are shell parts, not PCB items.
- **Single 1.9 V rail** (XC6219B192MR): PAW3311 VDD abs max is 2.1 V — 3.3 V anywhere on the sensor
  is fatal; the nRF52833 runs 1.7–3.6 V so MCU + sensor share the rail, no level shifting.
  Status LED runs from VSYS via Q2 (AO3400A); SWD debug is 1.9 V logic (set probe VTref).
- **Sensor wiring verified against the real datasheet** (v1.0, 1A009EN): 3-wire SDIO with the
  MISO-direct / MOSI-via-3.3 k bridge (R23; 1 k @ 4 MHz, 240 Ω @ 8 MHz), VDDREG bypass-only
  (4.7 µF/10 V + 100 nF), MOTION push-pull, LED chain 1V9 → 18 Ω 1% → IR LED → pin 1 (24 mA).
- **Board**: 70 × 110 mm envelope, 0.8 mm thick (sensor lens stack requires it), 2-layer.
  Open U wheel bay 24 × 38 mm between switch ears; chamfered corners; narrowed tail with
  **USB-C charge port at the tail edge**; sensor aperture + LED board cutouts inside the U5
  footprint (optical center at 135, 106); TI SWRA117D PCB antenna in a copper-free tail zone;
  3× M3 mounting holes; GND pour both layers.
- **nRF52833 support circuitry verified** against Nordic PS v1.7 + PCA10100 DK files:
  DEC3 = 100 pF (not 100 nF), DEC4+DEC6 tied (1 µF + 47 nF), DC/DC 10 µH + 15 nH,
  RF match 1.0 pF / 4.7 nH / 1.2 pF / 2.2 nH + antenna-dependent tune cap (DNP).
  BQ24074: ILIM mode 497 mA input / 445 mA charge, TS 10 k fixed, TMR/ITERM float.

## Verification shipped in `verification/`

- `ERC_report.rpt` — 0 violations
- `netlist_crosscheck.txt` — 44 signal nets + 6 rails exact-match against the design intent
- `pad_audit.txt` — **every PCB pad's net compared to the schematic netlist: 0 mismatches**
  (die pad / USB shield / crystal shell / antenna stub / encoder brackets are the verified,
  whitelisted board-side extras)
- `DRC_report.rpt` — 0 error-severity violations (silk-cosmetic warnings + unrouted ratsnest only)
- Geometric containment: every pad verified inside the shaped outline

## Before fab (the honest list)

1. **Route it** — the board is placed + netted, deliberately unrouted. RF path (nRF ANT →
   1.0 pF/4.7 nH/1.2 pF/2.2 nH → antenna): copy Nordic PCA10100 trace/ground geometry verbatim,
   50 Ω, stitch vias, then VNA-tune C24.
2. **EC1 vendor check** — pin/bracket spacing is a generic 11 mm pattern; verify against the exact
   TTC / F-switch drawing you buy.
3. **SW5 actuation** — shell cradle press travel must match the Kailh's plunger height/force
   (plunger end faces the bay); a GM 4.0 swap is drop-in if M3 ends up too easy to trigger.
4. **Sensor LED cutout** — drawn R0.65 for DRC; enlarge to the datasheet's R0.90 × 2.00 stadium
   with the lens datasheet's LED pad geometry at final fab.
5. **Kailh switch bosses** — add the two locating holes per the Omron D2F drawing.
6. **Battery polarity** — JST PH has no standard; this design says pin 1 = BAT+. Verify the pigtail
   with a DMM. Use a protected cell.

## Firmware bring-up notes

- SPI mode 3, start ≤2 MHz (matches R23 = 3.3 k). Wake-from-shutdown needs RESET + 50 ms (tMOT-RST).
- Scroll decoding: nRF52833 **QDEC** peripheral on P0.08/P0.11; LED pin on P0.13 gates Q2 from VSYS.
- nRESET = P0.18 via UICR PSELRESET; DC/DC REG1 enabled (L fitted). Battery ADC: AIN0, divider
  gated by P0.03 (zero standby drain).

## Regenerating (reproducible build)

`tools/` contains the deterministic generators: `gen_kicad.py` (schematic), `pcb_gen.py` (board),
plus the checkers (`check_netlist.py`, `pcb_check.py`, `drc_summary.py`). Run with KiCad's bundled
Python (`C:\Program Files\KiCad\10.0\bin\python.exe`). Edit the `OUT_DIR`/`PROJ` constants at the
top of each script to point at a working folder; the scripts rebuild the schematic and board from
scratch and re-run against the exported netlist.
