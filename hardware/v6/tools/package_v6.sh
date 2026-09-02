#!/usr/bin/env bash
# v6 packaging: gerbers, drill, zip, render, reports. Run after DRC is final.
set -e
cd "$(dirname "$0")/.."
KCLI="/c/Program Files/KiCad/10.0/bin/kicad-cli.exe"
PY="/c/Program Files/KiCad/10.0/bin/python.exe"

echo "=== gerbers ==="
rm -f gerbers/*
"$KCLI" pcb export gerbers --output gerbers/ \
  --layers F.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts \
  --subtract-soldermask hakai_mouse_v6.kicad_pcb
"$KCLI" pcb export drill --output gerbers/ --format excellon --drill-origin absolute \
  --excellon-separate-th hakai_mouse_v6.kicad_pcb
ls gerbers/ | wc -l

echo "=== zip ==="
rm -f GERBERS_hakai_v6_PROTO.zip
"$PY" - <<'EOF'
import zipfile, os
z=zipfile.ZipFile("GERBERS_hakai_v6_PROTO.zip","w",zipfile.ZIP_DEFLATED)
for f in sorted(os.listdir("gerbers")):
    z.write(os.path.join("gerbers",f), f)
z.close()
print("zip written:", os.path.getsize("GERBERS_hakai_v6_PROTO.zip"), "bytes")
EOF

echo "=== render ==="
"$KCLI" pcb render --output board_top_render.png --side top --quality high \
  --width 1600 --height 1200 hakai_mouse_v6.kicad_pcb || echo "render failed (non-fatal)"

echo "=== reports ==="
"$KCLI" sch erc --exit-code-violations --severity-error \
  --output verification/ERC_report.rpt hakai_mouse_v6.kicad_sch || true
"$KCLI" pcb drc --format report --output verification/DRC_report.rpt \
  hakai_mouse_v6.kicad_pcb || true
"$PY" tools/check_netlist.py > verification/netlist_crosscheck.txt
"$PY" tools/pcb_check.py 2>/dev/null | grep -vE 'memory leak' > verification/pad_audit.txt
cat verification/netlist_crosscheck.txt verification/pad_audit.txt

echo "=== verify_pkg ==="
"$PY" tools/verify_pkg.py 2>/dev/null | grep -vE 'memory leak'
echo "PACKAGING DONE"
