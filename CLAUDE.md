# APEX v11

Local resume-optimization and job-search agent app. Single developer, runs locally on Windows from the project folder.

## Architecture (verified against the code 2026-10-11)

- **Frontend:** `index.html` — single file, vanilla JS, no build step.
  19 views on the left icon rail (`data-view` → tooltip):
  `home` Home · `market` Market Intel · `resume` Resume X-Ray · `gap` Gap Report ·
  `templates` PDF Templates · `jobs` Live Jobs · `alerts` Job Alerts ·
  `cl` Cover Letter · `iv` Interview · `linkedin` LinkedIn · `outreach` Outreach ·
  `velocity` Velocity · `bullets` Bullets · `tailor` Tailor · `match` Match ·
  `weakness` Weakness X-Ray · `negotiate` Negotiate · `bridge` Career Bridge ·
  `tracker` Tracker (the job pipeline).
  All clickable controls use `data-action` / `data-arg`, routed by one
  delegated listener (`ACTIONS` in index.html). Inline `on*=` handlers are
  forbidden by the CSP and a test fails if one appears.
  "Launch" is not a tab: it is the drawer opened by the **Launch** button top right
  (`#open-drawer`).
- **Backend:** `agent_server.py` — Python stdlib (`http.server`
  `ThreadingHTTPServer` + `BaseHTTPRequestHandler`, capped at 64 concurrent
  requests). One package: `anthropic` (pinned in requirements.txt), imported
  only for Claude models. Binds 127.0.0.1 and ::1 on port 7842. Serves
  `index.html` at `/` so page and API share one origin, with a strict CSP
  (per-load nonce + `'strict-dynamic'`). Calls the model (Claude or OpenAI) and
  scrapes live job postings from free JSON APIs (Remotive, Arbeitnow, Jobicy,
  RemoteOK, Himalayas, The Muse by category, Greenhouse and Lever boards, HN
  "Who is hiring"); JSearch, USAJobs and Findwork only with their keys.
- **Engine:** `apex_engine.py` — the Evidence Engine (below). Pure functions
  over an injected `llm` callable, so tests drive it with stubs.
- **Storage:** `apex_store.py` (stdlib sqlite3) → `apex.db` beside the server
  (gitignored; override with `APEX_DB`). Applications (saved → applied →
  interview → offer / rejected / withdrawn), an append-only event timeline,
  artifacts (apply kit: tailored resume, cover letter, follow-ups), and score
  history (every `/analyze` run's keyword score AND its requirement list: the
  drift baseline). Validation lives in the store (`StoreError` → HTTP 400).
  Every call opens and closes its own connection (`_db()`); dates are UTC.
- **Vendor libs** pinned by version and SRI hash (`integrity="sha384-…"`),
  loaded on first use: pdf.js 3.11.174, mammoth 1.6.0, jsPDF 2.5.1 (registers
  as `window.jspdf`) from cdnjs; docx 8.5.0 from jsDelivr
  (`cdn.jsdelivr.net/npm/docx@8.5.0/build/index.umd.js`) because cdnjs does
  not carry docx. Bumping a version means recomputing its hash. Noto Sans
  (`assets/*.ttf`, OFL) is embedded in PDFs so non-Latin names survive.
- **Keys:** `config.json` beside the server (`ANTHROPIC_KEY` and/or
  `OPENAI_KEY`, optional `ANTHROPIC_WORKSPACE_ID`, `JSEARCH_KEY`, `SMTP_*`,
  `MODEL`, `MODEL_FAST`, `MODEL_AUDIT`, `MODEL_JUDGE`), falling back to env
  vars `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `JSEARCH_API_KEY`
  (`USAJOBS_API_KEY` + `USAJOBS_EMAIL`, `FINDWORK_API_KEY` are env only).
  Key names are matched leniently (case, dashes, "API" optional).
  `config.json` is gitignored. There is no `.env`. With no model key the
  server still starts and the page shows how to add one (`AI_PROBLEM`).

## Hard rules

1. **Serve the frontend over HTTP. Never open it as `file://`.**
   Open `http://localhost:7842/`. The server already serves `index.html`.

2. **PDF export must produce a real text layer.** Every PDF button goes through
   `atsExport()` → `ATS.pdf()` in `index.html`, which writes text with jsPDF
   `doc.text()` / `splitTextToSize()`. Never route an export through
   html2canvas / html2pdf: that produces an image ATS parsers read as blank.
   Verify by extracting text from the output, not by looking at it.

3. **No invented data in the UI.** Every tab binds to the parsed resume.
   Placeholder strings ("Your Name", "Recent Company", "Senior PM", "TechCorp",
   "Skill 1") surviving into a rendered view are a bug.

