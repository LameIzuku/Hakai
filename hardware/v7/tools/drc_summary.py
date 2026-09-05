import os
import re
import sys

rpt = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "verification", "DRC_report.rpt")
lines = open(rpt, encoding='utf-8').read().splitlines()

entries = []   # (kind, severity, detail_lines)
cur = None
for ln in lines:
    m = re.match(r'^\[(\w+)\]: (.*)', ln)
    if m:
        cur = [m.group(1), '', [m.group(2)]]
        entries.append(cur)
    elif cur is not None and ln.strip():
        if re.search(r';\s*(error|warning)', ln):
            cur[1] = 'error' if 'error' in ln else 'warning'
        cur[2].append(ln.strip())
    if ln.startswith('**'):
        cur = None

errors = [e for e in entries if e[1] == 'error' and e[0] != 'unconnected_items']
warns = [e for e in entries if e[1] == 'warning' and e[0] != 'unconnected_items']
print(f"errors: {len(errors)}, warnings: {len(warns)} (excl. ratsnest)")
for kind, sev, det in errors:
    print(f"\n[{kind}] {det[0]}")
    for d in det[1:4]:
        print("   ", d)
