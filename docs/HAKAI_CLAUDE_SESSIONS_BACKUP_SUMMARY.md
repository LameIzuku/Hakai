# HAKAI / Claude Sessions — Full Backup Summary

**Created:** 2026-08-08  
**Source folder:** `C:\Users\kavya\Documents\hakai\claud`  
**Also present:** `C:\Users\kavya\Documents\hakai\claud-20260808T140241Z-1-001.zip` (zip archive of this tree)

> **Important note on “sessions”**  
> This folder is a **project artifact dump** from Claude-assisted work (KiCad packages, docs, web, Blender MCP), **not** Claude Code transcript logs.  
> - Local Claude config here: `.claude/settings.local.json`, `.claude/launch.json` only.  
> - No `~/.claude/projects` session transcripts were found on this machine.  
> Content below is reconstructed from READMEs, design docs, verification reports, BOM/cost CSVs, and package structure.

---

## 1. Project in one line

**HAKAI (aka HAKAI M1 / “HAKAI WRATH”)** — wireless gaming mouse PCB + product packaging:

| Item | Spec |
|------|------|
| MCU + radio | Nordic **nRF52833-QIAA** (aQFN73), integrated 2.4 GHz |
| Sensor | PixArt **PAW3311DB-T2MU** (12k CPI class), L0AJ lens stack |
| Switches | **5× Kailh GM 8.0** (L/R/side×2/middle) |
| Scroll | Split wheel: **EC1** 11 mm encoder + **SW5** Kailh middle-click |
| Power | USB-C charge-only → **BQ24074** → **XC6219 1.9 V** system rail + Li-ion |
| Board | 2-layer, **0.8 mm**, ~70×110 mm mouse-plate, PCB IFA antenna |
| Cost (est.) | ~**$18.39** parts / ~**$24.89** with battery |

---

## 2. What was previously done (task log by era)

### A. Rev 1.1 → Rev 2.0/2.1 — Schematic audit & redesign
**Artifact:** `HAKAI_Mouse_Rev2.0_Schematic_Design.md`, `hakai_mouse_rev2/`

| Done | Detail |
|------|--------|
| Prototype audit | 13 issues logged from Rev 1.1 (encoder/DEC name collision, XL1/XL2 misuse, USB-on-GPIO mistake, FSUSB42 deleted, BQ24074 TS/ILIM, VSYS vs VBAT naming, RF match wrong, etc.) |
| Power tree redesign | Single **1.9 V** rail (PAW3311 abs max 2.1 V); VSYS / VBAT / 1V9 / 1V9_A split |
| nRF52833 pin map | Conflict-free GPIO; Nordic DEC/DC-DC/RF copied from PS + PCA10100 |
| PAW3311 verified | Real datasheet v1.0: 3-wire SDIO + R1 bridge, VDDREG bypass-only, LED chain 18 Ω |
| KiCad schematic gen | ERC = 0; netlist machine-checked vs design doc |
| Custom footprints | PAW3311 iDIP-8, Kailh GM8/D2F, 11 mm encoder |
| BOM + cost estimate | Generated for rev2 package |

### B. Rev 4.x–5.0 — Shaped PCB placement (still unrouted)
**Artifact:** evolution inside `hakai_mouse_rev2/` README narrative

| Done | Detail |
|------|--------|
| Schematic layout cleanup (v3) | Cleaner sheet organization |
| Mouse-plate outline (v4.1) | U wheel bay 24×38 mm, chamfered corners, narrowed tail, USB-C at tail |
| Sensor cutouts | Aperture + LED cutouts per PixArt Table 9 |
| Mounting | 3× M3 holes; antenna copper-free tail zone |
| Pad electrical audit | 0 pad↔net mismatches vs schematic |
| Split scroll (Rev 5.0) | EC1 left bay wall + SW5 tact right bay wall (type B commercial style) |

### C. v5.1 — Switch unification
**Artifact:** `hakai_mouse_v5/`

