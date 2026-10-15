"""Request handling: validation before spend, exact routing, size limits,
cancellation, setup mode without a key, and the newly fact-checked tools."""
import http.client
import json
import socket
import time

import pytest

from conftest import ServerProcess
from test_api import call
from test_fact_check import data_of, sse


def raw_post(app, path, body, headers=None):
    c = http.client.HTTPConnection('127.0.0.1', app.port, timeout=15)
    h = {'Host': f'localhost:{app.port}', 'Content-Type': 'application/json'}
    h.update(headers or {})
    c.request('POST', path, body=body, headers=h)
    r = c.getresponse()
    return r.status, json.loads(r.read() or b'{}')


def test_query_string_does_not_change_the_route(app, fixture_resume):
    events = sse(app, '/bullets?from=menu', {'resume': fixture_resume, 'jobTitle': 'Senior Data Analyst'})
    assert data_of(events, 'bullet_data')['ranked_bullets']


@pytest.mark.parametrize('path,body,status,msg', [
    ('/bullets', {'resume': 'too short'}, 400, 'Resume too short'),
    ('/tailor', {'resume': 'x' * 200}, 400, 'job posting'),
    ('/bridge', {'resume': 'x' * 200, 'toRole': 'PM'}, 400, 'moving from'),
    ('/grade-answer', {'question': 'Why us?'}, 400, 'answer'),
    ('/analyze', {'jobTitle': 'Analyst', 'resume': 'x' * 40_001}, 413, 'too long'),
    ('/match', {'resume': 'x' * 200, 'jobPosting': 'y' * 20_001}, 413, 'posting is too long'),
    ('/live-jobs', {'q': 'analyst', 'limit': 'many'}, 400, 'limit must be a number'),
    ('/transcribe', {'audio_b64': 'AAAA', 'mime': 'text/html\r\nX: y'}, 400, 'Unsupported audio'),
])
def test_invalid_input_is_refused_before_any_model_call(app, fake_openai, path, body, status, msg):
    before = len(fake_openai.calls)
    st, j = call(app, 'POST', path, body)
    assert st == status and msg in j['error'], (st, j)
    assert len(fake_openai.calls) == before


def test_body_shape_and_size_limits(app):
    assert raw_post(app, '/bullets', '[1, 2]')[0] == 400                       # not a JSON object
    assert raw_post(app, '/bullets', '{bad json')[0] == 400
    st, j = raw_post(app, '/bullets', '{}', headers={'Content-Length': '3000000'})
    assert st == 413 and 'too large' in j['error']
    # A negative length used to block a worker thread until its timeout.
    s = socket.create_connection(('127.0.0.1', app.port), timeout=5)
    s.sendall(f'POST /bullets HTTP/1.1\r\nHost: localhost:{app.port}\r\nContent-Length: -1\r\n\r\n'.encode())
    t = time.time()
    assert s.recv(200).startswith(b'HTTP/1.1 400') and time.time() - t < 3
    s.close()


def test_config_reports_setup_state_without_secrets(app):
    st, j = call(app, 'GET', '/config')
    assert st == 200 and j['AI_READY'] is True and j['AI_PROBLEM'] == '' and j['VERSION'] == '11.0'
    assert not any('sk-' in str(v) for v in j.values())
    st, j = call(app, 'GET', '/health')
    assert j['version'] == '11.0' and j['db'] == 'ok'


def test_old_get_render_route_is_gone(app):
    assert call(app, 'GET', '/render-resume?template=modern')[0] == 404


def test_get_live_jobs_validates_and_uses_saved_postings(app):
    assert call(app, 'GET', '/live-jobs?q=analyst&limit=abc')[0] == 400
    st, j = call(app, 'GET', '/live-jobs?q=data%20analyst&limit=3')
    assert st == 200 and 0 < j['count'] <= 3 and all(x['source'] == 'Fixture' for x in j['jobs'])


def test_closing_the_stream_stops_the_run(app, fake_openai, fixture_resume):
    """Every model answer takes 1.5 s here. A full run makes 15+ calls; after the
    client disconnects, at most the calls already in flight may finish."""
    c = http.client.HTTPConnection('127.0.0.1', app.port, timeout=30)
    c.request('POST', '/analyze', body=json.dumps({'jobTitle': 'Senior Data Analyst', 'resume': fixture_resume + '\nSLOWSTUB'}),
              headers={'Host': f'localhost:{app.port}', 'Content-Type': 'application/json'})
    r = c.getresponse()
    assert r.status == 200
    r.read(200)                                     # the run has started
    start = len(fake_openai.calls)
    r.close(); c.close()                            # the user closed the tab (the response holds the socket too)
    time.sleep(20)                                  # a full run would make ~13 more calls by now
    assert len(fake_openai.calls) - start <= 7, len(fake_openai.calls) - start


