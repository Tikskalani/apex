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
recognised; any other form is filled by its labels, inside frames too, and multi-page forms
(Next / Continue) are walked page by page. Workday gets its own flow: Apply, "Autofill with
Resume", the account step (APEX creates the account with a generated password it keeps for
the person, or signs in with the one it kept), then the seven steps to Submit.

Playwright is optional (requirements-dev.txt): without it, `available()` is False and the
page opens the posting.
"""
import os
import queue
import re
import secrets
import string
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
    """'greenhouse', 'lever', 'ashby', 'workday' or '' from a posting URL."""
    u = (url or '').lower()
    if 'greenhouse.io' in u or 'gh_jid=' in u:
        return 'greenhouse'
    if 'jobs.lever.co' in u:
        return 'lever'
    if 'ashbyhq.com' in u:
        return 'ashby'
    if 'myworkdayjobs.com' in u or 'myworkdaysite.com' in u:
        return 'workday'
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


def host_of(url):
    return re.sub(r'^https?://(?:www\.)?([^/]+).*', r'\1', url or '').lower()


def _page_of(scope):
    """The Page behind a Page or a Frame (keyboard, url, screenshots live on the Page)."""
    return getattr(scope, 'page', scope)


# Field order matters: the first selector that finds an empty, visible field wins.
_SELECTORS = {
    'first_name': ['#first_name', 'input[name="first_name"]', 'input[autocomplete="given-name"]',
                   '[data-automation-id="legalNameSection_firstName"]'],
    'last_name': ['#last_name', 'input[name="last_name"]', 'input[autocomplete="family-name"]',
                  '[data-automation-id="legalNameSection_lastName"]'],
    'name': ['input[name="name"]', 'input[name="_systemfield_name"]', 'input[autocomplete="name"]'],
    'email': ['#email', 'input[name="email"]', 'input[name="_systemfield_email"]', 'input[type="email"]'],
    'phone': ['#phone', 'input[name="phone"]', 'input[name="_systemfield_phone"]', 'input[type="tel"]',
              '[data-automation-id="phone-number"]'],
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
_HONEYPOT = re.compile(r'beecatcher|honeypot|hp_|^hpot', re.I)      # bot traps: a real applicant never sees them


def _fill(scope, key, value, log):
    if not value:
        return False
    for sel in _SELECTORS.get(key, []):
        loc = scope.locator(sel)
        for k in range(min(loc.count(), 3)):
            el = loc.nth(k)
            try:
                if el.is_visible() and not el.input_value() and not _HONEYPOT.search(el.get_attribute('data-automation-id') or ''):
                    el.fill(value)
                    log.append(key)
                    return True
            except Exception:
                continue
    try:                                   # any form: by its label
        el = scope.get_by_label(re.compile(_LABELS[key], re.I)).first
        if el.count() and el.is_visible() and not el.input_value() and el.get_attribute('role') != 'combobox':
            el.fill(value)
            log.append(key)
            return True
    except Exception:
        pass
    return False


def _attach(scope, pdf_path, letter, log):
    """The resume PDF into the resume upload; the cover letter into its text box (or as a text file)."""
    page = _page_of(scope)
    files = scope.locator('input[type="file"]')
    resume_done = letter_done = False
    k = 0
    while k < min(files.count(), 6):     # the form may re-render after an upload: look the inputs up again each time
        try:
            el = files.nth(k)
            ident = ' '.join(filter(None, [el.get_attribute('id', timeout=3000), el.get_attribute('name', timeout=3000),
                                           el.get_attribute('data-automation-id', timeout=3000),
                                           el.evaluate('e => (e.closest("label, div, fieldset") || {}).innerText || ""',
                                                       timeout=3000)])).lower()
            if ('autofill' in ident or 'parse' in ident) and 'file-upload-input-ref' not in ident:
                k += 1
                continue
            if not resume_done and re.search(r'resume|cv\b|_systemfield_resume|file-upload-input-ref', ident):
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
            ash = scope.locator('#_systemfield_resume, input[name="_systemfield_resume"]')
            (ash.first if ash.count() else files.first).set_input_files(pdf_path, timeout=10000)
            log.append('resume')
        except Exception:
            pass
    if letter and not letter_done:
        for sel in ['textarea[name="cover_letter_text"]', 'textarea[id*="cover" i]', 'textarea[name*="cover" i]',
                    'textarea[name="comments"]']:
            el = scope.locator(sel).first
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
# Kinds: text-like inputs, textarea, select, combobox (a typeable custom dropdown), listbox (a
# button that opens a list: Workday), radio, checkbox, file.
_EXTRACT = r"""() => {
  const hiddenAncestor = e => { for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
    const s = getComputedStyle(p); if (s.display === 'none' || s.visibility === 'hidden') return true; } return false; };
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    if (['radio', 'checkbox', 'file'].includes(e.type)) return !hiddenAncestor(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
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
  document.querySelectorAll('[data-apex-q]').forEach(e => { delete e.dataset.apexQ; delete e.dataset.apexOpt; });
  const out = [], groups = {}, seen = new Map();
  let n = 0;
  for (const e of document.querySelectorAll('input, textarea, select, [role="combobox"], button[aria-haspopup="listbox"]')) {
    if (['hidden', 'submit', 'image', 'reset', 'search'].includes(e.type) && e.tagName !== 'BUTTON' || !vis(e)) continue;
    if (/beecatcher|honeypot/i.test(e.getAttribute('data-automation-id') || '')) continue;       // bot trap: never touch
    const kind = e.tagName === 'SELECT' ? 'select' : e.tagName === 'BUTTON' ? 'listbox'
               : e.getAttribute('role') === 'combobox' ? 'combobox' : e.tagName === 'TEXTAREA' ? 'textarea' : (e.type || 'text');
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
    let value = kind === 'file' ? (e.files && e.files.length ? 'file' : '') : kind === 'listbox' ? clean(e.innerText) : (e.value || '');
    if (kind === 'listbox' && /^(select one|select|choose|--|please select)?$/i.test(value)) value = '';
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
     r'|consulted for|currently (?:work|employed) (?:at|for)|current (?:employee|contractor)|currently an? employee', 'former'),
    (r'employment agreement|non-?compete|post-employment|restrictive covenant', 'restrictions'),
    (r'18 years|at least 18|over 18|legal age', 'adult'),
    (r'relocat', 'relocate'),
    (r'hear about|how did you (?:find|learn|hear)|where did you (?:find|see|hear)|referral source|^source', 'hear'),
    (r'salary|compensation|pay (?:expectation|requirement)|desired pay|expected pay', 'salary'),
    (r'start date|when can you start|available to start|notice period|earliest', 'start'),
    (r'preferred (?:first )?name|name you.?d prefer|prefer(?:red)? to be called', 'preferred_name'),
    (r'^today.?s date|^date\b|^signature date|^date signed', 'today'), (r'^month$', 'month'), (r'^day$', 'day'), (r'^year$', 'year'),
    (r'phone device type|phone type|device type', 'phone_type'), (r'country phone code|^country code', 'phone_code'),
    (r'country', 'country'), (r'zip|postal', 'zip'), (r'address line 2|apt|suite', 'skip'), (r'street|address', 'address'),
    (r'\bstate\b|province|county', 'state'), (r'\bcity\b|location|where are you (?:located|based)', 'city'),
    (r'extension|^ext\b', 'skip'),
    (r'^(?:mobile |cell |phone|telephone)', 'phone'), (r'^e ?mail|^verify your e ?mail', 'email'),
    (r'^(?:verify your |legal )?first name|^given name', 'first_name'),
    (r'^(?:verify your |legal )?last name|^surname|family name', 'last_name'), (r'^(?:full |legal )?name\W*$', 'full_name'),
    (r'linkedin', 'linkedin'), (r'github', 'github'), (r'website|portfolio|personal site', 'website'),
    (r'(?:current|recent)\W.{0,25}(?:company|employer)|(?:company|employer) name', 'company'),
    (r'(?:current|recent)\W.{0,25}(?:job )?title|job title', 'title'),
    (r'consent|i agree|agree to|acknowledg|privacy|certif|attest|by (?:selecting|checking|submitting)|accurate and complete|terms and conditions', 'consent'),
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
    contains = [(o, n) for o, n in opts if v in n or (len(n) > 3 and n in v)]
    if contains:                                       # the closest in length wins: "United States" over "United States Minor Outlying Islands"
        return min(contains, key=lambda on: (abs(len(on[1]) - len(v)), opts.index(on)))[0]
    if v in ('united states', 'usa', 'us'):
        return next((o for o, n in opts if n in ('us', 'usa', 'united states of america', 'u s')), None)
    return None


_STATE_ABBR = {'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR', 'california': 'CA', 'colorado': 'CO',
               'connecticut': 'CT', 'delaware': 'DE', 'florida': 'FL', 'georgia': 'GA', 'hawaii': 'HI', 'idaho': 'ID',
               'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA', 'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA',
               'maine': 'ME', 'maryland': 'MD', 'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN',
               'mississippi': 'MS', 'missouri': 'MO', 'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV',
               'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM', 'new york': 'NY', 'north carolina': 'NC',
               'north dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK', 'oregon': 'OR', 'pennsylvania': 'PA',
               'rhode island': 'RI', 'south carolina': 'SC', 'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX',
               'utah': 'UT', 'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA', 'west virginia': 'WV',
               'wisconsin': 'WI', 'wyoming': 'WY', 'district of columbia': 'DC'}


def decide(q, answers, contact, ask=None):
    """The answer to one question: a string (or, for a checkbox group, a list of options), or
    None when it cannot be answered from what the candidate gave. Free text and unmatched
    choices go to `ask(question, options)` (the server's fact-checked model answer)."""
    label, kind, options = q['label'], q['kind'], q.get('options') or []
    flat = ' '.join(re.sub(r'[^\w/+.\-\s]', ' ', label).split())         # "current (or most recent) company"
    key = next((k for rx, k in _RULES if rx.search(label) or rx.search(flat)), None)
    a = {**DEFAULT_ANSWERS, **{k: v for k, v in (answers or {}).items() if v not in (None, '')}}
    city = a['city'] or (contact.get('location') or '').split(',')[0].strip()
    choice = kind in ('select', 'radio', 'combobox', 'checkbox', 'listbox')
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
            hit = pick(options, given) if options or choice else given
            if hit or not options:
                return [hit] if kind == 'checkbox' and hit else hit
        dec = next((o for o in options if _DECLINE.search(o)), None)
        if kind in ('combobox', 'listbox') and not options:
            return 'Decline'
        return [dec] if kind == 'checkbox' and dec else dec
    if key == 'today':
        return time.strftime('%m/%d/%Y')
    if key in ('month', 'day', 'year'):
        return time.strftime({'month': '%m', 'day': '%d', 'year': '%Y'}[key])
    if key == 'phone_type':
        return pick(options, 'Mobile') or pick(options, 'Cell') or pick(options, 'Home') or (options[0] if options else 'Mobile')
    if key == 'phone_code':
        if not options and kind in ('combobox', 'listbox'):
            return 'United States'
        return pick(options, 'United States of America (+1)') or pick(options, 'United States') or pick(options, '+1')
    first, last = split_name(contact.get('name'))
    contact_keys = {'phone': contact.get('phone'), 'email': contact.get('email'), 'first_name': first, 'last_name': last,
                    'full_name': ' '.join(filter(None, [first, last])), 'linkedin': contact.get('linkedin'), 'github': contact.get('github'), 'website': contact.get('website'),
                    'company': contact.get('company'), 'title': contact.get('title'),
                    'city': (f"{city}, {a['state']}" if a['state'] and kind in ('text', 'textarea') and not re.match(r'\s*city\b', label, re.I)
                             else city) or contact.get('location'),
                    'preferred_name': a['preferred_name'] or (contact.get('name') or '').split(' ')[0]}
    if key in contact_keys:
        val = contact_keys[key]
        if not val:
            return None
        return pick(options, val) if options else val
    if key == 'state' and options:
        val = a.get('state') or ''
        return pick(options, val) or pick(options, _STATE_ABBR.get(val.lower(), '')) or None
    if key in ('country', 'state', 'hear') and not options and kind in ('combobox', 'listbox') and a.get(key):
        return a[key]                                    # typed into the box; _set only accepts a matching option
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
    if kind in ('text', 'textarea', 'number', 'url') or (kind in ('combobox', 'listbox') and not options):
        if not q.get('required') and kind != 'textarea':
            return None
        return ask(label, [])
    if options and q.get('required'):
        got = ask(label, options)
        return pick(options, got) if got else None
    return None


def _option_scope(scope, el):
    """Where this control's options live: the element its aria-controls/aria-owns names, else the page."""
    try:
        for attr in ('aria-controls', 'aria-owns'):
            ident = el.get_attribute(attr, timeout=800)
            if ident:
                box = scope.locator('#' + ident.split()[0].replace(':', '\\:'))
                if box.count():
                    return box.first
    except Exception:
        pass
    return scope


def _visible_options(scope, wait_ms=1800, el=None):
    """The options of the open dropdown, waiting up to wait_ms for them to render."""
    page = _page_of(scope)
    where = _option_scope(scope, el) if el is not None else scope
    end = time.time() + wait_ms / 1000
    while True:
        try:
            texts = [t.strip() for t in where.locator('[role="option"]:visible').all_inner_texts() if t.strip()][:300]
        except Exception:
            texts = []
        if texts or time.time() > end:
            return texts
        page.wait_for_timeout(200)


def _close_lists(page):
    try:
        page.keyboard.press('Escape')
        page.wait_for_timeout(120)
    except Exception:
        pass


def _set(scope, q, value):
    """Put one answer into the form. True when it took."""
    page = _page_of(scope)
    sel = f'[data-apex-q="{q["i"]}"]'
    kind = q['kind']
    if kind in ('radio', 'checkbox'):
        vals = value if isinstance(value, list) else [value]
        ok = False
        for v in vals:
            if v not in q['options']:
                continue
            el = scope.locator(f'{sel}[data-apex-opt="{q["options"].index(v)}"]').first
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
    el = scope.locator(sel).first
    if kind == 'select':
        el.select_option(label=value, timeout=5000)
        return True
    if kind == 'listbox':                              # a button that opens a list (Workday)
        _close_lists(page)
        el.click(timeout=5000)
        page.wait_for_timeout(500)
        texts = _visible_options(scope, el=el)
        hit = pick(texts, value) if texts else None
        if hit is None and len(texts) >= 40:            # a long list (countries): type to jump, then look again
            page.keyboard.type(str(value)[:30], delay=15)
            page.wait_for_timeout(500)
            texts = _visible_options(scope, el=el)
            hit = pick(texts, value) if texts else None
        if hit is None:
            _close_lists(page)
            return False
        _option_scope(scope, el).locator('[role="option"]:visible').nth(texts.index(hit)).click(timeout=4000)
        page.wait_for_timeout(300)
        return True
    if kind == 'combobox':
        _close_lists(page)
        el.click(timeout=5000)
        try:
            el.fill(str(value)[:60], timeout=3000)
        except Exception:
            el.type(str(value)[:60], delay=20)
        texts = _visible_options(scope, el=el)
        hit = pick(texts, value) if texts else None
        if hit is None and texts and len(str(value)) > 3:    # the typed text narrowed the list: a shorter prefix may show it
            el.fill(str(value)[:4], timeout=3000)
            texts = _visible_options(scope, el=el)
            hit = pick(texts, value) if texts else None
        if hit is None:                                  # never Enter blindly: that picks whatever is first
            try:
                el.fill('', timeout=2000)
            except Exception:
                pass
            _close_lists(page)
            return False
        _option_scope(scope, el).locator('[role="option"]:visible').nth(texts.index(hit)).click(timeout=4000)
        page.wait_for_timeout(250)
        return True
    el.fill(str(value), timeout=5000)
    return True


def answer_questions(scope, answers, contact, ask=None, log=None, passes=3):
    """Answer every question it can, in passes (an answer can reveal further questions).
    Returns the labels of required questions left unanswered."""
    log = log if log is not None else []
    tried = set()
    for _ in range(passes):
        progress = False
        for q in scope.evaluate(_EXTRACT):
            if q['value'] or q['kind'] == 'file' or q['label'] in tried:
                continue
            tried.add(q['label'])
            if q['kind'] in ('combobox', 'listbox') and not q['options']:
                q['options'] = _combobox_options(scope, q)
            try:
                v = decide(q, answers, contact, ask)
            except Exception:
                v = None
            if v in (None, '', []):
                continue
            try:
                if _set(scope, q, v):
                    log.append(q['label'][:60])
                    progress = True
            except Exception:
                continue
        if not progress:
            break
    left = [q for q in scope.evaluate(_EXTRACT) if q['required'] and not q['value']]
    return [q['label'][:120] for q in left]


def _combobox_options(scope, q):
    """Open a custom dropdown and read its options (then close it). A list that shows a single
    Yes or No has not finished rendering: it counts as unreadable rather than as a choice."""
    page = _page_of(scope)
    el = scope.locator(f'[data-apex-q="{q["i"]}"]').first
    try:
        _close_lists(page)
        el.click(timeout=3000)
        texts = _visible_options(scope, el=el)
        _close_lists(page)
        if len(texts) == 1 and _norm(texts[0]) in ('yes', 'no'):
            return []
        return texts if len(texts) < 150 else []          # a long list (countries): type to filter instead
    except Exception:
        return []


# ── submitting ───────────────────────────────────────────────────────────────

_DONE = re.compile(r"thank(?:s| you)[^.]{0,80}(?:appl|interest|submi)|application (?:has been |was |is )?(?:received|submitted|sent|complete)"
                   r"|we(?:'ve| have) received your|successfully (?:submitted|applied)|your application (?:is|has) (?:in|been)"
                   r"|congratulations", re.I)
_CAPTCHA = ('iframe[src*="recaptcha/api2/bframe"]', 'iframe[src*="recaptcha/enterprise/bframe"]', 'iframe[src*="hcaptcha"]',
            'iframe[src*="challenges.cloudflare.com"]', '#challenge-form', '.cf-turnstile')
_NEXT_TEXT = re.compile(r'^\s*(?:next|continue|save (?:and|&) continue|proceed|next step|save & next)\s*$', re.I)
_SUBMIT_TEXT = re.compile(r'submit|send application|^\s*apply\s*$|finish', re.I)


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


def _errors(scope):
    try:
        return scope.evaluate("""() => [...document.querySelectorAll('[role="alert"], [class*="error"], [aria-invalid="true"], [data-automation-id="errorMessage"]')]
            .map(e => (e.innerText || e.getAttribute('aria-label') || e.name || '').trim()).filter(t => t && t.length < 200).slice(0, 6)""")
    except Exception:
        return []


def _button(scope, text_rx):
    """The last visible button (or submit input) whose text matches."""
    found = None
    for loc in (scope.locator('button:visible, input[type="submit"]:visible, [role="button"]:visible'),):
        for k in range(min(loc.count(), 40)):
            el = loc.nth(k)
            try:
                txt = el.inner_text(timeout=1000) if el.evaluate('e => e.tagName') != 'INPUT' else (el.get_attribute('value') or '')
            except Exception:
                continue
            if text_rx.search(txt or ''):
                found = el
    return found


def _submit_button(scope):
    """The Submit control of the application form: inside the form that holds the filled fields when
    there is one, never a button that reports, saves, shares or searches."""
    try:
        sel = scope.evaluate("""() => {
          const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
          const fields = [...document.querySelectorAll('input[type=file], [data-apex-q]')];
          const form = fields.map(f => f.closest('form')).find(Boolean);
          const pool = form ? [...form.querySelectorAll('button, input[type=submit]')] : [...document.querySelectorAll('button[type=submit], input[type=submit], button')];
          const text = b => (b.innerText || b.value || b.getAttribute('aria-label') || '').trim();
          const bad = /report|alert|save (?:job|this|search)|share|sign ?in|log ?in|subscribe|newsletter|search|follow|cancel|back|close|delete|remove|unsubscribe|flag|add |upload|attach|choose|browse/i;
          const good = /submit|send application|^apply|finish|complete application/i;
          const cands = pool.filter(b => vis(b) && !bad.test(text(b)) && (b.type === 'submit' || good.test(text(b))));
          const pick = cands.reverse().find(b => good.test(text(b))) || cands[0];
          if (!pick) return '';
          pick.setAttribute('data-apex-submit', '1');
          return '[data-apex-submit="1"]';
        }""")
    except Exception:
        return None
    if not sel:
        return None
    el = scope.locator(sel).first
    try:
        return el if el.is_visible() else None
    except Exception:
        return None


def submit(scope, shot_path='', wait=25, button=None):
    """Press Submit and confirm the site accepted it. Returns (status, detail): 'submitted'
    (detail: the confirmation text), 'captcha' (a bot check is showing: left for the person),
    'invalid' (the site flagged fields: their messages) or 'unconfirmed'."""
    page = _page_of(scope)
    btn = button
    if btn is None:
        btn = _submit_button(scope)
    if btn is None:
        return 'invalid', 'no Submit button found on the application form'
    before = page.url
    btn.scroll_into_view_if_needed(timeout=5000)
    btn.click(timeout=8000)
    end = time.time() + wait
    while time.time() < end:
        page.wait_for_timeout(1000)
        try:
            body = scope.inner_text('body', timeout=3000)
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
    errs = _errors(scope)
    return ('invalid', '; '.join(errs)) if errs else ('unconfirmed', 'no confirmation appeared after Submit')


# ── walking a form: one page, or many ────────────────────────────────────────

def fill_page(scope, pdf_path, letter, contact, answers, ask, log):
    """Fill what this page of the form asks: contact fields, files, every question. Returns the
    required questions left unanswered."""
    first, last = split_name(contact.get('name'))
    if not _fill(scope, 'first_name', first, log) | _fill(scope, 'last_name', last, log):
        _fill(scope, 'name', ' '.join(filter(None, [first, last])), log)
    for key in ('email', 'phone', 'linkedin', 'github', 'website'):
        _fill(scope, key, contact.get(key), log)
    if pdf_path and os.path.exists(pdf_path) and 'resume' not in log:
        _attach(scope, pdf_path, letter, log)
    _page_of(scope).wait_for_timeout(500)
    return answer_questions(scope, answers or {}, contact, ask, log)


def walk_form(page, pdf_path, letter, contact, answers, ask, do_submit, shot_path, log, pages=10, next_button=None):
    """Fill a form page by page: fill, press Next/Continue while there is one, and on the last page
    Submit (when asked and nothing required is left). Returns (status, detail, missing)."""
    missing = []
    for _ in range(pages):
        scope = _form_scope(page)
        missing = fill_page(scope, pdf_path, letter, contact, answers, ask, log)
        nxt = next_button(scope) if next_button else _button(scope, _NEXT_TEXT)
        nxt_text = ''
        if nxt is not None:
            try:
                nxt_text = nxt.inner_text(timeout=1000)
            except Exception:
                nxt_text = ''
        if nxt is not None and _NEVER_PRESS.search(nxt_text or ''):
            nxt = None
        is_last = nxt is None or _SUBMIT_TEXT.search(nxt_text or '')
        if is_last:
            if not do_submit:
                return 'filled', '', missing
            if missing:
                return 'needs_you', '', missing
            final = nxt if (nxt is not None and _SUBMIT_TEXT.search(nxt_text or '')) else None
            return (*submit(scope, shot_path, button=final), missing)
        if missing:                                      # the site would refuse Next; leave this page to the person
            return ('needs_you' if do_submit else 'filled'), '', missing
        step_before = _step_label(scope)
        try:
            nxt.scroll_into_view_if_needed(timeout=4000)
            nxt.click(timeout=8000)
        except Exception as e:
            return 'invalid', f'could not press Next: {str(e)[:120]}', missing
        page.wait_for_timeout(1500)
        _settle(page)
        scope = _form_scope(page)
        errs = _errors(scope)
        if errs and _step_label(scope) == step_before and step_before:
            return 'needs_you', 'the site flagged: ' + '; '.join(errs)[:200], [e[:120] for e in errs] or missing
        if _captcha(page):
            return 'captcha', 'a bot check (CAPTCHA) is showing', missing
    return 'unconfirmed', 'the form has more pages than APEX walks', missing


def _step_label(scope):
    try:
        el = scope.locator('[data-automation-id="progressBarActiveStep"], [aria-current="step"], .active-step').first
        return el.inner_text(timeout=800).strip() if el.count() else _page_of(scope).url
    except Exception:
        return _page_of(scope).url


def fill_form(page, url, pdf_path, letter, contact, answers=None, ask=None, do_submit=False, shot_path='',
              logins=None, on_login=None, website='', title=''):
    """Go to the application form, fill it and answer its questions; with do_submit, submit it.
    Returns {filled: [fields], missing: [required questions left], status, detail}. status is
    'filled' (not submitted), 'submitted', 'captcha', 'invalid', 'unconfirmed' or 'needs_you'
    (required questions APEX could not answer; nothing was submitted)."""
    log = []
    if board(url) == 'workday':
        return workday_flow(page, url, pdf_path, letter, contact, answers, ask, do_submit, shot_path, logins or {}, on_login, log)
    page = reach_form(page, url)
    wall = sign_in_wall(page)
    if wall and is_aggregator(page.url) and website:
        found = find_on_careers_site(page, website, title)
        if found is not None:
            page = reach_form(found, found.url)
            if board(page.url) == 'workday':
                return workday_flow(page, page.url, pdf_path, letter, contact, answers, ask, do_submit, shot_path, logins or {}, on_login, log)
            wall = sign_in_wall(page)
    if wall:
        return _left_for_person(page, {'filled': [], 'missing': [wall], 'status': 'needs_you', 'detail': wall}, shot_path)
    status, detail, missing = walk_form(page, pdf_path, letter, contact, answers, ask, do_submit, shot_path, log)
    return _left_for_person(page, {'filled': log, 'missing': missing, 'status': status, 'detail': detail}, shot_path)


def _left_for_person(page, r, shot_path=''):
    """Show the person, in the APEX window, what is left to do on this form; keep a picture of it."""
    status = r['status']
    if status != 'submitted' and shot_path:
        try:
            page.screenshot(path=re.sub(r'_confirmation\.png$', '', shot_path) + '_left.png', full_page=True)
        except Exception:
            pass
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


_INPUTS = ('input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=search]), textarea, select, '
           'button[aria-haspopup="listbox"]')
# Job boards and aggregators: their pages carry alert sign-ups, "report this listing" and search
# forms, never the employer's application. APEX only follows their Apply link outward.
AGGREGATOR_HOSTS = ('linkedin.com', 'indeed.com', 'glassdoor.com', 'ziprecruiter.com', 'learn4good.com', 'jobleads.com',
                    'trabajo.org', 'bebee.com', 'jobilize.com', 'dice.com', 'theladders.com', 'jobserve.com', 'talent.com',
                    'simplyhired.com', 'monster.com', 'jobrapido.com', 'adzuna.com', 'careerjet.com', 'jooble.org',
                    'jobtome.com', 'neuvoo.com', 'lensa.com', 'whatjobs.com', 'joblift.com', 'jobisjob.com', 'recruit.net',
                    'jobgether.com', 'himalayas.app', 'remoteok.com', 'remotive.com', 'jobicy.com', 'wellfound.com')
_NEVER_PRESS = re.compile(r'report|alert|save (?:job|this|search)|share|sign ?in|log ?in|subscribe|newsletter|search|follow|'
                          r'cancel|back|close|delete|remove|unsubscribe|flag', re.I)


def is_aggregator(url):
    h = host_of(url)
    return any(h == a or h.endswith('.' + a) for a in AGGREGATOR_HOSTS)


def is_application_form(scope):
    """Does this page hold an application form (not a job-alert or search box)? A resume upload,
    or a name field with an email or phone field and at least four fields in all."""
    try:
        return bool(scope.evaluate("""() => {
          const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
          const hiddenAncestor = e => { for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
            const s = getComputedStyle(p); if (s.display === 'none' || s.visibility === 'hidden') return true; } return false; };
          const els = [...document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select, button[aria-haspopup="listbox"]')];
          const files = els.filter(e => e.type === 'file' && !hiddenAncestor(e)).length;
          const shown = els.filter(e => e.type === 'file' ? !hiddenAncestor(e) : vis(e));
          if (files && shown.length < 2) return false;        // a lone upload box (search by resume) is not an application
          const txt = e => ((e.id || '') + ' ' + (e.name || '') + ' ' + (e.getAttribute('aria-label') || '') + ' ' + (e.placeholder || '') + ' '
            + ((e.labels && e.labels[0]) ? e.labels[0].innerText : '') + ' ' + (e.getAttribute('data-automation-id') || '')).toLowerCase();
          const has = rx => shown.some(e => rx.test(txt(e)));
          if (files) return true;
          return shown.length >= 4 && has(/name/) && (has(/e-?mail/) || has(/phone|tel/) || shown.some(e => e.type === 'email' || e.type === 'tel'));
        }"""))
    except Exception:
        return False
_APPLY_TEXT = re.compile(r'^\s*(?:apply(?: now| for this (?:job|position|role)| on (?:the )?company(?:\'s)? (?:site|website))?'
                         r'|apply externally|continue to (?:apply|application)|i.?m interested)\s*$', re.I)


def _form_fields(scope):
    try:
        return scope.locator(_INPUTS).evaluate_all(
            'els => els.filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 }).length')
    except Exception:
        return 0


def _form_scope(page):
    """The page, or the frame inside it, that holds the application form (iCIMS and others
    put the form in an iframe)."""
    best, best_n = page, _form_fields(page)
    for f in page.frames:
        if f == page.main_frame:
            continue
        try:
            n = _form_fields(f)
        except Exception:
            continue
        if n > best_n:
            best, best_n = f, n
    return best


_BANNER_DECLINE = re.compile(r'^\s*(?:reject all|decline(?: all)?|necessary only|only (?:necessary|essential)|refuse)\s*$', re.I)
_BANNER_OK = re.compile(r'^\s*(?:accept all|allow all|i understand|got it|accept(?: cookies)?|agree|ok(?:ay)?|continue)\s*$', re.I)


def dismiss_banners(page):
    """Close a cookie or consent banner that would sit over the page (decline when it offers that)."""
    for rx in (_BANNER_DECLINE, _BANNER_OK):
        try:
            loc = page.get_by_role('button', name=rx)
            for k in range(min(loc.count(), 4)):
                b = loc.nth(k)
                if b.is_visible():
                    b.click(timeout=2000)
                    page.wait_for_timeout(400)
                    return True
        except Exception:
            continue
    return False


def _settle(page):
    try:
        page.wait_for_load_state('domcontentloaded', timeout=20000)
        page.wait_for_load_state('networkidle', timeout=8000)
    except Exception:
        pass
    dismiss_banners(page)


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
        if board(page.url) and board(page.url) != 'workday' and form_url(page.url) != page.url:
            page.goto(form_url(page.url), wait_until='domcontentloaded', timeout=45000)
            _settle(page)
        if not is_aggregator(page.url) and is_application_form(_form_scope(page)):
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


_CAREERS_PATHS = ('/careers', '/careers/jobs', '/jobs', '/careers/search', '/en/careers', '/company/careers', '/about/careers', '')


_TITLE_ABBR = (('machine learning', 'ml'), ('artificial intelligence', 'ai'), ('software engineer', 'swe'), ('natural language processing', 'nlp'),
               ('site reliability engineer', 'sre'), ('large language model', 'llm'))


def _title_words(t):
    """A title's distinguishing words: abbreviations unified, level and location words dropped."""
    t = re.split(r'\s[-|,(]\s?|\(|\|', str(t or ''), 1)[0]        # "Staff ML Engineer - Houston" -> "Staff ML Engineer"
    n = ' ' + _norm(t) + ' '
    for long, short in _TITLE_ABBR:
        n = n.replace(' ' + long + ' ', ' ' + short + ' ')
    return {w for w in n.split() if (len(w) > 2 or w in ('ml', 'ai')) and w not in ('and', 'the', 'for', 'with', 'senior', 'staff', 'lead', 'principal', 'remote', 'hybrid', 'sr', 'jr')}


def find_on_careers_site(page, website, title):
    """When the only link is a job board's, look for the job on the employer's own careers pages:
    follow the link whose text matches the title best. Returns the page on the posting, or None."""
    if not website:
        return None
    base = website if website.startswith(('http', 'file:')) else 'https://' + website
    want = _title_words(title)
    if not want:
        return None
    for path in _CAREERS_PATHS:
        try:
            page.goto(base.rstrip('/') + path, wait_until='domcontentloaded', timeout=25000)
        except Exception:
            continue
        _settle(page)
        try:
            links = page.evaluate("""() => [...document.querySelectorAll('a[href]')].map(a => [a.innerText.trim().slice(0, 140), a.href])
                .filter(([t, h]) => t && t.length > 8 && /^(?:https?|file):/.test(h))""")
        except Exception:
            continue
        best, score = None, 0.0
        for text, href in links:
            have = _title_words(text)
            if not have:
                continue
            sc = len(want & have) / len(want | have)
            if sc > score:
                best, score = href, sc
        if best and score >= 0.5:
            try:
                page.goto(best, wait_until='domcontentloaded', timeout=30000)
                _settle(page)
                return page
            except Exception:
                return None
    return None


_SSO = re.compile(r'linkedin\.com|indeed\.com|taleo|successfactors|icims\.com/.*login|oraclecloud\.com', re.I)


def sign_in_wall(page):
    """'' when the form is open; otherwise what the person must do first (sign in, create an account)."""
    scope = _form_scope(page)
    try:
        pw = scope.locator('input[type=password]').evaluate_all(
            'els => els.filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 }).length')
    except Exception:
        pw = 0
    host = host_of(page.url)
    n = _form_fields(scope)
    if is_aggregator(page.url):
        return f'{host} only has a copy of this posting and no link to the employer\'s application; paste the employer\'s own posting link'
    if not is_application_form(scope) and n >= 3 and not pw:
        return f'the form on {host} is not an application form (a job alert or search box); open the posting in the APEX window'
    if pw and n <= 4:
        return f'sign in or create an account on {host} once in the APEX window; APEX applies from then on'
    if _SSO.search(page.url) and n < 3:
        return f'{host} needs you to sign in once in the APEX window'
    if n < 3:
        return f'APEX could not find the application form on {host}; open it in the APEX window'
    return ''


# ── Workday ──────────────────────────────────────────────────────────────────
# Workday career sites (company.wdN.myworkdayjobs.com) share one layout, addressed by
# data-automation-id: Apply -> "Autofill with Resume" -> Create Account / Sign In -> seven steps
# (My Information, My Experience, Application Questions, Voluntary Disclosures, Self Identify,
# Review) -> Submit. The account belongs to the candidate: APEX creates it with a strong
# password it keeps for them (the server stores it; nothing is ever printed), and signs in with
# it next time. A verification code Workday emails is for the person to type.

def new_password(n=16):
    """A password that satisfies Workday's rules (8+, upper, lower, digit, special) and most others."""
    alphabet = string.ascii_letters + string.digits
    core = ''.join(secrets.choice(alphabet) for _ in range(n - 4))
    return secrets.choice(string.ascii_uppercase) + secrets.choice(string.ascii_lowercase) + core + secrets.choice(string.digits) + '!'


def _wd(scope, aid):
    """The visible control with this automation id (a flow can keep a hidden twin on the page)."""
    loc = scope.locator(f'[data-automation-id="{aid}"]')
    try:
        for k in range(min(loc.count(), 6)):
            if loc.nth(k).is_visible():
                return loc.nth(k)
    except Exception:
        pass
    return loc.first


def _wd_visible(scope, aid):
    try:
        return _wd(scope, aid).is_visible()
    except Exception:
        return False


def _wd_next_button(scope):
    loc = _wd(scope, 'bottom-navigation-next-button')
    try:
        return loc.first if loc.count() and loc.first.is_visible() else None
    except Exception:
        return None


def workday_account(page, contact, logins, on_login):
    """Get past Workday's Create Account / Sign In step. Returns '' when signed in (or the step
    was not shown), else what the person must do."""
    host = host_of(page.url)
    email = (contact.get('email') or '').strip()
    scope = _form_scope(page)
    if _wd_visible(scope, 'SignInWithEmailButton'):
        _wd(scope, 'SignInWithEmailButton').click(timeout=8000)
        page.wait_for_timeout(1500)
    if not _wd_visible(scope, 'email'):
        return ''                                        # already signed in (the window keeps sessions)
    if not email:
        return f'sign in on {host} in the APEX window (no email on the resume to create an account with)'
    saved = (logins or {}).get(host)
    if saved and _wd_visible(scope, 'password') and not _wd_visible(scope, 'verifyPassword'):
        _wd(scope, 'email').fill(saved['email'])
        _wd(scope, 'password').fill(saved['password'])
        _wd(scope, 'signInSubmitButton').click(timeout=8000)
        page.wait_for_timeout(3000)
        _settle(page)
        scope = _form_scope(page)
        if not _wd_visible(scope, 'email'):
            return ''
        return f'sign in on {host} in the APEX window: the password APEX kept for it was refused'
    if _wd_visible(scope, 'createAccountLink'):
        _wd(scope, 'createAccountLink').click(timeout=8000)
        page.wait_for_timeout(1500)
        scope = _form_scope(page)
    if not _wd_visible(scope, 'verifyPassword'):
        return f'sign in on {host} in the APEX window (an account exists there already)'
    password = new_password()
    _wd(scope, 'email').fill(email)
    _wd(scope, 'password').fill(password)
    _wd(scope, 'verifyPassword').fill(password)
    if _wd_visible(scope, 'createAccountCheckbox'):
        try:
            _wd(scope, 'createAccountCheckbox').check(force=True, timeout=4000)
        except Exception:
            pass
    _wd(scope, 'createAccountSubmitButton').click(timeout=8000)
    page.wait_for_timeout(3000)
    _settle(page)
    scope = _form_scope(page)
    body = ''
    try:
        body = scope.inner_text('body', timeout=3000)
    except Exception:
        pass
    if re.search(r'already (?:exists|registered|have an account)|account (?:exists|already)', body, re.I):
        return f'sign in on {host} in the APEX window (an account with your email exists there already)'
    if on_login:
        on_login(host, email, password)                  # kept for next time, whatever happens next
    if re.search(r'verif(?:y|ication) (?:code|email)|check your (?:email|inbox)|enter the code', body, re.I) and _wd_visible(scope, 'email') is False:
        return f'{host} emailed you a verification code: enter it in the APEX window, then press Apply again'
    if _wd_visible(scope, 'verifyPassword'):
        errs = _errors(scope)
        return f'create your account on {host} in the APEX window' + (': ' + '; '.join(errs)[:160] if errs else '')
    return ''


def workday_flow(page, url, pdf_path, letter, contact, answers, ask, do_submit, shot_path, logins, on_login, log):
    """Apply on a Workday career site end to end."""
    page.goto(url, wait_until='domcontentloaded', timeout=60000)
    _settle(page)
    page.wait_for_timeout(1500)
    scope = _form_scope(page)
    if _wd_visible(scope, 'adventureButton'):
        _wd(scope, 'adventureButton').click(timeout=8000)
        page.wait_for_timeout(2000)
        scope = _form_scope(page)
        choice = 'autofillWithResume' if pdf_path and _wd_visible(scope, 'autofillWithResume') else 'applyManually'
        if _wd_visible(scope, choice):
            _wd(scope, choice).click(timeout=8000)
            page.wait_for_timeout(2500)
            _settle(page)
    wall = workday_account(page, contact, logins, on_login)
    if wall:
        return _left_for_person(page, {'filled': log, 'missing': [wall], 'status': 'needs_you', 'detail': wall})
    page.wait_for_timeout(1500)
    status, detail, missing = walk_form(page, pdf_path, letter, contact, answers, ask, do_submit, shot_path, log,
                                        pages=12, next_button=_wd_next_button)
    return _left_for_person(page, {'filled': log, 'missing': missing, 'status': status, 'detail': detail})


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


def run(fn, timeout=300):
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


def apply_job(url, pdf_path, letter, contact, answers=None, ask=None, do_submit=False, shot_path='', pdf_maker=None,
              logins=None, on_login=None, website='', title=''):
    """Open the application in the APEX browser window, fill it, answer it and (do_submit) submit it.
    pdf_maker(ctx) -> path makes the resume PDF on the browser thread when pdf_path is ''.
    logins: {host: {email, password}} APEX kept; on_login(host, email, password) saves a new one.
    Returns (result dict from fill_form, error or '')."""
    def fn(ctx):
        path = pdf_path or (pdf_maker(ctx) if pdf_maker else '')
        page = ctx.new_page()
        page.bring_to_front()
        r = fill_form(page, url, path, letter, contact, answers, ask, do_submit, shot_path, logins, on_login, website, title)
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
