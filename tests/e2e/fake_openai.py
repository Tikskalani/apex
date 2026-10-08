"""Offline stand-in for api.openai.com, used via APEX_OPENAI_BASE.

Answers /v1/chat/completions with canned content chosen by the system prompt,
so the browser suite is deterministic and never spends real credits.

Markers in the resume text steer the response:
  FAILPARSE  -> HTTP 500 (exercise the error path)
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
        system = next((m['content'] for m in msgs if m.get('role') == 'system'), '')
        user = next((m['content'] for m in msgs if m.get('role') == 'user'), '')
        _Handler.calls.append({'path': self.path, 'system': system[:80]})
        if 'FAILPARSE' in user:
            self._send(500, {'error': {'message': 'stubbed failure'}}); return
        if 'resume parser' in system:
            content = json.dumps(longform() if 'LONGFORM' in user else MARCUS)
        elif 'cover letters' in system:
            content = COVER_LETTER
        elif 'merge resume edits' in system:
            content = ("MARCUS DELGADO\nHouston, TX\n\nEXPERIENCE\n" +
                       "- Built SQL reporting for the management team\n" * 8)
        else:
            content = '{}'
        self._send(200, {'choices': [{'message': {'role': 'assistant', 'content': content}}]})


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
