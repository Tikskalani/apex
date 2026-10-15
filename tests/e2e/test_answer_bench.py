"""tools/answer_bench.py end to end against the offline stub."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT

pytest.importorskip('anthropic', reason='pip install -r requirements.txt')


def test_answer_bench_runs_the_loop_and_writes_a_report(tmp_path, fake_openai):
    for n in ('agent_server.py', 'apex_store.py', 'apex_engine.py', 'apex_domains.py', 'index.html'):
        shutil.copy(ROOT / n, tmp_path / n)
    (tmp_path / 'tools').mkdir()
    for n in ('benchmark.py', 'answer_bench.py'):
        shutil.copy(ROOT / 'tools' / n, tmp_path / 'tools' / n)
    cases = tmp_path / 'bench' / 'cases'
    cases.mkdir(parents=True)
    for n in ('devon_park.json', 'devon_park.txt', 'marcus_delgado.json', 'marcus_delgado.txt'):
        shutil.copy(ROOT / 'bench' / 'cases' / n, cases / n)
    (tmp_path / 'config.json').write_text(json.dumps({'OPENAI_KEY': 'sk-stub'}))
    env = dict(os.environ, APEX_OPENAI_BASE=fake_openai.url, APEX_DB=str(tmp_path / 'apex.db'), PYTHONIOENCODING='utf-8')
    r = subprocess.run([sys.executable, 'tools/answer_bench.py', '--model', 'gpt-6.1-sol', '--candidate', 'gpt-6.1-sol',
                        '--auditor', 'gpt-6.1-sol', '--cases', str(cases), '--budget', '1', '--out', str(tmp_path / 'run')],
                       cwd=tmp_path, env=env, capture_output=True, text=True, encoding='utf-8', timeout=600)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    results = json.loads((tmp_path / 'run' / 'results.json').read_text(encoding='utf-8'))
    assert [x['case'] for x in results] == ['devon_park'], 'only cases with hidden facts run'
    assert 'error' not in results[0], results[0]
    assert results[0]['first_final'] and results[0]['answered_final']
    assert '| devon_park |' in (tmp_path / 'run' / 'report.md').read_text(encoding='utf-8')
