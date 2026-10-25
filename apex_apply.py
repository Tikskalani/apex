"""The job agent's hands: open a job's application form in a browser window, fill every field,
answer the screening questions and submit it.

APEX's job agent prepares a tailored resume and cover letter for each job. Apply opens the
application in a visible Chromium window that keeps its own sign-ins (a profile folder beside
APEX), goes to the form and fills it: contact details and links, the resume PDF and the cover
letter, then every question it can answer: from the candidate's saved answers (work
authorization, sponsorship, start date, demographics...), by matching dropdown and checkbox
options, and, for free-text questions, with the `ask` callback the server passes (a
fact-checked model answer). With submit=True it presses Submit when no required question is
left and confirms the site accepted the application (a confirmation page; a screenshot is
kept). It never invents a factual answer: a required question it cannot answer from what the
candidate gave leaves the form open for the person. A bot check (CAPTCHA) is never worked
around: the form is left for the person.

Greenhouse (including company career pages that embed it), Lever and Ashby forms are
recognised; any other form is filled by its labels. Playwright is optional
(requirements-dev.txt): without it, `available()` is False and the page opens the posting.
"""
import os
import queue
import re
import threading
import time

PROFILE_DIR = os.environ.get('APEX_BROWSER_PROFILE') or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                     'apex_browser')
_JOBS = queue.Queue()
_STATE = {'thread': None, 'error': ''}
_LOCK = threading.Lock()

# What the candidate answers once (the profile's "application answers"). Empty demographic
# answers mean "decline to answer"; empty factual answers are never guessed.
DEFAULT_ANSWERS = {
    'authorized': '', 'sponsorship': '', 'relocate': '', 'salary': '', 'start': 'Two weeks after an offer',
    'hear': 'Job board', 'former': 'No', 'restrictions': 'No', 'adult': 'Yes',
    'country': 'United States', 'city': '', 'state': '', 'zip': '', 'address': '', 'preferred_name': '', 'pronouns': '',
    'gender': '', 'race': '', 'hispanic': '', 'veteran': '', 'disability': '', 'orientation': '', 'transgender': '',
}


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
    """The application form's URL: boards that keep it on a separate page, and Greenhouse forms
    embedded in a company's careers page (opened directly, without the page around them)."""
    b = board(url)
    base = (url or '').split('?')[0].rstrip('/')
    if b == 'lever' and not base.endswith('/apply'):
        return base + '/apply'
    if b == 'ashby' and not base.endswith('/application'):
        return base + '/application'
    m = re.search(r'[?&]gh_jid=(\d+)', url or '')
    if b == 'greenhouse' and m and 'greenhouse.io' not in (url or '').lower():
        return f'https://job-boards.greenhouse.io/embed/job_app?token={m.group(1)}'
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
    'location': ['input[name="location"]', 'input[id*="location" i]:not([role="combobox"])'],
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
        if el.count() and el.is_visible() and not el.input_value() and el.get_attribute('role') != 'combobox':
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
    k = 0
    while k < min(files.count(), 6):     # the form may re-render after an upload: look the inputs up again each time
        try:
            el = files.nth(k)
            ident = ' '.join(filter(None, [el.get_attribute('id', timeout=3000), el.get_attribute('name', timeout=3000),
                                           el.evaluate('e => (e.closest("label, div, fieldset") || {}).innerText || ""',
                                                       timeout=3000)])).lower()
            if 'autofill' in ident or 'parse' in ident:
                k += 1
                continue
            if not resume_done and re.search(r'resume|cv\b|_systemfield_resume', ident):
                el.set_input_files(pdf_path, timeout=10000)
                resume_done = True
                log.append('resume')
                page.wait_for_timeout(800)
            elif letter and not letter_done and 'cover' in ident and pdf_path:
                txt = os.path.splitext(pdf_path)[0] + '_cover_letter.txt'
                with open(txt, 'w', encoding='utf-8') as f:
                    f.write(letter)
                el.set_input_files(txt, timeout=10000)
                letter_done = True
                log.append('cover_letter')
                page.wait_for_timeout(800)
        except Exception:
            pass
        k += 1
    if not resume_done and files.count() >= 1:          # the first upload on the form is the resume
        try:
            ash = page.locator('#_systemfield_resume, input[name="_systemfield_resume"]')
            (ash.first if ash.count() else files.first).set_input_files(pdf_path, timeout=10000)
            log.append('resume')
        except Exception:
            pass
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


