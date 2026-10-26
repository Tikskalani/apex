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
    assert a['status'] == 'applied' and a['applied_on'] == S._today()
    h = S.get_application(a['id'], with_history=True)
    assert [e['kind'] for e in h['events']] == ['created']


def test_saved_has_no_applied_date_until_it_moves():
    a = mk(status='saved')
    assert a['applied_on'] is None
    a = S.update_application(a['id'], {'status': 'applied'})
    assert a['applied_on'] == S._today()


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
    old = (date.fromisoformat(S._today()) - timedelta(days=S.FOLLOWUP_AFTER_DAYS)).isoformat()
    recent = S._today()
    a = mk(company='Old', applied_on=old)
    b = mk(company='New', applied_on=recent)
    c = mk(company='Saved', status='saved')
    assert a['followup_due'] and not b['followup_due'] and not c['followup_due']
    a = S.record_followup_sent(a['id'])
    assert not a['followup_due'], 'sending a follow-up pushes the next one out'
    assert a['next_action_on'] == (date.fromisoformat(S._today()) + timedelta(days=S.FOLLOWUP_AFTER_DAYS)).isoformat()
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


# ── owners (hosted demo: one visitor never sees another's data) ──────────────

def test_owners_are_isolated():
    a, _ = S.create_application({'company': 'Acme', 'role': 'Analyst'}, owner='alice')
    b, created = S.create_application({'company': 'Acme', 'role': 'Analyst'}, owner='bob')
    assert created and a['id'] != b['id'], 'dedupe is per owner'
    assert 'owner' not in a, 'owner id is internal and never returned'
    assert [x['id'] for x in S.list_applications(owner='alice')] == [a['id']]
    assert S.list_applications() == [], 'the local owner sees neither'
    for fn in (lambda: S.get_application(a['id'], owner='bob'),
               lambda: S.update_application(a['id'], {'status': 'offer'}, owner='bob'),
               lambda: S.add_artifact(a['id'], 'note', 'x', owner='bob'),
               lambda: S.record_followup_sent(a['id'], owner='bob'),
               lambda: S.delete_application(a['id'], owner='bob')):
        with pytest.raises(S.StoreError, match='application not found'):
            fn()
    assert S.get_application(a['id'], owner='alice')['status'] == 'applied', 'bob changed nothing'
    S.add_artifact(a['id'], 'note', 'hello', owner='alice')
    assert S.list_applications(owner='bob')[0]['artifact_count'] == 0
    assert S.summary(owner='bob')['total'] == 1


def test_scores_are_per_owner():
    S.record_score('Data Analyst', 'general', 40, 70, owner='alice')
    assert S.latest_score('Data Analyst', owner='bob') is None
    assert S.latest_score('Data Analyst', owner='alice')['score_after'] == 70
    assert 'owner' not in S.latest_score('Data Analyst', owner='alice')


def test_per_owner_cap(monkeypatch):
    monkeypatch.setattr(S, 'MAX_APPS_PER_OWNER', 2)
    S.create_application({'company': 'A', 'role': 'R'}, owner='x')
    S.create_application({'company': 'B', 'role': 'R'}, owner='x')
    with pytest.raises(S.StoreError, match='pipeline is full'):
        S.create_application({'company': 'C', 'role': 'R'}, owner='x')
    S.create_application({'company': 'C', 'role': 'R'}, owner='y')


def test_upgrades_a_database_created_before_owners(tmp_path, monkeypatch):
    old = tmp_path / 'old.db'
    with sqlite3.connect(old) as c:
        c.executescript("""
          CREATE TABLE applications (id TEXT PRIMARY KEY, company TEXT NOT NULL, role TEXT NOT NULL,
            url TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
            applied_on TEXT, next_action_on TEXT, notes TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
          CREATE UNIQUE INDEX applications_dedupe ON applications (lower(trim(company)), lower(trim(role)), url);
          CREATE TABLE score_history (id INTEGER PRIMARY KEY AUTOINCREMENT, job_title TEXT NOT NULL,
            sector TEXT NOT NULL DEFAULT 'general', score_before INTEGER, score_after INTEGER, created_at TEXT NOT NULL);
          INSERT INTO applications VALUES ('old1','Legacy Co','Analyst','','','interview','2026-09-01',NULL,'',
            'manual','2026-09-01T00:00:00+00:00','2026-09-01T00:00:00+00:00');
          INSERT INTO score_history (job_title, score_before, score_after, created_at) VALUES ('Analyst', 30, 60, 'x');
        """)
    monkeypatch.setenv('APEX_DB', str(old))
    S.init(); S.init()                                   # idempotent
    assert [a['company'] for a in S.list_applications()] == ['Legacy Co'], 'existing rows belong to the local user'
    assert S.latest_score('Analyst')['score_after'] == 60
    S.create_application({'company': 'Legacy Co', 'role': 'Analyst'}, owner='visitor')   # old global index is gone


