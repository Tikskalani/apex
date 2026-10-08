"""APEX Evidence Engine (v11): recruiter-grade resume optimisation that never lies.

Why this exists. The v10 loop rewrote the whole document, then kept the rewrite
only if a keyword-count score went up. Better writing barely moves that score,
markdown in the model's output made the scorer misread good rewrites as
regressions, and one flagged phrase discarded every good edit with it. On real
resumes it shipped the original unchanged.

How this works.
  1. parse()     Lines get stable ids. Only the summary and experience/project
                 bullets are editable; the document is reassembled from the
                 original lines, so formatting and protected sections
                 (education, licences, ...) cannot drift or disappear.
  2. diagnose()  Recruiter rubric per bullet + one targeted question where the
                 candidate's own number would unlock the biggest gain.
  3. rewrite()   Expert playbook, edits by id. Split/merge allowed within a role.
  4. verify      Per bullet: deterministic fact gate (every number and technical
                 term must already exist in the source or the candidate's
                 answers), then a model audit. Failures get one retry with the
                 reason, then revert on their own. Good edits are never lost
                 because a different bullet failed.
  5. judge()     Blind A/B review by a simulated hiring manager for the target
                 role: the quality score the old keyword metric couldn't give.

Every model call goes through `llm(system, user, max_tokens=..., json_mode=..., effort=...)`
so tests can drive the whole pipeline with a stub.
"""
import json
import re

# ── Section model ────────────────────────────────────────────────────────────
_MD = re.compile(r'^[\s#>*_`]+|[\s*_`:]+$')
EDITABLE_SECTIONS = re.compile(
    r'experience|employment|work history|career history|professional history|projects?|'
    r'selected work|leadership|consulting', re.I)
SUMMARY_SECTIONS = re.compile(r'^(?:professional\s+|career\s+|executive\s+)?(?:summary|profile|about(?:\s+me)?|objective)$', re.I)
KNOWN_HEADERS = re.compile(
    r'^(?:(?:professional|technical|clinical|core|key|relevant|selected|additional|work|career|'
    r'employment|security|state|active)\s+)*'
    r'(?:summary|profile|objective|about(?:\s+me)?|experience|employment(?:\s+history)?|work\s+history|'
    r'career\s+history|skills|competencies|expertise|projects?|education(?:\s*(?:&|and)\s*training)?|'
    r'certifications?|licen[cs]es?(?:\s*(?:&|and)\s*certifications?)?|credentials?|languages?|awards?|honou?rs|'
    r'publications?|patents?|volunteer(?:\s+experience)?|military(?:\s+service)?|affiliations?|memberships?|'
    r'training|clearances?|authori[sz]ation|interests|references|portfolio|selected\s+work|leadership)$', re.I)
BULLET = re.compile(r'^(\s*)([-•*▪◦–·]|\d{1,2}[.)])\s+(?=\S)')


def _clean_header(line):
    return _MD.sub('', line or '').strip()


def is_header(line):
    s = (line or '').strip()
    if not s or len(s) > 60:
        return False
    if BULLET.match(s) and not s.startswith(('**', '__')):
        return False
    h = _clean_header(s)
    if not h or len(h.split()) > 6 or h.endswith(('.', ',', ';')):
        return False
    if KNOWN_HEADERS.match(h):
        return True
    letters = re.sub(r'[^A-Za-z]', '', h)
    return len(letters) >= 3 and letters.isupper() and not re.search(r'\d{4}', h)


