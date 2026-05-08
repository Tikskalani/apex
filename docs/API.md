# API Reference

APEX exposes 11 HTTP endpoints on `localhost:7842`. All POST endpoints stream Server-Sent Events back to the client.

## Authentication

None. APEX is a local single-user tool. Auth would be added when migrating to a hosted multi-user version.

## CORS

All endpoints respond with permissive CORS headers (`Access-Control-Allow-Origin: *`) so the frontend can call them from `file://` or `http://` origins.

## Endpoints

### `GET /health`
Health check. Returns server status, JSearch configuration state, and supported sectors.

**Response**
```json
{
  "status": "ok",
  "version": "7.0",
  "jsearch": "active",
  "sectors": ["tech", "healthcare", "real_estate", "finance", "..."],
  "modes": ["optimize"],
  "endpoints": ["/analyze", "/drift", "/match", "/xray", "/grade-answer", "/velocity"]
}
```

---

### `GET /config`
Returns only the JSearch key (never the OpenAI key) so the frontend can call JSearch directly from the browser.

**Response**
```json
{ "JSEARCH_KEY": "rapidapi-key-here" }
```

---

### `POST /analyze`
The main agent loop. Runs all 8 phases and emits SSE events as each phase completes.

**Request body**
```json
{
  "jobTitle": "Physical Therapist",
  "industry": "healthcare",
  "seniority": "mid",
  "jobDesc": "Optional pasted job posting text",
  "resume": "Full resume text",
  "mode": "optimize"
}
```

**Response** — `text/event-stream` with multiple events:
- `log` (many) — human-readable progress messages
- `step` (5+) — phase boundary markers
- `market_data` — Phase 4-5 output
- `resume_data` — Phase 6 output (optimized resume)
- `report_data` — Phase 7 output (gap report)
- `cover_letter_data`, `interview_data`, `linkedin_data`, `outreach_data`, `velocity_data` — Phase 8 outputs (parallel)
- `jobs_data` — raw harvested listings
- `cost_data` — exact GPT-4o spend
- `done` — final marker

See [`ARCHITECTURE.md`](ARCHITECTURE.md#sse-event-protocol) for full event schemas.

---

### `POST /tailor`
Rewrite a resume specifically for one job posting.

**Request body**
```json
{
  "resume": "Full resume text",
  "jobTitle": "Senior PT",
  "jobPosting": "Pasted job description",
  "sector": "healthcare"
}
```

**Response** — SSE stream emitting `tailor_data`:
```json
{
  "type": "tailor_data",
  "data": {
    "match_before": 62,
    "match_after": 91,
    "tailored_resume": "Full rewritten resume text"
  }
}
```

---

### `POST /bullets`
Score every bullet in the resume and rewrite the weakest.

**Request body**
```json
{
  "resume": "Full resume text",
  "jobTitle": "Physical Therapist",
  "sector": "healthcare",
  "keywords": ["manual therapy", "gait training", "..."]
}
```

> **Note:** `keywords` MUST be an array of strings. If you have an array of `{name, freq}` dicts (e.g. from `marketData.hot`), extract the names first.

**Response** — SSE stream emitting `bullet_data`:
```json
{
  "type": "bullet_data",
  "data": {
    "ranked_bullets": [
      {
        "text": "Led manual therapy program for 50+ patients/week",
        "score": 92,
        "rank": 1,
        "strengths": ["strong action verb", "quantified"],
        "weaknesses": [],
        "rewrite": null
      },
      {
        "text": "Helped patients with their care",
        "score": 28,
        "rank": 12,
        "strengths": [],
        "weaknesses": ["weak verb 'helped'", "no metrics", "vague"],
        "rewrite": "Delivered manual therapy to 30+ patients/week, achieving 94% satisfaction"
      }
    ],
    "average_score": 67,
    "strongest_bullet": "...",
    "weakest_bullet": "...",
    "overall_verdict": "Mid-quality with 4 bullets needing rewrites"
  }
}
```

---

### `POST /negotiate`
Generate a salary negotiation brief for the target role.

**Request body**
```json
{
  "jobTitle": "Physical Therapist",
  "sector": "healthcare",
  "seniority": "mid",
  "location": "Houston, TX",
  "resume": "Full resume text",
  "marketData": { "...": "from a previous /analyze run" }
}
```

**Response** — SSE stream emitting `negotiate_data`:
```json
{
  "type": "negotiate_data",
  "data": {
    "target_ask": "$95,000",
    "opening_counter": "$98,000",
    "minimum": "$88,000",
    "leverage_score": 75,
    "script": "Word-for-word negotiation script..."
  }
}
```

---

### `POST /bridge`
Map old-role language to new-role language for career changers.

**Request body**
```json
{
  "fromRole": "Physical Therapist",
  "toRole": "UX Researcher",
  "resume": "Full resume text",
  "sector": "tech"
}
```

**Response** — SSE stream emitting `bridge_data`:
```json
{
  "type": "bridge_data",
  "data": {
    "mappings": [
      { "old": "Treated patients", "new": "Conducted user research", "why": "Both involve assessing needs and tailoring interventions" }
    ]
  }
}
```

---

### `POST /match`
Score how well the resume matches a specific posting (no rewrite).

**Request body**
```json
{
  "resume": "Full resume text",
  "jobPosting": "Full posted job description"
}
```

**Response** — SSE stream emitting `match_data`:
```json
{
  "type": "match_data",
  "data": {
    "match_pct": 78,
    "missing_keywords": ["EMR", "Epic"],
    "quick_fixes": ["Add EMR to skills section"],
    "green_flags": ["5+ years experience matches"],
    "red_flags": ["Missing required certification"]
  }
}
```

---

### `POST /xray`
Weakness X-Ray analysis — first-impression score, killer bullets, generic phrases.

**Request body**
```json
{
  "resume": "Full resume text",
  "jobTitle": "Physical Therapist",
  "sector": "healthcare"
}
```

**Response** — SSE stream emitting `weakness_data`:
```json
{
  "type": "weakness_data",
  "data": {
    "first_impression_score": 62,
    "reaction": "Mid-tier — competent but not memorable",
    "killer_bullets": [
      { "text": "Worked on patient care", "why": "Vague, no impact" }
    ],
    "generic_phrases": ["team player", "results-driven"]
  }
}
```

---

### `POST /velocity`
Career velocity score — trajectory, market position, years to next level.

**Request body**
```json
{
  "jobTitle": "Physical Therapist",
  "sector": "healthcare",
  "seniority": "mid",
  "resume": "Full resume text"
}
```

**Response** — SSE stream emitting `velocity_data`:
```json
{
  "type": "velocity_data",
  "data": {
    "velocity_score": 72,
    "trajectory": "↑ Above average",
    "years_to_next_level": 2.3,
    "market_position": "Top 28% for PTs with 5 yrs experience",
    "content": "Detailed analysis text..."
  }
}
```

---

### `POST /drift`
Re-scrape live market and compare against a baseline ATS score to detect market drift.

**Request body**
```json
{
  "jobTitle": "Physical Therapist",
  "sector": "healthcare",
  "resume": "Full resume text",
  "baseline_score": 85
}
```

**Response** — SSE stream with drift analysis. Emits a warning if current score has dropped more than 5 points from baseline.

---

## Error handling

All endpoints emit `{"type": "error", "msg": "..."}` on uncaught exceptions and return HTTP 200 with the error inside the SSE stream (rather than HTTP 500). This lets the frontend display partial results plus the error gracefully.

For input validation failures (missing `jobTitle`, missing `resume`, etc.), endpoints return HTTP 400 with a JSON error body before opening the SSE stream.
