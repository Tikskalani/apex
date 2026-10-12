"""APEX local storage: the job pipeline, its timeline, apply kits and score history.

Pure stdlib (sqlite3). One database file beside the server (`apex.db`, or
$APEX_DB). Every public function opens its own short-lived connection (and
closes it), so it is safe to call from ThreadingHTTPServer's request threads.

Rules:
- Every row belongs to an `owner`. Running locally there is one owner, ''. In
  the hosted demo each signed-in visitor gets a random owner id, so visitors
  never see each other's data. Every query filters by owner; a row owned by
  someone else is indistinguishable from a missing row ("not found").
- Applications are mutable records; every status change also appends an event.
- Events and artifacts are append-only.
- Validation lives here, not in the HTTP layer: callers get StoreError with a
  message fit to show the user.
"""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

STATUSES = ('saved', 'applied', 'interview', 'offer', 'rejected', 'withdrawn')
ACTIVE = ('saved', 'applied', 'interview')          # still in play
SOURCES = ('manual', 'tailor', 'gmail', 'jobs', 'import')
ARTIFACT_KINDS = ('tailored_resume', 'cover_letter', 'followup', 'outreach', 'note')
FOLLOWUP_AFTER_DAYS = 7
MAX_TEXT = 200_000           # per artifact; a resume is ~5 KB
MAX_APPS_PER_OWNER = 2000    # a hosted visitor can't fill the disk
MAX_ARTIFACTS_PER_APP = 50
MAX_OWNER_BYTES = 20_000_000 # notes + artifacts per owner
MAX_SCORES_PER_OWNER = 200

TABLES = """
CREATE TABLE IF NOT EXISTS applications (
    id             TEXT PRIMARY KEY,
    owner          TEXT NOT NULL DEFAULT '',
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
CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    at             TEXT NOT NULL,
    kind           TEXT NOT NULL,
    detail         TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS artifacts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL,
    content        TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS score_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    owner        TEXT NOT NULL DEFAULT '',
    job_title    TEXT NOT NULL,
    sector       TEXT NOT NULL DEFAULT 'general',
    score_before INTEGER,
    score_after  INTEGER,
    keywords     TEXT NOT NULL DEFAULT '[]',   -- the run's requirements [{name, pct}]: the drift baseline
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spend (
    day   TEXT PRIMARY KEY,              -- UTC YYYY-MM-DD
    units INTEGER NOT NULL DEFAULT 0     -- AI cost units used that day (hosted demo)
);
"""

INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS applications_dedupe_owner
    ON applications (owner, lower(trim(company)), lower(trim(role)), url);
CREATE INDEX IF NOT EXISTS applications_owner ON applications (owner, updated_at);
CREATE INDEX IF NOT EXISTS events_app ON events (application_id, at);
CREATE INDEX IF NOT EXISTS artifacts_app ON artifacts (application_id, kind, created_at);
CREATE INDEX IF NOT EXISTS score_owner_title ON score_history (owner, lower(job_title), created_at);
"""


class StoreError(ValueError):
    """Bad input. The message is safe and useful to show the user."""


def db_path():
    return os.environ.get('APEX_DB') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'apex.db')


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _today():
    return datetime.now(timezone.utc).date().isoformat()      # UTC, like _now() and the spend table


def _connect():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


@contextmanager
def _db(immediate=False):
    """One transaction on a fresh connection: commit on success, roll back on
    error, always close. immediate=True takes the write lock up front, so a
    read-then-write cannot interleave with another request's write."""
    conn = _connect()
    try:
        if immediate:
            conn.execute('BEGIN IMMEDIATE')
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init():
    parent = os.path.dirname(db_path())
    if parent:
        os.makedirs(parent, exist_ok=True)
    with _db() as conn:
        conn.execute('PRAGMA journal_mode = WAL')
        conn.executescript(TABLES)
        # Databases created before owners existed: add the column in place.
        # Existing rows become owner '' (the local user), which is what they were.
        def has_owner(table):
            return any(r['name'] == 'owner' for r in conn.execute('SELECT name FROM pragma_table_info(?)', (table,)))
        if not has_owner('applications'):
            conn.execute("ALTER TABLE applications ADD COLUMN owner TEXT NOT NULL DEFAULT ''")
        if not has_owner('score_history'):
            conn.execute("ALTER TABLE score_history ADD COLUMN owner TEXT NOT NULL DEFAULT ''")
        if not any(r['name'] == 'keywords' for r in conn.execute("SELECT name FROM pragma_table_info('score_history')")):
            conn.execute("ALTER TABLE score_history ADD COLUMN keywords TEXT NOT NULL DEFAULT '[]'")
        conn.execute('DROP INDEX IF EXISTS applications_dedupe')     # pre-owner index
        conn.execute('DROP INDEX IF EXISTS score_title')
        conn.executescript(INDEXES)


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
    d.pop('owner', None)          # internal; never sent to the browser
    d['followup_due'] = _followup_due(d)
    return d


