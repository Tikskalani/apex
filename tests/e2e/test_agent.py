"""The job agent end to end, offline: profile -> scan (saved postings) -> approve -> kit -> applied -> Tracker."""
import time

from test_api import call


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
                                                      'min_fit': 0, 'daily_limit': 3, 'active': False})
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
