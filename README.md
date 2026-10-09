# APEX — Career Intelligence Platform

A local AI agent that rewrites your resume for a target role the way a top recruiter would, **without inventing a single fact**, and shows you every edit with the reason for it.

It scrapes live job postings, measures what employers are actually asking for, rewrites your summary and bullets, fact-checks every line against your own resume, and asks you for the numbers only you know.

---

## What makes it different from asking a chatbot

| | Plain chatbot ("improve my resume") | APEX |
|---|---|---|
| Market data | What the model remembers | Live postings; demand **counted** across them ("Python in 12% of postings") |
| Truth | Often invents metrics, tools and scope | Every edit checked against your resume; failed edits are reverted line by line |
| Missing numbers | Makes them up or leaves them out | Asks you targeted questions ("How many shops actively use it?") and writes your answers in |
| Control | One block of text | Every edit shown with its reason; keep or untick each one |
| Quality check | None | Blind before/after review by a simulated hiring manager for your target role |

`tools/benchmark.py` measures this on real resumes: the same model, run through APEX and asked plainly, scored by the same judges, with invented claims counted.

---

## Quick start

```powershell
copy config.example.json config.json
notepad config.json                  # add ANTHROPIC_KEY (or OPENAI_KEY); JSEARCH_KEY optional
pip install -r requirements.txt      # one package: the Anthropic SDK
python agent_server.py
```

Then open **http://localhost:7842/**. Don't open `index.html` from disk: the page must come from the server.

Requires Python 3.10+ (3.12 recommended).

---

## How it works

```
Resume + target role (+ optional job posting)
        │
   Scrape     live postings from 10+ sources in parallel, filter for relevance
   Measure    requirements proposed by the model, demand counted across postings
   Classify   which requirements your resume actually demonstrates
   Engine     recruiter review → rewrite → per-line fact check → blind judge
   Report     what a recruiter would flag, what you don't show yet, questions for you
   Extras     cover letter, interview prep, LinkedIn, outreach, career velocity
        │
Edited resume (you approve each change) + gap report + pipeline tracker
```

**The Evidence Engine** (`apex_engine.py`):
- **Structure-locked edits.** Only your summary and experience/project bullets are editable, and the document is rebuilt from your original lines, so formatting can't drift and sections like Education and licences are never touched.
- **Per-line verification.** A code check confirms every number, tool and name in an edit already appears in your resume or your answers. The model then audits for anything added *or* deleted. A failed edit is retried once, then reverted on its own.
- **A blind judge.** A simulated hiring manager scores the before and after in both orders, averaged.

**Measured on a real AI-engineer resume** (Claude Opus 5.5): hiring-manager score 62 → 66, 15 verified edits, 0 invented claims, 8 evidence questions, about $0.82 and 4 minutes. On strong resumes the remaining gap is usually the evidence, not the writing. Answering the questions is the biggest upgrade.

---

## Features

- **Resume X-Ray:** every verified edit with its reason, keep/untick toggles, "Rewrite with my answers"
- **Market Intel:** measured requirement demand; drift check against your last run
- **Gap Report:** specific recruiter flags, unmet requirements with demand, next steps
- **Tracker:** local job pipeline (SQLite): statuses, follow-ups due, saved apply kits, drafted follow-up emails
- **Tailor & Apply:** per-posting tailored resume and cover letter, saved to the pipeline
- **Interview, Negotiate, Career Bridge, Bullets, Weakness X-Ray, LinkedIn, Outreach**
- **Exports:** ATS-safe PDF with a real text layer, DOCX, TXT, plus visual templates

Voice answers in the Interview tab use OpenAI speech-to-text and need an `OPENAI_KEY`.

---

## Models

Set `MODEL` (writing, review, judging) and `MODEL_FAST` (extraction) in `config.json`. Any Claude (`claude-...`) or OpenAI (`gpt-...`) model works.

- **Only an Anthropic key:** defaults to `claude-opus-5-5` and `claude-haiku-5-5`.
- **Organisation-level Anthropic key:** also set `ANTHROPIC_WORKSPACE_ID`.
- **Choosing a model:** run `tools/benchmark.py` to compare models on your own resumes before picking.

Cost is measured per run (token usage × model price) and shown in the footer.

---

## Security and privacy

- **Local by default.** Everything runs on your machine; your data stays in `apex.db` beside the server.
- **Same-origin only.** The server answers only its own page: no wildcard CORS, foreign origins refused, static files allowlisted, and a strict Content-Security-Policy with a per-load nonce.
- **Keys stay put.** `config.json` holds your keys, is gitignored, and is never served.
- **Hosted demo mode** (access code, per-visitor private data, AI spend caps): see [DEPLOY.md](DEPLOY.md).

---

## Development

```bash
python tests/run_all.py            # regression suites
.venv/Scripts/python -m pytest     # unit, API, security and Playwright browser tests (offline model stub)
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/API.md](docs/API.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

---

## License

See [LICENSE](LICENSE).
