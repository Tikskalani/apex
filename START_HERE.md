# START HERE

**This folder is the single source of truth for APEX.** Everything you need is in it except `config.json`, which holds your API keys and must never leave your machine.

---

## 1. Two-minute setup

```powershell
# Copy the template and add your keys
copy config.example.json config.json
notepad config.json          # paste your OPENAI_KEY and JSEARCH_KEY

# Start the backend
python agent_server.py       # serves on http://localhost:7842
```

Then open `index.html` in your browser. The server badge in the top right should turn green.

SMTP fields are optional. They only power the Job Alerts email feature — leave them blank and everything else works.

---

## 2. The duplication problem, and how to not have it again

You currently have at least four copies of `agent_server.py` on this machine at four different line counts. When something broke, there was no way to tell which one was real. That cost a full session to untangle.

**The rule: this folder is the only place you edit APEX.** Everywhere else is either an archive or garbage.

Known copies to deal with:

| Location | What to do |
|---|---|
| `Downloads\Work Documents\APEX_Project\APEX\apex-github-ready\` | Replace contents with this folder |
| `Downloads\Work Documents\APEX_Project\APEX\` (1,769 lines) | Move to `_archive\` |
| `Resume Agent\Agent\` (1,776 lines) | Move to `_archive\` |
| `ITAI-2372-AI-Applications\apex\` (1,776 lines) | This is your git repo — update it with `git pull`, never by hand-copying |
| `APEX-Resume-Intelligence-Agent-main\` (291 lines) | Original scaffold. Archive or delete |

Archive rather than delete, but archive *once*:

```powershell
mkdir "$HOME\APEX_archive\2026-09-06"
# move old copies in, then never open them again
```

### Let git hold your history

The reason to stop keeping `_v7_backup.html`, `_old.py`, and dated duplicates is that git already does this, correctly:

```bash
git add -A
git commit -m "v10: ATS text-layer export, 4 endpoint fixes, null-byte repair"
git tag v10
git push
```

Every past version stays recoverable (`git checkout v9`), and there is exactly one copy of each file on disk. Backup files in the working folder are the thing that created the confusion — git makes them unnecessary.

---

## 3. Verify before you trust it

After any edit, run these three checks. Each one catches a failure that has actually bitten this project.

```powershell
# A. Python parses — catches syntax errors before the server dies on boot
python -c "import ast; ast.parse(open('agent_server.py', encoding='utf-8').read()); print('OK')"

# B. No null bytes — catches the interrupted-write corruption that hit index.html
python -c "print('nulls:', open('index.html','rb').read().count(b'\x00'))"

# C. File closes properly — catches truncation
python -c "print(repr(open('index.html','rb').read()[-20:]))"
```

Expected: `OK`, `nulls: 0`, and something ending in `</html>`.

---

## 4. The one test that matters

APEX exists to beat applicant tracking systems. The export is where that promise is kept or broken.

1. Paste a resume, run the agent
2. Go to Templates, click **Download PDF**
3. Open the PDF and **try to select the text with your cursor**

**If you can highlight it, it works.** If the text is not selectable, it is an image, and every ATS on earth will read that resume as a blank page.

This is not hypothetical — it was the actual state of the export until this build. Re-run this check any time you touch export code.

---

## 5. What is in this folder

| File | Purpose |
|---|---|
| `agent_server.py` | Backend. Pure stdlib, port 7842, 18 endpoints |
| `index.html` | Frontend. Single file, 16 tabs, CDN libraries |
| `config.example.json` | Template for your keys — copy to `config.json` |
| `config.json` | **You create this.** Gitignored. Never commit |
| `requirements.txt` | Documents the zero-dependency design |
| `.gitignore` | Blocks secrets and backup-file clutter |
| `CHANGELOG.md` | Version history |
| `START_HERE.md` | This file |

### Files from your old folder worth bringing over

These were in `apex-github-ready` and are your own writing. I did not have them, so copy them in manually:

`VISION.md` · `CONTRIBUTING.md` · `LICENSE` · `GETTING_STARTED.md` · `docs\` · `assets\` · `.github\`

Do not recreate them from scratch — the originals are better than anything regenerated.
