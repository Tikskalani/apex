"""apex_engine.Doc: PDF-shaped and non-English resumes parse into the right blocks."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import apex_engine as E  # noqa: E402

WRAPPED = '''JANE DOE
jane@example.com

EXPERIENCE
Data Analyst, Acme Corp
2020 - 2024
- Built weekly revenue reporting for the finance leadership team across four
regions and two business units
- Reduced month-end close effort by automating reconciliations in
SQL and Excel
- Ran the vendor review
Senior Analyst, Beta Inc
2018 - 2020
- Led audits

EDUCATION
BS Math'''


def test_hard_wrapped_bullets_join_their_continuation():
    d = E.Doc(WRAPPED)
    bullets = [b for b in d.blocks if b['kind'] == 'bullet']
    assert [b['text'] for b in bullets] == [
        'Built weekly revenue reporting for the finance leadership team across four regions and two business units',
        'Reduced month-end close effort by automating reconciliations in SQL and Excel',
        'Ran the vendor review', 'Led audits']
    assert bullets[0]['end'] - bullets[0]['start'] == 2
    assert 'Beta Inc' in bullets[3]['group'] and 'Acme' in bullets[2]['group'], 'a title-case line is a new role'
    assert d.render({}) == WRAPPED
    out = d.render({'B1': ['Built weekly revenue reporting for finance leaders in four regions']})
    assert '- Built weekly revenue reporting for finance leaders in four regions\n- Reduced' in out
    assert 'regions and two business units' not in out, 'both original lines were replaced'


@pytest.mark.parametrize('marker', ['●', '➢', '✓', '✔', '►', '▸', '◆', '■', '□', '○', '❖', '➤'])
def test_more_bullet_markers(marker):
    text = f'JANE DOE\nEXPERIENCE\nAnalyst, Acme\n{marker} Built reports\n{marker} Led audits\nEDUCATION\nBS'
    d = E.Doc(text)
    assert [b['text'] for b in d.blocks] == ['Built reports', 'Led audits']
    assert d.render({'B1': ['Built weekly reports']}).count(f'{marker} Built weekly reports') == 1


def test_symbol_font_bullet_is_stripped():
    text = 'JANE DOE\nEXPERIENCE\nAnalyst, Acme\n\uf0b7 Built reports\n\uf0b7Led audits\nEDUCATION\nBS'
    d = E.Doc(text)
    assert [b['text'] for b in d.blocks] == ['Built reports', 'Led audits']
    assert d.render({}) == text
    assert '\uf0b7' not in d.render({'B1': ['Built weekly reports']}).split('\n')[3]


def test_marker_detection_is_per_section():
    text = ('JANE DOE\nSKILLS\n- SQL\n- Excel\nEXPERIENCE\nAnalyst, Acme Corp\n2020 - 2024\n'
            'Built weekly revenue reporting for the finance leadership team across four regions\n'
            'Reduced month-end close effort by automating reconciliations in SQL and Excel\nEDUCATION\nBS Math')
    d = E.Doc(text)
    assert [b['kind'] for b in d.blocks] == ['bullet', 'bullet']


@pytest.mark.parametrize('header,kind', [
    ('Professional Experience & Achievements', 'bullet'), ('Experience & Achievements', 'bullet'),
    ('Technical Experience', 'bullet'), ('Relevant Experience', 'bullet'),
    ('Berufserfahrung', 'bullet'), ('Experiencia Profesional', 'bullet'), ('Experiencia Laboral', 'bullet'),
    ('Expérience professionnelle', 'bullet'), ('Experiência Profissional', 'bullet'),
    ('Summary of Qualifications', 'summary'), ('Highlights of Qualifications', 'summary'),
    ('Career Summary', 'summary'), ('Zusammenfassung', 'summary'), ('Profil', 'summary'),
    ('Resumen', 'summary'), ('Perfil', 'summary'), ('Résumé', 'summary'), ('Resumo', 'summary'),
])
def test_header_variants(header, kind):
    body = '- Built reports for the team' if kind == 'bullet' else 'Analyst who builds reports.'
    text = f'JANE DOE\n{header}\n{"Analyst, Acme" + chr(10) if kind == "bullet" else ""}{body}\nEducation\nBS'
    d = E.Doc(text)
    assert [b['kind'] for b in d.blocks] == [kind], (header, d.section_of)


@pytest.mark.parametrize('header', ['Ausbildung', 'Educación', 'Formation', 'Educação', 'Kenntnisse', 'Habilidades',
                                    'Compétences'])
def test_foreign_protected_headers_end_the_experience_section(header):
    text = f'JANE DOE\nBerufserfahrung\nAnalyst, Acme\n- Built reports\n{header}\n- BS Math'
    d = E.Doc(text)
    assert [b['text'] for b in d.blocks] == ['Built reports']


def test_no_editable_block_returns_a_note():
    r = E.optimize(lambda *a, **k: '{}', 'JANE DOE\njane@example.com\nSome text without sections', {'title': 'Analyst'})
    assert r['final'] == 'JANE DOE\njane@example.com\nSome text without sections'
    assert 'EXPERIENCE' in r['note'] and 'bullet' in r['note']
    assert r['changes'] == [] and r['rejected'] == []


def test_all_caps_role_lines_stay_inside_experience():
    """Review regression: 'SOFTWARE ENGINEER' read as a section made its bullets uneditable."""
    text = ('JANE DOE\nEXPERIENCE\nSOFTWARE ENGINEER\nAcme Corp, 2021 - Present\n- Built the billing service in Python\n'
            'DATA ANALYST\nGlobex, 2018 - 2021\n- Maintained weekly SQL reports\nEDUCATION\nBS Math')
    d = E.Doc(text)
    assert [b['text'] for b in d.blocks if b['kind'] == 'bullet'] == ['Built the billing service in Python',
                                                                     'Maintained weekly SQL reports']
    assert [n for n, _, _ in d.sections()] == ['EXPERIENCE', 'EDUCATION']


def test_section_reorder_is_refused_when_names_repeat():
    d = E.Doc('JANE DOE\nPROJECTS\n- One thing done well here\nPROJECTS\n- Another thing done well\nEDUCATION\nBS')
    assert d.valid_section_order(['EDUCATION', 'PROJECTS', 'PROJECTS']) is None
