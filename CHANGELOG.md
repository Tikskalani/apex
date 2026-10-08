# Changelog

All notable changes to APEX. Newest first.

---

## v10.4 — 2026-10-08

Security lockdown, a real job pipeline, and the test suite that found the bugs below. Run `python tests/run_all.py` and `.venv\Scripts\python -m pytest` after any change (setup in CLAUDE.md).

### Fixed — security

- **Any web page could read the OpenAI key.** The static route blocked `config.json` by exact name, but Windows opens `config.json.` and `config.json::$DATA` as the same file, and every response carried `Access-Control-Allow-Origin: *`. Static serving is now an allowlist of asset types.
- **Any web page could act as you.** POST routes (`/config/smtp`, `/alerts/test`, `/analyze`) accepted cross-site requests, including `text/plain` POSTs that skip CORS preflight. A Host / Origin / Sec-Fetch-Site guard now runs before every route.
- **`/config` returned the JSearch key.** It now reports presence only.
- **Scraped job links could carry `javascript:` URLs**, and several model-generated "scores" went into `innerHTML` unescaped. Links are http(s)-only; scores are coerced to numbers.
- **Strict Content-Security-Policy** with a per-load nonce: no inline script or handlers, no eval, `connect-src 'self'`, no framing. All 29 inline `onclick` handlers moved to delegated `data-action` routing. Every CDN script is pinned by SRI hash.

### Fixed — correctness

- **DOCX export never worked.** docx 8.5.0 is not on cdnjs (404). Now loaded from jsDelivr.
- **Exports could contain placeholder content.** When parsing failed or the resume was short, "Your Name" / "Recent Company" / "Skill 1" were silently substituted and exported. Failures are now reported; nothing is substituted.
- **Every streamed feature hung after finishing.** SSE responses were keep-alive with no length, so the browser never saw end-of-stream; Launch, Tailor, Bullets, Negotiate, Bridge, Drift and Followup awaited until a 300 s socket timeout.
- **Long title/company, degree and project lines ran off the PDF page** instead of wrapping.
- **`/analyze` spent credits on a 1-character resume**, and its 400 left the UI on "Running…". Both fixed.
- **~2 s added to every new connection**: `localhost` resolves to IPv6 first on Windows; the server listened on IPv4 only.
- **Server crashed at startup** when its output was redirected (cp1252 console encoding).
- `/config/smtp/test` used an undefined variable and always failed. Phase 8's five threads wrote to the stream unsynchronised.

### Added

- **Pipeline** (Tracker tab) on a local SQLite database (`apex.db`, stdlib only): saved → applied → interview → offer / rejected / withdrawn, changed inline; job link, notes, next-action date; timeline of every change; follow-ups-due banner and filter; response rate. Older browser-stored applications migrate automatically.
- **Apply kit.** Tailor & Apply → "Save kit to Pipeline" stores the job with its tailored resume and cover letter; re-export the saved resume as ATS PDF/DOCX any time.
- **Follow-ups.** Draft a follow-up sequence for any application (saved to it); "Mark follow-up sent" schedules the next check.
- **Market drift.** Every run records its ATS score; Market Intel → "Check drift now" re-scores against today's postings and shows the change since that run, with rising and fading keywords.
- **Faster runs.** Cover letter, interview, LinkedIn, outreach and velocity now generate alongside the rewrite loop instead of after it.
- **Test suite**: 79 pytest tests (store, drift, HTTP API, security/CSP, Playwright browser flows incl. PDF text-layer extraction and export→upload round trips) on an offline OpenAI stub.

### Removed

- html2pdf (unused; it rasterised to an image) and the dead html2canvas export path; a duplicate unreachable `/draft-cover-letter` route.

---

## v10.3 — 2026-09-07

Ten rounds of test-driven hardening. Every fix below came from a test that failed first. The suite ships in `tests/` — run `python tests/run_all.py` after any change.

### Fixed — correctness

- **Non-string keywords crashed scoring.** A numeric or `None` entry in the keyword list raised `AttributeError` mid-run.
- **Stemmer was inconsistent and asymmetric.** "education" reduced to `educ` while "educated" reduced to `educat`, so "patient education" did not match "educated patients and families" — real evidence was scored as missing. Matching now falls back to a ≥4-character common prefix in either direction.
- **`SECURITY CLEARANCE` and other prefixed headers were not protected.** Only bare `CLEARANCE` matched. Qualifier prefixes (security, professional, technical, clinical, state) are now accepted.
- **Lowercase and Title Case section headers were invisible.** Header detection required ALL CAPS, so a resume using `licenses and certifications` had no protected content at all. Known section names are now matched case-insensitively.
- **Education `location` and `gpa` were dropped by the exporter.** `norm()` mapped only degree, school, and year — so "Nashik, Maharashtra, India" vanished from every export.
- **Model commentary leaked into shipped resumes.** "Here is the improved resume:" and "Let me know if you'd like changes!" were written into the PDF. Preamble, postamble, and code fences are now stripped before the text is treated as a resume.
- **A missed fidelity audit was rewarded.** Adding an unsupported keyword raised the score, so if the model auditor failed to catch a fabrication, the loop kept it. A deterministic gate now rejects any candidate containing an unsupported keyword absent from the original — before the model audit runs, and without an API call.