class Doc:
    """A resume as lines with roles. Only `blocks` (summary + bullets) are editable."""

    def __init__(self, text):
        self.text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
        self.lines = self.text.split('\n')
        self.section_of = []
        section = ''
        first = next((i for i, l in enumerate(self.lines) if l.strip()), -1)
        for k, ln in enumerate(self.lines):
            # The first line is the candidate's name (often ALL CAPS), not a section.
            if k == first and not KNOWN_HEADERS.match(_clean_header(ln)):
                self.section_of.append(('', ''))
                continue
            if is_header(ln):
                section = _clean_header(ln)
                self.section_of.append(('#header', section))
            else:
                self.section_of.append(('', section))
        self.blocks = []            # {'id','kind','start','end','text','section','group'}
        self._find_summary()
        self._find_bullets()
        self.by_id = {b['id']: b for b in self.blocks}

    def _find_summary(self):
        idx = [i for i, (role, sec) in enumerate(self.section_of)
               if role == '' and sec and SUMMARY_SECTIONS.match(sec) and self.lines[i].strip()]
        if not idx:
            return
        start, end = idx[0], idx[0] + 1
        while end < len(self.lines) and self.section_of[end][0] == '' and self.section_of[end][1] == self.section_of[start][1]:
            end += 1
        while end > start and not self.lines[end - 1].strip():
            end -= 1
        self.blocks.append({'id': 'S', 'kind': 'summary', 'start': start, 'end': end,
                            'text': ' '.join(l.strip() for l in self.lines[start:end] if l.strip()),
                            'section': self.section_of[start][1], 'group': 'summary'})

    def _find_bullets(self):
        n, group, after_bullet = 0, '', True
        has_markers = any(BULLET.match(l) for l in self.lines)
        for i, ln in enumerate(self.lines):
            role, sec = self.section_of[i]
            if role:
                group, after_bullet = '', True       # a new section starts a new group
                continue
            if not sec or not EDITABLE_SECTIONS.search(sec):
                continue
            s = ln.strip()
            if not s:
                continue
            m = BULLET.match(ln)
            # PDF-extracted text often has no bullet markers: long sentence-like
            # lines inside an experience section are bullets.
            sentence_like = (not has_markers and len(s.split()) >= 8
                             and not re.search(r'\b(19|20)\d{2}\b.*\b((19|20)\d{2}|present)\b', s, re.I))
            if m or sentence_like:
                n += 1
                body = ln[m.end():] if m else s
                self.blocks.append({'id': f'B{n}', 'kind': 'bullet', 'start': i, 'end': i + 1, 'text': body.strip(),
                                    'marker': (m.group(1) + m.group(2) + ' ') if m else '- ',
                                    'section': sec, 'group': group or sec})
                after_bullet = True
            else:
                # Role / project heading. Consecutive heading lines (title, then
                # dates) belong together; the first one after a bullet starts a new role.
                group = s[:200] if after_bullet else (group + ' | ' + s)[:400]
                after_bullet = False

    def group_text(self, block_id):
        """All text of the role/project a block belongs to (its heading + sibling bullets)."""
        b = self.by_id[block_id]
        sib = [x['text'] for x in self.blocks if x['group'] == b['group']]
        return b['group'] + '\n' + '\n'.join(sib)

    def numbered(self):
        """The resume as the model sees it: editable blocks tagged with their id."""
        tag = {}
        for b in self.blocks:
            tag[b['start']] = b
        out, i = [], 0
        while i < len(self.lines):
            b = tag.get(i)
            if b:
                out.append(f'[{b["id"]}] {b["text"]}')
                i = b['end']
            else:
                out.append(self.lines[i])
                i += 1
        return '\n'.join(out)

    def sections(self):
        """[(name, first_line, end_line)] for each headed section, in document order."""
        heads = [i for i, (role, _) in enumerate(self.section_of) if role == '#header']
        return [(self.section_of[h][1], h, heads[k + 1] if k + 1 < len(heads) else len(self.lines))
                for k, h in enumerate(heads)]

    def valid_order(self, seq):
        """A bullet order is usable only as a full permutation of one role's bullets."""
        seq = [i for i in seq or [] if i in self.by_id and self.by_id[i]['kind'] == 'bullet']
        if len(seq) < 2 or len({self.by_id[i]['group'] for i in seq}) != 1:
            return None
        slots = [b['id'] for b in self.blocks if b['kind'] == 'bullet' and b['group'] == self.by_id[seq[0]]['group']]
        return seq if sorted(seq) == sorted(slots) and seq != slots else None

    def valid_section_order(self, names):
        have = [n for n, _, _ in self.sections()]
        names = [n for n in (names or []) if isinstance(n, str)]
        norm = lambda n: _clean_header(n).lower()
        if sorted(map(norm, names)) != sorted(map(norm, have)) or list(map(norm, names)) == list(map(norm, have)):
            return None
        return [next(h for h in have if norm(h) == norm(n)) for n in names]

    def render(self, edits, order=(), section_order=None):
        """edits: {block_id: [new line text, ...]}; order: [[ids of one role in new order], ...];
        section_order: [section names]. Unchanged lines come out byte-identical."""
        slot_src = {}
        for seq in order or ():
            slots = [b['id'] for b in self.blocks if b['kind'] == 'bullet' and b['group'] == self.by_id[seq[0]]['group']]
            slot_src.update(zip(slots, seq))
        tag = {b['start']: b for b in self.blocks}
        chunks, i = [], 0                       # (original line index, [output lines])
        while i < len(self.lines):
            b = tag.get(i)
            if not b:
                chunks.append((i, [self.lines[i]])); i += 1; continue
            src = slot_src.get(b['id'], b['id'])
            new = edits.get(src)
            if new is None and src == b['id']:
                lines = self.lines[b['start']:b['end']]
            elif b['kind'] == 'summary':
                lines = [' '.join(t.strip() for t in new if t and t.strip())]
            else:
                body = new if new is not None else [self.by_id[src]['text']]
                lines = [b['marker'] + t.strip() for t in body if t and t.strip()]
            chunks.append((i, lines)); i = b['end']
        if section_order:
            secs = {n: (a, z) for n, a, z in self.sections()}
            first = min(a for a, _ in secs.values())
            pre = [c for c in chunks if c[0] < first]
            body = []
            for n in section_order:
                a, z = secs[n]
                part = [c for c in chunks if a <= c[0] < z]
                if body and body[-1][1] and body[-1][1][-1].strip() and part:
                    body.append((-1, ['']))      # keep a blank line between moved sections
                body += part
            chunks = pre + body
        return '\n'.join(l for _, ls in chunks for l in ls)