4. **Nothing is done until it is verified.** Run `python tests/run_all.py`
   and `.venv\Scripts\python -m pytest` before calling a change fixed.

5. **The server is reachable by every web page you have open.** Any site in
   your browser can send requests to `localhost`. So: no wildcard CORS, no
   secrets in any response, static serving is allowlist-only. Do not loosen
   these to "fix" a fetch error — fix the origin instead.

6. **SSE responses close their connection.** Streams have no
   Content-Length; closing is the only end-of-stream signal. `_sse_start()`
   sends `Connection: close`. Don't change it back to keep-alive. Streams go
   through `_stream()`: a heartbeat every 15 s, and when the client leaves,
   `emit` raises `Cancelled` and `gpt()` refuses further calls.

7. **Every store call passes `owner=self.owner`.** A query without an owner
   filter leaks one visitor's resumes to another in the hosted demo.
   `tests/e2e/test_hosted.py` checks isolation; extend it with any new route.

8. **Never ship model text that hasn't passed verification.** Whole resumes
   go through `apex_engine.optimize` / `revise` (as `/analyze`, `/tailor` and
   `/engine/answer` do). Any other text that makes claims about the candidate
   (letters, profile copy, outreach, interview answers, single suggested
   lines, salary leverage) goes through `engine.verify_texts` via the server's
   `fact_checked`: deterministic gate, model audit, one repair, withhold the
   rest and show why. Exports re-parse through `/parse-resume`, whose output is
   checked against the source text (`verify_struct`).

9. **Judge quality with the judge, not the keyword score.** `ats_score` is the
   "Keyword match" number only; it is blind to writing quality and was the
   reason v10 shipped resumes unchanged. The judge also has a veto: a rewrite
   it scores lower than the original is not shipped.

10. **Validate before spending.** POST routes are dispatched on the path
    without its query string; `validate_post` (required fields, size limits)
    and `_precheck` run before the budget is charged or a model is called.
    New routes need a `REQUIRED` entry and an `AI_COSTS` entry if they call a model.

## The engine (apex_engine.py) — how a run improves a resume

`/analyze` Phase 4 measures demand (the model proposes role-specific
requirements; code counts the share of scraped postings that mention each,
whole words only). Phase 6 is `apex_engine.optimize()`: Doc parse (stable ids;
summary + experience/project bullets editable, Skills lines reorder-only,
wrapped PDF lines joined; re-assembled from original lines) → diagnose
(recruiter rubric + evidence questions, batched by role) → rewrite (PLAYBOOK)
→ per-line verify (`fact_gate`: whole-word terms, numbers with unit and scale,
a tool lexicon in any case; then a batched model audit for additions AND
omissions, on `MODEL_AUDIT` if set; one retry, then revert that line only) →
judge (hiring-manager A/B in both orders, averaged, with a veto). Phase 7 Gap
Report is built from the engine's findings. Phase 8 (cover letter, interview
prep, LinkedIn, outreach, velocity) runs alongside, each tab in its own thread
with a shared deadline; a tab that fails or times out sends `tab_skipped`.
The page lets the user untick edits (`/engine/render`, no model call) and
answer questions (`/engine/answer` → `engine.revise`, only the answered lines).

Models: `MODEL` / `MODEL_FAST` (env `APEX_MODEL` or config.json; default
`claude-opus-5-5` / `claude-haiku-5-5` when only an Anthropic key is set,
else `gpt-4o`). `MODEL_AUDIT` defaults to `MODEL`, `MODEL_JUDGE` to `MODEL_AUDIT`. Any
`gpt-...` model goes to OpenAI, any `claude-...` model to Anthropic via the
official SDK. `gpt()` adapts to OpenAI reasoning models (max_completion_tokens,
no temperature, reasoning_effort), uses JSON mode on OpenAI, retries 429/5xx
(not "ran out of tokens"), fails fast when out of credits, and meters real
cost per run for both providers. Claude calls set `output_config.effort`,
never temperature, and use server-side refusal fallback (`fallbacks="default"`)
on Opus/Sonnet 5.5 / Fable 5.1.

**Choosing a model: measure, don't guess.** `python tools/benchmark.py`
runs the engine per model on bench/cases (+ bench/private, gitignored, for
real resumes), cross-judges every output with every judge model (same-provider
scores shown separately), counts invented claims twice (the gate, and an
independent `--fabrication-judge` audit), cost and time, and includes
`chat:<model>` = the plain chatbot baseline APEX must beat, given the same
brief. It stops at `--budget`. Results go to bench/runs/ (gitignored).

