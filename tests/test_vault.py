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
