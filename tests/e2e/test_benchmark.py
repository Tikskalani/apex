"""tools/benchmark.py end to end against the offline stub (both providers)."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT

pytest.importorskip('anthropic', reason='pip install -r requirements.txt')


def test_benchmark_cross_judges_and_writes_a_blind_page(tmp_path, fake_openai):
    for n in ('agent_server.py', 'apex_store.py', 'apex_engine.py', 'apex_domains.py', 'apex_apply.py', 'index.html'):
        shutil.copy(ROOT / n, tmp_path / n)
    (tmp_path / 'tools').mkdir()
    shutil.copy(ROOT / 'tools' / 'benchmark.py', tmp_path / 'tools' / 'benchmark.py')
    cases = tmp_path / 'bench' / 'cases'
    cases.mkdir(parents=True)
    for n in ('marcus_delgado.json', 'marcus_delgado.txt'):
        shutil.copy(ROOT / 'bench' / 'cases' / n, cases / n)
    (tmp_path / 'config.json').write_text(json.dumps({'OPENAI_KEY': 'sk-stub', 'ANTHROPIC_KEY': 'sk-ant-stub'}))
    env = dict(os.environ, APEX_OPENAI_BASE=fake_openai.url, APEX_ANTHROPIC_BASE=fake_openai.url,
               APEX_DB=str(tmp_path / 'apex.db'), PYTHONIOENCODING='utf-8')
    run_dir = tmp_path / 'run'
    n0 = len(fake_openai.calls)
    r = subprocess.run([sys.executable, 'tools/benchmark.py', '--models', 'gpt-6.1-sol', 'claude-sonnet-5-5',
                        'chat:gpt-6.1-sol', '--judges', 'gpt-6.1-sol', 'claude-opus-5-5', '--cases', str(cases), '--budget', '1',
                        '--out', str(run_dir)], cwd=tmp_path, env=env, capture_output=True, text=True,
                       encoding='utf-8', timeout=300)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    report = (run_dir / 'report.md').read_text(encoding='utf-8')
    # APEX: nothing invented. The stub cannot do the independent audit ('{}' reply), so it shows '—', not 0.
    assert '| gpt-6.1-sol | 74.0 | 74.0 | 26.0 | 0 | — | 3 | 0 |' in report, report
    assert '| claude-sonnet-5-5 | 74.0 | 74.0 | 26.0 | 0 | — | 3 | 0 |' in report, report
    audits = [c for c in fake_openai.calls[n0:] if c['system'].startswith('You are an independent reference checker')]
    assert {c['model'] for c in audits} == {'gpt-6.1-sol'} and len(audits) == 3, 'one audit per output, first judge'
    chat = next(x for x in json.loads((run_dir / 'results.json').read_text(encoding='utf-8'))
                if x['model'] == 'chat:gpt-6.1-sol')
    ex = ' '.join(chat['invented_examples'])
    assert chat['invented'] >= 3 and '35' in ex and '40' in ex and 'Snowflake' in ex, chat['invented_examples']
    results = json.loads((run_dir / 'results.json').read_text(encoding='utf-8'))
    assert {(x['model'], j) for x in results for j in x['judges']} == {
        (m, j) for m in ('gpt-6.1-sol', 'claude-sonnet-5-5', 'chat:gpt-6.1-sol') for j in ('gpt-6.1-sol', 'claude-opus-5-5')}
    page = (run_dir / 'blind_review.html').read_text(encoding='utf-8')
    assert 'Version A' in page and 'Version B' in page
    assert 'gpt-6.1-sol' not in page and 'claude-sonnet' not in page, 'the blind page must not name models'
    rv = subprocess.run([sys.executable, 'tools/benchmark.py', '--reveal', str(run_dir)], cwd=tmp_path, env=env,
                        capture_output=True, text=True, encoding='utf-8')
    assert 'gpt-6.1-sol' in rv.stdout and 'claude-sonnet-5-5' in rv.stdout


def test_benchmark_stops_at_the_budget(tmp_path, fake_openai):
    """With a budget below one run's cost it runs once, then refuses to continue."""
    for n in ('agent_server.py', 'apex_store.py', 'apex_engine.py', 'apex_domains.py', 'apex_apply.py', 'index.html'):
        shutil.copy(ROOT / n, tmp_path / n)
    (tmp_path / 'tools').mkdir()
    shutil.copy(ROOT / 'tools' / 'benchmark.py', tmp_path / 'tools' / 'benchmark.py')
    cases = tmp_path / 'bench' / 'cases'
    cases.mkdir(parents=True)
    for n in ('marcus_delgado.json', 'marcus_delgado.txt', 'jordan_reyes.json', 'jordan_reyes.txt'):
        shutil.copy(ROOT / 'bench' / 'cases' / n, cases / n)
    (tmp_path / 'config.json').write_text(json.dumps({'OPENAI_KEY': 'sk-stub'}))
    env = dict(os.environ, APEX_OPENAI_BASE=fake_openai.url, APEX_DB=str(tmp_path / 'apex.db'), PYTHONIOENCODING='utf-8')
    r = subprocess.run([sys.executable, 'tools/benchmark.py', '--models', 'gpt-6.1-sol', '--judges', 'gpt-6.1-sol',
                        '--cases', str(cases), '--budget', '0.0001', '--out', str(tmp_path / 'run')],
                       cwd=tmp_path, env=env, capture_output=True, text=True, encoding='utf-8', timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    assert 'stopping: next run' in r.stdout
    assert len(json.loads((tmp_path / 'run' / 'results.json').read_text(encoding='utf-8'))) == 1
