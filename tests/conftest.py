"""Shared fixtures for the unit tests.

`server` imports a COPY of agent_server.py from a temp dir with no config.json,
so unit tests can call its functions without ever reading the real keys or
starting anything (the server only starts under __main__)."""
import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope='session')
def server(tmp_path_factory):
    d = tmp_path_factory.mktemp('server_module')
    shutil.copy(ROOT / 'agent_server.py', d / 'agent_server.py')
    old = {k: os.environ.get(k) for k in ('APEX_DB', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'APEX_FIXTURE_JOBS')}
    os.environ['APEX_DB'] = str(d / 'apex.db')
    os.environ['APEX_FIXTURE_JOBS'] = str(ROOT / 'tests' / 'e2e' / 'fixtures' / 'jobs.json')
    for k in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        os.environ.pop(k, None)
    spec = importlib.util.spec_from_file_location('apex_server_under_test', d / 'agent_server.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.store.init()
    yield mod
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
