"""The Launch flow through the Evidence Engine, in the browser (stub model)."""
import io
import re

import pdfplumber
from playwright.sync_api import expect

from test_apex import download, go, toast, launch_fill


def run_agent(page, resume):
    launch_fill(page, 'Senior Data Analyst', resume)
    page.click('#run-btn')
    expect(page.locator('#run-btn-text')).to_have_text('Launch', timeout=240000)   # the run finished
    go(page, 'resume')


def test_launch_review_answer_and_use(probe, fixture_resume):
    page = probe.page
    run_agent(page, fixture_resume)
    content = page.locator('#resume-content')
    expect(content).to_contain_text('3 verified edits')
    expect(content).to_contain_text('48 → 74')                         # judge, both orders averaged
    expect(content).to_contain_text('ENGINEMARKER')                     # the edit's reason is shown
    final = page.locator('#eng-final')
    expect(final).to_contain_text('Built recurring reports for the management team')
    expect(final).to_contain_text('B.S. Business Administration, University of Houston, 2019')

    # Untick one edit: that line goes back to what the candidate wrote.
    page.locator('[data-engine="keep"][data-id="B1"]').uncheck()
    expect(final).to_contain_text('Responsible for making reports for the management team')
    expect(final).to_contain_text('Queried SQL databases to extract reporting data')
    page.locator('[data-engine="keep"][data-id="B1"]').check()
    expect(final).to_contain_text('Built recurring reports')

    # Answer the evidence question: the number goes into that line only.
    page.fill('[data-answer="B1"]', '9 managers, weekly')
    page.click('[data-action="engineAnswer"]')
    expect(final).to_contain_text('Built weekly reports used by 9 managers', timeout=60000)
    expect(page.locator('[data-answer="B1"]')).to_have_count(0)        # answered questions aren't asked again

    # Use this version -> templates -> the PDF carries the edited text.
    page.click('[data-action="engineUse"]')
    expect(page.locator('#view-templates')).to_have_class(re.compile(r'\bactive\b'), timeout=30000)
    _, data = download(page, '#tpl-download')
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        text = '\n'.join(p.extract_text() or '' for p in pdf.pages)
    assert 'Marcus Delgado' in text
    assert probe.page_errors == [], probe.page_errors


def test_market_and_gap_report_show_engine_findings(probe, fixture_resume):
    page = probe.page
    run_agent(page, fixture_resume)
    go(page, 'market')
    expect(page.locator('#market-content')).to_contain_text('Hiring-manager score')
    expect(page.locator('#market-content')).to_contain_text('Edits verified against your resume')
    go(page, 'gap')
    gap = page.locator('#gap-content')
    expect(gap).to_contain_text('The summary says "Hard worker and team player"')     # specific, not generic
    expect(gap).to_contain_text('Requirements you don\'t show yet')
    expect(gap).to_contain_text('Python')
    expect(gap).to_contain_text('Answer: How many managers used these reports')
    assert probe.page_errors == [], probe.page_errors


def test_phone_launch_button_takes_a_real_tap(browser, app, fixture_resume):
    """Regression: at phone width the (invisible) toast covered the Launch button,
    so taps never reached it and a run could not be started on a phone."""
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, has_touch=True, is_mobile=True)
    page = ctx.new_page()
    page.goto(app.url + '/')
    expect(page.locator('#tel-server-v')).to_have_text('10.0')
    page.tap('#open-drawer')
    page.fill('#job-title', 'Senior Data Analyst')
    page.fill('#resume-text', fixture_resume)
    page.wait_for_timeout(400)
    page.tap('#run-btn')
    expect(page.locator('#drawer')).not_to_have_class(re.compile(r'\bopen\b'))     # the run started
    expect(page.locator('#run-btn-text')).to_have_text('Launch', timeout=240000)
    ctx.close()
