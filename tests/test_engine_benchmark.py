"""tools/benchmark.py helpers with a stub model: the chatbot gets the engine's brief, and the
independent fabrication audit is its own prompt and is reported next to the gate count."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import apex_engine as E  # noqa: E402

spec = importlib.util.spec_from_file_location('benchmark', ROOT / 'tools' / 'benchmark.py')
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)

TARGET = {'title': 'Senior Data Analyst', 'keywords': [{'name': 'SQL', 'pct': None}, {'name': 'Tableau', 'pct': None}],
          'supported': ['SQL'], 'unsupported': ['Tableau'], 'job_desc': 'Meridian Health posting POSTINGMARK'}


def test_chat_baseline_gets_the_same_brief():
    p = B.CHAT_PROMPT.format(title='Senior Data Analyst', brief=E._target_block(TARGET), resume='MY CV')
    assert p.startswith('Improve my resume for a Senior Data Analyst role')
    assert 'POSTINGMARK' in p and 'Tableau' in p and p.endswith('MY CV')


def test_fabrication_audit_is_independent_and_fails_soft():
    seen = []
    def llm(system, user, **_):
        seen.append(system)
        assert '<<<ORIGINAL' in user and '<<<REWRITE' in user
        return json.dumps({'unsupported': [{'claim': '35%', 'why': 'new number'}, {'claim': 'Snowflake'}]})
    assert B.fabrication_audit(E, llm, 'orig', 'new') == ['35%', 'Snowflake']
    assert seen == [B.FABRICATION_SYSTEM]
    assert seen[0] not in (E.VERIFY_SYSTEM, E.JUDGE_SYSTEM, E.DIAGNOSE_SYSTEM, E.REWRITE_SYSTEM, E.REPAIR_SYSTEM)
    assert B.fabrication_audit(E, lambda *a, **k: '{}', 'orig', 'new') is None, 'unreadable is not "0 invented"'


def test_report_shows_gate_and_audit_side_by_side():
    rec = lambda m, aud: {'model': m, 'final': 'x', 'error': None, 'invented': 2, 'audit_invented': aud,
                          'changes': 1, 'reverted': 0, 'cost_usd': 0.1, 'seconds': 3,
                          'judges': {'j': {'before': 40, 'after': 60}}}
    rep = B.summarize([rec('a', 5), rec('a', 1), rec('b', None)], ['a', 'b'], ['j'], 0.3)
    assert '| a | — | 60.0 | 20.0 | 4 | 6 | 2 | 0 |' in rep, rep
    assert '| b | — | 60.0 | 20.0 | 2 | — | 1 | 0 |' in rep, rep
    assert 'Invented claims (independent audit)' in rep


def test_invented_uses_the_gate_and_allows_a_created_summary_header():
    case = {'title': 'Senior Data Analyst', 'resume_text': 'JANE\nEXPERIENCE\n- Built SQL reports'}
    target = {'supported': ['SQL'], 'unsupported': ['Tableau']}
    assert B.invented(E, 'JANE\nSUMMARY\nData analyst.\nEXPERIENCE\n- Built SQL reports', case, target) == []
    assert B.invented(E, 'JANE\nEXPERIENCE\n- Built SQL reports in Tableau for 40 managers', case, target)
