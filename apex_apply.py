"""One-tap Apply: open a job's application form in a browser window and fill it in.

APEX's job agent prepares a tailored resume and cover letter for each approved job. Apply
opens the application in a visible Chromium window that keeps its own sign-ins (a profile
folder beside APEX), goes to the form, and fills what it can: name, email, phone, links,
location, the resume PDF and the cover letter. Greenhouse, Lever and Ashby forms are
recognised by their fields; any other form is filled by its labels where they are clear.

It never presses Submit. The person reviews the form, answers what is left (work
authorisation, demographic and custom questions) and submits it. Bot checks are left for
the person, never worked around.

Playwright is optional (requirements-dev.txt): without it, `available()` is False and the
page simply opens the posting.
"""
import os
import queue
import re
import threading

PROFILE_DIR = os.environ.get('APEX_BROWSER_PROFILE') or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                     'apex_browser')
_JOBS = queue.Queue()
_STATE = {'thread': None, 'error': ''}
_LOCK = threading.Lock()


def available():
    if os.environ.get('APEX_FORM_FILL') == '0':        # tests and headless machines: open the posting instead
        return False
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def board(url):
    """'greenhouse', 'lever', 'ashby' or '' from a posting URL."""
    u = (url or '').lower()
    if 'greenhouse.io' in u or 'gh_jid=' in u:
        return 'greenhouse'
    if 'jobs.lever.co' in u:
        return 'lever'
    if 'ashbyhq.com' in u:
        return 'ashby'
    return ''


def form_url(url):
    """The application form's URL for boards that keep it on a separate page."""
    b = board(url)
    base = (url or '').split('?')[0].rstrip('/')
    if b == 'lever' and not base.endswith('/apply'):
        return base + '/apply'
    if b == 'ashby' and not base.endswith('/application'):
        return base + '/application'
    return url


def split_name(full):
    parts = (full or '').replace(',', ' ').split()
    parts = [p for p in parts if not re.fullmatch(r'(?:PT|DPT|MBA|PhD|MD|RN|BSN|MS|BS|CPA|PE|SPT|OCS|SCS|NCS)\.?', p, re.I)]
    return (parts[0], ' '.join(parts[1:])) if parts else ('', '')


# Field order matters: the first selector that finds an empty, visible field wins.
_SELECTORS = {
    'first_name': ['#first_name', 'input[name="first_name"]', 'input[autocomplete="given-name"]'],
    'last_name': ['#last_name', 'input[name="last_name"]', 'input[autocomplete="family-name"]'],
    'name': ['input[name="name"]', 'input[name="_systemfield_name"]', 'input[autocomplete="name"]'],
    'email': ['#email', 'input[name="email"]', 'input[name="_systemfield_email"]', 'input[type="email"]'],
    'phone': ['#phone', 'input[name="phone"]', 'input[name="_systemfield_phone"]', 'input[type="tel"]'],
    'linkedin': ['input[name="urls[LinkedIn]"]', 'input[name*="linkedin" i]', 'input[id*="linkedin" i]'],
    'github': ['input[name="urls[GitHub]"]', 'input[name*="github" i]', 'input[id*="github" i]'],
    'website': ['input[name="urls[Portfolio]"]', 'input[name*="website" i]', 'input[id*="website" i]'],
    'location': ['input[name="location"]', 'input[id*="location" i]'],
}
_LABELS = {
    'first_name': r'^\s*first\s*name', 'last_name': r'^\s*last\s*name', 'name': r'^\s*(full\s*)?name\s*\*?\s*$',
    'email': r'e-?mail', 'phone': r'phone|mobile', 'linkedin': r'linkedin', 'github': r'github',
    'website': r'website|portfolio', 'location': r'^\s*(current\s*)?(location|city)',
}


def _fill(page, key, value, log):
    if not value:
        return False
    for sel in _SELECTORS.get(key, []):
        loc = page.locator(sel)
        for k in range(min(loc.count(), 3)):
            el = loc.nth(k)
            try:
                if el.is_visible() and not el.input_value():
                    el.fill(value)
                    log.append(key)
                    return True
            except Exception:
                continue
    try:                                   # any form: by its label
        el = page.get_by_label(re.compile(_LABELS[key], re.I)).first
        if el.count() and el.is_visible() and not el.input_value():
            el.fill(value)
            log.append(key)
            return True
    except Exception:
        pass
    return False


