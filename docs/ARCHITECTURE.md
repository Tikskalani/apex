# APEX Architecture

This document explains how APEX works internally. If you're contributing or just curious about the engineering decisions, this is the place to read.

## High-level flow

```
┌──────────────┐    HTTP POST /analyze    ┌──────────────┐
│   Browser    │  ────────────────────→   │   Server     │
│ index.html   │  ←──── SSE stream  ───── │ agent_server │
└──────────────┘   (every step live)      └──────────────┘
                                                 │
                                          ┌──────┴───────┐
                                          │              │
                                    OpenAI GPT-4o    JSearch + others
                                    (paid, $0.18/run) (free / freemium)
```

The browser opens a streaming connection (`text/event-stream`) and the server pushes JSON events as the agent progresses. Every phase of the agent emits a `step`, every interesting moment emits a `log`, and each tab's data arrives as a typed `*_data` event when ready.

## The 8 phases

### Phase 0 — Role classification
Input: job title + industry + seniority + (optional) job description.

Output: a structured classification with:
- `sector` (one of 28: tech, healthcare, real_estate, etc.)
- `function` (clinical, engineering, sales, etc.)
- `primary_search_term` (often cleaner than the user's input)
- `alternate_terms` (synonyms used as fallback in Phase 2)
- `expected_themes` (what good listings should mention)
- `anti_keywords` (terms that signal off-topic listings)

This single GPT-4o call costs ~1¢ but informs every subsequent decision.

### Phase 1 — Live harvest (parallel)
Threads spawn for each source in `SECTOR_SOURCES[sector]`. Each source has its own adapter:
- `src_jsearch` (RapidAPI — paid, returns 25 structured listings)
- `src_arbeitnow` (free public API)
- `src_themuse` (free public API, healthcare/tech/finance categorized)
- `src_usajobs` (government roles)
- `src_google` (Google News RSS — broad signal)
- `src_remoteok` (remote roles)
- `src_indeed_rss` (Indeed RSS — limited reliability)
- `src_linkedin_rss` (LinkedIn RSS — often blocked)

Each adapter returns a list of text blobs (job posting bodies). These are NOT structured listings — they're raw text used downstream for keyword extraction.

The threads join with a 25-second timeout. Whatever returned in time gets used. This is a deliberate "fail fast on slow sources" design.

### Phase 2 — Retry (conditional)
If Phase 1 returned fewer than `MIN_LISTINGS` (currently 12), the agent retries the top 3 sources with each `alternate_term` from Phase 0. Skipped if Phase 1 was sufficient.

### Phase 3 — Per-listing relevance filter
Each listing is scored against:
- target words (from the job title)
- sector signals (from Phase 0's `expected_themes`)
- anti-keywords (penalize off-topic listings)

Scoring is a simple weighted sum — fast, deterministic, no AI cost. Listings below the threshold are dropped. If too few survive, the threshold relaxes; if still too few, the top 10 by score are kept regardless.

The result is a clean, deduped corpus of relevant text. This is the foundation for everything else.

### Phase 4 — Keyword intelligence
A single GPT-4o call analyzes the corpus and extracts:
- `hot` keywords (high-frequency, must-have)
- `warm` keywords (medium-frequency, advantage)
- `cold` keywords (low-frequency, niche)
- `emerging` keywords (trending up)
- `hard_skills` vs `soft_skills` (Jobscan-style split)
- `salary_premium_skills` (skills that command higher pay in the data)
- `frequency` bars for the visualization tab

Cost: ~3¢ for ~16,000 chars of corpus.

### Phase 5 — ATS scoring
Compares the user's resume against the keyword set:
- `atsScoreBefore` — current state
- `atsScoreAfter` — projected state after optimization
- `keywordMatchPct` — % of market keywords the resume contains
- `topGaps` — what's missing
- `strengths` — what's already strong
- `addedKeywords` — what the optimizer will inject

This is a single GPT-4o call (~4¢) that returns the analysis JSON.

### Phase 6 — Self-improvement loop
This is the core innovation. Three iterations, each focused:

```python
ITER_FOCUS = {
    1: "Inject all validated keywords naturally. Strong action verbs. No passive voice.",
    2: "Quantify every achievement. STAR format for experience bullets.",
    3: "Improve readability and flow.",
}
```

For each iteration:
1. Generate a candidate rewrite
2. Self-grade the candidate against the same market keywords (1 GPT-4o call)
3. If `new_score > best_score`: keep the candidate
4. If `new_score < best_score`: revert to the previous best
5. Move to next iteration

This is more reliable than a single optimization pass because:
- Each iteration has a focused mandate (not "make it better" — that's vague)
- Bad changes are caught and reverted
- The final output is the best validated version, not the latest version

Cost: ~9¢ for the full loop (3 candidates + 3 self-grades).

### Phase 7 — Gap report
Generates a structured report for the Gap Report tab:
- `keywords[]` (status table: added / present / missing)
- `changes[]` (before/after bullet rewrites with explanations)
- `recommendations[]` (specific actions for the user)
- `salaryInsights[]` (market data)

One GPT-4o call (~3¢).

### Phase 8 — Parallel generation
Five generators fire simultaneously in separate threads:
- `gen_cover_letter` — sector-aware cover letter
- `gen_interview` — behavioral + technical Q&A
- `gen_linkedin` — headline, about, top skills
- `gen_outreach` — 6 templates (DM, email, referral, thanks, negotiation, tips)
- `gen_velocity` — career velocity score with trajectory

Each is independent — if one fails, the others still complete. Each emits its own `*_data` SSE event when done. Total Phase 8 cost: ~8¢.

## SSE event protocol

The frontend's `handleServerEvent(ev)` switch dispatches on `ev.type`:

| Event | When | Payload |
|---|---|---|
| `log` | Anytime | `{msg: string}` |
| `step` | Phase boundaries | `{id: 'market'\|'heat'\|'analyze'\|'rewrite'\|'report', status: 'running'\|'done', msg?: string}` |
| `market_data` | After Phase 4-5 | `{data: {hot, warm, cold, emerging, hard_skills, soft_skills, ...}}` |
| `resume_data` | After Phase 6 | `{original, optimized, added}` |
| `report_data` | After Phase 7 | `{data: {keywords, changes, recommendations, ...}}` |
| `cover_letter_data` | When generator finishes | `{letter}` |
| `interview_data` | When generator finishes | `{data: {behavioral, technical, questions_to_ask, ...}}` |
| `linkedin_data` | When generator finishes | `{data: {headline, about, skills}}` |
| `outreach_data` | When generator finishes | `{data: {linkedin_dm, cold_email, ...}}` |
| `velocity_data` | When generator finishes | `{data: {velocity_score, trajectory, ...}}` |
| `jobs_data` | After Phase 3 | `{jobs: [{source, text, query}]}` |
| `cost_data` | After Phase 8 | `{usd}` |
| `error` | On any uncaught exception | `{msg}` |
| `done` | Final | `{msg}` |

For the standalone endpoints (`/bullets`, `/tailor`, etc.), additional event types fire (`bullet_data`, `tailor_data`, etc.).

## Why pure Python stdlib

The decision to use `http.server` instead of FastAPI/Flask was deliberate:

**Pros**
- Zero pip install required — clone and run
- Smaller install footprint (no dependency tree)
- Great for portfolio demonstrations (people see "no dependencies" as a positive signal)
- Lower attack surface

**Cons**
- `ThreadingHTTPServer` doesn't scale to many concurrent users (limit ~50 simultaneous connections)
- No built-in async support
- Verbose request handling

**When this becomes a problem:** If APEX moves to a hosted multi-user version, migrate to FastAPI. The endpoint handlers are written in a way that maps directly to FastAPI route handlers — should take a day to port.

## Why a single-file frontend

Same philosophy: zero build step. Edit `index.html`, refresh browser, see changes.

**Pros**
- No webpack/vite/parcel/turbopack
- Easy for portfolio reviewers to inspect (one file = one mental model)
- Loads instantly (no JS bundle to download and parse)
- Easy to host anywhere (GitHub Pages, Netlify, S3, anything serving a single HTML file)

**Cons**
- 3,800-line file is harder to navigate than a component-per-file React app
- Limited reusability across other projects
- Manual state management (no React hooks, no Redux)

**When this becomes a problem:** If the app exceeds ~5,000 lines of JS, refactor to React + Vite. The current size is at the edge of comfortable.

## Cost economics

Per-run cost breakdown (GPT-4o pricing as of 2026):

| Phase | Calls | Input tokens | Output tokens | Cost |
|---|---|---|---|---|
| 0. Classification | 1 | 800 | 400 | $0.012 |
| 4. Keywords | 1 | 16000 | 1500 | $0.055 |
| 5. ATS scoring | 1 | 4000 | 1200 | $0.022 |
| 6. Self-improvement (×3 + 3 self-grades) | 6 | 12000 | 6000 | $0.090 |
| 7. Gap report | 1 | 4000 | 2000 | $0.025 |
| 8. Parallel × 5 generators | 5 | 16000 | 7500 | $0.075 |
| **Total** | **15** | **52,800** | **18,600** | **~$0.18** |

JSearch and other APIs are free at this volume.

A user running 10 optimizations per month costs ~$1.80 — vs $29/month for Jobscan. The economics make hosted SaaS extremely viable.

## Failure modes

What happens when things go wrong:

- **OpenAI rate-limited / down**: The current run fails with a clear error. The frontend shows the error banner. Local fallbacks (e.g. client-side bullet scorer) provide a degraded but functional experience.
- **JSearch quota exhausted**: Falls back to free sources (Arbeitnow, Google News, USAJobs, etc.). Confidence drops to "medium" or "low" but the run still completes.
- **Sparse listings (under 10)**: Phase 2 retries with alternate terms. If still sparse, the agent uses sector-knowledge fallback (no live data, but still useful). Confidence is reported honestly.
- **A Phase 8 generator fails**: The other 4 still complete and populate their tabs. Failed tab shows an error message. The main optimization is unaffected.
- **Browser closes mid-run**: Server detects broken pipe, stops emitting events, cleans up. Partial results are not persisted (acceptable since runs are cheap).

## What I'd change for v2

Honest tech debt:

1. **`http.server` → FastAPI** — the threading model has hit its limit for any concurrent multi-user scenario
2. **Response caching** — the same role + sector should reuse market data for 24 hours; would cut average cost in half
3. **Streaming GPT-4o responses** — currently we wait for full responses; streaming would make the UI feel even more responsive
4. **Resume parser hardening** — the section-detection heuristic in `parseResume()` is good but breaks on non-standard layouts. Better to use a proper parser like `pyresparser` or a small fine-tuned model.
5. **Test coverage** — there are no automated tests. For a hobby project that's acceptable; for production it's not.
6. **Mobile UI** — works but isn't optimized. A hosted version needs proper mobile breakpoints.
7. **Telemetry** — no visibility into which features get used or where users drop off. Need before optimizing further.
