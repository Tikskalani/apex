"""Server helpers without HTTP: request validation, the verified resume struct,
the alerts store. Uses the `server` fixture (a key-free copy of agent_server.py)."""
import json
import threading

import pytest

RESUME = ('Jane Doe\njane@example.com | (555) 010-2000\nEXPERIENCE\nAnalyst, Acme Corp (2020 - 2024)\n'
          '- Built weekly revenue reporting in SQL for the finance team\n- Automated month-end reconciliations\n'
          'EDUCATION\nBS Mathematics, State University, 2019')


def test_verify_struct_keeps_source_text_and_drops_inventions(server):
    parsed = {'name': 'Jane Doe', 'email': 'jane@example.com',
              'experience': [{'title': 'Analyst', 'company': 'Acme Corp', 'start': '2020', 'end': '2024',
                              'bullets': ['Built weekly revenue reports in SQL for finance team',     # paraphrase
                                          'Led a team of 12 analysts at Google']}],                 # invented
              'education': [{'degree': 'BS Mathematics', 'school': 'State University', 'year': '2019'}],
              'skills': {'technical': ['SQL', 'Kubernetes']}}
    struct, dropped = server.verify_struct(parsed, RESUME)
    bullets = struct['experience'][0]['bullets']
    assert bullets == ['Built weekly revenue reporting in SQL for the finance team'], 'snapped to the source line'
    assert struct['skills']['technical'] == ['SQL']
    assert {d['text'] for d in dropped} == {'Led a team of 12 analysts at Google', 'Kubernetes'}


@pytest.mark.parametrize('route,body,status', [
    ('/analyze', {'jobTitle': 'X', 'resume': 'a' * 99}, 400),
    ('/analyze', {'jobTitle': 'X', 'resume': 'a' * 100}, None),
    ('/draft-cover-letter', {'resume': 'short is fine here'}, None),
    ('/live-jobs', {'q': 'x', 'limit': '500'}, None),
    ('/inbox/scan', {'user': 'u', 'password': 'p', 'days': 'soon'}, 400),
    ('/render-resume', {}, 400),
    ('/render-resume', {'struct': {}}, None),
])
def test_validate_post(server, route, body, status):
    if status is None:
        server.validate_post(route, body)
    else:
        with pytest.raises(server.BadRequest) as e:
            server.validate_post(route, body)
        assert e.value.status == status


def test_numbers_are_clamped(server):
    body = {'q': 'x', 'limit': '500', 'minScore': -4}
    server.validate_post('/live-jobs', body)
    assert body['limit'] == 100 and body['minScore'] == 0


def test_rendering_a_given_struct_is_free(server):
    assert server.route_cost('/render-resume', {'struct': {}}) == 0
    assert server.route_cost('/render-resume', {'resume': 'x'}) == server.AI_COSTS['/render-resume'] > 0


def test_target_signature_is_stable_and_tamper_evident(server):
    t = {'title': 'Analyst', 'supported': ['SQL']}
    assert server._target_sig(t) == server._target_sig(dict(t))
    assert server._target_sig(t) != server._target_sig({**t, 'supported': ['SQL', 'Kubernetes']})


def test_alert_scan_never_loses_a_subscription_made_during_it(server, tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'ALERTS_FILE', str(tmp_path / 'alerts.json'))
    first = server.add_alert_subscription({'email': 'a@example.com', 'jobTitle': 'Data Analyst'})
    started, release = threading.Event(), threading.Event()

    def slow_jobs(query, limit=40, location=''):
        started.set()
        release.wait(5)
        return {'jobs': [{'title': 'Data Analyst', 'company': 'Acme', 'url': 'https://x.example/1'}]}
    monkeypatch.setattr(server, 'fetch_structured_jobs', slow_jobs)
    monkeypatch.setattr(server, 'send_alert_email', lambda *a: (True, 'sent'))
    t = threading.Thread(target=server.alerts_scan_once)
    t.start()
    started.wait(5)
    second = server.add_alert_subscription({'email': 'b@example.com', 'jobTitle': 'Engineer'})   # during the scan
    assert server.start_alert_scan() is False, 'a second scan does not start while one runs'
    release.set()
    t.join(10)
    data = json.loads((tmp_path / 'alerts.json').read_text(encoding='utf-8'))
    assert {s['id'] for s in data['subscriptions']} == {first['id'], second['id']}
    assert len(data['sent'][first['id']]) == 1 and next(
        s for s in data['subscriptions'] if s['id'] == first['id'])['last_run'] > 0


def test_corrupt_alerts_file_is_set_aside_not_wiped(server, tmp_path, monkeypatch):
    f = tmp_path / 'alerts.json'
    monkeypatch.setattr(server, 'ALERTS_FILE', str(f))
    f.write_text('{"subscriptions": [', encoding='utf-8')
    assert server.list_alerts() == []
    assert list(tmp_path.glob('alerts.json.corrupt-*')), 'the damaged file is kept for recovery'


# ── regressions from the independent review ─────────────────────────────────

def test_exports_drop_short_invented_skills_hidden_in_longer_words(server):
    source = 'Jane Doe\nSKILLS\nJavaScript, PostgreSQL, Google Analytics'
    struct, dropped = server.verify_struct({'skills': {'technical': ['Java', 'SQL', 'Go', 'JavaScript']}}, source)
    assert struct['skills']['technical'] == ['JavaScript']
    assert {d['text'] for d in dropped} == {'Java', 'SQL', 'Go'}


@pytest.mark.parametrize('text,want', [('$120-150K', (120000, 150000)), ('120 - 150k', (120000, 150000)),
                                       ('$120,000 + 401k', (120000, 120000)), ('$95K-$110K', (95000, 110000))])
def test_salary_ranges_with_one_k_and_401k(server, text, want):
    assert server.parse_salary(text) == want


def test_title_and_company_words_never_unlock_a_tool(server):
    allowed = server._words('Salesforce AWS Administrator')
    assert 'AWS' not in allowed and 'Salesforce' not in allowed and 'Administrator' in allowed
    probs = server.engine.fact_gate('I administered Salesforce and built AWS dashboards',
                                    'Administered the CRM for the sales team', allowed_words=allowed)
    assert any('AWS' in p for p in probs) and any('Salesforce' in p for p in probs)


# ── regressions from the real Claude run (2026-10-11) ────────────────────────

@pytest.mark.parametrize('title,query,want', [
    ('Senior Backend Engineer, Payments', 'Staff Backend Engineer', True),
    ('Backend Developer (Go)', 'Staff Backend Engineer', True),
    ('Security Engineer', 'Staff Backend Engineer', False),
    ('Staff Frontend Engineer', 'Staff Backend Engineer', False),
    ('Data Analyst II', 'Senior Data Analyst', True),
    ('Data Engineer', 'Senior Data Analyst', True),
    ('Marketing Analyst', 'Senior Data Analyst', False),
    ('Registered Nurse', 'Engineer', False),
])
def test_job_titles_match_on_what_the_job_is(server, title, query, want):
    assert server.title_matches(title, query) is want


def test_off_role_postings_drop_out_of_the_market_corpus(server):
    words = ['staff', 'backend', 'engineer']
    on = server.score_listing('Senior Backend Engineer - Go, Kafka, PostgreSQL. Build payment services.', words, [], [])
    off = server.score_listing('Security Engineer - defence clearance required. Engineer secure systems.', words, [], [])
    assert on >= 35 > off
