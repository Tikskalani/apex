# APEX Architecture

How APEX is put together and why. Read this, then `docs/API.md` for the wire details.
Where this file and the code disagree, the code is right.

## What it is

A local resume-optimisation and job-search app. One Python process serves a
single-page frontend and a JSON/SSE API on one origin, calls a language model (OpenAI
or Anthropic), scrapes public job postings, and keeps the user's job pipeline in SQLite.

| File | Role |
|---|---|
| `agent_server.py` | HTTP server (stdlib `http.server`), security guard, request validation, routes, the `/analyze` pipeline, job-source adapters, model layer `gpt()`, the fact-check wrappers for non-resume text, smaller tools (tailor, bullets, drift, salary, ...), job alerts. |
| `apex_engine.py` | Evidence Engine: parses a resume into editable blocks, diagnoses, rewrites, verifies every edit, judges; plus `verify_texts` for letters and messages. Pure functions over an injected `llm` callable. |
| `apex_store.py` | SQLite storage (stdlib `sqlite3`): applications, event timeline, apply-kit artifacts, score history with requirement lists, hosted daily spend. |
| `index.html` | The whole frontend: one file, vanilla JS, no build step. |
| `assets/NotoSans-*.ttf` | Unicode fonts embedded in exported PDFs (SIL OFL, `assets/OFL.txt`). |
| `config.json` | Keys and model choice (gitignored). See API.md, Configuration. |
| `tools/benchmark.py` | Compares models (and a plain chatbot) on bench resumes. Not part of the app. |
| `tools/feature_bench.py` | Runs each AI feature as APEX and as a plain request to the same model; a judge compares them blind in both orders and a separate model counts unsupported claims. Not part of the app. |

Runtime dependencies: Python standard library, plus the `anthropic` SDK, imported only
when a `claude-...` model is configured. Browser libraries (pdf.js, mammoth, jsPDF, docx)
come from pinned CDN URLs with SRI hashes and are loaded on first use.

## Components and data flow

```
 Browser: index.html  (CSP: per-load nonce + 'strict-dynamic', connect-src 'self')
   |   fetch JSON  /  POST + read SSE stream until the socket closes (abort = cancel)
   v
 agent_server.py  Handler  (one thread per request, at most 64 at once)
   _guard        Host / Origin / Sec-Fetch-Site check          -> 403
   _gate         hosted only: session cookie -> self.owner      -> 401 / 303 /login
   body          size-capped JSON read                          -> 400 / 411 / 413
   validate_post required fields, field sizes, clamps           -> 400 / 413
   _precheck     route checks that need the store / session     -> 400
   AI key        no model key and the route needs one           -> 503 {setup: true}
   charge        hosted only: AI budget units                   -> 429
   route ---------------------------------------------------------------.
     |                   |                          |                   |
     | /analyze          | /engine/*  /tailor       | /api/*            | static files
     v                   v                          v                   v (allowlist)
   agent_loop -----> apex_engine.optimize / revise   apex_store ------> apex.db (SQLite)
     |   |                     |   (engine_llm)
     |   '-- job sources (urllib, threads, one deadline) --> public job APIs
     v
   gpt(system, user, ...)  model layer, metered per request, cancellable
     |-- gpt-...    -> urllib POST {APEX_OPENAI_BASE}/v1/chat/completions
     '-- claude-... -> anthropic SDK  messages.create  (APEX_ANTHROPIC_BASE)
```

- **One origin.** `GET /` serves `index.html`; every API call is same-origin. This is
  what lets the server refuse every foreign origin (see Security).
- **Validate before spending.** POST routes are dispatched on the path without its query
  string. Everything that can be checked without a model is checked first, in the order
  above, so a bad request never costs budget or a model call. A new route needs a
  `REQUIRED` entry, and an `AI_COSTS` entry if it calls a model.
