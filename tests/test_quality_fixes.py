"""Fixes from the feature benchmark (2026-10-13): one bad sentence no longer costs a whole
text, advice may leave blanks for facts only the candidate knows, and job titles match on
what the job is (aliases, role family, seniority)."""
import json

import pytest

import apex_engine as E


def scripted_llm(*replies):
    """A model that returns the given JSON replies in order and records the prompts."""
    calls, queue = [], list(replies)

    def llm(system, user, **kw):
        calls.append(user)
        return json.dumps(queue.pop(0)) if queue else '{}'
    llm.calls = calls
    return llm


RESUME = ('Built the claims-summary tool on the OpenAI API, used by 35 adjusters. '
          'Added retrieval over policy documents with pgvector. Wrote integration tests.')


# ── trimming instead of withholding ──────────────────────────────────────────

def test_prune_drops_only_the_quoted_sentences():
    text = ('I built a claims-summary tool used by 35 adjusters. Its retrieval grounds every summary. '
            'I also wrote integration tests. I would love to bring this to your team.')
    cut = E._prune(text, ['"Its retrieval grounds every summary" - the evidence lists them separately'])
    assert 'grounds' not in cut and '35 adjusters' in cut and 'integration tests' in cut


def test_prune_refuses_when_too_little_is_left_or_nothing_matches():
    text = 'One claim here. Another claim there. A third one.'
    assert E._prune(text, ['"One claim here"', '"Another claim there"']) == ''     # 1 of 3 left
    assert E._prune(text, ['"a sentence that is not in the text"']) == ''
    assert E._prune('Short text. Two sentences.', ['"Short text"']) == ''          # too short to trim


def test_prune_matches_short_terms_as_whole_words():
    text = 'Shipped services in Go. Ran a good team. Wrote the docs. Led the on-call rotation.'
    cut = E._prune(text, ['term "Go" is not in the source'])
    assert 'services in Go' not in cut and 'good team' in cut


def test_a_letter_that_fails_twice_ships_without_the_bad_sentence():
    letter = ('I built a claims-summary tool on the OpenAI API, used by 35 adjusters. Its pgvector retrieval grounds '
              'every summary. I also wrote integration tests. I would welcome a conversation.')
    still_bad = {'results': [{'id': 'l', 'ok': False, 'problems': ['"Its pgvector retrieval grounds every summary" - '
                                                                   'not shown as connected']}]}
    llm = scripted_llm(still_bad,                                           # first audit
                       {'fixed': [{'id': 'l', 'text': letter}]},           # repair changes nothing
                       still_bad,                                           # second audit
                       {'results': [{'id': 'l', 'ok': True, 'problems': []}]})  # the trimmed letter passes
    ok, bad = E.verify_texts(llm, {'l': {'text': letter, 'evidence': RESUME}})
    assert 'l' in ok and 'grounds' not in ok['l'] and '35 adjusters' in ok['l'] and not bad
    assert len(llm.calls) == 4


def test_a_trimmed_text_that_still_fails_is_withheld():
    letter = 'I built the tool. It grounds every summary. I wrote tests. I lead the AI team.'
    bad_reply = {'results': [{'id': 'l', 'ok': False, 'problems': ['"It grounds every summary" - unsupported']}]}
    llm = scripted_llm(bad_reply, {'fixed': []}, bad_reply)
    ok, bad = E.verify_texts(llm, {'l': {'text': letter, 'evidence': RESUME}})
    assert ok == {} and bad['l']


# ── blanks the candidate fills in ────────────────────────────────────────────

def test_blanks_claim_nothing_in_advice_but_still_count_elsewhere():
    rewrite = 'Cut p99 latency [by X%] for [N] users by adding caching'
    ev = 'Reduced p99 latency of the authorization API by adding caching'
    llm = scripted_llm({'results': [{'id': 'r', 'ok': True}]})
    assert E.check_texts(llm, {'r': {'text': rewrite, 'evidence': ev, 'blanks': True}}) == {}
    assert 'blanks": true' in llm.calls[0] and 'square brackets' in llm.calls[0]
    probs = E.check_texts(scripted_llm(), {'r': {'text': 'Cut p99 latency by 40% for 2,000 users', 'evidence': ev,
                                                 'blanks': True}})
    assert probs['r'], 'a real number outside brackets is still a claim'


