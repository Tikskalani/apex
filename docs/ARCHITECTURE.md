# APEX Architecture

How APEX is put together and why. Read this, then `docs/API.md` for the wire details.
Where this file and the code disagree, the code is right.

## What it is

A local resume-optimisation and job-search app. One Python process serves a
single-page frontend and a JSON/SSE API on one origin, calls a language model (OpenAI
or Anthropic), scrapes public job postings, and keeps the user's job pipeline in SQLite.

| File | Role |
|---|---|
| `agent_server.py` | HTTP server (stdlib `http.server`), security guard, routes, the `/analyze` pipeline, job-source adapters, model layer `gpt()`, smaller tools (tailor, bullets, drift, ...), job alerts. |
| `apex_engine.py` | Evidence Engine: parses a resume into editable blocks, diagnoses, rewrites, verifies every edit, judges. Pure functions over an injected `llm` callable. |
| `apex_store.py` | SQLite storage (stdlib `sqlite3`): applications, event timeline, apply-kit artifacts, score history, hosted daily spend. |
| `index.html` | The whole frontend: one file, vanilla JS, no build step. |
| `config.json` | Keys and model choice (gitignored). See API.md, Configuration. |

Runtime dependencies: Python standard library, plus the `anthropic` SDK, imported only
when a `claude-...` model is configured. Browser libraries (pdf.js, mammoth, jsPDF, docx)
come from pinned CDN URLs with SRI hashes.

## Components and data flow

```
 Browser: index.html  (CSP with per-load nonce, connect-src 'self')
   |   fetch JSON  /  POST + read SSE stream until the socket closes
   v
 agent_server.py  Handler  (one thread per request)
   _guard   Host / Origin / Sec-Fetch-Site check          -> 403
   _gate    hosted only: session cookie -> self.owner      -> 401 / 303 /login
   charge   hosted only: AI budget units                   -> 429
   route ---------------------------------------------------------------.
     |                   |                          |                   |
     | /analyze          | /engine/*                | /api/*            | static files
     v                   v                          v                   v (allowlist)
   agent_loop -----> apex_engine.optimize(gpt)    apex_store ------> apex.db (SQLite)
     |   |                     |
     |   '-- job sources (urllib, threads) --> public job APIs and RSS feeds
     v
   gpt(system, user, ...)  model layer, metered per request
     |-- gpt-...    -> urllib POST {APEX_OPENAI_BASE}/v1/chat/completions
     '-- claude-... -> anthropic SDK  messages.create  (APEX_ANTHROPIC_BASE)
```

- **One origin.** `GET /` serves `index.html`; every API call is same-origin. This is
  what lets the server refuse every foreign origin (see Security).
- **SSE for long work.** `/analyze` and the per-tool routes stream `data: {json}` frames.
  Each tab's data arrives as a typed event (`market_data`, `engine_data`, ...) and the
  page's `handleEvent` dispatches on `type`. Streams have no `Content-Length`, so the
  server sends `Connection: close` and closing the socket ends the stream. With
  keep-alive the page never saw the end and every await hung until the socket timeout.
  The emitter holds a lock so frames from parallel threads never interleave, and stops
  writing when the client disconnects.
- **Storage.** `apex_store` opens a short-lived connection per call (WAL mode), so
  request threads can use it freely. Every row has an `owner`; every query filters on it.
  Validation lives in the store and raises `StoreError` (HTTP 400/404). Job-alert
  subscriptions are separate, in `alerts.json` (local only).
- **Frontend.** `index.html` has 19 views on an icon rail. All controls use
  `data-action` / `data-arg` and one delegated listener, because the CSP forbids inline
  `on*=` handlers. PDF export writes real text with jsPDF (`doc.text`), never an image of
  the page, so ATS parsers can read it.

### Model layer: `gpt()`

One function for every model call: `gpt(system, user, max_tokens, temp, *, json_mode, fast, effort, model)`.

- **Model choice.** `MODEL` writes, reviews and judges; `MODEL_FAST` (when `fast=True`)
  does cheap extraction. Defaults depend on which keys exist (API.md, Model selection).
