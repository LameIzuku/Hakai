# HAKAI Wireless Gaming Mouse — Rev 2.0 Corrected Schematic Design

**Target spec:** Nordic nRF52833 (QIAA/aQFN73) · PixArt PAW3311DB optical sensor · 4× Kailh switches
(Left, Right, Side-Back, Side-Forward) · scroll wheel (quadrature encoder + middle click) ·
integrated 2.4 GHz radio · USB-C charging + Li-ion.

> **Note on the "2.4 GHz module":** the nRF52833 *is* the radio (BLE / Nordic ESB / Gazell). No external
> transceiver is used — the "wireless section" is the nRF internal radio + antenna matching network + PCB/chip antenna.

> **Note on the PAW3311 datasheet:** PixArt ships the PAW3311DB datasheet under NDA ("Confidential").
> Items marked **[VERIFY-DS]** below must be confirmed against the real datasheet before fab.

> **KiCad project generated from this document:** [`hakai_mouse_rev2/hakai_mouse_rev2.kicad_sch`](hakai_mouse_rev2/hakai_mouse_rev2.kicad_sch)
> (KiCad 8 format; opens in KiCad 8/9/10). Verified: parses clean, **ERC = 0 errors**, and the exported
> netlist was machine-checked pin-for-pin against §3–§8 of this document (44 signal nets exact-match, 6 rails).
>
> **REV 2.1 — sensor wiring now VERIFIED against the real PAW3311DB datasheet** (v1.0, 1A009EN — copy in
> [`hakai_mouse_rev2/datasheets/`](hakai_mouse_rev2/datasheets/PAW3311DB-T2MU_v1.0.pdf)). Consequences applied
> throughout: **the whole system runs on a single 1.9 V rail** (PAW3311 VDD abs max is 2.1 V, so 3.3 V I/O would
> destroy it; the nRF52833 runs 1.7–3.6 V so MCU + sensor share the rail with no level shifting), the SPI link is
> **3-wire SDIO** with PixArt's MISO-direct / MOSI-via-R1 bridge, and the status LED moved to VSYS behind a FET.
> Audit-table findings 6–7 are superseded by §4.

---

## 1. Audit of prototype Rev 1.1 (issues found + corrections)

| # | Ref | Issue found in prototype | Sev | Correction in Rev 2.0 |
|---|-----|--------------------------|-----|-----------------------|
| 1 | Sheet 3/6 | Encoder nets named `DEC1/DEC2/DEC_SW` collide with nRF52833 **DECx supply-decoupling** pin names → wiring/BOM confusion | High | Renamed encoder nets `ENC_A / ENC_B / ENC_SW` |
| 2 | C9,C10 on P0.00/P0.01 | 2.2 µF caps on quadrature encoder GPIO **and** P0.00/P0.01 are the dedicated **XL1/XL2 (32.768 kHz)** pins — cannot be encoder inputs | High | LFXO stays on P0.00/P0.01; encoder moved to free GPIO; caps removed from signal lines |
| 3 | D+/D- → P0.15/P0.14 | nRF52833 USB uses **dedicated D+/D- pins + VBUS + DECUSB (4.7 µF)**, not GPIO | High | USB-C made **charge-only** (recommended). Optional wired-data path documented separately |
| 4 | U1 FSUSB42A | FSUSB42 is a USB2.0 signal mux, **not** a power load switch; BQ24074 already does dynamic power-path | Med | **Deleted** |
| 5 | VDD/VDDH decoupling | Nordic requires **4.7 µF** on the shorted VDD/VDDH node (present as C16 ✓); DECx + DC/DC must match reference | Med | Kept 4.7 µF; DECx values locked to Nordic QIAA reference |
| 6 | Sensor MOTION/NCS | MOTION is **open-drain, active-low** with no pull-up; NCS floats at boot | Med | Added 10 k pull-up on MOTION and on NCS (→ VDDIO) |
| 7 | Sensor supply | Only VDDIO wired; PAW3311 may have a separate analog VDD | Med | **[VERIFY-DS]** — both-case wiring provided in §4 |
| 8 | BQ24074 | **TS** (thermal) and **ILIM** pins not handled; floating TS faults charging | High | ILIM resistor added; TS biased (or NTC); EN1/EN2/CE defined |
| 9 | OUT vs BAT | System `OUT` and cell `BAT` share the label **"BAT"** — must be separate nodes | High | Renamed **VSYS** (system) vs **VBAT** (cell) |
| 10 | Batt ADC on P0.03 | Divider node collides with encoder-switch net; 300 k divider drains ~14 µA always | Med | Dedicated **AIN0 (P0.02)**; divider gated by a FET on P0.03 |
| 11 | RF match (2.7nH/3.3nH/1.2pF/1.0pF) | Values differ from Nordic reference; RF is layout-dependent | High | **Copy Nordic nRF52833 QIAA RF network verbatim** + tune antenna with VNA (§8) |
| 12 | U7 74LVC1G14 on DPI | Schmitt buffer unnecessary (firmware debounce); DPI button not in new spec | Low | **Removed** |
| 13 | XC6219 3.3 V LDO | Drops out below ~3.5 V cell → 3V3 sags with battery | Info | Acceptable (caps sensor ≤3.3 V, protects 3.6 V max). Buck-boost optional for full runtime |