def test_a_bracketed_number_is_not_a_blank_without_the_flag():
    probs = E.check_texts(scripted_llm(), {'r': {'text': 'Cut latency [by 40%]', 'evidence': 'Cut latency'}})
    assert probs['r']


# ── summaries are trimmed, not lost ──────────────────────────────────────────

def test_the_summary_keeps_its_good_sentences_when_one_cannot_be_verified():
    resume = ('JO DOE\njo@example.com\n\nSUMMARY\nFrontend developer. Good team player.\n\nEXPERIENCE\n'
              'Frontend Developer - Peakline, Denver\n2021 - Present\n- Built reusable components for the design system\n'
              '- Improved page load time\n')
    doc = E.Doc(resume)
    target = {'title': 'Senior Frontend Engineer', 'keywords': [], 'supported': [], 'unsupported': []}
    bad = 'Frontend developer building a design system of reusable components. Expert in data-heavy dashboards.'
    rewrite_reply = {'edits': [{'id': 'S', 'lines': [bad]}], 'order': []}
    llm = scripted_llm(rewrite_reply,        # the retry proposes the same summary
                       {'results': [{'id': 'S', 'ok': True, 'problems': []}]})   # audit of the trimmed summary
    proposals = {'S': {'lines': [bad], 'why': '', 'keywords': []}}
    accepted, rejected = E._verify(llm, doc, target, {'blocks': {}, 'document': {}}, {}, proposals, lambda m: None)
    assert 'S' in accepted and 'S' not in rejected
    assert accepted['S']['lines'] == ['Frontend developer building a design system of reusable components.']


# ── the questions worth asking come first ────────────────────────────────────

def test_questions_rank_relevant_low_impact_lines_first():
    resume = ('JO DOE\n\nEXPERIENCE\nEngineer - Acme\n2020 - Present\n' +
              ''.join(f'- Did thing number {n} for the team\n' for n in range(1, 11)))
    doc = E.Doc(resume)
    ids = [b['id'] for b in doc.editable() if b['kind'] == 'bullet']
    blocks = {i: {'question': f'How many for {i}?', 'relevance': 2, 'impact': 4} for i in ids}
    blocks[ids[9]].update(relevance=5, impact=1)           # the last line matters most
    blocks[ids[8]].update(relevance=4, impact=2)
    diag = {'blocks': blocks, 'document': {'most_relevant': [ids[7]]}}
    r = E._result(doc, diag, {}, {}, {}, [], {})
    got = [q['id'] for q in r['questions']]
    assert len(got) == 8 and got[:3] == [ids[9], ids[8], ids[7]], got
    assert got[3:] == ids[:5], 'ties keep resume order'


# ── job titles ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize('title,query,want', [
    ('ML Engineer, Ranking', 'Senior Machine Learning Engineer', True),
    ('Front-End Engineer', 'Senior Frontend Engineer', True),
    ('SRE, Infrastructure', 'Senior Site Reliability Engineer', True),
    ('Software Engineer I', 'Software Engineer (New Grad)', True),
    ('LLM Engineer', 'AI Engineer', True),
    ('Member of Technical Staff, Applied AI', 'AI Engineer', True),
    ('Account Executive, AI Native', 'AI Engineer', False),
    ('Staff Software Engineer', 'Software Engineer (New Grad)', False),
    ('Machine Learning Intern', 'Senior Machine Learning Engineer', False),
    ('Engineering Manager - Backend', 'Staff Backend Engineer', False),
    ('Research Scientist, Machine Learning', 'Senior Machine Learning Engineer', True),
])
def test_titles_match_across_spellings_roles_and_levels(server, title, query, want):
    assert server.title_matches(title, query) is want


def test_seniority_bands(server):
    assert [server.seniority_band(t) for t in ('Software Engineer (New Grad)', 'Staff Engineer', 'Software Engineer II',
                                               'Data Analyst')] == ['entry', 'senior', 'mid', 'mid']