# ── Deterministic fact gate ──────────────────────────────────────────────────
_NUM_TOKEN = re.compile(r'(?<![A-Za-z])\$?\d[\d,]*(?:\.\d+)?')
_WORD_NUMS = {'two': '2', 'three': '3', 'four': '4', 'five': '5', 'six': '6', 'seven': '7', 'eight': '8',
              'nine': '9', 'ten': '10', 'eleven': '11', 'twelve': '12', 'twenty': '20', 'hundred': '100',
              'dozen': '12', 'half': '50'}
# Technical-looking tokens: CamelCase, digits inside, symbols (C++, .NET, Node.js), or ALLCAPS acronyms.
_TERM = re.compile(r'(?<![\w.])(?:[A-Za-z][A-Za-z0-9]*(?:[+#]{1,2}|(?:[./-][A-Za-z0-9]+)+)|'
                   r'[A-Z]{2,}[A-Za-z0-9]*|[a-z]+[A-Z][A-Za-z0-9]*|[A-Z][a-z]+[A-Z][A-Za-z0-9]*|'
                   r'[A-Za-z]+\d[A-Za-z0-9]*)(?![\w])')
# A capitalised word that is not opening a sentence is usually a name: a tool,
# employer, product, place. A rewrite must not introduce new ones.
_PROPER = re.compile(r'(?<=[a-z0-9,)]\s)([A-Z][a-z]{2,})\b')
_CALENDAR = {'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
             'November', 'December', 'Jan', 'Feb', 'Mar', 'Apr', 'Jun', 'Jul', 'Aug', 'Sep', 'Sept', 'Oct', 'Nov',
             'Dec', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday', 'Present'}
_TERM_OK = {'AI', 'US', 'USA', 'UK', 'EU', 'CEO', 'CTO', 'CFO', 'COO', 'VP', 'QA', 'UI', 'UX', 'API', 'APIs',
            'KPI', 'KPIs', 'ROI', 'B2B', 'B2C', 'SaaS', 'IT', 'HR', 'PM', 'R&D', 'YoY', 'MoM', 'P&L', 'SLA',
            'SLAs', 'SOP', 'SOPs', 'E2E', 'end-to-end', 'real-time', 'on-call', 'cross-functional',
            'decision-making', 'self-serve', 'follow-up', 'multi-step', 'high-volume', 'low-latency',
            'full-stack', 'well-tested', 'production-ready', 'day-to-day', 'one-on-one', 'third-party',
            'in-house', 'long-term', 'short-term', 'hands-on', 'state-of-the-art', 'best-in-class'}


def _numbers(text):
    out = set()
    for m in _NUM_TOKEN.finditer(text or ''):
        v = m.group(0).lstrip('$').replace(',', '')
        out.add(v.rstrip('0').rstrip('.') if '.' in v else v)
    for w, v in _WORD_NUMS.items():
        if re.search(r'\b' + w + r'\b', text or '', re.I):
            out.add(v)
    return out


def _terms(text):
    return {t for t in _TERM.findall(text or '') if t not in _TERM_OK and not t.isdigit()}


# Same technology, different spelling. A rewrite may use the standard name of
# something the source names another way (Postgres -> PostgreSQL).
_ALIASES = [
    {'postgres', 'postgresql', 'psql'}, {'javascript', 'js'}, {'typescript', 'ts'}, {'kubernetes', 'k8s'},
    {'node.js', 'nodejs', 'node'}, {'next.js', 'nextjs'}, {'react.js', 'reactjs', 'react'},
    {'github actions', 'gha'}, {'amazon web services', 'aws'}, {'google cloud', 'gcp'}, {'ci/cd', 'ci', 'cicd'},
    {'machine learning', 'ml'}, {'large language model', 'llm', 'llms'}, {'rest api', 'rest apis', 'rest'},
    {'speech recognition', 'asr', 'speech-to-text', 'stt'}, {'text-to-speech', 'tts'},
    {'sql server', 'mssql'}, {'scikit-learn', 'sklearn'}, {'.net', 'dotnet'},
]
_ALIAS_OF = {name: grp for grp in _ALIASES for name in grp}


def _stemish(w):
    w = w.lower()
    for suf in ('ing', 'ed', 'es', 's'):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[:-len(suf)]
    return w


def _term_in_evidence(term, ev_low):
    core = term.lower().strip('.-/')
    if not core:
        return True
    if any(v in ev_low for v in (core, core.replace('-', ' '), core.replace('-', ''))):
        return True
    if any(a in ev_low for a in _ALIAS_OF.get(core, ())):
        return True
    # An ordinary hyphenated compound ("post-deploy", "write-offs") is fine when
    # each part already appears in the evidence.
    if '-' in core and core.replace('-', '').isalpha() and core == term.lower():
        parts = [p for p in core.split('-') if p]
        return all(_stemish(p) in ev_low for p in parts)
    return False


def fact_gate(new_text, evidence, unsupported_keywords=(), source_text='', allowed_words=()):
    """Problems with `new_text` given the evidence it may draw on. [] = clean.
    evidence: everything the bullet is allowed to use (its role's text + answers).
    source_text: the bullet's own original text (for keyword checks).
    allowed_words: extra capitalised words that are fine (e.g. the target title)."""
    problems = []
    allowed = {w.lower() for w in allowed_words or ()}
    ev_nums = _numbers(evidence)
    for n in sorted(_numbers(new_text) - ev_nums):
        # "8 rows" may legitimately be written as "eight"; any digit sequence
        # inside a longer evidence number (2026 in "Sep 2026") also counts.
        if not any(n in e for e in ev_nums):
            problems.append(f'number "{n}" is not in the source')
    ev_low = (evidence or '').lower()
    for t in sorted(_terms(new_text)):
        if not _term_in_evidence(t, ev_low):
            problems.append(f'term "{t}" is not in the source')
    for line in (new_text or '').split('\n'):
        for w in _PROPER.findall(line):
            if w in _CALENDAR or w.lower() in allowed or w.lower() in ev_low:
                continue
            problems.append(f'name "{w}" is not in the source')
    low_new, low_src = (new_text or '').lower(), (source_text or evidence or '').lower()
    for k in unsupported_keywords or ():
        kl = (k or '').lower().strip()
        if kl and len(kl) > 1 and re.search(r'(?<![a-z0-9])' + re.escape(kl) + r'(?![a-z0-9])', low_new) \
                and kl not in ev_low:
            problems.append(f'adds "{k}", which the resume does not demonstrate')
    return problems


# ── Prompts ──────────────────────────────────────────────────────────────────
PLAYBOOK = """HOW A TOP RECRUITER-WRITER EDITS (apply all of it)
Bullets
- Outcome or scope first, then how. Shape: [strong verb] [what] [for whom / at what scale] [result], [by/using method].
- 14-32 words, one main achievement. The first 6 words decide whether it is read: front-load the result,
  the scale, or the skill the target role hires for.
- Strong resumes get SHORTER, not longer. Condense a dense bullet to its strongest claim and drop secondary
  detail (process minutiae, minor features, repeated points). Split only when a bullet holds two achievements
  that would each rank in that role's top 3. Never add more than one bullet to a role.
- Specific beats general: name the system, the users, the volume, the metric - but only ones in the source.
- Keep the proper nouns that carry signal for the target role (the model, platform, framework, product name,
  employer). Generic tooling can go if it already appears in Skills.
- Use the target employer's vocabulary: when a SUPPORTED keyword names what the bullet already shows, use that exact
  term instead of a synonym. Never insert a keyword the bullet does not demonstrate.
- Cut: "responsible for", "helped", "worked on", "various", "successfully", "in order to", "utilize", "leverage",
  first person, filler adverbs, and unverifiable adjectives ("robust", "cutting-edge", "seamless", "passionate").
- Past tense for completed achievements, including in the current role ("Built", "Fixed", "Raised"); present
  tense only for ongoing duties ("Lead", "Maintain"). Digits for numbers. No trailing periods.
- Condense, never delete: every distinct accomplishment, project, role or title claim, and technology a
  recruiter for the target role would care about must survive (shorter is fine, gone is not).
- If a bullet is already excellent, return it unchanged. Change for a reason, never for variety.
Order
- Within each role, the bullets most relevant to the TARGET ROLE come first.
- Sections may be reordered when the strongest evidence for the target role sits low on the page
  (e.g. PROJECTS above EXPERIENCE for a career changer). Contact block always stays first.
Summary
- 2-3 sentences, no "I". Sentence 1: target-role identity and level the resume supports. Sentence 2: the 2-3
  strongest proofs for this role, with their real numbers. Optional sentence 3: the edge (domain, rare combination).
- Must name the target title or its closest true equivalent, and 3-5 top SUPPORTED keywords, naturally.
Truth (non-negotiable)
- Every fact you write must already be in the SOURCE resume or the candidate's ANSWERS: no new tools, numbers,
  scope, team sizes, titles, employers, outcomes, or seniority. You may reword, reorder, split, merge within a role,
  use the standard industry name for something the source clearly demonstrates, and count items the source lists."""

DIAGNOSE_SYSTEM = ('You are a hiring manager and senior technical recruiter for the target role. You read resumes the '
                   'way the real screen works: 6 seconds to decide, then a careful read for evidence. You are specific '
                   'and blunt; you never give generic advice. Return ONLY valid JSON.')

REWRITE_SYSTEM = ('You are the best resume writer in the world for the target role. You make resumes that win interviews '
                  'and survive reference checks, because every word is true. Return ONLY valid JSON.')

VERIFY_SYSTEM = ('You are a strict fact checker for resumes. A rewrite may rephrase, condense, split, reorder and use '
                 'standard terminology, but it may not claim anything the evidence does not show. Return ONLY valid JSON.')

JUDGE_SYSTEM = ('You are the hiring manager for the target role, screening resumes. You reward evidence, relevance and '
                'clarity, and you penalise anything that reads inflated or vague. Return ONLY valid JSON.')


def _target_block(t):
    kw = ', '.join(f'{k["name"]} ({k["pct"]}%)' if k.get('pct') is not None else k['name']
                   for k in (t.get('keywords') or [])[:25]) or '(none)'
    lines = [f'TARGET ROLE: {t.get("title")} | level: {t.get("seniority") or "unspecified"} | sector: {t.get("sector") or "general"}',
             f'MARKET KEYWORDS (share of real postings that ask for it): {kw}',
             f'SUPPORTED (the resume already demonstrates these; prefer these exact terms): {", ".join(t.get("supported") or []) or "(none)"}',
             f'NOT DEMONSTRATED (never add these; they are gaps for the report): {", ".join(t.get("unsupported") or []) or "(none)"}']
    if t.get('job_desc'):
        lines.append('TARGET JOB POSTING (highest priority signal):\n' + t['job_desc'][:5000])
    return '\n'.join(lines)


def _jload(text):
    if not text:
        return {}
    text = re.sub(r'```(?:json)?', '', text).strip()
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r'\{[\s\S]*\}', text)
        if not m:
            return {}
        try:
            return json.loads(m.group())
        except ValueError:
            try:
                return json.loads(re.sub(r',\s*([}\]])', r'\1', m.group()))
            except ValueError:
                return {}