- **Dispatch by prefix.** `claude-...` goes to `_claude()`; everything else goes to OpenAI.
- **OpenAI.** Plain `urllib`, 180 s timeout. Legacy models (`gpt-4*`, `gpt-3.5*`) get
  `max_tokens` and `temperature`. Newer models get `max_completion_tokens` (requested
  budget + 6000 for reasoning tokens) and `reasoning_effort` (default `low`), no
  temperature. `json_mode` sets `response_format: json_object`. When a model rejects a
  parameter with a 400, the server records that quirk per model and retries without it.
  429 and 5xx are retried up to 3 times with backoff (honouring `Retry-After`, capped at
  30 s). A 429 that mentions quota, credits or billing fails immediately with a clear
  "no credits" message, because retrying cannot help.
- **Anthropic.** Official SDK client (180 s timeout, SDK retries 3), `max_tokens` =
  requested + 8000, `output_config.effort` (default `low`), never `temperature`.
  `json_mode` is not passed; prompts ask for JSON and the parsers tolerate fences and
  trailing commas. For `claude-opus-5-5`, `claude-sonnet-5-5` and `claude-fable-5-1` the
  call uses server-side fallback (`fallbacks="default"`) so a safety refusal is re-run on
  a suitable model inside the same request (skipped when `APEX_ANTHROPIC_BASE` points at
  a stub). A `refusal` stop reason becomes an error. Organisation-level keys send the
  `anthropic-workspace-id` header. Credit and key errors are turned into plain messages.
- **Metering.** Each request sets a fresh `Meter` in a `ContextVar`. Every call adds its
  real token usage (Anthropic cache tokens included) priced from `MODEL_PRICES`; unknown
  models are priced at the most expensive known rate so the meter over-reports rather
  than under-reports. Threads that call the model are started with
  `contextvars.copy_context()` so their spend lands on the right request. The result is
  the `cost_data` event. A process-wide `TOTAL_METER` prints to the console.

## The `/analyze` pipeline

Phase numbers match the log output.

```
 0 classify ─> 1 harvest ─> 2 retry? ─> 3 filter ─> 4 requirements ─> 5 evidence
                                                                         │
                                         ┌───────────────────────────────┤
                                         │ start Phase 8 (5 threads)     │
                                         │                               v
                                         │                  6 Evidence Engine
                                         │                               v
                                         │                  7 gap report
                                         └──────── join ─────────────────┤
                                                                         v
                                                               cost_data, done
```

| Phase | What happens | Model |
|---|---|---|
| 0 Classify | Sector (one of 33), function, a cleaner search term, alternate terms, sector jargon, anti-keywords. Falls back to `general` on failure. | `MODEL` |
| 1 Harvest | One thread per source in `SECTOR_SOURCES[sector]` (JSearch if keyed, Remotive, Arbeitnow, RemoteOK, Jobicy, Findwork, Himalayas, The Muse, USAJobs, Indeed/LinkedIn RSS, Google News). Each returns raw text; sources fail independently. Joined with a 25 s timeout each. Emits `jobs_data`. | none |
| 2 Retry | Only if fewer than 5 listings: retry the first 3 sources with up to 3 alternate terms. | none |
| 3 Relevance filter | Deterministic score per listing (title words, sector jargon, length, anti-keyword penalty). Keep score ≥ 35; relax to 20; else take the top 10. Corpus capped at 16 000 characters. Confidence from the count (≥ 20 high, ≥ 10 medium, ≥ 5 low). | none |
| 4 Requirements | The model **proposes** 30-45 role-specific requirements from the postings and the target posting. `build_market` then **measures** demand: the share of filtered postings that mention each one. With fewer than 8 postings no percentage is stated. Under 3 % is dropped unless it is in the target posting. Buckets: hot ≥ 25 % or in posting, warm 10-24 %, cold < 10 %. | `MODEL_FAST` |
| 5 Evidence | `classify_keywords` splits the top 30 requirements into supported / unsupported: deterministic match first, then one strict model call for the rest. If that call fails, everything unknown is unsupported (fail closed). Unsupported requirements are reported as gaps and never added. The deterministic keyword-match score (`ats_score`) is computed. Emits `market_data`. | `MODEL` |
| 8 Generators (start) | Cover letter, interview prep, LinkedIn, outreach, career velocity. They read only the original resume, keywords and analysis, so they start here, in parallel with Phases 6-7, and stay off the critical path. Each emits its own event; a failure only logs. | `MODEL` |
| 6 Evidence Engine | `apex_engine.optimize` (next section). The keyword score is recomputed on the result; `market_data` is re-sent with judge scores and edit counts; then `engine_data` and `resume_data`. | `MODEL` |
| 7 Gap report | Built from the engine's findings with no extra model call: real before/after pairs, the diagnosed problems with fixes, unmet requirements with their measured share, the evidence questions. Emits `report_data`; the server stores the score for drift. | none |
| 8 Generators (join) | Each thread is joined with a 60 s timeout, then `cost_data` and `done`. | |

