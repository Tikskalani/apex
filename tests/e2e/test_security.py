"""The local server must not hand secrets or actions to other web pages.

Every page open in the browser can send requests to localhost. These tests pin
the guard in agent_server.py: own-origin only, allowlisted static files, no key
material in any response.
"""
import http.client
import json

import pytest

SECRET = 'sk-test-stub-not-a-real-key'   # written to the temp config.json by conftest


def req(app, method, path, headers=None, body=None):
    c = http.client.HTTPConnection('127.0.0.1', app.port, timeout=10)
    h = {'Host': f'localhost:{app.port}'}
    h.update(headers or {})
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


@pytest.mark.parametrize('path', [
    '/config.json', '/config.json.', '/config.json::$DATA', '/CONFIG.JSON', '/Config.Json.',
    '/agent_server.py', '/server.log', '/.gitignore', '/../config.json', '/%2e%2e/config.json',
    '/assets/../config.json', '/subscriptions.json',
])
def test_static_route_never_serves_private_files(app, path):
    status, _, body = req(app, 'GET', path)
    assert status in (403, 404), f'{path} -> {status}'
    assert SECRET.encode() not in body


def test_no_response_carries_key_material(app):
    for path in ('/', '/health', '/config', '/templates'):
        status, _, body = req(app, 'GET', path)
        assert status == 200
        assert SECRET.encode() not in body, f'{path} leaks the OpenAI key'
    cfg = json.loads(req(app, 'GET', '/config')[2])
    assert not any('KEY' in k for k in cfg), cfg


def test_no_wildcard_cors_anywhere(app):
    for method, path in (('GET', '/'), ('GET', '/health'), ('OPTIONS', '/analyze')):
        _, h, _ = req(app, method, path, {'Origin': f'http://localhost:{app.port}'})
        assert h.get('access-control-allow-origin') != '*'


@pytest.mark.parametrize('method,path,headers', [
    ('GET', '/health', {'Origin': 'https://evil.example'}),
    ('GET', '/config', {'Origin': 'null'}),                                       # file:// page
    ('GET', '/health', {'Host': 'evil.example'}),                                 # DNS rebinding
    ('GET', '/health', {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'no-cors'}),
    ('OPTIONS', '/config/smtp', {'Origin': 'https://evil.example'}),
    ('POST', '/config/smtp', {'Origin': 'https://evil.example', 'Content-Type': 'application/json'}),
    ('POST', '/config/smtp', {'Origin': 'https://evil.example', 'Content-Type': 'text/plain'}),  # no preflight
    ('POST', '/alerts/test', {'Sec-Fetch-Site': 'cross-site', 'Content-Type': 'text/plain'}),
])
def test_foreign_requests_refused(app, method, path, headers):
    body = b'{"user":"attacker@evil.example","password":"x"}' if method == 'POST' else None
    status, h, _ = req(app, method, path, headers, body)
    assert status == 403, f'{method} {path} {headers} -> {status}'
    assert 'access-control-allow-origin' not in h
    cfg = json.loads((app.dir / 'config.json').read_text())
    assert 'SMTP_USER' not in cfg, 'a refused request still wrote to config.json'


def test_link_to_front_page_from_another_site_still_works(app):
    status, _, _ = req(app, 'GET', '/', {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate'})
    assert status == 200


def test_browser_on_another_origin_cannot_read_the_api(browser, app, fake_openai):
    """End to end in Chromium: a page on a different origin tries to read APEX."""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(fake_openai.url + '/')                     # a different origin
    out = page.evaluate("""async (base) => {
      const res = {};
      for (const p of ['/config', '/health', '/config.json.']) {
        try { const r = await fetch(base + p); res[p] = 'READ ' + r.status + ' ' + (await r.text()).slice(0, 80); }
        catch (e) { res[p] = 'blocked'; }
      }
      try {
        await fetch(base + '/config/smtp', {method: 'POST', headers: {'Content-Type': 'text/plain'},
                                            body: JSON.stringify({user: 'a@evil.example', password: 'x'})});
      } catch (e) {}
      return res;
    }""", app.url)
    ctx.close()
    assert out == {'/config': 'blocked', '/health': 'blocked', '/config.json.': 'blocked'}, out
    cfg = json.loads((app.dir / 'config.json').read_text())
    assert 'SMTP_USER' not in cfg, 'cross-site text/plain POST overwrote SMTP settings'
