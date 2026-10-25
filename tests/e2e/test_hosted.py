"""The public demo: access code, signed sessions, per-visitor data, budgets,
local-only features off. Runs a second server with hosted-mode env vars."""
import http.client
import json
import re
import uuid
from urllib.parse import urlencode

import pytest
from playwright.sync_api import expect


def req(app, method, path, body=None, headers=None, form=None, ip=None):
    c = http.client.HTTPConnection('127.0.0.1', app.port, timeout=15)
    h = {'Host': app.public_host}
    if ip:
        h['Fly-Client-IP'] = ip
    data = None
    if form is not None:
        data, h['Content-Type'] = urlencode(form), 'application/x-www-form-urlencoded'
    elif body is not None:
        data, h['Content-Type'] = json.dumps(body), 'application/json'
    h.update(headers or {})
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    raw = r.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = raw.decode('utf-8', 'replace')
    return r.status, {k.lower(): v for k, v in r.getheaders()}, payload


def login(app, ip=None):
    st, h, _ = req(app, 'POST', '/login', form={'code': app.code}, ip=ip or f'10.0.0.{uuid.uuid4().int % 250}')
    assert st == 303 and h['location'] == '/', (st, h)
    return h['set-cookie'].split(';')[0]           # "apex_session=..."


def test_everything_but_health_and_login_needs_a_session(hosted):
    st, h, _ = req(hosted, 'GET', '/')
    assert st == 303 and h['location'] == '/login'
    st, _, j = req(hosted, 'GET', '/api/applications')
    assert st == 401 and j['login'] is True
    st, _, j = req(hosted, 'POST', '/parse-resume', body={'resume': 'x' * 200})
    assert st == 401
    st, h, page = req(hosted, 'GET', '/login')
    assert st == 200 and 'Access code' in page and "script-src" not in h['content-security-policy']


def test_health_answers_platform_checks_with_internal_host(hosted):
    st, _, j = req(hosted, 'GET', '/health', headers={'Host': '172.19.4.2:8080'})
    assert st == 200 and j['status'] == 'ok'


def test_login_sets_a_hardened_cookie_and_lets_you_in(hosted):
    st, h, _ = req(hosted, 'POST', '/login', form={'code': hosted.code}, ip='10.1.1.1')
    assert st == 303
    attrs = [a.strip().lower() for a in h['set-cookie'].split(';')]
    assert {'httponly', 'secure', 'samesite=lax', 'path=/'} <= set(attrs)
    cookie = h['set-cookie'].split(';')[0]
    st, h, body = req(hosted, 'GET', '/', headers={'Cookie': cookie})
    assert st == 200 and 'strict-transport-security' in h and '<title>APEX</title>' in body
    st, _, j = req(hosted, 'GET', '/config', headers={'Cookie': cookie})
    assert j['HOSTED'] is True and j['SMTP_CONFIGURED'] is False


def test_wrong_code_then_throttled(hosted):
    ip = '10.9.9.9'
    for _ in range(5):
        st, _, page = req(hosted, 'POST', '/login', form={'code': 'guess'}, ip=ip)
        assert st == 401 and 'not right' in page
    st, _, page = req(hosted, 'POST', '/login', form={'code': hosted.code}, ip=ip)
    assert st == 429 and 'Too many attempts' in page, 'even the right code waits out the lockout'
    login(hosted, ip='10.9.9.10')                     # other visitors unaffected


@pytest.mark.parametrize('cookie', ['apex_session=v1.abc.9999999999.deadbeef', 'apex_session=garbage',
                                    'apex_session=v1.' + 'a' * 32 + '.1.' + '0' * 64])
def test_forged_or_expired_sessions_rejected(hosted, cookie):
    st, _, _ = req(hosted, 'GET', '/api/applications', headers={'Cookie': cookie})
    assert st == 401


def test_logout_clears_the_cookie(hosted):
    st, h, _ = req(hosted, 'GET', '/logout', headers={'Cookie': login(hosted)})
    assert st == 303 and h['location'] == '/login' and 'max-age=0' in h['set-cookie'].lower()


