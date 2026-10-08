"""Browser automation of TESTS.md tests 1, 4, 6 and 8.

Run:  .venv\\Scripts\\python -m pytest tests/e2e -v
"""
import io
import re
import zipfile

import pdfplumber
import pytest
from playwright.sync_api import expect

MARGIN_PT = 0.75 * 72        # ATS.MARGIN in index.html
EXPECTED_TABS = ['Home', 'Market Intel', 'Resume X-Ray', 'Gap Report', 'PDF Templates', 'Live Jobs',
                 'Job Alerts', 'Cover Letter', 'Interview', 'LinkedIn', 'Outreach', 'Velocity', 'Bullets',
                 'Tailor', 'Match', 'Weakness X-Ray', 'Negotiate', 'Career Bridge', 'Tracker']
PLACEHOLDERS = ['Your Name', 'Recent Company', 'Senior PM', 'TechCorp', 'Skill 1']


# ── helpers ──────────────────────────────────────────────────────────────────

def launch_fill(page, title, resume):
    page.click('#open-drawer')
    page.fill('#job-title', title)
    page.fill('#resume-text', resume)


def close_drawer(page):
    page.click('#drawer-close')


def go(page, view):
    page.click(f'.dock-item[data-view="{view}"]')
    expect(page.locator(f'#view-{view}')).to_have_class(re.compile(r'\bactive\b'))


def toast(page, text):
    expect(page.locator('#toast')).to_contain_text(text, timeout=10000)


def download(page, selector):
    with page.expect_download(timeout=20000) as info:
        page.click(selector)
    d = info.value
    return d.suggested_filename, open(d.path(), 'rb').read()


