"""Offline stand-in for api.openai.com, used via APEX_OPENAI_BASE.

Answers /v1/chat/completions with canned content chosen by the system prompt,
so the browser suite is deterministic and never spends real credits.

Markers in the resume text steer the response:
  FAILPARSE  -> HTTP 400 (exercise the error path; 400s are not retried)
  LONGFORM   -> a resume long enough to need several PDF pages
  COVERLIE   -> the cover letter claims a number the resume does not have
  COVERALLBAD -> every sentence of the first cover letter draft claims such a number
                (the redraft is clean, unless ALWAYSBAD is also present)
  STUBBORN   -> the repair step returns the text unchanged (the check then trims the
                flagged sentences, or withholds the text when too little would be left)
  SLOWSTUB   -> every answer takes 1.5 s (to test cancelling a run)
The fact check flags any item containing "xxclaim"; the repair step drops each
sentence that contains a token quoted in the problems.
"""
import json
import re
import time
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# Built from the TESTS.md fixture resume, plus deliberately hostile shapes:
# a title/company line wider than the page, a bullet several lines long, and
# en/em dashes, which jsPDF's built-in Helvetica must encode correctly.
MARCUS = {
    "name": "Marcus Delgado",
    "title": "Data Analyst",
    "authorization": "",
    "email": "marcus.delgado@email.com",
    "phone": "(713) 555-0142",
    "location": "Houston, TX",
    "linkedin": "linkedin.com/in/marcusdelgado",
    "website": "",
    "summary": "Experienced professional looking for a new opportunity in data analysis. "
               "Hard worker and team player with good communication skills.",
    "experience": [
        {
            "title": "Senior Data Analyst and Business Intelligence Reporting Lead",
            "company": "Brightline Logistics Regional Operations and Fulfillment Division",
            "location": "Houston, TX",
            "start": "March 2021",
            "end": "Present",
            "bullets": [
                "Responsible for making reports for the management team",
                "Worked with SQL to get data from databases",
                "Built and maintained a self-service reporting layer over the warehouse management "
                "system that consolidated shipment, labor and dock-door utilization data from four "
                "regional facilities into a single nightly refresh, replacing eleven hand-maintained "
                "spreadsheets and cutting the weekly operations review preparation from two days to "
                "under three hours ENDOFLONGBULLET",
                "Was part of a team that did dashboards",
            ],
        },
        {
            "title": "Junior Analyst",
            "company": "Corva Retail Group",
            "location": "Houston, TX",
            "start": "June 2019",
            "end": "February 2021",
            "bullets": [
                "Assisted with data entry and cleaning",
                "Made spreadsheets for the sales team",
                "Participated in meetings about metrics",
            ],
        },
    ],
    "education": [
        {"degree": "B.S. Business Administration", "school": "University of Houston",
         "location": "Houston, TX", "year": "2019", "gpa": ""}
    ],
    "skills": {
        "technical": ["SQL", "Excel"],
        "tools": ["PowerPoint"],
        "soft": ["Communication", "Teamwork", "Time Management"],
    },
    "certifications": [],
    "projects": [],
    "languages": [],
    "awards": [],
    "additional": [],
}


def longform():
    s = json.loads(json.dumps(MARCUS))
    for i in range(1, 9):
        s["experience"].append({
            "title": f"Analyst Role {i}", "company": f"Company Number {i}", "location": "Houston, TX",
            "start": f"Jan 20{10 + i:02d}", "end": f"Dec 20{10 + i:02d}",
            "bullets": [f"Role {i} achievement {k}: delivered a measurable improvement to a reporting "
                        f"process used by the operations and finance teams" for k in range(1, 6)],
        })
    s["experience"][-1]["bullets"].append("FINALBULLETMARKER")
    return s


