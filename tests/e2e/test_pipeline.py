"""The Tracker as a pipeline: apex.db-backed, follow-ups, apply kit, drift."""
import io
import os
import re
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pdfplumber
from playwright.sync_api import expect

from test_api import call
from test_apex import download, go, toast, launch_fill, close_drawer

ROOT = Path(__file__).resolve().parents[2]


def uniq(p='Co'):
    return f'{p}-{uuid.uuid4().hex[:6]}'


def row(page, company):
    return page.locator('#trk-tbody tr', has_text=company)


def test_add_move_and_delete(probe):
    page, co = probe.page, uniq()
    go(page, 'tracker')
    page.fill('#trk-co', co)
    page.fill('#trk-role', 'Senior Data Analyst')
    page.fill('#trk-url', 'https://jobs.example.com/apex-1')
    page.click('#trk-add')
    toast(page, 'Added to pipeline')
    expect(row(page, co)).to_be_visible()
    expect(row(page, co).locator('a')).to_have_attribute('href', 'https://jobs.example.com/apex-1')

    # Same job again is recognised, not duplicated.
    page.fill('#trk-co', co.upper()); page.fill('#trk-role', 'senior data analyst')
    page.fill('#trk-url', 'https://jobs.example.com/apex-1')
    page.click('#trk-add')
    toast(page, 'already in your pipeline')
    expect(row(page, co)).to_have_count(1)

    row(page, co).locator('select.trk-status').select_option('interview')
    toast(page, 'Moved to Interview')
    row(page, co).get_by_role('button', name='Open').click()
    expect(page.locator('#pp-modal')).to_have_class(re.compile(r'\bopen\b'))
    expect(page.locator('#pp-timeline')).to_contain_text('Applied → Interview')

    page.fill('#pp-notes', 'Panel with clinical ops on Tuesday')
    page.click('#pp-save')
    toast(page, 'Saved')
    expect(page.locator('#pp-timeline')).to_contain_text('Notes updated')

    page.once('dialog', lambda d: d.accept())
    page.click('#pp-delete')
    toast(page, 'Deleted')
    expect(row(page, co)).to_have_count(0)
    probe.assert_clean()


def test_add_requires_company(probe):
    page = probe.page
    go(page, 'tracker')
    page.fill('#trk-role', 'Analyst')
    page.click('#trk-add')
    toast(page, 'company is required')
    probe.assert_clean()


def test_followup_due_draft_and_mark_sent(probe, app):
    page, co = probe.page, uniq('Due')
    ten_days = (date.today() - timedelta(days=10)).isoformat()
    st, j = call(app, 'POST', '/api/applications', {'company': co, 'role': 'Data Analyst', 'applied_on': ten_days})
    assert st == 201
    go(page, 'tracker')
    expect(page.locator('#trk-due')).to_be_visible()
    page.click('#trk-due [data-action="pipeFilter"]')
    expect(row(page, co).locator('.due-pill')).to_be_visible()

    row(page, co).get_by_role('button', name='Open').click()
    page.click('#pp-followup-btn')
    expect(page.locator('#pp-followup')).to_contain_text('followupmarker', timeout=15000)
    expect(page.locator('#pp-followup')).to_contain_text('LinkedIn note')
    expect(page.locator('#pp-timeline')).to_contain_text('Follow-up sequence saved')

    page.click('#pp-sent')
    toast(page, 'next check on')
    expect(page.locator('#pp-timeline')).to_contain_text('Follow-up sent')
    page.click('#pp-close')
    page.click('#trk-filters [data-arg="all"]')
    expect(row(page, co).locator('.due-pill')).to_have_count(0)
    probe.assert_clean()


