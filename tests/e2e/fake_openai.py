"""Offline stand-in for api.openai.com, used via APEX_OPENAI_BASE.

Answers /v1/chat/completions with canned content chosen by the system prompt,
so the browser suite is deterministic and never spends real credits.

Markers in the resume text steer the response:
  FAILPARSE  -> HTTP 400 (exercise the error path; 400s are not retried)
  LONGFORM   -> a resume long enough to need several PDF pages
"""
import json
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


COVER_LETTER = (
    "Meridian Health Systems is building clinical reporting that leaders actually use.\n\n"
    "At Brightline Logistics I worked with SQL to pull data and built reports for management.\n\n"
    "I would bring the same focus to your clinical operations group.\n\n"
    "I would welcome a conversation about the role."
)


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
            content = COVER_LETTER
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
            content = json.dumps({'results': [{'id': it['id'], 'ok': True, 'problems': []} for it in items]})
        elif 'You reward evidence' in system:              # engine: judge
            a_before = 'Responsible for making reports' in user.split('=== A ===')[1].split('=== B ===')[0]
            content = json.dumps({'A': {'score': 48 if a_before else 74, 'weakest': 'x'},
                                  'B': {'score': 74 if a_before else 48, 'weakest': 'x'},
                                  'better': 'B' if a_before else 'A', 'why': 'clearer evidence'})
        elif 'job search strategist' in system:          # /followup
            content = json.dumps({
                'week_1_email': {'subject': 'Following up on the Senior Data Analyst role',
                                 'body': 'Hi team, I applied last week and wanted to share FOLLOWUPMARKER.',
                                 'send_time': 'Tuesday 9am'},
                'week_2_email': {'subject': 'Quick check-in', 'body': 'Still very interested.', 'send_time': 'Thursday'},
                'linkedin_note': 'Hi, I applied for the analyst role and would love to connect.',
                'value_add': 'Share a one-page KPI dashboard mock-up.',
                'when_to_give_up': 'After three weeks with no reply.',
                'personalization_tips': ['Mention their clinical ops team'],
            })
        elif 'resume market analyst' in system:          # /drift
            content = json.dumps({'current_score': '71', 'drift': 999, 'new_keywords': ['dbt', 'Looker'],
                                  'faded_keywords': ['Access'], 'verdict': 'Postings now ask for dbt.',
                                  'urgency': 'bogus'})
        elif 'merge resume edits' in system:
            content = ("MARCUS DELGADO\nHouston, TX\n\nEXPERIENCE\n" +
                       "- Built SQL reporting for the management team\n" * 8)
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
