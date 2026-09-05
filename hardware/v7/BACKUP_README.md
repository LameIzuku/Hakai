# hardware/v7 — verified backup of v6-final-v2

This folder is a **clean backup baseline** snapshotted from the authoritative
`hardware/v6-final-v2` design on 2026-09-05, intended as the known-good starting
point for v7 work.

## Provenance

- Source: `hardware/v6-final-v2` (post zone-refill, commit `f4a4303`).
- The board, schematic, project and design-rule files are **byte-identical**
  to the source (verified by md5):
  - `hakai_mouse_v6.kicad_pcb` `ef6cae138167fae931a2888cb496e27b`
  - `hakai_mouse_v6.kicad_sch` `a82c291d391a0ee4529c270a1239aa0a`
  - `hakai_mouse_v6.kicad_pro` `f43a0dc614b6ee6f405e117072e7e9cb`
  - `hakai_mouse_v6.kicad_dru` `3626556137801c12f24f7fc3aa7da435`
- Filenames are kept as `hakai_mouse_v6.*` so the KiCad project linkage stays
  intact; the `v7` folder denotes the revision slot, not a rename.

## Verified state

Re-checked on copy with `tools/verify_connectivity.py`:

- 51 / 51 multi-pad nets fully connected — no opens.
- GND: 80 pads in one copper island, tied by 205 segments + 306 vias across
  both F.Cu and B.Cu pours.
- 49 single-node nets are all intentional `unconnected-*` no-connects.

See `verification/CONNECTIVITY_report.md` for the full analysis.

## What was intentionally excluded from this baseline

To keep the snapshot lean and known-good, these were **not** copied from
v6-final-v2:

- Intermediate board snapshots (`*.kicad_pcb.bak_*`, `*.best_*`,
  `pcb_final_proto_backup.*`).
- `build/` routing scratch and DRC JSON iterations.
- Board render PNGs and the stale `FAB_BLOCKERS_*.jpg`.
- Superseded gerber zips and loose gerber exports — only the current
  `gerbers/fab_ready/` fabrication package is kept.

## Contents

- Core design: `hakai_mouse_v6.kicad_{pcb,sch,pro,dru}`, `fp-lib-table`,
  `footprints.pretty/`.
- Fabrication: `gerbers/fab_ready/` (9 gerbers + merged drill + job + fab notes).
- Docs: `README.md`, `USAGE_MANUAL.md`, `DATASHEET_*.pdf`,
  `hakai_mouse_v6_schematic.pdf`, `datasheets/`, `LOGS.txt`,
  `BOM_*.csv`, `Cost_Estimate_*.csv`.
- Verification: `verification/`, `tools/`.