# ── Steps ────────────────────────────────────────────────────────────────────
def diagnose(llm, doc, target):
    ids = [b['id'] for b in doc.blocks]
    raw = llm(DIAGNOSE_SYSTEM, f'''{_target_block(target)}

RESUME (editable lines are tagged [S] summary and [B#] bullets):
{doc.numbered()}

Review it for the target role. For EVERY tagged id, score 1-5 on: impact (is a result or scale shown?),
specificity, scannability (one idea, front-loaded, 14-32 words), relevance (to the target role).
List concrete issues (quote words). If the candidate could supply ONE fact that would most strengthen it
(a number, scale, user count, outcome, before/after) that the bullet implies but does not state, write that
question, addressed to the candidate, answerable in a few words. Never ask for what is already stated.
No question if the bullet is already strong.

Then the document: the 3-6 most important problems a recruiter for this role would have, each specific to
THIS resume (quote it), and what to do. Which bullets are most relevant to the target role. Whether the
summary works for this role. Strengths to keep.

Return ONLY JSON:
{{"blocks": [{{"id": "B1", "impact": 1-5, "specificity": 1-5, "scannability": 1-5, "relevance": 1-5,
              "issues": ["..."], "question": "..." or null}}],
  "document": {{"problems": [{{"issue": "...", "fix": "..."}}], "summary_verdict": "...",
                "most_relevant": ["B3", "..."], "strengths": ["..."]}}}}
Ids present: {", ".join(ids)}''', max_tokens=5000, json_mode=True, effort='medium')
    d = _jload(raw)
    blocks = {b.get('id'): b for b in d.get('blocks', []) if isinstance(b, dict) and b.get('id') in doc.by_id}
    return {'blocks': blocks, 'document': d.get('document') if isinstance(d.get('document'), dict) else {}}


