"""Recruiter contacts, the follow-up autopilot, the morning digest and search-health analytics."""

import pytest


@pytest.fixture
def db(server, tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_DB', str(tmp_path / 'f.db'))
    server.store.init()
    return server.store


def test_contact_addresses_skip_no_reply_and_job_boards(server):
    text = 'Questions? privacy@acme.com or no-reply@greenhouse.io. Reach the recruiter at maria.k@acme.com or jobs@indeed.com.'
    assert server.contact_from_text(text) == 'maria.k@acme.com'
    assert server.contact_from_text('nothing here') == ''


def test_followup_due_schedule(server):
    base = {'status': 'applied', 'applied_on': '2026-10-01', 'followups_sent': 0, 'last_reply_on': None}
    assert server.followup_due(base, '2026-10-04') == 0
    assert server.followup_due(base, '2026-10-06') == 1
    assert server.followup_due(dict(base, followups_sent=1), '2026-10-10') == 0
    assert server.followup_due(dict(base, followups_sent=1), '2026-10-13') == 2
    assert server.followup_due(dict(base, followups_sent=2), '2026-10-30') == 0
    assert server.followup_due(dict(base, last_reply_on='2026-10-03'), '2026-10-13') == 0, 'they answered'
    assert server.followup_due(dict(base, status='interview'), '2026-10-13') == 0


def test_autopilot_drafts_sends_when_allowed_and_marks_ghosted(server, db, monkeypatch):
    st = db
    pid = st.save_profile({'name': 'Me', 'targets': 'AI Engineer', 'base_resume': 'Built RAG agents in Python. ' * 10, 'followups': 'auto'})['id']
    a1, _ = st.create_application({'company': 'Acme', 'role': 'AI Engineer', 'status': 'applied', 'applied_on': '2026-10-01'})
    a2, _ = st.create_application({'company': 'Beta', 'role': 'ML Engineer', 'status': 'applied', 'applied_on': '2026-10-15'})
    a3, _ = st.create_application({'company': 'Gamma', 'role': 'AI Engineer', 'status': 'applied', 'applied_on': '2026-09-20'})
    st.update_application(a2['id'], {'contact_email': 'rec@beta.com'})
    monkeypatch.setattr(server, '_local_today', lambda: '2026-10-21')
    sent = []
    monkeypatch.setattr(server, 'send_alert_email', lambda to, subject, html: sent.append((to, subject, html)) or (True, 'sent'))
    monkeypatch.setattr(server, 'smtp_ready', lambda: True)
    monkeypatch.setattr(server, 'AI_PROBLEM', '')

    def fake_gen(company, role, days, summary, emit, resume=''):
        emit({'type': 'followup_data', 'data': {'week_1_email': {'subject': f'Following up on {role}', 'body': 'Hi,\n\nStill keen on the role.\n\nJo'},
                                                'week_2_email': {'subject': 'Checking in', 'body': 'Hello again'}, 'withheld': {}}})
    monkeypatch.setattr(server, 'followup_generator', fake_gen)
    r = server.followup_autopilot()
    assert r['sent'] == 1 and sent[0][0] == 'rec@beta.com' and 'Following up on ML Engineer' in sent[0][1] and '<p>Hi,</p>' in sent[0][2]
    assert r['drafted'] == 2, 'Acme and Beta were drafted; Gamma is past the ghost line'
    assert [d['company'] for d in r['due']] == ['Acme'], 'Acme has no address: left due in the Tracker'
    assert r['ghosted'] == 1
    acme = st.get_application(a1['id'], with_history=True)
    assert acme['next_action_on'] == '2026-10-21' and any(x['kind'] == 'followup' for x in acme['artifacts'])
    beta = st.get_application(a2['id'], with_history=True)
    assert beta['followups_sent'] == 1 and any(e['kind'] == 'followup_sent' and e['detail']['by'] == 'apex' for e in beta['events'])
    gamma = st.get_application(a3['id'], with_history=True)
    assert any(e['kind'] == 'ghosted' for e in gamma['events']) and gamma['status'] == 'applied'
    assert server.followup_autopilot()['ghosted'] == 0, 'ghosted once'
    with pytest.raises(st.StoreError):
        server.send_followup(a1['id'])                       # no address
    assert server.send_followup(a2['id'], which=2)['which'] == 2 and len(sent) == 2
    assert pid


def test_replies_set_last_reply_and_the_contact(server, db):
    st = db
    a, _ = st.create_application({'company': 'Acme', 'role': 'AI Engineer', 'status': 'applied', 'applied_on': '2026-10-01'})
    rows = [{'from': 'Maria K <maria.k@acme.com>', 'match': {'id': a['id']}}, {'from': 'noreply@acme.com', 'match': {'id': a['id']}}]
    server.capture_contacts(rows)
    got = st.get_application(a['id'])
    assert got['contact_email'] == 'maria.k@acme.com' and got['contact_name'] == 'Maria K'
    st.update_application(a['id'], {'status': 'interview'})
    assert st.get_application(a['id'])['last_reply_on'] == st._today()


def test_digest_data_and_analytics(server, db, monkeypatch):
    st = db
    prof = st.save_profile({'name': 'Me', 'targets': 'AI Engineer', 'base_resume': 'Built RAG agents in Python. ' * 10, 'digest_email': 'me@example.com'})
    a, _ = st.create_application({'company': 'Acme', 'role': 'Senior AI Engineer', 'status': 'applied', 'applied_on': '2026-10-01'})
    for n in range(5):
        b, _ = st.create_application({'company': f'Co{n}', 'role': 'Forward Deployed Engineer', 'status': 'interview', 'applied_on': '2026-10-02'})
    for n in range(5):
        st.create_application({'company': f'Ml{n}', 'role': 'Machine Learning Engineer', 'status': 'applied', 'applied_on': '2026-10-02'})
    monkeypatch.setattr(server, '_local_today', lambda: '2026-10-21')
    d = server.digest_data(prof)
    assert d['day'] == '2026-10-21' and d['new'] == 0 and 'Acme' in [f['company'] for f in d['followups_due']]
    html = server.digest_html(prof, d)
    assert 'Follow-ups due' in html and 'Acme' in html
    with pytest.raises(st.StoreError):
        server.send_digest(dict(prof, digest_email=''))
    h = server.agent_analytics()
    assert h['funnel']['sent'] == 11 and h['funnel']['replied'] == 5 and h['funnel']['interviews'] == 5
    fam = {r['key']: r for r in h['by_family']}
    assert fam['forward deployed, solutions and customer AI engineering']['rate'] == 100
    assert fam['machine learning engineering']['rate'] == 0
    assert h['recommendations'] and 'forward deployed' in h['recommendations'][0]
    assert h['enough_data'] is True
