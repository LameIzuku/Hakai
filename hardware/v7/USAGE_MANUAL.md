# HAKAI M1 Wireless Gaming Mouse — v6.0 Usage & Bring-Up Manual

This is the practical companion to `README.md` (release notes) and
`DATASHEET_hakai_mouse_v6.pdf` (product-level specs). Read the README's
**pin-swap** and **hand-fix** sections before doing anything else.

---

## 1. BEFORE ORDERING BOARDS — mandatory checklist

1. **Close the two documented GND hand-fixes** (C12-2 and C19-2 pour tongues)
   in KiCad interactively — see §6. The board must show
   `unconnected = 0` in DRC afterwards. **Do not fab before this.**
2. Order class: **2-layer, 0.8 mm thickness** (non-negotiable — sensor lens
   stack), 1 oz copper. Capability needed: 0.10 mm track / 0.075 mm spacing
   (QFN courtyards only), 0.20 mm min drill, 0.20 mm hole-to-copper.
   That is "advanced" prototype class at JLCPCB/PCBWay — confirm 3.5 mil.
3. Upload `GERBERS_hakai_v6_PROTO.zip` — but ONLY after re-exporting it from
   the hand-fixed board (`bash tools/package_v6.sh` regenerates everything).
4. Solder stencil: order for **F.Paste** (top only; bottom has no parts).

## 2. Sourcing highlights (full list in `BOM_hakai_mouse_v6.csv`)

- U4 nRF52833-QIAA (build code Bxx+), U5 PixArt PAW3311DB-T2MU + **L0AJ-LSG1
  lens set** (SMT IR emitter — confirm D2's pads vs the emitter you buy),
  U2 BQ24074RGTR, U3 XC6219B192MR (1.9 V!).
- 5× Kailh GM 8.0 (SW1–SW5), EC1 = 11 mm rotation-only mouse encoder
  (verify drawing vs the generic footprint), J2 JST PH battery (pin 1 = BAT+
  **this design's convention — verify pigtail with a DMM**), USB-C 16-pin.
- Estimated cost: **$18.39 parts / $21.39 assembled proto / $24.89 w/ battery**
  (`Cost_Estimate_hakai_mouse_v6.csv`).

## 3. Assembly order & notes

1. Reflow top side (single-sided assembly). The nRF EP and BQ24074 EP need
   good paste coverage; the EP ground via at (155.40, 100.05) is intentional.
2. Hand-fit afterwards: SW1–SW5, EC1, J3 header, JST battery lead.
3. **Sensor stack**: fit the L0AJ lens through the two guide-post holes
   (self-aligning, can be heat-staked), PCB thickness 0.8 mm gives the
   2.2–2.6 mm lens-to-surface height. Keep the aperture area clean.
4. Battery: 3.7 V LiPo, **protected cell**, JST PH. Double-check polarity.

## 4. First power-on

1. Bench supply or battery; check 1V9 rail = 1.90 V ±3% (TP row / C5).
2. USB-C in: BQ24074 PGOOD (via nRF P0.15) low, charge LED logic on P0.14;
   charge current set 445 mA, input limit 497 mA.
3. SWD debug on J3 (1×05: 1V9, SWDIO, SWDCLK, nRESET, GND) — **set the
   probe VTref to 1.9 V**; nRESET is P0.18 via UICR PSELRESET.

## 5. Firmware pin map (v6.0 — note the three swaps!)

| Function | Pin | Notes |
|---|---|---|
| BTN_LEFT | P0.04 | active-low, 10 k pull-up |
| **BTN_RIGHT** | **P1.02** | was P0.05 in v5.3 |
| **BTN_SIDE_BACK** | **P1.04** | was P0.06 |
| BTN_SIDE_FWD | P0.07 | |
| ENC_A / ENC_B | P0.08 / P0.11 | nRF QDEC peripheral |
| ENC_SW (middle) | P0.12 | SW5 Kailh |
| SPI SCK / MOSI / MISO | P0.20 / P0.22 / P0.24 | 3-wire SDIO bridge (R23 3.3 k), mode 3, start ≤2 MHz |
| SENS_NCS / MOTION | P0.17 / P0.19 | MOTION push-pull active-low |
| LED_STAT | P0.13 | drives Q2 from VSYS (blue LED) |
| STAT / PGOOD | P0.14 / P0.15 | charger status, active-low |
| **VBAT_EN** | **P1.00** | was P0.03. Drive HIGH to sample battery |
| VBAT_SENSE | P0.02 / AIN0 | VBAT ÷3 (200 k/100 k), ~103 µA only while sampling |

Sensor wake-from-shutdown needs RESET + 50 ms (t_MOT-RST). DC/DC is fitted
(L1/L2) — enable REG1 DC/DC in firmware for radio efficiency.

## 6. The two hand-fixes (do these first — ~5 min each in KiCad)

Open `hakai_mouse_v6.kicad_pcb`, run DRC — you'll see 2 unconnected items:

- **C12-2** (47 nF, DEC4_6 bypass, near x=148, y=109.5): the GND tongue is
  boxed in by STAT's B.Cu horizontal (y≈108.6) and BTN_SIDE_BACK's pair
  (y≈109.10/109.55). Push-shove (hotkey `X`, walk into the STAT track) the
  STAT run ~0.4 mm north OR the BS-BACK pair south, then drop a GND via
  (0.45/0.20) in the freed band and let the zones refill.
- **C19-2** (12 pF, XC2 crystal load, near x=152.5, y=118.5): an XL2-area
  B.Cu diagonal crosses under the pad. Shove it ~0.3 mm SW and drop a GND
  via in the tongue, or drag a 0.15 mm GND track from the pad south-east to
  the via at (153.5, 122.5).

Refill zones (`B`), re-run DRC → expect **unconnected 0, errors 0** (4 silk
warnings are known-cosmetic). Then re-export fab files:
`bash tools/package_v6.sh`.

## 7. RF / antenna

The 2.4 GHz IFA and its feed keep Nordic's PCA10100 geometry; the tail zone
is copper-free on both layers. After assembly, measure with a VNA and fit
**C24** (DNP placeholder) to tune; typical starting value 1.2 pF.

## 8. Regenerating anything

All tools run with KiCad 10's bundled Python
(`"C:\Program Files\KiCad\10.0\bin\python.exe"`), paths package-relative:

```
python tools/gen_kicad.py            # schematic (rev 6.0, pin swaps included)
kicad-cli sch export netlist --output build/net.net hakai_mouse_v6.kicad_sch
python tools/check_netlist.py        # netlist vs design intent (45+6 nets)
python tools/pcb_check.py            # pad-by-pad audit vs netlist
python tools/verify_pkg.py           # containment/BOM/cost/inventory
bash   tools/package_v6.sh           # gerbers + drill + zip + render + reports
```

Routing archaeology (Freerouting jar, DSN/SES flow, repair scripts) is in
`tools/` — see README §"How it was routed".