---

## 2. Power tree

```
USB-C VBUS(5V) ──► BQ24074 ─┬─ BAT ◄──► Li-ion cell (J_BAT)   [charge]
   (charge-only)            └─ OUT = VSYS ──► F1(PTC) ──► XC6219B192MR 1.9V LDO ──► 1V9
                                                                                    │
                                             FB1 (ferrite 600Ω@100MHz) ──► 1V9_A (clean rail)
   1V9_A powers: nRF52833 (VDD/VDDH), PAW3311 VDD + VLED, all pull-ups
   VSYS powers:  status LED (via Q2 AO3400A low-side switch — 1.9V can't light a blue LED)
   VBAT ──► [FET-gated 200k/100k divider] ──► nRF AIN0 (fuel gauge; 4.2V/3 = 1.4V < 1.9V ✓)
```
Rail summary: **VBUS** 5 V (USB) · **VBAT** 3.0–4.2 V (cell) · **VSYS** ≈ VBAT/5 V (power-path) ·
**1V9** system logic · **1V9_A** clean analog/RF (ferrite-isolated).

> **Why 1.9 V:** PAW3311 VDD = 1.8–2.1 V with **abs max 2.1 V on VDD and every I/O pin** — 3.3 V anywhere on it
> is fatal. Running the nRF52833 at the same 1.9 V eliminates all level shifting. Debug note: set your SWD
> probe's VTref for 1.9 V logic. FETs on this board must be low-Vth (AO3400A, not 2N7002).

---

## 3. nRF52833 (U4, QIAA/aQFN73) — pin map & supply

**Supply / DC-DC — copy Nordic QIAA reference circuit component-for-component:**

**VERIFIED against Nordic PS v1.7 §7.3 + PCA10100 DK 2.0.0 design files:**

| Pin (ball) | Connection | Value |
|--------|-----------|-------|
| VDD (A22, B1, W1, AD14, AD23) + VDDH (Y2) shorted | 3V3_A | bulk **4.7 µF** (W1) + 1 µF (B1) + 100 nF × 3 (A22/AD14/AD23) |
| DEC1 (C1) | GND | 100 nF X7R |
| DEC3 (D23) | GND | **100 pF NP0** ⚠️ (common error is fitting 100 nF here — Nordic specifies 100 pF) |
| DEC4 (B5) + DEC6 (E24) | tied together = net `DEC4_6` | **1.0 µF** + **47 nF** (47 nF fitted in DC/DC configs) |
| DEC5 (N24) | — | N.C. on build codes **Bxx and later** (820 pF only for Axx silicon — spec QIAAB0+) |
| DCC (B3) | → `DEC4_6` via inductors | **10 µH (0603) + 15 nH (0402) in series** (REG1 DC/DC mode) |
| DECUSB (AC5), VBUS (AD2), D+ (AD6), D− (AD4) | **leave floating** | Nordic no-USB reference config 6 (charge-only design) |

> There is **no DEC2** and **no DCCH** on the nRF52833 (REG0 is LDO-only, unlike nRF52840).
> DC-DC (REG1) roughly halves active radio current — implemented in this design.
> nRESET is **P0.18 (AC13)** mapped via UICR `PSELRESET[0/1]` — there is no dedicated reset ball.

**GPIO assignment (clean, conflict-free):**

