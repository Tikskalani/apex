"""/api/* over real HTTP against the isolated server copy (its own apex.db)."""
import http.client
import json
import uuid


def call(app, method, path, body=None, headers=None):
    c = http.client.HTTPConnection('127.0.0.1', app.port, timeout=10)
    h = {'Host': f'localhost:{app.port}', 'Content-Type': 'application/json'}
    h.update(headers or {})
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
    r = c.getresponse()
    return r.status, json.loads(r.read() or b'{}')


def uniq(prefix='Co'):
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


def test_application_lifecycle(app):
    co = uniq()
    st, j = call(app, 'POST', '/api/applications', {'company': co, 'role': 'Senior Data Analyst',
                                                    'url': 'https://jobs.example.com/42', 'status': 'saved'})
    assert st == 201 and j['created']
    aid = j['application']['id']
    st, j = call(app, 'POST', '/api/applications', {'company': co.lower(), 'role': 'senior data analyst',
                                                    'url': 'https://jobs.example.com/42'})
    assert st == 200 and not j['created'] and j['application']['id'] == aid

    st, j = call(app, 'POST', '/api/applications/update', {'id': aid, 'status': 'interview', 'notes': 'Panel Tue'})
    assert st == 200 and j['application']['status'] == 'interview' and j['application']['applied_on']

    st, j = call(app, 'POST', '/api/applications/artifact', {'id': aid, 'kind': 'cover_letter', 'content': 'Dear team'})
    assert st == 201
    st, j = call(app, 'GET', f'/api/application?id={aid}')
    assert st == 200
    assert [a['kind'] for a in j['application']['artifacts']] == ['cover_letter']
    assert [e['kind'] for e in j['application']['events']] == ['created', 'status', 'note', 'artifact']

    st, j = call(app, 'GET', '/api/applications')
    assert st == 200 and any(a['id'] == aid and a['artifact_count'] == 1 for a in j['applications'])
    assert set(j['summary']) >= {'total', 'by_status', 'response_rate', 'followups_due'}

    assert call(app, 'POST', '/api/applications/delete', {'id': aid})[0] == 200
    st, j = call(app, 'POST', '/api/applications/delete', {'id': aid})
    assert st == 404 and j['error'] == 'application not found'


def test_validation_errors_are_400_with_a_message(app):
    st, j = call(app, 'POST', '/api/applications', {'company': '', 'role': 'X'})
    assert st == 400 and j['error'] == 'company is required'
    st, j = call(app, 'POST', '/api/applications', {'company': 'A', 'role': 'B', 'url': 'javascript:alert(1)'})
    assert st == 400 and 'http' in j['error']
    st, j = call(app, 'POST', '/api/applications/update', {'id': 'nope', 'status': 'offer'})
    assert st == 404


def test_import_with_dedupe(app):
    co = uniq('Imp')
    st, j = call(app, 'POST', '/api/applications/import', {'source': 'gmail', 'items': [
        {'company': co, 'role': 'Analyst', 'date': '2026-09-01'},
        {'company': co, 'role': 'Analyst', 'date': '2026-09-01'},
        {'company': '', 'role': 'Analyst'}]})
    assert st == 200 and (j['created'], j['duplicates'], len(j['skipped'])) == (1, 1, 1)


def test_api_is_behind_the_origin_guard(app):
    st, _ = call(app, 'POST', '/api/applications/delete', {'id': 'x'},
                 headers={'Origin': 'https://evil.example', 'Content-Type': 'text/plain'})
    assert st == 403
    st, _ = call(app, 'GET', '/api/applications', headers={'Origin': 'https://evil.example'})
    assert st == 403


def test_drift_without_baseline_explains_itself(app, fixture_resume):
    st, j = call(app, 'POST', '/drift', {'jobTitle': uniq('Role'), 'resume': fixture_resume})
    assert st == 400 and 'Run the agent once' in j['error']


def test_unknown_api_route_is_json_404(app):
    st, j = call(app, 'GET', '/api/nope')
    assert st == 404 and j == {'error': 'not found'}


def test_sse_stream_ends_when_the_handler_finishes(app):
    """Regression: SSE was keep-alive with no length, so readers never saw EOF."""
    import time
    c = http.client.HTTPConnection('127.0.0.1', app.port, timeout=20)
    c.request('POST', '/followup', body=json.dumps({'company': 'Acme', 'role': 'Analyst', 'daysSince': 8}),
              headers={'Host': f'localhost:{app.port}', 'Content-Type': 'application/json'})
    r = c.getresponse()
    assert r.status == 200 and r.getheader('Connection') == 'close'
    t = time.time()
    body = r.read()          # returns only when the server closes the stream
    assert time.time() - t < 15
    assert b'"followup_data"' in body and b'"done"' in body