def _attach(page, pdf_path, letter, log):
    """The resume PDF into the resume upload; the cover letter into its text box (or as a text file)."""
    files = page.locator('input[type="file"]')
    resume_done = letter_done = False
    for k in range(files.count()):
        el = files.nth(k)
        ident = ' '.join(filter(None, [el.get_attribute('id'), el.get_attribute('name'),
                                       el.evaluate('e => (e.closest("label, div, fieldset") || {}).innerText || ""')])).lower()
        if not resume_done and re.search(r'resume|cv\b|_systemfield_resume', ident):
            el.set_input_files(pdf_path)
            resume_done = True
            log.append('resume')
        elif letter and not letter_done and 'cover' in ident and pdf_path:
            txt = os.path.splitext(pdf_path)[0] + '_cover_letter.txt'
            with open(txt, 'w', encoding='utf-8') as f:
                f.write(letter)
            el.set_input_files(txt)
            letter_done = True
            log.append('cover_letter')
    if not resume_done and files.count() == 1:          # one upload on the form: it is the resume
        files.first.set_input_files(pdf_path)
        log.append('resume')
    if letter and not letter_done:
        for sel in ['textarea[name="cover_letter_text"]', 'textarea[id*="cover" i]', 'textarea[name*="cover" i]',
                    'textarea[name="comments"]']:
            el = page.locator(sel).first
            try:
                if el.count() and el.is_visible() and not el.input_value():
                    el.fill(letter)
                    log.append('cover_letter')
                    break
            except Exception:
                continue


def fill_form(page, url, pdf_path, letter, contact):
    """Go to the application form and fill it. Returns the list of fields filled (never submits)."""
    page.goto(form_url(url), wait_until='domcontentloaded', timeout=45000)
    try:
        page.wait_for_load_state('networkidle', timeout=8000)
    except Exception:
        pass
    if board(url) == 'greenhouse':                       # older boards show the form after "Apply"
        for label in ('Apply for this job', 'Apply Now', 'Apply'):
            btn = page.get_by_role('button', name=label).first
            try:
                if btn.count() and btn.is_visible() and not page.locator('#first_name').count():
                    btn.click()
                    break
            except Exception:
                pass
    log = []
    first, last = split_name(contact.get('name'))
    if not _fill(page, 'first_name', first, log) | _fill(page, 'last_name', last, log):
        _fill(page, 'name', ' '.join(filter(None, [first, last])), log)
    for key in ('email', 'phone', 'linkedin', 'github', 'website', 'location'):
        _fill(page, key, contact.get(key), log)
    if pdf_path and os.path.exists(pdf_path):
        _attach(page, pdf_path, letter, log)
    try:
        page.evaluate("""() => { const d = document.createElement('div');
          d.textContent = 'APEX filled what it could. Check every field, answer the rest, then press Submit yourself.';
          d.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;background:#1f5fbf;color:#fff;'
            + 'font:600 14px system-ui,sans-serif;padding:10px 16px;text-align:center';
          document.body.appendChild(d); }""")
    except Exception:
        pass
    return log


def _browser_loop():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(PROFILE_DIR, headless=False, no_viewport=True,
                                                    args=['--start-maximized'])
        try:
            while True:
                job = _JOBS.get()
                if job is None:
                    break
                url, pdf_path, letter, contact, done = job
                try:
                    page = ctx.new_page()
                    page.bring_to_front()
                    done(fill_form(page, url, pdf_path, letter, contact), '')
                except Exception as e:
                    if 'closed' in str(e).lower():           # the person closed the window: start again next time
                        done([], 'The browser window was closed; press Apply again.')
                        break
                    done([], f'Could not fill the form: {str(e)[:200]}')
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def _ensure_browser():
    with _LOCK:
        t = _STATE['thread']
        if t and t.is_alive():
            return
        t = threading.Thread(target=_browser_loop, daemon=True)
        _STATE['thread'] = t
        t.start()


def open_and_fill(url, pdf_path, letter, contact, timeout=90):
    """Fill the application in the APEX browser window. Returns (fields filled, error or '')."""
    if not available():
        return [], 'The form filler needs Playwright (pip install -r requirements-dev.txt).'
    _ensure_browser()
    box, ev = {}, threading.Event()

    def done(filled, err):
        box.update(filled=filled, err=err)
        ev.set()
    _JOBS.put((url, pdf_path, letter, contact, done))
    if not ev.wait(timeout):
        return [], 'The form took too long to load; it is open in the APEX browser window.'
    if box['err'] and 'closed' in box['err']:
        _STATE['thread'] = None
    return box['filled'], box['err']