- **No key, still a page.** Without a model key the server starts anyway. `/config` reports
  `AI_READY: false` and the reason (`AI_PROBLEM`); the page shows a setup card and turns
  Launch off, and model routes answer `503 {"error", "setup": true}`.
- **SSE for long work.** `/analyze` and the per-tool routes stream `data: {json}` frames.
  Each tab's data arrives as a typed event (`market_data`, `engine_data`, ...) and the
  page's `handleEvent` dispatches on `type`. Streams have no `Content-Length`, so the
  server sends `Connection: close` and closing the socket ends the stream.
- **Cancellation.** Every stream runs through `Handler._stream()`. It installs a cancel
  event for the request in a `ContextVar` (`_CANCEL`), sends a `: ping` heartbeat every
  15 seconds, and builds a thread-safe `emit` (a lock keeps frames from parallel threads
  whole). When a write or heartbeat fails because the browser left (closed tab, Cancel
  button), the event is set; from then on `emit` raises `Cancelled`, and `gpt()` and
  `http_get()` call `cancel_check()` first and raise too. `Cancelled` is a
  `BaseException`, so the many `except Exception` blocks in the pipeline cannot swallow it
  and keep spending. Worker threads are started with `contextvars.copy_context()`, so they
  inherit the request's cancel event (and its cost meter). Phase 8 tabs add one more stop
  event each (`_TAB_STOP`), so a single tab can be stopped at its deadline without
  touching the run.
- **Storage.** `apex_store` opens a fresh connection per call through `_db()`, which
  commits or rolls back and always closes it (WAL mode), so request threads can use it
  freely. Every row has an `owner`; every query filters on it. Validation lives in the
  store and raises `StoreError` (HTTP 400/404). Job-alert subscriptions are separate, in
  `alerts.json` (local only).
