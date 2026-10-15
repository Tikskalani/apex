"""apex_apply.fill_form on local copies of the common application forms. It fills and never submits."""
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
def test_fills_the_form_and_never_submits(browser_page, tmp_path, kind):
    page = browser_page
    html = tmp_path / f'{kind}.html'
    html.write_text(f'<!doctype html><html><body>{FORMS[kind]}</body></html>', encoding='utf-8')
    pdf = tmp_path / 'Jo_Rivera_Resume.pdf'
    pdf.write_bytes(b'%PDF-1.4\n%fake\n')
    filled = apex_apply.fill_form(page, html.as_uri(), str(pdf), LETTER, CONTACT)
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
    assert page.locator('text=APEX filled what it could').count() == 1


def test_board_and_form_urls():
    assert apex_apply.board('https://job-boards.greenhouse.io/anthropic/jobs/123') == 'greenhouse'
    assert apex_apply.form_url('https://jobs.lever.co/spotify/abc') == 'https://jobs.lever.co/spotify/abc/apply'
    assert apex_apply.form_url('https://jobs.ashbyhq.com/openai/xyz?src=1') == 'https://jobs.ashbyhq.com/openai/xyz/application'
    assert apex_apply.form_url('https://example.com/jobs/1') == 'https://example.com/jobs/1'
    assert apex_apply.split_name('Maya Brooks, PT, DPT') == ('Maya', 'Brooks')
