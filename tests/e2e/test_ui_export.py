"""v11 upload and export: PDF line rebuilding, scanned-PDF warning, Unicode PDF
text (embedded Noto Sans), Unicode-safe filenames, real template variations,
the DOCX right tab stop, and exports that follow the user's kept edits."""
import io
import json
import re
import shutil
import unicodedata
import zipfile
from pathlib import Path

import pdfplumber
import pytest
from playwright.sync_api import expect

from test_apex import close_drawer, download, go, launch_fill, toast

ROOT = Path(__file__).resolve().parents[2]
NAME = 'Zoë Łukasiewicz-Nguyễn'


def tiny_pdf(lines):
    """A hand-written one-page PDF: one text run per (x, y, text), WinAnsi Helvetica."""
    ops = ['BT /F1 11 Tf']
    for x, y, t in lines:
        s = t.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        ops.append(f'1 0 0 1 {x} {y} Tm ({s}) Tj')
    ops.append('ET')
    stream = '\n'.join(ops).encode('cp1252')
    objs = [b'<< /Type /Catalog /Pages 2 0 R >>',
            b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
            b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream',
            b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>']
    out, offs = bytearray(b'%PDF-1.4\n'), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b'%d 0 obj\n' % i + o + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1)
    out += b''.join(b'%010d 00000 n \n' % o for o in offs)
    out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, xref)
    return bytes(out)


def upload(page, name, data):
    page.set_input_files('#file-input', files=[{'name': name, 'mimeType': 'application/octet-stream', 'buffer': data}])


def test_pdf_upload_keeps_line_breaks_and_bullets(ui):
    page = ui.page
    pdf = tiny_pdf([
        (72, 720, 'Marcus Delgado'),
        (72, 704, 'Data Analyst'),
        (72, 660, 'EXPERIENCE'),
        (72, 644, 'Senior Analyst, Brightline'), (430, 644, '2021 – Present'),
        (72, 628, '• Built weekly reports for 9 managers'),
        (72, 612, '• Queried SQL databases'),
    ] + [(72, 580 - 14 * i, f'Filler line number {i} with enough words to be a resume') for i in range(6)])
    page.click('#open-drawer')
    upload(page, 'resume.pdf', pdf)
    toast(page, 'Resume loaded')
    lines = page.input_value('#resume-text').split('\n')
    assert lines[0] == 'Marcus Delgado' and lines[1] == 'Data Analyst', lines[:3]
    assert '' in lines[2:4], 'the gap before EXPERIENCE should stay a blank line'
    assert 'Senior Analyst, Brightline 2021 – Present' in lines, lines
    assert '• Built weekly reports for 9 managers' in lines and '• Queried SQL databases' in lines, lines
    ui.assert_clean()


def test_scanned_pdf_and_old_formats_warn(ui):
    page = ui.page
    page.click('#open-drawer')
    upload(page, 'scan.pdf', tiny_pdf([(72, 720, '  ')]))
    toast(page, 'probably a scan')
    expect(page.locator('#toast')).to_have_class(re.compile(r'\berr\b'))
    upload(page, 'old.doc', b'\xd0\xcf\x11\xe0 not really a doc')
    toast(page, 'Save it as PDF or DOCX')


@pytest.fixture
def fonts_served(app):
    """The e2e server copy has no assets/; give it the two fonts."""
    dst = Path(app.dir) / 'assets'
    dst.mkdir(exist_ok=True)
    for f in ('NotoSans-Regular.ttf', 'NotoSans-Bold.ttf'):
        shutil.copy(ROOT / 'assets' / f, dst / f)


UNICODE_STRUCT = {
    'name': NAME, 'title': 'Analyst', 'email': 'zoe@example.test', 'phone': '', 'location': 'Kraków',
    'linkedin': '', 'website': '', 'authorization': '',
    'summary': 'Analyst who turns messy data → clear decisions; uptime ≥ 99.9%.',
    'experience': [{'title': 'Analityk danych', 'company': 'Łódź Żywność', 'location': 'Łódź', 'start': '2021', 'end': 'Present',
                    'bullets': ['Cut report time from 2 days → 3 hours', 'Coordinated with Đặng Thị Hương']}],
    'education': [], 'skills': {'technical': ['SQL'], 'tools': [], 'soft': []},
    'certifications': [], 'projects': [], 'languages': [], 'awards': [], 'additional': [],
}