| Done | Detail |
|------|--------|
| SW5 → Kailh GM 8.0 | Middle click same part as main buttons (BOM SW1–SW5 qty 5) |
| Full package | Sch/PCB unrouted, BOM, cost (~$17.72 / $24.22), verification suite |
| Generators | `tools/gen_kicad.py`, `pcb_gen.py`, netlist/pad checkers |

### D. v5.2–5.3 — “FINAL” mechanical + electrical hardening
**Artifact:** `final/` (`hakai_mouse_final.*`)

| Done | Detail |
|------|--------|
| v5.2 high-side battery sense | Q3 AO3401A + R25; nets `VBAT_SW` / `VBAT_SW_G`; C36 10 µF on BQ BAT |
| v5.3 sensor mechanicals | Datasheet-exact aperture/notch, LED stadium R0.90×2.00, 2× guide-post holes, Ø0.80 pins |
| Custom IR-LED footprint | Pads at Table 9 positions (not generic 1206) |
| Kailh footprint corrected | Flat bottom; Omron D2F pattern; **no boss holes** (investigated & closed) |
| R25 = 47 k | Doubled ADC off-state margin vs Q3 Vgs(th) |
| Placement/silk cleanup | TP row, SW4 edge, sensor clear zone, silk warnings 38 → 4 |
| Product datasheet PDF | `DATASHEET_hakai_mouse_final.pdf` |
| Cost | ~$18.39 parts / $24.89 w/ battery |
| State | **Placed + netted, deliberately unrouted** (143 ratsnest “errors” intentional) |

### E. v6.0 — Full routing + fab package
**Artifacts:** `v6/`, `final v2 (v6)/` (release-oriented twin; second also has `USAGE_MANUAL.md` + multi-angle renders)

| Done | Detail |
|------|--------|
| Full routing | **138** signal connections; Freerouting 2.2.4 + custom A*/finish scripts |
| Design rules | Netclasses + `hakai_mouse_v6.kicad_dru`; fine 0.10/0.075 mm in QFN |
| GND | Pour both layers, **280+** stitch vias, EP ground tie |
| Pin swaps (fab necessity) | BTN_RIGHT P0.05→**P1.02**; BTN_SIDE_BACK P0.06→**P1.04**; VBAT_EN P0.03→**P1.00** |
| Gerbers | `GERBERS_hakai_v6_PROTO.zip` + drill + job file |
| Verification | ERC 0; pad audit 306/0 mismatches; DRC 0 error-severity except **2 documented GND tongue hand-fixes** (C12-2, C19-2) |
| Usage manual | Bring-up, assembly order, pin map, hand-fix procedure, RF tune notes |
| Repro tools | Large `tools/` set: route/finish/zone/package scripts + freerouting jar |

### F. Marketing site + 3D assets
**Artifact:** `site/`

| Done | Detail |
|------|--------|
| Landing page | `index.html` — brand **HAKAI WRATH** |
| Buy page | `buy.html` |
| 3D preview | `preview.html` + `assets/hakai.obj` + PBR maps (diffuse, normal, roughness, metalness) |
| Product photos | front/back/left/top/etc. PNGs |
| Local server | `server.ps1` |
| v2 site | `site/v2/` (index + buy) |

### G. Blender MCP tooling
**Artifact:** `blender_mcp_addon.py` (~118 KB)

| Done | Detail |
|------|--------|
| Blender ↔ Claude MCP | Addon to connect Blender to Claude via MCP (BlenderMCP / Siddharth Ahuja lineage) |
| Purpose in this project | Likely shell/3D model iteration for the mouse (pairs with `site/assets`) |

### H. Claude project permissions (meta)
**Artifact:** `.claude/settings.local.json`

Allowed: WebSearch; fetch Nordic docs / GitHub; `artifact-design` skill.

---

## 3. Topics summarized separately