- **Frontend.** `index.html` has 19 views on an icon rail. All controls use
  `data-action` / `data-arg` and one delegated listener, because the CSP forbids inline
  `on*=` handlers. See [The page](#the-page).

### Model layer: `gpt()`

One function for every model call: `gpt(system, user, max_tokens, temp, *, json_mode, fast, effort, model)`.

- **Model choice.** `MODEL` writes, reviews and judges; `MODEL_FAST` (when `fast=True`)
  does cheap extraction and classification. Defaults depend on which keys exist (API.md,
  Model selection).
- **Engine routing.** The engine never calls `gpt()` directly; the server hands it
  `engine_llm`, which sends fact-check prompts (`VERIFY_SYSTEM`: the resume-edit audit and
  `verify_texts`) to `MODEL_AUDIT` and judge prompts to `MODEL_JUDGE`. Both default to
  `MODEL` (the judge to `MODEL_AUDIT`), so setting them is how a writer stops grading its
  own work.
- **Dispatch by prefix.** `claude-...` goes to `_claude()`; everything else goes to OpenAI.
- **OpenAI.** Plain `urllib`, 180 s timeout. Legacy models (`gpt-4*`, `gpt-3.5*`) get
  `max_tokens` and `temperature`. Newer models get `max_completion_tokens` (requested
  budget + 6000 for reasoning tokens) and `reasoning_effort` (default `low`), no
  temperature. `json_mode` sets `response_format: json_object`. When a model rejects a
  parameter with a 400, the server records that quirk per model and retries without it.
  429 and 5xx are retried up to 3 times with backoff (honouring `Retry-After`, capped at
  30 s). A 429 that mentions quota, credits or billing fails immediately with a clear
  "no credits" message, because retrying cannot help. An answer cut off before any text
  ("ran out of tokens") is not retried.
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
  than under-reports. The result is the `cost_data` event. A process-wide `TOTAL_METER`
  prints to the console.

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
                                         └──── join, 90 s deadline ──────┤
                                                                         v
                                                tab_skipped?, cost_data, done
```

| Phase | What happens | Model |
|---|---|---|
| 0 Classify | Sector (one of 33), function, a cleaner search term, alternate terms, sector jargon, anti-keywords. Falls back to `general` on failure. | `MODEL` |
| 1 Harvest | One thread per source in `SECTOR_SOURCES[sector]`: JSearch (with `JSEARCH_KEY`), Remotive, Arbeitnow, RemoteOK, Jobicy, Findwork (with `FINDWORK_API_KEY`), Himalayas, The Muse (by category), USAJobs (with `USAJOBS_API_KEY` + `USAJOBS_EMAIL`). Sources without their key return nothing. Each returns raw text and fails independently. All share one 30-second deadline; late sources are logged as skipped. Emits `jobs_data`. | none |
| 2 Retry | Only if fewer than 5 listings: retry the first 3 sources with up to 3 alternate terms. | none |
| 3 Relevance filter | Deterministic score per listing (title words, sector jargon, length, anti-keyword penalty). Keep score ≥ 35; relax to 20; else take the top 10. Corpus capped at 16 000 characters. Confidence from the count (≥ 20 high, ≥ 10 medium, ≥ 5 low). | none |
| 4 Requirements | The model **proposes** 30-45 role-specific requirements from the postings and the target posting. `build_market` then **measures** demand: the share of filtered postings that mention each one, matched as whole words (`_present`). With fewer than 8 postings no percentage is stated. Under 3 % is dropped unless it is in the target posting. Buckets: hot ≥ 25 % or in posting, warm 10-24 %, cold < 10 %. | `MODEL_FAST` |
| 5 Evidence | `classify_keywords` splits the top 30 requirements into supported / unsupported: deterministic whole-word match first, then one strict model call for the rest. If that call fails, everything unknown is unsupported (fail closed). Unsupported requirements are reported as gaps and never added. The deterministic keyword-match score (`ats_score`) is computed. Emits `market_data`. | `MODEL` |
| 8 Generators (start) | Cover letter, interview prep, LinkedIn, outreach, career velocity, each in its own thread. They read only the original resume, keywords and analysis, so they start here, in parallel with Phases 6-7, and stay off the critical path. Each emits its own event. Text about the candidate is fact-checked (below). | `MODEL` |
| 6 Evidence Engine | `apex_engine.optimize` (next section). The keyword score is recomputed on the result; `market_data` is re-sent with judge scores and edit counts; then `engine_data` and `resume_data`. A `notice` event tells the page when the engine found nothing to edit or the judge kept the original. | `MODEL`, audit `MODEL_AUDIT`, judge `MODEL_JUDGE` |
| 7 Gap report | Built from the engine's findings with no extra model call: real before/after pairs, the diagnosed problems with fixes, unmet requirements with their measured share, the evidence questions. Emits `report_data`; the server stores the score and the run's top 30 requirements (`baselineKeywords`) for drift. | none |
| 8 Generators (join) | The tabs get 90 more seconds in total (one deadline for all). A tab still running is stopped through its own stop event (its model calls and emits end); a tab that raised is caught. Either way the page gets `tab_skipped` with the reason, instead of a tab that silently never arrives. Then `cost_data` and `done`. | |

Phase 8 output that makes claims about the candidate goes through the server's
`fact_checked` (below): the cover letter, every sample interview answer, LinkedIn
headline, About and experience bullets (skills the resume does not show are dropped), and
every outreach message.

### Phase 6: the Evidence Engine (`apex_engine.optimize`)

Every model call goes through the injected `llm` (the server passes `engine_llm`), so tests
drive the whole engine with a stub.

1. **Parse (`Doc`).** The resume becomes lines with roles and stable ids. The first line is
   the name. A header is a known section name (English, German, Spanish, French and
   Portuguese; markdown `#` and `**` are stripped) or a short all-caps line. Editable:
   the summary (`S`), experience/project bullets (`B1`, `B2`, ...) and Skills lines
   (`K1`, ...). Whether a section uses bullet markers (`-`, `•`, `*`, numbers, the
   Symbol-font bullet PDFs leave behind, ...) is decided per section: in a marked section a
   following unmarked line is the wrapped rest of the bullet unless it looks like a role or
   date heading; in an unmarked section (common in PDF text) a sentence of 8+ words without
   a date range is a bullet. An unmarked line right after a bullet that starts lowercase, or
   follows a connector word ("and", "of", ","), always continues it. Bullets are grouped by role. Everything else
   (contact block, education, licences) is never sent for editing. Output is reassembled from
   the original lines, so unchanged lines come out byte-identical and protected sections
   cannot drift or vanish. A resume with no summary gets a virtual `S` slot: if the engine
   writes one, it is inserted before the first section (`summary_created`). A resume with
   no summary and no bullets is returned unchanged with a `note` explaining how to lay it
   out; the page shows it as a warning.
2. **Diagnose.** As hiring manager for the target role: per-block rubric (impact,
   specificity, scannability, relevance, 1-5), quoted issues, and at most one question per
   block whose answer (a number, a scale, an outcome) would unlock the biggest gain. Plus
   document-level problems, most relevant bullets, strengths. Long resumes go in calls of
   at most 20 blocks (`BATCH`), never splitting a role unless it alone is bigger; only the
   first call reviews the document as a whole.
3. **Rewrite.** Same batching, with the `PLAYBOOK` (outcome first, 14-32 words, condense
   rather than delete, use the employer's vocabulary only for demonstrated skills, never
   add facts) and the reviewer notes. Edits come back by id. It also proposes a bullet
   order per role and, in the first call, optionally a section order. Skills lines may only
   be reordered: items can move between lines of a section, nothing added, dropped or renamed.
4. **Verify, per edit.** Edits identical to the original are skipped. Skills edits are
   checked deterministically (`skills_ok`: the same labels and items as a multiset). Every
   other edit must pass both:
   - `fact_gate` (deterministic, below), against that edit's evidence: its role's text plus
     the candidate's answer; for the summary, the whole resume plus all answers.
   - Model audit (`MODEL_AUDIT`), 8 items per call, each role's text sent once: flags
     **ADDED** claims (tools, numbers, scope, causal claims the evidence does not make)
     and **DROPPED** content (a distinct accomplishment, project or technology silently
     deleted). An item the audit does not clear counts as failed.
5. **Retry once, revert per edit.** Failed ids get one more rewrite with the exact
   reasons, then the same verification. Anything still failing keeps its original text
   and is listed in `rejected`. A bad edit never takes good edits down with it.
6. **Ordering is separate from wording.** Verified wording edits are keyed by id. Orders
   are applied afterwards and only if valid (a full permutation of one role's bullets; a
   permutation of the existing section headers). So every reported change compares a line
   with its own rewrite, never with a neighbour that moved into its slot. The user can
   untick any edit or the reorders; `/engine/render` reassembles with no model call.
7. **Judge, with a veto.** Two blind calls (`MODEL_JUDGE`) as the target role's hiring
   manager, original vs final as A/B and then B/A, scores averaged so position bias and
   noise cancel. The judge reads the first 40,000 characters of each version and says so
   when it had to cut. If it scores the rewrite **below** the original, the original
   ships: the edits move to `vetoed_changes`, `veto` says why, and the page shows a notice.
   A worse resume is never shipped as an improvement.

**Answering questions: `engine.revise`.** `POST /engine/answer` does not re-run the
engine. It rewrites only the ids the candidate answered, with the answers as new
evidence, through the same gate, audit and one retry. The edits the user kept are applied
as they are, the first run's order and section order are re-applied, unanswered questions
and the diagnosis carry over, and the result is judged once (with the veto). An answered
id that fails falls back to its kept edit, else the original.

An `optimize` run makes at least 4 model calls: diagnose, rewrite, two judge calls; plus
one more diagnose and rewrite call per extra batch of 20 blocks, one audit per 8 changed
blocks and, if anything failed, one retry rewrite with its audit.

### The fact gate (`fact_gate`)

The deterministic half of every check. It compares a new text with the evidence it may
draw on and lists problems; empty means clean.

- **Words, not substrings.** Text is split into words and matched as word n-grams (stems,
  up to 6 words), so "AWS" is not found in "laws" and "Java" not in "JavaScript".
- **Numbers with unit and scale.** Every quantity is read as (value, unit): digits, number
  words ("fifteen"), scales ("$2M" is 2,000,000 dollars, not the 2 in "2 interns"), `%`,
  `x` / "times" / "doubled", years, currencies, vague amounts ("dozens"), and ranges
  ("10-15%", "$1-2M") that share their unit. A number must be in the evidence with the same
  unit. Counting items the evidence lists ("3 tools" when one line names three) is allowed
  up to 9.
- **Terms and names.** Technical-looking tokens (CamelCase, ALLCAPS acronyms, `C++`,
  `Node.js`) and capitalised words that are not an ordinary sentence opener must be backed by
  the evidence. A small allowlist covers common acronyms (`KPI`, `SaaS`, `B2B`, ...).
- **Tool lexicon.** A list of languages, frameworks, databases, clouds, SaaS tools,
  certifications and large employers is flagged in any case and position when the evidence
  lacks it. Entries that are also ordinary words (Excel, Go, Rust, React, Spark, Slack, ...)
  count only when capitalised.
- **Same thing, other name.** Aliases (`Postgres` / `PostgreSQL`, `k8s` / `Kubernetes`), one-way
  implications (evidence naming S3 backs "AWS", not the reverse), a vendor prefix
  ("Microsoft Excel" from "Excel"), and hyphenated compounds whose parts appear.
- **Keywords.** A requirement the resume does not demonstrate may never appear. A resume
  bullet may use a demonstrated (supported) keyword only when its own role shows it, so a
  bullet cannot borrow another job's skill.
- **Context rule.** For letters and messages, the job posting can be passed as `context`.
  Its names and numbers back only sentences that claim nothing about the candidate; a
  sentence with I / my / we, or a resume-style line opening with a verb, needs the evidence.

### Fact check for everything else (`verify_texts`)

Text that is not a resume edit but makes claims about the candidate goes through
`engine.verify_texts`, called by the server's `fact_checked`: the fact gate (with greeting
and sign-off words allowed), then a model audit (`MODEL_AUDIT`, 8 items per call, each
distinct evidence text sent once), one repair call with the reasons, a second check, and
whatever still fails is withheld with its reasons. Used for cover letters (both routes),
sample interview answers, LinkedIn copy, outreach messages, `/bullets` rewrites, `/xray`
fixes, `/bridge` reframes, narrative and answers, follow-up emails, salary leverage points
and `/grade-answer`'s better version. A rewrite of a quoted resume line is checked against
that line's role, found with `line_evidence`.