def unicode_page(page, struct=UNICODE_STRUCT):
    page.route('**/parse-resume', lambda r: r.fulfill(status=200, content_type='application/json',
                                                     body=json.dumps({'struct': struct, 'dropped': []})))
    launch_fill(page, 'Data Analyst', 'Zoë Łukasiewicz-Nguyễn\n' + 'Analyst who turns data into decisions.\n' * 5)
    close_drawer(page)
    go(page, 'templates')
    expect(page.locator('#tpl-actions')).to_be_visible()


def pdf_text(data):
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return '\n'.join(p.extract_text() or '' for p in pdf.pages), [c['fontname'] for p in pdf.pages for c in p.chars]


def test_unicode_name_survives_pdf_export(ui, fonts_served):
    page = ui.page
    unicode_page(page)
    name, data = download(page, '#tpl-download')
    assert name == 'Zoe_Lukasiewicz-Nguyen_APEX_modern.pdf', name
    text, fonts = pdf_text(data)
    text = unicodedata.normalize('NFC', text)
    for needle in (NAME, 'Łódź Żywność', 'Đặng Thị Hương', 'Kraków'):
        assert needle in text, f'{needle!r} not extractable: {text[:400]!r}'
    # Noto Sans has no arrow / ≥ glyphs: they become readable ASCII, never mojibake.
    assert '2 days -> 3 hours' in text and '>= 99.9%' in text, text
    assert any('NotoSans' in f for f in fonts), set(fonts)
    ui.assert_clean()


def test_templates_change_the_pdf_and_docx(ui, fonts_served):
    page = ui.page
    unicode_page(page, dict(UNICODE_STRUCT, name='Marcus Delgado', summary='Plain ASCII summary.',
                            experience=[dict(UNICODE_STRUCT['experience'][0], company='Brightline', location='Houston',
                                             bullets=['Built reports'])]))
    _, modern = download(page, '#tpl-download')
    page.click('.tpl-card[data-tpl="classic"]')
    name, classic = download(page, '#tpl-download')
    assert name == 'Marcus_Delgado_APEX_classic.pdf'
    t_modern, f_modern = pdf_text(modern)
    t_classic, f_classic = pdf_text(classic)
    assert 'PROFESSIONAL EXPERIENCE' in t_modern and 'PROFESSIONAL EXPERIENCE' in t_classic
    assert any('Times' in f for f in f_classic) and not any('Times' in f for f in f_modern), (set(f_classic), set(f_modern))
    page.click('.tpl-card[data-tpl="creative"]')
    _, creative = download(page, '#tpl-download')
    t_creative, _ = pdf_text(creative)
    assert 'Professional Experience' in t_creative and 'PROFESSIONAL EXPERIENCE' not in t_creative

    page.click('.tpl-card[data-tpl="classic"]')
    _, docx = download(page, '#tpl-download-docx')
    xml = zipfile.ZipFile(io.BytesIO(docx)).read('word/document.xml').decode('utf-8')
    assert 'Times New Roman' in xml
    tabs = re.findall(r'<w:tab w:val="right" w:pos="(\d+)"', xml)
    assert tabs and set(tabs) == {'10080'}, tabs          # 8.5in - 2 x 0.75in = 7in = 10080 twips
    ui.assert_clean()


