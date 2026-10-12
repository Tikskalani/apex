import re, json, sys  # noqa: F401  (re-exported to the suites via `from harness import *`)
import os
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def load_core(path=None):
    """agent_server.py as a module, imported from a temp copy with no config.json
    (so no keys are read) and the server not started. Returns its namespace."""
    import importlib.util, shutil, tempfile
    d = tempfile.mkdtemp(prefix='apex_core_')
    shutil.copy(path or os.path.join(_ROOT, 'agent_server.py'), os.path.join(d, 'agent_server.py'))
    os.environ.setdefault('APEX_DB', os.path.join(d, 'apex.db'))
    for k in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        os.environ.pop(k, None)
    sys.path.insert(0, _ROOT)                     # apex_store, apex_engine
    spec = importlib.util.spec_from_file_location('apex_core_under_test', os.path.join(d, 'agent_server.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return vars(mod)
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