Not checked, because they are advice, scores or the candidate's choice: interview
questions and tips, salary figures, velocity, match scores, `/bridge` skill translations.
`/match` quick fixes are not rewritten but each is marked `shown_on_resume` (whole-word
match) so the page can say which ones the resume does not back yet.

## Job sources

Two sets of adapters in `agent_server.py`. All return nothing rather than raise.

- **Text sources** for the market analysis (`/analyze`, `/drift`): `src_*` functions per
  sector (Phase 1 above).
- **Structured sources** for Live Jobs, alerts and salary (`fetch_structured_jobs`):
  Remotive, Arbeitnow, Jobicy, RemoteOK, The Muse, public Greenhouse boards (18 companies)
  and Lever boards (14), the latest Hacker News "Who is hiring" thread; JSearch and
  USAJobs with their keys. They run through `parallel_map`: one thread per source, one
  25-second deadline for all, stragglers abandoned instead of waited on one by one
  (the board lists use the same helper with 15 seconds). Results are de-duplicated,
  junk titles dropped, filtered by location aliases ("Houston" matches "Houston, TX" but
  not "Dallas, TX") and ranked.
- **Fetching.** `http_get` sends a browser user agent, accepts gzip, times out after 12 s
  by default (some sources set their own), treats a response over 12 MB as a failure instead of truncating it,
  and checks for cancellation first.