def test_export_uses_the_kept_edits_and_reparses_after_changes(ui):
    page = ui.page
    parsed = []

    def parse(route):
        text = json.loads(route.request.post_data)['resume']
        parsed.append(text)
        route.fulfill(status=200, content_type='application/json', body=json.dumps(
            {'struct': {'name': 'Marcus Delgado', 'summary': text.split('\n')[1]}, 'dropped': ['Invented Corp']}))
    page.route('**/parse-resume', parse)
    page.route('**/engine/render', lambda r: r.fulfill(status=200, content_type='application/json',
                                                      body=json.dumps({'text': 'Marcus Delgado\nUNTICKED VERSION\n' + 'x' * 120})))
    launch_fill(page, 'Data Analyst', 'Marcus Delgado\nORIGINAL TEXT\n' + 'y' * 120)
    close_drawer(page)
    page.evaluate("""handleEvent({type: 'engine_data', data: {original: 'Marcus Delgado\\nORIGINAL TEXT\\n' + 'y'.repeat(120),
        final: 'Marcus Delgado\\nEDITED TEXT\\n' + 'x'.repeat(120), target: {title: 'T'},
        changes: [{id: 'S', before: 'a', after: ['b']}], questions: []}})""")
    go(page, 'templates')
    _, data = download(page, '#tpl-download-txt')
    assert 'EDITED TEXT' in data.decode('utf-8') and 'EDITED TEXT' in parsed[-1]
    expect(page.locator('#tpl-dropped')).to_contain_text('Invented Corp')
    go(page, 'resume')
    page.locator('[data-engine="keep"][data-id="S"]').uncheck()
    expect(page.locator('#eng-final')).to_contain_text('UNTICKED VERSION')
    go(page, 'templates')
    _, data = download(page, '#tpl-download-txt')
    assert 'UNTICKED VERSION' in data.decode('utf-8'), 'the export must follow the untick'
    page.select_option('#tpl-source', 'launch')
    _, data = download(page, '#tpl-download-txt')
    assert 'ORIGINAL TEXT' in data.decode('utf-8')
    assert len(parsed) == 3
    ui.assert_clean()


def test_cover_letter_exports(ui, fonts_served):
    page = ui.page
    page.evaluate("handleEvent({type: 'cover_letter_data', letter: 'Dear Łódź team,\\n\\nI build reports.\\n\\nZoë'})")
    go(page, 'cl')
    name, data = download(page, '#cl-content [data-action="letterExport"][data-arg="pdf"]')
    assert name.endswith('Cover_Letter.pdf') and data[:5] == b'%PDF-'
    text, _ = pdf_text(data)
    assert 'Dear Łódź team,' in unicodedata.normalize('NFC', text)
    name, data = download(page, '#cl-content [data-action="letterExport"][data-arg="docx"]')
    assert 'I build reports.' in zipfile.ZipFile(io.BytesIO(data)).read('word/document.xml').decode('utf-8')
    name, data = download(page, '#cl-content [data-action="letterExport"][data-arg="txt"]')
    assert data.decode('utf-8').startswith('Dear Łódź team,')
    ui.assert_clean()


def test_saved_versions_compare_and_restore(ui):
    page = ui.page
    page.click('#open-drawer')
    page.fill('#resume-text', 'line one\nline two\nline three')
    page.fill('#ver-name', 'First')
    page.click('#ver-save')
    toast(page, 'Version saved')
    page.fill('#resume-text', 'line one\nline 2\nline three')
    page.click('#ver-list [data-action="verCompare"]')
    expect(page.locator('#ver-diff div.del')).to_contain_text('line two')
    expect(page.locator('#ver-diff div.add')).to_contain_text('line 2')
    page.click('#ver-list [data-action="verRestore"] >> nth=-1')
    assert page.input_value('#resume-text') == 'line one\nline two\nline three'
    expect(page.locator('#ver-list .mini-row')).to_have_count(2)       # the replaced text was kept as a version
    # Saved target roles switch title, seniority and posting together.
    page.fill('#job-title', 'Data Analyst'); page.select_option('#seniority', 'mid'); page.fill('#job-desc', 'POSTING A')
    page.click('#role-save')
    page.fill('#job-title', 'BI Lead'); page.select_option('#seniority', 'director'); page.fill('#job-desc', '')
    page.click('#role-save')
    page.select_option('#role-pick', label='Data Analyst · mid · with posting')
    assert page.input_value('#job-title') == 'Data Analyst' and page.input_value('#job-desc') == 'POSTING A'
    ui.assert_clean()