### Topic 1 — Electrical architecture
- **Why 1.9 V:** PAW3311 VDD/I/O abs max **2.1 V**; nRF runs 1.7–3.6 V → shared rail, no level shifters.  
- **Charger:** BQ24074 power-path; USB-C is **charge-only** (not full USB data on nRF USB pins).  
- **Rails:** VBUS 5 V → VSYS (OUT) / VBAT (cell) → PTC → 1.9 V LDO → ferrite → clean 1V9_A for MCU/sensor/RF.  
- **LED:** Blue status LED from **VSYS** via low-side AO3400A (1.9 V cannot light blue LED).  
- **Battery ADC:** High-side gated divider; sample only when VBAT_EN high (~103 µA); zero standby when off.  
- **Charge setpoints:** ~445 mA charge / ~497 mA input limit (ISET/ILIM resistors).

### Topic 2 — Sensor (PAW3311) & optics
- 8-pin staggered DIP, **3-wire SPI** (MISO direct, MOSI via R23 3.3 k @ ≤2 MHz start).  
- VDDREG pin: **bypass only** (never to MCU).  
- LED chain: 1V9 → 18 Ω → IR LED → pin 1 (internal 24 mA control).  
- PCB thickness **0.8 mm** for lens Z = 2.20–2.60 mm.  
- v5.3+ board features match PixArt Table 9 (L0AJ-LSG1): aperture, stadium LED cutout, guide posts.

### Topic 3 — MCU, RF, clocks
- HFXO 32 MHz + LFXO 32.768 kHz on dedicated pins.  
- DEC3 = **100 pF** (not 100 nF); DEC4+DEC6 tied; DC/DC 10 µH + 15 nH.  
- RF match Nordic-verbatim: 1.0 pF / 4.7 nH / 1.2 pF / 2.2 nH + C24 DNP tune.  
- Antenna: TI SWRA117D PCB IFA, copper-free tail; **VNA-tune after assemble**.

### Topic 4 — Mechanics / UI switches
- 5× Kailh GM 8.0; split scroll (encoder + separate middle Kailh).  
- Open U wheel bay; shell owns wheel/axle/cradle.  
- Encoder footprint generic 11 mm — **must match purchased vendor drawing**.  
- Kailh “boss holes” myth closed: flat bottom, no PCB boss holes.

### Topic 5 — PCB layout & manufacturing
- Evolved unrouted placement packages → fully routed v6.  
- 2-layer advanced prototype: 0.10 mm track / 0.075 mm clearance (QFN only).  
- aQFN-73 west-face escape forced **3 pin swaps** (firmware must match v6).  
- **Blocking fab issue:** 2 GND pour tongues (C12, C19) still need interactive hand-fix → then re-export gerbers.  
- Silk: 4 cosmetic warnings remaining.

### Topic 6 — Tooling / automation
- Deterministic Python generators for schematic + PCB (KiCad 10 bundled Python).  
- Checkers: netlist intent, pad audit, DRC summary, package verify.  
- Routing pipeline: Specctra DSN → Freerouting → SES import → hand finish scripts.  
- `package_v6.sh` regenerates gerbers/renders/reports.

### Topic 7 — Product / web / brand
- Branding **HAKAI WRATH** (“Break everything between you and the shot”).  
- Static marketing site + 3D OBJ preview assets.  
- Engineering datasheet PDFs in final/v6 packages.

### Topic 8 — What’s NOT done (open work)
1. **Close C12-2 / C19-2 GND hand-fixes** in KiCad; re-run DRC → unconnected = 0.  
2. Re-export `GERBERS_hakai_v6_PROTO.zip` after hand-fixes.  
3. Vendor-verify EC1 encoder + IR LED exact P/N pads + battery pigtail polarity.  
4. **Firmware** (nRF52) — pin map documented; no firmware tree in this folder.  
5. Shell/mechanical CAD beyond web 3D assets; assembly of first proto.  
6. VNA antenna tune (C24); regulatory/emissions later.  
7. Claude **chat transcripts** not archived here — only work products.

---

## 4. Version lineage (which folder to open)