- **Fixture mode.** With `APEX_FIXTURE_JOBS` pointing at a JSON file of saved postings, no
  job board is contacted: the harvest, drift and salary use those postings and Live Jobs
  returns those jobs. The tests run this way.

## Other tools, and why they are built the way they are

- **Matching is whole-word.** `_present` (server) decides whether a requirement appears
  in a posting or a resume: a whole-word phrase match, else every word of the requirement
  as a word (longer words by stem), so "Go" never matches "good" and "SOC operations" never
  matches "associate ... operations". It drives demand percentages, the supported /
  unsupported split, the keyword score, LinkedIn skill filtering and `/match`'s
  `shown_on_resume`.
- **Drift compares like with like.** Every `/analyze` stores its keyword score and its top 30
  requirements. `/drift` re-scrapes, has the fast model propose today's requirements, counts
  both lists in today's postings, and scores the same resume with `ats_score` against the
  stored list and against today's. The difference is the drift. New requirements, and stored
  ones that dropped off today's list or whose share fell by 10 points or more, are listed. No model guesses a score. Runs
  stored before requirement lists existed fall back to the stored score, and `basis` says
  which comparison was made.
- **Salary from posted pay.** `/negotiate` first collects stated pay ranges from live
  postings for the role and location (hourly rates annualised, implausible values dropped).
  With 3 or more, the model is given the 25th percentile, median and 75th percentile and
  told to base every figure on them; otherwise the brief is labelled an AI estimate. The
  candidate's leverage points are fact-checked.
