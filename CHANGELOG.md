# Changelog

All notable changes to APEX. Newest first.

---

## Unreleased

Everything APEX writes about you is now fact-checked, runs can be cancelled, a bad request costs nothing, and the engine reads more resume layouts. The server still reports version 11.0.

### Fixed

- **Apply never opened the browser window** ("The application took too long"): Playwright's bundled Chromium is unsigned and Windows 11 refuses to start it. APEX now opens your installed Google Chrome (then Edge, then Chromium) with its own profile folder, and reports at once, by name, when no browser could start instead of waiting out a timeout.
- **The resume PDF read as a wall of text.** Line spacing was 1.08; it is now 1.2 with air after each bullet, between skill groups and between roles. The PDF is drawn with that spacing first and tightened in steps only if it would spill past two pages, so a short resume gets the room and a long one still fits. The DOCX export uses the same line spacing. The engine now keeps each bullet to one achievement of at most two printed lines and splits longer source bullets instead of carrying them over.
- The resume PDF the agent makes in the background failed on APEX's own page (a script-evaluation rule in the page's Content Security Policy).

- **From the first real scan** (129 postings): the job agent and the market radar matched skills by word stem, so "Scala" was found in "scalable" and "evals" in "evaluate", and generic words ("product", "requirements", "integration", "enterprise") counted as skills; fit scores ran high (most 85-97) and the radar listed noise as gaps. Skills now match as whole words (a plural counts), skills that are also everyday words only as written ("Go" the language, "REST", "Make.com"), and names recruiters treat as the same skill count ("LLM" for "large language models", "Postgres" for "PostgreSQL"). A search for a hands-on role (engineer, developer, scientist, architect) no longer proposes leadership or non-engineering titles ("Head of AI Native Operations", "AI Transformation Owner", "Manager, Applied AI Architects"), and a remote job open only outside the US ("Remote - Brazil", "Remote - Canada") is not proposed. The server no longer prints a traceback when the browser drops a spare connection.

