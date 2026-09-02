# Hakai

Hardware, firmware-adjacent tooling and web assets for the Hakai mouse.

## Repository layout

```
hardware/            KiCad projects, one folder per design revision
  rev2/                Jul 2026  - hakai_mouse_rev2
  v5/                  Jul 2026  - hakai_mouse_v5
  final/               Jul 2026  - hakai_mouse_final
  v6/                  Jul 2026  - hakai_mouse_v6
  v6-final-v2/         Aug 2026  - hakai_mouse_v6   <-- CURRENT / authoritative
site/                Product site (static HTML + assets)
docs/                Design notes and schematic write-ups
tools/               Helper scripts (Blender MCP addon, etc.)
archive/             Local-only zip snapshots (not tracked - see .gitignore)
```

Revision order is chronological by board file date. **`hardware/v6-final-v2/` is
the authoritative design**; the other folders are kept for history and should not
be fabricated from.

## Current board: `hardware/v6-final-v2`

| | |
|---|---|
| Board            | 70.10 x 110.10 mm, 2 layer, 0.8 mm |
| Copper           | 1 oz (35 um) both outer layers |
| Min track / clearance | 0.10 mm / 0.072 mm (QFN courtyards only; 0.20 mm elsewhere) |
| Min drill        | 0.20 mm |
| Mounting holes   | 3x NPTH 3.2 mm at (114,72), (155,130), (160,74) |

### Assembly note - MH3

MH3 is the NPTH 3.2 mm hole at **(155.000, 130.000)**. The ground pour is held
back 1.40 mm from the hole edge by a dedicated keepout. **Fit a nylon or other
insulating washer / standoff at MH3** - do not use a bare metal washer.

### Known issue - zone fill must be refilled before fabrication

> The committed `hakai_mouse_v6.kicad_pcb` has a **stale saved zone fill**. It
> predates the SWDIO / VBAT_SENSE reroutes, so the stored GND pour overlaps
> those traces and intrudes into the MH3 keepout.
>
> - DRC **with** zone refill: 0 violations, 0 unconnected
> - DRC **without** refill (i.e. what gets plotted): **33 errors**, including
>   `0.0000 mm` clearance between the GND pour and SWDIO / VBAT_SENSE
>
> Gerber export plots the *saved* fill, so exporting without refilling first
> produces boards with SWDIO and VBAT_SENSE shorted to ground.
>
> **Before any fabrication export:** open the board, `Edit > Fill All Zones` (B),
> re-run DRC with "Refill all zones" *unchecked* and confirm 0/0, then save.

## Excluded from version control

| Excluded | Size | Why |
|---|---|---|
| `archive/*.zip` | 163 MB + 64 MB | Self-archives of this tree; the 163 MB file exceeds GitHub's 100 MB hard limit |
| `**/tools/fr/*.jar` | 58 MB each | Freerouting - download from [freerouting/freerouting](https://github.com/freerouting/freerouting/releases) |
| `.history/` | - | VS Code Local History; contains nested git repos |
| `*.kicad_prl` | - | Per-user KiCad local settings |

`.gitattributes` sets `* -text` so git never rewrites line endings. Gerber and
drill files are checksum-verified; EOL conversion would silently corrupt them.