def pdf_report(data):
    """Text and geometry of every character, page by page."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = [{'w': p.width, 'h': p.height, 'text': p.extract_text() or '', 'chars': p.chars}
                 for p in pdf.pages]
    return pages


def assert_inside_margins(pages):
    for n, pg in enumerate(pages, 1):
        for c in pg['chars']:
            if not c['text'].strip():
                continue
            assert c['x0'] >= MARGIN_PT - 1, f'page {n}: {c["text"]!r} starts in the left margin at x={c["x0"]:.1f}'
            assert c['x1'] <= pg['w'] - MARGIN_PT + 1, (
                f'page {n}: {c["text"]!r} runs into the right margin (x1={c["x1"]:.1f}, '
                f'limit {pg["w"] - MARGIN_PT:.1f}) - a line is clipped instead of wrapped')
            assert c['bottom'] <= pg['h'] - MARGIN_PT + 3, (
                f'page {n}: {c["text"]!r} sits in the bottom margin (bottom={c["bottom"]:.1f})')


def parsed_templates_page(probe, resume):
    page = probe.page
    launch_fill(page, 'Senior Data Analyst', resume)
    close_drawer(page)
    go(page, 'templates')
    expect(page.locator('#tpl-actions')).to_be_visible()
    return page


# ── TEST 1: smoke ────────────────────────────────────────────────────────────

def test_1_smoke(probe):
    page = probe.page
    expect(page.locator('#tel-server')).to_have_class(re.compile(r'\blive\b'))

    libs = page.evaluate("""() => ({
        jspdf:    !!(window.jspdf || window.jsPDF),
        docx:     typeof window.docx !== 'undefined',
        pdfjsLib: typeof window.pdfjsLib !== 'undefined',
        mammoth:  typeof window.mammoth !== 'undefined'})""")
    missing = [k for k, ok in libs.items() if not ok]
    assert not missing, f'CDN libraries MISSING: {missing} (needs network access to cdnjs.cloudflare.com)'

    tabs = page.eval_on_selector_all('.dock-item', 'els => els.map(e => e.dataset.tip)')
    assert tabs == EXPECTED_TABS

    page.wait_for_timeout(500)   # let late script/font loads report
    probe.assert_clean()


# ── TEST 4: export, with the text-layer check a human used to do by hand ─────

def test_4_export_pdf_has_real_text_layer(probe, fixture_resume):
    page = parsed_templates_page(probe, fixture_resume)
    for label in ('Download PDF', 'Download DOCX', 'Download TXT'):
        expect(page.get_by_role('button', name=label)).to_be_visible()

    name, data = download(page, '#tpl-download')
    assert name == 'Marcus_Delgado_APEX_modern.pdf'
    assert data[:5] == b'%PDF-'
    pages = pdf_report(data)
    text = '\n'.join(p['text'] for p in pages)

    # Selectable / Ctrl+F-findable: these strings come out of the text layer.
    for needle in ('Marcus Delgado', 'PROFESSIONAL EXPERIENCE', 'Worked with SQL to get data from databases',
                   'University of Houston', 'SQL, Excel'):
        assert needle in text, f'{needle!r} not extractable from the PDF text layer'
    # The long bullet wrapped (its last word survived) rather than being clipped.
    assert 'ENDOFLONGBULLET' in text
    # jsPDF's built-in Helvetica must encode the dashes, not emit mojibake.
    assert 'March 2021 – Present' in text, 'en dash in the date range did not survive'
    assert 'Senior Data Analyst and Business Intelligence Reporting Lead' in text.replace('\n', ' ')
    assert_inside_margins(pages)
    for p in PLACEHOLDERS:
        assert p not in text
    probe.assert_clean()


def test_4_export_multipage_pdf(probe, fixture_resume):
    page = parsed_templates_page(probe, fixture_resume + '\nLONGFORM\n')
    _, data = download(page, '#tpl-download')
    pages = pdf_report(data)
    assert len(pages) >= 2, 'long resume should break onto a second page'
    assert 'FINALBULLETMARKER' in pages[-1]['text'], 'content after the page break was lost'
    assert_inside_margins(pages)
    probe.assert_clean()


def test_4_export_docx_and_txt(probe, fixture_resume):
    page = parsed_templates_page(probe, fixture_resume)

    name, data = download(page, '#tpl-download-docx')
    assert name == 'Marcus_Delgado_APEX_modern.docx'
    xml = zipfile.ZipFile(io.BytesIO(data)).read('word/document.xml').decode('utf-8')
    for needle in ('Marcus Delgado', 'Worked with SQL to get data from databases', 'ENDOFLONGBULLET'):
        assert needle in xml

    name, data = download(page, '#tpl-download-txt')
    assert name == 'Marcus_Delgado_APEX_modern.txt'
    txt = data.decode('utf-8')
    assert 'Marcus Delgado' in txt and '- Worked with SQL to get data from databases' in txt
    probe.assert_clean()


# ── TEST 6: endpoint reachability, from the page as TESTS.md specifies ───────

def test_6_endpoints(probe):
    results = probe.page.evaluate("""async () => {
      const S = location.origin, out = {};
      for (const p of ['/health','/cities','/templates','/config']) {
        try { out[p] = (await fetch(S + p)).status; } catch (e) { out[p] = 'NETWORK ERROR ' + e.message; }
      }
      const posts = {
        '/parse-resume': { resume: 'Jane Doe\\njane@x.com\\nEXPERIENCE\\nAnalyst at Acme 2020-2024\\n- Did things' },
        '/draft-cover-letter': { resume: 'Jane Doe, analyst, 4 years SQL', jobTitle: 'Data Analyst', company: 'Acme', posting: 'SQL required' },
        '/apply-all-recommendations': { optimized: 'Jane Doe\\nEXPERIENCE\\n- Built reports', changes: [], bulletRewrites: [], addedKeywords: ['SQL'] }
      };
      for (const [p, body] of Object.entries(posts)) {
        try {
          const r = await fetch(S + p, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
          out[p] = r.status;
        } catch (e) { out[p] = 'NETWORK ERROR ' + e.message; }
      }
      return out;
    }""")
    assert results == {p: 200 for p in results} and len(results) == 7, results
    probe.assert_clean()


# ── TEST 8: error handling ───────────────────────────────────────────────────

def test_8_1_empty_resume(probe):
    launch_fill(probe.page, 'Senior Data Analyst', '')
    probe.page.click('#run-btn')
    toast(probe.page, 'Paste your resume')
    probe.assert_clean()


def test_8_2_empty_job_title(probe, fixture_resume):
    launch_fill(probe.page, '', fixture_resume)
    probe.page.click('#run-btn')
    toast(probe.page, 'Enter a job title')
    probe.assert_clean()


def test_8_3_download_before_parsing(probe):
    page = probe.page
    go(page, 'templates')
    expect(page.locator('#tpl-actions')).to_be_visible()
    downloads = []
    page.on('download', lambda d: downloads.append(d))
    page.click('#tpl-download')
    toast(page, 'Open Launch and paste your resume first')
    page.wait_for_timeout(1000)
    assert not downloads, 'a PDF was exported with no resume (placeholder content)'
    # Previews must not show invented content either.
    for frame in page.frames[1:]:
        body = frame.locator('body').inner_text()
        for p in PLACEHOLDERS:
            assert p not in body, f'template preview shows placeholder {p!r}'
    probe.assert_clean()


def test_8_4_single_character_resume(probe, fake_openai):
    before = len(fake_openai.calls)
    launch_fill(probe.page, 'Senior Data Analyst', 'x')
    probe.page.click('#run-btn')
    toast(probe.page, 'Resume too short (1 of 100')
    assert len(fake_openai.calls) == before, 'a 1-character resume reached the model'
    probe.assert_clean()


def test_8_5_parse_failure_is_reported_not_papered_over(probe, fixture_resume):
    """Regression: a failed parse used to export 'Your Name' / 'Recent Company'."""
    page = parsed_templates_page(probe, fixture_resume + '\nFAILPARSE\n')
    downloads = []
    page.on('download', lambda d: downloads.append(d))
    page.click('#tpl-download')
    toast(page, 'Could not parse your resume')
    page.wait_for_timeout(1000)
    assert not downloads
    # The stubbed 500 is logged by Chrome as a network error; that is the
    # scenario under test. What must not happen is an uncaught exception.
    assert not probe.page_errors, probe.page_errors
    assert all('500' in e for e in probe.console_errors), probe.console_errors


def test_8_6_server_rejects_short_resume_with_message(probe):
    """A direct /analyze call with junk gets a 400 + message, not a hung stream."""
    r = probe.page.evaluate("""async () => {
      const r = await fetch('/analyze', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                         body: JSON.stringify({jobTitle: 'X', resume: 'x'})});
      return {status: r.status, body: await r.json()};
    }""")
    assert r['status'] == 400 and 'too short' in r['body']['error']


# ── Delegated actions (inline handlers were removed for the CSP) ─────────────

def test_data_action_buttons_work(probe):
    page = probe.page
    go(page, 'templates')
    page.click('.brand[data-action="tab"]')
    expect(page.locator('#view-home')).to_have_class(re.compile(r'\bactive\b'))
    page.click('#view-home [data-action="tab"][data-arg="templates"]')
    expect(page.locator('#view-templates')).to_have_class(re.compile(r'\bactive\b'))
    go(page, 'home')
    page.click('#view-home [data-action="launch"]')
    expect(page.locator('#drawer')).to_have_class(re.compile(r'\bopen\b'))
    probe.assert_clean()


# ── Upload round trip: our own exports must read back in (pdf.js / mammoth) ──

@pytest.mark.parametrize('button,ext', [('#tpl-download', 'pdf'), ('#tpl-download-docx', 'docx')])
def test_exported_resume_uploads_back(probe, fixture_resume, button, ext):
    page = parsed_templates_page(probe, fixture_resume)
    _, data = download(page, button)
    page.fill('#resume-text', '')
    page.set_input_files('#file-input', files=[{'name': f'resume.{ext}', 'mimeType': 'application/octet-stream',
                                                 'buffer': data}])
    toast(page, 'Resume loaded')
    text = page.input_value('#resume-text')
    assert 'Marcus Delgado' in text and 'Worked with SQL to get data from databases' in text, text[:300]
    probe.assert_clean()