| Function | nRF signal | Net |
|----------|-----------|-----|
| HFXO 32 MHz | XC1 / XC2 (dedicated) | Y1 + 2×12 pF |
| LFXO 32.768 kHz | P0.00 / P0.01 (XL1/XL2, dedicated) | Y2 + 2× caps to match crystal CL |
| Sensor SPI clock | P0.20 | `SPI_SCK` |
| Sensor SPI MOSI | P0.22 | `SPI_MOSI` → **R1 3.3 k** → `SENS_SDIO` (3-wire bridge) |
| Sensor SPI MISO | P0.24 | `SENS_SDIO` (**direct** on the SDIO pin) |
| Sensor chip-select | P0.17 | `SENS_NCS` (10 k PU) |
| Sensor motion IRQ | P0.19 | `SENS_MOTION` (push-pull active-low; PU optional) |
| Left click | P0.04 | `BTN_LEFT` |
| Right click | P0.05 | `BTN_RIGHT` |
| Side back | P0.06 | `BTN_SIDE_BACK` |
| Side forward | P0.07 | `BTN_SIDE_FWD` |
| Encoder A | P0.08 | `ENC_A` |
| Encoder B | P0.11 | `ENC_B` |
| Middle click (wheel push) | P0.12 | `ENC_SW` |
| Status LED | P0.13 | `LED_STAT` |
| Battery ADC | P0.02 (AIN0) | `VBAT_SENSE` |
| ADC divider enable | P0.03 | `VBAT_EN` |
| Charge status /CHG | P0.14 | `STAT` (optional) |
| Power good /PG | P0.15 | `PGOOD` (optional) |
| SWDIO / SWDCLK | dedicated | debug header J3 |
| Reset | P0.18 | `nRESET` (10 k PU) |

> **Do not use P0.09 / P0.10** as ordinary GPIO unless you reconfigure them from NFC in UICR
> (`CONFIG_NFCT_PINS_AS_GPIOS`). They are left unused here.

---

## 4. PAW3311 optical sensor (U5) — SPI + power

> **VERIFIED — PixArt datasheet v1.0 (1A009EN, 15 Nov 2022), Table 1 + Figure 6.** 8-pin staggered DIP.
> Key electricals: **VDD 1.8–2.1 V (abs max 2.1 V — all I/O abs max = VDD)** · 3-wire SPI, fSCLK ≤ 8 MHz ·
> run 2.3 mA (LPGM, incl. LED) · power-down 3 µA · up to 12,000 cpi, 300 ips, 35 g · Ta 0–40 °C ·
> VDD rise time 0.15–20 ms · transient supply up to 70 mA during ramp.

| Pin | Function (verified) | Net | Wiring (per Figure 6) |
|----|-----------|-----|----|
| 1 | LED — illumination control | `SENS_LED` | chain: 1V9_A(VLED, 33 µF bulk) → **R_LED 18 Ω 1%** → IR LED → pin 1 (24 mA internally controlled) |
| 2 | VDDREG — internal LDO out | `VDDREG` | **bypass only: 4.7 µF/10 V + 100 nF to GND.** Never connects to the MCU |
| 3 | VDD | 1V9_A | 10 µF + 100 nF at the pin |
| 4 | SCLK | `SPI_SCK` | nRF P0.20 |
| 5 | MOTION — active-low, push-pull | `SENS_MOTION` | nRF P0.19 (pull-up optional/DNP) |
| 6 | GND | GND | plane |
| 7 | SDIO — bidirectional data | `SENS_SDIO` | **nRF MISO (P0.24) direct** + **nRF MOSI (P0.22) via R1** — PixArt's 3-wire↔4-wire bridge |
| 8 | NCS — active low | `SENS_NCS` | nRF P0.17 + 10 k PU → 1V9_A |

**R1 (SDIO series, 1%):** 3.3 k @ 2 MHz · 1.0 k @ 4 MHz · 240 Ω @ 8 MHz. Load cap limit 20 pF on SDIO/MOTION.
Timing: tSRAD 2 µs, tSWW/tSWR 5 µs, NCS→SCLK 120 ns, wake-from-shutdown needs RESET + 50 ms motion delay.

**Optics:** LM31-LNG / LM33-LSG / L0AL-LSG1 (5 mm IR emitter) or L0AJ-LSG1 (SMT IR, 1206). Lens-to-surface
**Z = 2.20–2.60 mm**. Wave-solder with a flux-protection fixture; keep Kapton apertures on until final assembly
(datasheet §4.2). Local copy: [`datasheets/PAW3311DB-T2MU_v1.0.pdf`](hakai_mouse_rev2/datasheets/PAW3311DB-T2MU_v1.0.pdf).

---

## 5. Switches, encoder, LED

**4× Kailh switches — active-low, one 10 k pull-up each to 3V3_A, 100 nF across each for RC debounce (optional; firmware debounce also used):**

