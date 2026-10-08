"""APEX local storage: the job pipeline, its timeline, apply kits and score history.

Pure stdlib (sqlite3). One database file beside the server (`apex.db`, or
$APEX_DB). Every public function opens its own short-lived connection, so it is
safe to call from ThreadingHTTPServer's request threads.

Rules:
- Applications are mutable records; every status change also appends an event.
- Events and artifacts are append-only.
- Validation lives here, not in the HTTP layer: callers get StoreError with a
  message fit to show the user.
"""
import json
import os
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone

STATUSES = ('saved', 'applied', 'interview', 'offer', 'rejected', 'withdrawn')
ACTIVE = ('saved', 'applied', 'interview')          # still in play
SOURCES = ('manual', 'tailor', 'gmail', 'jobs', 'import')
ARTIFACT_KINDS = ('tailored_resume', 'cover_letter', 'followup', 'outreach', 'note')
FOLLOWUP_AFTER_DAYS = 7
MAX_TEXT = 200_000           # per artifact; a resume is ~5 KB

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id             TEXT PRIMARY KEY,
    company        TEXT NOT NULL CHECK (length(trim(company)) > 0),
    role           TEXT NOT NULL CHECK (length(trim(role)) > 0),
    url            TEXT NOT NULL DEFAULT '',
    location       TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL CHECK (status IN ('saved','applied','interview','offer','rejected','withdrawn')),
    applied_on     TEXT,                 -- YYYY-MM-DD, set when status first reaches 'applied' or beyond
    next_action_on TEXT,                 -- YYYY-MM-DD, when to follow up
    notes          TEXT NOT NULL DEFAULT '',
    source         TEXT NOT NULL DEFAULT 'manual',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS applications_dedupe
    ON applications (lower(trim(company)), lower(trim(role)), url);

CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    at             TEXT NOT NULL,
    kind           TEXT NOT NULL,
    detail         TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS events_app ON events (application_id, at);

CREATE TABLE IF NOT EXISTS artifacts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL,
    content        TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS artifacts_app ON artifacts (application_id, kind, created_at);

CREATE TABLE IF NOT EXISTS score_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_title    TEXT NOT NULL,
    sector       TEXT NOT NULL DEFAULT 'general',
    score_before INTEGER,
    score_after  INTEGER,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS score_title ON score_history (lower(job_title), created_at);
