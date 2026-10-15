"""tools/feature_bench.py end to end against the offline stub."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT

pytest.importorskip('anthropic', reason='pip install -r requirements.txt')


def test_feature_bench_runs_every_feature_and_writes_a_report(tmp_path, fake_openai):
    for n in ('agent_server.py', 'apex_store.py', 'apex_engine.py', 'apex_domains.py', 'apex_apply.py', 'index.html'):
        shutil.copy(ROOT / n, tmp_path / n)
    (tmp_path / 'tools').mkdir()
    for n in ('benchmark.py', 'feature_bench.py'):
        shutil.copy(ROOT / 'tools' / n, tmp_path / 'tools' / n)
    cases = tmp_path / 'bench' / 'cases'
    cases.mkdir(parents=True)
    for n in ('devon_park.json', 'devon_park.txt'):
        shutil.copy(ROOT / 'bench' / 'cases' / n, cases / n)
    (tmp_path / 'config.json').write_text(json.dumps({'OPENAI_KEY': 'sk-stub'}))
    env = dict(os.environ, APEX_OPENAI_BASE=fake_openai.url, APEX_DB=str(tmp_path / 'apex.db'),
               APEX_FIXTURE_JOBS=str(ROOT / 'tests' / 'e2e' / 'fixtures' / 'jobs.json'), PYTHONIOENCODING='utf-8')
    run_dir = tmp_path / 'run'
    r = subprocess.run([sys.executable, 'tools/feature_bench.py', '--model', 'gpt-6.1-sol', '--judge', 'gpt-6.1-sol',
                        '--auditor', 'gpt-6.1-sol', '--cases', str(cases), '--budget', '1', '--workers', '2',
                        '--out', str(run_dir)], cwd=tmp_path, env=env, capture_output=True, text=True,
                       encoding='utf-8', timeout=600)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    results = json.loads((run_dir / 'results.json').read_text(encoding='utf-8'))
    assert {x['feature'] for x in results} == {'tailor', 'cover_letter', 'bullets', 'xray', 'match', 'bridge',
                                               'negotiate', 'followup', 'grade_answer'}
    for x in results:
        assert x['error'] is None, x
        assert x['apex'] and x['chat'] and x['outcome'] in ('apex', 'chat', 'tie')
    report = (run_dir / 'report.md').read_text(encoding='utf-8')
    assert 'APEX win-tie-loss' in report and '| cover_letter |' in report
    assert '### APEX' in (run_dir / 'outputs.md').read_text(encoding='utf-8')
