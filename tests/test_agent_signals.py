"""Ghost-posting signals, kept sign-ins, and the company-board source read once and filtered locally."""
import json

import pytest


def test_ghost_signals_age_repost_evergreen_and_thin_copies(server):
    g = server.ghost_signals({'posted': '2026-08-01', 'url': 'https://jobs.ashbyhq.com/x/y', 'posting': 'x' * 500}, None, '2026-10-25')
    assert g['score'] == 2 and g['why'] == ['posted 85 days ago']
    g = server.ghost_signals({'posted': '2026-10-20', 'url': 'https://www.learn4good.com/x', 'posting': 'short'},
                             {'first_seen': '2026-10-20', 'reposted': 0}, '2026-10-25')
    assert g['score'] == 1 and g['why'] == ['thin aggregator copy']
    g = server.ghost_signals({'posted': '2026-10-24', 'url': 'https://boards.greenhouse.io/a/jobs/1',
                              'posting': 'We are always accepting applications for our talent pool. ' * 10}, None, '2026-10-25')
    assert g['score'] >= 3 and 'evergreen' in g['why'][0]
    g = server.ghost_signals({'posted': '', 'url': 'https://www.indeed.com/x', 'posting': 'y' * 800},
                             {'first_seen': '2026-08-20', 'reposted': 2}, '2026-10-25', direct_known=False)
    assert g['score'] == 4 and g['why'] == ['listed for 66 days', 'reposted 2x', "not on the employer's own board"]
    assert server.ghost_signals({'posted': '2026-10-24', 'url': 'https://jobs.lever.co/a/b', 'posting': 'z' * 800}, None, '2026-10-25') == {'score': 0, 'why': []}


def test_sightings_track_age_and_reposts(server, tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_DB', str(tmp_path / 's.db'))
    st = server.store
    st.init()
    s = st.note_sightings([{'job_key': 'acme|ai engineer', 'posted': '2026-10-01'}], '2026-10-02')
    assert s['acme|ai engineer']['times'] == 1 and s['acme|ai engineer']['first_seen'] == '2026-10-02'
    s = st.note_sightings([{'job_key': 'acme|ai engineer', 'posted': '2026-10-01'}], '2026-10-02')
    assert s['acme|ai engineer']['times'] == 1, 'the same day counts once'
    s = st.note_sightings([{'job_key': 'acme|ai engineer', 'posted': '2026-10-20'}], '2026-10-21')
    assert s['acme|ai engineer'] == {'first_seen': '2026-10-02', 'last_seen': '2026-10-21', 'times': 2, 'posted': '2026-10-20', 'reposted': 1}


def test_kept_sign_ins(server, tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_DB', str(tmp_path / 'l.db'))
    st = server.store
    st.init()
    st.save_login('Acme.wd5.myworkdayjobs.com', 'jo@example.com', 'Strong-1!')
    assert st.logins() == {'acme.wd5.myworkdayjobs.com': {'email': 'jo@example.com', 'password': 'Strong-1!'}}
    assert [l['host'] for l in st.list_logins()] == ['acme.wd5.myworkdayjobs.com'] and 'password' not in st.list_logins()[0]
    assert st.reveal_login('acme.wd5.myworkdayjobs.com')['password'] == 'Strong-1!'
    st.save_login('acme.wd5.myworkdayjobs.com', 'jo@example.com', 'Newer-2!')
    assert st.reveal_login('acme.wd5.myworkdayjobs.com')['password'] == 'Newer-2!', 'one sign-in per site'
    assert st.delete_login('acme.wd5.myworkdayjobs.com') is True
    with pytest.raises(st.StoreError):
        st.reveal_login('acme.wd5.myworkdayjobs.com')


def test_discovered_boards_are_loaded_and_filtered_locally(server, monkeypatch):
    assert len(server.ASHBY_BOARDS) + len(server.GREENHOUSE_BOARDS) + len(server.LEVER_BOARDS) > 150, 'data/boards.json merged in'
    assert server._BOARD_NAMES.get('langchain') or 'langchain' in server.ASHBY_BOARDS or 'langchain' in server.GREENHOUSE_BOARDS
    rows = [('ashby', 'acme', {'title': 'Senior AI Engineer', 'url': 'https://jobs.ashbyhq.com/acme/1', 'text': 'Build agents in Python ' * 30,
                               'location': 'Remote', 'posted': server.time.strftime('%Y-%m-%d')}),
            ('ashby', 'acme', {'title': 'Account Executive', 'url': 'https://jobs.ashbyhq.com/acme/2', 'text': 'sell', 'location': 'NY', 'posted': '2026-01-01'}),
            ('greenhouse', 'beta', {'title': 'AI Engineer', 'url': 'https://boards.greenhouse.io/beta/jobs/9', 'text': '', 'id': 9,
                                    'location': 'Houston, TX', 'posted': '2026-09-01'})]
    monkeypatch.setattr(server, 'all_board_rows', lambda: rows)
    monkeypatch.setattr(server, 'FIXTURE_JOBS', None)
    monkeypatch.setattr(server, 'http_get', lambda url, *a, **k: json.dumps({'content': '&lt;p&gt;Ship LLM features&lt;/p&gt;', 'updated_at': '2026-09-01T00:00:00Z'}))
    server._BOARD_CACHE.clear()
    jobs = server.company_board_jobs('AI Engineer')
    by = {j['url']: j for j in jobs}
    assert set(by) == {'https://jobs.ashbyhq.com/acme/1', 'https://boards.greenhouse.io/beta/jobs/9'}
    assert by['https://jobs.ashbyhq.com/acme/1']['fresh'] is True and by['https://boards.greenhouse.io/beta/jobs/9']['fresh'] is False
    assert 'Ship LLM features' in by['https://boards.greenhouse.io/beta/jobs/9']['text']
    assert server._fresh('2026-01-01') is False