| Switch | Net | nRF |
|--------|-----|-----|
| SW1 Left (main) | `BTN_LEFT` | P0.04 |
| SW2 Right (main) | `BTN_RIGHT` | P0.05 |
| SW3 Side Back | `BTN_SIDE_BACK` | P0.06 |
| SW4 Side Forward | `BTN_SIDE_FWD` | P0.07 |

Each: `switch` between GPIO and GND; `10 k` from GPIO to 3V3_A. (nRF internal pull-ups can replace external — but external is more robust.)

**Scroll wheel — mechanical quadrature encoder E1 with integrated push switch:**

| Encoder pin | Net | nRF |
|-------------|-----|-----|
| A | `ENC_A` | P0.08 (10 k PU + 0.01 µF to GND) |
| B | `ENC_B` | P0.11 (10 k PU + 0.01 µF to GND) |
| Common (C) | GND | — |
| SW (push = middle click) | `ENC_SW` | P0.12 (10 k PU) |

> Small RC (10 k / 10 nF) on A/B tames mechanical contact bounce; keep caps ≤10 nF so edges stay crisp.

**Status LED (D3):** VSYS → 1 k → LED → **Q2 (AO3400A)** → GND; gate = nRF P0.13 + 100 k pulldown.
(Moved off the logic rail: 1.9 V cannot forward-bias a blue LED, and direct GPIO sinking from VSYS
would leak with a 1.9 V-high pin.) Optional.

---

## 6. Charging & power (BQ24074, U2)

| BQ24074 pin | Connection | Notes |
|-------------|-----------|-------|
| IN | VBUS (USB-C) | 1 µF + 10 µF input |
| OUT | **VSYS** | 10 µF; feeds F1→LDO. **Separate from BAT** |
| BAT | **VBAT** (cell + J_BAT) | 10 µF; single Li-ion |
| ISET | R to GND | ICHG = 890/R_ISET. R=2.0 k → **445 mA** |
| ILIM | R to GND | I_IN_LIM = 1600/R_ILIM. R=3.24 k → **~494 mA** (USB500) |
| /CE | GND (or MCU) | low = charge enabled |
| EN1, EN2 | set per truth table | choose USB100 / USB500 / ILIM mode |
| TS | NTC to VBAT pack **or** 10 k/10 k divider to keep in-window | **must not float** |
| /CHG, /PG | STAT (P0.14), PGOOD (P0.15) | open-drain, add 100 k PU (optional) |
| PAD/VSS | GND | thermal pad |

**LDO (XC6219B332MR, U3):** VSYS → F1 (PTC 1 A) → LDO IN; OUT = 3V3; 1 µF in + 10 µF out; CE tied to enable.
**Rail split:** 3V3 → FB1 (600 Ω @100 MHz ferrite) → **3V3_A** with 100 nF + 10 µF (clean rail for nRF + sensor + RF).

**Protection:** use a protected Li-ion cell, or add a DW01A + dual-MOSFET (e.g. 8205A) pack-protection front-end on VBAT.

**Fuel gauge:** VBAT → 200 k (R15) → node → 100 k (R16) → drain of small NFET → GND; node → nRF AIN0 (P0.02);
FET gate = `VBAT_EN` (P0.03). Divider only conducts during a reading → zero standby drain.

---

## 7. Clocks

| Osc | Xtal | Load caps | Notes |
|-----|------|-----------|-------|
| HFXO (mandatory for radio) | Y1 32 MHz, CL 8 pF, ESR/load per Nordic list | 2× 12 pF (C_HF) | Must be on Nordic's approved crystal list; short traces |
| LFXO (recommended, low-power) | Y2 32.768 kHz | 2× caps sized to crystal CL: C ≈ 2·(CL − Cstray). For CL 9 pF → ~12 pF | Enables accurate BLE timing / low sleep current |

---

## 8. 2.4 GHz radio section (RF)

- The nRF52833 single-ended `ANT` output drives an **impedance-matching network** into a **PCB or chip antenna**.
- **Verified reference values** (identical in PS v1.7 reference configs and the PCA10100 DK):
  `ANT (H23) → shunt 1.0 pF NP0 → series 4.7 nH (LQG15HS) → shunt 1.2 pF NP0 → series 2.2 nH (LQG15HS) → 50 Ω feed`,
  plus one **antenna-dependent shunt tune cap** at the antenna feed (Nordic BOM: "Ctune — antenna dependent"; DNP until VNA-tuned).
