"""apex_apply on local copies of the common application forms: it fills them, answers the screening
questions, and submits only when asked and nothing required is left."""
import pytest

import apex_apply

CONTACT = {'name': 'Jo Rivera, DPT', 'email': 'jo@example.com', 'phone': '555-0100',
           'linkedin': 'https://linkedin.com/in/jo', 'github': 'https://github.com/jo', 'location': 'Austin, TX'}
LETTER = 'Dear team, I would like to apply.'

FORMS = {
    'greenhouse': """<form onsubmit="window.SUBMITTED=1;return false">
      <input id="first_name"><input id="last_name"><input id="email" type="email"><input id="phone" type="tel">
      <label>Resume/CV <input id="resume" type="file"></label>
      <textarea id="cover_letter_text"></textarea>
      <label>LinkedIn Profile <input id="job_application_answers_attributes_0_text_value" name="linkedin_url"></label>
      <button type="submit">Submit application</button></form>""",
    'lever': """<form onsubmit="window.SUBMITTED=1;return false">
      <input name="name"><input name="email"><input name="phone">
      <input name="urls[LinkedIn]"><input name="urls[GitHub]">
      <label>Resume/CV <input name="resume" type="file"></label>
      <textarea name="comments"></textarea><button type="submit">Submit</button></form>""",
    'ashby': """<form onsubmit="window.SUBMITTED=1;return false">
      <input name="_systemfield_name"><input name="_systemfield_email"><input name="_systemfield_phone">
      <div><span>Resume</span><input id="_systemfield_resume" type="file"></div>
      <button type="submit">Submit Application</button></form>""",
    'labels': """<form onsubmit="window.SUBMITTED=1;return false">
      <label for="a">First name</label><input id="a"><label for="b">Last name</label><input id="b">
      <label for="c">Email address</label><input id="c"><label for="d">Mobile phone</label><input id="d">
      <label for="e">Upload your CV</label><input id="e" type="file">
      <button type="submit">Send</button></form>""",
}


@pytest.fixture
def browser_page(browser):          # the session's browser: a second Playwright cannot run beside it
    page = browser.new_page()
    yield page
    page.close()


