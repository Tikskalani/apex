"""v11 page behaviour: lazy libraries, a11y basics, run bar, sub-tool errors,
inbox route, harvested postings, persistence, first-run setup, new events.

Uses the session `app` / `browser` fixtures from conftest.py. `ui` mirrors
conftest's `probe` but waits for the health dot instead of a fixed version
string, so these tests keep working across version bumps.
"""
import json
import re

import pytest
from playwright.sync_api import expect

from test_apex import close_drawer, go, launch_fill, toast




def fire(page, *events):
    """Feed SSE events to the page exactly as streamSSE would."""
    page.evaluate("evs => evs.forEach(e => handleEvent(e))", list(events))


# ── performance: vendor libraries are not on the critical path ───────────────

def test_vendor_libraries_load_on_first_use(ui):
    page = ui.page
    page.wait_for_timeout(800)
    libs = page.evaluate("""() => ({jspdf: !!window.jspdf, docx: !!window.docx, pdfjs: !!window.pdfjsLib,
                                    mammoth: !!window.mammoth,
                                    tags: [...document.scripts].filter(s => s.src).map(s => s.src)})""")
    assert not any(libs[k] for k in ('jspdf', 'docx', 'pdfjs', 'mammoth')), libs
    assert libs['tags'] == [], 'no vendor script tag should block the first paint'
    # On demand: same pinned URL, SRI hash and CORS mode as before.
    got = page.evaluate("""async () => { await loadLib('jspdf'); await loadLib('pdfjs');
        const s = [...document.scripts].filter(x => x.src);
        return {jspdf: !!(window.jspdf && window.jspdf.jsPDF), worker: pdfjsLib.GlobalWorkerOptions.workerSrc,
                attrs: s.map(x => [x.src, x.integrity.slice(0, 7), x.crossOrigin])}; }""")
    assert got['jspdf']
    assert got['worker'].endswith('/pdf.js/3.11.174/pdf.worker.min.js')
    assert all(a[1] == 'sha384-' and a[2] == 'anonymous' for a in got['attrs']), got['attrs']
    ui.assert_clean()


# ── accessibility basics ─────────────────────────────────────────────────────

def test_dock_buttons_have_accessible_names(ui):
    page = ui.page
    names = page.eval_on_selector_all('.dock-item', 'els => els.map(e => e.getAttribute("aria-label"))')
    tips = page.eval_on_selector_all('.dock-item', 'els => els.map(e => e.dataset.tip)')
    # The Tracker label may carry a live count ("Tracker (2 follow-ups due)").
    assert all(n and (n == t or n.startswith(t + ' (')) for n, t in zip(names, tips)) and len(names) == len(tips), names
    expect(page.get_by_role('button', name='Resume X-Ray', exact=True)).to_be_visible()
    expect(page.get_by_role('button', name='More tools', exact=True)).to_be_visible()
    # Every form field has a label (for=) or an aria-label.
    unlabeled = page.evaluate("""() => [...document.querySelectorAll('input:not([type=hidden]):not([type=file]), textarea, select')]
        .filter(el => !el.getAttribute('aria-label') && !(el.id && document.querySelector('label[for="' + el.id + '"]')) && !el.closest('label'))
        .map(el => el.id || el.outerHTML.slice(0, 60))""")
    assert unlabeled == [], unlabeled
    assert page.get_attribute('#toast', 'aria-live') == 'polite'
    ui.assert_clean()


def test_drawer_is_a_dialog_escape_closes_and_focus_returns(ui):
    page = ui.page
    drawer = page.locator('#drawer')
    assert drawer.get_attribute('inert') is not None and drawer.get_attribute('aria-hidden') == 'true'
    assert drawer.get_attribute('role') == 'dialog' and drawer.get_attribute('aria-modal') == 'true'
    page.focus('#open-drawer')
    page.keyboard.press('Enter')
    expect(drawer).to_have_class(re.compile(r'\bopen\b'))
    assert drawer.get_attribute('inert') is None
    page.wait_for_function("document.getElementById('drawer').contains(document.activeElement)")
    for _ in range(40):                      # focus is trapped inside while open
        page.keyboard.press('Tab')
        assert page.evaluate("document.getElementById('drawer').contains(document.activeElement)")
    page.keyboard.press('Escape')
    expect(drawer).not_to_have_class(re.compile(r'\bopen\b'))
    assert drawer.get_attribute('inert') is not None
    assert page.evaluate("document.activeElement.id") == 'open-drawer'
    ui.assert_clean()