| Folder | Role | Board state | Prefer for… |
|--------|------|-------------|-------------|
| `hakai_mouse_rev2/` | Early Rev 2–5.0 path | Unrouted | History / early netlist |
| `hakai_mouse_v5/` | v5.1 package | Unrouted | Mid history |
| `final/` | **v5.3 FINAL** placed package | Unrouted, mech-correct | Pre-route reference |
| `v6/` | **v6.0 routed** + routing archaeology | Routed + build intermediates | Deep routing debug |
| `final v2 (v6)/` | **v6.0 release-style** (+ USAGE_MANUAL, multi-renders) | Routed | **Best “ship” package to open** |
| `site/` | Marketing / 3D web | N/A | Landing page |
| `HAKAI_Mouse_Rev2.0_Schematic_Design.md` | Master electrical design prose | N/A | Why decisions exist |
| `blender_mcp_addon.py` | Blender MCP addon | N/A | 3D workflow |

**Recommended “current truth” for hardware:**  
`final v2 (v6)/` (or `v6/` if you need the full routing script history).

---

## 5. Firmware pin map (v6.0 — use this, not v5.3)

| Function | Pin | Notes |
|----------|-----|--------|
| BTN_LEFT | P0.04 | active-low |
| **BTN_RIGHT** | **P1.02** | swapped from P0.05 |
| **BTN_SIDE_BACK** | **P1.04** | swapped from P0.06 |
| BTN_SIDE_FWD | P0.07 | |
| ENC_A / ENC_B | P0.08 / P0.11 | QDEC |
| ENC_SW | P0.12 | SW5 |
| SPI SCK / MOSI / MISO | P0.20 / P0.22 / P0.24 | mode 3, ≤2 MHz start |
| SENS_NCS / MOTION | P0.17 / P0.19 | |
| LED_STAT | P0.13 | gates Q2 from VSYS |
| STAT / PGOOD | P0.14 / P0.15 | charger |
| **VBAT_EN** | **P1.00** | swapped from P0.03; drive HIGH to sample |
| VBAT_SENSE | P0.02 (AIN0) | |
| nRESET | P0.18 | UICR PSELRESET |
| SWD | J3 | **VTref = 1.9 V** |

---

## 6. Key file index (quick restore map)

```
claud/
├── HAKAI_CLAUDE_SESSIONS_BACKUP_SUMMARY.md   ← this file
├── HAKAI_Mouse_Rev2.0_Schematic_Design.md    ← electrical design bible
├── blender_mcp_addon.py
├── .claude/                                  ← permissions only (no transcripts)
├── hakai_mouse_rev2/                         ← early KiCad
├── hakai_mouse_v5/                           ← v5.1
├── final/                                    ← v5.3 unrouted “FINAL”
├── v6/                                       ← routed + tools + DSN/SES history
├── final v2 (v6)/                            ← best release package + USAGE_MANUAL
│   ├── hakai_mouse_v6.kicad_pro/sch/pcb
│   ├── GERBERS_hakai_v6_PROTO.zip
│   ├── BOM_ / Cost_Estimate_ / DATASHEET_
│   ├── USAGE_MANUAL.md
│   ├── verification/
│   └── tools/
└── site/                                     ← HAKAI WRATH web + 3D assets
```

---

## 7. Safest next actions (if continuing the project)

1. Open `final v2 (v6)/hakai_mouse_v6.kicad_pcb` in KiCad 8/9/10.  
2. Apply the two GND hand-fixes (USAGE_MANUAL §6); refill zones; DRC → 0 unconnected.  
3. Re-run `tools/package_v6.sh` (or KiCad plot) for fresh gerbers.  
4. Order **2-layer 0.8 mm advanced** PCB + top stencil; source BOM.  
5. Start nRF firmware using **v6 pin map**.  
6. Optional: drop final prototype project files here or beside this folder for a delta review against v6.

---

## 8. Uncertainty / caveats

- Summaries are from **artifacts**, not live chat logs — conversational intent (why certain experiments) may be incomplete.  
- `final/` vs `final v2 (v6)/` vs `v6/` may differ slightly in tooling noise; release docs agree on electrical intent of v6.  
- Dates on files (e.g. design md ~2026-07-04, DRC report 2026-07-12) mark the hardware sprint; this backup was written 2026-08-08.  
- Do not fab v6 gerbers until C12/C19 GND tongues are fixed and gerbers re-exported.

---

*End of backup summary.*
