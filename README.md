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

### Fabrication status: READY

The saved zone fill is current. Verified with KiCad 10.0.5:

- DRC **without** `--refill-zones` (i.e. against the *stored* fill that gerber
  export actually plots): **0 violations, 0 unconnected**
- Ground pour clearance to the MH3 hole edge: **1.3964 mm (F.Cu) / 1.3974 mm
  (B.Cu)**, measured in the exported gerber
- Mounting-hole drill: 3x NPTH 3.2 mm, MH3 at `X155.0 Y-130.0`

Ready-to-send package: **`gerbers/fab_ready/`** - 9 gerbers, merged Excellon
drill (PTH + NPTH, MixedPlating), `.gbrjob`, and `FAB_NOTES.txt`.

> **Always re-fill zones before exporting gerbers.** Gerber export plots the
> *saved* fill, not a live one. If you edit routing, run `Edit > Fill All Zones`
> (B), confirm DRC is 0/0 with "Refill all zones" *unchecked*, then save and
> re-export. An earlier revision of this board shipped a stale fill in which the
> GND pour overlapped SWDIO and VBAT_SENSE at 0.0000 mm clearance.

### Known deviation - VBAT_SENSE under the RF feed

`VBAT_SENSE` on B.Cu crosses beneath `RF_FEED` on F.Cu, with the nearest plane
cut **~1.79 mm from the antenna feed pad ANT1.1** at (138.000, 140.000).
Crossing counts are unchanged from the pre-reroute baseline (2x RF_FEED, 2x ANT,
1x RF1, all broadside through the 0.8 mm dielectric), but the baseline's closest
cut was 8.83 mm out. Accepted for prototype. If return loss disappoints, look
here before touching the match component values.

## Excluded from version control

| Excluded | Size | Why |
|---|---|---|
| `archive/*.zip` | 163 MB + 64 MB | Self-archives of this tree; the 163 MB file exceeds GitHub's 100 MB hard limit |
| `**/tools/fr/*.jar` | 58 MB each | Freerouting - download from [freerouting/freerouting](https://github.com/freerouting/freerouting/releases) |
| `.history/` | - | VS Code Local History; contains nested git repos |
| `*.kicad_prl` | - | Per-user KiCad local settings |

`.gitattributes` sets `* -text` so git never rewrites line endings. Gerber and
drill files are checksum-verified; EOL conversion would silently corrupt them.