def test_upload_zone_is_a_keyboard_button(ui):
    page = ui.page
    page.click('#open-drawer')
    zone = page.locator('#upload-zone')
    assert zone.evaluate('e => e.tagName') == 'BUTTON'
    with page.expect_file_chooser() as fc:
        zone.focus(); page.keyboard.press('Enter')
    assert fc.value is not None


def test_template_cards_are_keyboard_radios(ui):
    page = ui.page
    go(page, 'templates')
    expect(page.locator('.tpl-card')).to_have_count(6)
    first = page.locator('.tpl-card[aria-checked="true"]')
    expect(first).to_have_attribute('data-tpl', 'modern')
    first.focus(); page.keyboard.press('ArrowRight')
    expect(page.locator('.tpl-card[aria-checked="true"]')).to_have_attribute('data-tpl', 'classic')
    assert page.evaluate("state.selectedTemplate") == 'classic'
    ui.assert_clean()


# ── templates: no silent model call ──────────────────────────────────────────

def test_opening_templates_does_not_parse(ui, fixture_resume):
    page = ui.page
    parses = []
    page.on('request', lambda r: parses.append(r.url) if r.url.endswith('/parse-resume') else None)
    launch_fill(page, 'Senior Data Analyst', fixture_resume)
    close_drawer(page)
    go(page, 'templates')
    expect(page.locator('#tpl-actions')).to_be_visible()
    page.wait_for_timeout(1500)
    assert parses == [], 'opening Templates must not call the model'
    expect(page.locator('#tpl-note')).to_contain_text('one AI call')
    page.click('#tpl-reparse')                       # explicit: now it parses
    toast(page, 'Previews show your resume')
    assert len(parses) == 1
    ui.assert_clean()


# ── sub-tools: errors inline, button back ────────────────────────────────────

@pytest.mark.parametrize('route,view,btn,out', [
    ('/bullets', 'bullets', '#bullets-run', '#bullets-out'),
    ('/xray', 'weakness', '#weak-run', '#weak-out'),
])
def test_subtool_error_shows_inline_and_button_comes_back(ui, fixture_resume, route, view, btn, out):
    page = ui.page
    page.route('**' + route, lambda r: r.fulfill(status=500, content_type='application/json',
                                                 body=json.dumps({'error': 'stubbed tool failure'})))
    launch_fill(page, 'Senior Data Analyst', fixture_resume)
    close_drawer(page)
    go(page, view)
    page.click(btn)
    expect(page.locator(out + ' .tool-error')).to_contain_text('stubbed tool failure')
    expect(page.locator(btn)).to_be_enabled()
    assert not ui.page_errors, ui.page_errors


def test_subtool_disables_button_while_running(ui):
    page = ui.page
    page.route('**/bridge', lambda r: (page.wait_for_timeout(1200), r.fulfill(
        status=200, content_type='text/event-stream',
        body='data: ' + json.dumps({'type': 'bridge_data', 'data': {
            'transition_score': 60, 'transition_verdict': 'ok', 'skill_translations': [],
            'hidden_strengths': ['HIDDENSTRENGTH'], 'gaps_to_address': ['GAPMARK'], 'quick_wins': ['WINMARK'],
            'interview_bridge_answers': [{'question': 'Why switch?', 'answer': None, 'answer_withheld': ['claims a cert']}]}})
             + '\n\ndata: {"type":"done","msg":"ok"}\n\n')))
    go(page, 'bridge')
    page.fill('#br-from', 'Nurse'); page.fill('#br-to', 'Analyst')
    page.click('#br-run')
    expect(page.locator('#br-run')).to_be_disabled()
    for mark in ('HIDDENSTRENGTH', 'GAPMARK', 'WINMARK', 'Why switch?'):
        expect(page.locator('#br-out')).to_contain_text(mark)
    expect(page.locator('#br-out .withheld')).to_contain_text('claims a cert')
    expect(page.locator('#br-run')).to_be_enabled()
    ui.assert_clean()