### Fixed — scoring accuracy

- **56 legitimate action verbs were counted as weak**, including queried, triaged, screened, refactored, validated, taught, supervised, installed, inspected, charted, and reconciled. Vocabulary expanded across data, clinical, trades, and business domains, plus irregular past tenses (wrote, oversaw, sold, spoke) the stemmer cannot derive.

### Added

- **`tests/` regression suite** — 8 suites, 60+ assertions, covering scorer edge cases, protected-content extraction across four resume shapes, adversarial model output, export field fidelity, ranking validity, the real historical failure, over-correction, and Unicode/large-input robustness. Every test exists because a bug got through.

### Verified

Ranking sanity on a controlled set: a strong quantified resume scores 98, keyword-stuffed 70, weak 22, unstructured 45. A weak resume gains +14 through honest rewriting; a strong honest resume correctly gains nothing and is told why.

---

## v10.2 — 2026-09-07

### Fixed — critical

**Export dropped licenses, certifications, languages, projects, awards, and work authorization.** The parser extracted them; the ATS export engine (PDF, DOCX, TXT) read only name, contact, summary, experience, education, and skills and discarded the rest. This was a second, independent leak alongside the v10.1 rewrite-loop fix — the loop could preserve a license section perfectly and the exporter would still delete it. All three formats now render every parsed field. Licenses render immediately after the summary, where regulated-profession screeners look first.

**Parser truncated credentials.** Post-nominals ("Jane Doe, PT") were stripped from the name. Education date ranges collapsed to the end year. No field existed for work authorization. Sections that fit no schema field were discarded. Added `authorization`, preserved post-nominals and full date ranges, and added `additional[]` as a catch-all so nothing on the resume is silently lost.

### Fixed — scorer

- Present-tense verbs (instruct, design, prepare — correct for a current role) were not recognized as strong; only past-tense forms were. Stem-based matching now.
- Skills lists using `•` as an inline separator were counted as bullets lacking verbs. Verb and quantification ratios now measure experience-section bullets only.
- Keyword evidence uses stem matching, so "educated patients" supports "patient education".

On a well-written resume these three fixes moved the measured score from 71 to 79 with no change to the resume — the earlier number was the scorer's blindness, not the candidate's.

### Changed

- **Ceiling explanation.** When no rewrite beats the original, the log now states why in actionable terms: coverage already at N% with the remainder unsupported, verbs already strong, no numbers present to promote. Silence was being read as failure.
- Fidelity audit now lists explicitly what is *not* fabrication — stronger verbs, rephrasing, condensing, naming a skill the original demonstrates in other words — so honest rewrites are not rejected.
- Evidence gate no longer requires the exact phrase; describing the activity in any wording counts.

---

## v10.1 — 2026-09-06

Core rewrite. Fixes a defect that caused the agent to fabricate qualifications and delete credentials while reporting an improved score. Full root-cause analysis in `ANALYSIS_v10.md`.

### Fixed — critical

**Fabrication.** The rewrite prompt passed the gap list as "GAPS TO ADDRESS" and instructed the model to "inject ALL validated keywords." A candidate lacking telehealth experience received a summary claiming telehealth proficiency. The anti-fabrication rule covered only companies, titles, dates, and credentials — not skills or experience.

**Credential loss.** No section-preservation rule existed. The self-scorer read only the first 3,000 characters, so deleting licenses, certifications, languages, and education from the bottom of a resume cost zero points. The loop's fitness function rewarded content loss.

**Fake scores.** The Phase 5 prompt contained example values `55` and `82`; the model anchored on them across unrelated resumes. The after-score was predicted before any rewrite occurred, then `max()`-ed against the self-score so it could never decrease.

### Replaced

- **Evidence gate** — market keywords are classified as supported (resume demonstrates it) or unsupported before rewriting. Only supported keywords reach the rewriter. Unsupported go to the gap report only.
- **Fidelity audit** — every iteration is compared against the original; any unsupported claim rejects the iteration. Fails closed if the audit is unavailable.
- **Protected content** — licenses, certifications, credentials, languages, work authorization, clearances, education, publications, patents, awards, and affiliations are extracted before the loop, verified after every iteration, and restored verbatim if dropped.
- **Deterministic ATS score** — keyword coverage 55, sections 15, verb strength 15, quantification 10, hygiene 5. Reads the full text. Same input, same score.
- **Strict improvement** — iterations are kept only on `>`, not `>=`.
- **Iteration 2** no longer permits estimates. Numbers come from the original or do not exist.
- **Length guard** — candidates under 50% of previous length are rejected as content loss.