def rewrite(llm, doc, target, diag, answers=None, only=None, feedback=None):
    """Proposed edits {id: {'lines': [...], 'why': str, 'keywords': [...]}}."""
    answers = answers or {}
    ids = [b['id'] for b in doc.blocks if only is None or b['id'] in only]
    notes = []
    for i in ids:
        dx = diag['blocks'].get(i) or {}
        bits = []
        if dx.get('issues'):
            bits.append('issues: ' + '; '.join(str(x) for x in dx['issues'][:4]))
        if answers.get(i):
            bits.append(f'CANDIDATE ANSWER (new evidence, use it): {answers[i]}')
        if feedback and feedback.get(i):
            bits.append('PREVIOUS ATTEMPT REJECTED because: ' + '; '.join(feedback[i]) + ' - fix exactly this.')
        if bits:
            notes.append(f'[{i}] ' + ' | '.join(bits))
    docx = diag.get('document') or {}
    raw = llm(REWRITE_SYSTEM, f'''{_target_block(target)}

{PLAYBOOK}

RESUME (edit only the tagged ids; everything untagged stays exactly as is):
{doc.numbered()}

REVIEWER NOTES PER ID:
{chr(10).join(notes) or '(none)'}

DOCUMENT-LEVEL PROBLEMS TO FIX: {json.dumps(docx.get('problems') or [], ensure_ascii=False)[:2500]}
MOST RELEVANT TO THE TARGET: {", ".join(docx.get('most_relevant') or []) or 'use your judgement'}

Rewrite these ids: {", ".join(ids)}.
For each id return the new text as a list of lines (one line for the summary; a bullet may become 1-2 bullets,
no marker characters). Within each role, return the order you want its bullets in ("order"), most relevant to the
target first, using the ORIGINAL ids (all of that role's ids). If the section order hurts this candidate for the
target role, return the section headers in the order you want ("section_order"), else []. Return the unchanged
text when no edit improves it.

SECTION HEADERS NOW: {[n for n, _, _ in doc.sections()]}

Return ONLY JSON:
{{"edits": [{{"id": "B1", "lines": ["..."], "why": "short reason a recruiter would agree with", "keywords": ["terms used"]}}],
  "order": [["B3", "B1", "B2"]], "section_order": []}}''', max_tokens=7000, json_mode=True, effort='medium')
    d = _jload(raw)
    out = {}
    for e in d.get('edits', []) or []:
        if not isinstance(e, dict) or e.get('id') not in ids:
            continue
        lines = e.get('lines')
        if isinstance(lines, str):
            lines = [lines]
        lines = [re.sub(r'^\s*(?:[-•*▪◦–·]|\d{1,2}[.)])\s+', '', str(x)).strip() for x in (lines or []) if str(x).strip()]
        if lines:
            out[e['id']] = {'lines': lines[:3], 'why': str(e.get('why') or '')[:300],
                            'keywords': [str(k) for k in (e.get('keywords') or [])][:8]}
    order = [o for o in (d.get('order') or []) if isinstance(o, list)]
    if isinstance(d.get('section_order'), list) and d['section_order']:
        order.append({'sections': d['section_order']})
    return out, order