# ── Gmail import goes to /inbox/scan ─────────────────────────────────────────

def test_inbox_scan_posts_to_inbox_route(ui):
    page = ui.page
    seen = {}

    def inbox(route):
        seen['body'] = json.loads(route.request.post_data)
        route.fulfill(status=200, content_type='application/json', body=json.dumps({
            'count': 1, 'scanned': 12, 'rows': [{'from': 'jobs@acme.test', 'subject': 'Your application', 'date': '2026-10-01',
                                                 'status': 'applied', 'company': 'Acme INBOXMARK', 'role': 'Analyst'}]}))
    page.route('**/inbox/scan', inbox)
    page.route('**/alerts/scan', lambda r: (seen.setdefault('wrong', True), r.abort()))
    go(page, 'tracker')
    page.fill('#ix-email', 'me@example.test'); page.fill('#ix-pwd', 'app-password-stub')
    page.click('#ix-scan')
    expect(page.locator('#ix-results')).to_contain_text('Acme INBOXMARK')
    expect(page.locator('#ix-status')).to_contain_text('Scanned 12 emails')
    assert 'wrong' not in seen
    assert seen['body']['user'] == 'me@example.test' and seen['body']['days'] == 30 and seen['body']['host']

    page.unroute('**/inbox/scan')
    page.route('**/inbox/scan', lambda r: r.fulfill(status=502, content_type='application/json',
                                                     body=json.dumps({'error': 'IMAP login failed STUBERR'})))
    page.click('#ix-scan')
    expect(page.locator('#ix-results .tool-error')).to_contain_text('IMAP login failed STUBERR')
    expect(page.locator('#ix-scan')).to_be_enabled()


# ── harvested postings are not job cards ─────────────────────────────────────

def test_jobs_data_is_counted_not_rendered_as_cards(ui):
    page = ui.page
    fire(page, {'type': 'jobs_data', 'query': 'Data Analyst',
                'jobs': [{'source': 'remotive', 'text': 'raw posting text ' * 20, 'query': 'Data Analyst'}] * 3})
    expect(page.locator('#jobs-list .job-card')).to_have_count(0)
    go(page, 'market')
    expect(page.locator('#market-harvest')).to_contain_text('3 postings analysed')
    # When the Jobs view is empty, a normal search fills it with real listings.
    page.route('**/live-jobs', lambda r: r.fulfill(status=200, content_type='application/json', body=json.dumps({
        'jobs': [{'title': 'Data Analyst LIVEJOB', 'company': 'Acme', 'location': 'Remote', 'url': 'https://acme.test/j',
                  'source': 'stub', 'posted': '2 days ago', 'snippet': 'SQL'}], 'count': 1, 'query': 'Data Analyst'})))
    page.evaluate('maybeAutoSearchJobs()')
    go(page, 'jobs')
    expect(page.locator('#jobs-list .job-card')).to_have_count(1)
    expect(page.locator('#jobs-list .job-title')).to_have_text('Data Analyst LIVEJOB')
    assert page.inner_text('#tel-jobs') == '1' and page.text_content('#jobs-count').startswith('1 job')
    ui.assert_clean()


def test_jobs_filters_dedupe_remote_and_age(ui):
    page = ui.page
    jobs = [
        {'title': 'Analyst', 'company': 'Acme', 'location': 'Remote', 'source': 'a', 'posted': '1 day ago', 'url': 'https://a.test'},
        {'title': 'Analyst', 'company': 'ACME', 'location': 'Remote', 'source': 'b', 'posted': '1 day ago', 'url': 'https://b.test'},
        {'title': 'Engineer', 'company': 'Beta', 'location': 'Houston, TX', 'source': 'a', 'posted': '20 days ago', 'url': 'https://c.test'},
        {'title': 'Designer', 'company': 'Gamma', 'location': 'Austin, TX', 'source': 'a', 'posted': '', 'url': 'https://d.test'},
    ]
    page.route('**/live-jobs', lambda r: r.fulfill(status=200, content_type='application/json',
                                                   body=json.dumps({'jobs': jobs, 'count': 4, 'query': 'x'})))
    go(page, 'jobs')
    page.fill('#jobs-q', 'analyst'); page.click('#jobs-search-btn')
    expect(page.locator('#jobs-list .job-card')).to_have_count(3)          # the duplicate is hidden
    page.check('#jf-remote')
    expect(page.locator('#jobs-list .job-card')).to_have_count(1)
    page.uncheck('#jf-remote')
    page.select_option('#jf-days', '7')
    expect(page.locator('#jobs-list .job-card')).to_have_count(2)          # 20-day-old dropped, undated kept
    page.select_option('#jf-days', '0')
    page.fill('#jf-text', 'gamma')
    expect(page.locator('#jobs-list .job-card')).to_have_count(1)
    ui.assert_clean()