- **Exports never take text from the model.** `/parse-resume` has the model structure the
  resume, then `verify_struct` checks every string against the resume text: kept when it
  is there, replaced by the closest resume line (or two joined lines, for wrapped text)
  when it was paraphrased, else blanked and reported in `dropped`, which the page shows.
- **Tailoring is the engine.** `/tailor` extracts the posting's requirements with the fast
  model and runs `engine.optimize` with the posting as the target, so a tailored resume (and
  the apply kit saved from it) gets the same per-line verification and the judge's scores.
- **Legacy merge.** `/apply-all-recommendations` (unused by the page) applies only rewrites
  that replace a real line and pass the fact gate; it makes no model call and never adds
  keywords.

## Why the engine is built this way

The v10 loop rewrote the whole resume, re-scored it with a keyword-count metric, and
kept the rewrite only if that score went up. Better writing barely moves a keyword
count, markdown in the model's output made the formatting-blind scorer read good
rewrites as regressions, and one flagged phrase discarded every edit with it, so on real
resumes it shipped the original unchanged. That loop and its audit are gone.

The engine replaces it with three rules:

- **Never ship unverified model text.** Every resume edit passes the deterministic gate
  and the model audit on its own, or is reverted on its own. Every other text about the
  candidate passes `verify_texts` or is withheld. Any new feature that writes resume text
  should go through `apex_engine`.
- **Judge quality with the judge, not the keyword score.** `ats_score` is shown as
  "Keyword match" only. It is deterministic and useful for drift, and blind to writing.
- **A worse result never ships.** The judge's veto keeps the original when the rewrite
  scores lower.

Supporting choices: requirement percentages are counted from real postings, not stated
by the model; evidence classification and the audits fail closed.

## Storage

`apex_store.py`, one SQLite file (`apex.db`, or `APEX_DB`).

- **Connections.** `_db()` opens one connection per call, runs one transaction (commit on
  success, rollback on error) and always closes it. Writes that read first use
  `BEGIN IMMEDIATE` so two requests cannot interleave.
