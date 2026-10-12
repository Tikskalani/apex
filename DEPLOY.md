# Deploying the APEX demo (Fly.io)

What you get: `https://apex-<name>.fly.dev`, behind an access code you hand out.
Each visitor gets a private pipeline, AI spend is capped per visitor, per network
and per day, and features that would use *your* email account (SMTP, alerts,
Gmail import) are switched off. Running locally (`python agent_server.py`) is
unchanged.

Cost: Fly bills per second while the machine runs and it sleeps when idle, so a
lightly used demo is typically a few dollars a month (Fly asks for a card). The
real cost to watch is the AI provider. Step 2 caps it.

## 1. Install the Fly CLI and sign in

```powershell
iwr https://fly.io/install.ps1 -useb | iex
fly auth signup      # or: fly auth login
```

## 2. Give the demo its own Anthropic key, with a spend limit

In console.anthropic.com: create a **workspace** called "APEX demo", set a
**monthly spend limit** on it (e.g. $10), and create an API key inside that
workspace. Use this key only for the demo, never your personal one. If the key
leaks or the demo gets popular, the workspace limit is the hard stop.

(OpenAI works too: a separate project with a monthly budget, and `OPENAI_API_KEY`
below instead. Set `APEX_MODEL` / `APEX_MODEL_FAST` in `fly.toml` to OpenAI models.)

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
access code (long and not guessable: it is the only lock on your AI budget):

```powershell
$secret = py -c "import secrets; print(secrets.token_urlsafe(48))"
$code   = py -c "import secrets; print(secrets.token_urlsafe(9))"
fly secrets set --app apex-yourname `
  ANTHROPIC_API_KEY="sk-ant-...your demo key..." `
  APEX_ACCESS_CODE="$code" `
  APEX_SESSION_SECRET="$secret"
"Access code: $code"
```

Optional job sources (each is skipped without its key):

| Secret | Source |
|---|---|
| `JSEARCH_API_KEY` | JSearch (many boards, best for local and non-tech roles) |
| `USAJOBS_API_KEY` + `USAJOBS_EMAIL` | USAJobs (government roles; free key from developer.usajobs.gov) |
| `FINDWORK_API_KEY` | Findwork.dev |

Models: `fly.toml` sets `APEX_MODEL = "claude-sonnet-5-5"` and
`APEX_MODEL_FAST = "claude-haiku-5-5"` for the demo. Opus is the local default
(best output) but costs about twice as much per run. Optionally set
`APEX_MODEL_AUDIT` so the fact-check audit runs on a different model than the writer.

## 5. Deploy (one machine)

```powershell
fly deploy --ha=false
```

`--ha=false` matters: the pipeline lives in SQLite on one volume, so the demo
must run as a single machine.

## 6. Check it

- Open `https://apex-yourname.fly.dev`: you should get the sign-in page.
- Wrong code: "That access code is not right." Right code: the app.
- `https://apex-yourname.fly.dev/health` shows `"db": "ok"` and `"ai_ready": true`.
- Paste the TESTS.md fixture resume, Launch, and confirm the tabs fill.
- `fly logs --app apex-yourname` shows the server window.

## Day to day

| Task | Command |
|---|---|
| Change the access code (signs everyone out) | `fly secrets set APEX_ACCESS_CODE="new-code" APEX_SESSION_SECRET="new-secret"` (rotate both: old sessions stay valid until the secret changes) |
| Raise/lower limits | edit `[env]` in `fly.toml`, then `fly deploy --ha=false` |
| Deploy a new version | run the tests, then `fly deploy --ha=false` |
| Pause the demo | `fly scale count 0 --app apex-yourname` (resume: `count 1`) |
| Back up visitor data | `fly ssh sftp get /data/apex.db apex-backup.db --app apex-yourname` |
| Restore a backup | `fly ssh sftp put apex-backup.db /data/apex.db --app apex-yourname`, then `fly machine restart` |

Fly also snapshots volumes daily (kept 5 days by default): `fly volumes snapshots list apex_data`.
For uptime alerts, point any uptime monitor at `/health` (it returns 503 if the
database cannot be read).

## Limits and what to expect

- **Budget units:** a full Launch run costs 12, tailoring 8, answering the
  engine's questions 6, most single tools 1-2. Defaults: 40 per visitor and per
  network (IP) per hour, 300 for everyone per UTC day (~25 runs). Signing in
  again does not reset a budget, and one network can open at most 5 sessions a
  day. Requests that are refused (bad input, too large) cost nothing. The daily
  counter is stored on the volume, so restarts don't reset it.
- **Request limits:** resumes up to 40,000 characters, postings up to 20,000,
  request bodies up to 2 MB.
- **Job scraping from a data centre:** some job boards rate-limit cloud IP
  addresses, so the live demo may find fewer postings than your PC. Sources fail
  independently; the run reports which were skipped.
- **Visitor data** is tied to the browser session (14 days) and deleted a week
  after the session ends. Each visitor can store up to 20 MB of documents.
- **Privacy:** visitors paste resumes. The sign-in page tells them their data is
  private to their session and not to paste anything sensitive.
