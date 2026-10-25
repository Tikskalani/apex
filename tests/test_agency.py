"""Agency-grade controls: the audit record of what was sent, review before submit, the quality bar,
the activity log and the client report."""
import json

import pytest


@pytest.fixture
def db(server, tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_DB', str(tmp_path / 'a.db'))
    server.store.init()
    return server.store


def _ready_item(st, pid, company, fit, score_before=60, score_after=70, attempt=None):
    st.add_queue_items(pid, [{'title': 'AI Engineer', 'company': company, 'url': f'https://jobs.ashbyhq.com/{company.lower()}/1',
                              'posting': 'p' * 700, 'fit': fit, 'reasons': {}}])
    i = next(x for x in st.list_queue(pid) if x['company'] == company)
    kit = {'resume': 'r', 'cover_letter': 'c', 'struct': {'name': 'Jo Rivera'}, 'score_before': score_before, 'score_after': score_after}
    if attempt:
        kit['attempt'] = attempt
    st.update_queue_item(i['id'], status='ready', kit=kit)
    return i['id']


def test_quality_bar_and_review_mode_in_the_autopilot(server, db, monkeypatch):
    st = db
    pid = st.save_profile({'name': 'Me', 'targets': 'AI Engineer', 'base_resume': 'x' * 200, 'auto_submit': True, 'auto_prepare': 5,
                           'min_fit_submit': 60, 'review_first': True})['id']
    good = _ready_item(st, pid, 'Good', 80)
    _ready_item(st, pid, 'Low', 45)
    _ready_item(st, pid, 'Worse', 85, score_before=70, score_after=50)
    calls = []
    monkeypatch.setattr(server, 'agent_submit', lambda qid, owner='', **kw: calls.append((qid, kw)) or {'status': 'filled'})
    monkeypatch.setattr(server, 'submitted_today', lambda *a, **k: 0, raising=False)
    server.agent_autosubmit()
    assert [c[0] for c in calls] == [good] and calls[0][1] == {'do_submit': False}, 'only the job above the bar, and only filled (review mode)'
    att = {i['company']: ((i['kit'] or {}).get('attempt') or {}) for i in st.list_queue(pid)}
    assert att['Low']['status'] == 'below_bar' and 'under your bar of 60' in att['Low']['detail']
    assert att['Worse']['status'] == 'below_bar' and 'below the original' in att['Worse']['detail']
    assert server.below_bar({'fit': 90, 'kit': {}}, 55) == ''


def test_submit_now_falls_back_to_a_full_apply_when_nothing_is_filled(server, db, monkeypatch):
    st = db
    pid = st.save_profile({'name': 'Me', 'targets': 'AI Engineer', 'base_resume': 'x' * 200})['id']
    qid = _ready_item(st, pid, 'Acme', 80)
    monkeypatch.setattr(server, 'agent_submit', lambda q, owner='', **kw: {'status': 'submitted', 'via': 'full', **kw})
    assert server.agent_submit_now(qid)['via'] == 'full'
    qid2 = _ready_item(st, pid, 'Beta', 80, attempt={'status': 'filled', 'url_final': 'https://jobs.ashbyhq.com/beta/1/application', 'record': {'Email': 'jo@x'}})
    monkeypatch.setattr(server.apex_apply, 'submit_open', lambda url, shot: ({'status': 'submitted', 'detail': 'Thank you for applying!', 'url': url, 'missing': []}, ''))
    monkeypatch.setattr(server, 'agent_mark_applied', lambda q, owner='': st.create_application({'company': 'Beta', 'role': 'AI Engineer', 'status': 'applied'})[0])
    r = server.agent_submit_now(qid2)
    assert r['status'] == 'submitted' and r['application_id']
    app = st.get_application(r['application_id'], with_history=True)
    rec = next(x for x in app['artifacts'] if x['kind'] == 'submission_record')
    assert json.loads(rec['content'])['answers'] == {'Email': 'jo@x'}
    assert ((st.get_queue_item(qid2)['kit'] or {}).get('submission') or {}).get('record') == {'Email': 'jo@x'}
    with pytest.raises(st.StoreError):
        server.agent_submit_now('nope')


def test_activity_log_and_client_report(server, db, monkeypatch):
    st = db
    pid = st.save_profile({'name': 'Dana', 'targets': 'AI Engineer', 'base_resume': 'x' * 200})['id']
    monkeypatch.setattr(server, '_local_today', lambda: '2026-10-25')
    a, _ = st.create_application({'company': 'Acme', 'role': 'AI Engineer', 'status': 'applied', 'applied_on': '2026-10-22'})
    st.update_application(a['id'], {'status': 'interview'})
    st.record_followup_sent(a['id'], by='apex', to='rec@acme.com')
    _ready_item(st, pid, 'Held', 40, attempt={'status': 'below_bar', 'detail': 'fit 40 is under your bar of 55', 'at': '2026-10-25 08:00'})
    sub_ = _ready_item(st, pid, 'Sent', 80)
    kit = dict(st.get_queue_item(sub_)['kit'], submission={'status': 'submitted', 'at': '2026-10-25 07:30', 'detail': 'Thanks for applying', 'record': {}})
    st.update_queue_item(sub_, status='applied', kit=kit, application_id=a['id'])
    act = server.agent_activity(pid=pid)
    kinds = [x['kind'] for x in act]
    assert 'submitted' in kinds and 'below_bar' in kinds and 'followup_sent' in kinds and 'status' in kinds
    assert act == sorted(act, key=lambda x: x['at'], reverse=True)
    d = server.client_report_data(pid=pid)
    assert d['client'] == 'Me' and d['profile'] == 'Dana' and d['submitted'][0]['company'] == 'Acme' and d['submitted'][0]['how'] == 'APEX'
    assert d['replies'][0]['to'] == 'interview' and d['followups'][0]['by'] == 'apex' and d['needs'][0]['company'] == 'Held'
    html = server.client_report_html(pid=pid)
    assert 'job search report' in html and 'Acme' in html and 'Held' in html and 'Waiting on the client' in html
    with pytest.raises(st.StoreError):
        server.client_report_data(pid='nope')
