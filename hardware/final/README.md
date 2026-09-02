# HAKAI Wireless Gaming Mouse — FINAL Release Package (v5.3)

> **v5.3 — sensor/switch mechanicals brought to datasheet-exact, ADC margin doubled:**
> 1. **PAW3311 board features now EXACT per PixArt Table 9 (L0AJ-LSG1 column):** the aperture
>    cutout grows to its true size (x −7.86…+1.64 with the optical-axis notch out to −9.56,
>    y 1.38…11.23, corners R0.40 max — the v5.2 rect was undersized and the lens tower would
>    not have fit); the LED cutout is the real **R0.90 × 2.00 stadium** (was a R0.65 placeholder);
>    the **2× lens guide-post holes** (2.0 × 1.6, R0.40, x 4.58…6.58) are added — the L0AJ lens
>    self-aligns through these and can be heat-staked (PixArt assembly note 8); sensor pin holes
>    are Ø0.80 per the drawing. **D2 now uses a custom footprint** whose pads sit at the Table 9
>    "LED Soldering Pad" positions, 0.12 mm clear of the stadium (a generic 1206 would violate
>    copper-to-edge). C26/C27/R23 moved slightly to clear the new cutouts. **Verify D2's pads
>    against the final PixArt-recommended IR-LED P/N before fab.**
> 2. **Kailh boss-hole question CLOSED — no holes needed:** official Omron D2F + D2FC datasheets
>    and the Kailh GM 8.0 drawing all show a **flat switch bottom**; the "two holes" in those
>    drawings are side-face chassis-pin features 1.5 mm above the PCB. Omron's PCB pattern is
>    3× Ø1.2 terminal holes at 5.08 pitch — the footprint now matches it exactly, and its
>    silk/courtyard is fixed to the true centered 12.8 × 5.8 body (plunger marked on F.Fab).
> 3. **R25 = 47 k (was 100 k):** Q1's worst-case off-state leakage (5 µA) × 47 k = 0.24 V,
>    comfortably under Q3's 0.5 V minimum gate threshold — the paper margin that was zero at
>    100 k is now 2×. Sampling current rises to ~103 µA, still only while P0.03 is high.
> 4. **Placement + silkscreen corrections from the adversarial re-review of this revision:**
>    TP1–TP6 raised to y = 43.5 (SW2's corrected courtyard overlapped the old row and the
>    switch body would have blocked probing); SW4 moved to x = 107.2 (its true-size body
>    overhung the x = 104 board edge); R22/C35/R23 relocated to the open band below the
>    sensor (y = 115.5), fully vacating the PixArt clear zone so only U5 features + the IR
>    LED live inside the lens region; Kailh plunger marker set to x = −1.95 per the verified
>    drawings. **Silkscreen cleaned up:** custom-footprint reference designators repositioned
>    off their own pads/cutouts, the U5 body outline redrawn so it no longer crosses the
>    aperture/notch/stadium cutouts, D2 and the M3-hole refs moved to F.Fab (they sit under
>    the lens / are board-only). DRC silk warnings dropped from 38 → **4** (all harmless
>    refdes-text overlaps in the two densest corners; 0 error-severity violations besides the
>    intentional unrouted ratsnest).

> **v5.2:** C36 (10 µF) added at the BQ24074 BAT pins (Table 7-1 mandatory bypass);
> battery-sense divider re-topologized to **high-side gating** (Q3 AO3401A + R25, Q1 drives the
> gate) so AIN0 can never float above VDD and standby drain is truly zero. New nets `VBAT_SW`,
> `VBAT_SW_G`. **v5.1:** middle click = 5th Kailh GM 8.0 (SW5).

nRF52833 (integrated 2.4 GHz radio) · PixArt PAW3311DB (datasheet-verified wiring **and**
mechanicals) · 5× Kailh GM 8.0 · **split scroll wheel** (EC1 encoder + SW5 Kailh) · BQ24074
charger · **single 1.9 V system rail** · shaped mouse-plate PCB with open wheel bay.

## Contents