AUDIT_BATCH = 8


def audit(llm, doc, items, answers):
    """Model fact-check of changed blocks. items: {id: [lines]} -> {id: [problems]}.
    Checks additions (claims the evidence does not support) and omissions (a distinct
    accomplishment, role, project or technology silently deleted). Each role's text
    is sent once; items go in batches so nothing is ever truncated."""
    res = {}
    ids = list(items)
    for k in range(0, len(ids), AUDIT_BATCH):
        res.update(_audit_batch(llm, doc, {i: items[i] for i in ids[k:k + AUDIT_BATCH]}, answers))
    return res


def _audit_batch(llm, doc, items, answers):
    groups, payload = {}, []
    for i, lines in items.items():
        g = 'WHOLE RESUME' if doc.by_id[i]['kind'] == 'summary' else doc.by_id[i]['group']
        if g not in groups:
            groups[g] = doc.text if g == 'WHOLE RESUME' else doc.group_text(i)
        item = {'id': i, 'evidence_group': g, 'source': doc.by_id[i]['text'], 'rewrite': lines}
        if answers.get(i):
            item['candidate_answer'] = answers[i]
        payload.append(item)
    raw = llm(VERIFY_SYSTEM, f"""For each item, compare the REWRITE with its SOURCE line and its EVIDENCE GROUP (the
original role or project text; for the summary, the whole resume) plus any candidate answer.

Flag (ok=false) only real problems:
1. ADDED: a tool, number, scope, team size, user count, outcome, title or seniority the evidence does not show;
   a changed meaning; a causal claim the evidence does not make ("which increased revenue").
2. DROPPED: the rewrite deletes a distinct accomplishment, project, role/title claim, or technology that a
   recruiter for the target role would care about, and it does not appear elsewhere in its evidence group.
   Dropping minor detail, repetition, or process minutiae is fine and expected.
Rephrasing, condensing, splitting, standard terminology for something clearly demonstrated, and counting
listed items are fine.

EVIDENCE GROUPS:
{json.dumps(groups, ensure_ascii=False)}

ITEMS:
{json.dumps(payload, ensure_ascii=False)}

Return ONLY JSON: {{"results": [{{"id": "B1", "ok": true|false, "problems": ["ADDED|DROPPED: quote - why"]}}]}}""",
              max_tokens=3000, json_mode=True, effort='medium')
    d = _jload(raw)
    res = {}
    results = [r for r in (d.get('results') or []) if isinstance(r, dict)]
    for r in results:
        if r.get('id') in items and r.get('ok') is False:
            res[r['id']] = [str(p) for p in (r.get('problems') or ['flagged by fact check'])][:3]
    seen = {r.get('id') for r in results}
    for i in items:                       # fail closed: an unchecked edit is not an approved edit
        if i not in seen:
            res.setdefault(i, ['not confirmed by the fact check'])
    return res