# ── run bar, cancel, footer status ───────────────────────────────────────────

def test_run_bar_shows_progress_and_cancel_stops_the_run(ui, fixture_resume):
    page = ui.page
    def slow(route):                         # hold the run open long enough to cancel it
        page.wait_for_timeout(3000)
        try:
            route.continue_()
        except Exception:
            pass                             # the page already aborted the request
    page.route('**/analyze', slow)
    launch_fill(page, 'Senior Data Analyst', fixture_resume)
    page.click('#run-btn')
    bar = page.locator('#runbar')
    expect(bar).to_be_visible()
    expect(page.locator('#foot-status-lbl')).to_contain_text('RUNNING')
    page.click('#rb-cancel')
    expect(page.locator('#rb-step')).to_contain_text('Cancelled', timeout=10000)
    expect(page.locator('#foot-status-lbl')).to_contain_text('CANCELLED')
    expect(page.locator('#run-btn-text')).to_have_text('Launch')
    assert not ui.page_errors, ui.page_errors
    page.wait_for_timeout(3200)                # let the held route finish before teardown
    page.unroute_all(behavior='ignoreErrors')


# ── persistence ──────────────────────────────────────────────────────────────

def test_resume_settings_results_and_choices_survive_reload(ui, fixture_resume):
    page = ui.page
    launch_fill(page, 'Senior Data Analyst', fixture_resume)
    page.select_option('#seniority', 'manager')
    close_drawer(page)
    page.route('**/engine/render', lambda r: r.fulfill(status=200, content_type='application/json',
                                                      body=json.dumps({'text': 'RERENDERED TEXT'})))
    fire(page,
         {'type': 'cover_letter_data', 'letter': 'Dear team, PERSISTLETTER.'},
         {'type': 'engine_data', 'data': {
             'original': fixture_resume, 'final': 'FINAL TEXT', 'target': {'title': 'Senior Data Analyst'}, 'sig': 'abc',
             'changes': [{'id': 'B1', 'before': 'old line', 'after': ['new line'], 'why': 'w', 'kind': 'bullet'}],
             'questions': [{'id': 'B2', 'line': 'some line', 'question': 'How many?'}], 'score': {'before': 40, 'after': 60}}},
         {'type': 'tab_skipped', 'tab': 'velocity', 'reason': 'SKIPREASON'})
    go(page, 'resume')
    page.locator('[data-engine="keep"][data-id="B1"]').uncheck()
    expect(page.locator('#eng-final')).to_contain_text('RERENDERED TEXT')
    page.fill('[data-answer="B2"]', '12 analysts')
    page.wait_for_timeout(900)                                   # debounced save
    page.goto(page.url)                          # a fresh load: no browser form restore
    expect(page.locator('#tel-server')).to_have_class(re.compile(r'\blive\b'))
    assert page.input_value('#job-title') == 'Senior Data Analyst'
    assert page.input_value('#resume-text') == fixture_resume
    assert page.input_value('#seniority') == 'manager'
    go(page, 'cl')
    expect(page.locator('#cl-content')).to_contain_text('PERSISTLETTER')
    go(page, 'velocity')
    expect(page.locator('#vel-content')).to_contain_text('SKIPREASON')
    go(page, 'resume')
    expect(page.locator('[data-engine="keep"][data-id="B1"]')).not_to_be_checked()
    expect(page.locator('#eng-final')).to_contain_text('RERENDERED TEXT')
    assert page.input_value('[data-answer="B2"]') == '12 analysts'
    # Clear saved data really clears it.
    page.click('#open-drawer')
    page.once('dialog', lambda d: d.accept())
    page.click('#clear-saved')
    page.wait_for_load_state('load')
    expect(page.locator('#tel-server')).to_have_class(re.compile(r'\blive\b'))
    page.wait_for_timeout(500)
    assert page.input_value('#job-title') == ''
    assert page.evaluate("localStorage.getItem('apex_state_v1')") is None