def test_saved_kit_exports_a_real_pdf(probe, app, stub_resume):
    page, co = probe.page, uniq('Kit')
    _, j = call(app, 'POST', '/api/applications', {'company': co, 'role': 'Senior Data Analyst', 'status': 'saved'})
    aid = j['application']['id']
    assert call(app, 'POST', '/api/applications/artifact',
                {'id': aid, 'kind': 'tailored_resume', 'content': stub_resume})[0] == 201
    assert call(app, 'POST', '/api/applications/artifact',
                {'id': aid, 'kind': 'cover_letter', 'content': 'Dear Meridian team, ...'})[0] == 201
    go(page, 'tracker')
    page.click('#trk-filters [data-arg="all"]')
    expect(row(page, co).locator('.kit-pill')).to_have_text('2 docs')
    row(page, co).get_by_role('button', name='Open').click()
    expect(page.locator('#pp-kit')).to_contain_text('Tailored resume')
    expect(page.locator('#pp-kit')).to_contain_text('Cover letter')
    name, data = download(page, '#pp-kit [data-action="kitExport"][data-arg="pdf"]')
    assert name.endswith(f'_APEX_tailored_{co.replace("-", "_")}.pdf'), name
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        text = '\n'.join(p.extract_text() or '' for p in pdf.pages)
    assert 'Marcus Delgado' in text
    probe.assert_clean()


def test_browser_storage_migrates_into_the_database(browser, app):
    co = uniq('Legacy')
    ctx = browser.new_context()
    ctx.add_init_script(f"""
      if (!sessionStorage.getItem('seeded')) {{
        sessionStorage.setItem('seeded', '1');
        localStorage.setItem('apex_apps', JSON.stringify([
          {{company: '{co}', role: 'Analyst', date: '2026-08-01', status: 'interview'}},
          {{company: 'Unknown', role: 'Unknown', date: '2026-08-02', status: 'applied'}}
        ]));
      }}""")
    page = ctx.new_page()
    page.goto(app.url + '/')
    toast(page, 'Moved 1 saved application')
    assert page.evaluate("localStorage.getItem('apex_apps')") is None
    assert co in page.evaluate("localStorage.getItem('apex_apps_backup')")
    _, j = call(app, 'GET', '/api/applications')
    mine = [a for a in j['applications'] if a['company'] == co]
    assert len(mine) == 1 and mine[0]['status'] == 'interview' and mine[0]['applied_on'] == '2026-08-01'
    assert not any(a['company'] == 'Unknown' for a in j['applications']), 'placeholder rows must not be imported'
    ctx.close()


def test_drift_check_against_recorded_baseline(probe, app, fixture_resume):
    page, title = probe.page, uniq('Senior Data Analyst')
    # Record a baseline exactly as a finished /analyze run would: score + its requirement list.
    sys.path.insert(0, str(ROOT))
    import apex_store
    old = os.environ.get('APEX_DB')
    os.environ['APEX_DB'] = str(app.dir / 'apex.db')
    try:
        apex_store.record_score(title, 'general', 40, 60, keywords=[{'name': 'Excel', 'pct': 80}, {'name': 'Access', 'pct': 60}])
    finally:
        if old is None: os.environ.pop('APEX_DB', None)
        else: os.environ['APEX_DB'] = old

    launch_fill(page, title, fixture_resume)
    page.dispatch_event('#job-title', 'change')
    close_drawer(page)
    go(page, 'market')
    expect(page.locator('#drift-base')).to_contain_text('Baseline 60')
    page.click('#drift-run')
    # Today's saved postings ask for Python and Tableau, never for Access: the
    # same resume is scored against both requirement lists (no model guess).
    out = page.locator('#drift-out')
    expect(out).to_contain_text('Python', timeout=40000)
    expect(out).to_contain_text('Access')
    probe.assert_clean()


def test_drift_without_baseline_says_why(probe, fixture_resume):
    page = probe.page
    launch_fill(page, uniq('Brand New Role'), fixture_resume)
    close_drawer(page)
    go(page, 'market')
    page.click('#drift-run')
    expect(page.locator('#drift-out')).to_contain_text('Run the agent once for this job title')
    # Chrome logs the 400 as a network error; that is the scenario. No exceptions.
    assert not probe.page_errors