### Phase 6: the Evidence Engine (`apex_engine.optimize`)

Every model call goes through the injected `llm` (the server passes `gpt`), so tests drive
the whole engine with a stub.

1. **Parse (`Doc`).** The resume becomes lines with roles. Section headers are detected;
   only the summary (id `S`) and experience/project bullets (`B1`, `B2`, ...) are editable.
   Bullets are grouped by role. Everything else (contact block, education, licences,
   skills) is never sent for editing. Output is reassembled from the original lines, so
   unchanged lines come out byte-identical and protected sections cannot drift or vanish.
2. **Diagnose.** One call as hiring manager for the target role: per-block rubric
   (impact, specificity, scannability, relevance, 1-5), quoted issues, and at most one
   question per block whose answer (a number, a scale, an outcome) would unlock the
   biggest gain. Plus document-level problems, most relevant bullets, strengths.
3. **Rewrite.** One call with the `PLAYBOOK` (outcome first, 14-32 words, condense
   rather than delete, use the employer's vocabulary only for demonstrated skills, never
   add facts) and the reviewer notes. Edits come back by id. It also proposes a bullet
   order per role and, optionally, a section order.
4. **Verify, per bullet.** Edits identical to the original are skipped. Each remaining
   edit must pass both:
   - `fact_gate` (deterministic): every number, technical-looking term (CamelCase,
     acronyms, `C++`, `Node.js`, ...) and mid-sentence capitalised name must already
     appear in that bullet's evidence (its role's text plus the candidate's answer; for
     the summary, the whole resume plus all answers). A small alias table allows standard
     names (`Postgres` to `PostgreSQL`). Unsupported requirements may not appear.
   - Model audit, batched 8 items per call, each item sent with its role's text:
     flags **ADDED** claims (tools, numbers, scope, causal claims the evidence does not
     make) and **DROPPED** content (a distinct accomplishment, project or technology
     silently deleted). An item the audit does not return counts as failed.
5. **Retry once, revert per bullet.** Failed ids get one more rewrite with the exact
   reasons, then the same verification. Anything still failing keeps its original text
   and is listed in `rejected`. A bad edit never takes good edits down with it.
6. **Ordering is separate from wording.** Verified wording edits are keyed by id. Orders
   are applied afterwards and only if valid (a full permutation of one role's bullets; a
   permutation of the existing section headers). So every reported change compares a line
   with its own rewrite, never with a neighbour that moved into its slot. The user can
   untick any edit or the reorders; `/engine/render` reassembles with no model call.
7. **Judge.** Two blind calls as the target role's hiring manager, original vs final as
   A/B and then B/A, scores averaged so position bias and noise cancel. The judge
   **reports** quality (`recruiterScoreBefore/After`); it does not veto the result.

Candidate answers go through `POST /engine/answer`, which re-runs the whole engine with
the answers added to each block's evidence.

An engine run makes at least 4 model calls: diagnose, rewrite, two judge calls, plus one
audit per 8 changed blocks and, if anything failed, one retry rewrite with its audit.

## Why it is built this way

The v10 loop rewrote the whole resume, re-scored it with a keyword-count metric, and
kept the rewrite only if that score went up. Better writing barely moves a keyword
count, markdown in the model's output made the formatting-blind scorer read good
rewrites as regressions, and one flagged phrase discarded every edit with it, so on real
resumes it shipped the original unchanged.

The engine replaces that with two rules:

- **Never ship unverified model text into the resume.** Every edit passes the
  deterministic gate and the model audit on its own, or is reverted on its own. Any new
  feature that writes resume text should go through `apex_engine`.
- **Judge quality with the judge, not the keyword score.** `ats_score` is shown as
  "Keyword match" only. It is deterministic and useful for drift, and blind to writing.

Supporting choices: requirement percentages are counted from real postings, not stated
by the model; evidence classification and the audit fail closed.