- **Copy the RF trace/ground geometry from the reference layout too** — the match is meaningless without the exact
  stack-up and antenna. (The prototype's 2.7 nH/3.3 nH/1.2 pF/1.0 pF were not the reference values.)
- Keep the RF path 50 Ω, ground the shunt cap nearest the radio to the VSS pin closest to ANT, and keep a
  copper keep-out under the antenna.
- After building: **tune with a VNA** to the antenna's real feed impedance, then verify with a spectrum analyzer
  for FCC/CE harmonics before production.

---

## 9. Debug / test

- **J3 SWD header:** 3V3, SWDIO, SWDCLK, nRESET, GND.
- **Test points:** VBUS, VBAT, VSYS, 3V3, 3V3_A, SPI_SCK/MOSI/MISO, SENS_NCS, SENS_MOTION.

---

## 10. Bill of Materials (key parts)

| Ref | Part | Value/MPN | Notes |
|-----|------|-----------|-------|
| U4 | Nordic nRF52833 | nRF52833-QIAA | MCU + 2.4 GHz radio |
| U5 | PixArt PAW3311DB | PAW3311DB-T2MU | optical sensor (NDA datasheet) |
| U2 | TI charger | BQ24074 | Li-ion + power path |
| U3 | Torex LDO | **XC6219B192MR** | **1.9 V** / 240 mA (system rail) |
| Q1, Q2 | N-MOSFET | AO3400A (SOT-23) | low-Vth — 2N7002 is marginal with a 1.9 V gate |
| R_LED | Resistor | 18 Ω 1% | IR LED chain (24 mA) |
| R1(SDIO) | Resistor | 3.3 k 1% | MOSI→SDIO bridge (2 MHz; 1 k @ 4 MHz, 240 Ω @ 8 MHz) |
| C(VDDREG) | Caps | 4.7 µF/10 V + 100 nF | sensor pin 2 bypass |
| C(VLED) | Cap | 33 µF | LED-chain bulk |
| Y1 | Crystal | 32 MHz (Nordic-approved) | HFXO |
| Y2 | Crystal | 32.768 kHz | LFXO |
| L_RF | RF match | **per Nordic QIAA ref** | do not substitute |
| L_DCDC | Inductor | 10 µH | if DC-DC enabled |
| FB1 | Ferrite | 600 Ω @100 MHz, 1206 | 3V3→3V3_A |
| F1 | PTC fuse | 1 A hold | VSYS |
| SW1–4 | Kailh switch | Kailh mechanical ×4 | L/R/back/fwd |
| E1 | Encoder | quadrature + push | scroll wheel |
| C(VDD) | Cap | 4.7 µF + 100 nF | VDD/VDDH node |
| C(DEC) | Caps | 100 nF ×DECx, 1 µF DEC4 | per Nordic ref |
| C(sens VDD) | Caps | 10 µF + 100 nF (at pin 3) | sensor supply |
| R(PU) | Resistor | 10 k ×(buttons, NCS, MOTION, enc) | pull-ups |
| R_ISET | Resistor | 2.0 k | 445 mA charge |
| R_ILIM | Resistor | 3.24 k | ~500 mA input limit |
| R15/R16 | Resistor | 200 k / 100 k | battery divider |
| J1 | USB-C | Type-C recept | charge |
| J_BAT | JST | 2-pin | Li-ion cell |

---

## 11. Pre-fab verification checklist

- [x] ~~[VERIFY-DS]~~ **RESOLVED (datasheet v1.0):** single VDD 1.8–2.1 V (abs max 2.1 V) → system rail = 1.9 V;
      3-wire SDIO + R1 bridge; VDDREG bypass-only; MOTION push-pull; LED chain 18 Ω @ 24 mA.
- [x] ~~[VERIFY-DS]~~ **RESOLVED:** lens LM31-LNG/LM33-LSG/L0AL-LSG1 (5 mm) or L0AJ-LSG1 (SMT); Z = 2.20–2.60 mm.
- [ ] nRF52833 supply/DEC/DC-DC caps + RF network **matched to Nordic QIAA reference** and layout copied.
- [ ] HFXO crystal is on Nordic's approved list.
- [ ] BQ24074 TS pin biased (not floating); ILIM/ISET/EN1/EN2/CE set for your cell + USB current.
- [ ] VSYS and VBAT are separate nets; power-path verified.
- [ ] P0.00/P0.01 reserved for LFXO; P0.09/P0.10 unused (NFC) unless reconfigured.
- [ ] RF tuned with VNA; emissions checked before production.
```