def struct_text(s):
    """The resume text a struct was parsed from. /parse-resume checks every
    parsed string against the submitted text, so tests that export the stub's
    struct must paste this text."""
    lines = [s['name'], s['title'], ' | '.join(x for x in (s['email'], s['phone'], s['location'], s['linkedin']) if x),
             '', 'SUMMARY', s['summary'], '', 'EXPERIENCE']
    for e in s['experience']:
        lines += [e['title'], f"{e['company']} - {e['location']}", f"{e['start']} - {e['end']}"]
        lines += ['- ' + b for b in e['bullets']] + ['']
    lines += ['EDUCATION'] + [f"{d['degree']}, {d['school']}, {d['location']}, {d['year']}" for d in s['education']]
    lines += ['', 'SKILLS', ', '.join(s['skills']['technical'] + s['skills']['tools']), ', '.join(s['skills']['soft'])]
    return '\n'.join(lines) + '\n'


COVER_LETTER = (
    "Your team needs reporting that leaders actually use.\n\n"
    "As an analyst I work with SQL every day.\n\n"
    "I would welcome a conversation about the role."
)
COVER_LETTER_ALL_LIES = ("I cut reporting costs by 40% at Brightline. I grew dashboard use by 40% in a year.\n\n"
                         "I saved the team 40% of its SQL time.")

BULLETS = {'ranked_bullets': [
    {'text': 'Responsible for making reports for the management team', 'score': 30, 'rank': 3,
     'rewrite': 'Built recurring reports for the management team'},
    {'text': 'Worked with SQL to get data from databases', 'score': 35, 'rank': 2,
     'rewrite': 'Cut query time by 40% with SQL across databases'},
    {'text': 'Was part of a team that did dashboards', 'score': 20, 'rank': 4,
     'rewrite': 'Built dashboards with the team. Dashboards won praise xxclaim.'},
    {'text': 'Assisted with data entry and cleaning', 'score': 80, 'rank': 1, 'rewrite': None}],
    'average_score': 41, 'overall_verdict': 'weak verbs'}

BRIDGE = {'transition_score': 70, 'transition_verdict': 'solid base',
          'skill_translations': [{'old_language': 'spreadsheets', 'new_language': 'financial models'}],
          'experience_reframes': [
              {'original_bullet': 'Worked with SQL to get data from databases',
               'reframed_bullet': 'Queried SQL databases to supply data for decisions'},
              {'original_bullet': 'Made spreadsheets for the sales team',
               'reframed_bullet': 'Built sales pipeline models for 30 reps'}],
          'narrative': 'Analyst who works with SQL and reporting, moving into finance.',
          'interview_bridge_answers': [{'question': 'Why change?', 'answer': 'I like working with numbers in SQL.'}]}

LINKEDIN = {'headline': 'Data Analyst | SQL · Excel · Reporting',
            'about': 'Data analyst who builds SQL reporting for management teams. Led a team of 12 analysts.',
            'skills': ['SQL', 'Excel', 'Tableau', 'Python'],
            'experience_bullets': [{'role': 'Senior Data Analyst',
                                    'bullets': ['Built recurring reports for the management team']}],
            'featured_tips': ['Pin a dashboard'], 'connection_strategy': ['Join analytics groups']}

OUTREACH = {'linkedin_dm': {'message': 'Hi, I build SQL reporting for operations teams and would value a chat.',
                            'followup': 'Following up on my note.'},
            'cold_email': {'subject': 'SQL reporting', 'body': 'I saved Brightline $2M last year.',
                           'followup': 'Checking in.'},
            'referral_request': 'Would you introduce me to the analytics lead?',
            'thank_you_note': 'Thank you for your time today.',
            'negotiation_script': 'Thank you for the offer.', 'tips': ['Be brief']}

INTERVIEW = {
    'behavioral': [
        {'q': 'Tell me about a report you built.', 'tip': 'Lead with the result',
         'a': 'At Brightline Logistics I built reports for the management team using SQL.'},
        {'q': 'Tell me about leading a team.', 'tip': 'Be honest',
         'a': 'I led a team of 12 analysts at a large company.'}],
    'technical': [{'q': 'How do you write a join?', 'a': 'I use SQL joins to combine tables.', 'tip': 'Explain keys'}],
    'situational': [],
    'questions_to_ask': ['What does success look like?'], 'salary_negotiation': ['Wait for the offer'],
    'red_flags_to_address': ['No Tableau yet: say you are learning it']}