## Hosted demo mode (Fly.io; see DEPLOY.md)

Off unless `APEX_ACCESS_CODE` is set; local runs never see it. When on:
access-code sign-in (`/login`; 5 wrong codes / 10 min per IP, 60 attempts /
10 min overall, 5 new sessions per IP per day), HMAC-signed session cookie
(`APEX_SESSION_SECRET`, HttpOnly, Secure, SameSite=Lax, 14 days), each session
is a separate store `owner`, AI routes metered by `AI_COSTS` against an hourly
budget per visitor AND per IP (memory) and a daily budget (persisted in
`apex.db`), and `HOSTED_DISABLED` routes (SMTP, alerts, Gmail import) answer
403. Client IP comes from `Fly-Client-IP` only on Fly (`APEX_TRUST_PROXY` in
fly.toml), else the last `X-Forwarded-For` entry. Owners inactive for 21 days
are purged; each owner is capped at 20 MB of documents. The server refuses to
listen publicly without an access code. `/health` skips only the Host check
and pings the database. Deploy as ONE machine (`fly deploy --ha=false`).

## Endpoints

GET: `/` (index.html), `/health`, `/cities`, `/templates`, `/config`,
`/live-jobs`, `/alerts/list`, `/assets/*` (fonts, images).

POST (SSE): `/analyze` (the full run), `/engine/answer`, `/tailor`,
`/bullets`, `/negotiate`, `/bridge`, `/followup`, `/drift`, `/velocity`,
`/match`, `/xray`, `/grade-answer`.
POST (JSON): `/engine/render`, `/draft-cover-letter`, `/parse-resume`,
`/render-resume`, `/apply-all-recommendations` (legacy, no model),
`/transcribe`, `/live-jobs`, `/config/smtp`, `/config/smtp/test`,
`/alerts/subscribe`, `/alerts/unsubscribe`, `/alerts/test`, `/alerts/scan`,
`/inbox/scan`, hosted `/login` (form).

Local data API (`apex_store`): GET `/api/applications`,
`/api/application?id=`, `/api/scores/latest?jobTitle=`; POST
`/api/applications`, `/api/applications/update`, `/api/applications/delete`,
`/api/applications/import`, `/api/applications/artifact`,
`/api/applications/followup-sent`.

## Known limits — do NOT "fix" these without a plan

- **Velocity** has no trigger of its own; it is filled by Phase 8 of `/analyze`.
- **SMTP is off by default.** Optional, affects email alerts only.
- **Some job sources return zero results** for some roles. Sources fail
  independently by design; the run logs which were skipped.
- **Voice answers need an OpenAI key** (speech-to-text); Anthropic has none.
- **The fact gate cannot derive years of experience** from date ranges, so
  "5 years" is flagged unless written somewhere. Safer than the reverse.

## Running it

```powershell
cd "path\to\Apex 10"
python agent_server.py
# then open http://localhost:7842/  (NOT the file on disk)
```

## Tests

- `python tests/run_all.py` — the two legacy suites (keyword score, ranking),
  the JS syntax check and `r4_export` (needs node).
- `.venv\Scripts\python -m pytest` — unit tests (`tests/test_*.py`: engine,
  fact gate, parsing, store, drift, server helpers, deploy config) plus the
  e2e suite (`tests/e2e`: API, security/CSP, hosted demo, fact checks, request
  hardening, pipeline, Playwright UI). Setup once:
  `py -3.12 -m venv .venv`, `.venv\Scripts\python -m pip install -r requirements-dev.txt`,
  `.venv\Scripts\python -m playwright install chromium`. Starts its own server
  copies with a stub config, an offline model stub (`tests/e2e/fake_openai.py`)
  and saved job postings (`tests/e2e/fixtures/jobs.json`): never the real keys,
  credits or job boards. Unit tests import a key-free copy of the server (the
  `server` fixture in `tests/conftest.py`). Browser tests need network for the
  CDN libs. A few minutes on Windows.
- CI: `.github/workflows/tests.yml` runs ruff (errors only), `run_all.py` and
  pytest on pushes to `main` and on pull requests.
- Not automated: TESTS.md 2, 3, 5, 7 need a real model and live job boards.

## Working agreements

- Read before writing. Report what the code actually does before proposing
  a change, especially on the export and data-binding paths.
- One commit per logical change.
- Python 3.12. Complete runnable code, no elided snippets or pseudocode.
- Flag security issues, edge cases, and failure modes proactively.
- Be direct. If the approach asked for is worse than an available
  alternative, say so before building it.
