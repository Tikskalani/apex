"""The job agent end to end, offline: profile -> scan (saved postings) -> approve -> kit -> applied -> Tracker."""
import time

from test_api import call, uniq


def wait_for(app, pid, pred, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        st, j = call(app, 'GET', '/api/agent/queue?profile=' + pid)
        assert st == 200, j
        if pred(j):
            return j
        time.sleep(0.5)
    raise AssertionError(f'timed out; last queue: {j}')


def test_agent_proposes_prepares_on_approval_and_files_applied_jobs(app, fixture_resume):
    st, j = call(app, 'POST', '/api/agent/profiles', {'name': 'Me', 'targets': 'Data Analyst', 'base_resume': fixture_resume,
                                                      'min_fit': 0, 'daily_limit': 3, 'active': False,
                                                      'auto_prepare': 0})
    assert st == 200, j
    pid = j['profile']['id']
    assert j['profile']['targets'] == ['Data Analyst'] and j['profile']['daily_limit'] == 3

    st, j = call(app, 'POST', '/api/agent/scan', {'profile': pid})
    assert st == 200 and j['started'] is True
    q = wait_for(app, pid, lambda j: not j['scanning'] and j['items'])
    items = q['items']
    assert 0 < len(items) <= 3, 'at most the daily limit'
    assert all(i['status'] == 'proposed' for i in items) and all('fit' in i for i in items)
    assert items == sorted(items, key=lambda i: -i['fit']), 'best fit first'

    # Nothing is tailored (no model call) until approval.
    first = items[0]
    st, j = call(app, 'POST', '/api/agent/approve', {'ids': [first['id']]})
    assert st == 200 and j['approved'] == 1
    q = wait_for(app, pid, lambda j: any(i['id'] == first['id'] and i['status'] in ('ready', 'failed') for i in j['items']))
    item = next(i for i in q['items'] if i['id'] == first['id'])
    assert item['status'] == 'ready', item
    st, j = call(app, 'GET', '/api/agent/item?id=' + first['id'])
    kit = j['item']['kit']
    assert kit['resume'] and kit['cover_letter'], kit
    assert kit['tier'] == 'economy' and kit['calls'] > 0 and kit['cost_usd'] > 0, 'what the kit cost is measured'
    st, j = call(app, 'GET', '/api/agent/queue?profile=' + pid)
    assert j['cost']['measured'] == 1 and j['cost']['usd'] == kit['cost_usd'] and j['cost']['tier'] == 'economy'
    p = call(app, 'GET', '/api/agent/profiles')[1]['profiles']
    me = next(x for x in p if x['id'] == pid)
    assert me['base_tailored'] and me['base_key'], 'the economy base is made once and kept'

    # A second scan never proposes the same job again.
    call(app, 'POST', '/api/agent/scan', {'profile': pid})
    q = wait_for(app, pid, lambda j: not j['scanning'])
    keys = [(i['company'].lower(), i['title'].lower()) for i in q['items']]
    assert len(keys) == len(set(keys))

    st, j = call(app, 'POST', '/api/agent/applied', {'id': first['id']})
    assert st == 200, j
    app_id = j['application']['id']
    st, j = call(app, 'GET', '/api/application?id=' + app_id)
    a = j['application']
    assert a['status'] == 'applied' and a['source'] == 'agent'
    assert {x['kind'] for x in a['artifacts']} == {'tailored_resume', 'cover_letter'}

    others = [i['id'] for i in q['items'] if i['status'] == 'proposed']
    if others:
        st, j = call(app, 'POST', '/api/agent/skip', {'ids': others})
        assert st == 200 and j['skipped'] == len(others)


def test_agent_profile_needs_a_resume_and_titles_to_scan(app):
    st, j = call(app, 'POST', '/api/agent/profiles', {'name': 'Empty', 'active': False})
    pid = j['profile']['id']
    st, j = call(app, 'POST', '/api/agent/scan', {'profile': pid})
    assert st == 200            # starts; the scan itself reports why it cannot run (in the server log)
    st, j = call(app, 'POST', '/api/agent/scan', {'profile': 'nope'})
    assert st == 404
    st, j = call(app, 'POST', '/api/agent/profiles', {'name': ''})
    assert st == 400 and 'name is required' in j['error']
    call(app, 'POST', '/api/agent/profiles/delete', {'id': pid})


def test_the_best_new_matches_are_prepared_without_asking(app, fixture_resume):
    """auto_prepare: the top N of each scan are approved and prepared right away (kits ready on arrival)."""
    st, j = call(app, 'POST', '/api/agent/profiles', {'name': 'Fast', 'targets': 'Senior Data Analyst',
                                                      'base_resume': fixture_resume, 'min_fit': 0, 'daily_limit': 4,
                                                      'auto_prepare': 2, 'active': False})
    pid = j['profile']['id']
    assert j['profile']['auto_prepare'] == 2
    call(app, 'POST', '/api/agent/scan', {'profile': pid})
    q = wait_for(app, pid, lambda j: not j['scanning'] and j['items']
                 and not any(i['status'] in ('approved', 'preparing') for i in j['items']), timeout=90)
    st_by_fit = [i['status'] for i in sorted(q['items'], key=lambda i: -i['fit'])]
    assert st_by_fit.count('ready') == 2, st_by_fit
    assert all(s == 'proposed' for s in st_by_fit if s != 'ready')
    call(app, 'POST', '/api/agent/profiles/delete', {'id': pid})


def test_apply_opens_the_posting_for_a_prepared_job(app, fixture_resume):
    """Without the form filler (APEX_FORM_FILL=0 in tests) Apply hands back the posting link; a PDF is checked."""
    st, j = call(app, 'POST', '/api/agent/profiles', {'name': 'Applier', 'targets': 'Data Analyst II', 'min_fit': 0,
                                                      'base_resume': fixture_resume, 'daily_limit': 1, 'auto_prepare': 1,
                                                      'active': False})
    pid = j['profile']['id']
    call(app, 'POST', '/api/agent/scan', {'profile': pid})
    q = wait_for(app, pid, lambda j: not j['scanning'] and j['items'] and j['items'][0]['status'] in ('ready', 'failed'))
    item = q['items'][0]
    assert item['status'] == 'ready', item
    st, j = call(app, 'GET', '/api/agent/item?id=' + item['id'])
    assert j['item']['kit']['struct']['name'], 'the kit carries the parsed resume for the PDF'
    st, j = call(app, 'POST', '/api/agent/apply', {'id': item['id'], 'pdf_b64': ''})
    assert st == 200 and j['mode'] == 'link' and j['url'] == item['url']
    call(app, 'POST', '/api/agent/profiles/delete', {'id': pid})


def test_evidence_vault_api(app):
    st, j = call(app, 'POST', '/api/facts', {'text': 'Cut p95 latency of the RAG API from 2.1s to 600ms', 'topic': 'ApiCo'})
    assert st == 201 and j['fact']['source'] == 'manual', j
    fid = j['fact']['id']
    st, j = call(app, 'POST', '/api/facts', {'text': 'cut p95 latency of the RAG API from 2.1s to 600ms', 'topic': 'apico'})
    assert st == 200 and j['duplicate'] is True
    st, j = call(app, 'GET', '/api/facts')
    assert st == 200 and any(f['id'] == fid for f in j['facts'])
    st, j = call(app, 'POST', '/api/facts', {'text': '  '})
    assert st == 400
    st, j = call(app, 'POST', '/api/facts/delete', {'id': fid})
    assert st == 200
    st, j = call(app, 'POST', '/api/facts/delete', {'id': fid})
    assert st == 404
    st, j = call(app, 'POST', '/api/facts/github', {'username': '  '})
    assert st == 400


def test_radar_and_digest_routes(app, fixture_resume):
    st, j = call(app, 'POST', '/api/agent/profiles', {'name': 'Radar', 'targets': 'AI Engineer', 'base_resume': fixture_resume,
                                                      'active': False})
    pid = j['profile']['id']
    st, j = call(app, 'GET', '/api/agent/radar?profile=' + pid)
    assert st == 200 and j == {'postings': 0, 'days': 0, 'skills': [], 'gaps': [], 'families': []}
    st, j = call(app, 'GET', '/api/agent/digest?profile=' + pid)
    assert st == 200 and j['new'] == 0 and j['ready'] == 0 and j['top'] == []
    st, j = call(app, 'POST', '/api/agent/radar/ideas', {'profile': pid})
    assert st == 400 and 'scan first' in j['error']
    st, j = call(app, 'GET', '/api/agent/radar?profile=nope')
    assert st == 404


def test_sign_ins_analytics_and_digest_routes(app, fixture_resume):
    st, j = call(app, 'GET', '/api/agent/logins')
    assert st == 200 and j == {'logins': []}
    st, j = call(app, 'POST', '/api/agent/logins/reveal', {'host': 'nowhere.myworkdayjobs.com'})
    assert st == 404
    st, j = call(app, 'GET', '/api/agent/analytics')
    assert st == 200 and set(j) >= {'funnel', 'by_family', 'by_source', 'recommendations', 'enough_data'}
    st, j = call(app, 'POST', '/api/agent/profiles', {'name': 'Digest', 'targets': 'AI Engineer', 'base_resume': fixture_resume,
                                                      'active': False, 'digest_email': 'me@example.com', 'followups': 'auto', 'skip_ghosts': False})
    assert st == 200 and j['profile']['digest_email'] == 'me@example.com' and j['profile']['followups'] == 'auto' and j['profile']['skip_ghosts'] is False
    pid = j['profile']['id']
    st, j = call(app, 'GET', '/api/agent/digest/preview?profile=' + pid)
    assert st == 200 and j['new'] == 0 and 'followups_due' in j and 'ghosts' in j
    st, j = call(app, 'POST', '/api/agent/digest/send', {'profile': pid})
    assert st == 400 and 'not set up' in j['error'], 'no SMTP in tests: a clear message, nothing sent'
    st, j = call(app, 'POST', '/api/agent/profiles', {'name': 'Bad', 'targets': 'AI Engineer', 'digest_email': 'not-an-address'})
    assert st == 400
    st, j = call(app, 'POST', '/api/agent/followups/run', {})
    assert st == 200 and set(j) == {'drafted', 'sent', 'due', 'ghosted'}


def test_follow_up_send_needs_an_address(app):
    st, j = call(app, 'POST', '/api/applications', {'company': uniq('FU'), 'role': 'AI Engineer', 'status': 'applied'})
    aid = j['application']['id']
    st, j = call(app, 'POST', '/api/applications/followup/send', {'id': aid})
    assert st == 400 and 'no recruiter address' in j['error']
    st, j = call(app, 'POST', '/api/applications/update', {'id': aid, 'contact_email': 'bad address'})
    assert st == 400
    st, j = call(app, 'POST', '/api/applications/update', {'id': aid, 'contact_email': 'rec@example.com', 'contact_name': 'Rec'})
    assert st == 200 and j['application']['contact_email'] == 'rec@example.com'
    st, j = call(app, 'POST', '/api/applications/followup/send', {'id': aid})
    assert st == 400 and 'not set up' in j['error']


def test_client_workspaces_are_isolated_per_request(app, fixture_resume):
    st, j = call(app, 'POST', '/api/clients', {'name': 'Workspace Test ' + uniq('')})
    assert st == 201 and j['client']['id'].startswith('workspace-test')
    cid = j['client']['id']
    H = {'X-Apex-Client': cid}
    st, j = call(app, 'GET', '/api/clients', headers=H)
    assert st == 200 and j['current'] == cid and any(c['id'] == cid for c in j['clients'])
    st, j = call(app, 'POST', '/api/agent/profiles', {'name': 'Dana', 'targets': 'Data Analyst', 'base_resume': fixture_resume, 'active': False}, headers=H)
    assert st == 200
    pid = j['profile']['id']
    st, j = call(app, 'GET', '/api/agent/profiles', headers=H)
    assert [p['id'] for p in j['profiles']] == [pid]
    st, j = call(app, 'GET', '/api/agent/profiles')
    assert pid not in [p['id'] for p in j['profiles']], 'the default workspace does not see the client profile'
    st, j = call(app, 'POST', '/api/facts', {'text': 'Client-only fact', 'topic': 'X'}, headers=H)
    assert st == 201
    st, j = call(app, 'GET', '/api/facts')
    assert all(f['text'] != 'Client-only fact' for f in j['facts'])
    st, j = call(app, 'GET', '/api/agent/queue?profile=' + pid)
    assert st == 404, 'a client profile is not reachable from the default workspace'
    st, j = call(app, 'GET', '/api/agent/profiles', headers={'X-Apex-Client': 'no-such-client'})
    assert st == 400 and 'unknown client' in j['error']
    st, j = call(app, 'POST', '/api/clients/delete', {'id': cid})
    assert st == 200 and j['removed']['profiles'] == 1 and j['removed']['facts'] == 1
    st, j = call(app, 'GET', '/api/agent/profiles', headers=H)
    assert st == 400


def test_report_activity_and_submit_now_routes(app, fixture_resume):
    import http.client
    st, j = call(app, 'POST', '/api/agent/profiles', {'name': 'Report', 'targets': 'AI Engineer', 'base_resume': fixture_resume, 'active': False,
                                                      'review_first': True, 'min_fit_submit': 70})
    assert st == 200 and j['profile']['review_first'] is True and j['profile']['min_fit_submit'] == 70
    pid = j['profile']['id']
    st, j = call(app, 'GET', '/api/agent/activity?profile=' + pid)
    assert st == 200 and j['activity'] == []
    st, j = call(app, 'GET', '/api/agent/report?profile=' + pid)
    assert st == 200 and j['profile'] == 'Report' and j['client'] == 'Me' and 'funnel' in j
    c = http.client.HTTPConnection('127.0.0.1', app.port, timeout=10)
    c.request('GET', '/report?profile=' + pid, headers={'Host': f'localhost:{app.port}'})
    r = c.getresponse()
    body = r.read().decode('utf-8')
    assert r.status == 200 and 'text/html' in r.getheader('Content-Type', '') and 'job search report' in body and 'Report' in body
    st, j = call(app, 'POST', '/api/agent/submit_now', {'id': 'nope'})
    assert st == 404
    st, j = call(app, 'POST', '/api/agent/report/send', {'profile': pid, 'to': 'not-an-address'})
    assert st == 400
    call(app, 'POST', '/api/agent/profiles/delete', {'id': pid})