# ── the questions on a form ──────────────────────────────────────────────────

# Lists every question on the form: {i, kind, label, required, value, options}. Each control
# is tagged data-apex-q (radio/checkbox options also data-apex-opt) so it can be found again.
_EXTRACT = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return (r.width > 0 && r.height > 0 || ['radio', 'checkbox', 'file'].includes(e.type)) && s.visibility !== 'hidden' && s.display !== 'none'; };
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  const forLabel = e => { if (!e.id) return ''; const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`); return l ? clean(l.innerText) : ''; };
  const labelOf = e => {
    const f = forLabel(e); if (f) return f;
    const lb = e.getAttribute('aria-labelledby');
    if (lb) { const t = clean(lb.split(' ').map(i => document.getElementById(i)).filter(Boolean).map(x => x.innerText).join(' ')); if (t) return t; }
    if (e.getAttribute('aria-label')) return clean(e.getAttribute('aria-label'));
    const fs = e.closest('fieldset'); if (fs && fs.querySelector('legend')) return clean(fs.querySelector('legend').innerText);
    const w = e.closest('label'); if (w && clean(w.innerText)) return clean(w.innerText);
    let p = e.parentElement;
    for (let k = 0; k < 5 && p; k++, p = p.parentElement) {
      const l = p.querySelector('label, legend, [class*="label"], [class*="question"]');
      if (l && clean(l.innerText)) return clean(l.innerText);
    }
    return clean(e.placeholder || e.name || e.id);
  };
  const out = [], groups = {}, seen = new Map();
  let n = 0;
  for (const e of document.querySelectorAll('input, textarea, select, [role="combobox"]')) {
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes(e.type) || !vis(e)) continue;
    const kind = e.tagName === 'SELECT' ? 'select' : e.getAttribute('role') === 'combobox' ? 'combobox'
               : e.tagName === 'TEXTAREA' ? 'textarea' : (e.type || 'text');
    if (kind === 'radio' || kind === 'checkbox') {
      const fs = e.closest('fieldset, [role="radiogroup"], [role="group"]');
      const opt = forLabel(e) || clean((e.closest('label') || {}).innerText) || e.value;
      const mates = e.name ? [...document.querySelectorAll(`input[name="${CSS.escape(e.name)}"]`)] : [e];
      const key = (e.name || (fs && (fs.id || fs.getAttribute('aria-labelledby'))) || 'solo') + ':' + (mates.length > 1 || fs ? '' : opt);
      let g = groups[key];
      if (!g) {
        const head = fs ? clean((fs.querySelector('legend') || {}).innerText || (fs.getAttribute('aria-labelledby') && document.getElementById(fs.getAttribute('aria-labelledby')) || {}).innerText) : '';
        let q = head;
        if (!q && mates.length === 1 && !fs) q = opt;      // a lone checkbox: its own label is the question
        if (!q) {                       // no fieldset: the nearest heading above the options, inside their own block
          let p = e.parentElement;
          for (let k = 0; k < 6 && p && !q; k++, p = p.parentElement) {
            if ([...p.querySelectorAll('input, select, textarea')].some(x => !mates.includes(x))) break;
            for (const l of p.querySelectorAll('label, legend, [class*="label"], [class*="question"], [class*="title"]')) {
              const t = clean(l.innerText);
              if (t && !l.contains(e) && !l.querySelector('input') && t !== opt) { q = t; break; }
            }
          }
          if (!q) { const prev = (e.closest('[class*="field"], [class*="question"], div') || e).previousElementSibling;
                    if (prev && !prev.querySelector('input, select, textarea')) q = clean(prev.innerText); }
        }
        g = groups[key] = { i: n++, kind, label: q || labelOf(e), required: !!e.required, value: '', options: [] };
        out.push(g);
      }
      e.dataset.apexQ = g.i; e.dataset.apexOpt = g.options.length;
      g.options.push(opt);
      if (e.checked) g.value = g.value ? g.value + '; ' + opt : opt;
      if (e.required) g.required = true;
      continue;
    }
    const label = kind === 'file' ? (forLabel(e) || clean(e.name || e.id || 'file')) : labelOf(e);
    if (kind !== 'combobox' && kind !== 'file' && seen.get(label) === 'combobox') continue;   // the hidden twin of a custom dropdown
    if (!seen.has(label)) seen.set(label, kind);
    let value = kind === 'file' ? (e.files && e.files.length ? 'file' : '') : (e.value || '');
    if (kind === 'select') { const o = e.options[e.selectedIndex];
      value = !o || !o.value && /^(select|choose|--|please|$)/i.test(clean(o.text)) || /^(select|choose|--|please)/i.test(clean(o.text)) ? '' : clean(o.text); }
    if (kind === 'combobox') {            // the shown value of a custom dropdown
      const box = e.closest('[class*="control"]') || e.closest('[class*="shell"], [class*="container"]') || e.parentElement;
      const shown = box && box.querySelector('[class*="single-value"], [class*="singleValue"], [class*="multi-value"], [class*="multiValue"]');
      value = shown ? clean(shown.innerText) : value;
    }
    e.dataset.apexQ = n;
    out.push({ i: n++, kind, label, value, required: e.required || e.getAttribute('aria-required') === 'true' || /\*\s*$/.test(label),
               options: kind === 'select' ? [...e.options].map(o => clean(o.text)).filter(t => t && !/^(select|choose|--)/i.test(t)) : [] });
  }
  for (const g of out) if (/\*\s*$/.test(g.label)) g.required = true;
  return out;
}"""

_DECLINE = re.compile(r"decline|prefer not|don.?t wish|do not wish|not (?:to )?(?:say|answer|disclose|identify)|choose not|"
                      r"i do not want|rather not|wish not", re.I)

# (label pattern, answer key). The first match decides; order matters.
_RULES = [
    (r'gender|sex\b', 'gender'), (r'transgender', 'transgender'), (r'sexual orientation', 'orientation'),
    (r'hispanic|latin[oa]|latinx', 'hispanic'), (r'\brace\b|ethnic', 'race'), (r'veteran|military|served in', 'veteran'),
    (r'disabilit', 'disability'), (r'pronoun', 'pronouns'),
    (r'sponsor|visa|immigration', 'sponsorship'),
    (r'authori[sz]ed to work|legally (?:authori|eligible|able|permitted)|eligib\w* to work|right to work|work authori', 'authorized'),
    (r'previously (?:worked|been employed|applied)|ever (?:worked|been employed)|former employee|worked (?:at|for) .{0,40}before'
     r'|consulted for|currently (?:work|employed) (?:at|for)', 'former'),
    (r'employment agreement|non-?compete|post-employment|restrictive covenant', 'restrictions'),
    (r'18 years|at least 18|over 18|legal age', 'adult'),
    (r'relocat', 'relocate'),
    (r'hear about|how did you (?:find|learn|hear)|where did you (?:find|see|hear)|referral source|^source', 'hear'),
    (r'salary|compensation|pay (?:expectation|requirement)|desired pay|expected pay', 'salary'),
    (r'start date|when can you start|available to start|notice period|earliest', 'start'),
    (r'preferred (?:first )?name|name you.?d prefer|prefer(?:red)? to be called', 'preferred_name'),
    (r'country', 'country'), (r'zip|postal', 'zip'), (r'street|address', 'address'),
    (r'\bstate\b|province', 'state'), (r'\bcity\b|location|where are you (?:located|based)', 'city'),
    (r'^(?:mobile |cell |phone|telephone)', 'phone'), (r'^e ?mail', 'email'), (r'^first name', 'first_name'),
    (r'^last name|^surname|family name', 'last_name'), (r'^(?:full |legal )?name\W*$', 'full_name'),
    (r'linkedin', 'linkedin'), (r'github', 'github'), (r'website|portfolio|personal site', 'website'),
    (r'(?:current|recent)\W.{0,25}(?:company|employer)|(?:company|employer) name', 'company'),
    (r'(?:current|recent)\W.{0,25}(?:job )?title|job title', 'title'),
    (r'consent|i agree|agree to|acknowledg|privacy|certif|attest|by (?:selecting|checking|submitting)|accurate and complete', 'consent'),
    (r'accommodat', 'skip'), (r'^attach$|cover letter|resume|^cv\b', 'skip'),
]
_RULES = [(re.compile(p, re.I), k) for p, k in _RULES]
_EEO = {'gender', 'transgender', 'orientation', 'hispanic', 'race', 'veteran', 'disability', 'pronouns'}


def _norm(s):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', str(s or '').lower()).split())


def pick(options, value):
    """The option that says `value` (exact, starts with, or contains), or None."""
    v = _norm(value)
    if not v or not options:
        return None
    opts = [(o, _norm(o)) for o in options]
    for o, n in opts:
        if n == v:
            return o
    for o, n in opts:
        if n.startswith(v + ' ') or n.startswith(v) and v in ('yes', 'no'):
            return o
    if v in ('yes', 'no'):
        return None
    for o, n in opts:
        if v in n or (len(n) > 3 and n in v):
            return o
    if v in ('united states', 'usa', 'us'):
        return next((o for o, n in opts if n in ('us', 'usa', 'united states of america', 'u s')), None)
    return None


def decide(q, answers, contact, ask=None):
    """The answer to one question: a string (or, for a checkbox group, a list of options), or
    None when it cannot be answered from what the candidate gave. Free text and unmatched
    choices go to `ask(question, options)` (the server's fact-checked model answer)."""
    label, kind, options = q['label'], q['kind'], q.get('options') or []
    flat = ' '.join(re.sub(r'[^\w/+.\-\s]', ' ', label).split())         # "current (or most recent) company"
    key = next((k for rx, k in _RULES if rx.search(label) or rx.search(flat)), None)
    a = {**DEFAULT_ANSWERS, **{k: v for k, v in (answers or {}).items() if v not in (None, '')}}
    city = a['city'] or (contact.get('location') or '').split(',')[0].strip()
    if key == 'skip':
        return None
    if key == 'consent':
        if not q.get('required'):
            return None
        if kind in ('checkbox',):
            return options[:1]
        return pick(options, 'I agree') or pick(options, 'Yes') or pick(options, 'I acknowledge') or (options[0] if len(options) == 1 else None)
    if key in _EEO:
        given = a.get(key)
        if given:
            hit = pick(options, given) if options or kind in ('select', 'radio', 'combobox', 'checkbox') else given
            if hit or not options:
                return [hit] if kind == 'checkbox' and hit else hit
        dec = next((o for o in options if _DECLINE.search(o)), None)
        if kind == 'combobox' and not options:
            return 'Decline'
        return [dec] if kind == 'checkbox' and dec else dec
    first, last = split_name(contact.get('name'))
    contact_keys = {'phone': contact.get('phone'), 'email': contact.get('email'), 'first_name': first, 'last_name': last,
                    'full_name': ' '.join(filter(None, [first, last])), 'linkedin': contact.get('linkedin'), 'github': contact.get('github'), 'website': contact.get('website'),
                    'company': contact.get('company'), 'title': contact.get('title'),
                    'city': (f"{city}, {a['state']}" if a['state'] and kind in ('text', 'textarea') else city) or contact.get('location'),
                    'preferred_name': a['preferred_name'] or (contact.get('name') or '').split(' ')[0]}
    if key in contact_keys:
        val = contact_keys[key]
        if not val:
            return None
        return pick(options, val) if options else val
    if key:
        val = a.get(key)
        if key == 'salary' and not val and kind in ('text', 'textarea'):
            val = 'Open to a competitive offer for the role and location'
        if not val:
            return None
        if options:
            return pick(options, val) or (pick(options, 'Other') if key == 'hear' else None)
        return val
    if ask is None:
        return None
    if kind in ('text', 'textarea', 'number', 'url') or (kind == 'combobox' and not options):
        if not q.get('required') and kind != 'textarea':
            return None
        return ask(label, [])
    if options and q.get('required'):
        got = ask(label, options)
        return pick(options, got) if got else None
    return None


def _set(page, q, value):
    """Put one answer into the form. True when it took."""
    sel = f'[data-apex-q="{q["i"]}"]'
    kind = q['kind']
    if kind in ('radio', 'checkbox'):
        vals = value if isinstance(value, list) else [value]
        ok = False
        for v in vals:
            if v not in q['options']:
                continue
            el = page.locator(f'{sel}[data-apex-opt="{q["options"].index(v)}"]').first
            try:
                el.check(force=True, timeout=4000)
                ok = True
            except Exception:
                try:
                    el.click(force=True, timeout=4000)
                    ok = True
                except Exception:
                    pass
        return ok
    el = page.locator(sel).first
    if kind == 'select':
        el.select_option(label=value, timeout=5000)
        return True
    if kind == 'combobox':
        el.click(timeout=5000)
        try:
            el.fill(str(value)[:60], timeout=3000)
        except Exception:
            el.type(str(value)[:60], delay=20)
        page.wait_for_timeout(700)
        opts = page.locator('[role="option"]:visible')
        texts = [t.strip() for t in opts.all_inner_texts()][:200]
        hit = pick(texts, value) if texts else None
        if hit is not None:
            opts.nth(texts.index(hit)).click(timeout=4000)
        else:
            page.keyboard.press('Enter')
        page.wait_for_timeout(200)
        return True
    el.fill(str(value), timeout=5000)
    return True


def answer_questions(page, answers, contact, ask=None, log=None):
    """Answer every question it can. Returns the labels of required questions left unanswered."""
    log = log if log is not None else []
    for q in page.evaluate(_EXTRACT):
        if q['value'] or q['kind'] == 'file':
            continue
        if q['kind'] == 'combobox' and not q['options']:
            q['options'] = _combobox_options(page, q)
        try:
            v = decide(q, answers, contact, ask)
        except Exception:
            v = None
        if v in (None, '', []):
            continue
        try:
            if _set(page, q, v):
                log.append(q['label'][:60])
        except Exception:
            continue
    left = [q for q in page.evaluate(_EXTRACT) if q['required'] and not q['value']]
    return [q['label'][:120] for q in left]


def _combobox_options(page, q):
    """Open a custom dropdown and read its options (then close it)."""
    el = page.locator(f'[data-apex-q="{q["i"]}"]').first
    try:
        el.click(timeout=3000)
        page.wait_for_timeout(400)
        texts = [t.strip() for t in page.locator('[role="option"]:visible').all_inner_texts()][:200]
        page.keyboard.press('Escape')
        return texts if len(texts) < 150 else []          # a long list (countries): type to filter instead
    except Exception:
        return []


# ── submitting ───────────────────────────────────────────────────────────────

_DONE = re.compile(r"thank(?:s| you)[^.]{0,80}(?:appl|interest|submi)|application (?:has been |was |is )?(?:received|submitted|sent|complete)"
                   r"|we(?:'ve| have) received your|successfully (?:submitted|applied)|your application (?:is|has) (?:in|been)", re.I)
_CAPTCHA = ('iframe[src*="recaptcha/api2/bframe"]', 'iframe[src*="recaptcha/enterprise/bframe"]', 'iframe[src*="hcaptcha"]',
            'iframe[src*="challenges.cloudflare.com"]', '#challenge-form', '.cf-turnstile')


def _captcha(page):
    for sel in _CAPTCHA:
        loc = page.locator(sel)
        for k in range(min(loc.count(), 3)):
            try:
                box = loc.nth(k).bounding_box()
                if box and box['width'] > 60 and box['height'] > 60 and loc.nth(k).is_visible():
                    return True
            except Exception:
                continue
    return False


def submit(page, shot_path='', wait=25):
    """Press Submit and confirm the site accepted it. Returns (status, detail): 'submitted'
    (detail: the confirmation text), 'captcha' (a bot check is showing: left for the person),
    'invalid' (the site flagged fields: their messages) or 'unconfirmed'."""
    btn = None
    for loc in (page.locator('button[type="submit"]:visible, input[type="submit"]:visible'),
                page.get_by_role('button', name=re.compile(r'submit|send application|apply', re.I))):
        if loc.count():
            btn = loc.last
            break
    if btn is None:
        return 'invalid', 'no Submit button found'
    before = page.url
    btn.scroll_into_view_if_needed(timeout=5000)
    btn.click(timeout=8000)
    end = time.time() + wait
    while time.time() < end:
        page.wait_for_timeout(1000)
        try:
            body = page.inner_text('body', timeout=3000)
        except Exception:
            body = ''
        if _DONE.search(body) or (page.url != before and re.search(r'confirm|thank|success', page.url, re.I)):
            if shot_path:
                try:
                    page.screenshot(path=shot_path, full_page=True)
                except Exception:
                    pass
            m = _DONE.search(body)
            return 'submitted', (body[max(0, m.start() - 40):m.end() + 120] if m else page.url).strip()
        if _captcha(page):
            return 'captcha', 'a bot check (CAPTCHA) is showing'
    errs = page.evaluate("""() => [...document.querySelectorAll('[role="alert"], [class*="error"], [aria-invalid="true"]')]
        .map(e => (e.innerText || e.getAttribute('aria-label') || e.name || '').trim()).filter(t => t && t.length < 200).slice(0, 6)""")
    return ('invalid', '; '.join(errs)) if errs else ('unconfirmed', 'no confirmation appeared after Submit')


def fill_form(page, url, pdf_path, letter, contact, answers=None, ask=None, do_submit=False, shot_path=''):
    """Go to the application form, fill it and answer its questions; with do_submit, submit it.
    Returns {filled: [fields], missing: [required questions left], status, detail}. status is
    'filled' (not submitted), 'submitted', 'captcha', 'invalid', 'unconfirmed' or 'needs_you'
    (required questions APEX could not answer; nothing was submitted)."""
    page = reach_form(page, url)
    wall = sign_in_wall(page)
    if wall:
        return _left_for_person(page, {'filled': [], 'missing': [wall], 'status': 'needs_you', 'detail': wall})
    log = []
    first, last = split_name(contact.get('name'))
    if not _fill(page, 'first_name', first, log) | _fill(page, 'last_name', last, log):
        _fill(page, 'name', ' '.join(filter(None, [first, last])), log)
    for key in ('email', 'phone', 'linkedin', 'github', 'website'):
        _fill(page, key, contact.get(key), log)
    if pdf_path and os.path.exists(pdf_path):
        _attach(page, pdf_path, letter, log)
    page.wait_for_timeout(500)
    missing = answer_questions(page, answers or {}, contact, ask, log)
    if do_submit and not missing:
        status, detail = submit(page, shot_path)
    else:
        status, detail = ('needs_you', '') if do_submit else ('filled', '')
    return _left_for_person(page, {'filled': log, 'missing': missing, 'status': status, 'detail': detail})


def _left_for_person(page, r):
    """Show the person, in the APEX window, what is left to do on this form."""
    status = r['status']
    if status != 'submitted':
        msg = {'captcha': 'APEX filled this application. The site wants a bot check: complete it and press Submit.',
               'needs_you': 'APEX filled what it could. Answer the questions it left, then press Submit.',
               'invalid': 'APEX pressed Submit but the site flagged some fields: fix them and press Submit.',
               'unconfirmed': 'APEX pressed Submit but saw no confirmation: check this page.'}.get(
                   status, 'APEX filled this application. Check it and press Submit.')
        if status == 'needs_you' and r['detail']:
            msg = 'APEX needs you here: ' + r['detail']
        try:
            page.evaluate("""m => { const d = document.createElement('div'); d.textContent = m;
              d.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;background:#1f5fbf;color:#fff;'
                + 'font:600 14px system-ui,sans-serif;padding:10px 16px;text-align:center';
              document.body.appendChild(d); }""", msg)
        except Exception:
            pass
    r['url'] = page.url
    return r


_INPUTS = 'input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=search]), textarea, select'
_APPLY_TEXT = re.compile(r'^\s*(?:apply(?: now| for this (?:job|position|role)| on (?:the )?company(?:\'s)? (?:site|website))?'
                         r'|apply externally|continue to (?:apply|application)|i.?m interested)\s*$', re.I)


def _form_fields(page):
    try:
        return page.locator(_INPUTS).evaluate_all(
            'els => els.filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 }).length')
    except Exception:
        return 0


def _settle(page):
    try:
        page.wait_for_load_state('domcontentloaded', timeout=20000)
        page.wait_for_load_state('networkidle', timeout=8000)
    except Exception:
        pass


def reach_form(page, url, hops=3):
    """Open the posting and get to its application form: Greenhouse forms embedded in a careers
    page are opened directly; a job board's or aggregator's "Apply" button is followed (also into
    a new tab) until a page with a form, or a known applicant tracking system, is reached.
    Returns the page holding the form (which may be a new tab)."""
    page.goto(form_url(url), wait_until='domcontentloaded', timeout=45000)
    _settle(page)
    for _ in range(hops):
        gh = next((f.url for f in page.frames if 'greenhouse.io' in (f.url or '') and 'job_app' in (f.url or '')), '')
        if gh and gh != page.url:                        # a form embedded in a careers page: open it directly
            page.goto(gh, wait_until='domcontentloaded', timeout=45000)
            _settle(page)
        if board(page.url) and form_url(page.url) != page.url:
            page.goto(form_url(page.url), wait_until='domcontentloaded', timeout=45000)
            _settle(page)
        if _form_fields(page) >= 3:
            return page
        btn = None
        for loc in (page.get_by_role('link', name=_APPLY_TEXT), page.get_by_role('button', name=_APPLY_TEXT)):
            for k in range(min(loc.count(), 5)):
                try:
                    if loc.nth(k).is_visible():
                        btn = loc.nth(k)
                        break
                except Exception:
                    continue
            if btn is not None:
                break
        if btn is None:
            return page
        before = set(page.context.pages)
        try:
            btn.click(timeout=8000)
        except Exception:
            return page
        page.wait_for_timeout(2500)
        new = [p for p in page.context.pages if p not in before]
        if new:                                          # the employer's site opened in a new tab
            page = new[-1]
            page.bring_to_front()
        _settle(page)
    return page


_SSO = re.compile(r'linkedin\.com|indeed\.com|myworkdayjobs\.com|workday|taleo|successfactors|icims\.com/.*login|'
                  r'oraclecloud\.com', re.I)


def sign_in_wall(page):
    """'' when the form is open; otherwise what the person must do first (sign in, create an account)."""
    try:
        pw = page.locator('input[type=password]').evaluate_all(
            'els => els.filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 }).length')
    except Exception:
        pw = 0
    host = re.sub(r'^https?://(?:www\.)?([^/]+).*', r'\1', page.url)
    if pw and _form_fields(page) <= 4:
        return f'sign in or create an account on {host} once in the APEX window; APEX applies from then on'
    if _SSO.search(page.url) and _form_fields(page) < 3:
        return f'{host} needs you to sign in once in the APEX window'
    if _form_fields(page) < 3:
        return f'APEX could not find the application form on {host}; open it in the APEX window'
    return ''


# ── the APEX browser window (one thread owns Playwright) ─────────────────────

# The installed Chrome first: Playwright's own Chromium is unsigned, and Windows 11 (Smart App
# Control) refuses to start unsigned programs. APEX's window always uses its own profile folder.
CHANNELS = [c for c in (os.environ.get('APEX_BROWSER_CHANNEL') or 'chrome,msedge,chromium').split(',') if c]


def launch(pw):
    """The APEX browser window. Raises RuntimeError naming every browser tried."""
    errors = []
    for ch in CHANNELS:
        try:
            return pw.chromium.launch_persistent_context(
                PROFILE_DIR, channel=None if ch == 'chromium' else ch, headless=False, no_viewport=True,
                args=['--start-maximized'])
        except Exception as e:
            errors.append(f'{ch}: {str(e).splitlines()[0][:120]}')
    raise RuntimeError('APEX could not open a browser window (' + '; '.join(errors) + '). Install Google Chrome, '
                       'or close every Microsoft Edge window and try again.')


def _browser_loop():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        try:
            ctx = launch(pw)
        except Exception as e:
            _STATE['error'] = str(e)
            print(f'  [apply] {e}', flush=True)
            while True:                                  # every waiting job learns why at once
                try:
                    job = _JOBS.get_nowait()
                except queue.Empty:
                    break
                if job:
                    job[1](None, str(e))
            return
        _STATE['error'] = ''
        try:
            while True:
                job = _JOBS.get()
                if job is None:
                    break
                fn, done = job
                try:
                    done(fn(ctx), '')
                except Exception as e:
                    if 'closed' in str(e).lower():           # the person closed the window: start again next time
                        done(None, 'The browser window was closed; try again.')
                        break
                    done(None, f'{type(e).__name__}: {str(e)[:200]}')
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


def run(fn, timeout=240):
    """Run fn(browser_context) on the APEX browser thread. Returns (result, error or '')."""
    if not available():
        return None, 'The form filler needs Playwright (pip install -r requirements-dev.txt).'
    _ensure_browser()
    box, ev = {}, threading.Event()

    def done(result, err):
        box.update(result=result, err=err)
        ev.set()
    _JOBS.put((fn, done))
    end = time.time() + timeout
    while not ev.wait(1):
        t = _STATE['thread']
        if not (t and t.is_alive()):                     # the browser could not start, or crashed
            return None, _STATE['error'] or 'The APEX browser window closed unexpectedly; try again.'
        if time.time() > end:
            return None, 'The application took too long; it is open in the APEX browser window.'
    if box['err'] and 'closed' in box['err']:
        _STATE['thread'] = None
    return box['result'], box['err']


def make_pdf(ctx, app_url, struct, template='tech'):
    """The tailored resume as a PDF, drawn by APEX's own exporter (the page's ATS.pdf) in a
    background tab, so an application can go out with no APEX page open."""
    page = ctx.new_page()
    try:
        page.goto(app_url, wait_until='domcontentloaded', timeout=30000)
        for _ in range(60):          # APEX's CSP forbids string evaluation, so no wait_for_function: poll
            if page.evaluate("() => typeof ATS !== 'undefined'"):
                break
            page.wait_for_timeout(500)
        else:
            raise RuntimeError('the APEX page did not load its PDF exporter')
        return page.evaluate("""async ([st, tpl]) => {
            if (!st.name && st.raw) st = (await parseResumeText(st.raw)).struct;
            const out = await ATS.pdf(st, 'tailored', tpl, { blob: true });
            return await new Promise((res, rej) => { const r = new FileReader();
              r.onload = () => res(String(r.result).split(',')[1]); r.onerror = rej; r.readAsDataURL(out.blob); }); }""",
                             [struct, template])
    finally:
        page.close()


def apply_job(url, pdf_path, letter, contact, answers=None, ask=None, do_submit=False, shot_path='', pdf_maker=None):
    """Open the application in the APEX browser window, fill it, answer it and (do_submit) submit it.
    pdf_maker(ctx) -> path makes the resume PDF on the browser thread when pdf_path is ''.
    Returns (result dict from fill_form, error or '')."""
    def fn(ctx):
        path = pdf_path or (pdf_maker(ctx) if pdf_maker else '')
        page = ctx.new_page()
        page.bring_to_front()
        r = fill_form(page, url, path, letter, contact, answers, ask, do_submit, shot_path)
        if r['status'] == 'submitted':
            for pg in list(ctx.pages):
                if pg.url == r.get('url') or pg is page:
                    pg.close()
        return r
    return run(fn)


def open_and_fill(url, pdf_path, letter, contact, timeout=90):
    """Fill the application (contact, files, nothing else) without submitting. Returns (fields, error)."""
    r, err = apply_job(url, pdf_path, letter, contact)
    return (r or {}).get('filled', []), err