@pytest.mark.parametrize('kind', list(FORMS))
def test_fills_the_form_and_submits_only_when_asked(browser_page, tmp_path, kind):
    page = browser_page
    html = tmp_path / f'{kind}.html'
    html.write_text(f'<!doctype html><html><body>{FORMS[kind]}</body></html>', encoding='utf-8')
    pdf = tmp_path / 'Jo_Rivera_Resume.pdf'
    pdf.write_bytes(b'%PDF-1.4\n%fake\n')
    r = apex_apply.fill_form(page, html.as_uri(), str(pdf), LETTER, CONTACT)
    filled = r['filled']
    assert r['status'] == 'filled'
    assert page.evaluate('window.SUBMITTED') is None, 'never submits'
    vals = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('input:not([type=file]), textarea')]
        .map(e => [e.id || e.name, e.value]))""")
    files = page.evaluate("""() => [...document.querySelectorAll('input[type=file]')].map(e => e.files.length)""")
    assert 'jo@example.com' in vals.values() and '555-0100' in vals.values(), vals
    if kind in ('greenhouse', 'labels'):
        assert 'Jo' in vals.values() and 'Rivera' in vals.values(), 'credentials (DPT) left out of the name'
    else:
        assert 'Jo Rivera' in vals.values(), vals
    assert files[0] == 1 and 'resume' in filled, (files, filled)
    if kind in ('greenhouse', 'lever'):
        assert LETTER in vals.values() and 'cover_letter' in filled
    if kind == 'lever':
        assert vals['urls[LinkedIn]'] == CONTACT['linkedin'] and vals['urls[GitHub]'] == CONTACT['github']
    assert page.locator('text=APEX filled this application').count() == 1


def test_board_and_form_urls():
    assert apex_apply.board('https://job-boards.greenhouse.io/anthropic/jobs/123') == 'greenhouse'
    assert apex_apply.form_url('https://jobs.lever.co/spotify/abc') == 'https://jobs.lever.co/spotify/abc/apply'
    assert apex_apply.form_url('https://jobs.ashbyhq.com/openai/xyz?src=1') == 'https://jobs.ashbyhq.com/openai/xyz/application'
    assert apex_apply.form_url('https://example.com/jobs/1') == 'https://example.com/jobs/1'
    assert apex_apply.split_name('Maya Brooks, PT, DPT') == ('Maya', 'Brooks')


ANSWERS = {'authorized': 'Yes', 'sponsorship': 'No', 'city': 'Houston', 'state': 'Texas'}
FULL = """<form id="f" onsubmit="event.preventDefault(); window.SUBMITTED = 1;
      document.body.innerHTML = '<h1>Thank you for applying! Your application has been received.</h1>'">
  <label for="fn">First Name*</label><input id="fn" required>
  <label for="ln">Last Name*</label><input id="ln" required>
  <label for="em">Email*</label><input id="em" type="email" required>
  <label for="cv">Resume/CV</label><input id="cv" type="file">
  <label for="auth">Are you legally authorized to work in the United States?*</label>
  <select id="auth" required><option value="">Select...</option><option>Yes</option><option>No</option></select>
  <fieldset><legend>Will you now or in the future require visa sponsorship?*</legend>
    <label><input type="radio" name="sp" value="y" required> Yes</label><label><input type="radio" name="sp" value="n"> No</label></fieldset>
  <label for="g">Gender</label><select id="g"><option>Select...</option><option>Male</option><option>Female</option>
    <option>I prefer not to answer</option></select>
  <label for="why">Why do you want to work here?*</label><textarea id="why" required></textarea>
  <label><input type="checkbox" id="ok" required> I certify that the information I provided is accurate and complete*</label>
  <label><input type="checkbox" id="sms"> Yes, send me text messages about jobs</label>
  EXTRA
  <button type="submit">Submit application</button></form>"""


def _form(tmp_path, extra=''):
    html = tmp_path / 'full.html'
    html.write_text(f'<!doctype html><html><body>{FULL.replace("EXTRA", extra)}</body></html>', encoding='utf-8')
    pdf = tmp_path / 'Jo_Rivera_Resume.pdf'
    pdf.write_bytes(b'%PDF-1.4\n%fake\n')
    return html.as_uri(), str(pdf)


def test_answers_every_question_and_submits(browser_page, tmp_path):
    page = browser_page
    url, pdf = _form(tmp_path)
    asked = []
    r = apex_apply.fill_form(page, url, pdf, LETTER, CONTACT, ANSWERS,
                             ask=lambda q, opts: asked.append(q) or 'Your RAG work matches what I have built.',
                             do_submit=True, shot_path=str(tmp_path / 'confirm.png'))
    assert r['status'] == 'submitted' and 'application has been received' in r['detail'], r
    assert asked == ['Why do you want to work here?*'], 'only the free-text question goes to the model'
    assert (tmp_path / 'confirm.png').exists(), 'a screenshot of the confirmation is kept'


def test_never_submits_with_a_required_question_unanswered(browser_page, tmp_path):
    page = browser_page
    url, pdf = _form(tmp_path, '<label for="yrs">Years of Kubernetes in production*</label><input id="yrs" required>')
    r = apex_apply.fill_form(page, url, pdf, LETTER, CONTACT, ANSWERS, ask=lambda q, opts: None, do_submit=True)
    assert r['status'] == 'needs_you' and page.evaluate('window.SUBMITTED') is None
    assert any('Kubernetes' in m for m in r['missing']) and any('Why do you want' in m for m in r['missing'])
    vals = page.evaluate("""() => ({auth: document.getElementById('auth').value, g: document.getElementById('g').value,
        sp: (document.querySelector('input[name=sp]:checked') || {}).value, ok: document.getElementById('ok').checked,
        sms: document.getElementById('sms').checked})""")
    assert vals == {'auth': 'Yes', 'g': 'I prefer not to answer', 'sp': 'n', 'ok': True, 'sms': False}, vals


def test_factual_answers_are_never_guessed():
    q = {'label': 'Are you legally authorized to work in the US?*', 'kind': 'select', 'options': ['Yes', 'No'], 'required': True}
    assert apex_apply.decide(q, {}, CONTACT, ask=lambda *a: 'Yes') is None, 'not set: left for the person, not asked'
    assert apex_apply.decide(q, {'authorized': 'No'}, CONTACT) == 'No'
    eeo = {'label': 'Veteran Status', 'kind': 'select', 'options': ['I am a veteran', 'I am not a veteran', 'I decline to self-identify']}
    assert apex_apply.decide(eeo, {}, CONTACT) == 'I decline to self-identify'
    assert apex_apply.decide(eeo, {'veteran': 'I am not a veteran'}, CONTACT) == 'I am not a veteran'
    co = {'label': 'Current/Most Recent Company Name', 'kind': 'text', 'options': [], 'required': True}
    assert apex_apply.decide(co, {}, dict(CONTACT, company='Acme')) == 'Acme'
    sms = {'label': 'Yes, I consent to receive text messages', 'kind': 'checkbox', 'options': ['Yes'], 'required': False}
    assert apex_apply.decide(sms, {}, CONTACT) is None, 'optional opt-ins stay unticked'


def test_company_career_pages_open_the_greenhouse_form():
    assert apex_apply.form_url('https://www.samsara.com/company/careers/roles/8024110?gh_jid=8024110') == \
        'https://job-boards.greenhouse.io/embed/job_app?token=8024110'