def _followup_due(a):
    if a['status'] not in ('applied', 'interview'):
        return False
    if a.get('next_action_on'):
        return a['next_action_on'] <= _today()
    if a.get('applied_on'):
        return a['applied_on'] <= (date.fromisoformat(_today()) - timedelta(days=FOLLOWUP_AFTER_DAYS)).isoformat()
    return False


def _event(conn, app_id, kind, **detail):
    conn.execute('INSERT INTO events (application_id, at, kind, detail) VALUES (?,?,?,?)',
                 (app_id, _now(), kind, json.dumps(detail, ensure_ascii=False)))


def _find_dupe(conn, owner, company, role, url):
    return conn.execute(
        'SELECT * FROM applications WHERE owner = ? AND lower(trim(company)) = lower(?)'
        ' AND lower(trim(role)) = lower(?) AND url = ?', (owner, company, role, url)).fetchone()


# ── applications ──────────────────────────────────────────────────────────────

def create_application(data, *, owner=''):
    """Create, or return the existing row if company+role+url already exists
    for this owner. Returns (application, created: bool)."""
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
    with _db(immediate=True) as conn:
        existing = _find_dupe(conn, owner, company, role, url)
        if existing:
            return _row(existing), False
        n = conn.execute('SELECT count(*) FROM applications WHERE owner = ?', (owner,)).fetchone()[0]
        if n >= MAX_APPS_PER_OWNER:
            raise StoreError(f'pipeline is full ({MAX_APPS_PER_OWNER} applications); delete some first')
        if rec['notes']:
            _check_owner_bytes(conn, owner, len(rec['notes']))
        try:
            conn.execute(
                'INSERT INTO applications (id, owner, company, role, url, location, status, applied_on,'
                ' next_action_on, notes, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (rec['id'], owner, rec['company'], rec['role'], rec['url'], rec['location'], rec['status'],
                 rec['applied_on'], rec['next_action_on'], rec['notes'], rec['source'],
                 rec['created_at'], rec['updated_at']))
        except sqlite3.IntegrityError:
            # Lost a race with an identical create on another request thread.
            existing = _find_dupe(conn, owner, company, role, url)
            if existing:
                return _row(existing), False
            raise
        _event(conn, rec['id'], 'created', status=status, source=source)
    return get_application(rec['id'], owner=owner), True


def get_application(app_id, *, owner='', with_history=False):
    with _db() as conn:
        r = conn.execute('SELECT * FROM applications WHERE id = ? AND owner = ?', (app_id, owner)).fetchone()
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


def list_applications(*, owner=''):
    with _db() as conn:
        rows = [_row(r) for r in conn.execute(
            'SELECT * FROM applications WHERE owner = ? ORDER BY updated_at DESC', (owner,))]
        kits = {r['application_id']: r['n'] for r in conn.execute(
            'SELECT a.application_id, count(*) AS n FROM artifacts a JOIN applications p ON p.id = a.application_id'
            ' WHERE p.owner = ? GROUP BY a.application_id', (owner,))}
    for a in rows:
        a['artifact_count'] = kits.get(a['id'], 0)
    return rows


def update_application(app_id, changes, *, owner=''):
    allowed = {'status', 'notes', 'next_action_on', 'url', 'location', 'company', 'role', 'applied_on'}
    unknown = set(changes) - allowed - {'id'}
    if unknown:
        raise StoreError(f'cannot update: {", ".join(sorted(unknown))}')
    with _db(immediate=True) as conn:
        r = conn.execute('SELECT * FROM applications WHERE id = ? AND owner = ?', (app_id, owner)).fetchone()
        if not r:
            raise StoreError('application not found')
        _apply_update(conn, app_id, _row(r), changes, owner)
    return get_application(app_id, owner=owner)


