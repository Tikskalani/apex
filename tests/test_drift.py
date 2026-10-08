"""normalize_drift: model output -> safe, internally consistent drift result."""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import apex_store  # noqa: E402

# Load just normalize_drift from agent_server.py (importing the module would
# require config.json and start nothing useful).
_src = (ROOT / 'agent_server.py').read_text(encoding='utf-8')
_fn = next(n for n in ast.parse(_src).body if isinstance(n, ast.FunctionDef) and n.name == 'normalize_drift')
_ns = {'store': apex_store}
exec(compile(ast.Module(body=[_fn], type_ignores=[]), 'agent_server.py', 'exec'), _ns)
normalize_drift = _ns['normalize_drift']


def test_delta_is_computed_not_trusted():
    r = normalize_drift({'current_score': '71', 'drift': 999, 'urgency': 'high'}, 60)
    assert (r['current_score'], r['drift'], r['drifted']) == (71, 11, True)


def test_urgency_derived_when_missing_or_invalid():
    assert normalize_drift({'current_score': 45}, 60)['urgency'] == 'high'
    assert normalize_drift({'current_score': 58, 'urgency': 'URGENT!!'}, 60)['urgency'] == 'medium'
    assert normalize_drift({'current_score': 62.4}, 60) | {} == {
        'current_score': 62, 'baseline_score': 60, 'drift': 2, 'drifted': False,
        'new_keywords': [], 'faded_keywords': [], 'verdict': '', 'urgency': 'low'}


def test_lists_are_clamped_to_strings():
    r = normalize_drift({'current_score': 70, 'new_keywords': ['dbt', {'x': 1}, 3, None] + ['k'] * 30,
                         'faded_keywords': 'not a list'}, 70)
    assert r['new_keywords'][:3] == ['dbt', '3', 'k'] and len(r['new_keywords']) == 15
    assert r['faded_keywords'] == []


@pytest.mark.parametrize('bad', [{}, None, [], {'current_score': 'n/a'}])
def test_unusable_answers_raise(bad):
    with pytest.raises(Exception):
        normalize_drift(bad, 50)