def test_answer_request_sends_target_sig_and_kept(ui, fixture_resume):
    page = ui.page
    sent = {}

    def answer(route):
        sent.update(json.loads(route.request.post_data))
        route.fulfill(status=400, content_type='application/json', body=json.dumps({'error': 'stub stop'}))
    page.route('**/engine/answer', answer)
    fire(page, {'type': 'engine_data', 'data': {
        'original': fixture_resume, 'final': 'F', 'target': {'title': 'T', 'x': 1}, 'sig': 'SIG123',
        'changes': [{'id': 'B1', 'before': 'a', 'after': ['b']}, {'id': 'B3', 'before': 'c', 'after': ['d']}],
        'questions': [{'id': 'B2', 'line': 'l', 'question': 'q?'}], 'order': [['B1', 'B3']], 'section_order': None,
        'problems': [{'issue': 'i', 'fix': 'f'}], 'strengths': ['s'], 'summary_verdict': 'v'}})
    page.evaluate("state.engine.keep.B3 = false")
    go(page, 'resume')
    page.fill('[data-answer="B2"]', '7 teams')
    page.click('[data-action="engineAnswer"]')
    toast(page, 'stub stop')
    assert sent['sig'] == 'SIG123' and sent['target'] == {'title': 'T', 'x': 1}
    assert sent['answers'] == {'B2': '7 teams'} and sent['kept'] == {'B1': ['b']}
    # The review is carried over so the server rewrites only the answered lines.
    assert sent['questions'][0]['id'] == 'B2' and sent['order'] == [['B1', 'B3']]
    assert sent['problems'] == [{'issue': 'i', 'fix': 'f'}] and sent['strengths'] == ['s'] and sent['summary_verdict'] == 'v'
    expect(page.locator('[data-action="engineAnswer"]')).to_be_enabled()


# ── first run: no AI key ─────────────────────────────────────────────────────

def test_no_ai_key_shows_setup_and_disables_launch(ui):
    page = ui.page
    page.route('**/config', lambda r: r.fulfill(status=200, content_type='application/json', body=json.dumps({
        'AI_READY': False, 'AI_PROBLEM': 'No model key: copy config.example.json to config.json STUBSETUP',
        'VOICE_READY': False, 'HOSTED': False, 'SMTP_CONFIGURED': False, 'VERSION': '11.0'})))
    page.reload()
    expect(page.locator('#setup-card')).to_be_visible()
    expect(page.locator('#setup-card')).to_contain_text('STUBSETUP')
    expect(page.locator('#run-btn')).to_be_disabled()
    expect(page.locator('#run-blocked')).to_contain_text('no AI key')
    expect(page.locator('#brand-ver')).to_have_text('v11.0')
    go(page, 'iv')
    expect(page.locator('#vi-notice')).to_be_visible()
    expect(page.locator('#vi-start')).to_be_disabled()


def test_sse_refusal_message_is_shown(ui, fixture_resume):
    page = ui.page
    page.route('**/analyze', lambda r: r.fulfill(status=429, content_type='application/json',
                                                 body=json.dumps({'error': 'Hourly budget used up BUDGETMARK'})))
    launch_fill(page, 'Senior Data Analyst', fixture_resume)
    page.click('#run-btn')
    toast(page, 'BUDGETMARK')
    expect(page.locator('#rb-step')).to_contain_text('BUDGETMARK')
    expect(page.locator('#run-btn')).to_be_enabled()


# ── new event payloads are rendered, not dropped ─────────────────────────────