def test_off_role_text_scores_low_even_with_short_words(server):
    words = ['ai', 'engineer']
    assert server.score_listing('Account manager. We aim to grow air freight sales with fair pricing.', words, [], []) < 35
    assert server.score_listing('AI Engineer - build LLM features, RAG and evals for our platform. ' * 3,
                                words, [], []) >= 35


def test_entry_level_pay_counts_only_entry_level_postings(server, monkeypatch):
    jobs = [{'title': 'Software Engineer, New Grad', 'company': 'A', 'salary': '$120,000 - $140,000'},
            {'title': 'Junior Software Engineer', 'company': 'B', 'salary': '$100,000 - $120,000'},
            {'title': 'Software Engineer I', 'company': 'C', 'salary': '$110,000 - $130,000'},
            {'title': 'Software Engineer', 'company': 'D', 'salary': '$300,000 - $400,000'},
            {'title': 'Staff Software Engineer', 'company': 'E', 'salary': '$400,000 - $500,000'}]
    monkeypatch.setattr(server, 'fetch_structured_jobs', lambda *a, **k: {'jobs': jobs})
    pay = server.posted_pay('Software Engineer (New Grad)')
    assert pay['n'] == 3 and pay['median'] == 120000 and set(pay['companies']) == {'A', 'B', 'C'}
    assert server.posted_pay('Software Engineer')['n'] == 5        # a mid-level search counts every posting


# ── page budget: cuts that keep what matters ─────────────────────────────────

def test_cuts_fit_the_page_budget_but_never_lose_a_required_skill_or_a_role():
    filler = ' '.join(['service'] * 150)
    resume = ('JO DOE\n\nEXPERIENCE\nAI Engineer - Acme\n2022 - Present\n'
              f'- Built the RAG pipeline over policy documents {filler}\n'
              f'- Ran weekly demos for the sales team {filler}\n'
              f'- Helped at the internal hackathon {filler}\n'
              f'- Covered on-call during the holidays {filler}\n'
              f'- Ordered laptops for new hires {filler}\n'
              f'- Cleaned up old dashboards {filler}\n'
              f'- Answered questions in the help channel {filler}\n'
              'Support Engineer - Beta\n2020 - 2022\n'
              f'- Set up the ticket queue {filler}\n')
    doc = E.Doc(resume)
    target = {'title': 'AI Engineer', 'domain': 'ai_swe', 'seniority': 'mid', 'keywords': [],
              'supported': ['RAG'], 'unsupported': []}
    ids = {b['text'].split()[0]: b['id'] for b in doc.editable() if b['kind'] == 'bullet'}
    llm = scripted_llm({'cuts': [{'id': ids['Built'], 'why': 'x'},        # only place RAG shows: kept
                                 {'id': ids['Set'], 'why': 'x'},          # the support role's only bullet: kept
                                 {'id': ids['Helped'], 'why': 'minor'}, {'id': ids['Cleaned'], 'why': 'minor'},
                                 {'id': ids['Answered'], 'why': 'minor'}, {'id': ids['Ordered'], 'why': 'minor'},
                                 {'id': ids['Covered'], 'why': 'minor'}]})
    cuts = E._fit_budget(llm, doc, target, {}, [], lambda m: None)
    assert ids['Built'] not in cuts and ids['Set'] not in cuts
    assert ids['Helped'] in cuts and all(c['lines'] == [] and c['why'].startswith('Cut to fit 2 pages') for c in cuts.values())
    final = doc.render({i: [] for i in cuts})
    assert len(final.split()) <= 1000 + 40 or len(cuts) == 5          # stops once within budget


def test_no_cuts_outside_the_niche_or_within_budget():
    doc = E.Doc('JO DOE\n\nEXPERIENCE\nAnalyst - Acme\n2020 - Present\n- Built reports\n- Ran meetings\n')
    assert E._fit_budget(scripted_llm(), doc, {'title': 'Accountant', 'domain': None}, {}, [], lambda m: None) == {}
    assert E._fit_budget(scripted_llm(), doc, {'title': 'AI Engineer', 'domain': 'ai_swe'}, {}, [], lambda m: None) == {}