Where the rule is not yet enforced (model text that does not go through the engine):
`/tailor` (`tailored_resume` and its match scores), `/bullets` (rewrites), `/bridge`
(reframed bullets), the Phase 8 cover letter and LinkedIn `experience_bullets`, and the
legacy `/apply-all-recommendations`, which the page no longer calls. The v10
`improvement_loop` and `fidelity_audit` are still in `agent_server.py` and exercised by
`tests/run_all.py`, but `/analyze` does not use them.

## Security model

The server is reachable by every page open in the user's browser, so it trusts nothing
by default:

- **Origin guard** (`_guard`, before any route, and before a POST body is read): the Host
  header must be one of the server's own (blocks DNS rebinding); an `Origin`, when sent,
  must be the server's own (`file://` pages send `null` and are told to use
  `http://localhost:7842/`); `Sec-Fetch-Site: cross-site` is refused except for a plain
  navigation to `/`. Clients that send no `Origin` (curl, tests) pass.
- **CORS** echoes only the server's own origins, never `*`.
- **Static files** are allowlist-only by name pattern and extension; `config.json`,
  Python files, the database and dotfiles are never served.
- **CSP** on `index.html` with a fresh nonce per load: only the page's own scripts and the
  two pinned CDNs run, `connect-src 'self'` stops data leaving for anywhere but this
  server, framing is denied.
- **No secrets in responses.** `/config` reports which keys exist, never their values.
- **Loopback only** unless hosted mode is on; the server refuses to bind publicly without
  an access code.

## Hosted demo mode

Off unless `APEX_ACCESS_CODE` is set (deployment notes in `DEPLOY.md`). When on:

- Visitors sign in at `/login` with the access code (5 failures per IP per 10 minutes,
  then 429) and get an HMAC-signed session cookie (`HttpOnly`, `SameSite=Lax`, `Secure`
  on a public host, 14 days).
- Each session is a separate store `owner`, so visitors never see each other's data.
- AI routes cost units (`AI_COSTS`, a full run is 10). Spend is capped per visitor per
  hour (in memory) and for everyone per UTC day (in `apex.db`, so a restart cannot reset
  it). Over budget: 429.
- Features that act with the operator's email account or collect third-party credentials
  (SMTP setup, job alerts, IMAP inbox scan) answer 403, and the alert loop does not run.
- SQLite lives on one volume, so the app runs as one machine.

## Testing

| Command | What it covers |
|---|---|
| `python tests/run_all.py` | Stdlib regression suites `r1`-`r10` (scorer, protected sections, legacy loop under hostile model output, ranking, weak bullets, final checks) plus a syntax check of every inline script in `index.html`. The JS checks (`check_js_syntax`, `r4_export`) need Node and `r7_e2e` needs pdfplumber and a fixture PDF; they skip cleanly without them. |
| `python -m pytest` (from the project venv) | `tests/test_*.py`: store, drift, engine and deploy-config unit tests. `tests/e2e/`: Playwright (Chromium) suites for the main flows, security and CSP, the local API, the pipeline, the engine UI, the Claude provider, hosted mode (including owner isolation) and the benchmark tool. |
| `python tools/benchmark.py` | Not a test: runs the engine per candidate model on `bench/cases` (and gitignored `bench/private`), cross-judges every output with every judge model (same-provider scores reported separately), counts invented claims, cost and time, includes a plain-chatbot baseline (`chat:<model>`), stops at `--budget`. Results in `bench/runs/`. |

The e2e suite starts its own copy of the server on a free port with a stub `config.json`
and points `APEX_OPENAI_BASE` (and, for the Claude suite, `APEX_ANTHROPIC_BASE`) at
`tests/e2e/fake_openai.py`: an offline stub that answers both the OpenAI
`/v1/chat/completions` and Anthropic `/v1/messages` shapes with canned output chosen by
the system prompt. It never uses real keys or credits. It does need network access for
the CDN libraries.

Not automated: anything that needs real model output or live job scraping (paid and
non-deterministic). See `TESTS.md`.

## Limits worth knowing

- `ThreadingHTTPServer` is one thread per request and synchronous model calls; fine for
  one user or a small demo, not for real concurrency.
- SQLite on one disk: one machine only.
- Free job sources come and go; any one returning nothing is expected. A run with zero
  postings in total still completes, with requirements listed but not measured.
- The `/drift` `current_score` is a model estimate, while its baseline is the stored
  deterministic keyword score from the last run, so the two numbers are not measured
  the same way.
