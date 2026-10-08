# Deploying the APEX demo (Fly.io)

What you get: `https://apex-<name>.fly.dev`, behind an access code you hand out.
Each visitor gets a private pipeline, AI spend is capped per visitor and per day,
and features that would use *your* email account (SMTP, alerts, Gmail import)
are switched off. Running locally (`python agent_server.py`) is unchanged.

Cost: Fly bills per second while the machine runs and it sleeps when idle, so a
lightly used demo is typically a few dollars a month (Fly asks for a card). The
real cost to watch is OpenAI. Step 2 caps it.

## 1. Install the Fly CLI and sign in

```powershell
iwr https://fly.io/install.ps1 -useb | iex
fly auth signup      # or: fly auth login
```

## 2. Give the demo its own OpenAI key, with a budget

In platform.openai.com: create a **new project** called "APEX demo", set a
**monthly budget** on it (Settings → Limits, e.g. $10), and create an API key
in that project. Use this key only for the demo; never your personal one.
If the key leaks or the demo gets popular, the budget is the hard stop.

## 3. Name the app

Pick a name (letters, digits, dashes), e.g. `apex-yourname`. In `fly.toml`,
replace both `apex-CHANGE-ME` with it. Then:

```powershell
cd "path\to\Apex 10"
fly apps create apex-yourname
fly volumes create apex_data --size 1 --region dfw --app apex-yourname --yes
```

## 4. Set the secrets

Secrets live in Fly, never in a file. Generate a session secret and choose an
access code (long and not guessable: it's the only lock on your OpenAI budget):

```powershell
$secret = py -c "import secrets; print(secrets.token_urlsafe(48))"
$code   = py -c "import secrets; print(secrets.token_urlsafe(9))"
fly secrets set --app apex-yourname `
  OPENAI_API_KEY="sk-proj-...your demo key..." `
  APEX_ACCESS_CODE="$code" `
  APEX_SESSION_SECRET="$secret"
"Access code: $code"
```

Optional: `JSEARCH_API_KEY="..."` for the JSearch job source.

Models: set `APEX_MODEL` / `APEX_MODEL_FAST` in `[env]` of `fly.toml` (e.g.
`gpt-6.1-sol` / `gpt-6-luna`, or `claude-sonnet-5-5` / `claude-haiku-5-5`).
For Claude models also set `ANTHROPIC_API_KEY` with `fly secrets set`, and give
that Anthropic workspace a monthly spend limit in the Anthropic console, the
same way as step 2.

## 5. Deploy (one machine)

```powershell
fly deploy --ha=false
```

`--ha=false` matters: the pipeline lives in SQLite on one volume, so the demo
must run as a single machine.

## 6. Check it

- Open `https://apex-yourname.fly.dev`: you should get the sign-in page.
- Wrong code: "That access code is not right." Right code: the app.
- Paste the TESTS.md fixture resume, Launch, and confirm tabs fill.
- `fly logs --app apex-yourname` shows the server window.

## Day to day

| Task | Command |
|---|---|
| Change the access code (signs everyone out on next request) | `fly secrets set APEX_ACCESS_CODE="new-code" APEX_SESSION_SECRET="new-secret"` |
| Raise/lower limits | edit `[env]` in `fly.toml`, then `fly deploy --ha=false` |
| Deploy a new version | run the tests, then `fly deploy --ha=false` |
| Pause the demo | `fly scale count 0 --app apex-yourname` (resume: `count 1`) |
| Back up visitor data | `fly ssh sftp get /data/apex.db apex-backup.db --app apex-yourname` |

## Limits and what to expect

- **Budget units:** a full Launch run costs 10, tailoring 2, most single tools 1.
  Defaults: 40 per visitor per hour, 300 for everyone per UTC day (~30 runs).
  The daily counter is stored on the volume, so restarts don't reset it.
- **Job scraping from a data centre:** some job boards rate-limit or block
  cloud IP addresses, so the live demo may find fewer postings than your PC.
  Sources fail independently; a run only fails if every source returns 0.
- **Visitor data** is tied to the browser session (14 days). Signing out or
  clearing cookies starts a fresh, empty pipeline.
- **Privacy:** visitors paste resumes. The sign-in page tells them their data is
  private to their session and not to paste anything sensitive. If you share
  the demo widely, add a short privacy note and delete old data now and then.