- **Dates are UTC**, for timestamps and for "today" (follow-ups due, `applied_on`), like the
  hosted spend table.
- **Score history** stores each run's keyword score and its requirement list
  (`keywords`, `[{name, pct}]`): the drift baseline. Older databases get the column added in
  place on start-up.
- **Caps** per owner: 2000 applications, 20 MB of notes and saved documents, 50 documents per
  application, the newest 200 score records.
- **Purge.** In hosted mode a background thread deletes visitors untouched for 21 days
  (sessions last 14) and daily-spend rows older than 90 days. The local owner is never purged.
- **Health.** `ping()` reads the database for `/health`, which answers 503 when it fails.

### Alerts store

Job alerts live in `alerts.json` (local only). Only one scan runs at a time (a lock shared
by the 15-minute loop, `/alerts/subscribe` and `/alerts/scan`). A scan works on a snapshot,
because it takes minutes of network calls, then merges its results into the current file
under `ALERTS_LOCK`, so a subscribe or unsubscribe made meanwhile is never overwritten.
Writes go to a temporary file that replaces the old one (`alerts.json` and `config.json`
alike), so a crash never leaves a truncated file; an unreadable `alerts.json` is set aside,
not silently replaced. The sent-job log keeps the newest 500 per subscription. A failed
send is retried on the next scan.

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
- **CSP** on `index.html` with a fresh nonce per load and `'strict-dynamic'`: only the
  page's own scripts run, and the scripts they add. The vendor libraries are added on first
  use by `loadLib()` with their pinned URL and SRI `integrity`, so a modified CDN file is
  refused and nothing blocks the first paint. `connect-src 'self'` stops data leaving for
  anywhere but this server; framing is denied.
- **Limits.** Request bodies, resume and posting sizes are capped (API.md), and at most 64
  requests run at once.
- **No secrets in responses.** `/config` reports which keys exist, never their values.
- **Loopback only** unless hosted mode is on; the server refuses to bind publicly without
  an access code.

## Hosted demo mode

Off unless `APEX_ACCESS_CODE` is set (deployment notes in `DEPLOY.md`). When on:

- Visitors sign in at `/login` with the access code and get an HMAC-signed session cookie
  (`HttpOnly`, `SameSite=Lax`, `Secure` on a public host, 14 days). Sign-in is throttled: 5
  wrong codes per IP per 10 minutes, 60 attempts per 10 minutes from everyone, and 5 new
  sessions per IP per day.
- Each session is a separate store `owner`, so visitors never see each other's data.
- AI routes cost units (`AI_COSTS`; a full run is 12). Spend is capped per visitor and per
  IP per hour (in memory), and for everyone per UTC day (in `apex.db`, so a restart cannot
  reset it). Over budget: 429.
- The client IP comes from `Fly-Client-IP` only when running on Fly with
  `APEX_TRUST_PROXY=1`; elsewhere from the last `X-Forwarded-For` entry with that setting,
  else the socket. A header the platform does not overwrite would be forgeable.
- `/engine/answer` checks the `sig` on the engine target, so a visitor cannot send back a
  target whose "supported" list widens the fact gate.
- Features that act with the operator's email account or collect third-party credentials
  (SMTP setup, job alerts, IMAP inbox scan) answer 403, and the alert loop does not run.
- SQLite lives on one volume, so the app runs as one machine.

## The page

`index.html`, vanilla JS, one file.

- **Run bar.** Every long run shows a bar with the current step, elapsed time and a Cancel
  button. Cancel aborts the `fetch`, which closes the stream and so cancels the run on the
  server. Leaving the page during a run asks first. The Tailor & Apply dialog gives each
  opening its own `AbortController` and sequence number, so a late answer for one job can
  never land in another job's kit.
