"""Every feature that writes about the candidate goes through the fact check.

Driven over real HTTP against the stub model (fake_openai.py), whose canned
answers include invented numbers and an "xxclaim" the audit flags, so each
route has to show what survives the check and withhold the rest.
"""
import http.client
import json

from playwright.sync_api import expect

from test_api import call
from test_apex import close_drawer, go, launch_fill


def sse(app, path, body, timeout=120):
    c = http.client.HTTPConnection('127.0.0.1', app.port, timeout=timeout)
    c.request('POST', path, body=json.dumps(body),
              headers={'Host': f'localhost:{app.port}', 'Content-Type': 'application/json'})
    r = c.getresponse()
    assert r.status == 200
    return [json.loads(f[6:]) for f in r.read().split(b'\n\n') if f.startswith(b'data: ')]


def data_of(events, kind):
    ev = [e for e in events if e.get('type') == kind]
    assert ev, f'no {kind}: {[e.get("type") for e in events]}'
    return ev[-1]['data']


def test_tailor_runs_the_evidence_engine(app, fixture_resume):
    events = sse(app, '/tailor', {'resume': fixture_resume, 'jobTitle': 'Senior Data Analyst', 'sector': 'general',
                                  'jobPosting': 'Meridian Health: Senior Data Analyst. SQL, Tableau, dashboards.'})
    d = data_of(events, 'tailor_data')
    assert d['verified'] is True
    assert 'Built recurring reports for the management team' in d['tailored_resume'], 'verified engine edit applied'
    assert 'Responsible for making reports' not in d['tailored_resume']
    assert 'University of Houston' in d['tailored_resume'], 'protected sections untouched'
    assert 'Tableau' in d['gaps'] and 'Tableau' not in d['tailored_resume'], 'a requirement it lacks is never added'
    assert (d['match_score_before'], d['match_score_after']) == (48, 74), 'scores come from the blind judge'
    assert d['changes'] and all(c['why'] for c in d['changes'])
    assert events[-1]['type'] == 'done'
    assert data_of(events, 'cost_data')['measured'] is True


def test_bullet_rewrites_are_checked(app, fixture_resume):
    rows = data_of(sse(app, '/bullets', {'resume': fixture_resume, 'jobTitle': 'Senior Data Analyst'}),
                   'bullet_data')['ranked_bullets']
    by = {r['text']: r for r in rows}
    assert by['Responsible for making reports for the management team']['rewrite'] == \
        'Built recurring reports for the management team'
    sql = by['Worked with SQL to get data from databases']
    assert sql['rewrite'] is None and any('"40"' in p for p in sql['rewrite_withheld']), 'invented 40% withheld'
    assert by['Was part of a team that did dashboards']['rewrite'] == 'Built dashboards with the team.', \
        'the flagged sentence was repaired away'
    assert by['Assisted with data entry and cleaning']['rewrite'] is None
    assert 'rewrite_withheld' not in by['Assisted with data entry and cleaning'], 'no rewrite is not a withheld one'


def test_bridge_reframes_and_story_are_checked(app, fixture_resume):
    d = data_of(sse(app, '/bridge', {'resume': fixture_resume, 'fromRole': 'Data Analyst', 'toRole': 'Financial Analyst'}),
                'bridge_data')
    r = d['experience_reframes']
    assert r[0]['reframed_bullet'] == 'Queried SQL databases to supply data for decisions'
    assert r[1]['reframed_bullet'] is None and any('"30"' in p for p in r[1]['reframed_bullet_withheld'])
    assert d['narrative'].startswith('Analyst who works with SQL')
    assert d['interview_bridge_answers'][0]['answer'] == 'I like working with numbers in SQL.'


def test_xray_fixes_are_checked(app, fixture_resume):
    k = data_of(sse(app, '/xray', {'resume': fixture_resume, 'jobTitle': 'Senior Data Analyst'}), 'xray_data')['killer_bullets']
    assert k[0]['fix'] == 'Built reports for the management team'
    assert k[1]['fix'] is None and k[1]['fix_withheld']


def test_cover_letter_is_checked_repaired_or_withheld(app, fixture_resume):
    body = {'resume': fixture_resume, 'jobTitle': 'Senior Data Analyst', 'company': 'Meridian Health',
            'posting': 'Senior Data Analyst. SQL required.'}
    st, j = call(app, 'POST', '/draft-cover-letter', body)
    assert st == 200 and j['verified'] and 'SQL every day' in j['letter']
    assert '\n\n' in j['letter'], 'paragraphs survive'

    st, j = call(app, 'POST', '/draft-cover-letter', dict(body, resume=fixture_resume + '\nCOVERLIE'))
    assert st == 200 and '40%' not in j['letter'] and 'SQL every day' in j['letter'], 'invented number repaired away'

    # The repair changes nothing: the check trims the one unsupported sentence and keeps the letter.
    st, j = call(app, 'POST', '/draft-cover-letter', dict(body, resume=fixture_resume + '\nCOVERLIE STUBBORN'))
    assert st == 200 and '40%' not in j['letter'] and 'SQL every day' in j['letter'], 'trimmed, not withheld'

    # Every sentence is unsupported, so nothing can be trimmed: one redraft, told what to avoid, is clean.
    st, j = call(app, 'POST', '/draft-cover-letter', dict(body, resume=fixture_resume + '\nCOVERALLBAD STUBBORN'))
    assert st == 200 and '40%' not in j['letter'] and 'SQL every day' in j['letter'], 'redrafted'

    # The redraft fails too: withheld, with the reason.
    st, j = call(app, 'POST', '/draft-cover-letter',
                 dict(body, resume=fixture_resume + '\nCOVERALLBAD ALWAYSBAD STUBBORN'))
    assert st == 422 and j['letter'] == '' and j['error'].startswith('Withheld') and '"40' in j['error']


def test_apply_all_merges_without_a_model_and_without_inventing(app, fake_openai, fixture_resume):
    before = len(fake_openai.calls)
    st, j = call(app, 'POST', '/apply-all-recommendations', {
        'original': fixture_resume, 'optimized': fixture_resume, 'addedKeywords': ['Tableau'],
        'bulletRewrites': [
            {'text': 'Responsible for making reports for the management team',
             'rewrite': 'Built recurring reports for the management team'},
            {'text': 'Worked with SQL to get data from databases', 'rewrite': 'Cut query time by 40% with SQL'},
            {'text': 'A line that is not in the resume', 'rewrite': 'Anything'}]})
    assert st == 200 and len(fake_openai.calls) == before, 'no model call'
    assert '- Built recurring reports for the management team' in j['merged']
    assert '40%' not in j['merged'] and 'Worked with SQL to get data from databases' in j['merged']
    assert 'Tableau' not in j['merged'] and j['keywords_not_added'] == ['Tableau']
    assert j['applied'] == {'lines': 1, 'keywords': 0} and len(j['skipped']) == 2


def test_withheld_text_is_explained_in_the_page(probe, fixture_resume):
    page = probe.page
    launch_fill(page, 'Senior Data Analyst', fixture_resume)
    close_drawer(page)
    go(page, 'bullets')
    page.click('#bullets-run')
    out = page.locator('#bullets-out')
    expect(out).to_contain_text('Built recurring reports for the management team', timeout=30000)
    expect(out.locator('.withheld')).to_contain_text("claimed something your resume doesn't show")
    expect(out).not_to_contain_text('40%')
    probe.assert_clean()