"""


class StoreError(ValueError):
    """Bad input. The message is safe and useful to show the user."""


def db_path():
    return os.environ.get('APEX_DB') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'apex.db')


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _today():
    return date.today().isoformat()


def _connect():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init():
    with _connect() as conn:
        conn.execute('PRAGMA journal_mode = WAL')
        conn.executescript(SCHEMA)


# ── validation ────────────────────────────────────────────────────────────────

def _text(v, field, limit=500, required=False):
    s = '' if v is None else str(v).strip()
    if required and not s:
        raise StoreError(f'{field} is required')
    if len(s) > limit:
        raise StoreError(f'{field} is too long ({len(s)} > {limit} characters)')
    return s


def _status(v):
    s = (v or 'applied').strip().lower()
    if s not in STATUSES:
        raise StoreError(f'status must be one of: {", ".join(STATUSES)}')
    return s


def _day(v, field):
    if v in (None, ''):
        return None
    try:
        return date.fromisoformat(str(v).strip()[:10]).isoformat()
    except ValueError:
        raise StoreError(f'{field} must be a date like 2026-10-08')


def _url(v):
    s = _text(v, 'url', 2000)
    if s and not s.lower().startswith(('http://', 'https://')):
        raise StoreError('url must start with http:// or https://')
    return s


def _row(r):
    d = dict(r)
    d['followup_due'] = _followup_due(d)
    return d


def _followup_due(a):
    if a['status'] not in ('applied', 'interview'):
        return False
    if a.get('next_action_on'):
        return a['next_action_on'] <= _today()
    if a.get('applied_on'):
        return a['applied_on'] <= (date.today() - timedelta(days=FOLLOWUP_AFTER_DAYS)).isoformat()
    return False


def _event(conn, app_id, kind, **detail):
    conn.execute('INSERT INTO events (application_id, at, kind, detail) VALUES (?,?,?,?)',
                 (app_id, _now(), kind, json.dumps(detail, ensure_ascii=False)))


# ── applications ──────────────────────────────────────────────────────────────

def create_application(data):
    """Create, or return the existing row if company+role+url already exists.
    Returns (application, created: bool)."""
    company = _text(data.get('company'), 'company', 200, required=True)
    role = _text(data.get('role'), 'role', 200, required=True)
    url = _url(data.get('url'))
    status = _status(data.get('status'))
    source = (data.get('source') or 'manual').strip().lower()
    if source not in SOURCES:
        raise StoreError(f'source must be one of: {", ".join(SOURCES)}')
    applied_on = _day(data.get('applied_on') or data.get('date'), 'applied_on')
    if not applied_on and status != 'saved':
        applied_on = _today()
    now = _now()
    rec = {
        'id': uuid.uuid4().hex, 'company': company, 'role': role, 'url': url,
        'location': _text(data.get('location'), 'location', 200), 'status': status,
        'applied_on': applied_on, 'next_action_on': _day(data.get('next_action_on'), 'next_action_on'),
        'notes': _text(data.get('notes'), 'notes', 20_000), 'source': source,
        'created_at': now, 'updated_at': now,
    }
    with _connect() as conn:
        existing = conn.execute(
            'SELECT * FROM applications WHERE lower(trim(company)) = lower(?) AND lower(trim(role)) = lower(?) AND url = ?',
            (company, role, url)).fetchone()
        if existing:
            return _row(existing), False
        try:
            conn.execute(
                'INSERT INTO applications (id, company, role, url, location, status, applied_on, next_action_on,'
                ' notes, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (rec['id'], rec['company'], rec['role'], rec['url'], rec['location'], rec['status'],
                 rec['applied_on'], rec['next_action_on'], rec['notes'], rec['source'],
                 rec['created_at'], rec['updated_at']))
        except sqlite3.IntegrityError:
            # Lost a race with an identical create on another request thread.
            existing = conn.execute(
                'SELECT * FROM applications WHERE lower(trim(company)) = lower(?) AND lower(trim(role)) = lower(?) AND url = ?',
                (company, role, url)).fetchone()
            if existing:
                return _row(existing), False
            raise
        _event(conn, rec['id'], 'created', status=status, source=source)
    return get_application(rec['id']), True


def get_application(app_id, with_history=False):
    with _connect() as conn:
        r = conn.execute('SELECT * FROM applications WHERE id = ?', (app_id,)).fetchone()
        if not r:
            raise StoreError('application not found')
        a = _row(r)
        if with_history:
            a['events'] = [dict(e, detail=json.loads(e['detail']))
                           for e in conn.execute('SELECT at, kind, detail FROM events WHERE application_id = ? ORDER BY id',
                                                 (app_id,))]
            a['artifacts'] = [dict(x) for x in conn.execute(
                'SELECT id, kind, content, created_at FROM artifacts WHERE application_id = ? ORDER BY id DESC',
                (app_id,))]
    return a


def list_applications():
    with _connect() as conn:
        rows = [_row(r) for r in conn.execute('SELECT * FROM applications ORDER BY updated_at DESC')]
        kits = {r['application_id']: r['n'] for r in conn.execute(
            'SELECT application_id, count(*) AS n FROM artifacts GROUP BY application_id')}
    for a in rows:
        a['artifact_count'] = kits.get(a['id'], 0)
    return rows


def update_application(app_id, changes):
    allowed = {'status', 'notes', 'next_action_on', 'url', 'location', 'company', 'role', 'applied_on'}
    unknown = set(changes) - allowed - {'id'}
    if unknown:
        raise StoreError(f'cannot update: {", ".join(sorted(unknown))}')
    current = get_application(app_id)
    upd = {}
    if 'status' in changes:
        upd['status'] = _status(changes['status'])
    if 'notes' in changes:
        upd['notes'] = _text(changes['notes'], 'notes', 20_000)
    if 'next_action_on' in changes:
        upd['next_action_on'] = _day(changes['next_action_on'], 'next_action_on')
    if 'applied_on' in changes:
        upd['applied_on'] = _day(changes['applied_on'], 'applied_on')
    if 'url' in changes:
        upd['url'] = _url(changes['url'])
    if 'location' in changes:
        upd['location'] = _text(changes['location'], 'location', 200)
    for f in ('company', 'role'):
        if f in changes:
            upd[f] = _text(changes[f], f, 200, required=True)
    if not upd:
        return current
    # Moving out of 'saved' is the moment of applying.
    if upd.get('status') and upd['status'] != 'saved' and not current['applied_on'] and 'applied_on' not in upd:
        upd['applied_on'] = _today()
    m = {**current, **upd, 'updated_at': _now()}
    with _connect() as conn:
        try:
            conn.execute(
                'UPDATE applications SET company = ?, role = ?, url = ?, location = ?, status = ?, applied_on = ?,'
                ' next_action_on = ?, notes = ?, updated_at = ? WHERE id = ?',
                (m['company'], m['role'], m['url'], m['location'], m['status'], m['applied_on'],
                 m['next_action_on'], m['notes'], m['updated_at'], app_id))
        except sqlite3.IntegrityError:
            raise StoreError('another application already has this company, role and link')
        if 'status' in upd and upd['status'] != current['status']:
            _event(conn, app_id, 'status', frm=current['status'], to=upd['status'])
        if 'notes' in upd and upd['notes'] != current['notes']:
            _event(conn, app_id, 'note')
    return get_application(app_id)


def delete_application(app_id):
    with _connect() as conn:
        n = conn.execute('DELETE FROM applications WHERE id = ?', (app_id,)).rowcount
    if not n:
        raise StoreError('application not found')


def import_applications(items, source='import'):
    """Bulk create with dedupe (localStorage migration, Gmail scan).
    Returns counts. Invalid rows are skipped and reported, never half-saved."""
    if not isinstance(items, list):
        raise StoreError('items must be a list')
    created, duplicates, skipped = 0, 0, []
    for i, it in enumerate(items[:1000]):
        try:
            _, was_new = create_application({**(it or {}), 'source': (it or {}).get('source') or source})
            created += was_new
            duplicates += not was_new
        except StoreError as e:
            skipped.append({'index': i, 'error': str(e)})
    return {'created': created, 'duplicates': duplicates, 'skipped': skipped}


def summary():
    apps = list_applications()
    by = {s: sum(1 for a in apps if a['status'] == s) for s in STATUSES}
    sent = sum(by[s] for s in ('applied', 'interview', 'offer', 'rejected'))
    progressed = by['interview'] + by['offer']
    return {
        'total': len(apps), 'by_status': by, 'sent': sent,
        'response_rate': round(progressed / sent * 100) if sent else None,
        'followups_due': sum(1 for a in apps if a['followup_due']),
    }


# ── artifacts (apply kit) ─────────────────────────────────────────────────────

def add_artifact(app_id, kind, content):
    if kind not in ARTIFACT_KINDS:
        raise StoreError(f'kind must be one of: {", ".join(ARTIFACT_KINDS)}')
    content = '' if content is None else str(content)
    if not content.strip():
        raise StoreError('content is empty')
    if len(content) > MAX_TEXT:
        raise StoreError('content is too large')
    get_application(app_id)   # raises if missing
    with _connect() as conn:
        cur = conn.execute('INSERT INTO artifacts (application_id, kind, content, created_at) VALUES (?,?,?,?)',
                           (app_id, kind, content, _now()))
        _event(conn, app_id, 'artifact', artifact=kind)
        conn.execute('UPDATE applications SET updated_at = ? WHERE id = ?', (_now(), app_id))
    return cur.lastrowid


def record_followup_sent(app_id, days=FOLLOWUP_AFTER_DAYS):
    """Mark that a follow-up went out; schedule the next one."""
    get_application(app_id)
    nxt = (date.today() + timedelta(days=days)).isoformat()
    with _connect() as conn:
        conn.execute('UPDATE applications SET next_action_on = ?, updated_at = ? WHERE id = ?', (nxt, _now(), app_id))
        _event(conn, app_id, 'followup_sent', next_action_on=nxt)
    return get_application(app_id)


# ── score history (drift baseline) ────────────────────────────────────────────

def _score(v):
    try:
        n = round(float(v))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, n))


def record_score(job_title, sector, before, after):
    title = _text(job_title, 'job_title', 200, required=True)
    b, a = _score(before), _score(after)
    if a is None:
        raise StoreError('score_after must be a number')
    with _connect() as conn:
        conn.execute('INSERT INTO score_history (job_title, sector, score_before, score_after, created_at) VALUES (?,?,?,?,?)',
                     (title, (sector or 'general').strip(), b, a, _now()))


def latest_score(job_title):
    with _connect() as conn:
        r = conn.execute('SELECT * FROM score_history WHERE lower(job_title) = lower(?) ORDER BY id DESC LIMIT 1',
                         ((job_title or '').strip(),)).fetchone()
    return dict(r) if r else None