### Added

- **Integrity Report** panel on the Market tab — keywords added with evidence, withheld for lack of evidence, rewrites blocked for fabrication, protected sections restored, and before/after breakdown of each score component.
- `market_data` now carries `keywordsInjected`, `keywordsGapsOnly`, `fabricationsBlocked`, `protectedRestored`, `scoreBreakdownBefore`, `scoreBreakdownAfter`.
- Bullet detection tolerant of marker-less PDF-extracted text.

### Changed

- All version strings now read v10 (header docstring, startup banner, agent log, frontend brand, `/health`).
- Expect **lower** ATS numbers than v9 reported. The old numbers were inflated by fabrication and anchoring. A lower true score beats a higher false one.

### Verified

Against the resume that exposed the bug, with a mocked model reproducing the observed behavior: the previously shipped output was rejected for fabrication; licenses, certifications, and languages survived; telehealth was withheld and routed to the gap report.

---

## v10 — 2026-09-06

Repair and hardening release. Fixes a defect that silently defeated the product's core promise, plus four broken endpoint calls.

### Fixed — critical

**ATS-unreadable PDF export.** Export rendered through `html2canvas`, which rasterizes the page to a JPEG and wraps it in a PDF. The resulting file contained no extractable text, so every applicant tracking system parsed it as a blank document. The optimization work was real; the exported artifact discarded it at the final step.

Replaced with a jsPDF text-layer engine:

- Genuine selectable text
- Name 15pt bold · section headers 12pt bold uppercase with rules · body 10.5pt
- 0.75" margins, US Letter
- Hyphen bullets (`-`) — parsed more reliably than `•` by common ATS engines
- Explicit page-break arithmetic instead of viewport-dependent capture

The `html2pdf` template pipeline is retained for visually designed, human-facing PDFs. It is no longer the ATS path.

### Added

- **DOCX export** — docx.js, Calibri, right-aligned tab stops for date ranges
- **Clean TXT export** — plaintext fallback for paste-into-form applications
- Export buttons on both the template panel and the tailored-resume modal
- `POST /draft-cover-letter` — synchronous JSON. The tailoring modal called this and it did not exist server-side, so the cover-letter pane rendered a fetch error on every run
- `POST /apply-all-recommendations` — merges optimized resume with gap changes, bullet rewrites, and missing keywords; falls back to the original if the merge returns a suspiciously short result
- `POST /transcribe` — Whisper transcription for voice interview practice. Hand-rolled multipart body to preserve the zero-dependency constraint. 25 MB guard
- `drift_data` SSE handler — the server emitted this and the frontend silently discarded it

### Fixed

- **`index.html` corruption** — 56,328 trailing null bytes from an interrupted write. Document content was intact through byte 154,959; padding stripped
- **`/inbox/scan` → `/alerts/scan`** — frontend called a route name that did not exist
- **Stale export cache** — the tailored-resume struct is parsed once and cached; it now invalidates on every new tailor run. Without this, exports could serve a previous resume
- Added missing `base64` and `uuid` imports required by the transcribe endpoint

### Verified

- 18 of 18 SSE event types handled
- Zero frontend calls without a matching backend route
- JavaScript parses clean (`node --check`)
- Python parses clean (`ast.parse`)
- Zero null bytes; file terminates correctly

### Known gaps

- `/drift` and `/followup` have no UI trigger. Both work server-side and `drift_data` now has a handler, but nothing invokes them
- `/velocity` has no direct trigger, though `velocity_data` still arrives via Phase 8 of `/analyze`, so that tab populates normally

---

## v9 — 2026-05-13

- Expanded to 18 endpoints and 16 tabs
- Added `/cities`, `/config`, `/templates`, `/grade-answer`, `/live-jobs`, `/parse-resume`, `/render-resume`, `/alerts/*`
- Six resume templates with server-side HTML rendering
- Voice interview practice with answer grading
- Email job alerts with SMTP configuration

## v8 — 2026-05-07

- Added `/tailor`, `/bullets`, `/negotiate`, `/bridge`, `/followup`, `/match`, `/xray`, `/drift`, `/velocity`
- Phase 8 parallel generation: cover letter, interview prep, LinkedIn, outreach, career velocity

## v5 — 2026-05-03

- 8-phase agent loop with role classification and sector awareness
- Ten live job sources with per-listing relevance filtering
- Three-iteration self-improvement loop with automatic regression revert
- ATS scoring against live market data
