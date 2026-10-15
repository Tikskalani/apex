"""The evidence vault: facts the candidate confirmed once are kept and reused as evidence
in every later resume (engine) and saved from the answers they give (server)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import apex_engine as E   # noqa: E402
import apex_store as S    # noqa: E402

RESUME = ('JO DOE\n\nEXPERIENCE\nAI Engineer - Acme\n2021 - Present\n- Built a support chatbot on GPT-4\n'
          '- Wrote evals for the chatbot\n\nPROJECTS\nDocChat - RAG over PDFs\n- Answers questions over uploaded PDFs\n')


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_DB', str(tmp_path / 'apex.db'))
    S.init()


def test_store_keeps_each_fact_once_and_deletes(db):
    f = S.add_fact('Cut support tickets by 30%', 'Acme')
    assert f and f['source'] == 'manual'
    assert S.add_fact('cut support tickets by 30%', 'acme') is None, 'same fact, same topic: kept once'
    assert S.add_fact('Cut support tickets by 30%', 'DocChat'), 'another topic is another fact'
    assert len(S.list_facts()) == 2 and S.engine_facts()[0].keys() == {'topic', 'text'}
    S.delete_fact(f['id'])
    assert len(S.list_facts()) == 1
    with pytest.raises(S.StoreError):
        S.delete_fact(f['id'])
    with pytest.raises(S.StoreError):
        S.add_fact('   ')
    with pytest.raises(S.StoreError):
        S.add_fact('x', source='rumor')


def test_facts_join_the_evidence_of_their_role_or_project():
    d = E.Doc(RESUME)
    d.attach_facts([{'topic': 'Acme', 'text': 'The chatbot handled 12,000 chats a month.'},
                    {'topic': 'docchat', 'text': 'DocChat has 30 GitHub stars.'},
                    {'topic': '', 'text': 'Speaks Spanish.'}])
    bullet = next(b for b in d.blocks if 'support chatbot' in b['text'])
    project = next(b for b in d.blocks if 'uploaded PDFs' in b['text'])
    assert '12,000 chats' in d.group_text(bullet['id']) and '30 GitHub stars' not in d.group_text(bullet['id'])
    assert '30 GitHub stars' in d.group_text(project['id'])
    assert 'Speaks Spanish' in d.evidence_text() and 'Speaks Spanish' not in d.text
    shown = d.numbered()
    assert 'FACTS THE CANDIDATE CONFIRMED' in shown and '12,000 chats' in shown and 'Speaks Spanish' in shown


def test_no_facts_no_change():
    d = E.Doc(RESUME)
    before = d.numbered()
    d.attach_facts(None)
    assert d.numbered() == before and d.evidence_text() == d.text


def test_answers_are_saved_with_their_role(server, tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_DB', str(tmp_path / 'apex.db'))
    server.store.init()
    d = E.Doc(RESUME)
    bullet = next(b for b in d.blocks if 'support chatbot' in b['text'])
    qs = [{'id': bullet['id'], 'question': 'How many chats a month?'}]
    assert server.remember_answers(RESUME, qs, {bullet['id']: '12,000', 'nope': 'x', 'B9': ''}) == 1
    assert server.remember_answers(RESUME, qs, {bullet['id']: '12,000'}) == 0, 'saved once'
    (f,) = server.store.list_facts()
    assert f['source'] == 'answer' and 'Acme' in f['topic'] and '12,000' in f['text'] and 'chats a month' in f['text']
    assert '12,000' in server.vault_text()


# ── market radar (what the scanned postings ask for vs what you show) ────────

POSTING = ('We are hiring an AI Engineer to build RAG and agentic workflows with LangChain and pgvector. '
           'You will write evals, ship Python services on AWS with Docker and Kubernetes, and own guardrails. ' * 4)


def test_radar_counts_full_postings_and_families(server):
    snap = {'postings': 0, 'terms': {}, 'families': {}}
    server.radar_count(snap, 'Senior AI Engineer', POSTING)
    server.radar_count(snap, 'Forward Deployed Engineer, AI', 'short snippet about RAG')
    assert snap['postings'] == 1, 'snippets count for the family only'
    assert snap['families'] == {'llm_app': 1, 'forward_deployed': 1}
    assert {'RAG', 'LangChain', 'pgvector', 'evals', 'Kubernetes'} <= set(snap['terms'])
    assert 'Rust' not in snap['terms']


def test_radar_shares_gaps_trend_and_digest(server, tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_DB', str(tmp_path / 'radar.db'))
    st = server.store
    st.init()
    resume = 'JO DOE\nEXPERIENCE\nAI Engineer - Acme\n- Built RAG over support docs in Python with pgvector\n' + 'x ' * 60
    pid = st.save_profile({'name': 'Me', 'targets': 'AI Engineer', 'base_resume': resume})['id']
    old = {'postings': 10, 'terms': {'RAG': 8, 'Kubernetes': 1}, 'families': {'llm_app': 10}}
    new = {'postings': 10, 'terms': {'RAG': 9, 'Kubernetes': 6, 'evals': 5, 'Python': 1}, 'families': {'llm_app': 7, 'mlops_platform': 3}}
    st.save_radar(pid, '2026-09-20', old)
    st.save_radar(pid, '2026-10-10', new)
    r = server.agent_radar(pid)
    by = {s['term']: s for s in r['skills']}
    assert r['postings'] == 10 and r['days'] == 1, 'the last 14 days only'
    assert by['RAG']['shown'] and not by['Kubernetes']['shown']
    assert by['Kubernetes']['share'] == 60 and by['Kubernetes']['trend'] == 50
    assert 'Python' in by and by['Python']['shown']
    assert [g['term'] for g in r['gaps']] == ['Kubernetes', 'evals']
    assert r['families'][0] == {'family': 'llm_app', 'label': server.apex_domains.label('llm_app'), 'share': 70}
    st.add_fact('Deployed the RAG service on Kubernetes (EKS) with autoscaling', 'Acme')
    assert 'Kubernetes' not in [g['term'] for g in server.agent_radar(pid)['gaps']], 'the vault counts as shown'
    d = server.agent_digest(pid)
    assert d['new'] == 0 and d['gaps'][0]['term'] == 'evals'


def test_project_ideas_from_gaps(server, tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_DB', str(tmp_path / 'ideas.db'))
    st = server.store
    st.init()
    pid = st.save_profile({'name': 'Me', 'targets': 'AI Engineer', 'base_resume': 'Built RAG in Python. ' * 10})['id']
    with pytest.raises(st.StoreError):
        server.radar_ideas(pid)                                  # nothing scanned: nothing to close
    st.save_radar(pid, '2026-10-10', {'postings': 10, 'terms': {'evals': 7}, 'families': {}})
    seen = {}

    def fake_gpt(system, user, **kw):
        seen['user'] = user
        return '{"ideas": [{"title": "Eval harness for the RAG bot", "closes": ["evals"], "plan": ["a", "b", "c"]}, {"nope": 1}]}'
    monkeypatch.setattr(server, 'gpt', fake_gpt)
    r = server.radar_ideas(pid)
    assert [i['title'] for i in r['ideas']] == ['Eval harness for the RAG bot']
    assert 'evals (70% of postings)' in seen['user'] and 'Built RAG in Python' in seen['user']
