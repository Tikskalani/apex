"""Drift on like-for-like data, posted pay, and whole-word requirement matching.
Uses the `server` fixture (a key-free copy of agent_server.py)."""
import pytest

RESUME = ('JANE DOE\nSUMMARY\nData analyst.\nEXPERIENCE\nAnalyst, Acme (2020 - Present)\n'
          '- Built weekly reporting in SQL and Excel for 12 managers\n- Maintained dashboards\nEDUCATION\nBS Math\n'
          'SKILLS\nSQL, Excel')


def market(*names_pcts):
    return {'frequency': [{'name': n, 'pct': p} for n, p in names_pcts]}


def test_drift_scores_the_same_resume_against_then_and_now(server):
    then = [{'name': 'SQL', 'pct': 70}, {'name': 'Excel', 'pct': 60}, {'name': 'Access', 'pct': 40}]
    now = market(('SQL', 75), ('Python', 60), ('Tableau', 55), ('Excel', 30))
    r = server.drift_result(RESUME, then, now, baseline_score=99, postings=12)
    base, _ = server.ats_score(RESUME, ['SQL', 'Excel', 'Access'])
    cur, _ = server.ats_score(RESUME, ['SQL', 'Python', 'Tableau', 'Excel'])
    assert (r['baseline_score'], r['current_score'], r['drift']) == (base, cur, cur - base)
    assert r['baseline_score'] != 99, 'the stored score is not compared with a different measurement'
    assert r['new_keywords'] == ['Python', 'Tableau']
    assert set(r['faded_keywords']) == {'Excel', 'Access'}          # 60 -> 30, and gone
    assert r['postings'] == 12 and 'counted in today' in r['basis']


def test_drift_without_a_stored_list_falls_back_to_the_stored_score(server):
    r = server.drift_result(RESUME, [], market(('SQL', 70)), baseline_score=40, postings=9)
    assert r['baseline_score'] == 40 and r['new_keywords'] == [] and 'older run' in r['basis']


@pytest.mark.parametrize('text,want', [
    ('$120,000 - $150,000', (120000, 150000)), ('120k-150k', (120000, 150000)), ('$55/hr', (114400, 114400)),
    ('$95000 - $', (95000, 95000)), ('', None), ('competitive', None), ('$1 - $2', None),
])
def test_parse_salary(server, text, want):
    assert server.parse_salary(text) == want


def test_posted_pay_from_postings_that_state_it(server):
    pay = server.posted_pay('Data Analyst')            # fixture jobs: 4 of 5 state a range
    assert pay['n'] == 4 and pay['p25'] <= pay['median'] <= pay['p75']


@pytest.mark.parametrize('needle,hay,want', [
    ('Go', 'good experience a while ago', False), ('Go', 'services in Go and Python', True),
    ('SOC operations', 'associate for warehouse operations', False), ('RAG', 'storage averages', False),
    ('patient education', 'educated patients and families', True), ('Excel', 'excellent communication', False),
    ('machine learning', 'built machine learning models', True), ('dashboards', 'maintained a dashboard', True),
])
def test_requirement_matching_is_whole_word(server, needle, hay, want):
    assert server._present(needle, server._norm(hay)) is want


def test_stem_cache_never_mixes_texts_of_equal_length(server):
    a, b = server._norm('python sql dashboards'), server._norm('tableau excel reports')
    assert len(a) == len(b)
    assert server._present('python', a) and not server._present('python', b)