| File | What |
|---|---|
| `hakai_mouse_final.kicad_pro` | **Open this** in KiCad 8/9/10 |
| `hakai_mouse_final.kicad_sch` | Schematic, Rev 5.3. ERC = 0 |
| `hakai_mouse_final.kicad_pcb` | Shaped board: all footprints placed + full net assignment. **UNROUTED** |
| `hakai_mouse_final_schematic.pdf` | Plotted schematic for review |
| `board_top_render.png` | 3D top view of the board |
| `BOM_hakai_mouse_final.csv` | Grouped bill of materials (kicad-cli export) |
| `Cost_Estimate_hakai_mouse_final.csv` | Per-part cost estimates + totals (≈$18.39 parts / ≈$24.89 w/ battery) |
| `DATASHEET_hakai_mouse_final.pdf` | Product-level engineering datasheet (HAKAI M1) |
| `footprints.pretty/` + `fp-lib-table` | Custom footprints: PAW3311 iDIP-8 (full Table 9 features), IR-LED pads, Kailh GM8/D2F (verified pattern), 11 mm encoder |
| `datasheets/PAW3311DB-T2MU_v1.0.pdf` | PixArt datasheet — source of all sensor wiring + Table 9 mechanicals |
| `verification/` | ERC report, DRC report, netlist cross-check, pad-by-pad electrical audit |
| `tools/` | Python generators + checkers that build this project (run with KiCad's bundled python) |
| `build/` | Intermediate netlist (`net.net`) used by the board generator and checkers |

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
- **Sensor verified against the real datasheet** (v1.0, 1A009EN) — electrically *and*
  mechanically: 3-wire SDIO with the MISO-direct / MOSI-via-3.3 k bridge (R23; 1 k @ 4 MHz,
  240 Ω @ 8 MHz), VDDREG bypass-only (4.7 µF/10 V + 100 nF), MOTION push-pull, LED chain
  1V9 → 18 Ω 1% → IR LED → pin 1 (24 mA); board features exact per Table 9 (aperture + notch,
  LED stadium, guide-post holes, Ø0.80 pin holes, 0.8 mm PCB).
- **Board**: 70 × 110 mm envelope, 0.8 mm thick (sensor lens stack requires it), 2-layer.
  Open U wheel bay 24 × 38 mm between switch ears; chamfered corners; narrowed tail with
  **USB-C charge port at the tail edge**; sensor aperture/LED/guide-post cutouts inside the U5
  footprint (optical center at 135, 106); TI SWRA117D PCB antenna in a copper-free tail zone;
  3× M3 mounting holes; GND pour both layers.
- **nRF52833 support circuitry verified** against Nordic PS v1.7 + PCA10100 DK files:
  DEC3 = 100 pF (not 100 nF), DEC4+DEC6 tied (1 µF + 47 nF), DC/DC 10 µH + 15 nH,
  RF match 1.0 pF / 4.7 nH / 1.2 pF / 2.2 nH + antenna-dependent tune cap (DNP).
  BQ24074: ILIM mode 497 mA input / 445 mA charge, TS 10 k fixed, TMR/ITERM float,
  BAT bypassed by C36 10 µF at pins 2/3 (v5.2).

## Verification shipped in `verification/`

- `ERC_report.rpt` — 0 violations
- `netlist_crosscheck.txt` — 45 signal nets + 6 rails exact-match against the design intent
- `pad_audit.txt` — **every PCB pad's net compared to the schematic netlist: 0 mismatches**
  (die pad / USB shield / crystal shell / antenna stub / encoder brackets are the verified,
  whitelisted board-side extras)
- `DRC_report.rpt` — 0 error-severity violations besides the intentional unrouted ratsnest
  (KiCad rates each of the 143 missing connections as an error; the only other entries are
  4 silk-cosmetic warnings — refdes-text overlaps in the two densest corners, no electrical,
  clearance, or solder-mask impact)
- Geometric containment: every pad verified inside the shaped outline

## Before fab (the honest list)

1. **Route it** — the board is placed + netted, deliberately unrouted. RF path (nRF ANT →
   1.0 pF/4.7 nH/1.2 pF/2.2 nH → antenna): copy Nordic PCA10100 trace/ground geometry verbatim,
   50 Ω, stitch vias, then VNA-tune C24.
2. **EC1 vendor check** — pin/bracket spacing is a generic 11 mm pattern; verify against the exact
   TTC / F-switch drawing you buy.
3. **SW5 actuation** — shell cradle press travel must match the Kailh's plunger height/force
   (plunger end faces the bay); a GM 4.0 swap is drop-in if M3 ends up too easy to trigger.
4. **IR LED P/N** — D2's pads follow PixArt Table 9; confirm them against the reflow pad
   recommendation of the actual emitter you buy (PixArt names the P/N for the L0AJ-LSG1 set).
5. **Battery polarity** — JST PH has no standard; this design says pin 1 = BAT+. Verify the pigtail
   with a DMM. Use a protected cell.

*(Closed in v5.3: the old "enlarge LED cutout" item — now datasheet-exact — and the old "add
Kailh boss holes" item — investigated against official Omron/Kailh drawings; the switches have
flat bottoms and no boss holes exist to add.)*

## Firmware bring-up notes

- SPI mode 3, start ≤2 MHz (matches R23 = 3.3 k). Wake-from-shutdown needs RESET + 50 ms (tMOT-RST).
- Scroll decoding: nRF52833 **QDEC** peripheral on P0.08/P0.11; LED pin on P0.13 gates Q2 from VSYS.
- nRESET = P0.18 via UICR PSELRESET; DC/DC REG1 enabled (L fitted). Battery ADC: AIN0; drive
  P0.03 **high** to sample (Q1 pulls Q3's gate low → P-FET connects VBAT to the divider; adds
  ~103 µA through R25 + divider only while sampling). P0.03 low/high-Z = divider fully dead,
  AIN0 held at GND by R9 — true zero standby drain.

## Regenerating (reproducible build)

`tools/` contains the deterministic generators: `gen_kicad.py` (schematic), `pcb_gen.py` (board),
plus the checkers (`check_netlist.py`, `pcb_check.py`, `verify_pkg.py`, `drc_summary.py`). All
paths are **package-relative** as of v5.2 — no editing needed. Run with KiCad's bundled Python
(`C:\Program Files\KiCad\10.0\bin\python.exe`):

```
python tools/gen_kicad.py                                # rebuild schematic
kicad-cli sch export netlist --output build/net.net hakai_mouse_final.kicad_sch
python tools/pcb_gen.py                                  # rebuild board (reads build/net.net)
python tools/fill_zones.py                               # refill GND pours
python tools/check_netlist.py                            # netlist vs design intent
python tools/pcb_check.py                                # pad-by-pad PCB vs netlist audit
python tools/verify_pkg.py                               # containment/BOM/cost/inventory
```
