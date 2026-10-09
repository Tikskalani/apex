# API Reference

Everything here is served by `agent_server.py` (Python stdlib `ThreadingHTTPServer`).
This file describes the code as it is; if the two disagree, the code wins and this
file is out of date.

- [Reaching the server](#reaching-the-server)
- [Conventions](#conventions)
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

## Conventions

| Topic | Rule |
|---|---|
| Request bodies | JSON (`Content-Type: application/json`). A body that is not valid JSON gets `400 {"error": "Bad JSON: ..."}`. Exception: hosted-mode `POST /login` takes a form post. |
| JSON errors | `{"error": "message fit to show the user"}` with the HTTP status listed per route. |
| Unknown route | `404 {"error": "not found"}` |
| Query strings on POST | POST routes are matched on the full path including any query string, so `/analyze?x=1` is a 404. Only `/api/*` strips the query. |
| Size limits | `POST /login`: 4 KB. `/transcribe`: 25 MB of decoded audio. Store fields have their own limits (see `/api/*`). Other bodies are not capped. |
| SSE responses | `200`, `Content-Type: text/event-stream`, `Connection: close`. See below. |

### How SSE responses work

Streaming routes answer with one frame per event:

```
data: {"type": "log", "msg": "PHASE 3 — Relevance Filter"}

data: {"type": "market_data", "data": {...}}

```

- Every frame is a single `data:` line holding one JSON object with a `type` field.
  There are no `event:` or `id:` lines.
- The response has no `Content-Length`. **The server closes the connection to end the
  stream**; that close is the only end-of-stream signal. Clients must read until EOF.
- Validation failures happen before the stream starts and come back as an ordinary
  JSON error with a 4xx status.
- Once the stream has started, failures arrive as an `error` event inside the 200
  response. A stream normally ends with `done`; after an `error` it may simply end.
- Events may arrive from several server threads; each frame is written atomically.

## Security model

The server is reachable by every web page open in the user's browser, because any
page can send requests to `localhost`. The defences below assume that.

| Defence | What it does |
|---|---|
| `_guard` (every method, before any route runs) | Refuses with `403 {"error": ...}` when: the `Host` header is not `localhost:PORT`, `127.0.0.1:PORT`, `[::1]:PORT` (or `APEX_PUBLIC_HOST` when hosted), which blocks DNS rebinding; an `Origin` header is present and is not one of the server's own origins (`Origin: null` from `file://` gets a specific message); or `Sec-Fetch-Site: cross-site`, except a top-level navigation `GET /` or `/index.html`. Requests with no `Origin` header (curl, scripts, the test suite) pass the origin check. POSTs are refused before the body is read, so a `text/plain` POST that skips the CORS preflight is still blocked. |
| CORS | Never `*`. `Access-Control-Allow-Origin` echoes the request `Origin` only when it is one of the server's own origins (`http://localhost:PORT`, `http://127.0.0.1:PORT`, `http://[::1]:PORT`, or `https://APEX_PUBLIC_HOST`), with `Vary: Origin`. Allowed methods `GET, POST, OPTIONS`; allowed header `Content-Type`. `OPTIONS` runs the guard, then answers `204`. |
| Static files | Allowlist only. A path is served if and only if it matches `/<name>.<ext>` or `/assets/<name>.<ext>`, the name uses only `A-Z a-z 0-9 _ -` and dots between segments, and the extension is one of `css js png jpg jpeg webp svg ico woff2`. `config.json`, `*.py`, `*.db`, dotfiles and Windows aliases (`config.json.`, `x::$DATA`) never match. Anything else with a dot in the last segment is a 404. |
| CSP on `index.html` | A fresh random nonce per page load is added to every `<script` tag in the file. Policy: `default-src 'none'`; `script-src 'nonce-...'` plus `cdnjs.cloudflare.com` and `cdn.jsdelivr.net`; `worker-src blob:` plus cdnjs (pdf.js worker); `connect-src 'self'`; `frame-ancestors 'none'`; `object-src 'none'`; `base-uri 'none'`; `form-action 'self'`. Also `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, and `Strict-Transport-Security` when `APEX_PUBLIC_HOST` is set. Inline `on*=` handlers cannot run under this policy. |
| No key material | No response contains an API key or SMTP password. `GET /config` reports presence only (`JSEARCH_ACTIVE`, `SMTP_CONFIGURED`). Store rows never include their `owner` column. |

## Hosted demo mode

Off unless `APEX_ACCESS_CODE` is set. Local runs never see any of it.

| Item | Behaviour |
|---|---|
| Startup checks | Exits if `APEX_ACCESS_CODE` is set and `APEX_SESSION_SECRET` is shorter than 32 characters. Exits if `APEX_PUBLIC_HOST` is set, or `APEX_BIND` is not loopback, without an access code. |
| `GET /login` | Sign-in page (its own strict CSP). Only exists in hosted mode. |
| `POST /login` | Form field `code`, compared in constant time. Right code: `303` to `/` with a new session cookie. Wrong code: `401` page. 5 failures from one IP in 10 minutes: `429` page. Body over 4 KB: `413`. |
| `GET /logout` | `303` to `/login`, clears the cookie. |
| Session cookie | `apex_session=v1.<owner>.<expiry>.<HMAC-SHA256>`, signed with `APEX_SESSION_SECRET`. `HttpOnly; SameSite=Lax; Path=/`, plus `Secure` when `APEX_PUBLIC_HOST` is set. Valid 14 days. Each session gets a random `owner` id, and every store query filters by it, so visitors never see each other's data. |
| No valid session | `GET /` or `/index.html`: `303` to `/login`. Anything else: `401 {"error": "Your session has ended. Reload the page to sign in again.", "login": true}`. `/health`, `/login` and `/logout` need no session. |
| AI budget | Each AI-backed POST route costs units (table below), charged before the body is read. Over the per-visitor hourly budget (`APEX_VISITOR_BUDGET`, default 40, held in memory) or the shared UTC-day budget (`APEX_DAILY_BUDGET`, default 300, persisted in `apex.db` so a restart cannot reset it): `429 {"error": "..."}`. |
| Disabled routes | `403 {"error": "This feature is turned off in the online demo. Run APEX locally to use it."}` for `/config/smtp`, `/config/smtp/test`, `/alerts/subscribe`, `/alerts/unsubscribe`, `/alerts/test`, `/alerts/scan`, `/alerts/list`, `/inbox/scan`. The job-alert background loop does not run. |
| `/health` | Skips only the Host check (platform health checks use an internal Host). Origin and Sec-Fetch-Site rules still apply. |
| Client IP | `APEX_TRUST_PROXY=1` takes it from `Fly-Client-IP`, else the first `X-Forwarded-For` entry; otherwise the socket address. Used for login throttling only. |

Cost units per route (`AI_COSTS`):

| Units | Routes |
|---|---|
| 10 | `/analyze` |
| 6 | `/engine/answer` |
| 2 | `/tailor`, `/apply-all-recommendations`, `/transcribe` |
| 1 | `/bullets`, `/negotiate`, `/bridge`, `/followup`, `/drift`, `/match`, `/xray`, `/grade-answer`, `/velocity`, `/draft-cover-letter`, `/parse-resume` |
| 0 | everything else (`/api/*`, `/engine/render`, `/render-resume`, `/live-jobs`, ...) |

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
| `MODEL_FAST` | Model for extraction (Phase 4 requirement proposal). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` | Optional, job-alert email only. Default host `smtp.gmail.com`, port `587`. `POST /config/smtp` writes these into `config.json`. |

At least one of `OPENAI_KEY` / `ANTHROPIC_KEY` is required or the server exits at startup.

The four key names above (`OPENAI_KEY`, `ANTHROPIC_KEY`, `ANTHROPIC_WORKSPACE_ID`,
`JSEARCH_KEY`) are matched tolerantly: case, punctuation and the word `API` are ignored,
so `Anthropic_API-Key` and `anthropic api key` both work. For these keys `config.json`
wins over the environment. `MODEL`, `MODEL_FAST` and the `SMTP_*` keys are read by their
exact names.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `APEX_PORT` | `7842` | Listen port. |
| `APEX_MODEL` | see below | Overrides `MODEL` in `config.json`. |
| `APEX_MODEL_FAST` | see below | Overrides `MODEL_FAST` in `config.json`. |
| `APEX_DB` | `apex.db` beside the server | SQLite file path. |
| `APEX_OPENAI_BASE` | `https://api.openai.com` | OpenAI base URL (the tests point it at an offline stub). |
| `APEX_ANTHROPIC_BASE` | SDK default | Anthropic base URL (tests). When set, server-side fallback is not requested. |
| `APEX_ACCESS_CODE` | unset | Turns on hosted mode. |
| `APEX_SESSION_SECRET` | unset | Signs session cookies; at least 32 characters when hosted. |
| `APEX_PUBLIC_HOST` | unset | Public hostname, e.g. `apex-demo.fly.dev`. Added to allowed Host/Origin; enables `Secure` cookies and HSTS. |
| `APEX_BIND` | loopback | Bind address (`0.0.0.0` inside a container). Non-loopback requires hosted mode. |
| `APEX_TRUST_PROXY` | unset | `1` to trust `Fly-Client-IP` / `X-Forwarded-For`. |
| `APEX_VISITOR_BUDGET` | `40` | Cost units per visitor per hour. |
| `APEX_DAILY_BUDGET` | `300` | Cost units for all visitors per UTC day. |

### Model selection

Order of precedence: `APEX_MODEL` env, then `config.json` `MODEL`, then the default.

| Keys present | `MODEL` default | `MODEL_FAST` default |
|---|---|---|
| Anthropic only | `claude-opus-5-5` | `claude-haiku-5-5` |
| OpenAI (with or without Anthropic) | `gpt-4o` | same as the resolved `MODEL` |

Routing is by prefix: `claude-...` goes to Anthropic through the official `anthropic` SDK,
anything else to OpenAI `/v1/chat/completions`. A model whose provider key is missing
fails at call time with a message naming the missing key. `config.example.json` suggests
`gpt-6.1-sol` / `gpt-6-luna`; use `tools/benchmark.py` to choose on your own resumes.

---

## GET routes

| Path | Query | Response |
|---|---|---|
| `/`, `/index.html` | | `index.html` with a per-load CSP nonce. Hosted without a session: `303 /login`. |
| `/<file>.<ext>`, `/assets/<file>.<ext>` | | Allowlisted static file, or `404`. |
| `/health` | | `{"status": "ok", "version": "10.0", "jsearch": "active"\|"inactive", "sectors": [...], "templates": [...]}` |
| `/config` | | `{"JSEARCH_ACTIVE": bool, "HOSTED": bool, "SMTP_CONFIGURED": bool}` (presence only, never key values) |
| `/templates` | | `{"templates": [{"id", "name", "desc"}]}` for `modern`, `classic`, `tech`, `executive`, `creative`, `minimal` |
| `/cities` | | `{"cities": ["Austin, TX", ...], "extras": ["Remote", "Anywhere", "AL", ...]}` |
| `/live-jobs` | `q` (required), `location`, `limit` (default 40) | `{"jobs": [...], "count", "query", "parsed_location", "requested_location"}`; `400` if `q` is missing. Job: `{title, company, location, url, source, posted, snippet, salary}`. No model call. |
| `/render-resume` | `template` (default `modern`), `data` = base64url of a resume struct JSON | `text/html` rendering of that template. |
| `/alerts/list` | `email` (optional filter) | `{"subscriptions": [...]}`. Local only. |
| `/api/applications`, `/api/application`, `/api/scores/latest` | | See [Local data API](#local-data-api-api). |
| `/login`, `/logout` | | Hosted mode only (see above). |

## POST routes that stream (SSE)

All of these call the model. Each lists its request fields, the events it emits beyond
`log` and `step`, and what ends it. Missing optional fields fall back to the default shown.

### `POST /analyze`

The full run. See ARCHITECTURE.md for what each phase does.

| Field | Required | Default | Notes |
|---|---|---|---|
| `jobTitle` | yes | | Empty: `400 {"error": "Enter a target job title."}` |
| `resume` | yes | | Under 100 characters after trimming: `400 {"error": "Resume too short (...)"}` |
| `seniority` | | `senior` | |
| `jobDesc` | | `""` | A target posting. Highest-priority signal for requirements and rewriting. |
| `industry` | | `general` | Stored with the score record. The run's sector comes from the model's Phase 0 classification. |
| `mode` | | `optimize` | Echoed in logs and `cost_data` only. |

Events, in roughly this order: `log`, `step` (ids `market`, `heat`, `analyze`, `rewrite`,
`report`), `jobs_data`, `market_data` (after Phase 5), the Phase 8 events in whatever
order they finish (`cover_letter_data`, `interview_data`, `linkedin_data`,
`outreach_data`, `velocity_data`), `market_data` again (now with after-scores),
`engine_data`, `resume_data`, `report_data`, `cost_data`, `done`.
When `report_data` is sent, the server also writes the before/after keyword score to
`score_history` (the baseline for `/drift`). An uncaught failure sends `error` and ends
the stream; a failing Phase 8 generator only logs.

### `POST /engine/answer`

Re-runs the Evidence Engine with the candidate's answers to its questions as new evidence.

| Field | Required | Notes |
|---|---|---|
| `resume` | yes | The original resume (`engine_data.data.original`), at least 100 characters. |
| `target` | yes | `engine_data.data.target`; must contain `title`. Missing either: `400 {"error": "Run the agent first, then answer the questions."}` |
| `answers` | yes | `{"B3": "about 40 clinics", ...}` keyed by block id. All empty: `400 {"error": "Answer at least one question."}` Each answer is cut to 500 characters. |

Events: `log`, `engine_data` (`{"data": ..., "answers": {...}}`), `cost_data`, `done`; or `error`.

### Single-tool streams

| Route | Request fields (default) | Data event | Ends with |
|---|---|---|---|
| `/tailor` | `jobPosting`, `resume`, `jobTitle`, `sector` (`general`) | `tailor_data` | `done` / `error` |
| `/bullets` | `resume`, `jobTitle`, `sector` (`general`), `keywords` (array of strings) | `bullet_data` | `done` / `error` |
| `/negotiate` | `jobTitle`, `sector` (`general`), `seniority` (`senior`), `location`, `resume`, `marketData` (object; reads `salaryByLocation`, `salary_skills`) | `negotiate_data` | `done` / `error` |
| `/bridge` | `fromRole`, `toRole`, `resume`, `sector` (`general`) | `bridge_data` | `done` / `error` |
| `/followup` | `company`, `role`, `daysSince` (7), `resumeSummary` | `followup_data` (also has `company`) | `done` / `error` |
| `/match` | `jobPosting`, `resume` | `match_data` | `done` / `error` |
| `/xray` | `jobTitle`, `sector` (`general`), `resume`, `keywords` | `xray_data` | `done` / `error` |
| `/grade-answer` | `question`, `answer`, `jobTitle`, `sector` (`general`) | `answer_grade` (also has `question`) | `answer_grade` or `error`; no `done` |
| `/velocity` | `jobTitle`, `sector` (`general`), `seniority` (`senior`), `resume` | `velocity_data` | `done` / `error` |
| `/drift` | `jobTitle` (required), `resume` (required, 100+ chars), `baselineScore`, `sector` (`general`) | `drift_data` (also has `role`) | `done` / `error` |

Notes:

- These routes do not validate their fields (except `/drift`); empty input reaches the model.
- `/tailor` returns a whole rewritten resume (`tailored_resume`) plus model-estimated
  `match_score_before` / `match_score_after`. `/bullets` returns model rewrites of weak bullets.
  **Neither goes through the Evidence Engine's verification.** Treat their text as suggestions.
- `/drift`: without `baselineScore`, the baseline is the latest `score_after` stored for that
  job title by `/analyze`. None stored: `400` asking you to run the agent first. Short resume:
  `400 {"error": "Paste your resume in Launch first."}`. It re-scrapes postings and asks the
  model for a `current_score`; the server computes `drift = current_score - baseline_score`
  itself and clamps the other fields.
- `/velocity` has no button of its own in the page; `/analyze` Phase 8 fills that view.

## POST routes that return JSON

| Route | Request fields | Success response | Errors |
|---|---|---|---|
| `/engine/render` | `resume` (the original), `edits` `{id: [lines]}` (at most 3 lines per id; unknown ids ignored), `order` `[[ids of one role]]`, `section_order` `[header names]` | `{"text": "..."}` | `400 {"error"}` |
| `/parse-resume` | `resume` | `{"struct": {...}}` (name, title, authorization, contact fields, summary, experience, education, skills, certifications, projects, languages, awards, additional) | `500 {"error"}` |
| `/render-resume` | `template` (default `modern`), `struct`, or `resume` (parsed by the model first if no `struct`) | `{"html", "template", "struct"}` | `500 {"error"}` |
| `/draft-cover-letter` | `resume` (required), `jobTitle`, `company`, `posting`, `sector` | `{"letter", "jobTitle", "company"}` | `400` no resume; `500 {"error", "letter": ""}` |
| `/transcribe` | `audio_b64`, `mime` (default `audio/webm`) | `{"text": "..."}` (OpenAI `whisper-1`) | `400` no OpenAI key or no audio; `413` over 25 MB; `500 {"error", "text": ""}` |
| `/live-jobs` | `q` (required), `location`, `limit` (40), `resume`, `minScore` | As GET `/live-jobs`; with `resume`, each job gains `match_score` (0-100, local keyword overlap, no model call) and `shared_keywords`, and jobs under `minScore` are dropped | `400` no `q`; `500` |
| `/apply-all-recommendations` | `optimized` or `original`, `changes`, `bulletRewrites`, `addedKeywords`, `sector`, `jobTitle` | `{"merged", "applied": {"rewrites", "changes", "keywords"}}` | `400` no resume; `500 {"error", "merged"}` |

`/engine/render` makes no model call. It reassembles the original resume with the edits
the user kept; unchanged lines come out byte-identical. It does not re-verify edit text:
the page sends back edits it received in `engine_data`.

`/apply-all-recommendations` is legacy. It asks the model to merge rewrites and keywords
into a whole new resume with no verification, and the page no longer calls it.

### Local-only routes (403 in hosted mode)

| Route | Request fields | Response |
|---|---|---|
| `/alerts/subscribe` | `email`, `jobTitle` (both required), `location`, `sector`, `keywords`, `resumeSummary`, `frequency` (`instant` 30 min, `hourly`, `daily`) | `{"subscription", "smtp_configured"}`. Stored in `alerts.json`. Sends a confirmation and starts a scan if SMTP is set. |
| `/alerts/unsubscribe` | `id` | `{"removed": bool}` |
| `/alerts/test` | `email` | `200 {"ok": true, "msg"}` or `500 {"ok": false, "msg"}` |
| `/alerts/scan` | none | `{"started": true}` (scan runs in the background) |
| `/config/smtp` | `host`, `port`, `user`, `password`, `from_addr` | Writes `SMTP_*` into `config.json`. `{"saved": true, "smtp_configured"}` |
| `/config/smtp/test` | `host`, `port`, `user`, `password` | Sends a test mail to `user` without saving. `{"ok", "msg"}` (200 even on SMTP failure; 400 if user/password missing) |
| `/inbox/scan` | `user`, `password` (IMAP app password), `host` (`imap.gmail.com`), `days` (30) | `{"count", "rows": [{from, subject, date, status, company, role, confidence}], "scanned"}`. The model classifies each email; irrelevant ones are dropped. |

Locally a background thread checks alert subscriptions every 15 minutes.

---

## Local data API (`/api/*`)

The job pipeline, backed by `apex_store` (SQLite). Every call is scoped to the caller's
`owner` (`''` locally, the session's owner id when hosted). Another owner's row behaves
exactly like a missing one. No model calls.

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/api/applications` | | `{"applications": [...], "summary": {...}}` |
| GET | `/api/application` | `?id=` | `{"application": {..., "events": [...], "artifacts": [...]}}` |
| GET | `/api/scores/latest` | `?jobTitle=` (case-insensitive) | `{"score": {id, job_title, sector, score_before, score_after, created_at} or null}` |
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
| Artifact `kind` | `tailored_resume`, `cover_letter`, `followup`, `outreach`, `note`. Content non-empty, at most 200 000 characters. |
| Limit | 2000 applications per owner. |

Returned applications also carry `followup_due` (bool) and, in lists, `artifact_count`.
`summary` is `{total, by_status, sent, response_rate, followups_due}`.

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
| `step` | `/analyze`, `/tailor`, `/match`, `/xray` | `id` (`market`, `heat`, `analyze`, `rewrite`, `report`), `status` (`running`, `done`), `msg` |
| `jobs_data` | `/analyze` | `jobs: [{source, text, query}]` (up to 30 raw listing snippets), `query`, `sector` |
| `market_data` | `/analyze` (twice) | `data`: see below |
| `engine_data` | `/analyze`, `/engine/answer` | `data`: see below; `/engine/answer` adds `answers` |
| `resume_data` | `/analyze` | `original`, `optimized` (engine output), `added: []` |
| `report_data` | `/analyze` | `data`: `{changes: [{before, after, why}], recommendations, sectorInsights, nextSteps, hardSkillsGap, softSkillsGap, atsScoreBefore, atsScoreAfter, recruiterScoreBefore, recruiterScoreAfter, scrape_info}` |
| `cover_letter_data` | `/analyze` | `letter` |
| `interview_data` | `/analyze` | `data`: `{behavioral, technical, situational: [{q, a, tip}], questions_to_ask, salary_negotiation, red_flags_to_address}` |
| `linkedin_data` | `/analyze` | `data`: `{headline, about, skills, experience_bullets, featured_tips, connection_strategy}` |
| `outreach_data` | `/analyze` | `data`: `{linkedin_dm, cold_email, referral_request, thank_you_note, negotiation_script, tips}`, `company` |
| `velocity_data` | `/analyze`, `/velocity` | `data`: `{velocity_score, trajectory, next_level_title, years_to_next_level, market_position, market_position_note, acceleration_moves, 10_year_projection, peer_comparison, ...}` |
| `cost_data` | `/analyze`, `/engine/answer` | `data`: `{mode, calls, est_usd, est_cents, tokens_in, tokens_out, measured: true}`, measured from real token usage of this request |
| `tailor_data` | `/tailor` | `data`: `{tailored_resume, match_score_before, match_score_after, keywords_injected, sections_reordered, top_matches, gaps_addressed, company_name, role_title, key_requirements, tailoring_notes}` |
| `bullet_data` | `/bullets` | `data`: `{ranked_bullets: [{text, score, rank, strengths, weaknesses, rewrite}], average_score, strongest_bullet, weakest_bullet, overall_verdict}` |
| `negotiate_data` | `/negotiate` | `data`: `{target_salary, minimum_acceptable, opening_ask, rationale, your_leverage, market_evidence, premium_skills_value, negotiation_script: {opening_line, counter_script, if_they_push_back, closing_line}, red_flags, equity_considerations, timing_advice, benefits_to_negotiate}` |
| `bridge_data` | `/bridge` | `data`: `{transition_score, transition_verdict, skill_translations, hidden_strengths, experience_reframes, gaps_to_address, quick_wins, narrative, interview_bridge_answers}` |
| `followup_data` | `/followup` | `data`: `{week_1_email, week_2_email, linkedin_note, value_add, when_to_give_up, personalization_tips}`, `company` |
| `match_data` | `/match` | `data`: `{match_pct, should_apply, apply_confidence, verdict, matching_keywords, missing_critical, missing_nice, quick_fixes, red_flags, green_flags, estimated_competition, role_title_extracted, company_extracted}` |
| `xray_data` | `/xray` | `data`: `{killer_bullets: [{quote, problem, fix, impact}], summary_verdict, first_impression_score, first_impression_note, biggest_missed_opportunity, generic_phrases, strong_elements, formatting_score, formatting_notes}` |
| `answer_grade` | `/grade-answer` | `data`: `{score, grade, verdict, strengths, weaknesses, ideal_answer_structure, better_version, keywords_used, keywords_missed, coaching_tip}`, `question` |
| `drift_data` | `/drift` | `data`: `{current_score, baseline_score, drift, drifted, new_keywords, faded_keywords, verdict, urgency}`, `role` |
| `error` | all streams | `msg` |
| `done` | all streams except `/grade-answer` | `msg`: one-line summary |

### `market_data.data`

| Field | Meaning |
|---|---|
| `frequency` | Up to 30 requirements: `{name, kind, pct, freq, in_posting}`. `pct` (= `freq`) is the measured share of filtered postings that mention it, or `null` when fewer than 8 postings were found. `in_posting`: present in `jobDesc`. |
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
| `changes` | Verified edits: `{id, kind, section, group, before, after: [lines], why, keywords}`. |
| `rejected` | Edits that failed verification twice and were reverted: `{id, line, why: [problems]}`. |
| `questions` | Up to 8 `{id, question, line}`: facts the candidate could supply. |
| `problems`, `strengths`, `summary_verdict` | Recruiter diagnosis of the document. |
| `order`, `section_order` | Proposed bullet order per role and section order, kept separate from wording. |
| `score` | Judge result `{before, after, verdict, after_weakest, better}`, or `null`. |
| `line_scores` | `{id: average rubric score 1-5}`. |
| `final` | The assembled resume with all verified edits and orders applied. |
| `original` | The input resume; send it back to `/engine/render` and `/engine/answer`. |
| `target` | `{title, seniority, sector, job_desc, keywords, supported, unsupported}`; send it back to `/engine/answer`. |