XRAY = {'killer_bullets': [
    {'quote': 'Responsible for making reports for the management team', 'problem': 'passive',
     'fix': 'Built reports for the management team', 'impact': 'high'},
    {'quote': 'Assisted with data entry and cleaning', 'problem': 'vague',
     'fix': 'Cleaned 50,000 records weekly', 'impact': 'medium'}],
    'first_impression_score': 50, 'formatting_score': 70, 'first_impression_note': 'generic'}


def _repair(user):
    """Drop each sentence that contains a token the fact check quoted."""
    items = json.loads(user.split('ITEMS:')[1].split('Return ONLY JSON')[0])
    out = []
    for it in items:
        if 'STUBBORN' in user:
            out.append({'id': it['id'], 'text': it['text']}); continue
        bad = {t for p in it.get('problems') or [] for t in re.findall(r'"([^"]+)"', p)}
        keep = [s for s in re.split(r'(?<=[.!?])\s+', it['text']) if not any(t in s for t in bad)]
        out.append({'id': it['id'], 'text': ' '.join(keep)})
    return json.dumps({'fixed': out})


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    calls = []

    def log_message(self, *a):
        pass

    def _send(self, code, payload, ctype='application/json'):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # A neutral page on a *different* origin, for cross-origin browser tests.
        self._send(200, b'<!doctype html><title>other origin</title><p>other origin', 'text/html')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        msgs = body.get('messages', [])
        claude = self.path.startswith('/v1/messages')        # Anthropic Messages API shape
        if claude:
            system = body.get('system') or ''
            if isinstance(system, list):
                system = ' '.join(b.get('text', '') for b in system if isinstance(b, dict))
        else:
            system = next((m['content'] for m in msgs if m.get('role') == 'system'), '')
        user = next((m['content'] for m in msgs if m.get('role') == 'user'), '')
        if isinstance(user, list):
            user = ' '.join(b.get('text', '') for b in user if isinstance(b, dict))
        _Handler.calls.append({'path': self.path, 'system': system[:80], 'model': body.get('model'),
                               'provider': 'anthropic' if claude else 'openai', 'body_keys': sorted(body)})
        if 'SLOWSTUB' in user:
            time.sleep(1.5)        # a slow model, so tests can close the stream mid-run
        if 'FAILPARSE' in user:
            err = {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'stubbed failure'}}                 if claude else {'error': {'message': 'stubbed failure'}}
            self._send(400, err); return   # 400: not retried
        content = self._answer(system, user)
        if claude:
            self._send(200, {'id': 'msg_stub', 'type': 'message', 'role': 'assistant', 'model': body.get('model'),
                             'content': [{'type': 'text', 'text': content}], 'stop_reason': 'end_turn',
                             'stop_sequence': None, 'usage': {'input_tokens': 100, 'output_tokens': 50}})
        else:
            self._send(200, {'choices': [{'message': {'role': 'assistant', 'content': content}}],
                             'usage': {'prompt_tokens': 100, 'completion_tokens': 50}})

    @staticmethod
    def _answer(system, user):
        if user.startswith('Improve my resume for a'):      # benchmark: plain chatbot baseline
            return '\n'.join([
                'MARCUS DELGADO', 'Houston, TX', '', 'SUMMARY',
                'Results-driven analyst who increased reporting efficiency by 35% using Tableau and Snowflake.',
                '', 'EXPERIENCE', 'Data Analyst - Brightline Logistics', '- Built dashboards for 40 managers',
                '', 'EDUCATION', 'B.S. Business Administration, University of Houston, 2019'])
        if 'resume parser' in system:
            content = json.dumps(longform() if 'LONGFORM' in user else MARCUS)
        elif 'cover letters' in system:
            redraft = 'A previous draft was rejected' in user
            content = (COVER_LETTER_ALL_LIES if 'COVERALLBAD' in user and (not redraft or 'ALWAYSBAD' in user) else
                       COVER_LETTER + ('\n\nI cut reporting costs by 40% at Brightline.' if 'COVERLIE' in user else ''))
        elif 'You correct text written for a job candidate' in system:   # fact check: repair
            content = _repair(user)
        elif 'You extract hiring requirements' in system:  # /tailor
            content = json.dumps({'company': 'Meridian Health', 'role_title': 'Senior Data Analyst',
                                  'requirements': ['SQL', 'Tableau', 'dashboards', 'reporting']})
        elif 'Brutally honest' in system:                  # /xray
            content = json.dumps(XRAY)
        elif 'resume analyst' in system:                   # /bullets
            content = json.dumps(BULLETS)
        elif 'career transition strategist' in system:     # /bridge
            content = json.dumps(BRIDGE)
        elif 'LinkedIn profile writer' in system:
            content = json.dumps(LINKEDIN)
        elif system.startswith('Expert career coach'):     # outreach
            content = json.dumps(OUTREACH)
        elif 'Requirements analyst' in system:          # market requirements (counted against postings)
            content = json.dumps({'candidates': [
                {'name': n, 'kind': k} for n, k in (
                    ('SQL', 'hard'), ('Excel', 'tool'), ('Python', 'hard'), ('Tableau', 'tool'), ('dashboards', 'hard'),
                    ('reporting', 'hard'), ('data analysis', 'hard'), ('stakeholder communication', 'soft'),
                    ('A/B testing', 'hard'), ('KPIs', 'domain'))],
                'emerging': [{'name': 'dbt'}], 'salary_skills': [{'name': 'Python', 'impact': 'high', 'note': 'x'}]})
        elif 'strict evidence auditor' in system:         # which market keywords the resume demonstrates
            kws = json.loads(user.split('KEYWORDS:')[1].split('RESUME:')[0].strip())
            no = {'python', 'tableau', 'a/b testing', 'kpis'}
            content = json.dumps({'supported': [k for k in kws if k.lower() not in no],
                                  'unsupported': [k for k in kws if k.lower() in no]})
        elif 'the way the real screen works' in system:   # engine: diagnose
            content = json.dumps({'blocks': [
                {'id': 'S', 'impact': 1, 'specificity': 1, 'scannability': 3, 'relevance': 2,
                 'issues': ['generic'], 'question': None},
                {'id': 'B1', 'impact': 1, 'specificity': 2, 'scannability': 3, 'relevance': 4,
                 'issues': ['"Responsible for" hides the action'],
                 'question': 'How many managers used these reports, and how often?'},
                {'id': 'B2', 'impact': 2, 'specificity': 2, 'scannability': 3, 'relevance': 5, 'issues': [], 'question': None}],
                'document': {'problems': [{'issue': 'The summary says "Hard worker and team player"', 'fix': 'Lead with SQL reporting'}],
                             'strengths': ['Hands-on SQL'], 'summary_verdict': 'generic', 'most_relevant': ['B2']}})
        elif 'best resume writer in the world' in system:  # engine: rewrite
            b1 = ('Built weekly reports used by 9 managers' if 'CANDIDATE ANSWER' in user
                  else 'Built recurring reports for the management team')
            content = json.dumps({'edits': [
                {'id': 'S', 'lines': ['Data analyst who works with SQL to build reports and dashboards for the management team.'],
                 'why': 'leads with the role', 'keywords': ['SQL']},
                {'id': 'B1', 'lines': [b1], 'why': 'strong verb, ENGINEMARKER', 'keywords': []},
                {'id': 'B2', 'lines': ['Queried SQL databases to extract reporting data'], 'why': 'specific', 'keywords': ['SQL']}],
                'order': [], 'section_order': []})
        elif 'strict fact checker for resumes' in system:  # engine: verify
            items = json.loads(user.split('ITEMS:')[1].split('Return ONLY JSON')[0])
            content = json.dumps({'results': [
                {'id': it['id'], 'ok': 'xxclaim' not in json.dumps(it),
                 'problems': ['"xxclaim" - not in the evidence'] if 'xxclaim' in json.dumps(it) else []}
                for it in items]})
        elif 'You reward evidence' in system:              # engine: judge
            a_before = 'Responsible for making reports' in user.split('=== A ===')[1].split('=== B ===')[0]
            content = json.dumps({'A': {'score': 48 if a_before else 74, 'weakest': 'x'},
                                  'B': {'score': 74 if a_before else 48, 'weakest': 'x'},
                                  'better': 'B' if a_before else 'A', 'why': 'clearer evidence'})
        elif 'job search strategist' in system:          # /followup
            content = json.dumps({
                'week_1_email': {'subject': 'Following up on the Senior Data Analyst role',
                                 'body': 'Hi team, I applied last week and remain very interested. followupmarker',
                                 'send_time': 'Tuesday 9am'},
                'week_2_email': {'subject': 'Quick check-in', 'body': 'Still very interested.', 'send_time': 'Thursday'},
                'linkedin_note': 'Hi, I applied for the analyst role and would love to connect.',
                'value_add': 'Share a one-page KPI dashboard mock-up.',
                'when_to_give_up': 'After three weeks with no reply.',
                'personalization_tips': ['Mention their clinical ops team'],
            })
        elif 'Interview prep for:' in user:             # /analyze Phase 8 interview prep
            content = json.dumps(INTERVIEW)
        elif 'Grade this interview answer' in user:      # /grade-answer
            content = json.dumps({'score': 70, 'grade': 'B', 'verdict': 'solid', 'strengths': ['clear'],
                                  'weaknesses': ['no result'], 'ideal_answer_structure': 'STAR',
                                  'better_version': 'I built weekly reports with SQL. It cut prep time by 50%.',
                                  'keywords_used': ['SQL'], 'keywords_missed': [], 'coaching_tip': 'add the result'})
        elif 'Career strategist' in system:              # velocity
            content = json.dumps({'velocity_score': 64, 'trajectory': 'ascending', 'next_level_title': 'Lead Data Analyst',
                                  'years_to_next_level': 2, 'market_position': 'at', 'market_position_note': 'typical',
                                  'acceleration_moves': ['own a KPI'], '10_year_projection': 'analytics lead',
                                  'peer_comparison': 'on par'})
        elif 'salary negotiation strategist' in system:  # /negotiate
            content = json.dumps({'target_salary': '$110,000', 'minimum_acceptable': '$95,000', 'opening_ask': '$120,000',
                                  'rationale': 'posted pay', 'market_evidence': ['median posted pay'],
                                  'your_leverage': ['Hands-on SQL reporting for the management team',
                                                    'Managed a $5M analytics budget'],
                                  'negotiation_script': {'opening_line': 'Thank you', 'counter_script': 'Could we reach',
                                                         'if_they_push_back': 'I understand', 'closing_line': 'Great'},
                                  'red_flags': [], 'equity_considerations': '', 'timing_advice': 'after the offer',
                                  'benefits_to_negotiate': ['PTO']})
        elif 'You are an ATS system' in system:          # /match
            content = json.dumps({'match_pct': 72, 'should_apply': True, 'apply_confidence': 'medium',
                                  'verdict': 'good fit', 'matching_keywords': ['SQL'], 'missing_critical': ['Tableau'],
                                  'missing_nice': [],
                                  'quick_fixes': [{'add_to_resume': 'SQL', 'where': 'skills', 'impact': 'high'},
                                                  {'add_to_resume': 'Tableau', 'where': 'skills', 'impact': 'high'}],
                                  'red_flags': [], 'green_flags': ['SQL'], 'estimated_competition': 'medium'})
        elif 'You classify recruiter and job-search emails' in system:   # /inbox/scan
            ids = [int(x) for x in re.findall(r'#(\d+): FROM=', user)]
            content = json.dumps({'classifications': [{'id': i, 'status': 'applied', 'company': 'Acme', 'role': 'Analyst',
                                                       'confidence': 80} for i in ids]})
        else:
            content = '{}'
        return content


class FakeOpenAI:
    def __init__(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        # Don't let server_close() wait on a browser's idle keep-alive socket.
        self.server.block_on_close = False
        self.server.daemon_threads = True
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
        self.calls = _Handler.calls
        self._t = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