def _judge_once(llm, a, b, target):
    raw = llm(JUDGE_SYSTEM, f"""{_target_block(target)}

Two versions of the same candidate's resume, A and B. Score each 0-100 as the hiring manager for the target
role: first-6-second impression, relevance to the role, evidence of impact, clarity, credibility.
85+ means "interview immediately", 70 "probably", 55 "maybe", below 40 "no". Be calibrated, not generous.

=== A ===
{a[:14000]}

=== B ===
{b[:14000]}

Return ONLY JSON: {{"A": {{"score": 0-100, "strongest": "...", "weakest": "..."}},
                   "B": {{"score": 0-100, "strongest": "...", "weakest": "..."}},
                   "better": "A"|"B"|"tie", "why": "..."}}""", max_tokens=1200, json_mode=True, effort='low')
    d = _jload(raw)

    def sc(x):
        try:
            return max(0, min(100, round(float((d.get(x) or {}).get('score')))))
        except (TypeError, ValueError):
            return None
    return d, sc('A'), sc('B')


def judge(llm, before, after, target):
    """Hiring-manager review, run in both orders and averaged so position bias and
    run-to-run noise cancel. Returns {'before', 'after', 'verdict', 'after_weakest', 'better'}."""
    d1, a1, b1 = _judge_once(llm, before, after, target)     # A = before
    d2, a2, b2 = _judge_once(llm, after, before, target)     # A = after
    pairs_before = [x for x in (a1, b2) if x is not None]
    pairs_after = [x for x in (b1, a2) if x is not None]
    if not pairs_before or not pairs_after:
        return {'before': None, 'after': None, 'verdict': '', 'after_weakest': '', 'better': 'tie'}
    sb, sa = round(sum(pairs_before) / len(pairs_before)), round(sum(pairs_after) / len(pairs_after))
    return {'before': sb, 'after': sa,
            'verdict': str(d1.get('why') or d2.get('why') or '')[:400],
            'after_weakest': str((d2.get('A') or {}).get('weakest') or (d1.get('B') or {}).get('weakest') or '')[:300],
            'better': 'after' if sa > sb else 'before' if sb > sa else 'tie'}


