# Contributing to APEX

Thanks for your interest in making APEX better. This is a solo-built project that grew into something useful — contributions of any kind are welcome.

## Ways to contribute

- **Report bugs** — open an issue with steps to reproduce
- **Suggest features** — open a feature request issue
- **Fix bugs** — pick an open issue and submit a PR
- **Add a sector** — add yours by extending `SECTOR_SOURCES` in `agent_server.py`
- **Improve a template** — the export PDF/DOCX templates in `index.html` can always be sharper
- **Polish the UI** — better animations, accessibility improvements, mobile layout
- **Write docs** — clearer setup instructions, troubleshooting tips, video walkthroughs

## Development setup

```bash
# 1. Fork and clone
git clone https://github.com/YOUR_USERNAME/apex.git
cd apex

# 2. Create your config
cp config.example.json config.json
# Add an Anthropic key (ANTHROPIC_KEY) or an OpenAI key (OPENAI_KEY); JSearch is optional

# 3. Install and run the server
pip install -r requirements.txt
python agent_server.py

# 4. Open the app at http://localhost:7842/
#    (never open index.html from disk: the page must come from the server)
```

There is intentionally no build pipeline. The frontend is a single HTML file. Edit, save, refresh the browser. The backend reloads on Python restart only.

### Tests (run before every PR)

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m playwright install chromium
python tests/run_all.py            # regression suites
.venv/Scripts/python -m pytest     # unit, API, security and browser tests (offline model stub, no API cost)
```

Changes that touch resume writing should also be checked with `tools/benchmark.py`, which compares models
and the plain-chatbot baseline on the resumes in `bench/cases/` (this one does spend API credits). Changes to
any other AI feature (letters, follow-ups, Bullets, X-Ray, Match, Bridge, Negotiate, answer grading, Tailor) can be
checked with `tools/feature_bench.py`, which runs each one as APEX and as a plain request to the same model and
has a judge compare them blind; use `--features` and `--only` to keep the spend small.

## Code style

**Python:**
- Follow PEP 8 loosely — readability over rules
- Type hints encouraged for new functions
- Keep functions small and focused
- Comment WHY, not WHAT

**JavaScript:**
- ES6+ syntax (arrow functions, template literals, destructuring)
- No frameworks — vanilla JS is intentional
- Functions over classes
- Use `const` by default, `let` when reassigning

**CSS:**
- Use CSS variables for any value used more than once
- Mobile-first when adding new components
- Match the existing design system (see existing variable names in `index.html`)

## Submitting a PR

1. Branch from `main`: `git checkout -b feature/your-feature-name`
2. Make your changes — keep commits focused and well-described
3. Run the tests above; for writing changes, run the benchmark too
4. Open a PR with:
   - What changed and why
   - Screenshots if UI changes
   - A note if you tested it on a real run

## What I look for in PRs

- **Doesn't break existing features** — run the full test suite (it runs on every push to `main` and every pull request in GitHub Actions).
- **Honest about tradeoffs** — every change has costs. Note them.
- **No feature creep** — APEX is opinionated. New tabs/endpoints need a strong justification.
- **No breaking config changes** without a migration path

## Code of conduct

Be kind. Be specific. Be patient with people who are learning. Punch up, never down.

If you're not sure how to start, open a discussion before writing code — happy to chat about the right approach for what you have in mind.