def test_daily_spend_is_capped_atomically():
    assert S.try_spend('2026-10-08', 6, 10) and S.try_spend('2026-10-08', 4, 10)
    assert not S.try_spend('2026-10-08', 1, 10), 'at the cap'
    assert S.spent('2026-10-08') == 10 and S.spent('2026-10-09') == 0
    assert S.try_spend('2026-10-09', 1, 10), 'a new day starts fresh'
    results = []
    ts = [threading.Thread(target=lambda: results.append(S.try_spend('2026-10-10', 1, 5))) for _ in range(20)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert sum(results) == 5 and S.spent('2026-10-10') == 5


# ── v11: baselines, caps, maintenance ────────────────────────────────────────

def test_score_keeps_its_requirement_list_for_drift():
    S.record_score('Data Analyst', 'general', 40, 61, keywords=[{'name': 'SQL', 'pct': 71.6}, {'name': '', 'pct': 5}, 'junk'])
    last = S.latest_score('data analyst')
    assert last['score_after'] == 61 and last['keywords'] == [{'name': 'SQL', 'pct': 72}]


def test_score_history_is_trimmed_per_owner(monkeypatch):
    monkeypatch.setattr(S, 'MAX_SCORES_PER_OWNER', 3)
    for i in range(5):
        S.record_score(f'Role {i}', 'general', 1, i)
    assert S.latest_score('Role 4')['score_after'] == 4 and S.latest_score('Role 1') is None


def test_artifacts_per_application_are_capped(monkeypatch):
    monkeypatch.setattr(S, 'MAX_ARTIFACTS_PER_APP', 2)
    a = mk()
    S.add_artifact(a['id'], 'note', 'one')
    S.add_artifact(a['id'], 'note', 'two')
    with pytest.raises(S.StoreError, match='already has 2 saved documents'):
        S.add_artifact(a['id'], 'note', 'three')


def test_owner_storage_is_capped(monkeypatch):
    monkeypatch.setattr(S, 'MAX_OWNER_BYTES', 1000)
    a = mk()
    S.add_artifact(a['id'], 'note', 'x' * 900)
    with pytest.raises(S.StoreError, match='using all the space'):
        S.add_artifact(a['id'], 'note', 'y' * 200)
    with pytest.raises(S.StoreError, match='using all the space'):
        S.update_application(a['id'], {'notes': 'z' * 200})


def test_purge_removes_only_stale_hosted_owners():
    S.create_application({'company': 'Local', 'role': 'Mine'})                    # owner '' is never purged
    old = S.create_application({'company': 'Old', 'role': 'Visitor'}, owner='visitor-old')[0]
    S.create_application({'company': 'New', 'role': 'Visitor'}, owner='visitor-new')
    with S._db() as conn:
        conn.execute("UPDATE applications SET updated_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (old['id'],))
    assert S.purge_inactive_owners(30) == 1
    assert S.list_applications(owner='visitor-old') == []
    assert len(S.list_applications(owner='visitor-new')) == 1 and len(S.list_applications()) == 1


def test_ping_and_connections_are_closed(tmp_path, monkeypatch):
    S.ping()
    mk()
    S.list_applications()
    # On Windows an open sqlite connection keeps the file locked: removing it
    # proves every connection was closed, not just committed.
    import gc, os
    gc.collect()
    for suffix in ('', '-wal', '-shm'):
        p = str(tmp_path / 'apex.db') + suffix
        if os.path.exists(p):
            os.remove(p)


def test_owner_storage_cap_also_covers_new_applications(monkeypatch):
    monkeypatch.setattr(S, 'MAX_OWNER_BYTES', 1000)
    S.create_application({'company': 'A', 'role': 'R', 'notes': 'x' * 900})
    with pytest.raises(S.StoreError, match='using all the space'):
        S.create_application({'company': 'B', 'role': 'R', 'notes': 'y' * 200})


def test_profile_tier_and_base_resume_round_trip():
    p = S.save_profile({'name': 'Me', 'targets': 'AI Engineer', 'base_resume': 'SUMMARY\nx'})
    assert p['tier'] == 'economy' and p['base_tailored'] == '' and p['base_key'] == ''
    p = S.save_profile({'id': p['id'], 'name': 'Me', 'targets': 'AI Engineer', 'base_resume': 'SUMMARY\nx', 'tier': 'best'})
    assert p['tier'] == 'best'
    p = S.save_profile({'id': p['id'], 'name': 'Me', 'tier': 'platinum'})
    assert p['tier'] == 'economy', 'an unknown tier falls back to economy'
    S.set_profile_base(p['id'], 'k1', 'SUMMARY\noptimized')
    p = S.get_profile(p['id'])
    assert (p['base_key'], p['base_tailored']) == ('k1', 'SUMMARY\noptimized')
    S.set_profile_base(p['id'], 'k1', 'nope', owner='someone-else')
    assert S.get_profile(p['id'])['base_tailored'] == 'SUMMARY\noptimized', 'owner-scoped'


def test_kit_costs_are_the_measured_spend_of_ready_and_applied_kits():
    p = S.save_profile({'name': 'Me', 'targets': 'AI Engineer'})
    assert S.add_queue_items(p['id'], [{'title': f'Job {i}', 'company': 'Acme', 'url': f'https://x.example/{i}',
                                        'posting': 'p', 'fit': 50 - i, 'reasons': {}} for i in range(4)]) == 4
    ids = [i['id'] for i in sorted(S.list_queue(p['id']), key=lambda i: -i['fit'])]
    S.update_queue_item(ids[0], status='ready', kit={'cost_usd': 0.07})
    S.update_queue_item(ids[1], status='applied', kit={'cost_usd': 0.09})
    S.update_queue_item(ids[2], status='failed', kit={'cost_usd': 0.5})
    S.update_queue_item(ids[3], status='ready', kit={'resume': 'no cost recorded'})
    assert sorted(S.kit_costs(p['id'])) == [0.07, 0.09]
    assert S.kit_costs(p['id'], owner='other') == []
    S.update_queue_item(ids[3], posting='the posting text, fetched later')
    assert S.get_queue_item(ids[3])['posting'] == 'the posting text, fetched later'