def test_new_fields_are_rendered(ui):
    page = ui.page
    fire(page,
         {'type': 'engine_data', 'data': {'original': 'x' * 120, 'final': 'x' * 120, 'target': {'title': 'T'},
                                          'changes': [], 'questions': [], 'note': 'NOTEMARK', 'summary_created': True,
                                          'veto': {'before': 61, 'after': 55, 'why': 'VETOWHY'},
                                          'vetoed_changes': [{'before': 'orig line', 'after': ['VETOEDLINE'], 'why': ''}]}},
         {'type': 'notice', 'level': 'warn', 'msg': 'NOTICEMARK no editable lines'},
         {'type': 'interview_data', 'data': {'verified': True, 'behavioral': [
             {'q': 'Tell me', 'a': None, 'a_withheld': ['claims PMP'], 'tip': 't'}], 'red_flags_to_address': ['REDFLAGMARK']}},
         {'type': 'match_data', 'data': {'match_pct': 70, 'should_apply': True, 'apply_confidence': 'medium',
                                         'missing_critical': ['CRITMARK'], 'missing_nice': ['NICEMARK'],
                                         'red_flags': ['REDMARK'], 'green_flags': ['GREENMARK'],
                                         'quick_fixes': [{'add_to_resume': 'Tableau', 'where': 'skills', 'shown_on_resume': False}]}},
         {'type': 'negotiate_data', 'data': {'target_salary': '$100k', 'estimate_basis': 'model_estimate', 'basis_note': 'BASISNOTE',
                                             'rationale': 'RATIONALEMARK', 'your_leverage': ['LEVMARK'], 'your_leverage_withheld': ['claimed award'],
                                             'market_evidence': ['EVIDMARK'], 'red_flags': ['LOWBALLMARK'], 'timing_advice': 'TIMINGMARK',
                                             'benefits_to_negotiate': ['PTOMARK'], 'equity_considerations': 'EQUITYMARK',
                                             'negotiation_script': {'opening_line': 'hi'}}},
         {'type': 'tailor_data', 'data': {'tailored_resume': 'Marcus\nline', 'changes': [], 'gaps': [], 'company_name': 'Acme',
                                          'questions': [{'id': 'B1', 'line': 'l', 'question': 'TAILORQ?'}]}})
    go(page, 'resume')
    for mark in ('NOTEMARK', 'VETOWHY', 'VETOEDLINE', 'A summary was added', 'Your original was kept', 'NOTICEMARK'):
        expect(page.locator('#view-resume')).to_contain_text(mark)
    go(page, 'iv')
    expect(page.locator('#iv-content')).to_contain_text('REDFLAGMARK')
    expect(page.locator('#iv-content .withheld')).to_contain_text('claims PMP')
    go(page, 'match')
    for mark in ('CRITMARK', 'NICEMARK', 'REDMARK', 'GREENMARK', 'only add it if it is true for you', 'medium'):
        expect(page.locator('#match-out')).to_contain_text(mark)
    go(page, 'negotiate')
    for mark in ('AI estimate, not market data', 'BASISNOTE', 'RATIONALEMARK', 'LEVMARK', 'EVIDMARK', 'LOWBALLMARK',
                 'TIMINGMARK', 'PTOMARK', 'EQUITYMARK'):
        expect(page.locator('#neg-out')).to_contain_text(mark)
    go(page, 'tailor')
    expect(page.locator('#tailor-out')).to_contain_text('TAILORQ?')
    for label in ('Export PDF', 'DOCX', 'TXT', 'Save to pipeline'):
        expect(page.locator('#tailor-out').get_by_role('button', name=label, exact=True)).to_be_visible()
    # New results are flagged on the rail instead of switching views.
    assert page.evaluate("document.querySelector('.view.active').id") == 'view-tailor'
    ui.assert_clean()


def test_new_results_badge_without_switching_view(ui):
    page = ui.page
    go(page, 'jobs')
    fire(page, {'type': 'market_data', 'data': {'recruiterScoreBefore': 40, 'recruiterScoreAfter': 60, 'total_jobs_analyzed': 9}})
    assert page.evaluate("document.querySelector('.view.active').id") == 'view-jobs'
    market = page.locator('.dock-item[data-view="market"]')
    expect(market.locator('.dock-badge')).to_have_count(1)
    assert 'new results' in market.get_attribute('aria-label')
    go(page, 'market')
    expect(market.locator('.dock-badge')).to_have_count(0)
    ui.assert_clean()


# ── phone layout ─────────────────────────────────────────────────────────────

