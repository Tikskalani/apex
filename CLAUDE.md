# APEX v10.4

Local resume-optimization and job-search agent app. Single developer, runs locally on Windows from the project folder.

## Architecture (verified against the code 2026-10-08)

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
- **Backend:** `agent_server.py` — pure Python stdlib (`http.server`
  `ThreadingHTTPServer` + `BaseHTTPRequestHandler`). No pip dependencies.
  Binds `localhost:7842` only. Serves `index.html` at `/` so page and API share
  one origin. Calls OpenAI for parsing/optimization/cover letters and scrapes
  live job postings (JSearch optional). Listens on 127.0.0.1 and ::1.
  Sends a strict CSP with a per-load nonce on `index.html`.
- **Storage:** `apex_store.py` (stdlib sqlite3) → `apex.db` beside the server
  (gitignored; override with `APEX_DB`). Applications (saved → applied →
  interview → offer / rejected / withdrawn), an append-only event timeline,
  artifacts (apply kit: tailored resume, cover letter, follow-ups), and
  score history (every `/analyze` run's before/after ATS score, used as the
  drift baseline). Validation lives in the store (`StoreError` → HTTP 400).
  Browser `localStorage['apex_apps']` from older versions is migrated once on
  page load (kept as `apex_apps_backup`).
- **Vendor libs** pinned by version and SRI hash (`integrity="sha384-…"`):
  pdf.js 3.11.174, mammoth 1.6.0, jsPDF 2.5.1 (registers as
  `window.jspdf`) from cdnjs; docx 8.5.0 from jsDelivr
  (`cdn.jsdelivr.net/npm/docx@8.5.0/build/index.umd.js`) because cdnjs does
  not carry docx at all. Bumping a version means recomputing its hash.
- **Keys:** `config.json` beside the server (`OPENAI_KEY`, `JSEARCH_KEY`,
  optional `SMTP_*`), falling back to env vars `OPENAI_API_KEY` /
  `JSEARCH_API_KEY`. `config.json` is gitignored. There is no `.env`.

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

6. **SSE responses close their connection.** Streams have no
   Content-Length; closing is the only end-of-stream signal. `_sse_start()`
   sends `Connection: close`. Don't change it back to keep-alive.

5. **The server is reachable by every web page you have open.** Any site in
   your browser can send requests to `localhost`. So: no wildcard CORS, no
   secrets in any response, static serving is allowlist-only. Do not loosen
   these to "fix" a fetch error — fix the origin instead.

## Endpoints

GET: `/` (index.html), `/health`, `/cities`, `/templates`, `/config`,
`/live-jobs`, `/alerts/list`, `/render-resume`.

POST (v10 additions marked *): `/analyze` (SSE, the full 8-phase run),
`/tailor`, `/bullets`, `/negotiate`, `/bridge`, `/followup`, `/drift`,
`/velocity`, `/match`, `/xray`, `/draft-cover-letter`*,
`/apply-all-recommendations`*, `/parse-resume`*, `/render-resume`,
`/alerts/*`.

Local data API (v10.4, `apex_store`): GET `/api/applications`,
`/api/application?id=`, `/api/scores/latest?jobTitle=`; POST
`/api/applications`, `/api/applications/update`, `/api/applications/delete`,
`/api/applications/import`, `/api/applications/artifact`,
`/api/applications/followup-sent`.

## Known gaps — do NOT "fix" these

- **Velocity** has no trigger of its own; it is filled by Phase 8 of
  `/analyze`. (Drift and Followup are wired as of v10.4: Market Intel →
  "Check drift now"; Tracker → Open → "Draft follow-up".)
- **SMTP is off.** Optional, affects email alerts only.
- **Some job sources return zero results.** Sources fail independently by
  design. Only a problem if the total scraped across all sources is 0.

## Running it

```powershell
cd "path\to\Apex 10"
python agent_server.py
# then open http://localhost:7842/  (NOT the file on disk)
```

## Tests

- `python tests/run_all.py` — regression suites (stdlib; `r4_export` needs node,
  `r7_e2e` needs pdfplumber + a fixture PDF; both skip cleanly).
- `.venv\Scripts\python -m pytest` — store/drift unit tests (`tests/test_*.py`)
  plus the Playwright suite (`tests/e2e`): TESTS.md 1, 4, 6, 8, security/CSP,
  local API, pipeline, follow-ups, apply kit, drift. Setup once:
  `py -3.12 -m venv .venv`, `.venv\Scripts\python -m pip install -r requirements-dev.txt`,
  `.venv\Scripts\python -m playwright install chromium`. Starts its own server
  copy (env `APEX_PORT`, `APEX_OPENAI_BASE`) with a stub config and an offline
  OpenAI stub; never uses the real keys or credits. Needs network for the CDN
  libs. ~1.5–2.5 min, most of it in Chromium shutdown on Windows.
- Not automated: TESTS.md 2, 3, 5, 7 need real OpenAI + live job scraping
  (non-deterministic and paid). Test 4's manual text-selection check *is*
  automated (pdfplumber extracts text and checks glyph positions).

## Working agreements

- Read before writing. Report what the code actually does before proposing
  a change, especially on the export and data-binding paths.
- Git initialised 2026-10-08. One commit per logical change.
- Python 3.12. Complete runnable code, no elided snippets or pseudocode.
- Flag security issues, edge cases, and failure modes proactively.
- Be direct. If the approach asked for is worse than an available
  alternative, say so before building it.