- Exports printed a role as "Independent AI Consulting — Independent AI Consulting" when the parse put the company in both fields; a section heading could sit alone at the foot of a page with its content on the next; a title line parsed as "AI engineer" printed in lowercase.
- **A location typed as "Austin, TX" dropped every job listed as "Austin, Texas"** (all JSearch results), so a physical therapy search found nothing. "City, ST" now matches both spellings, and suburbs from sources that searched near the city (JSearch, USAJobs) count when they are in the same state.
- **JSearch could miss the 25-second deadline** fetching its two pages one after the other; they are fetched at once, and a search is reused for 12 hours (the free plan allows 200 requests a month).
- A posting for a supporting role ("Physical Therapist Assistant", "aide", "technician") no longer matches a search for the role itself.
- **Exports flattened real resumes** (found on the owner's own resume). Labelled skill groups ("Agentic development: ...") were merged into one run-on "Technical:" paragraph, a project's separate points were glued into one paragraph with " | ", and Projects always printed last. `/parse-resume` now returns `skills.groups`, project `bullets` and `date`, and the resume's `section_order`; PDF, DOCX and TXT print groups as labelled lines, projects as bullets, and sections in the resume's own order. The template previews are drawn by the same code as the PDF (`ATS.html`), so the preview shows exactly what downloads (the older server templates, which left out Projects, are no longer used by the page). PDF skill labels keep a real space in the text layer for application systems.
- **New-graduate clinicians had almost nothing editable**: Clinical Rotations, Internships, Externships, Fieldwork, Practicum, Clinical Affiliations and Research are now experience sections the engine works on.
- **Closing the tab did not stop a run.** The server kept calling the model (and spending) after the browser left. Streams now send a heartbeat every 15 s; once the client is gone, the run stops making model calls and fetching postings (`Cancelled`).
- **A slow tab could hold up the end of a run, or never arrive.** Cover letter, interview, LinkedIn, outreach and velocity now share one 90-second deadline after the report; a tab still running is stopped and a tab that failed is reported, both with a `tab_skipped` event the page shows. Job sources share one 30-second deadline instead of 25 s each.
- **Fact gate false matches.** Matching is on whole words ("AWS" is not in "laws", "Java" is not in "JavaScript"), numbers are compared with their unit and scale ("$2M" is not the 2 in "2 interns"), and a lexicon of tools, platforms, certifications and employers is caught in any case and position.
- **Requirement matching was substring-based** (`_present`): "Go" matched "good", which inflated demand percentages and "supported" skills. Whole words now. A cache keyed on `id()` could also return another text's stems.
- **Resumes the engine could not read.** Hard-wrapped PDF lines are joined back into one bullet, bullet markers are detected per section (including the Symbol-font bullet PDFs leave), German, Spanish, French and Portuguese headers are recognised, and long resumes are processed in batches (one call for 96 lines overflowed and edited nothing). A resume with nothing editable now says why instead of coming back unchanged in silence.
- **Drift measured nothing.** It compared a stored keyword score with a model's guess. It is now deterministic: the same resume scored against your last run's requirements and today's, both counted in today's postings (`drift_data.basis`, `postings`).
- **Salary figures were model guesses shown as market data.** `/negotiate` now uses pay ranges stated in live postings when there are at least 3, and labels the brief an AI estimate otherwise (`estimate_basis`, `basis_note`, `posted_pay`).
- **Inbox scan said "no emails" when it had failed.** An unreadable inbox or a failed classification is now a `502` with the reason; every email is classified (was the first 40), in batches.
- `/alerts/test` and `/config/smtp/test` reported SMTP failures as `200`/`500`; now `502` (`400` for missing credentials).
- **Job alerts could lose subscriptions.** Two scans could run at once, and a scan overwrote subscribes or unsubscribes made while it ran. One scan at a time; results are merged into the current file; `alerts.json` and `config.json` are written atomically; a damaged `alerts.json` is set aside instead of replaced.
- **Database connections were never closed**, and "today" (follow-ups, applied dates) was local time while timestamps were UTC. Both fixed in `apex_store`.
- POST routes called with a query string (`/analyze?x=1`) returned 404.
- **Exports could contain text the parser made up.** `/parse-resume` now checks every field against your resume and leaves out (and lists) anything it cannot find; resumes over 9,000 characters are no longer cut before parsing.
- **Accented and non-Latin names broke PDF export.** Noto Sans is embedded.
- `/followup` wrote from a short summary and `/grade-answer` had no resume to check a rewrite against; both now accept `resume`.
- **Found in a real Claude run (Staff Backend Engineer):**
  - Market requirements were off-role ("security engineering", "defence security clearance") because any posting saying "engineer" counted. Postings must now carry the role's core title words (`title_matches`, `role_words`). Kept postings went from 123 of 123 to 31 of 76, average relevance from 54 to 74.
  - The fact check withheld good outreach for ordinary words: message openers ("Would", "Please"), plural nouns starting a sentence ("Containers"), and plain slash compounds ("team/product").
  - JSearch fetched its three pages one after another and missed the deadline; now in parallel.
  - `/tailor` now reports its measured cost (`cost_data`).
- **Found by the feature benchmark (six tech resumes, APEX vs. asking Claude directly):**
  - One unverifiable sentence threw away a whole cover letter, follow-up email or improved interview answer, so the page showed nothing usable. `engine.verify_texts` now, after its one repair, drops just the sentences the check quotes when at least 60% of the text survives, and checks what is left; only a text that still fails is withheld.
  - The engine lost good new summaries the same way (one phrase such as "data-heavy" failed twice, so "Good team player" shipped). A rejected summary is now trimmed to its verifiable sentences and checked again.
  - A rewrite could pull another bullet's achievement into its own line while that bullet stayed, so the fact appeared twice. Each bullet now keeps its own achievement.
  - A cover letter that joined separate resume facts in every paragraph could be neither repaired nor trimmed. It now gets one fresh draft that is told which claims to avoid. Letters also stop copying weak resume phrasing ("worked on", "helped with") and keep separate facts separate.
  - The improved interview answer kept the candidate's weak lines, because it could only use their words, and was removed whole when a story could not be verified. Now a question about what they did is told in STAR form with blanks for details only they know, a question about what they would do gets a strong "I would..." approach (intent, not a claim), and an answer that fails the check gets one redraft told what to avoid.
  - Weakness X-Ray and Bullets "fixes" kept the weak verbs they criticised, because a stronger verb would overstate the candidate's role. They now offer the stronger verb as a choice to confirm ("[Led / Co-led] the migration").
  - Job titles missed postings spelled another way: "ML Engineer" for Machine Learning, "Front-End", "SRE", "SWE", "LLM", "Member of Technical Staff" (`canon_title`). A new-grad search required "new" and "grad" in the title. A posting for a different kind of role ("Account Executive, AI" for "AI Engineer", "Engineering Manager" for an engineer) or the other end of the ladder (staff roles for a new-grad search, internships for a senior one) no longer matches (`seniority_band`).
  - Most of the curated Greenhouse and Lever company boards no longer existed (they answered with nothing).

### Added

- **Workday, and other multi-page application sites.** The agent now applies on Workday career sites end to end: Apply, "Autofill with Resume", the account step (APEX creates the employer account with a strong generated password and keeps it for you, or signs in with the one it kept), My Information, My Experience, Application Questions, Voluntary Disclosures, Self Identify, Review, Submit, confirmation. Forms that live inside a frame (iCIMS and others) and forms spread over Next/Continue pages are walked page by page. A verification code an employer emails, an account that already exists, or a required question only you can answer leaves the form open for you with the reason. **Sign-ins APEX made for you** (Apply Queue tab) lists them; a password is revealed only when you ask. Stored on this computer only.
- **Ghost-job filter.** Every scan now records when it first saw each job and whether its posting date keeps moving. A posting over 45 days old, listed for 45+ days, reposted, written as an evergreen "talent pool" ad, or an aggregator copy with no trace on the employer's own board is scored; likely ghosts are not proposed (profile: **Skip likely ghost postings**), stale ones are ranked down and labelled with the reason. The digest counts what was filtered.
- **Follow-ups that send themselves.** After 5 silent days (then 12) the agent drafts the follow-up (fact-checked) for each application; with **Send them for me** on and a recruiter address known, it sends it from your mailbox and records it; otherwise it marks the follow-up due in the Tracker. After 21 silent days it notes the application as ghosted and stops. Recruiter addresses are picked up from postings and from replies in your inbox, and can be typed on the application card. **Send follow-up** on the card sends the next one now. `POST /api/applications/followup/send`, `POST /api/agent/followups/run`.
- **Morning digest by email.** Give the profile a digest address (email set up in Alerts) and an hour after the morning scan APEX sends: new matches, what it applied to, replies, what needs you, follow-ups due, ghosts filtered, top gaps. **Send digest** sends it now. `GET /api/agent/digest/preview`, `POST /api/agent/digest/send`.
- **Search health.** Reply and interview rates by role family, source, fit band, weekday and resume template, median days to a reply, and a plain recommendation once a group has five or more applications ("Forward deployed roles reply 3x more than ML engineer roles: lean into them"). Apply Queue tab. `GET /api/agent/analytics`.
- **Hidden jobs, the day they go up.** `tools/discover_boards.py` found 348 AI companies' Greenhouse, Ashby and Lever boards (from the public YC directory plus well-known AI employers; each verified) in `data/boards.json`. The agent reads every board once every six hours and matches locally, so a posting is seen before aggregators copy it; postings under a day old are marked **new today** and ranked up.
- **Company brief** (application card). What the company does, its product, stack, recent news, size and funding, how it works, from its own site and GitHub organisation (never from memory: gaps say "not found"), plus three fact-checked lines on where your work maps to it and four questions to ask. `POST /api/applications/brief`.
- **Warm path** (application card). People you can reach about an application without LinkedIn: addresses in the posting or from a reply, the company's public GitHub members, people who posted its hiring notes on Hacker News; with two short fact-checked notes (to a recruiter, to an engineer) to send. `POST /api/applications/warm`.

- **The job agent applies on its own.** With **Apply for me** on in the profile, every prepared application is filled, answered and submitted in the APEX browser window: contact details, resume PDF and cover letter; the screening questions from your saved **Application answers** (work authorization, sponsorship, relocation, start date, salary, demographics: blank means decline to answer); dropdowns and checkboxes matched by their options; free-text questions written from your resume, evidence vault and cover letter and fact-checked. It presses Submit only when no required question is left, confirms the site accepted the application (a screenshot of the confirmation is kept in `apex_files/apply/`), and files the job in the Tracker as submitted. A required question it cannot answer truthfully, a sign-in wall or a bot check leaves the form open for you with the reason on the card; nothing is guessed and no bot check is worked around. Up to the profile's daily number a day. `/api/agent/apply` returns `status` (`submitted`, `needs_you`, `captcha`, `invalid`, `unconfirmed`, `filled`), `missing` and `detail`.
- **Add jobs by link** (Apply Queue tab). Paste job links, one per line: LinkedIn, Indeed, Greenhouse, Lever, Ashby or a company careers page. APEX reads each posting (applicant tracking systems through their APIs, other pages through the model), finds the employer's own application when the link is a job board's, scores the fit, tailors your resume to it, writes the cover letter and applies. Links it cannot read (a sign-in wall, an expired posting) are reported with the reason. `POST /api/agent/links {profile, urls}`.
- **The employer's own application form.** Job boards (BeBee, Learn4Good, JobLeads, LinkedIn...) copy postings that expire, wall or redirect; the agent now looks the same job up on the employer's Greenhouse, Ashby or Lever board (by company name, matching the title closely) and uses that link for the posting, the kit and the application. Applied at scan time and again when applying. The JSearch source already prefers the employer's apply link over an aggregator's.

- **Replies move your applications forward.** The inbox scan now ties each job email to the application it is about in the Tracker (same company; the role breaks ties) and offers **Move to Interview / Offer / Rejected** (or **Apply N status updates**) instead of adding a duplicate. Nothing changes until you press it; the email's subject is added to the application's notes. Only forward moves are offered: an offer is never turned into a rejection and a closed application stays closed. `/inbox/scan` rows carry `match` and `update_to`, and the response `updates`.
- **Interview prep pack** (Tracker, local only). For an application in interview: what this team will probe (from the saved posting when the job agent found it), 8-10 likely questions with why they ask and an answer outline from your own experience, 4-5 STAR stories, questions to ask and topics to brush up. Outlines and stories are fact-checked against your resume and evidence vault; one that claims more is left out and counted. Saved with the application (`interview_prep`). `POST /api/applications/prep`.

- **Market radar and today's digest** (Apply Queue tab, local only). Every scan records what the postings it found ask for (skills and tools, on full postings) and which AI role families they are. The radar shows, over the last 14 days, the share of postings asking for each skill, whether your resume or evidence vault shows it, and how the share moved against the two weeks before; the gaps are the most-asked skills you do not show. **Suggest projects for my gaps** (one model call, about 2¢) proposes three weekend-sized projects that build on what you already did, each with a number to measure and the resume line it becomes once built (ideas only; nothing reaches a resume until you add what you measured to the vault). A **Today** card shows the day's new matches, kits ready to apply and the top three gaps. The job agent's fit score now counts the vault as evidence. `/api/agent/radar`, `/api/agent/digest`, `/api/agent/radar/ideas`.

- **Evidence vault** (local only). Facts you confirm once are kept and used as evidence in every later resume, tailored resume, cover letter and job-agent application: your answers to the engine's questions (saved automatically, tagged with the role or project they are about), your public GitHub repositories (description, language, stars, topics and the start of each README), and notes you add. A fact about a role or project is evidence for that role's lines; every fact is evidence for the summary and the cover letter; a skill shown only in the vault counts as shown. APEX still states nothing that is not in your resume or the vault. Apply Queue tab, **Evidence vault**; `/api/facts`.

- **Resumes fit their page budget**: two pages for AI and software engineering, one for physical therapy (two for senior clinicians). When the rewritten resume runs over, the model proposes bullets to cut (repeated proof first, then the least relevant); code keeps a cut only if every role keeps a bullet and no skill the target asks for disappears from the page. Cuts appear as edits ("Removed to fit the page budget") you can untick. Found on a real resume that came out at 3 pages, the third holding only Education.
- **One-tap Apply.** On a job in the Apply queue, Apply prepares it if needed, makes the tailored resume PDF, and opens the application in an APEX browser window (`apex_apply.py`, Playwright; it keeps its own sign-ins in `apex_browser/`). Greenhouse, Lever and Ashby forms are recognised by their fields and any other form by its labels: name, email, phone, LinkedIn, GitHub, location, the resume PDF and the cover letter are filled. APEX never presses Submit; the person checks the form, answers what is left and submits, then presses "I submitted it". Kits now carry the parsed resume, so the PDF needs no model call.
- **Faster job agent:** three kits are prepared at once, and the best new matches of each scan (`auto_prepare`, default 5 per profile, about 30¢ each) are prepared without asking, so they are ready when you look.
- **Job agent and Apply queue** (local only). A profile per person (base resume, target titles, location, remote, jobs per day, minimum fit). Every morning after `APEX_AGENT_HOUR` (default 7, local time), or on Scan now, the agent searches each target, keeps postings for the right role at the right level, scores each against the base resume on this computer (no model call: the share of the skills and tools the posting asks for that the resume shows), and proposes the best. Nothing is tailored until you approve (one at a time or all): then the Evidence Engine tailors the base resume to that posting and a cover letter is written, both fact-checked, about 30¢ each. You open the posting, apply, and press Mark applied, which files it with its kit in the Tracker. A job is never proposed twice. APEX never submits an application. Routes `/api/agent/*` (403 when hosted); tables `profiles` and `queue`.
- **Built for two fields** (`apex_domains.py`): AI and software engineering, and physical therapy. Each has a pack (what hiring managers in the field screen for, how to order the page, the field's vocabulary and the shape of excellent lines) that the engine's review, rewrite and judge read for any target title in that field. Measured on 6 bench resumes (3 tech, 3 physical therapy) with the same field-aware judge: average gain +8.0 with packs against +5.0 without; an acute care PT resume went from made-worse (63 → 60) to 60 → 68. Three fictional physical therapy cases join `bench/cases`.
- **Focus mode** (default): the dock shows Home, Resume X-Ray, PDF Templates, Live Jobs, Cover Letter and Tracker; "More tools" shows the rest and is remembered. A run in focus mode asks only for the cover letter of the extra tabs (`/analyze` `extras: false`), so it costs less.
- **Company job boards as a source** (`company_board_jobs`): full postings from the public Greenhouse, Ashby and Lever boards of 53 tech and AI employers (OpenAI, Anthropic, Databricks, Stripe, Snowflake, Cloudflare and others), checked live. Used by the market scan for tech, AI/data, cloud and security roles and for `general`, by Live Jobs, and by the salary brief. Most US postings there state pay, so `/negotiate` has real ranges far more often. One fetch per title is shared for 15 minutes.
- **Salary from postings at your level.** An entry-level search counts only entry-level postings and a senior search senior ones (`posted_pay`); `posted_pay.companies` and `basis_note` name the employers the figures mostly come from.
- **Blanks you fill in.** Suggested rewrites (Bullets, Weakness X-Ray), Career Bridge reframes and answers, interview sample answers and the improved version of a graded answer may leave a short blank, e.g. "cut p99 latency [by X%]", where only you know the fact; the page highlights it. The fact check treats a blank as no claim, and everything stated outright is still checked. Rewrites must be clearly stronger than the original (no synonym swaps).
- **Rewrite with my latest resume** on the Cover Letter tab: the run writes the letter before you answer the engine's questions, so this writes it again from your edited resume (the edits you kept, including lines rewritten with your answers), fact-checked again. Voice-practice grading also reads the edited resume.
- **Bullets shows the whole review**: the verdict, the 3 fixes that matter most (`top_fixes`), what is weak in each bullet, and the question that would unlock its missing number (`ask`); the page showed only the score and rewrite before. **Answer grading** adds what the question is probing and the follow-ups to expect (`follow_up_questions`), with room for a full answer.
- `tools/answer_bench.py`: measures the question loop. Bench cases carry hidden `facts`; a simulated candidate answers the engine's questions from them only, the answered lines are rewritten, and the judge scores the resume and cover letter before and after, with an audit of unsupported claims.
- `tools/feature_bench.py`: every AI feature run as APEX and as a plain request to the same model, judged blind in both orders, with an independent count of unsupported claims on each side. Five tech cases join `bench/cases` (ML, AI engineering, frontend, SRE, new grad).

- **Starts without a key.** The page shows a setup card and turns Launch off; model routes answer `503 {"error", "setup": true}`. `GET /config` adds `AI_READY`, `AI_PROBLEM`, `VOICE_READY`, `MODEL`, `VERSION`.
- **Judge veto.** If the blind hiring-manager review scores the rewrite below your original, the original ships and the page says why (`veto`, `vetoed_changes`, `notice` event).
- **Summary creation** for resumes without one, and **Skills reordering** (`K#` lines: the skills the role asks for first; nothing added, dropped or renamed, checked in code).
- **Answering questions rewrites only those lines** (`engine.revise`): the edits you kept stay, the first run's order and diagnosis carry over, then one judge pass.
- **Fact check for everything else that writes about you.** Tailor & Apply runs the Evidence Engine against the posting, so the tailored resume saved to your apply kit is verified line by line and its scores are the blind judge's. Cover letters (both), interview sample answers, LinkedIn copy, outreach and follow-up messages, salary leverage points, Bullets rewrites, Weakness X-Ray fixes, Career Bridge reframes, story and answers, and graded-answer rewrites go through `engine.verify_texts`: fact gate, model audit, one repair, and anything still unverified is withheld with the reason shown on the page. Match quick fixes are marked `shown_on_resume`. Prompts no longer carry example rewrites with invented metrics.
- **`MODEL_AUDIT` / `MODEL_JUDGE`** (config or `APEX_MODEL_AUDIT` / `APEX_MODEL_JUDGE`): run the fact-check audit and the judge on another model than the writer.
- **Run bar** with progress, elapsed time and Cancel (cancelling stops the run on the server); a warning before leaving the page mid-run.
- **Kept in your browser:** resume, inputs, filters, the last run's results and your review choices survive a reload; **saved resume versions** (restore, compare as a line diff, delete); **saved target roles**.
- **Live Jobs filters** (remote only, posted within N days, hide duplicates), **cover-letter export** (PDF, DOCX, TXT), a due-follow-up count on the Tracker icon.
- **Accessibility:** dialogs trap focus, close on Escape and return focus; closed ones are `inert`; status changes are announced.
- `/health` reports `db` and `ai_ready`, and answers `503` when the database cannot be read.
- `APEX_FIXTURE_JOBS` (saved postings instead of live job boards); USAJobs (`USAJOBS_API_KEY` + `USAJOBS_EMAIL`) and Findwork (`FINDWORK_API_KEY`) sources.
- `tools/benchmark.py --fabrication-judge`: an independent model audit of invented claims, beside the engine's own gate.
- **CI** (`.github/workflows/tests.yml`): ruff (errors only), `run_all.py` and pytest on pushes to `main` and pull requests. New unit tests for the fact gate, parsing, engine flow and server helpers; e2e tests for fact checks, request hardening, core UI and exports, all offline.

### Changed

- **One niche: AI engineering.** Physical therapy is removed (its pack, bench cases and template). `apex_domains.py` now holds one AI-engineering hiring guide plus 10 role families with about 60 titles (AI/LLM application, voice and multimodal, ML, MLOps and AI platform, forward deployed and solutions, full-stack AI, research, evals and safety, data for AI, AI automation). Each family adds its own focus, terms and example lines, read by the engine's review, rewrite and judge and by the job agent's fit score. The titles are offered in the Launch title box and in the job agent's "Add a role" list (`/config` `ROLES`).
- **Cleaner resume layout** (PDF, Word and preview), following current resume-design guidance: each role prints as the title with its dates flush right, then the company and location on a grey line (the layout of Jake's resume, the engineers' favourite); bullets have a true hanging indent; section rules sit clear of the text; the contact line wraps between items, shows links without "https://www." and makes email and links clickable; 0.6-inch margins; multi-page resumes get "Name | Page n of m" in the footer. The Tech template is now that dense, centred, black-headed layout. The template that suits the target role is marked Recommended (Tech for engineering, Classic for physical therapy), and a PDF download reports its page count, with a note when it is over the field's budget.
- **Faster runs:** the engine's independent model calls now run at the same time (review batches, rewrite batches, fact-check batches, both judge orders), and the rewrite returns only the lines it changes instead of every line.
- **Validate before spending.** Every POST is checked (body size, required fields, field sizes, route checks, AI key) before any budget is charged or model called. Limits: request body 2 MB (`/transcribe` 36 MB), resume 40,000 characters, posting 20,000, other fields 60,000. Answers: `400`, `411` (no `Content-Length`), `413`, `503`, `429`.
- **Cost units** (`AI_COSTS`, hosted demo): `/analyze` 12, `/tailor` 8, most single tools 2, `/drift` and `/velocity` 1, `/render-resume` 2 (0 with a `struct`), `/live-jobs` 1; `/apply-all-recommendations` 0.
- `/parse-resume` returns `{struct, dropped}`. `/render-resume` is POST only.
- `/engine/answer` takes `kept`, the first run's `questions`, `order`, `section_order` and diagnosis, and (hosted) `sig`.
- The legacy `/apply-all-recommendations` route merges without a model: only rewrites that replace a real line and pass the fact gate, never keywords.
- Vendor libraries (pdf.js, mammoth, jsPDF, docx) load on first use, still pinned and SRI-checked; the CSP adds `'strict-dynamic'`.
- Live Jobs: sources run in parallel under one 25-second deadline; `limit` is clamped to 1-100; a response over 12 MB is discarded. The Muse is queried by its category names (free text returned nothing).
- `/health` and `/config` report version 11.0 (`/health` said 10.0).
- `python tests/run_all.py` runs the two remaining legacy suites (`r1_scorer`, `r5_ranking`) plus the JS checks.
- CI uses `actions/checkout`, `setup-python` and `setup-node` v7 (Node 24; v4/v5 ran on the deprecated Node 20), Node 22 for the JS checks, and pins `ubuntu-24.04` ahead of `ubuntu-latest` moving to 26.04.
- `fly.toml` runs the demo on Claude Sonnet 5.5 / Haiku 5.5 and sets `APEX_TRUST_PROXY` (no longer baked into the Docker image).

### Removed

- GET `/render-resume` (resume data in a URL).
- The v10 rewrite loop (`improvement_loop`, `fidelity_audit`) and its suites `r2_protected`, `r3_loop`, `r7_e2e`, `r8_weak`, `r10_final`.
- Dead code that wrote unverified text: unreachable duplicate `/transcribe` and `/apply-all-recommendations` handlers, and the unused `linkedin_optimizer`, `outreach_generator` and `_cover_letter` functions.
- Job sources that returned aggregator pages or nothing: Indeed and LinkedIn RSS, Google News, Wellfound, Jooble.

### Security

- **Hosted budget can't be reset by signing in again.** The hourly limit applies per IP as well as per visitor; one IP can start 5 sessions a day; sign-in is limited to 60 attempts per 10 minutes overall (on top of 5 wrong codes per IP).
- **Client IP spoofing.** `Fly-Client-IP` is trusted only on Fly; elsewhere the last `X-Forwarded-For` entry is used (the first one is whatever the client sent).
- **`/engine/answer` target is signed** in hosted mode, so a visitor cannot widen what the fact gate accepts.
- **Visitor data is purged** 21 days after its last use; each visitor is capped at 20 MB of documents and 50 per application.
- **Slow or huge requests:** request size limits, at most 64 requests at once, idle connections dropped after 60 s (was 300 s).
- Resumes, postings and answers are passed to the model as marked data blocks, with an instruction to ignore instructions inside them.
- SMTP and IMAP connections verify the server's TLS certificate.

---

## v11 — 2026-10-09

A new resume engine, Claude support, and a benchmark that measures APEX against a plain chatbot.

### Why

On real resumes v10 shipped the original unchanged (62 → 62, zero lines edited). It kept a rewrite only if a keyword-count score rose; better writing barely moves that score, and markdown in the model's output made the scorer read good rewrites as regressions. Market keywords for an AI-engineer target came back as JavaScript and Java, with percentages invented by the model.

### Added

- **Evidence Engine** (`apex_engine.py`): structure-locked editing (only the summary and experience/project bullets, re-assembled from your original lines), a recruiter-rubric review, a rewrite playbook (outcome first, condense never delete, past tense for completed work), **per-line verification** (deterministic fact gate for numbers, tools and names, then a model audit for additions and omissions; one retry, then revert that line only), bullet and section ordering kept separate from wording, and a blind hiring-manager judge scored in both orders.
- **Evidence questions**: APEX asks for the numbers only you know and rewrites with your answers.
- **Review screen**: every verified edit with its reason and a Keep toggle; "Use this version"; "Restore my original".
- **Measured market demand**: the model proposes role-specific requirements; the code counts how many scraped postings mention each.
- **Claude support** via the official Anthropic SDK (the one optional package). Anthropic-only configs default to Claude Opus 5.5 / Haiku 5.5. Organisation-level keys take `ANTHROPIC_WORKSPACE_ID`.
- **Model layer**: current OpenAI reasoning models (adaptive parameters), JSON mode, retries with backoff, clear out-of-credit messages, and **real per-run cost** (the footer cost was a hard-coded estimate).
- **`tools/benchmark.py`**: the same engine per model on bench resumes, cross-judged by every judge model (same-provider scores shown apart), invented claims counted, cost and time, and a `chat:<model>` baseline = the plain "improve my resume" request. Blind review page included.

### Removed

- **"Apply All Suggestions"**: it regenerated the whole resume with no verification, after the truth-checking step.
- The Phase 5 analysis call and the generic Phase 7 report call (the engine's findings replace both).
- `GETTING_STARTED.md` and `START_HERE.md` (machine-specific notes).

### Fixed

- On phones, an invisible notification covered the Launch button; taps never reached it.
- Engine bugs found in real runs and pinned by tests: mislabelled before/after pairs after reordering, resumes growing longer, wrong tense, deleted experience, a truncated fact-check request, false rejections of ordinary words ("write-offs") and standard names ("Postgres" → "PostgreSQL").

### Privacy

- Personal data removed from the code, tests, docs and the whole git history: test fixtures use fictional people, and commits carry only the GitHub handle and no-reply email.

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

Core rewrite. Fixes a defect that caused the agent to fabricate qualifications and delete credentials while reporting an improved score. Full root-cause analysis in `docs/history/ANALYSIS_v10.md`.

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
