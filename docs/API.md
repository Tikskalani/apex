# API Reference

Everything here is served by `agent_server.py` (Python stdlib `ThreadingHTTPServer`).
This file describes the code as it is; if the two disagree, the code wins and this
file is out of date.

- [Reaching the server](#reaching-the-server)
- [Conventions](#conventions)
- [Validation before spending](#validation-before-spending)
- [Security model](#security-model)
- [Hosted demo mode](#hosted-demo-mode)
- [Configuration](#configuration)
- [GET routes](#get-routes)
- [POST routes that stream (SSE)](#post-routes-that-stream-sse)
- [POST routes that return JSON](#post-routes-that-return-json)
- [Local data API (`/api/*`)](#local-data-api-api)
- [SSE event reference](#sse-event-reference)

---

## Reaching the server

```
python agent_server.py
# open http://localhost:7842/
```

- Default port `7842`; override with `APEX_PORT`.
- Locally it listens on loopback only: `127.0.0.1` and, if available, `::1`.
  It never binds `0.0.0.0` unless hosted mode is configured (see below).
- `GET /` serves `index.html`. The page and the API share one origin, so the page
  calls the API with plain relative `fetch()`es.
- Do not open `index.html` from disk. A `file://` page sends `Origin: null`, which the
  server refuses with a 403 telling you to open `http://localhost:7842/` instead.
- The server starts without a model key. The page then shows a setup card (from
  `GET /config`), and routes that need a model answer `503` (see below).
- At most 64 requests are handled at once; one more gets `503` with an empty body.
  An idle connection is dropped after 60 seconds.

## Conventions

| Topic | Rule |
|---|---|
| Request bodies | A JSON object (`Content-Type: application/json`), sent with a `Content-Length`. An empty body counts as `{}`. Exception: hosted-mode `POST /login` takes a form post. |
| Body errors | `Transfer-Encoding` instead of a length: `411 {"error": "Send a Content-Length."}`. A length that is not a number, or is negative: `400 {"error": "Bad Content-Length."}`. Not valid JSON: `400 {"error": "Bad JSON: ..."}`. Valid JSON but not an object: `400 {"error": "Request body must be a JSON object."}`. On 411 and 413 the body is left unread and the connection is closed. |
| Size limits | Body: 2,000,000 bytes (`MAX_BODY_BYTES`); `/transcribe`: 36,000,000 bytes (`MAX_AUDIO_BODY_BYTES`, 25 MB of audio after base64). Fields: `resume`, `original`, `optimized` at most 40,000 characters (`MAX_RESUME_CHARS`); `jobDesc`, `jobPosting`, `posting` at most 20,000 (`MAX_POSTING_CHARS`); any other string field at most 60,000 (`MAX_FIELD_CHARS`; `audio_b64` exempt). Over a limit: `413 {"error": "..."}`. Hosted `POST /login`: 4 KB. Store fields have their own limits (see `/api/*`). |
| JSON errors | `{"error": "message fit to show the user"}` with the HTTP status listed per route. |
| Unknown route | `404 {"error": "not found"}` |
| Query strings on POST | Ignored for dispatch: POST routes match the path without its query string, so `/analyze?x=1` is `/analyze`. |
| SSE responses | `200`, `Content-Type: text/event-stream`, `Connection: close`. See below. |

### How SSE responses work

Streaming routes answer with one frame per event:

```
data: {"type": "log", "msg": "PHASE 3 — Relevance Filter"}

data: {"type": "market_data", "data": {...}}

: ping

```

- Every event frame is a single `data:` line holding one JSON object with a `type` field.
  There are no `event:` or `id:` lines.
- Every 15 seconds the server writes a `: ping` comment line (a heartbeat). Clients must
  skip lines that do not start with `data:`.
- The response has no `Content-Length`. **The server closes the connection to end the
  stream**; that close is the only end-of-stream signal. Clients must read until EOF.
- Validation failures happen before the stream starts and come back as an ordinary
  JSON error (see [Validation before spending](#validation-before-spending)).
- Once the stream has started, failures arrive as an `error` event inside the 200
  response. A stream normally ends with `done`; after an `error` it may simply end.
- Events may arrive from several server threads; each frame is written atomically.
- **Cancelling.** Closing the connection cancels the run: the next write or heartbeat
  fails, and from then on the request makes no more model calls and fetches no more job
  postings. The page's Cancel button aborts the `fetch`, which does exactly this.

## Validation before spending

A POST request goes through these steps in order; the first that fails answers, and a
refused request costs nothing (no budget, no model call):

1. `_guard` (Host / Origin / Sec-Fetch-Site): `403`.
2. Hosted mode: session (`401`), then routes switched off in the demo (`403`).
3. Body read: `411`, `413` or `400` (see Conventions). `/api/*` routes are dispatched here.
4. `validate_post`: size limits (`413`), required fields (`400`, table below), numeric
   fields clamped into range (a value that is not a number: `400 {"error": "<field> must be a number."}`).
5. `_precheck`: checks that need the store or the session (`/drift`, `/engine/answer`,
   `/apply-all-recommendations`; see each route): `400`.
6. No model key configured and the route needs a model (any `AI_COSTS` route except
   `/live-jobs`, and only when it would cost something):
   `503 {"error": "No AI key is set up yet. Copy config.example.json ...", "setup": true}`.
7. Hosted mode: AI budget (`429 {"error": "..."}`).

Required fields (`REQUIRED`; "resume (100+)" means a resume of at least 100 characters
after trimming, else `400 {"error": "Resume too short (N of 100 characters minimum). Paste the full resume text first."}`):

| Route | Required | Message when missing |
|---|---|---|
| `/analyze` | `jobTitle`, resume (100+) | `Enter a target job title.` |
| `/tailor`, `/match` | `jobPosting`, resume (100+) | `Paste the job posting first.` |
| `/bullets`, `/xray`, `/velocity`, `/negotiate` | resume (100+) | |
| `/bridge` | `fromRole`, `toRole`, resume (100+) | `Enter the role you are moving from.` / `Enter the role you want.` |
| `/grade-answer` | `question`, `answer` | `There is no interview question to grade.` / `Type or record an answer first.` |
| `/followup` | `company`, `role` | `Enter the company.` / `Enter the role.` |
| `/draft-cover-letter` | `resume` | `resume required` |
| `/parse-resume` | `resume` | `Paste your resume first.` |
| `/live-jobs` | `q` | `q required` |
| `/transcribe` | `audio_b64` | `audio_b64 required` |
| `/alerts/subscribe` | `email`, `jobTitle` | `email and jobTitle required` |
| `/inbox/scan` | `user`, `password` | `user and password required` |

## Security model

The server is reachable by every web page open in the user's browser, because any
page can send requests to `localhost`. The defences below assume that.

| Defence | What it does |
|---|---|
| `_guard` (every method, before any route runs) | Refuses with `403 {"error": ...}` when: the `Host` header is not `localhost:PORT`, `127.0.0.1:PORT`, `[::1]:PORT` (or `APEX_PUBLIC_HOST` when hosted), which blocks DNS rebinding; an `Origin` header is present and is not one of the server's own origins (`Origin: null` from `file://` gets a specific message); or `Sec-Fetch-Site: cross-site`, except a top-level navigation `GET /` or `/index.html`. Requests with no `Origin` header (curl, scripts, the test suite) pass the origin check. POSTs are refused before the body is read, so a `text/plain` POST that skips the CORS preflight is still blocked. |
| CORS | Never `*`. `Access-Control-Allow-Origin` echoes the request `Origin` only when it is one of the server's own origins (`http://localhost:PORT`, `http://127.0.0.1:PORT`, `http://[::1]:PORT`, or `https://APEX_PUBLIC_HOST`), with `Vary: Origin`. Allowed methods `GET, POST, OPTIONS`; allowed header `Content-Type`. `OPTIONS` runs the guard, then answers `204`. |
| Static files | Allowlist only. A path is served if and only if it matches `/<name>.<ext>` or `/assets/<name>.<ext>`, the name uses only `A-Z a-z 0-9 _ -` and dots between segments, and the extension is one of `css js png jpg jpeg webp svg ico woff2 ttf`. `config.json`, `*.py`, `*.db`, dotfiles and Windows aliases (`config.json.`, `x::$DATA`) never match. Anything else with a dot in the last segment is a 404. |
| CSP on `index.html` | A fresh random nonce per page load is added to every `<script` tag in the file. Policy: `default-src 'none'`; `script-src 'nonce-...' 'strict-dynamic'` plus `https://cdnjs.cloudflare.com` and `https://cdn.jsdelivr.net` (browsers that understand `'strict-dynamic'` ignore the host list); `worker-src blob:` plus cdnjs (pdf.js worker); `style-src 'self' 'unsafe-inline'` plus Google Fonts; `font-src` Google Fonts and `data:`; `img-src 'self' data: blob:`; `media-src 'self' blob:`; `connect-src 'self'`; `frame-src 'self' blob: data:`; `object-src 'none'`; `base-uri 'none'`; `form-action 'self'`; `frame-ancestors 'none'`. Also `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, and `Strict-Transport-Security` when `APEX_PUBLIC_HOST` is set. Inline `on*=` handlers cannot run under this policy. The vendor libraries (pdf.js, mammoth, jsPDF, docx) are not in the HTML: the page's own script adds each on first use with its pinned URL and SRI `integrity` (which `'strict-dynamic'` allows), so a modified CDN file is refused. |
| No key material | No response contains an API key or SMTP password. `GET /config` reports presence only (`JSEARCH_ACTIVE`, `SMTP_CONFIGURED`, `AI_READY`, `VOICE_READY`). Store rows never include their `owner` column. |

## Hosted demo mode

Off unless `APEX_ACCESS_CODE` is set. Local runs never see any of it.

| Item | Behaviour |
|---|---|
| Startup checks | Exits if `APEX_ACCESS_CODE` is set and `APEX_SESSION_SECRET` is shorter than 32 characters. Exits if `APEX_PUBLIC_HOST` is set, or `APEX_BIND` is not loopback, without an access code. |
| `GET /login` | Sign-in page (its own strict CSP). Only exists in hosted mode. |
| `POST /login` | Form field `code`, compared in constant time. Right code: `303` to `/` with a new session cookie. Wrong code: `401` page. `429` page when the IP has 5 wrong codes in 10 minutes, when more than 60 sign-in attempts arrived from anyone in 10 minutes (a rotating or spoofed IP cannot get around it), or, for a right code, when the IP already started 5 sessions in the last 24 hours. Body over 4 KB (or a negative length): `413`. |
| `GET /logout` | `303` to `/login`, clears the cookie. |
| Session cookie | `apex_session=v1.<owner>.<expiry>.<HMAC-SHA256>`, signed with `APEX_SESSION_SECRET`. `HttpOnly; SameSite=Lax; Path=/`, plus `Secure` when `APEX_PUBLIC_HOST` is set. Valid 14 days. Each session gets a random `owner` id, and every store query filters by it, so visitors never see each other's data. |
| No valid session | `GET /` or `/index.html`: `303` to `/login`. Anything else: `401 {"error": "Your session has ended. Reload the page to sign in again.", "login": true}`. `/health`, `/login` and `/logout` need no session. |
| AI budget | Each AI-backed route costs units (table below), charged after validation, before the work starts. Two hourly limits, each `APEX_VISITOR_BUDGET` (default 40, held in memory): one per visitor and one per client IP, so signing in again does not reset it. Plus a shared UTC-day budget (`APEX_DAILY_BUDGET`, default 300, persisted in `apex.db` so a restart cannot reset it). Over any of them: `429 {"error": "..."}`. |
| Disabled routes | `403 {"error": "This feature is turned off in the online demo. Run APEX locally to use it."}` for `/config/smtp`, `/config/smtp/test`, `/alerts/subscribe`, `/alerts/unsubscribe`, `/alerts/test`, `/alerts/scan`, `/alerts/list`, `/inbox/scan`. The job-alert background loop does not run. |
| `/engine/answer` | The `sig` from `engine_data` must match the `target` sent back (HMAC with the session secret), so a visitor cannot widen what the fact gate accepts. |
| `/health` | Skips only the Host check (platform health checks use an internal Host). Origin and Sec-Fetch-Site rules still apply. |
| Client IP | With `APEX_TRUST_PROXY=1`: on Fly.io (`FLY_APP_NAME` set) the `Fly-Client-IP` header; elsewhere the last `X-Forwarded-For` entry (the one the nearest proxy added). Otherwise, or when that header is empty, the socket address. Used for login throttling, sessions per IP and the per-IP budget. |
| Data retention | A background thread (every 6 hours) deletes every visitor whose newest application update and score record are more than 21 days old (the 14-day session plus a week), and daily-budget rows older than 90 days. The local owner `''` is never purged. |
| Store caps | Per owner: 20 MB of notes and saved documents, 2000 applications, 200 score records; 50 saved documents per application. These apply locally too. |

Cost units per route (`AI_COSTS`):

| Units | Routes |
|---|---|
| 12 | `/analyze` |
| 8 | `/tailor` |
| 6 | `/engine/answer` |
| 2 | `/bullets`, `/negotiate`, `/bridge`, `/followup`, `/match`, `/xray`, `/grade-answer`, `/draft-cover-letter`, `/parse-resume`, `/render-resume` (0 when a `struct` is sent), `/transcribe` |
| 1 | `/drift`, `/velocity`, `/live-jobs` (GET and POST; no model call, it limits job-board scraping) |
| 0 | everything else (`/api/*`, `/engine/render`, `/apply-all-recommendations`, ...) |

Routes whose text is fact-checked cost more: the check and its repair are model calls too.

## Configuration

### `config.json`

Lives beside `agent_server.py`; gitignored. Copy `config.example.json` to start.
Keys starting with `_` are comments.

| Key | Purpose |
|---|---|
| `OPENAI_KEY` | OpenAI key. Needed for any `gpt-...` model and for `/transcribe` (Whisper). Env fallback `OPENAI_API_KEY`. |
| `ANTHROPIC_KEY` | Anthropic key. Needed for any `claude-...` model. Env fallback `ANTHROPIC_API_KEY`. |
| `ANTHROPIC_WORKSPACE_ID` | Only for organisation-level Anthropic keys; sent as the `anthropic-workspace-id` header. Env fallback of the same name. |
| `JSEARCH_KEY` | RapidAPI JSearch key. Optional; the free job sources work without it. Env fallback `JSEARCH_API_KEY`. |
| `MODEL` | Model that writes, reviews and judges. |
| `MODEL_FAST` | Model for extraction and classification (requirement proposal, posting requirements for `/tailor`, inbox classification). |
| `MODEL_AUDIT` | Optional. Model for the fact-check audits (resume edits and `verify_texts`). Empty: `MODEL`. |
| `MODEL_JUDGE` | Optional. Model for the blind hiring-manager judge. Empty: `MODEL_AUDIT`. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` | Optional, job-alert email only. Default host `smtp.gmail.com`, port `587`. `POST /config/smtp` writes these into `config.json`. |

No model key is required to start. Without `OPENAI_KEY` and `ANTHROPIC_KEY` the server
prints a warning and runs; `GET /config` reports `AI_READY: false` with the reason in
`AI_PROBLEM`, and model routes answer `503 {"error", "setup": true}`.

The four key names above (`OPENAI_KEY`, `ANTHROPIC_KEY`, `ANTHROPIC_WORKSPACE_ID`,
`JSEARCH_KEY`) are matched tolerantly: case, punctuation and the word `API` are ignored,
so `Anthropic_API-Key` and `anthropic api key` both work. For these keys `config.json`
wins over the environment. The `MODEL*` and `SMTP_*` keys are read by their exact names.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `APEX_PORT` | `7842` | Listen port. |
| `APEX_MODEL` | see below | Overrides `MODEL` in `config.json`. |
| `APEX_MODEL_FAST` | see below | Overrides `MODEL_FAST`. |
| `APEX_MODEL_AUDIT` | `MODEL` | Overrides `MODEL_AUDIT`. |
| `APEX_MODEL_JUDGE` | `MODEL_AUDIT` | Overrides `MODEL_JUDGE`. |
| `APEX_DB` | `apex.db` beside the server | SQLite file path. |
| `APEX_OPENAI_BASE` | `https://api.openai.com` | OpenAI base URL (the tests point it at an offline stub). |
| `APEX_ANTHROPIC_BASE` | SDK default | Anthropic base URL (tests). When set, server-side fallback is not requested. |
| `APEX_FIXTURE_JOBS` | unset | Path to a JSON file `{"postings": ["text", ...], "jobs": [{title, company, location, url, source, posted, snippet, salary}, ...]}`. When set, no job board is contacted: runs, drift and salary use these postings, `/live-jobs` returns these jobs. The tests use it. |
| `USAJOBS_API_KEY`, `USAJOBS_EMAIL` | unset | USAJobs source (both needed; the email is the one the key was issued to). |
| `FINDWORK_API_KEY` | unset | Findwork.dev source. |
| `APEX_ACCESS_CODE` | unset | Turns on hosted mode. |
| `APEX_SESSION_SECRET` | unset | Signs session cookies and the engine target `sig`; at least 32 characters when hosted. |
| `APEX_PUBLIC_HOST` | unset | Public hostname, e.g. `apex-demo.fly.dev`. Added to allowed Host/Origin; enables `Secure` cookies and HSTS. |
| `APEX_BIND` | loopback | Bind address (`0.0.0.0` inside a container). Non-loopback requires hosted mode. |
| `APEX_TRUST_PROXY` | unset | `1` to take the client IP from a proxy header (see Client IP above). |
| `APEX_VISITOR_BUDGET` | `40` | Cost units per visitor, and per IP, per hour. |
| `APEX_DAILY_BUDGET` | `300` | Cost units for all visitors per UTC day. |

### Model selection

Order of precedence: `APEX_<NAME>` env, then `config.json` `<NAME>`, then the default.

| Keys present | `MODEL` default | `MODEL_FAST` default |
|---|---|---|
| Anthropic only | `claude-opus-5-5` | `claude-haiku-5-5` |
| OpenAI (with or without Anthropic) | `gpt-4o` | same as the resolved `MODEL` |

`MODEL_AUDIT` defaults to the resolved `MODEL`, `MODEL_JUDGE` to the resolved
`MODEL_AUDIT`. The engine's calls go through `engine_llm`, which sends fact-check
prompts to `MODEL_AUDIT` and judge prompts to `MODEL_JUDGE`, so the writer does not
grade its own work when they differ.

Routing is by prefix: `claude-...` goes to Anthropic through the official `anthropic` SDK,
anything else to OpenAI `/v1/chat/completions`. A model whose provider key is missing
fails at call time with a message naming the missing key. `config.example.json` suggests
`claude-opus-5-5` / `claude-haiku-5-5`; use `tools/benchmark.py` to choose on your own
resumes.

---

`MODEL_REVIEW` (config or `APEX_MODEL_REVIEW`, default `MODEL`) runs the engine's recruiter review. For faster runs set it and `MODEL_AUDIT` to `claude-sonnet-5-5`: measured on 4 bench resumes, the engine took about 65 s instead of 85 s, with an average gain of +7.0 instead of +9.0.

## GET routes

| Path | Query | Response |
|---|---|---|
| `/`, `/index.html` | | `index.html` with a per-load CSP nonce. Hosted without a session: `303 /login`. |
| `/<file>.<ext>`, `/assets/<file>.<ext>` | | Allowlisted static file (e.g. the Noto Sans fonts the PDF export embeds), or `404`. |
| `/health` | | `{"status": "ok", "version": "11.0", "db": "ok", "ai_ready": bool, "jsearch": "active"\|"inactive", "sectors": [...], "templates": [...]}`. `version` is the server's `VERSION`. `db` comes from a read of `apex.db`; when it fails the answer is `503` with `"status": "degraded"` and `"db": "error: <Type>"`. |
| `/config` | | `{"JSEARCH_ACTIVE": bool, "HOSTED": bool, "SMTP_CONFIGURED": bool, "AI_READY": bool, "AI_PROBLEM": "" or the setup message, "VOICE_READY": bool (an OpenAI key exists), "MODEL": model name or "" when not ready, "VERSION": "11.0"}`. Presence only, never key values. |
| `/templates` | | `{"templates": [{"id", "name", "desc"}]}` for `modern`, `classic`, `tech`, `executive`, `creative`, `minimal` |
| `/cities` | | `{"cities": ["Austin, TX", ...], "extras": ["Remote", "Anywhere", "AL", ...]}` |
| `/live-jobs` | `q` (required), `location`, `limit` (default 40, clamped to 1-100) | `{"jobs": [...], "count", "query", "parsed_location", "requested_location"}`. Job: `{title, company, location, url, source, posted, snippet, salary}`. `400` if `q` is missing or `limit` is not a number. No model call; costs 1 unit in hosted mode (`429` over budget). See POST `/live-jobs` for the sources. |
| `/alerts/list` | `email` (optional filter) | `{"subscriptions": [...]}`. Local only. |
| `/api/applications`, `/api/application`, `/api/scores/latest` | | See [Local data API](#local-data-api-api). |
| `/login`, `/logout` | | Hosted mode only (see above). |

There is no GET `/render-resume`; use POST.

## POST routes that stream (SSE)

All of these call the model. Each lists its request fields, the events it emits beyond
`log` and `step`, and what ends it. Missing optional fields fall back to the default shown.
Required fields are checked before the stream starts (see above).

### `POST /analyze`

The full run. See ARCHITECTURE.md for what each phase does.

| Field | Required | Default | Notes |
|---|---|---|---|
| `jobTitle` | yes | | Empty: `400 {"error": "Enter a target job title."}` |
| `resume` | yes | | 100 to 40,000 characters. |
| `seniority` | | `senior` | |
| `jobDesc` | | `""` | A target posting, up to 20,000 characters. Highest-priority signal for requirements and rewriting. |
| `industry` | | `general` | Stored with the score record. The run's sector comes from the model's Phase 0 classification. |
| `mode` | | `optimize` | Echoed in logs only. |

Events, in roughly this order: `log`, `step` (ids `market`, `heat`, `analyze`, `rewrite`,
`report`), `jobs_data`, `market_data` (after Phase 5), `notice` (only when the engine
found nothing to edit, or the judge kept the original), `market_data` again (now with
after-scores), `engine_data`, `resume_data`, `report_data`, then `tab_skipped` for each
Phase 8 tab that failed or was stopped at its deadline, `cost_data`, `done`. The Phase 8
events (`cover_letter_data`, `interview_data`, `linkedin_data`, `outreach_data`,
`velocity_data`) arrive whenever they finish, anywhere after the first `market_data`.
When `report_data` is sent, the server also writes the before/after keyword score and the
run's requirement list (`baselineKeywords`) to `score_history`: the baseline for `/drift`.
An uncaught failure sends `error` and ends the stream; a failing Phase 8 tab only logs
and sends `tab_skipped`.

### `POST /engine/answer`

Rewrites the lines the candidate answered questions about, with the answers as new
evidence (`engine.revise`). Only the answered ids are rewritten (Skills lines never);
they go through the same fact gate, audit and one retry, then one judge with its veto.
There is no new diagnosis.

| Field | Required | Notes |
|---|---|---|
| `resume` | yes | The original resume (`engine_data.data.original`), at least 100 characters. |
| `target` | yes | `engine_data.data.target`; must contain `title`. Missing or short resume or no target: `400 {"error": "Run the agent first, then answer the questions."}` |
| `sig` | hosted | `engine_data.data.sig`. Checked only in hosted mode; a mismatch is `400 {"error": "This review is from an older run. Run the agent again, then answer the questions."}` |
| `answers` | yes | `{"B3": "about 40 clinics", ...}` keyed by block id. All empty: `400 {"error": "Answer at least one question."}` Each answer is cut to 500 characters. |
| `kept` | | `{id: [lines]}`: the edits from the first run the user kept (at most 3 lines each). Applied as they are; an answered id that fails verification falls back to its kept edit, else the original. |
| `questions` | | The first run's `questions`; unanswered ones are carried over. |
| `order`, `section_order` | | The first run's reordering, re-applied when still valid. |
| `problems`, `strengths`, `summary_verdict` | | The first run's diagnosis, carried into the result. |

Events: `log`, `engine_data` (`{"data": ..., "answers": {...}}`; `data.revised` lists the
ids rewritten), `cost_data`, `done`; or `error`. A judge veto or a nothing-to-edit note
is in `engine_data.data` (`veto`, `note`); this route sends no `notice`.

### Single-tool streams

| Route | Request fields (default) | Data event | Ends with |
|---|---|---|---|
| `/tailor` | `jobPosting` (required), `resume` (required), `jobTitle`, `sector` (`general`) | `tailor_data`; `notice` as in `/analyze` | `done` / `error` |
| `/bullets` | `resume` (required), `jobTitle`, `sector` (`general`), `keywords` (array of strings) | `bullet_data` | `done` / `error` |
| `/negotiate` | `resume` (required), `jobTitle`, `sector` (`general`), `seniority` (`senior`), `location`, `marketData` (object; reads `salary_skills`) | `negotiate_data` | `done` / `error` |
| `/bridge` | `fromRole`, `toRole`, `resume` (all required), `sector` (`general`) | `bridge_data` | `done` / `error` |
| `/followup` | `company`, `role` (required), `daysSince` (7), `resume`, `resumeSummary` | `followup_data` (also has `company`) | `done` / `error` |
| `/match` | `jobPosting`, `resume` (required) | `match_data` | `done` / `error` |
| `/xray` | `resume` (required), `jobTitle`, `sector` (`general`), `keywords` | `xray_data` | `done` / `error` |
| `/grade-answer` | `question`, `answer` (required), `jobTitle`, `sector` (`general`), `resume` | `answer_grade` (also has `question`) | `answer_grade` or `error`; no `done` |
| `/velocity` | `resume` (required), `jobTitle`, `sector` (`general`), `seniority` (`senior`) | `velocity_data` | `done` / `error` |
| `/drift` | `jobTitle` (required), `resume` (required, 100+ chars), `baselineScore`, `sector` (`general`) | `drift_data` (also has `role`) | `done` / `error` |

Notes:

- `/tailor` runs the Evidence Engine with the posting as the target: one fast call extracts the
  posting's requirements (up to 20), `classify_keywords` splits them into shown and not shown, then
  `engine.optimize` rewrites, verifies line by line and judges. `match_score_before` /
  `match_score_after` are the blind hiring-manager scores against this posting (`null` when no
  editable lines were found). Requirements the resume does not show are listed in `gaps` and
  never added.
- **Fact check.** Text these routes write about the candidate goes through
  `engine.verify_texts`: the deterministic fact gate, then a model audit, one repair with the
  reasons; a text that still fails loses just the sentences the check quotes when at least 60%
  of it survives, and what is left is checked again; whatever still fails is withheld. Suggested
  rewrites, Bridge reframes and answers, interview sample answers and `better_version` may leave a
  short blank in square brackets ("[by X%]") for a fact only the candidate knows: a blank claims
  nothing; everything stated outright is checked. `/bullets` rewrites, `/xray` fixes, and
  `/bridge` reframes are checked against their role's text where the quoted line is found (else
  the whole resume); `/bridge` narrative and answers, `/negotiate` leverage points and
  `/followup` messages against the resume (for `/followup`: `resume`, else `resumeSummary`);
  `/grade-answer`'s `better_version` against the candidate's answer plus `resume`. A withheld
  field is `null` (or `""` for a message or the narrative) with the reasons beside it:
  `rewrite_withheld`, `fix_withheld`, `reframed_bullet_withheld`, `answer_withheld`,
  `narrative_withheld`, `better_version_withheld`, `your_leverage_withheld`, and `withheld` in
  `followup_data`. Scores, `/bridge` skill translations and `/match` results are opinions and are
  not checked; `/match` instead marks each quick fix with `shown_on_resume`.
- `/negotiate` first looks for real pay: it fetches live postings (the `/live-jobs` sources, up
  to 80), reads every stated pay range (hourly rates × 2080; values outside $15,000-$1,500,000
  ignored) and, with at least 3, gives the model the 25th percentile, median and 75th percentile
  (rounded to $1,000). An entry-level title counts only entry-level postings and a senior title
  senior ones (all postings when fewer than 3 say senior). Then `estimate_basis` is `postings` and
  `posted_pay` is included (with `companies`, the employers most of the figures come from, also
  named in `basis_note`);
  otherwise it is `model_estimate` and `basis_note` says the figures are an AI estimate.
- `/drift` is deterministic apart from one fast call. `_precheck` refuses an empty `jobTitle`
  (`400 {"error": "Enter a target job title."}`), a short resume
  (`400 {"error": "Paste your resume in Launch first."}`), and, without `baselineScore`, a job
  title with no stored run (`400` asking you to run the agent once for it). It re-scrapes postings
  (fewer than 5 relevant: an `error` event and no `done`), has the model propose today's
  requirements, and counts both today's list and the baseline run's stored list in today's
  postings. It then scores the same resume with `ats_score` against the baseline's list and
  against today's: `drift = current_score - baseline_score`, `basis` says which comparison was
  made. A stored run from before requirement lists were saved, or an explicit `baselineScore`,
  falls back to comparing today's score with that stored number.
- `/velocity` has no button of its own in the page; `/analyze` Phase 8 fills that view.

## POST routes that return JSON

| Route | Request fields | Success response | Errors |
|---|---|---|---|
| `/engine/render` | `resume` (the original), `edits` `{id: [lines]}` (`S`, `B#`, `K#`; at most 3 lines per id; unknown ids ignored), `order` `[[ids of one role]]`, `section_order` `[header names]` | `{"text": "..."}` | `400 {"error"}` |
| `/parse-resume` | `resume` (required) | `{"struct": {...}, "dropped": [{field, text}]}`. `struct`: name, title, authorization, contact fields, summary, experience, education, skills, certifications, projects, languages, awards, additional. Every string is checked against the resume text (`verify_struct`): kept when it is there, replaced by the closest resume line when the model paraphrased it, else blanked and listed in `dropped`. | `400`; `503` no AI key; `500 {"error"}` |
| `/render-resume` | `template` (default `modern`; unknown ids render as `modern`), `struct`, or `resume` | `{"html", "template", "struct"}`. With `struct`: rendered as sent, no model call, cost 0. With only `resume`: parsed and checked as in `/parse-resume`, cost 2. | `400 {"error": "Send struct or resume."}`; `503` no AI key (resume only); `500 {"error"}` |
| `/draft-cover-letter` | `resume` (required), `jobTitle`, `company`, `posting`, `sector` | `{"letter", "verified": true, "jobTitle", "company"}`; the letter passed the fact check (the posting may be named, claims about the candidate must be in the resume) | `400`; `422 {"error": "Withheld: ...", "letter": "", "withheld": [problems]}` when it could not be verified after one repair; `500 {"error", "letter": ""}` |
| `/transcribe` | `audio_b64` (required), `mime` (default `audio/webm`; also `audio/ogg`, `audio/mp4`, `audio/mpeg`, `audio/wav`) | `{"text": "..."}` (OpenAI `whisper-1`) | `400` no audio, unsupported `mime`, or no OpenAI key (an Anthropic-only setup: "type your answer instead"); `413` body over 36,000,000 bytes or audio over 25 MB; `503` no model key at all; `500 {"error", "text": ""}` |
| `/live-jobs` | `q` (required), `location`, `limit` (40, clamped 1-100), `resume`, `minScore` (0, clamped 0-100) | As GET `/live-jobs`; with `resume`, each job gains `match_score` (0-100, local keyword overlap, no model call) and `shared_keywords`, and jobs under `minScore` are dropped | `400`; `429` hosted budget; `500` |
| `/apply-all-recommendations` | `optimized` or `original` (the base), `original` (the evidence), `bulletRewrites` / `changes` (`[{text\|bullet\|original\|before, rewrite\|after}]`), `addedKeywords` | `{"merged", "applied": {"lines", "keywords": 0}, "skipped": [{line, why}], "keywords_not_added"}` | `400 {"error": "optimized or original resume required"}`; `500 {"error", "merged"}` |

`/live-jobs` queries Remotive, Arbeitnow, Jobicy, RemoteOK, The Muse (by category),
the public Greenhouse, Ashby and Lever boards of a fixed list of tech and AI employers
(`company_board_jobs`: full postings, with pay where the posting states it; one fetch per
title is cached for 15 minutes), and the latest Hacker News "Who is hiring" thread; JSearch and USAJobs only with their keys. All sources run in
parallel under one 25-second deadline (a source that has not answered by then is left
out), a response over 12 MB is discarded, and a location in `q` ("nurse houston") is
detected when `location` is empty. Jobs are de-duplicated by title + company, directory
and landing pages are dropped, the rest are filtered by location aliases and ranked by
title match, location and source. Per-source counts are computed but not returned.

`/engine/render` makes no model call. It reassembles the original resume with the edits
the user kept; unchanged lines come out byte-identical. It does not re-verify edit text:
the page sends back edits it received in `engine_data`. Skills (`K#`) edits that change
the set of skills are ignored.

`/apply-all-recommendations` is legacy and the page no longer calls it. It makes no model
call: a rewrite is applied only when it replaces a line in the resume and passes the fact gate
against that line's role in `original`. Keywords are never woven in; they come back in
`keywords_not_added`.

### Local-only routes (403 in hosted mode)

The job agent (`/api/agent/*`, JSON, local only):

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/api/agent/profiles` | | `{"profiles": [{id, name, base_resume, targets, location, remote_ok, daily_limit, min_fit, active, last_scan}], "scan_hour"}` |
| POST | `/api/agent/profiles` | `id` (to update), `name` (required), `targets` (list or comma-separated, up to 6), `base_resume`, `location`, `remote_ok`, `daily_limit` (1-50, 30), `min_fit` (0-90, 35), `active` | `{"profile"}` |
| POST | `/api/agent/profiles/delete` | `id` | `{"deleted": true}` (its queue goes with it; Tracker rows stay) |
| POST | `/api/agent/scan` | `profile` | `{"started": true}`; the scan runs in the background |
| GET | `/api/agent/queue` | `?profile=` | `{"items": [{id, title, company, location, url, source, salary, posted, posting (first 400 chars), fit, reasons {target, matched, missing}, status, kit, application_id, scanned_on}], "scanning", "preparing"}`. Status: `proposed`, `approved`, `preparing`, `ready`, `applied`, `skipped`, `failed` |
| GET | `/api/agent/item` | `?id=` | `{"item"}` with the full posting and kit `{resume, cover_letter, letter_withheld, changes, gaps, score_before, score_after}` or `{error}` |
| POST | `/api/agent/approve` | `ids` | `{"approved": n}` (from proposed, failed or skipped); starts preparing. `503` without an AI key |
| POST | `/api/agent/skip` | `ids` | `{"skipped": n}` |
| POST | `/api/agent/apply` | `id`, `pdf_b64` (the tailored resume PDF the page made) | One-tap Apply. `{"mode": "filled", "url", "filled": [fields], "error"}`: the application opened in the APEX browser window (a Chromium profile in `apex_browser/`, via `apex_apply.py`) and its contact fields, resume and cover letter were filled; nothing is submitted. `{"mode": "link", "url"}` when Playwright is not installed or `APEX_FORM_FILL=0`: the page opens the posting |
| GET | `/api/agent/radar` | `?profile=` | `{"postings", "days", "skills": [{term, share, shown, trend}], "gaps": [...the most-asked skills not shown], "families": [{family, label, share}]}` over the last 14 days of scans. `share` is the % of full postings asking for the skill; `shown` is whether the base resume or the evidence vault shows it; `trend` is the change in share against the 14 days before (null with fewer than 10 postings then) |
| GET | `/api/agent/digest` | `?profile=` | `{"day", "new", "ready", "top": [{id, title, company, fit, status}], "gaps", "postings"}`: today's new matches, kits ready to apply, the top gaps |
| POST | `/api/applications/prep` | `id`, `resume` | `{"pack": {company, role, from_posting, focus, questions: [{q, kind, why, outline}], stories: [{title, situation, action, result}], ask, review, withheld}}`, also saved as the application's `interview_prep` artifact (JSON). Outlines and stories are fact-checked against the resume and the evidence vault: a withheld outline is `""`, a withheld story is left out, `withheld` counts both. One model call. `503` without an AI key |
| POST | `/api/agent/radar/ideas` | `profile` | `{"ideas": [{title, closes, builds_on, plan, measure, resume_line}], "gaps"}`: three project ideas for the top gaps (one model call). `400` with no gaps yet, `503` without an AI key |
| POST | `/api/agent/applied` | `id` | `{"application"}`: created in the Tracker (status applied, source `agent`) with the tailored resume and cover letter as artifacts |

The evidence vault (`/api/facts`, JSON, local only). Every engine run, tailoring, cover letter and agent kit reads it; `/engine/answer` adds the answers it receives (source `answer`).

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/facts` | | `{"facts": [{id, topic, text, source, created_at}]}`, newest first. Source: `manual`, `answer`, `github` |
| POST | `/api/facts` | `text` (required, up to 2000 chars), `topic` (the role, company or project it is about) | `201 {"fact"}`, or `200 {"fact": null, "duplicate": true}` when the same text about the same topic is already there. Up to 500 facts |
| POST | `/api/facts/delete` | `id` | `{"deleted": true}`, `404` when not found |
| POST | `/api/facts/github` | `username` | `{"imported": n, "repos": [names]}`: up to 12 public, non-fork repositories with a description or stars, one fact each plus one with the start of the README |

| Route | Request fields | Response |
|---|---|---|
| `/alerts/subscribe` | `email`, `jobTitle` (both required), `location`, `sector`, `keywords`, `resumeSummary`, `frequency` (`instant` 30 min, `hourly`, `daily`; anything else is `daily`) | `{"subscription", "smtp_configured"}`. Stored in `alerts.json`. If SMTP is set, sends a confirmation and starts a scan (unless one is running). |
| `/alerts/unsubscribe` | `id` | `{"removed": bool}` |
| `/alerts/test` | `email` | `200 {"ok": true, "msg": "sent"}`, or `502 {"ok": false, "msg", "error"}` when sending failed (SMTP not set, refused, unreachable) |
| `/alerts/scan` | none | `{"started": bool}`: `false` when a scan is already running. The scan runs in the background. |
| `/config/smtp` | `host`, `port` (587, clamped 1-65535), `user`, `password`, `from_addr` | Merges `SMTP_*` into `config.json` (atomic write). `{"saved": true, "smtp_configured"}` |
| `/config/smtp/test` | `host`, `port`, `user`, `password` | Sends a test mail to `user` without saving. `200 {"ok": true, "msg"}`; `400 {"ok": false, "msg", "error"}` if user or password is missing; `502 {"ok": false, "msg", "error"}` when the SMTP server fails |
| `/inbox/scan` | `user`, `password` (IMAP app password) (required), `host` (`imap.gmail.com`), `days` (30, clamped 1-365) | Reads the 60 most recent inbox emails from the last `days` and has `MODEL_FAST` classify every one, in batches of 20 (`applied`, `interview_invite`, `interview_followup`, `offer`, `rejected`, `recruiter_outreach`, `ghosted`, `not_relevant`). `{"count", "rows": [{from, subject, date, status, company, role, confidence}], "scanned"}`; `not_relevant` ones are dropped. No emails: `{"count": 0, "rows": [], "scanned": 0, "msg"}`. The inbox could not be read (unreachable, login refused, IMAP error): `502 {"error"}` saying why. The classification failed: `502 {"error": "Could not classify the emails: ..."}`. |

Locally a background thread runs an alert scan every 15 minutes. Only one scan runs at a
time (the loop, `/alerts/subscribe` and `/alerts/scan` share a lock).

---

## Local data API (`/api/*`)

The job pipeline, backed by `apex_store` (SQLite). Every call is scoped to the caller's
`owner` (`''` locally, the session's owner id when hosted). Another owner's row behaves
exactly like a missing one. No model calls. Bodies are limited to 2 MB like every POST.
Dates are UTC (`YYYY-MM-DD`; "today" is the UTC date).

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/api/applications` | | `{"applications": [...], "summary": {...}}` |
| GET | `/api/application` | `?id=` | `{"application": {..., "events": [...], "artifacts": [...]}}` |
| GET | `/api/scores/latest` | `?jobTitle=` (case-insensitive) | `{"score": {id, job_title, sector, score_before, score_after, keywords: [{name, pct}], created_at} or null}` |
| POST | `/api/applications` | application fields | `201 {"application", "created": true}`, or `200 {..., "created": false}` when an identical company + role + url already exists |
| POST | `/api/applications/update` | `id` + any of `status`, `notes`, `next_action_on`, `applied_on`, `url`, `location`, `company`, `role` | `{"application"}` |
| POST | `/api/applications/delete` | `id` | `{"deleted": true}` (its events and artifacts go with it) |
| POST | `/api/applications/import` | `items` (array, first 1000 used), `source` (`import` or `gmail`) | `{"created", "duplicates", "skipped": [{index, error}]}` |
| POST | `/api/applications/artifact` | `id`, `kind`, `content` | `201 {"artifact_id"}` |
| POST | `/api/applications/followup-sent` | `id` | `{"application"}` with `next_action_on` = today + 7 days |

Application fields and rules:

| Field | Rule |
|---|---|
| `company`, `role` | Required, at most 200 characters. |
| `status` | `saved`, `applied`, `interview`, `offer`, `rejected`, `withdrawn`. Default `applied`. Leaving `saved` sets `applied_on` to today if it is empty. |
| `url` | Optional, must start with `http://` or `https://`, at most 2000 characters. |
| `location` | At most 200 characters. |
| `notes` | At most 20 000 characters. |
| `applied_on` (alias `date` on create), `next_action_on` | `YYYY-MM-DD`. |
| `source` (create only) | `manual` (default), `tailor`, `gmail`, `jobs`, `import`. |
| Artifact `kind` | `tailored_resume`, `cover_letter`, `followup`, `outreach`, `note`. Content non-empty, at most 200 000 characters. At most 50 per application. |
| Limits | 2000 applications per owner; 20 MB of notes and artifact content per owner; the newest 200 score records per owner are kept. |

Returned applications also carry `followup_due` (bool: `applied` or `interview` with a
`next_action_on` that is today or past, or, without one, applied 7 or more days ago) and,
in lists, `artifact_count`. `summary` is `{total, by_status, sent, response_rate, followups_due}`.

Errors: validation failures are `400 {"error": "..."}`; a missing id is
`404 {"error": "application not found"}`; an unexpected failure is
`500 {"error": "internal error (<Type>); see the server window"}`; unknown `/api/` paths are `404`.

---

## SSE event reference

Every event is `{"type": ..., ...}`. Payloads holding model output are the model's JSON
as parsed; fields can be missing when the model leaves them out.

| Type | Sent by | Fields |
|---|---|---|
| `log` | all streams | `msg`: human-readable progress line |
| `step` | `/analyze`, `/tailor`, `/match`, `/xray` | `id` (`market`, `heat`, `analyze`, `rewrite`, `report`; `/tailor` uses `analyze` and `rewrite`, `/match` and `/xray` `analyze`), `status` (`running`, `done`), `msg` |
| `notice` | `/analyze`, `/tailor` | `level` (`warn`: the engine found no summary or bullets it could edit, and the resume is unchanged; `info`: the judge scored the rewrite below the original, so the original was kept), `msg` |
| `jobs_data` | `/analyze` | `jobs: [{source, text, query}]` (up to 4 raw listing snippets per source, 30 in all), `query`, `sector` |
| `market_data` | `/analyze` (twice) | `data`: see below |
| `engine_data` | `/analyze`, `/engine/answer` | `data`: see below; `/engine/answer` adds `answers` |
| `resume_data` | `/analyze` | `original`, `optimized` (engine output), `added: []` |
| `report_data` | `/analyze` | `data`: `{changes: [{before, after, why}], recommendations, sectorInsights, nextSteps, hardSkillsGap, softSkillsGap, atsScoreBefore, atsScoreAfter, recruiterScoreBefore, recruiterScoreAfter, scrape_info, baselineKeywords: [{name, pct}]}` (`baselineKeywords`: the run's top 30 requirements, stored as the drift baseline) |
| `cover_letter_data` | `/analyze` | `letter` and `verified: true`; or `letter: ""` and `withheld: [problems]` when it could not be verified |
| `interview_data` | `/analyze` | `data`: `{behavioral, technical, situational: [{q, a, tip, a_withheld?}], questions_to_ask, salary_negotiation, red_flags_to_address, verified: true}`. Every sample answer `a` is fact-checked; a withheld one is `null` with its reasons in `a_withheld` |
| `linkedin_data` | `/analyze` | `data`: `{headline, about, skills, experience_bullets, featured_tips, connection_strategy, withheld}`. Headline, About and experience bullets are fact-checked (a withheld one is `""` or dropped; reasons in `withheld`); skills the resume does not show are dropped |
| `outreach_data` | `/analyze` | `data`: `{linkedin_dm, cold_email, referral_request, thank_you_note, negotiation_script, tips, withheld}`, `company`. Every message body is fact-checked; a withheld one is `""` |
| `velocity_data` | `/analyze`, `/velocity` | `data`: `{velocity_score, trajectory, next_level_title, years_to_next_level, market_position, market_position_note, acceleration_moves, 10_year_projection, peer_comparison}`; `/velocity` adds `velocity_factors` and `risk_factors` |
| `tab_skipped` | `/analyze` | `tab` (`cover_letter`, `interview`, `linkedin`, `outreach`, `velocity`), `reason`: the tab failed (`Could not be generated: ...`) or was still running 90 seconds after the report and was stopped |
| `cost_data` | `/analyze`, `/engine/answer`, `/tailor` | `data`: `{mode, calls, est_usd, est_cents, tokens_in, tokens_out, measured: true}`, measured from real token usage of this request |
| `tailor_data` | `/tailor` | `data`: `{tailored_resume, verified: true, match_score_before, match_score_after, company_name, role_title, key_requirements, top_matches, gaps, keywords_injected, sections_reordered (bool), tailoring_notes, changes, rejected, questions}`; `changes` / `rejected` / `questions` as in `engine_data` |
| `bullet_data` | `/bullets` | `data`: `{ranked_bullets: [{text, score, rank, strengths, weaknesses, rewrite, rewrite_withheld?, ask}], top_fixes, average_score, strongest_bullet, weakest_bullet, overall_verdict}`. `ask`: the question whose answer would make that bullet strongest; `top_fixes`: the 3 changes that matter most (advice, not claims) |
| `negotiate_data` | `/negotiate` | `data`: `{target_salary, minimum_acceptable, opening_ask, rationale, your_leverage, your_leverage_withheld, market_evidence, premium_skills_value, negotiation_script: {opening_line, counter_script, if_they_push_back, closing_line}, red_flags, equity_considerations, timing_advice, benefits_to_negotiate, estimate_basis: "postings"\|"model_estimate", basis_note, posted_pay?: {n, p25, median, p75}}`. `your_leverage` keeps only points that passed the fact check; `your_leverage_withheld` lists the reasons for the rest (up to 6) |
| `bridge_data` | `/bridge` | `data`: `{transition_score, transition_verdict, skill_translations, hidden_strengths, experience_reframes: [{original_bullet, reframed_bullet, why, reframed_bullet_withheld?}], gaps_to_address, quick_wins, narrative, narrative_withheld?, interview_bridge_answers: [{question, answer, answer_withheld?}]}` |
| `followup_data` | `/followup` | `data`: `{week_1_email, week_2_email, linkedin_note, value_add, when_to_give_up, personalization_tips, withheld: {week_1?, week_2?, linkedin_note?: [problems]}}`, `company`. The two email bodies and the LinkedIn note are fact-checked; a withheld one is `""` |
| `match_data` | `/match` | `data`: `{match_pct, should_apply, apply_confidence, verdict, matching_keywords, missing_critical, missing_nice, quick_fixes: [{add_to_resume, where, impact, shown_on_resume}], quick_fixes_note, red_flags, green_flags, estimated_competition, role_title_extracted, company_extracted}`. `shown_on_resume`: the phrase already appears in the resume (whole-word match); the others are things to add only if true |
| `xray_data` | `/xray` | `data`: `{killer_bullets: [{quote, problem, fix, impact, fix_withheld?}], summary_verdict, first_impression_score, first_impression_note, biggest_missed_opportunity, generic_phrases, strong_elements, formatting_score, formatting_notes}` |
| `answer_grade` | `/grade-answer` | `data`: `{score, grade, verdict, strengths, weaknesses, ideal_answer_structure, follow_up_questions, better_version, better_version_withheld?, keywords_used, keywords_missed, coaching_tip}`, `question`. `better_version` is `null` when withheld |
| `drift_data` | `/drift` | `data`: `{current_score, baseline_score, drift, drifted, new_keywords, faded_keywords, verdict, urgency, basis, postings}`, `role`. `drifted` when the score moved 3 or more; `urgency` `high` at -10 or worse, `medium` below -2, else `low`; `postings`: how many relevant postings were counted |
| `error` | all streams | `msg` |
| `done` | all streams except `/grade-answer` | `msg`: one-line summary |

### `market_data.data`

| Field | Meaning |
|---|---|
| `frequency` | Up to 30 requirements: `{name, kind, pct, freq, in_posting}`. `pct` (= `freq`) is the measured share of filtered postings that mention it (whole words), or `null` when fewer than 8 postings were found. `in_posting`: present in `jobDesc`. |
| `hot`, `warm`, `cold` | `pct >= 25` or in the posting / 10-24 / under 10. |
| `hard_skills`, `soft_skills`, `emerging`, `salary_skills` | Subsets and model-named extras. |
| `measured`, `validation_note` | Whether percentages are real, and how they were computed. |
| `confidence`, `confidence_pct`, `total_jobs_analyzed`, `sector`, `scrape_info` | Data quality from the harvest. |
| `supported`, `unsupported` | Requirements the resume demonstrates / does not (gaps, never added). |
| `atsScoreBefore`, `atsScoreAfter`, `scoreBreakdownBefore`, `scoreBreakdownAfter` | Deterministic keyword-match score (0-100). Blind to writing quality. |
| `recruiterScoreBefore`, `recruiterScoreAfter`, `editsVerified`, `editsReverted` | Second emission only: the hiring-manager judge's averaged scores and edit counts. |

### `engine_data.data`

| Field | Meaning |
|---|---|
| `changes` | Verified edits: `{id, kind, section, group, before, after: [lines], why, keywords}`. `kind` is `summary`, `bullet` or `skills` (a reordered Skills line). |
| `rejected` | Edits that failed verification twice and were reverted: `{id, line, why: [problems]}`. |
| `questions` | Up to 8 `{id, question, line}`: facts the candidate could supply. |
| `problems`, `strengths`, `summary_verdict` | Recruiter diagnosis of the document. |
| `order`, `section_order` | Proposed bullet order per role and section order, kept separate from wording. |
| `score` | Judge result `{before, after, verdict, after_weakest, better}`, plus `truncated: true` when a version was longer than the 40,000 characters the judge reads; or `null`. |
| `line_scores` | `{id: average rubric score 1-5}`. |
| `final` | The assembled resume with all verified edits and orders applied (the original when vetoed). |
| `note` | Set when the engine found no summary or bullets to edit: why, and how to fix the resume's layout. |
| `veto`, `vetoed_changes` | Set when the judge scored the rewrite below the original: `veto` is `{before, after, why}`; the edits move from `changes` to `vetoed_changes`, and `final` is the original. |
| `summary_created` | `true` when the resume had no summary and the engine wrote one (inserted before the first section). |
| `revised` | `/engine/answer` only: the ids rewritten with answers. |
| `truncated` | Reserved; currently always `null` (the judge's flag is `score.truncated`). |
| `sig` | Signature of `target`; send it back to `/engine/answer`. |
| `original` | The input resume; send it back to `/engine/render` and `/engine/answer`. |
| `target` | `{title, seniority, sector, job_desc, keywords, supported, unsupported}`; send it back to `/engine/answer`. |