- **Saved in this browser.** The resume, inputs, filters, the last run's results (every tab),
  and the review state (kept edits, answers) are saved to `localStorage` and restored on
  reload. A size guard drops bulky results before the resume; a button clears it all. The
  pipeline itself is in `apex.db`, not the browser.
- **Saved resume versions** (up to 20): save, restore (the current text is saved first),
  delete, and compare any version with the current text as a line diff.
- **Saved target roles**: title, seniority, industry and posting, to switch between roles.
- **Live Jobs filters**: remote only, posted within N days, hide duplicates.
- **Tracker follow-ups**: a banner and a count on the Tracker icon for follow-ups that are
  due or overdue, a filter for them, a drafted follow-up sequence per application, and
  "Mark follow-up sent", which schedules the next check.
- **Exports.** PDF export writes real text with jsPDF (`doc.text`), never an image of the
  page, so ATS parsers can read it. It embeds Noto Sans (fetched from `/assets/`) so names
  outside Latin-1 survive; Helvetica is the fallback if the font cannot load. DOCX and TXT
  too, for the resume and for cover letters.
- **Accessibility.** Closed dialogs are `inert`; an open one takes focus, keeps Tab inside
  and closes on Escape, then returns focus. Status changes are announced (`aria-live`),
  errors stay on screen 8 seconds, focus outlines are visible, and motion is reduced when the
  system asks.

## Testing

| Command | What it covers |
|---|---|
| `python tests/run_all.py` | The two remaining stdlib regression suites (`r1_scorer`: keyword score; `r5_ranking`: ranking sanity), a syntax check of every inline script in `index.html` (`check_js_syntax`) and the export engine (`r4_export`). The two JS checks need Node and skip cleanly without it. |
| `.venv\Scripts\python -m pytest` | Unit tests (`tests/test_*.py`): engine flow, fact gate, parsing and benchmark helpers, store, drift, server helpers, deploy config. They import a key-free copy of the server (`tests/conftest.py`). E2E tests (`tests/e2e/`): API, security and CSP, hosted mode (including owner isolation), fact checks, request hardening, pipeline, the Claude provider, the benchmark tool, and Playwright (Chromium) UI suites (core flows, engine review, exports). |
| `python tools/benchmark.py` | Not a test: runs the engine per candidate model on `bench/cases` (and gitignored `bench/private`), cross-judges every output with every judge model (same-provider scores reported separately), counts invented claims twice (the engine's gate, and an independent `--fabrication-judge` audit), cost and time, includes a plain-chatbot baseline (`chat:<model>`), stops at `--budget`. Results in `bench/runs/`. |

The e2e suite starts its own copy of the server on a free port with a stub `config.json`,
points `APEX_OPENAI_BASE` (and, for the Claude suite, `APEX_ANTHROPIC_BASE`) at
`tests/e2e/fake_openai.py`, and sets `APEX_FIXTURE_JOBS` to `tests/e2e/fixtures/jobs.json`.
The stub answers both the OpenAI `/v1/chat/completions` and Anthropic `/v1/messages`
shapes with canned output chosen by the system prompt. No real keys, credits or job boards
are used. Browser tests need network access for the CDN libraries.

CI (`.github/workflows/tests.yml`, on pushes to `main` and on pull requests): `ruff check
--select F,E9` (errors only), `run_all.py`, then pytest, on Python 3.12 with Node 20.

Not automated: anything that needs real model output or live job scraping (paid and
non-deterministic). See `TESTS.md`.

## Limits worth knowing

- `ThreadingHTTPServer` is one thread per request and synchronous model calls; fine for
  one user or a small demo, not for real concurrency.
- SQLite on one disk: one machine only.
- Free job sources come and go; any one returning nothing is expected. A run with zero
  postings in total still completes, with requirements listed but not measured.
- The fact gate cannot derive years of experience from date ranges, so "5 years" is
  flagged unless the resume says it. That is the safe direction.
- The judge reads the first 40,000 characters of each version.
