"""Closing the loop: job emails move tracked applications forward (the page asks first), and
an interview prep pack whose outlines and stories are fact-checked against your evidence."""
import json

import pytest


def apps(*rows):
    return [{'id': f'a{i}', 'company': c, 'role': r, 'status': s, 'updated_at': f'2026-10-0{i + 1}'}
            for i, (c, r, s) in enumerate(rows)]


def test_emails_match_applications_and_propose_forward_moves(server):
    tracked = apps(('Acme AI, Inc.', 'AI Engineer', 'applied'), ('Globex', 'ML Engineer', 'interview'),
                   ('Initech', 'Forward Deployed Engineer', 'offer'), ('Hooli', 'AI Engineer', 'rejected'))
    rows = [{'company': 'Acme AI', 'role': 'AI Engineer', 'status': 'interview_invite'},
            {'company': 'Globex Corporation', 'role': '', 'status': 'interview_followup'},   # already there
            {'company': 'Globex', 'role': '', 'status': 'offer'},
            {'company': 'Initech', 'role': '', 'status': 'rejected'},                        # an offer stays
            {'company': 'Hooli', 'role': '', 'status': 'interview_invite'},                  # closed stays closed
            {'company': 'Umbrella', 'role': '', 'status': 'interview_invite'},               # not tracked
            {'company': 'Acme AI', 'role': '', 'status': 'recruiter_outreach'}]
    server.match_inbox(rows, tracked)
    assert [r.get('update_to') for r in rows] == ['interview', None, 'offer', None, None, None, None]
    assert [r.get('match', {}).get('id') for r in rows] == ['a0', 'a1', 'a1', 'a2', 'a3', None, 'a0']


def test_role_breaks_ties_between_applications_at_one_company(server):
    tracked = apps(('Acme', 'Data Engineer', 'applied'), ('Acme', 'AI Engineer', 'applied'))
    rows = server.match_inbox([{'company': 'Acme', 'role': 'AI Engineer', 'status': 'rejected'}], tracked)
    assert rows[0]['match']['id'] == 'a1' and rows[0]['update_to'] == 'rejected'


RESUME = ('JO DOE\nEXPERIENCE\nAI Engineer - Acme\n- Built a support chatbot on GPT-4 used by 40 agents\n'
          '- Wrote evals for the chatbot\n' + 'Python, RAG, pgvector. ' * 5)


def test_prep_pack_keeps_only_checked_outlines_and_stories(server, tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_DB', str(tmp_path / 'prep.db'))
    server.store.init()
    a, _ = server.store.create_application({'company': 'Acme', 'role': 'AI Engineer', 'status': 'interview'})
    pack = {'focus': ['RAG quality'], 'review': ['vector indexes'], 'ask': ['How do you run evals?'],
            'questions': [{'q': 'Tell me about a RAG system', 'kind': 'technical', 'why': 'core', 'outline': 'The chatbot for 40 agents'},
                          {'q': 'Biggest scale?', 'kind': 'technical', 'why': 'scale', 'outline': 'Served 10M users'}],
            'stories': [{'title': 'Chatbot', 'situation': 'Support load', 'action': 'Built it', 'result': '40 agents use it'},
                        {'title': 'Invented', 'situation': 'x', 'action': 'Led 12 engineers', 'result': 'y'}]}
    seen = {}
    monkeypatch.setattr(server, 'gpt', lambda system, user, **kw: seen.setdefault('user', user) and json.dumps(pack))

    def checked(items, unsupported, allowed, note):
        bad = {k: ['not shown'] for k, v in items.items() if '10M' in v['text'] or '12 engineers' in v['text']}
        return {k: v['text'] for k, v in items.items() if k not in bad}, bad
    monkeypatch.setattr(server, 'fact_checked', checked)
    server.store.add_fact('The chatbot cut first-response time from 4h to 2 min', 'Acme')
    r = server.interview_prep(a, RESUME)
    assert [q['outline'] for q in r['questions']] == ['The chatbot for 40 agents', '']
    assert [s['title'] for s in r['stories']] == ['Chatbot'] and r['withheld'] == 2
    assert r['focus'] == ['RAG quality'] and r['from_posting'] is False
    assert '4h to 2 min' in seen['user'], 'the vault is evidence'
    with pytest.raises(server.store.StoreError):
        server.interview_prep(a, '')
