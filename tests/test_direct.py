"""The employer's own application: aggregator links resolved to the company's ATS board, and
job links the user pastes read into the queue."""
import json

import pytest

GH_LIST = {'jobs': [{'id': 1, 'title': 'GTM Engineer - AI Agent Health, Cost & Growth Metrics', 'absolute_url': 'https://job-boards.greenhouse.io/langchain/jobs/1',
                     'location': {'name': 'Houston, TX'}},
                    {'id': 2, 'title': 'Account Executive', 'absolute_url': 'https://job-boards.greenhouse.io/langchain/jobs/2', 'location': {'name': 'NY'}}]}
GH_JOB = {'title': 'GTM Engineer - AI Agent Health, Cost & Growth Metrics', 'absolute_url': 'https://job-boards.greenhouse.io/langchain/jobs/1',
          'location': {'name': 'Houston, TX'}, 'content': '&lt;p&gt;Build agent health metrics with &lt;b&gt;LangSmith&lt;/b&gt; and Python.&lt;/p&gt;'}


def fake_http(table):
    def get(url, *a, **k):
        for key, val in table.items():
            if key in url:
                return json.dumps(val) if not isinstance(val, str) else val
        return None
    return get


def test_company_slugs(server):
    assert server.company_slugs('Cherry Bekaert')[:3] == ['cherrybekaert', 'cherry-bekaert', 'cherry']
    assert server.company_slugs('Bain & Company')[0] == 'bain'
    assert 'langchain' in server.company_slugs('LangChain, Inc.')
    assert server.needs_resolving('https://bebee.com/x') and not server.needs_resolving('https://jobs.ashbyhq.com/a/b')


def test_aggregator_link_resolves_to_the_employers_board(server, monkeypatch):
    monkeypatch.setattr(server, 'http_get', fake_http({'greenhouse.io/v1/boards/langchain/jobs/1': GH_JOB,
                                                        'greenhouse.io/v1/boards/langchain/jobs': GH_LIST}))
    server._DIRECT_CACHE.clear()
    d = server.find_direct_posting('LangChain', 'GTM Engineer - AI Agent Health, Cost & Growth Metrics')
    assert d and d['url'].endswith('/jobs/1') and d['source'] == 'Greenhouse' and 'LangSmith' in d['posting']
    assert server.find_direct_posting('LangChain', 'Chief Financial Officer') is None, 'a different role is never swapped in'
    c = {'title': 'GTM Engineer - AI Agent Health, Cost & Growth Metrics', 'company': 'LangChain', 'url': 'https://www.learn4good.com/x',
         'posting': 'short', 'reasons': {}}
    server.resolve_direct([c])
    assert c['url'].endswith('/jobs/1') and c['reasons']['direct'] and 'LangSmith' in c['posting']


def test_pasted_links_are_read_and_queued_approved(server, tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_DB', str(tmp_path / 'links.db'))
    server.store.init()
    page = '<html><title>Senior AI Engineer at Acme</title><body>' + 'We are hiring a Senior AI Engineer to build RAG systems in Python. ' * 20 + '</body></html>'
    monkeypatch.setattr(server, 'http_get', fake_http({'greenhouse.io/v1/boards/acme/jobs/77': dict(GH_JOB, title='Senior AI Engineer'),
                                                        'careers.acme.com': page, 'linkedin.com/jobs/view/123': 'Sign in to view this job'}))
    monkeypatch.setattr(server, 'gpt', lambda *a, **k: json.dumps({'title': 'Staff ML Engineer', 'company': 'Acme', 'location': 'Remote',
                                                                   'description': 'Build RAG systems in Python with evals.'}))
    monkeypatch.setattr(server, 'agent_kick', lambda *a, **k: True)
    server._DIRECT_CACHE.clear()
    pid = server.store.save_profile({'name': 'Me', 'targets': 'AI Engineer', 'base_resume': 'Built RAG in Python. ' * 10})['id']
    r = server.import_links(pid, 'https://job-boards.greenhouse.io/acme/jobs/77\nhttps://careers.acme.com/jobs/9\n'
                                 'https://www.linkedin.com/jobs/view/123456/\nnot-a-link')
    assert r['added'] == 2 and [i['status'] for i in r['items']] == ['approved', 'approved']
    assert {i['company'] for i in r['items']} == {'Acme'}
    assert [f['reason'][:20] for f in r['failed']] == ['the page shows a sig', 'not a web link']
    q = server.store.list_queue(pid)
    assert len(q) == 2 and all(i['status'] == 'approved' for i in q)
    r2 = server.import_links(pid, ['https://job-boards.greenhouse.io/acme/jobs/77'])
    assert r2['added'] == 0 and r2['items'][0]['status'] == 'approved', 'pasting a job twice does not duplicate it'
    with pytest.raises(server.store.StoreError):
        server.import_links(pid, '')


def test_linkedin_links_are_normalised(server):
    assert server._linkedin_view('https://www.linkedin.com/jobs/search/?currentJobId=4312345678&f_TPR=r86400') == \
        'https://www.linkedin.com/jobs/view/4312345678/'
    assert server._linkedin_view('https://www.linkedin.com/jobs/view/senior-ai-engineer-at-acme-4312345678?refId=x') == \
        'https://www.linkedin.com/jobs/view/4312345678/'
