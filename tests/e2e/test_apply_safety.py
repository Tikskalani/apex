"""What the agent must never do on a form: treat a job board's alert box as an application, press a
report/share/alert button as Submit, or give up when the employer's own careers page has the job."""

import pytest

import apex_apply

CONTACT = {'name': 'Jo Rivera', 'email': 'jo@example.com', 'phone': '555-0100', 'location': 'Houston, TX'}
ALERT_PAGE = """<!doctype html><html><body><h1>Staff ML Engineer at Fute</h1>
  <form onsubmit="event.preventDefault(); window.ALERT_CREATED = 1">
    <label for="e">Email</label><input id="e" type="email"><label for="k">Keywords</label><input id="k" value="ml engineer">
    <label for="l">Location</label><input id="l" value="Houston"><label for="f">Frequency</label><select id="f"><option>Daily</option></select>
    <button type="submit">Create alert</button></form>
  <button onclick="window.REPORTED = 1">Report this listing</button>
  <a href="APPLY_HREF">Apply on company website</a>
</body></html>"""
APP_PAGE = """<!doctype html><html><body><h1>Staff ML Engineer</h1>
  <button onclick="window.REPORTED = 1">Report job</button>
  <form onsubmit="event.preventDefault(); window.SUBMITTED = 1; document.body.innerHTML = '<p>Thank you for applying!</p>'">
    <label for="fn">First Name*</label><input id="fn" required><label for="ln">Last Name*</label><input id="ln" required>
    <label for="em">Email*</label><input id="em" type="email" required><label for="cv">Resume</label><input id="cv" type="file">
    <button type="button" onclick="window.SAVED = 1">Save job</button>
    <button type="submit">Submit application</button></form>
</body></html>"""
CAREERS_PAGE = """<!doctype html><html><body><h1>Careers at Fute</h1>
  <a href="/nope">About us and our mission</a><a href="APP_HREF">Staff Machine Learning Engineer - Houston</a><a href="/x">Account Executive, Enterprise</a>
</body></html>"""


@pytest.fixture
def pg(browser):
    page = browser.new_page()
    yield page
    page.close()


def test_aggregator_hosts_are_never_application_forms():
    assert apex_apply.is_aggregator('https://us.trabajo.org/job-1') and apex_apply.is_aggregator('https://www.jobleads.com/us/job/x')
    assert apex_apply.is_aggregator('https://us.jobrapido.com/jobpreview/1') and not apex_apply.is_aggregator('https://jobs.ashbyhq.com/a/b')
    assert not apex_apply.is_aggregator('https://searchcareers.caci.com/careers/apply?pid=1')


def test_an_alert_form_is_not_an_application_and_no_wrong_button_is_pressed(pg, tmp_path):
    (tmp_path / 'alert.html').write_text(ALERT_PAGE.replace('APPLY_HREF', 'app.html'), encoding='utf-8')
    (tmp_path / 'app.html').write_text(APP_PAGE, encoding='utf-8')
    pg.goto((tmp_path / 'alert.html').as_uri())
    assert apex_apply.is_application_form(pg) is False
    assert apex_apply._submit_button(pg) is None or 'Report' not in apex_apply._submit_button(pg).inner_text()
    # the Apply link leads to the real form; nothing on the alert page was touched
    page = apex_apply.reach_form(pg, (tmp_path / 'alert.html').as_uri())
    assert page.url.endswith('app.html') and apex_apply.is_application_form(page) is True
    pdf = tmp_path / 'r.pdf'
    pdf.write_bytes(b'%PDF-1.4\n')
    r = apex_apply.fill_form(page, page.url, str(pdf), '', CONTACT, {}, ask=None, do_submit=True)
    assert r['status'] == 'submitted', r
    assert page.evaluate('[window.SUBMITTED, window.REPORTED, window.SAVED]') == [1, None, None], "only the form's Submit was pressed"


def test_report_and_save_buttons_are_never_submit(pg, tmp_path):
    (tmp_path / 'app.html').write_text(APP_PAGE.replace('<button type="submit">Submit application</button>', ''), encoding='utf-8')
    pg.goto((tmp_path / 'app.html').as_uri())
    assert apex_apply._submit_button(pg) is None
    status, detail = apex_apply.submit(pg)
    assert status == 'invalid' and pg.evaluate('[window.REPORTED, window.SAVED]') == [None, None]


def test_the_job_is_found_on_the_employers_careers_page(pg, tmp_path):
    (tmp_path / 'careers.html').write_text(CAREERS_PAGE.replace('APP_HREF', 'app.html'), encoding='utf-8')
    (tmp_path / 'app.html').write_text(APP_PAGE, encoding='utf-8')
    found = apex_apply.find_on_careers_site(pg, (tmp_path / 'careers.html').as_uri(), 'Staff ML Engineer')
    assert found is not None and found.url.endswith('app.html')
    assert apex_apply.find_on_careers_site(pg, (tmp_path / 'careers.html').as_uri(), 'Chief Financial Officer') is None


def test_cookie_banner_is_declined_before_the_form(pg, tmp_path):
    html = APP_PAGE.replace('<h1>', '<div id="cc" style="position:fixed;inset:0;background:#fff"><p>We use cookies</p>'
                            '<button onclick="window.ACCEPTED=1;cc.remove()">Accept all</button><button onclick="window.DECLINED=1;cc.remove()">Reject all</button></div><h1>')
    (tmp_path / 'app.html').write_text(html, encoding='utf-8')
    page = apex_apply.reach_form(pg, (tmp_path / 'app.html').as_uri())
    assert page.evaluate('[window.DECLINED, window.ACCEPTED]') == [1, None]
    assert apex_apply.is_application_form(page)


def test_citizenship_clearance_government_and_source_answers():
    C = dict(CONTACT, source='Job board')
    q = lambda label, opts: {'label': label, 'kind': 'combobox', 'options': opts, 'required': True}
    a = {'us_person': 'Yes', 'clearance': 'None', 'gov_employee': 'Never'}
    assert apex_apply.decide(q('Are you a U.S. Person? This includes a U.S. Citizen.', ['Yes', 'No']), a, C) == 'Yes'
    assert apex_apply.decide(q('Do you currently possess an active security clearance?', ['Yes', 'No']), a, C) == 'No'
    assert apex_apply.decide(q('If you currently possess an active security clearance, which agency sponsored the clearance?',
                               ['I do not possess an active security clearance.', 'DOD', 'CIA']), a, C) == 'I do not possess an active security clearance.'
    assert apex_apply.decide(q('The below survey requests information so that CACI can fulfill its obligations (U.S. Government employment)',
                               ['I am currently employed by the U.S. Government.', 'I have never been employed by the U.S. Government.']), a, C) \
        == 'I have never been employed by the U.S. Government.'
    assert apex_apply.decide(q('Which job board?', []), {}, C) == 'Job board'
    assert apex_apply.decide(q('Are you a U.S. Person?', ['Yes', 'No']), {}, C) is None, 'not set: never guessed'
    assert apex_apply.decide(q('Security clearance level', ['None', 'Secret']), {'clearance': 'Secret'}, C) == 'Secret'