def optimize(llm, resume, target, answers=None, log=lambda m: None, judge_it=True):
    """The whole pipeline. Returns a result dict the server sends to the page."""
    answers = {k: str(v).strip()[:500] for k, v in (answers or {}).items() if str(v or '').strip()}
    doc = Doc(resume)
    if not doc.blocks:
        log('  ⚠ Could not find a summary or experience bullets to work on; check the section headers.')
        return {'final': resume, 'changes': [], 'questions': [], 'problems': [], 'lines': doc.lines,
                'score': None, 'note': 'no editable content found'}
    log(f'  ✓ {sum(1 for b in doc.blocks if b["kind"] == "bullet")} bullets and '
        f'{"a" if "S" in doc.by_id else "no"} summary to work on')

    diag = diagnose(llm, doc, target)
    log(f'  ✓ Recruiter review: {len(diag["blocks"])} lines scored, '
        f'{len((diag["document"] or {}).get("problems") or [])} document-level problems')

    proposals, order = rewrite(llm, doc, target, diag, answers)
    unsupported = target.get('unsupported') or []
    accepted, rejected, feedback = {}, {}, {}

    def gate(i, lines):
        ev = doc.group_text(i) + '\n' + answers.get(i, '')
        if doc.by_id[i]['kind'] == 'summary':
            ev = doc.text + '\n' + '\n'.join(answers.values())   # the summary may draw on the whole resume
        allowed = re.findall(r'[A-Za-z]+', target.get('title') or '') + list(target.get('supported') or [])
        return fact_gate('\n'.join(lines), ev, unsupported, doc.by_id[i]['text'], allowed)

    def screen(props):
        changed = {}
        for i, p in props.items():
            if ' '.join(p['lines']).strip() == doc.by_id[i]['text'].strip():
                continue
            probs = gate(i, p['lines'])
            if probs:
                feedback[i] = probs
            else:
                changed[i] = p['lines']
        flagged = audit(llm, doc, changed, answers) if changed else {}
        for i, probs in flagged.items():
            feedback[i] = probs
        return {i: props[i] for i in changed if i not in flagged}

    accepted.update(screen(proposals))
    retry_ids = [i for i in feedback if i in proposals]
    if retry_ids:
        log(f'  ↻ {len(retry_ids)} edit(s) failed verification; retrying with the reasons')
        retry, _ = rewrite(llm, doc, target, diag, answers, only=set(retry_ids), feedback=feedback)
        fb_before = dict(feedback)
        for i in retry_ids:
            feedback.pop(i, None)
        ok = screen(retry)
        accepted.update(ok)
        for i in retry_ids:
            if i not in ok:
                rejected[i] = feedback.get(i) or fb_before.get(i) or ['failed verification']
    log(f'  ✓ {len(accepted)} edit(s) verified · {len(rejected)} kept original (could not verify)')

    # Wording edits are per id; ordering is separate, so every change below
    # compares a line with its own rewrite (never with a neighbour moved into its slot).
    edits = {i: p['lines'] for i, p in accepted.items()}
    orders = [o for o in (doc.valid_order(x) for x in order if isinstance(x, list)) if o]
    sec = next((doc.valid_section_order(x['sections']) for x in order if isinstance(x, dict)), None)
    final = doc.render(edits, orders, sec)

    changes = []
    for b in doc.blocks:
        if b['id'] in edits and ' '.join(edits[b['id']]).strip() != b['text'].strip():
            p = accepted[b['id']]
            changes.append({'id': b['id'], 'kind': b['kind'], 'section': b['section'], 'group': b['group'],
                            'before': b['text'], 'after': edits[b['id']], 'why': p.get('why') or '',
                            'keywords': p.get('keywords') or []})
    questions = []
    for b in doc.blocks:
        q = (diag['blocks'].get(b['id']) or {}).get('question')
        if q and isinstance(q, str) and q.strip() and b['id'] not in answers:
            questions.append({'id': b['id'], 'question': q.strip()[:300], 'line': b['text'][:240]})
    scores = {}
    for b in doc.blocks:
        dx = diag['blocks'].get(b['id']) or {}
        vals = [dx.get(k) for k in ('impact', 'specificity', 'scannability', 'relevance')]
        vals = [v for v in vals if isinstance(v, (int, float))]
        if vals:
            scores[b['id']] = round(sum(vals) / len(vals), 1)

    result = {'final': final, 'lines': doc.lines, 'changes': changes, 'questions': questions[:8],
              'order': orders, 'section_order': sec,
              'rejected': [{'id': i, 'line': doc.by_id[i]['text'][:240], 'why': w} for i, w in rejected.items()],
              'problems': (diag['document'] or {}).get('problems') or [],
              'strengths': (diag['document'] or {}).get('strengths') or [],
              'summary_verdict': (diag['document'] or {}).get('summary_verdict') or '',
              'line_scores': scores, 'score': None}
    if judge_it:
        result['score'] = judge(llm, resume, final, target)
        j = result['score']
        log(f'  ✓ Hiring-manager score (blind A/B): {j.get("before")} → {j.get("after")}')
    return result