def test_phone_footer_fits_and_tailor_modal_footer_is_compact(browser, app):
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, has_touch=True, is_mobile=True)
    page = ctx.new_page()
    page.goto(app.url + '/')
    expect(page.locator('#tel-server')).to_have_class(re.compile(r'\blive\b'), timeout=15000)
    fits = page.evaluate("""() => { const p = document.getElementById('foot-pipeline');
        return {sw: p.scrollWidth, cw: p.clientWidth, foot: document.querySelector('.footer').scrollWidth, vw: innerWidth}; }""")
    assert fits['sw'] <= fits['cw'] + 1, fits
    assert fits['foot'] <= fits['vw'], fits
    page.route('**/tailor', lambda r: r.fulfill(status=500, content_type='application/json', body='{"error":"x"}'))
    page.route('**/draft-cover-letter', lambda r: r.fulfill(status=500, content_type='application/json', body='{"error":"x"}'))
    page.evaluate("document.getElementById('resume-text').value = 'x'.repeat(200)")
    page.evaluate("openTailorApplyModal({title: 'Analyst', company: 'Acme', url: 'https://acme.test'})")
    expect(page.locator('#ta-modal')).to_have_class(re.compile(r'\bopen\b'))
    h = page.evaluate("document.querySelector('#ta-modal .modal-footer').getBoundingClientRect().height")
    assert h < 844 * 0.25, f'modal footer is {h}px of 844'
    ctx.close()


def test_tailor_modal_ignores_stale_answers(ui):
    page = ui.page
    page.route('**/draft-cover-letter', lambda r: r.fulfill(status=200, content_type='application/json',
                                                           body=json.dumps({'letter': 'LETTER FOR ' + json.loads(r.request.post_data)['company']})))
    page.route('**/tailor', lambda r: r.fulfill(status=200, content_type='text/event-stream', body='data: ' + json.dumps(
        {'type': 'tailor_data', 'data': {'tailored_resume': 'RESUME FOR ' + json.loads(r.request.post_data)['jobPosting'][:20], 'changes': []}}) + '\n\n'))
    page.evaluate("document.getElementById('resume-text').value = 'x'.repeat(200)")
    page.evaluate("openTailorApplyModal({title: 'A', company: 'AlphaCo'})")
    page.evaluate("closeTailorApplyModal(); openTailorApplyModal({title: 'B', company: 'BetaCo'})")
    expect(page.locator('#ta-cover-body')).to_have_text('LETTER FOR BetaCo')
    page.wait_for_timeout(600)
    assert page.evaluate("window._taCover") == 'LETTER FOR BetaCo'
    assert page.evaluate("TA.job.company") == 'BetaCo'
    page.keyboard.press('Escape')
    expect(page.locator('#ta-modal')).not_to_have_class(re.compile(r'\bopen\b'))


def test_cover_letter_rewrites_from_the_latest_resume(ui):
    """The run writes the letter before the questions are answered; the button rewrites
    it from the edited resume (answers included), not the original in the Launch box."""
    page = ui.page
    sent = []

    def letter(route):
        body = json.loads(route.request.post_data)
        sent.append(body)
        route.fulfill(status=200, content_type='application/json',
                      body=json.dumps({'letter': 'NEW LETTER citing ' + body['resume'][-10:], 'verified': True}))
    page.route('**/draft-cover-letter', letter)
    page.evaluate("document.getElementById('resume-text').value = 'ORIGINAL ' + 'x'.repeat(200)")
    page.evaluate("document.getElementById('job-title').value = 'Data Analyst'")
    page.evaluate("handleEvent({type: 'cover_letter_data', letter: 'FIRST LETTER'})")
    page.evaluate("state.engine = {text: 'EDITED ' + 'y'.repeat(200) + ' 9 MANAGERS', data: {}}")
    go(page, 'cl')
    page.click('#cl-content [data-action="letterRefresh"]')
    expect(page.locator('#cl-content')).to_contain_text('NEW LETTER citing 9 MANAGERS')
    assert sent[0]['resume'].startswith('EDITED') and sent[0]['jobTitle'] == 'Data Analyst'
    assert page.evaluate("window._coverLetter").startswith('NEW LETTER')


