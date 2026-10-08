# APEX — Career Intelligence Platform

A local AI agent that rewrites your resume against **live job market data**, not a static keyword list.

Scrapes real postings for your target role, extracts what employers are actually asking for this week, scores your resume against it, then rewrites and re-grades itself until the score stops improving.

**Zero pip dependencies.** Pure Python standard library. Runs entirely on your machine.

---

## What makes it different

Most resume tools match your text against a fixed keyword dictionary. APEX harvests live postings first, so the keywords come from the market as it exists today.

**Self-grading loop.** After rewriting, APEX re-scores its own output. If a revision lowers the ATS score, it reverts automatically and tries a different approach. Three iterations, best result kept.

**Sector-aware.** A physical therapist and a machine learning engineer get different sources, different keyword weightings, and different anti-keywords. Role classification runs before anything else.

**Honest about data quality.** When live harvest returns thin results, APEX reports low confidence instead of inventing keywords.

---

## Results from a real run

Physical therapist resume, no cherry-picking:

| Metric | Value |
|---|---|
| Live postings scraped | 71 |
| ATS score | 55 → 85 |
| Total API cost | ~$0.18 |
| Wall-clock time | ~3 minutes |

---

## Quick start

```powershell
copy config.example.json config.json
notepad config.json          # add OPENAI_KEY and JSEARCH_KEY
python agent_server.py       # http://localhost:7842
```

Open `index.html` in your browser. The status badge turns green when the backend is reachable.

Requires Python 3.8+ (3.12 recommended). Nothing to install.

New to the project? Read **[START_HERE.md](START_HERE.md)** first.

---

## How it works

```
Resume + target role
        │
   Phase 0  Role classification — sector, function, search terms, anti-keywords
   Phase 1  Live harvest — 10 job sources in parallel threads
   Phase 2  Retry with alternate terms if results are sparse
   Phase 3  Per-listing relevance filtering — drop off-topic postings
   Phase 4  Confidence scoring — how much do we trust this sample?
   Phase 5  Keyword extraction, cross-validated against real listings
   Phase 6  ATS scoring vs live market
   Phase 7  Self-improvement loop — rewrite, re-grade, revert regressions (×3)
   Phase 8  Parallel generation — cover letter, interview prep,
            LinkedIn, outreach, career velocity
        │
Optimized resume + gap report + 16 tabs of output
```

### Job sources

JSearch (RapidAPI) · USAJobs · Arbeitnow · TheMuse · RemoteOK · Remotive · WeWorkRemotely · Indeed RSS · LinkedIn RSS · Google Jobs RSS

Failures are isolated per-source. One dead API does not stop the run.

---

## Features

**Core** — market keyword intelligence, ATS scoring, self-improving rewrite, before/after gap report

**Tailoring** — paste any posting, get a resume rewritten for that specific role with match scores before and after

**Bullet ranker** — every bullet scored 0–100 on verb strength, quantification, keyword density, specificity. Weakest rewritten automatically

**Interview prep** — behavioral and technical Q&A in STAR format, plus voice practice with Whisper transcription and answer grading

**Negotiation brief** — target ask, opening counter, walk-away minimum, leverage score, and a word-for-word script

**Skills bridge** — for career changers. Maps skills from your current field into the target field's vocabulary

**Weakness X-ray** — first-impression score, killer bullets, generic phrases to delete

**Exports** — ATS-safe PDF with a real text layer, DOCX in Calibri, clean TXT, plus six visual templates for human readers

---

## Export and ATS safety

This matters more than any other feature, so it is worth being explicit.

Applicant tracking systems extract text. A PDF built by screenshotting a web page contains **no text** — only pixels — and parses as an empty document no matter how good the resume is.

APEX builds its ATS export as a genuine text layer via jsPDF:

- Selectable, extractable text
- Standard section headers ATS parsers recognize
- Hyphen bullets, which parse more reliably than typographic bullets
- No tables, no text boxes, no graphics, no multi-column layout
- 0.75" margins, US Letter

**Verify it yourself:** open an exported PDF and try to select the text with your cursor. If you can highlight it, an ATS can read it.

The six visual templates remain available for humans — portfolio sites, direct email to a hiring manager, printing. Use the ATS export for online applications.

---

## Configuration

`config.json` (gitignored, never committed):

| Key | Required | Purpose |
|---|---|---|
| `OPENAI_KEY` | Yes | GPT-4o and Whisper |
| `JSEARCH_KEY` | Recommended | Highest-volume job source. Other sources work without it |
| `SMTP_*` | No | Job alert emails only. Use an App Password for Gmail |

---

## Cost

Roughly **$0.15–0.25** per full optimization at current GPT-4o pricing. Individual tools like the bullet ranker or negotiation brief cost a few cents each.

Compare against $25–50/month subscription resume tools.

---

## Architecture notes

**Backend** — `ThreadingHTTPServer` on port 7842. Server-sent events stream progress so the UI shows live agent reasoning rather than a spinner. Every phase emits typed events.

**Frontend** — one HTML file. No build step, no bundler, no framework. Libraries load from CDN.

**Why zero dependencies?** Portability and demo safety. No virtualenv, no version conflicts, no `pip install` failing on a lab machine five minutes before a presentation.

---

## Project status

Built as coursework for **ITAI 2372 — AI Applications**, Houston Community College, under Prof. Sridhar Ganti.

Current version: **v10**. See [CHANGELOG.md](CHANGELOG.md).

---

## License

See `LICENSE`.