def _apply_update(conn, app_id, current, changes, owner):
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
        return
    if 'notes' in upd and len(upd['notes']) > len(current['notes']):
        _check_owner_bytes(conn, owner, len(upd['notes']) - len(current['notes']))
    # Moving out of 'saved' is the moment of applying.
    if upd.get('status') and upd['status'] != 'saved' and not current['applied_on'] and 'applied_on' not in upd:
        upd['applied_on'] = _today()
    m = {**current, **upd, 'updated_at': _now()}
    try:
        conn.execute(
            'UPDATE applications SET company = ?, role = ?, url = ?, location = ?, status = ?, applied_on = ?,'
            ' next_action_on = ?, notes = ?, updated_at = ? WHERE id = ? AND owner = ?',
            (m['company'], m['role'], m['url'], m['location'], m['status'], m['applied_on'],
             m['next_action_on'], m['notes'], m['updated_at'], app_id, owner))
    except sqlite3.IntegrityError:
        raise StoreError('another application already has this company, role and link')
    if 'status' in upd and upd['status'] != current['status']:
        _event(conn, app_id, 'status', frm=current['status'], to=upd['status'])
    if 'notes' in upd and upd['notes'] != current['notes']:
        _event(conn, app_id, 'note')


def delete_application(app_id, *, owner=''):
    with _db() as conn:
        n = conn.execute('DELETE FROM applications WHERE id = ? AND owner = ?', (app_id, owner)).rowcount
    if not n:
        raise StoreError('application not found')


def import_applications(items, source='import', *, owner=''):
    """Bulk create with dedupe (localStorage migration, Gmail scan).
    Returns counts. Invalid rows are skipped and reported, never half-saved."""
    if not isinstance(items, list):
        raise StoreError('items must be a list')
    created, duplicates, skipped = 0, 0, []
    for i, it in enumerate(items[:1000]):
        try:
            it = it if isinstance(it, dict) else {}
            _, was_new = create_application({**it, 'source': it.get('source') or source}, owner=owner)
            created += was_new
            duplicates += not was_new
        except StoreError as e:
            skipped.append({'index': i, 'error': str(e)})
    return {'created': created, 'duplicates': duplicates, 'skipped': skipped}


def summary(*, owner=''):
    apps = list_applications(owner=owner)
    by = {s: sum(1 for a in apps if a['status'] == s) for s in STATUSES}
    sent = sum(by[s] for s in ('applied', 'interview', 'offer', 'rejected'))
    progressed = by['interview'] + by['offer']
    return {
        'total': len(apps), 'by_status': by, 'sent': sent,
        'response_rate': round(progressed / sent * 100) if sent else None,
        'followups_due': sum(1 for a in apps if a['followup_due']),
    }


# ── artifacts (apply kit) ─────────────────────────────────────────────────────

def add_artifact(app_id, kind, content, *, owner=''):
    if kind not in ARTIFACT_KINDS:
        raise StoreError(f'kind must be one of: {", ".join(ARTIFACT_KINDS)}')
    content = '' if content is None else str(content)
    if not content.strip():
        raise StoreError('content is empty')
    if len(content) > MAX_TEXT:
        raise StoreError('content is too large')
    get_application(app_id, owner=owner)   # raises if missing or someone else's
    with _db(immediate=True) as conn:
        n = conn.execute('SELECT count(*) FROM artifacts WHERE application_id = ?', (app_id,)).fetchone()[0]
        if n >= MAX_ARTIFACTS_PER_APP:
            raise StoreError(f'this application already has {MAX_ARTIFACTS_PER_APP} saved documents; delete it or start a new one')
        _check_owner_bytes(conn, owner, len(content))
        cur = conn.execute('INSERT INTO artifacts (application_id, kind, content, created_at) VALUES (?,?,?,?)',
                           (app_id, kind, content, _now()))
        _event(conn, app_id, 'artifact', artifact=kind)
        conn.execute('UPDATE applications SET updated_at = ? WHERE id = ?', (_now(), app_id))
    return cur.lastrowid


def _check_owner_bytes(conn, owner, adding):
    used = conn.execute(
        'SELECT coalesce((SELECT sum(length(notes)) FROM applications WHERE owner = ?), 0)'
        ' + coalesce((SELECT sum(length(a.content)) FROM artifacts a JOIN applications p ON p.id = a.application_id'
        ' WHERE p.owner = ?), 0)', (owner, owner)).fetchone()[0]
    if used + adding > MAX_OWNER_BYTES:
        raise StoreError('your saved documents are using all the space this demo allows; delete some applications first')