def test_without_a_key_the_page_opens_and_explains_setup(tmp_path_factory, fake_openai, monkeypatch):
    for k in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        monkeypatch.delenv(k, raising=False)
    a = ServerProcess(tmp_path_factory, fake_openai, config_json={})
    try:
        st, j = call(a, 'GET', '/config')
        assert j['AI_READY'] is False and 'config.json' in j['AI_PROBLEM']
        st, j = call(a, 'POST', '/bullets', {'resume': 'x' * 200})
        assert st == 503 and j['setup'] is True
        c = http.client.HTTPConnection('127.0.0.1', a.port, timeout=10)
        c.request('GET', '/', headers={'Host': f'localhost:{a.port}'})
        assert c.getresponse().status == 200
    finally:
        a.stop()


def test_interview_prep_answers_are_checked(app, fixture_resume):
    events = sse(app, '/analyze', {'jobTitle': 'Senior Data Analyst', 'resume': fixture_resume}, timeout=120)
    iv = data_of(events, 'interview_data')
    assert iv['verified'] and iv['behavioral'][0]['a'].startswith('At Brightline Logistics')
    assert iv['behavioral'][1]['a'] is None and iv['behavioral'][1]['a_withheld'], 'invented "team of 12" withheld'
    assert data_of(events, 'velocity_data')['velocity_score'] == 64
    report = data_of(events, 'report_data')
    assert {'name', 'pct'} <= set(report['baselineKeywords'][0]), 'the drift baseline keeps its requirement list'


def test_salary_uses_posted_pay_and_checks_leverage(app, fixture_resume):
    d = data_of(sse(app, '/negotiate', {'jobTitle': 'Data Analyst', 'resume': fixture_resume}), 'negotiate_data')
    assert d['estimate_basis'] == 'postings' and d['posted_pay']['n'] == 4 and '4 live postings' in d['basis_note']
    assert d['your_leverage'] == ['Hands-on SQL reporting for the management team']
    assert any('5' in p for p in d['your_leverage_withheld']), 'invented $5M budget withheld'


def test_match_marks_fixes_the_resume_does_not_show(app, fixture_resume):
    d = data_of(sse(app, '/match', {'jobPosting': 'Data Analyst. SQL and Tableau.', 'resume': fixture_resume}), 'match_data')
    shown = {f['add_to_resume']: f['shown_on_resume'] for f in d['quick_fixes']}
    assert shown == {'SQL': True, 'Tableau': False} and 'only if it is true' in d['quick_fixes_note']


def test_grade_answer_rewrite_only_uses_what_they_said(app):
    events = sse(app, '/grade-answer', {'question': 'Tell me about a report.', 'answer': 'I built weekly reports with SQL for my team.',
                                       'jobTitle': 'Data Analyst'})
    g = [e for e in events if e.get('type') == 'answer_grade'][-1]['data']
    assert g['better_version'] == 'I built weekly reports with SQL.', 'the invented "50%" sentence was repaired away'


def test_grade_answer_redrafts_an_answer_it_cannot_repair(app):
    # STUBBORN: the repair changes nothing and two sentences are too few to trim, so one redraft
    # told what to avoid replaces it (its blank claims nothing).
    events = sse(app, '/grade-answer', {'question': 'Tell me about a report.', 'jobTitle': 'Data Analyst',
                                       'answer': 'I built weekly reports with SQL for my team. STUBBORN'})
    g = [e for e in events if e.get('type') == 'answer_grade'][-1]['data']
    assert g['better_version'].startswith('I built weekly reports with SQL for my team.') and '50%' not in g['better_version']
    assert '[the time it saved]' in g['better_version'] and 'better_version_withheld' not in g


def test_inbox_errors_are_reported_not_hidden(app):
    st, j = call(app, 'POST', '/inbox/scan', {'user': 'a@example.com', 'password': 'x', 'host': '127.0.0.1'})
    assert st == 502 and 'Could not reach 127.0.0.1' in j['error']


def test_smtp_settings_keep_the_rest_of_config_json(tmp_path_factory, fake_openai):
    a = ServerProcess(tmp_path_factory, fake_openai)          # its own server: SMTP stays off elsewhere
    try:
        st, j = call(a, 'POST', '/config/smtp', {'host': 'smtp.example.com', 'port': '2525', 'user': 'me@example.com',
                                                 'password': 'app-pass'})
        assert st == 200 and j['saved']
        cfg = json.loads((a.dir / 'config.json').read_text(encoding='utf-8'))
        assert cfg['OPENAI_KEY'].startswith('sk-test') and cfg['SMTP_PORT'] == 2525 and cfg['SMTP_HOST'] == 'smtp.example.com'
        assert not list(a.dir.glob('config.json.*.tmp')), 'written atomically, no temp files left'
    finally:
        a.stop()