def test_visitors_never_see_each_others_pipeline(hosted):
    alice, bob = login(hosted), login(hosted)
    st, _, j = req(hosted, 'POST', '/api/applications', body={'company': 'Secret Co', 'role': 'Analyst'},
                   headers={'Cookie': alice})
    assert st == 201
    aid = j['application']['id']
    _, _, j = req(hosted, 'GET', '/api/applications', headers={'Cookie': bob})
    assert j['applications'] == [] and j['summary']['total'] == 0
    for method, path, body in (('GET', f'/api/application?id={aid}', None),
                               ('POST', '/api/applications/update', {'id': aid, 'status': 'offer'}),
                               ('POST', '/api/applications/delete', {'id': aid})):
        st, _, j = req(hosted, method, path, body=body, headers={'Cookie': bob})
        assert st == 404 and j['error'] == 'application not found'
    _, _, j = req(hosted, 'GET', '/api/applications', headers={'Cookie': alice})
    assert [a['company'] for a in j['applications']] == ['Secret Co']
    assert 'owner' not in j['applications'][0]


@pytest.mark.parametrize('method,path', [('POST', '/config/smtp'), ('POST', '/alerts/test'),
                                         ('POST', '/inbox/scan'), ('POST', '/alerts/subscribe'),
                                         ('GET', '/alerts/list')])
def test_operator_only_features_are_off(hosted, method, path):
    st, _, j = req(hosted, method, path, body={'user': 'a@b.c', 'password': 'x', 'email': 'a@b.c'} if method == 'POST' else None,
                   headers={'Cookie': login(hosted)})
    assert st == 403 and 'turned off in the online demo' in j['error']


def test_per_visitor_and_per_ip_ai_budget(hosted):
    ip = '10.7.7.7'
    cookie = login(hosted, ip=ip)
    resume = 'Jane Doe\njane@x.com\nEXPERIENCE\n' + 'Analyst at Acme, built SQL reports. ' * 5
    st, _, _ = req(hosted, 'POST', '/parse-resume', body={'resume': resume}, headers={'Cookie': cookie}, ip=ip)
    assert st == 200                                   # budget is 3 units; parsing costs 2
    st, _, j = req(hosted, 'POST', '/parse-resume', body={'resume': resume}, headers={'Cookie': cookie}, ip=ip)
    assert st == 429 and 'Demo limit reached' in j['error']
    st, _, _ = req(hosted, 'POST', '/api/applications', body={'company': 'Free', 'role': 'Ops'},
                   headers={'Cookie': cookie}, ip=ip)
    assert st == 201, 'pipeline (no AI) is not metered'
    st, _, j = req(hosted, 'POST', '/parse-resume', body={'resume': resume}, headers={'Cookie': login(hosted, ip=ip)}, ip=ip)
    assert st == 429, 'signing in again is a new visitor, not a new budget: the IP keeps its limit'
    other = '10.7.7.8'
    st, _, _ = req(hosted, 'POST', '/parse-resume', body={'resume': resume}, headers={'Cookie': login(hosted, ip=other)}, ip=other)
    assert st == 200, 'another visitor on another network has their own budget'


def test_bad_requests_cost_nothing(hosted):
    ip = '10.6.6.6'
    cookie = login(hosted, ip=ip)
    resume = 'Jane Doe\njane@x.com\nEXPERIENCE\n' + 'Analyst at Acme, built SQL reports. ' * 5
    for path, body in (('/parse-resume', '{{{'), ('/analyze', json.dumps({'jobTitle': '', 'resume': resume})),
                       ('/tailor?x=1', json.dumps({'resume': 'short'})), ('/nope', '{}')):
        c = http.client.HTTPConnection('127.0.0.1', hosted.port, timeout=15)
        c.request('POST', path, body=body, headers={'Host': hosted.public_host, 'Content-Type': 'application/json',
                                                   'Cookie': cookie, 'Fly-Client-IP': ip})
        assert c.getresponse().status in (400, 404)
    st, _, _ = req(hosted, 'POST', '/parse-resume', body={'resume': resume}, headers={'Cookie': cookie}, ip=ip)
    assert st == 200, 'four refused requests spent none of the 3-unit budget'


