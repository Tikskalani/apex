#!/usr/bin/env python3
"""
APEX regression suite.  Run from the project root:

    python tests/run_all.py

Requires python3. `r4_export` additionally requires node; it is skipped with a
warning if node is absent. `r7_e2e` needs pdfplumber and a PDF in tests/fixtures/;
it skips cleanly without either. Neither is a dependency of APEX itself.
"""
import subprocess, sys, os, shutil

HERE = os.path.dirname(os.path.abspath(__file__))

# Make our own stdout UTF-8-safe on legacy Windows consoles.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
PY_TESTS = ['r1_scorer', 'r2_protected', 'r3_loop', 'r5_ranking', 'r7_e2e', 'r8_weak', 'r10_final']
JS_TESTS = ['check_js_syntax', 'r4_export']

fails, skipped = [], []

# Windows consoles default to cp1252, which cannot encode the box-drawing and
# check characters the suites print. Force UTF-8 on both ends.
CHILD_ENV = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')

def run(cmd, name):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=HERE,
                           env=CHILD_ENV, encoding='utf-8', errors='replace')
    except subprocess.TimeoutExpired:
        print(f'{name:14} TIMEOUT'); fails.append(name); return
    out = (r.stdout or '').strip()
    err = (r.stderr or '').strip()
    last = out.splitlines()[-1] if out else ''
    if 'ALL PASS' in last:
        note = ' (skipped)' if 'SKIP' in out else ''
        print(f'{name:14} ALL PASS{note}')
        if note: skipped.append(name)
        return
    # Something went wrong - show enough to act on, not a wall of text.
    print(f'{name:14} FAIL')
    fails.append(name)
    for line in out.splitlines():
        if line.strip().startswith('FAIL'):
            print(f'                 {line.strip()}')
    if err:
        tail = err.splitlines()
        print(f'                 error: {tail[-1]}')
        for line in tail:
            if 'ModuleNotFoundError' in line or 'ImportError' in line:
                print(f'                 hint : pip install {line.split()[-1].strip(chr(39))}')
                break

for t in PY_TESTS:
    run([sys.executable, os.path.join(HERE, t + '.py')], t)

node = shutil.which('node')
for t in JS_TESTS:
    if not node:
        print(f'{t:14} SKIPPED (node not installed)'); skipped.append(t); continue
    run([node, os.path.join(HERE, t + '.js')], t)

print()
if fails:
    print(f'FAILING: {", ".join(fails)}')
    sys.exit(1)
print('ALL SUITES PASS' + (f'  ({len(skipped)} skipped: {", ".join(skipped)})' if skipped else ''))
