"""apex_store: the pipeline database. Run: .venv\\Scripts\\python -m pytest tests/test_store.py"""
import sqlite3
import sys
import threading
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import apex_store as S   # noqa: E402


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_DB', str(tmp_path / 'apex.db'))
    S.init()


def mk(**kw):
    data = {'company': 'Meridian Health', 'role': 'Senior Data Analyst', **kw}
    return S.create_application(data)[0]


def test_create_defaults_and_history():
    a = mk(url='https://jobs.example.com/1')
    assert a['status'] == 'applied' and a['applied_on'] == date.today().isoformat()
    h = S.get_application(a['id'], with_history=True)
    assert [e['kind'] for e in h['events']] == ['created']


def test_saved_has_no_applied_date_until_it_moves():
    a = mk(status='saved')
    assert a['applied_on'] is None
    a = S.update_application(a['id'], {'status': 'applied'})
    assert a['applied_on'] == date.today().isoformat()


@pytest.mark.parametrize('bad,msg', [
    ({'company': ''}, 'company is required'),
    ({'role': '   '}, 'role is required'),
    ({'status': 'ghosted'}, 'status must be one of'),
    ({'url': 'javascript:alert(1)'}, 'url must start with http'),
    ({'applied_on': 'yesterday'}, 'applied_on must be a date'),
    ({'source': 'scraper'}, 'source must be one of'),
])
def test_validation_messages(bad, msg):
    with pytest.raises(S.StoreError, match=msg):
        S.create_application({'company': 'A', 'role': 'B', **bad})


def test_dedupe_is_case_and_space_insensitive():
    a, new1 = S.create_application({'company': 'Acme', 'role': 'Analyst', 'url': 'https://x.test/1'})
    b, new2 = S.create_application({'company': ' acme ', 'role': 'ANALYST', 'url': 'https://x.test/1'})
    assert new1 and not new2 and a['id'] == b['id']
    _, new3 = S.create_application({'company': 'Acme', 'role': 'Analyst', 'url': 'https://x.test/2'})
    assert new3, 'a different posting at the same company is a different application'


def test_concurrent_identical_creates_make_one_row():
    results = []
    def go():
        results.append(S.create_application({'company': 'Race', 'role': 'Cond', 'url': ''}))
    ts = [threading.Thread(target=go) for _ in range(8)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert len({r[0]['id'] for r in results}) == 1
    assert sum(1 for _, created in results if created) == 1
    assert len(S.list_applications()) == 1


def test_status_change_appends_event_and_rejects_unknown_fields():
    a = mk()
    S.update_application(a['id'], {'status': 'interview'})
    S.update_application(a['id'], {'status': 'offer', 'notes': 'Verbal offer 120k'})
    h = S.get_application(a['id'], with_history=True)
    statuses = [(e['detail']['frm'], e['detail']['to']) for e in h['events'] if e['kind'] == 'status']
    assert statuses == [('applied', 'interview'), ('interview', 'offer')]
    with pytest.raises(S.StoreError, match='cannot update: created_at'):
        S.update_application(a['id'], {'created_at': 'x'})


def test_update_into_duplicate_is_a_clear_error():
    mk(company='A', role='R')
    b = mk(company='B', role='R')
    with pytest.raises(S.StoreError, match='already has this company'):
        S.update_application(b['id'], {'company': 'a'})


def test_followup_due_logic():
    old = (date.today() - timedelta(days=S.FOLLOWUP_AFTER_DAYS)).isoformat()
    recent = date.today().isoformat()
    a = mk(company='Old', applied_on=old)
    b = mk(company='New', applied_on=recent)
    c = mk(company='Saved', status='saved')
    assert a['followup_due'] and not b['followup_due'] and not c['followup_due']
    a = S.record_followup_sent(a['id'])
    assert not a['followup_due'], 'sending a follow-up pushes the next one out'
    assert a['next_action_on'] == (date.today() + timedelta(days=S.FOLLOWUP_AFTER_DAYS)).isoformat()
    r = S.update_application(b['id'], {'status': 'rejected', 'next_action_on': old})
    assert not r['followup_due'], 'closed applications never need a follow-up'


def test_artifacts_kit_and_cascade_delete():
    a = mk()
    S.add_artifact(a['id'], 'tailored_resume', 'Marcus Delgado\nSQL')
    S.add_artifact(a['id'], 'cover_letter', 'Dear team')
    assert S.list_applications()[0]['artifact_count'] == 2
    with pytest.raises(S.StoreError, match='content is empty'):
        S.add_artifact(a['id'], 'cover_letter', '   ')
    with pytest.raises(S.StoreError, match='kind must be one of'):
        S.add_artifact(a['id'], 'virus', 'x')
    S.delete_application(a['id'])
    with sqlite3.connect(S.db_path()) as c:
        assert c.execute('SELECT count(*) FROM artifacts').fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM events').fetchone()[0] == 0
    with pytest.raises(S.StoreError, match='not found'):
        S.delete_application(a['id'])


def test_import_reports_duplicates_and_skips_bad_rows():
    items = [{'company': 'A', 'role': 'R', 'date': '2026-09-01', 'status': 'applied'},
             {'company': 'a', 'role': 'r', 'date': '2026-09-01'},
             {'company': '', 'role': 'R'},
             {'company': 'B', 'role': 'R', 'status': 'interview'}]
    r = S.import_applications(items)
    assert r['created'] == 2 and r['duplicates'] == 1
    assert r['skipped'] == [{'index': 2, 'error': 'company is required'}]
    assert {a['source'] for a in S.list_applications()} == {'import'}


def test_summary_counts():
    mk(company='A', status='saved'); mk(company='B'); mk(company='C', status='interview')
    mk(company='D', status='offer'); mk(company='E', status='rejected')
    s = S.summary()
    assert s['total'] == 5 and s['sent'] == 4 and s['response_rate'] == 50
    assert s['by_status']['saved'] == 1


def test_score_history_baseline():
    assert S.latest_score('Senior Data Analyst') is None
    S.record_score('Senior Data Analyst', 'general', 41, 78)
    S.record_score('senior data analyst', 'general', '55', 83.6)
    last = S.latest_score('SENIOR DATA ANALYST')
    assert (last['score_before'], last['score_after']) == (55, 84)
    with pytest.raises(S.StoreError):
        S.record_score('X', 'general', 1, 'n/a')
