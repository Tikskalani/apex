# Contributing to APEX

Thanks for your interest in making APEX better. This is a solo-built project that grew into something useful — contributions of any kind are welcome.

## Ways to contribute

- **Report bugs** — open an issue with steps to reproduce
- **Suggest features** — open a feature request issue
- **Fix bugs** — pick an issue tagged `good-first-issue` and submit a PR
- **Add a sector** — APEX supports 28 industries; add yours by extending `SECTOR_SOURCES` in `agent_server.py`
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
# Add your OpenAI and JSearch keys to config.json

# 3. Run the server
python agent_server.py

# 4. Open the frontend
# (any browser — no build step needed)
open index.html
```

There is intentionally no build pipeline. The frontend is a single HTML file. Edit, save, refresh the browser. The backend reloads on Python restart only.

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
3. Test against a real resume run before submitting
4. Open a PR with:
   - What changed and why
   - Screenshots if UI changes
   - A note if you tested it on a real run

## What I look for in PRs

- **Doesn't break existing features** — APEX has 16 tabs and 10 endpoints, all working. Check yours doesn't regress others.
- **Honest about tradeoffs** — every change has costs. Note them.
- **No feature creep** — APEX is opinionated. New tabs/endpoints need a strong justification.
- **No breaking config changes** without a migration path

## Code of conduct

Be kind. Be specific. Be patient with people who are learning. Punch up, never down.

If you're not sure how to start, open a discussion before writing code — happy to chat about the right approach for what you have in mind.
