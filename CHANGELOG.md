# Changelog

All notable changes to APEX are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-05-08

### Initial public release

The first stable, production-ready version of APEX. Everything below was built and battle-tested before this release.

### Added

**Core agent**
- 8-phase agent loop (classification → harvest → filter → keywords → score → improve → report → parallel generation)
- Self-improvement loop with 3 iterations and auto-revert on regression
- Sector-aware source routing across 28 industries
- Live job market scraping from JSearch, USAJobs, The Muse, Arbeitnow, Remotive, Google News RSS

**16 analysis tabs (all populate from a single agent run)**
- Market Intelligence — hot/warm/cold/emerging keywords, frequency bars, hard/soft skill split, salary premium analysis
- Resume X-Ray — original vs optimized side-by-side with keyword highlighting
- Gap Report — keyword status table, before/after rewrites, ATS score progression
- Live Jobs — real openings from 5+ APIs with direct apply links
- Cover Letter — AI-generated, market-data-aware
- Interview Prep — STAR-format Q&A, smart questions to ask, salary negotiation tips
- LinkedIn Optimizer — headline + about + ranked skills
- Outreach Generator — 6 templates (DM, cold email, referral, thank-you, negotiation, tips)
- Bullet Strength Ranker — every bullet scored 0-100 with rewrites for the weakest
- Job-Specific Tailor — paste posting → resume rewritten for that exact role
- Smart Job Match — match %, missing keywords, quick fixes, green/red flags
- Salary Negotiation Brief — target/counter/floor + word-for-word script
- Skills Bridge — career-changer translator
- Weakness X-Ray — first-impression score, killer bullets, generic phrases
- Career Velocity — trajectory vs peers, years to next level, market position
- Application Tracker — local pipeline tracking with response-rate calculation

**Engineering**
- Server-Sent Events (SSE) streaming for real-time progress
- 10 RESTful endpoints: `/analyze`, `/tailor`, `/bullets`, `/negotiate`, `/bridge`, `/match`, `/xray`, `/velocity`, `/drift`, `/health`, `/config`
- Production-grade exports: PDF (jsPDF), DOCX (docx.js), TXT
- Intelligent resume parser for clean section detection during export
- localStorage-backed version history (last 10 runs), application tracker, drift detection baseline
- Cost tracker showing exact GPT-4o spend per run
- Server health check with version and JSearch status
- Browser-side public job API integration (The Muse, Arbeitnow, Remotive, USAJobs, JSearch)
- JSearch key auto-load from server `/config` endpoint

**Frontend**
- 3,800+ line single-file vanilla JS implementation
- Zero framework, zero build step
- Drag-drop file upload with PDF + DOCX support (pdf.js + mammoth.js loaded on-demand)
- Premium dark UI with horizontal-scroll tab nav
- Full responsive design with proper max-width constraints

**Backend**
- 1,769-line pure-Python-stdlib server
- Threading-based parallel job harvest (8+ concurrent sources)
- No pip packages required
- Cross-platform (macOS, Windows, Linux)

### Security
- `config.json` excluded via `.gitignore`
- Server `/config` endpoint exposes only the JSearch key, never the OpenAI key
- All user data stays local except authorized OpenAI/JSearch API calls

### Known limitations
- Single-user only (no auth — by design for a local tool)
- USAJobs API may return 401 from browser (CORS/User-Agent constraint) — falls back gracefully
- File upload limited to .txt, .pdf, .doc, .docx (10,000 chars max for textarea paste)

---

## Future versions

See the [Roadmap](README.md#roadmap) section in the README for what's planned next.