def record_followup_sent(app_id, days=FOLLOWUP_AFTER_DAYS, *, owner=''):
    """Mark that a follow-up went out; schedule the next one."""
    get_application(app_id, owner=owner)
    nxt = (date.fromisoformat(_today()) + timedelta(days=days)).isoformat()
    with _db() as conn:
        conn.execute('UPDATE applications SET next_action_on = ?, updated_at = ? WHERE id = ? AND owner = ?',
                     (nxt, _now(), app_id, owner))
        _event(conn, app_id, 'followup_sent', next_action_on=nxt)
    return get_application(app_id, owner=owner)


# ── daily AI budget (hosted demo) ─────────────────────────────────────────────

def try_spend(day, units, cap):
    """Atomically add `units` to `day` unless that would exceed `cap`.
    Persisted so a restarted (auto-stopped) machine can't reset the cap."""
    with _db() as conn:
        conn.execute('INSERT OR IGNORE INTO spend (day, units) VALUES (?, 0)', (day,))
        cur = conn.execute('UPDATE spend SET units = units + ? WHERE day = ? AND units + ? <= ?',
                           (units, day, units, cap))
        return cur.rowcount == 1


def spent(day):
    with _db() as conn:
        r = conn.execute('SELECT units FROM spend WHERE day = ?', (day,)).fetchone()
    return r['units'] if r else 0


# ── score history (drift baseline) ────────────────────────────────────────────

def _score(v):
    try:
        n = round(float(v))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, n))


def record_score(job_title, sector, before, after, *, owner='', keywords=None):
    """keywords: the run's requirements [{name, pct}], so a later drift check can
    re-count the same list on fresh postings (like with like)."""
    title = _text(job_title, 'job_title', 200, required=True)
    b, a = _score(before), _score(after)
    if a is None:
        raise StoreError('score_after must be a number')
    kws = [{'name': str(k.get('name'))[:80], 'pct': _score(k.get('pct'))}
           for k in (keywords or []) if isinstance(k, dict) and k.get('name')][:40]
    with _db() as conn:
        conn.execute('INSERT INTO score_history (owner, job_title, sector, score_before, score_after, keywords, created_at)'
                     ' VALUES (?,?,?,?,?,?,?)', (owner, title, (sector or 'general').strip(), b, a,
                                                 json.dumps(kws, ensure_ascii=False), _now()))
        conn.execute('DELETE FROM score_history WHERE owner = ? AND id NOT IN (SELECT id FROM score_history'
                     ' WHERE owner = ? ORDER BY id DESC LIMIT ?)', (owner, owner, MAX_SCORES_PER_OWNER))


def latest_score(job_title, *, owner=''):
    with _db() as conn:
        r = conn.execute('SELECT * FROM score_history WHERE owner = ? AND lower(job_title) = lower(?)'
                         ' ORDER BY id DESC LIMIT 1', (owner, (job_title or '').strip())).fetchone()
    if not r:
        return None
    d = dict(r)
    d.pop('owner', None)
    try:
        d['keywords'] = json.loads(d.get('keywords') or '[]')
    except ValueError:
        d['keywords'] = []
    return d


# ── maintenance ───────────────────────────────────────────────────────────────

def ping():
    """Raises if the database cannot be read (used by /health)."""
    with _db() as conn:
        conn.execute('SELECT 1 FROM spend LIMIT 1').fetchall()


def purge_inactive_owners(days):
    """Hosted demo: delete every non-local owner's data untouched for `days`
    (sessions last 14 days, so nobody can come back to it). The local user ''
    is never purged. Returns the number of applications removed."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec='seconds')
    with _db(immediate=True) as conn:
        stale = [r['owner'] for r in conn.execute(
            "SELECT owner FROM (SELECT owner, max(updated_at) AS t FROM applications WHERE owner != '' GROUP BY owner"
            " UNION ALL SELECT owner, max(created_at) FROM score_history WHERE owner != '' GROUP BY owner)"
            " GROUP BY owner HAVING max(t) < ?", (cutoff,))]
        n = 0
        for o in stale:
            n += conn.execute('DELETE FROM applications WHERE owner = ?', (o,)).rowcount
            conn.execute('DELETE FROM score_history WHERE owner = ?', (o,))
        conn.execute("DELETE FROM spend WHERE day < ?", ((datetime.now(timezone.utc) - timedelta(days=90)).date().isoformat(),))
    return n
