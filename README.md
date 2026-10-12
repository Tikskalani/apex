# APEX — Career Intelligence Platform

A local AI agent that rewrites your resume for a target role the way a top recruiter would, **without inventing facts**, and shows you every edit with the reason for it.

It scrapes live job postings, measures what employers are actually asking for, rewrites your summary and bullets, fact-checks every line against your own resume, and asks you for the numbers only you know.

---

## What makes it different from asking a chatbot

| | Plain chatbot ("improve my resume") | APEX |
|---|---|---|
| Market data | What the model remembers | Live postings; demand **counted** across them ("Python in 12% of postings") |
| Truth | Often invents metrics, tools and scope | Every edit checked against your resume; failed edits are reverted line by line |
| Missing numbers | Makes them up or leaves them out | Asks you targeted questions ("How many shops actively use it?") and writes your answers in |
| Control | One block of text | Every edit shown with its reason; keep or untick each one |
| Quality check | None | Blind before/after review by a simulated hiring manager for your target role; if it prefers your original, your original is kept |

`tools/benchmark.py` measures this on your resumes: the same model, run through APEX and asked plainly, scored by the same judges, with invented claims counted.

---

## Quick start

```powershell
pip install -r requirements.txt      # one package: the Anthropic SDK
python agent_server.py
```

Then open **http://localhost:7842/**. Don't open `index.html` from disk: the page must come from the server.

The server starts without a key. Until you add one, the page shows a setup card and AI features stay off. To add one:

```powershell
copy config.example.json config.json
notepad config.json                  # ANTHROPIC_KEY (or OPENAI_KEY); JSEARCH_KEY optional
```

then restart the server. Requires Python 3.10+ (3.12 recommended).

---

## How it works

```
Resume + target role (+ optional job posting)
        │
   Scrape     live postings from several job sources in parallel, filter for relevance
   Measure    requirements proposed by the model, demand counted across postings
   Classify   which requirements your resume actually demonstrates
   Engine     recruiter review → rewrite → per-line fact check → blind judge (with a veto)
   Report     what a recruiter would flag, what you don't show yet, questions for you
   Extras     cover letter, interview prep, LinkedIn, outreach, career velocity (fact-checked)
        │
Edited resume (you approve each change) + gap report + pipeline tracker
```

**The Evidence Engine** (`apex_engine.py`):
- **Structure-locked edits.** Only your summary, experience/project bullets and the order of your skills are editable, and the document is rebuilt from your original lines, so formatting can't drift and sections like Education and licences are never touched. If your resume has no summary, it can write one.
- **Per-line verification.** A code check confirms every number (with its unit and scale), tool and name in an edit already appears in that role's text or your answers. The model then audits for anything added *or* deleted. A failed edit is retried once, then reverted on its own.
- **A blind judge with a veto.** A simulated hiring manager scores the before and after in both orders, averaged. If it scores the rewrite lower, your original is kept and you're told why.
- **Your answers.** Answer its questions and only those lines are rewritten, with your answers as evidence; the edits you kept stay.

**Measured in the v11 release on a real AI-engineer resume** (Claude Opus 5.5): hiring-manager score 62 → 66, 15 verified edits, 0 invented claims, 8 evidence questions, about $0.82 and 4 minutes. On strong resumes the remaining gap is usually the evidence, not the writing. Answering the questions is the biggest upgrade.

---

## Features

- **Resume X-Ray:** every verified edit with its reason, keep/untick toggles, "Rewrite with my answers"
- **Market Intel:** measured requirement demand; drift check that re-counts your last run's requirements in today's postings
- **Gap Report:** specific recruiter flags, unmet requirements with demand, next steps
- **Tracker:** local job pipeline (SQLite): statuses, follow-ups due, saved apply kits, drafted follow-up emails
- **Tailor & Apply:** per-posting tailored resume (the same verified engine, aimed at that posting) and cover letter, saved to the pipeline
- **Fact-checked writing:** cover letters, interview sample answers, LinkedIn copy, outreach and follow-up messages, salary leverage points and suggested bullet rewrites go through the same check; anything it can't verify is withheld and the page says why
- **Negotiate:** based on pay ranges stated in live postings when there are enough; otherwise labelled as an AI estimate
- **Interview, Career Bridge, Bullets, Weakness X-Ray, Match, LinkedIn, Outreach, Live Jobs** (with remote, date and duplicate filters), **Job Alerts** (email, local only)
- **Exports:** ATS-safe PDF with a real text layer (Noto Sans embedded, so accented and non-Latin names survive), DOCX, TXT, plus visual templates; cover letters as PDF, DOCX or TXT
- **Kept in your browser:** your resume, inputs and last results survive a reload; save named resume versions (restore, compare) and target roles to switch between
- **Long runs** show progress and elapsed time and can be cancelled; a cancelled run stops spending on the server

Voice answers in the Interview tab use OpenAI speech-to-text and need an `OPENAI_KEY`.

---

## Models

Set `MODEL` (writing, review, judging) and `MODEL_FAST` (extraction) in `config.json`. Any Claude (`claude-...`) or OpenAI (`gpt-...`) model works. Optionally set `MODEL_AUDIT` (fact checks) and `MODEL_JUDGE` (the blind judge) so the writer doesn't grade its own work.

- **Only an Anthropic key:** defaults to `claude-opus-5-5` and `claude-haiku-5-5`.
- **Organisation-level Anthropic key:** also set `ANTHROPIC_WORKSPACE_ID`.
- **Choosing a model:** run `tools/benchmark.py` to compare models on your own resumes before picking.

Cost is measured per run (token usage × model price) and shown in the footer.

---

## Security and privacy

- **Local by default.** The server listens on your machine only. Your pipeline stays in `apex.db` beside the server; your resume, inputs and saved versions stay in your browser's local storage. Resume text goes to the model provider you configured.
- **Same-origin only.** The server answers only its own page: no wildcard CORS, foreign origins refused, static files allowlisted, and a strict Content-Security-Policy with a per-load nonce. CDN libraries are pinned and SRI-checked.
- **Bad requests cost nothing.** Inputs are checked (required fields, size limits) before any model call.
- **Keys stay put.** `config.json` holds your keys, is gitignored, and is never served.
- **Hosted demo mode** (access code, per-visitor private data, AI spend caps per visitor, per network and per day): see [DEPLOY.md](DEPLOY.md).

---

## Development

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m playwright install chromium

python tests/run_all.py                          # regression suites + JS checks (Node optional)
.venv\Scripts\python -m pytest                   # unit, API, security and Playwright browser tests
.venv\Scripts\python -m ruff check --select F,E9 agent_server.py apex_engine.py apex_store.py tools tests
```

The tests run offline: an offline model stub and saved job postings, never your keys, credits or the live job boards (browser tests still load the CDN libraries). GitHub Actions runs the same three steps on pushes to `main` and on pull requests.

See [CONTRIBUTING.md](CONTRIBUTING.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/API.md](docs/API.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

---

## License

See [LICENSE](LICENSE). The bundled Noto Sans fonts are under the SIL Open Font License ([assets/OFL.txt](assets/OFL.txt)).
