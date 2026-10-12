"""apex_engine: structure-locked edits, the fact gate, per-bullet verification."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import apex_engine as E  # noqa: E402

MARCUS = (ROOT / 'tests' / 'e2e' / 'fixtures' / 'marcus_delgado.txt').read_text(encoding='utf-8')
TARGET = {'title': 'Senior Data Analyst', 'seniority': 'senior', 'sector': 'general',
          'keywords': [{'name': 'SQL', 'pct': 71}, {'name': 'Tableau', 'pct': 48}, {'name': 'dashboards', 'pct': 40}],
          'supported': ['SQL', 'dashboards', 'reporting'], 'unsupported': ['Tableau', 'Python', 'A/B testing']}


# ── parsing / rendering ──────────────────────────────────────────────────────

def test_parse_finds_summary_and_bullets_by_role():
    d = E.Doc(MARCUS)
    kinds = [(b['id'], b['kind']) for b in d.blocks]
    assert kinds[0] == ('S', 'summary')
    bullets = [b for b in d.blocks if b['kind'] == 'bullet']
    assert len(bullets) == 7
    assert bullets[0]['text'] == 'Responsible for making reports for the management team'
    assert 'Brightline' in bullets[0]['group'] and 'March 2021' in bullets[0]['group'], 'role = title + dates'
    assert 'Corva' in bullets[4]['group']
    assert not any('EDUCATION' in b['section'].upper() or 'SKILLS' in b['section'].upper() for b in bullets)


def test_render_without_edits_is_byte_identical():
    for text in (MARCUS, MARCUS.replace('\n', '\r\n')):
        assert E.Doc(text).render({}) == text.replace('\r\n', '\n')


def test_markdown_and_title_case_headers_are_recognised():
    md = MARCUS.replace('EXPERIENCE', '## Experience').replace('SUMMARY', '**Summary**')
    d = E.Doc(md)
    assert d.blocks[0]['id'] == 'S' and sum(b['kind'] == 'bullet' for b in d.blocks) == 7


def test_unmarked_pdf_style_bullets():
    text = ('JANE DOE\nEXPERIENCE\nAnalyst, Acme Corp\n2020 - 2024\n'
            'Built weekly revenue reporting for the finance leadership team across four regions\n'
            'Reduced month-end close effort by automating reconciliations in SQL and Excel\nEDUCATION\nBS Math')
    d = E.Doc(text)
    assert [b['kind'] for b in d.blocks] == ['bullet', 'bullet']


def test_render_splits_and_keeps_marker_and_protected_sections():
    d = E.Doc(MARCUS)
    out = d.render({'B2': ['Queried SQL databases for reporting data', 'Second idea'], 'S': ['New summary.']})
    assert '- Queried SQL databases for reporting data\n- Second idea' in out
    assert 'SUMMARY\nNew summary.\n' in out
    assert 'B.S. Business Administration, University of Houston, 2019' in out


# ── fact gate ────────────────────────────────────────────────────────────────

EVID = 'Data Analyst - Brightline Logistics\nMaintained weekly KPI reports used by 12 clinic managers using SQL and Excel'


@pytest.mark.parametrize('new,bad', [
    ('Maintained weekly KPI reports for 12 clinic managers', None),
    ('Maintained weekly KPI reports for twelve clinic managers', None),
    ('Maintained weekly KPI reports for 15 clinic managers', 'number "15"'),
    ('Cut reporting time by 40%', 'number "40"'),
    ('Built KPI reports in Tableau for 12 managers', 'adds "Tableau"'),
    ('Built KPI reports with PowerBI for 12 managers', 'term "PowerBI"'),
    ('Built SQL and Excel reporting for 12 clinic managers', None),
    ('Built a cross-functional, end-to-end KPI process', None),
])
def test_fact_gate(new, bad):
    probs = E.fact_gate(new, EVID, TARGET['unsupported'], EVID)
    if bad is None:
        assert probs == [], probs
    else:
        assert any(bad in p for p in probs), probs


# ── the pipeline with a scripted model ───────────────────────────────────────

class Script:
    """A fake model: answers by which system prompt is asking."""
    def __init__(self, edits, audit_bad=(), order=None, retry_edits=None):
        self.edits, self.audit_bad, self.order, self.retry_edits = edits, set(audit_bad), order or [], retry_edits
        self.calls = []

    def __call__(self, system, user, max_tokens=0, json_mode=False, effort=None, **_):
        self.calls.append(system[:20])
        if system == E.DIAGNOSE_SYSTEM:
            return json.dumps({'blocks': [{'id': 'B1', 'impact': 1, 'specificity': 1, 'scannability': 2, 'relevance': 3,
                                           'issues': ['"Responsible for" hides the action'],
                                           'question': 'How many managers used these reports each week?'},
                                          {'id': 'B2', 'impact': 2, 'specificity': 2, 'scannability': 3, 'relevance': 4,
                                           'issues': [], 'question': None}],
                               'document': {'problems': [{'issue': 'Summary is generic', 'fix': 'Lead with the role'}],
                                            'strengths': ['SQL'], 'summary_verdict': 'generic',
                                            'most_relevant': ['B2']}})
        if system == E.REWRITE_SYSTEM:
            retry = 'PREVIOUS ATTEMPT REJECTED' in user
            ed = self.retry_edits if (retry and self.retry_edits is not None) else self.edits
            return json.dumps({'edits': [{'id': k, 'lines': v, 'why': 'stronger', 'keywords': []} for k, v in ed.items()],
                               'order': [] if retry else self.order})
        if system == E.VERIFY_SYSTEM:
            items = json.loads(user.split('ITEMS:')[1].split('Return ONLY JSON')[0])
            return json.dumps({'results': [{'id': it['id'], 'ok': it['id'] not in self.audit_bad,
                                            'problems': ['adds scope'] if it['id'] in self.audit_bad else []}
                                           for it in items]})
        if system == E.JUDGE_SYSTEM:
            return json.dumps({'A': {'score': 50}, 'B': {'score': 50}, 'better': 'tie', 'why': 'x'})
        raise AssertionError('unexpected prompt')


def test_good_edits_survive_a_bad_one():
    llm = Script({'S': ['Data analyst who builds SQL reporting and dashboards for management.'],
                  'B1': ['Built recurring reports for the management team'],
                  'B2': ['Queried SQL databases in Tableau to extract reporting data']})   # Tableau: unsupported
    r = E.optimize(llm, MARCUS, TARGET, judge_it=False)
    ids = {c['id'] for c in r['changes']}
    assert {'S', 'B1'} <= ids and 'B2' not in ids, 'the bad edit is reverted alone'
    assert 'Built recurring reports for the management team' in r['final']
    assert 'Tableau' not in r['final']
    assert r['rejected'] and r['rejected'][0]['id'] == 'B2'
    assert 'University of Houston' in r['final']
    assert r['questions'][0]['id'] == 'B1' and 'How many managers' in r['questions'][0]['question']


def test_retry_fixes_a_rejected_edit():
    llm = Script({'B1': ['Built reports for 40 managers']},          # 40 is invented
                 retry_edits={'B1': ['Built recurring reports for the management team']})
    r = E.optimize(llm, MARCUS, TARGET, judge_it=False)
    assert [c['id'] for c in r['changes']] == ['B1'] and not r['rejected']
    assert 'for 40 managers' not in r['final']


def test_model_audit_veto_reverts_only_that_bullet():
    llm = Script({'B1': ['Built recurring reports for the management team'],
                  'B3': ['Led process improvements across the department']}, audit_bad={'B3'},
                 retry_edits={'B3': ['Led process improvements across the department']})
    r = E.optimize(llm, MARCUS, TARGET, judge_it=False)
    assert [c['id'] for c in r['changes']] == ['B1']
    assert 'Helped improve some processes' in r['final']


def test_answers_become_evidence():
    llm = Script({'B1': ['Built weekly reports used by 9 managers to plan staffing']})
    r = E.optimize(llm, MARCUS, TARGET, answers={'B1': '9 managers, weekly'}, judge_it=False)
    assert 'used by 9 managers' in r['final']
    assert not any(q['id'] == 'B1' for q in r['questions']), 'answered questions are not asked again'


def test_reorder_stays_within_a_role():
    llm = Script({}, order=[['B3', 'B1', 'B2', 'B4'], ['B5', 'B1']])   # 2nd crosses roles: ignored
    r = E.optimize(llm, MARCUS, TARGET, judge_it=False)
    exp = r['final'].split('EXPERIENCE')[1]
    assert exp.index('Helped improve some processes') < exp.index('Responsible for making reports')
    assert exp.index('Assisted with data entry') > exp.index('June 2019'), 'Corva bullets stayed in their role'


def test_unparseable_model_output_changes_nothing():
    def broken(system, user, **_):
        return 'Sorry, I cannot help with that.'
    r = E.optimize(broken, MARCUS, TARGET, judge_it=False)
    assert r['final'] == MARCUS and r['changes'] == []


def test_judge_runs_both_orders_and_averages():
    """Position bias cancels: the after version wins in both orders, scores average."""
    calls = []
    def llm(system, user, **_):
        a_is_before = 'BEFORE_TEXT' in user.split('=== A ===')[1].split('=== B ===')[0]
        calls.append(a_is_before)
        # a judge that likes position A by 4 points
        before, after = (44, 80) if a_is_before else (40, 84)
        return json.dumps({'A': {'score': before if a_is_before else after},
                           'B': {'score': after if a_is_before else before}})
    j = E.judge(llm, 'BEFORE_TEXT', 'AFTER_TEXT', TARGET)
    assert sorted(calls) == [False, True]
    assert (j['before'], j['after'], j['better']) == (42, 82, 'after')


def test_audit_batches_and_sends_each_role_once(monkeypatch):
    """Regression (real run): one oversized request was truncated, so the last
    edits were never checked and got reverted."""
    monkeypatch.setattr(E, 'AUDIT_BATCH', 3)
    d = E.Doc(MARCUS)
    seen = []
    def llm(system, user, **_):
        groups = json.loads(user.split('EVIDENCE GROUPS:')[1].split('ITEMS:')[0])
        items = json.loads(user.split('ITEMS:')[1].split('Return ONLY JSON')[0])
        seen.append((len(groups), [x['id'] for x in items]))
        return json.dumps({'results': [{'id': x['id'], 'ok': True} for x in items]})
    items = {f'B{i}': ['x'] for i in range(1, 8)}
    assert E.audit(llm, d, items, {}) == {}
    assert [ids for _, ids in seen] == [['B1', 'B2', 'B3'], ['B4', 'B5', 'B6'], ['B7']]
    assert seen[0][0] == 1 and seen[1][0] == 2, 'each role text appears once per request'


@pytest.mark.parametrize('new,bad', [
    ('Deployed the KPI reports to Kubernetes for 12 managers', 'name "Kubernetes"'),
    ('Built KPI reports for 12 clinic managers at Brightline Logistics', None),
    ('Built KPI reports for 12 clinic managers. Reports ran every March', None),
    ('Senior Data Analyst building KPI reports for 12 clinic managers', None),
])
def test_fact_gate_proper_nouns(new, bad):
    probs = E.fact_gate(new, EVID, (), EVID, allowed_words=['Senior', 'Data', 'Analyst'])
    if bad is None:
        assert probs == [], probs
    else:
        assert any(bad in p for p in probs), probs


def test_reorder_never_mislabels_changes():
    """Regression (real run): reordering moved content between slots, so the
    change list paired one bullet's 'before' with another bullet's 'after'."""
    llm = Script({'B1': ['Built recurring reports for the management team']}, order=[['B3', 'B1', 'B2', 'B4']])
    r = E.optimize(llm, MARCUS, TARGET, judge_it=False)
    assert [(c['id'], c['before'], c['after']) for c in r['changes']] == [
        ('B1', 'Responsible for making reports for the management team', ['Built recurring reports for the management team'])]
    exp = r['final'].split('EXPERIENCE')[1]
    assert exp.index('Helped improve some processes') < exp.index('Built recurring reports') < exp.index('Worked with SQL')
    assert r['order'] == [['B3', 'B1', 'B2', 'B4']]


def test_section_reorder_moves_whole_sections_and_keeps_contact_first():
    d = E.Doc(MARCUS)
    sec = d.valid_section_order(['SUMMARY', 'SKILLS', 'EXPERIENCE', 'EDUCATION'])
    out = d.render({}, (), sec)
    assert out.startswith('MARCUS DELGADO')
    assert out.index('SKILLS') < out.index('EXPERIENCE') < out.index('EDUCATION')
    assert sorted(out.split()) == sorted(MARCUS.split()), 'nothing lost or duplicated'
    assert d.valid_section_order(['SUMMARY', 'EXPERIENCE']) is None, 'partial lists are ignored'


def test_summary_is_checked_against_the_whole_resume():
    """Regression (real run): the fact check saw only the old summary as evidence,
    so a summary citing a real number from a bullet was reverted."""
    seen = {}
    class Spy(Script):
        def __call__(self, system, user, **kw):
            if system == E.VERIFY_SYSTEM:
                seen['groups'] = json.loads(user.split('EVIDENCE GROUPS:')[1].split('ITEMS:')[0])
            return super().__call__(system, user, **kw)
    llm = Spy({'S': ['Data analyst who works with SQL to get data from databases for the management team.']})
    r = E.optimize(llm, MARCUS, TARGET, judge_it=False)
    ev = seen['groups']['WHOLE RESUME']
    assert 'Corva Retail Group' in ev and 'University of Houston' in ev
    assert [c['id'] for c in r['changes']] == ['S']


@pytest.mark.parametrize('new,ok', [
    # real-run false positives
    ('Ran post-deploy health checks on the reporting system', True),
    ('Cut write-offs by tracking stock at lot level', True),
    ('Validated with tests against real PostgreSQL', True),
    # still caught
    ('Validated with tests against real MongoDB', False),
    ('Built a scikit-learn ranking model', False),
])
def test_fact_gate_compounds_and_aliases(new, ok):
    ev = 'Ran health checks after each deploy. Staff write off stock at lot level. Tests against a real Postgres.'
    probs = E.fact_gate(new, ev, (), ev)
    assert (probs == []) is ok, probs


# ── fact check for text that is not a resume edit ────────────────────────────

class TextScript:
    """Stub model for check_texts / verify_texts: the audit flags items whose text
    contains a flagged word; the repair returns scripted text per id."""

    def __init__(self, flag=(), repairs=None):
        self.flag, self.repairs, self.calls = set(flag), repairs or {}, []

    def __call__(self, system, user, **_):
        self.calls.append(system)
        items = json.loads(user.split('ITEMS:')[1].split('Return ONLY JSON')[0])
        if system == E.VERIFY_SYSTEM:
            return json.dumps({'results': [
                {'id': it['id'], 'ok': not any(w in it['text'] for w in self.flag),
                 'problems': ['claims more than the resume shows']} for it in items]})
        if system == E.REPAIR_SYSTEM:
            return json.dumps({'fixed': [{'id': it['id'], 'text': self.repairs.get(it['id'], it['text'])}
                                         for it in items]})
        raise AssertionError('unexpected prompt')


def test_text_check_gate_runs_before_the_model():
    llm = TextScript()
    bad = E.check_texts(llm, {'letter': {'text': 'I cut reporting time by 40% using SQL.', 'evidence': EVID}})
    assert any('number "40"' in p for p in bad['letter'])
    assert llm.calls == [], 'a gate failure never reaches the model audit'


def test_text_check_context_names_pass_but_unshown_skills_fail():
    posting = 'Meridian Health is hiring. Tableau required.'
    ok = E.check_texts(TextScript(), {'l': {'text': 'Meridian Health needs KPI reporting. I build it in SQL.',
                                             'evidence': EVID, 'context': posting}})
    assert ok == {}, ok
    # A first-person sentence is a claim: only the evidence (or allowed words, e.g. the company) backs it.
    mixed = {'l': {'text': 'Meridian Health needs KPI reporting, which I build in SQL.', 'evidence': EVID,
                   'context': posting}}
    assert E.check_texts(TextScript(), mixed)
    assert E.check_texts(TextScript(), mixed, allowed_words=['Meridian', 'Health']) == {}
    bad = E.check_texts(TextScript(), {'l': {'text': 'I build KPI reports in Tableau.', 'evidence': EVID,
                                              'context': posting}}, unsupported=['Tableau'])
    assert any('adds "Tableau"' in p for p in bad['l'])


def test_verify_texts_repairs_once_then_withholds():
    llm = TextScript(flag={'ransformed'},
                     repairs={'a': 'Maintained weekly KPI reports for 12 clinic managers.',
                              'b': 'It transformed the business.'})
    ok, withheld = E.verify_texts(llm, {
        'a': {'text': 'Transformed the clinic with KPI reports.', 'evidence': EVID},
        'b': {'text': 'It transformed the business.', 'evidence': EVID},
        'c': {'text': 'Maintained KPI reports in SQL and Excel.', 'evidence': EVID},
        'd': {'text': '', 'evidence': EVID}})
    assert ok == {'a': 'Maintained weekly KPI reports for 12 clinic managers.',
                  'c': 'Maintained KPI reports in SQL and Excel.'}
    assert set(withheld) == {'b'}, 'the repair failed the check again, so it is withheld'
    assert llm.calls.count(E.REPAIR_SYSTEM) == 1, 'one repair, never a loop'


def test_verify_texts_fails_closed_on_an_unreadable_audit():
    ok, withheld = E.verify_texts(lambda s, u, **_: 'not json', {'a': {'text': 'Built KPI reports.', 'evidence': EVID}})
    assert ok == {} and withheld['a']


def test_text_check_sends_each_evidence_text_once():
    seen = []
    def llm(system, user, **_):
        seen.append(json.loads(user.split('EVIDENCE:')[1].split('CONTEXT:')[0]))
        items = json.loads(user.split('ITEMS:')[1].split('Return ONLY JSON')[0])
        return json.dumps({'results': [{'id': it['id'], 'ok': True} for it in items]})
    assert E.check_texts(llm, {k: {'text': 'Maintained KPI reports.', 'evidence': EVID} for k in 'abc'}) == {}
    assert len(seen) == 1 and list(seen[0].values()) == [EVID]


def test_fact_gate_numbers_inside_years_are_not_evidence():
    """Regression: "$2M" passed because "2" occurs inside "2021"."""
    ev = 'Analyst, Acme (March 2021 - Present)\nGrew the user base to 15,000 accounts and 1,200,000 events'
    assert any('number "2"' in p for p in E.fact_gate('Saved $2M in costs', ev))
    assert any('number "20"' in p for p in E.fact_gate('Led 20 analysts', ev))
    assert E.fact_gate('Grew the user base to 15K accounts and 1.2M events', ev) == []
    assert E.fact_gate('Analyst since 2021', ev) == []


def test_letter_vocabulary_is_not_mistaken_for_a_name():
    text = 'Dear Hiring Manager,\n\nI saw your post on LinkedIn. I maintain KPI reports in SQL.\n\nBest Regards'
    assert E.check_texts(TextScript(), {'l': {'text': text, 'evidence': EVID}}) == {}