def test_bullets_and_grading_show_the_whole_review(ui):
    """Bullets: verdict, the fixes that matter most, what is weak, highlighted blanks and the
    question that unlocks each one. Grading: what the question probes and likely follow-ups."""
    page = ui.page
    page.evaluate("""handleEvent({type: 'bullet_data', data: {overall_verdict: 'Duties, not results.', average_score: 48,
        top_fixes: ['Rewrite the summary first'],
        ranked_bullets: [{text: 'Improved page load time', score: 30, rank: 2, weaknesses: ['no metric'],
                          rewrite: 'Cut dashboard load time [by X%]', ask: 'How fast was it before and after?'}]}})""")
    go(page, 'bullets')
    out = page.locator('#bullets-out')
    for text in ('Duties, not results.', 'Fix these first', 'Rewrite the summary first', 'Weak: no metric',
                 'Ask yourself: How fast was it before and after?'):
        expect(out).to_contain_text(text)
    expect(out.locator('mark.blank')).to_have_text('[by X%]')
    page.evaluate("""viRenderGrade({score: 55, grade: 'C', verdict: 'Vague.', ideal_answer_structure: 'Ownership of a hard call.',
        follow_up_questions: ['What would you do differently?'], better_version: 'I [describe the decision].'})""")
    grade = page.locator('#vi-grade')
    expect(grade).to_contain_text('What this question is probing')
    expect(grade).to_contain_text('What would you do differently?')
    expect(grade.locator('mark.blank')).to_have_text('[describe the decision]')


def test_focus_mode_shows_the_core_tools_and_skips_the_extra_tabs(ui):
    """The dock shows the tools a job search needs; "More tools" reveals the rest and is remembered.
    In focus mode a run asks the server for the cover letter only (extras: false)."""
    page = ui.page
    assert page.evaluate("document.body.classList.contains('focus')")
    expect(page.locator('.dock-item[data-view="resume"]')).to_be_visible()
    expect(page.locator('.dock-item[data-view="velocity"]')).to_be_hidden()
    page.click('.dock-more')
    expect(page.locator('.dock-item[data-view="velocity"]')).to_be_visible()
    page.reload()
    expect(page.locator('.dock-item[data-view="velocity"]')).to_be_visible()     # remembered
    page.click('.dock-more')
    expect(page.locator('.dock-item[data-view="velocity"]')).to_be_hidden()
    sent = []
    page.route('**/analyze', lambda r: (sent.append(json.loads(r.request.post_data)),
                                        r.fulfill(status=200, content_type='text/event-stream',
                                                  body='data: {"type": "done", "msg": "ok"}\n\n')))
    launch_fill(page, 'AI Engineer', 'Jo Doe\nAI engineer.\n' + '- Built an agent with evals\n' * 20)
    page.click('#run-btn')
    page.wait_for_timeout(800)
    assert sent and sent[0]['extras'] is False


def test_apply_queue_from_profile_to_applied(ui, fixture_resume):
    """The Apply queue tab: create a profile, scan (saved postings), approve one, apply."""
    page = ui.page
    page.evaluate('r => { document.getElementById("resume-text").value = r; }', fixture_resume)
    go(page, 'queue')
    page.click('[data-action="agNew"]')                         # other tests may have made profiles already
    expect(page.locator('#ag-editor')).to_be_visible()
    page.fill('#ag-name', 'Me')
    page.fill('#ag-targets', 'Data Analyst')
    page.fill('#ag-minfit', '0')
    page.fill('#ag-limit', '2')
    page.uncheck('#ag-active')
    page.click('[data-action="agUseResume"]')
    assert page.input_value('#ag-resume').startswith(fixture_resume[:30])
    page.click('[data-action="agSave"]')
    expect(page.locator('#ag-editor')).to_be_hidden()
    page.click('#ag-scan')
    approve = page.locator('#ag-list [data-action="agApprove"]').first
    expect(approve).to_be_visible(timeout=30000)
    approve.click()
    expect(page.locator('#ag-list [data-action="agApplied"]').first).to_be_visible(timeout=30000)
    expect(page.locator('#ag-list')).to_contain_text('Ready to apply')
    page.locator('#ag-list [data-action="agApplied"]').first.click()
    expect(page.locator('#ag-list')).to_contain_text('Applied · in the Tracker')
    ui.assert_clean()
