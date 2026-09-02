# HAKAI Wireless Gaming Mouse — Rev 5.0 KiCad Project

> **Rev 5.0 — split scroll wheel (type B, like commercial mice):** the integrated
> push-encoder is replaced by **EC1** (11 mm rotation-only encoder, LEFT bay wall,
> D-socket takes the wheel axle) + **SW5** (6×6 tact, RIGHT bay wall — the cradle
> arm presses it for middle click). Same nets, same MCU pins (`ENC_A` P0.08,
> `ENC_B` P0.11, `ENC_SW` P0.12). Wheel/axle/cradle are shell parts.
> Verify EC1's pin/bracket spacing against the chosen vendor drawing before fab.

> **Rev 4.1** = Rev 2.1 electrical design (netlist unchanged since datasheet verification) +
> schematic layout cleanup (v3) + shaped mouse-plate PCB (v4.1, modeled on a commercial DIY mouse board):
> - **U-shaped wheel bay** (24×38 mm, open at the front edge) between two switch "ears";
>   encoder sits at the bay bottom with the wheel hanging into it
> - chamfered corners, mid-side steps, **narrowed tail** with the **USB-C charge port at the tail edge**
> - sensor **aperture + LED cutouts** (inside the U5 footprint, per PixArt Table 9); optical center (135, 106)
> - **3× M3 mounting holes** (board-only footprints MH1–MH3); antenna in a copper-free tail zone
> - geometric containment check: every pad verified inside the shaped outline
>
> **Full electrical audit (v4):** every pad on the PCB was machine-compared against the
> schematic netlist — 309 pads vs 298 assignments (250 named nets + 48 no-connects),
> **0 mismatches**; die pad→GND, USB shield→GND, crystal shell→GND, antenna stub→GND
> verified as the only intentional board-side extras. Schematic ERC = 0, PCB DRC = 0 errors.

nRF52833 (integrated 2.4 GHz radio) · PixArt PAW3311DB (datasheet-verified wiring) ·
4× Kailh GM 8.0 · scroll encoder · BQ24074 charger · **single 1.9 V system rail**.

## Contents

| File | What |
|---|---|
| `hakai_mouse_rev2.kicad_pro` | Project file — open this in KiCad 8/9/10 |
| `hakai_mouse_rev2.kicad_sch` | Schematic. ERC = 0. Netlist machine-verified against the design doc (44 nets) |
| `hakai_mouse_rev2.kicad_pcb` | Board: all 91 footprints placed + full net assignment. **UNROUTED** (see below). DRC = 0 errors (silk warnings only) |
| `hakai_mouse_rev2.pdf` | Plotted schematic |
| `BOM_hakai_mouse_rev2.csv` | Grouped bill of materials (kicad-cli export) |
| `Cost_Estimate_hakai_mouse_rev2.csv` | Per-part approximate prototype costs + PCB fab + totals |
| `footprints.pretty/` + `fp-lib-table` | Custom footprints: PAW3311 iDIP-8 (with aperture/LED board cutouts per datasheet Table 9), Kailh GM8/D2F, 11 mm encoder |
| `datasheets/PAW3311DB-T2MU_v1.0.pdf` | PixArt datasheet (source of all sensor wiring) |

## Board facts

- 70 × 110 mm, **0.8 mm thickness** (PAW3311 lens stack requires it), 2-layer.
- Sensor optical center at board center; sensor aperture + LED **board cutouts** are on Edge.Cuts inside the sensor footprint.
- GND pour on both layers, shaped to keep the antenna region copper-free.
- Antenna: TI SWRA117D PCB IFA (proven 2.4 GHz copper footprint from the KiCad library).

## Before fab — the honest list

1. **Route it.** The board is placed + netted, not routed. RF path (nRF ANT → C22/L3/C23/L4 → ANT1):
   copy the trace/ground geometry from Nordic's PCA10100 reference, 50 Ω, shunt caps grounded to the
   VSS nearest ANT, stitch vias around the RF section. Then VNA-tune C24.
2. **Enlarge the LED cutout** in the sensor footprint from the DRC-safe R0.65 circle to the datasheet's
   R0.90 × 2.00 stadium, and use the lens datasheet's LED pad geometry (a generic 1206 is close but not exact).
3. **Verify the encoder footprint** against your actual vendor (TTC/Alps/F-switch pin spacing varies).
4. Kailh switch footprint: add the two locating-boss holes per the Omron D2F drawing.
5. JST battery pigtail: **verify polarity with a DMM** — pin 1 = BAT+ is this design's convention, there is no JST standard.
6. SWD probe VTref = 1.9 V logic.

## Firmware bring-up notes

- SPI mode 3, ≤2 MHz initially (R23 = 3.3 k matches 2 MHz; 1 k @ 4 MHz, 240 Ω @ 8 MHz).
- 3-wire SDIO bridge: MCU MISO reads SDIO directly; MOSI drives through R23.
- Wake-from-shutdown requires RESET, then 50 ms before valid motion (tMOT-RST).
- nRESET is P0.18 via UICR PSELRESET; DC/DC REG1 enabled (10 µH + 15 nH fitted).
