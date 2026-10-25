"""The Workday flow on a faithful local copy of a Workday career site (tests/e2e/fixtures/workday.html):
Apply, Autofill with Resume, Create Account (a generated password APEX keeps), seven steps, Submit."""
from pathlib import Path

import pytest

import apex_apply

FIXTURE = Path(__file__).parent / 'fixtures' / 'workday.html'
CONTACT = {'name': 'Jo Rivera', 'email': 'jo@example.com', 'phone': '555-0100', 'location': 'Houston, TX',
           'linkedin': 'https://linkedin.com/in/jo', 'github': '', 'company': 'Acme', 'title': 'AI Engineer'}
ANSWERS = {'authorized': 'Yes', 'sponsorship': 'No', 'city': 'Houston', 'state': 'Texas', 'address': '1 Main St', 'zip': '77001'}


@pytest.fixture
def wd_page(browser):
    page = browser.new_page()
    yield page
    page.close()


def _pdf(tmp_path):
    p = tmp_path / 'Jo_Rivera_Resume.pdf'
    p.write_bytes(b'%PDF-1.4\n%fake\n')
    return str(p)


def test_board_detects_workday():
    assert apex_apply.board('https://nvidia.wd5.myworkdayjobs.com/en-US/Site/job/x/Title_JR1') == 'workday'
    assert apex_apply.new_password() != apex_apply.new_password()
    pw = apex_apply.new_password()
    assert len(pw) >= 12 and any(c.isupper() for c in pw) and any(c.islower() for c in pw) and any(c.isdigit() for c in pw) and '!' in pw


def test_workday_creates_the_account_walks_every_step_and_submits(wd_page, tmp_path):
    page = wd_page
    saved = {}
    log = []
    r = apex_apply.workday_flow(page, FIXTURE.as_uri(), _pdf(tmp_path), 'Dear team', CONTACT, ANSWERS,
                                ask=lambda q, opts: 'Your agent platform matches what I build.' if not opts else None,
                                do_submit=True, shot_path=str(tmp_path / 'wd.png'), logins={},
                                on_login=lambda h, e, p: saved.update(host=h, email=e, password=p), log=log)
    st = page.evaluate('window.STATE')
    assert r['status'] == 'submitted' and 'Congratulations' in r['detail'], r
    assert st['submitted'] is True and st['created']['email'] == 'jo@example.com'
    assert st['created']['bee'] == '', 'the honeypot field was never touched'
    assert saved['email'] == 'jo@example.com' and saved['password'] == st['created']['password'] and 'myworkday' not in saved['host']
    vals = page.evaluate("""() => ({fn: fn.value, ln: ln.value, a1: a1.value, city: city.value, zip: zip.value, ph: ph.value,
        src: src.textContent, country: country.textContent, st: st.textContent, pt: pt.textContent, q1: q1.textContent, q2: q2.textContent,
        q3: q3.value, g: g.textContent, v: v.textContent, prev: (document.querySelector('input[name=prev]:checked')||{}).value,
        cv: cv.files.length, terms: terms.checked})""")
    assert vals['fn'] == 'Jo' and vals['ln'] == 'Rivera' and vals['a1'] == '1 Main St' and vals['city'] == 'Houston' and vals['zip'] == '77001'
    assert vals['ph'] == '555-0100' and vals['cv'] == 1
    assert vals['src'] == 'Job Board' and vals['country'] == 'United States of America' and vals['st'] == 'Texas' and vals['pt'] == 'Mobile'
    assert vals['q1'] == 'Yes' and vals['q2'] == 'No' and vals['prev'] == 'n'
    assert vals['q3'] == 'Your agent platform matches what I build.'
    assert vals['g'] == 'I do not wish to answer' and vals['v'] == 'I decline to self identify' and vals['terms'] is True
    assert (tmp_path / 'wd.png').exists()


def test_workday_signs_in_with_the_kept_password(wd_page, tmp_path):
    page = wd_page
    page.add_init_script("window.EXISTING = {email: 'jo@example.com', password: 'Kept-Pass-1!'};")
    page.goto(FIXTURE.as_uri())
    host = apex_apply.host_of(page.url)
    created = {}
    r = apex_apply.workday_flow(page, FIXTURE.as_uri(), _pdf(tmp_path), '', CONTACT, ANSWERS, ask=lambda q, o: 'fine' if not o else None,
                                do_submit=False, shot_path='', logins={host: {'email': 'jo@example.com', 'password': 'Kept-Pass-1!'}},
                                on_login=lambda *a: created.update(x=1), log=[])
    st = page.evaluate('window.STATE')
    assert st['signedIn'] is True and st['created'] is None and not created, 'signed in with the kept password; no new account'
    assert r['status'] == 'filled' and st['step'] == 5, r


def test_workday_hands_over_when_the_account_already_exists(wd_page, tmp_path):
    page = wd_page
    page.add_init_script("window.EXISTING = {email: 'jo@example.com', password: 'Unknown-1!'};")
    page.goto(FIXTURE.as_uri())
    r = apex_apply.workday_flow(page, FIXTURE.as_uri(), _pdf(tmp_path), '', CONTACT, ANSWERS, ask=None, do_submit=True,
                                shot_path='', logins={}, on_login=None, log=[])
    assert r['status'] == 'needs_you' and 'exists' in r['detail'] and page.evaluate('window.STATE.submitted') is False


def test_workday_never_submits_with_an_unanswerable_required_question(wd_page, tmp_path):
    page = wd_page
    page.goto(FIXTURE.as_uri())
    page.evaluate("""() => { document.getElementById('extra').innerHTML =
        '<label for="q9">How many years of Kubernetes in production?*</label><input id="q9" required>'; }""")
    log = []
    # Drive the fixture to the questions step the way a real run would, then walk from there.
    page.click('[data-automation-id="adventureButton"]'); page.click('[data-automation-id="autofillWithResume"]')
    page.click('[data-automation-id="SignInWithEmailButton"]'); page.click('[data-automation-id="createAccountLink"]')
    page.fill('#cemail', 'jo@example.com'); page.fill('#cpw', 'Strong-Pass-1!'); page.fill('#cpw2', 'Strong-Pass-1!')
    page.check('[data-automation-id="createAccountCheckbox"]'); page.click('[data-automation-id="createAccountSubmitButton"]')
    status, detail, missing = apex_apply.walk_form(page, _pdf(tmp_path), '', CONTACT, ANSWERS, lambda q, o: None, True, '', log,
                                                   pages=12, next_button=apex_apply._wd_next_button)
    st = page.evaluate('window.STATE')
    assert status == 'needs_you' and st['submitted'] is False
    assert any('Kubernetes' in m for m in missing) or any('interested' in m for m in missing), missing
    assert st['step'] == 3, 'stopped on the page with the open question; earlier pages were completed'
