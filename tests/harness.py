import re, json, sys
import os
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def load_core(path=None):
    path = path or os.path.join(_ROOT, 'agent_server.py')
    src = open(path, encoding='utf-8').read()
    core = src[src.index('# APEX v10 CORE'):src.index('# LINKEDIN OPTIMIZER')]
    ns = {'re': re, 'json': json, 'gpt': None, 'jparse': json.loads,
          'clean': lambda x: (x or '').strip(), 'LOOP_ITERS': 3}
    exec(core, ns)
    return ns
def pdf_text(p):
    """Only used by suites that read a fixture PDF. Imported lazily so the other
    suites run on a bare Python install."""
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError('pdfplumber not installed - this suite needs it; the app does not')
    with pdfplumber.open(p) as pdf:
        return '\n'.join(pg.extract_text() or '' for pg in pdf.pages)
FAILS = []
def check(name, cond, detail=''):
    if cond: print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}  {detail}"); FAILS.append(name)
def summary():
    print(f"\n{'ALL PASS' if not FAILS else str(len(FAILS))+' FAILURES: '+', '.join(FAILS)}")
    return len(FAILS)