def test_new_sessions_per_ip_are_capped(hosted):
    ip = '10.5.5.5'
    for _ in range(5):
        login(hosted, ip=ip)
    st, _, page = req(hosted, 'POST', '/login', form={'code': hosted.code}, ip=ip)
    assert st == 429 and 'Too many new sessions' in page


def test_spoofed_forwarded_for_is_not_trusted_on_fly(hosted):
    """On Fly only Fly-Client-IP (set by Fly's proxy) counts: rotating
    X-Forwarded-For values cannot dodge the login throttle."""
    ip = '10.4.4.4'
    for n in range(5):
        st, _, _ = req(hosted, 'POST', '/login', form={'code': 'guess'}, ip=ip,
                       headers={'X-Forwarded-For': f'203.0.113.{n}'})
        assert st == 401
    st, _, page = req(hosted, 'POST', '/login', form={'code': 'guess'}, ip=ip, headers={'X-Forwarded-For': '198.51.100.9'})
    assert st == 429


def test_public_origin_is_https_only(hosted):
    cookie = login(hosted)
    st, h, _ = req(hosted, 'GET', '/health', headers={'Cookie': cookie, 'Origin': f'https://{hosted.public_host}'})
    assert st == 200 and h['access-control-allow-origin'] == f'https://{hosted.public_host}'
    st, _, _ = req(hosted, 'GET', '/config', headers={'Cookie': cookie, 'Origin': f'http://{hosted.public_host}'})
    assert st == 403


def test_refuses_to_listen_publicly_without_an_access_code(tmp_path_factory, fake_openai):
    import subprocess, sys
    from conftest import ROOT
    d = tmp_path_factory.mktemp('nogate')
    import shutil
    for n in ('agent_server.py', 'apex_store.py', 'apex_engine.py', 'apex_domains.py', 'apex_apply.py', 'index.html'):
        shutil.copy(ROOT / n, d / n)
    import os
    env = dict(os.environ, OPENAI_API_KEY='sk-x', APEX_BIND='0.0.0.0', APEX_PORT='0')
    r = subprocess.run([sys.executable, '-I', str(d / 'agent_server.py')], cwd=d, env=env,
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 1 and 'refusing to listen publicly' in r.stdout


def test_browser_sign_in_flow(browser, hosted):
    ctx = browser.new_context()
    page = ctx.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(hosted.url + '/')
    expect(page).to_have_url(re.compile(r'/login$'))
    page.fill('#code', 'nope')
    page.click('button[type=submit]')
    expect(page.locator('.err')).to_contain_text('not right')
    page.fill('#code', hosted.code)
    page.click('button[type=submit]')
    expect(page.locator('#tel-server-v')).to_have_text('11.0')   # (string evals are blocked by the CSP)
    expect(page.locator('body')).to_have_class(re.compile(r'\bhosted\b'))
    expect(page.locator('.dock-item[data-view="alerts"]')).to_be_hidden()
    expect(page.locator('a[href="/logout"]')).to_be_visible()
    page.click('.dock-item[data-view="tracker"]')
    expect(page.locator('#trk-tbody')).to_contain_text('No applications yet')
    # Session ends server-side -> next API call sends the page back to /login.
    ctx.clear_cookies()
    page.click('#trk-add')                                        # client validation, no request
    page.fill('#trk-co', 'X'); page.fill('#trk-role', 'Y')
    page.click('#trk-add')
    expect(page).to_have_url(re.compile(r'/login$'))
    assert not errors, errors
    ctx.close()


@pytest.mark.parametrize('path', ['/api/facts', '/api/agent/profiles'])
def test_vault_and_job_agent_are_local_only(hosted, path):
    st, _, j = req(hosted, 'GET', path, headers={'Cookie': login(hosted)})
    assert st == 403 and 'local APEX' in j['error']


@pytest.mark.parametrize('path', ['/api/applications/brief', '/api/applications/warm', '/api/applications/followup/send'])
def test_research_and_outbound_mail_are_local_only(hosted, path):
    st, _, j = req(hosted, 'POST', path, body={'id': 'x'}, headers={'Cookie': login(hosted)})
    assert st == 403 and 'local APEX' in j['error']
