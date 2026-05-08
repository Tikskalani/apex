# 📤 How to upload APEX to GitHub

Step-by-step guide to publishing this repo. Read each section in order — should take 15-20 minutes.

---

## Before you start

**You'll need:**
- A GitHub account ([sign up here](https://github.com/join) if you don't have one)
- Git installed on your machine ([install instructions](https://git-scm.com/downloads))
- This `apex-github-ready/` folder downloaded and extracted

---

## Step 1 — Verify nothing sensitive is in the folder

⚠️ **CRITICAL: Before pushing anything to GitHub, double-check there are no API keys.**

Open these files and verify:

- ✅ `config.example.json` should have placeholder text only (not real keys)
- ✅ `config.json` should NOT exist in this folder
- ✅ Search the folder for your real OpenAI key — it should not appear anywhere

```bash
# Run this in the apex-github-ready folder to scan for the start of an OpenAI key
grep -r "sk-proj-" .
# Should return: nothing
```

If anything turns up, delete it before continuing.

---

## Step 2 — Create the repo on GitHub

1. Go to **[github.com/new](https://github.com/new)**
2. Repository name: `apex` (or `apex-resume-intelligence` if `apex` is taken)
3. Description: `AI-powered resume optimization agent with 16 analysis tabs and live job market scraping. ~18¢ per run.`
4. **Public** (you want this discoverable for portfolio purposes)
5. ❌ **DO NOT** check "Add a README" — we already have one
6. ❌ **DO NOT** add a .gitignore from the dropdown — we already have one
7. ❌ **DO NOT** choose a license from the dropdown — we already have MIT
8. Click **Create repository**

GitHub will show you a page with setup instructions. **Keep that page open** — you'll use the URL from it.

---

## Step 3 — Initialize git and push

Open a terminal and navigate to the `apex-github-ready/` folder:

```bash
cd path/to/apex-github-ready
```

Then run these commands one at a time:

```bash
# 1. Initialize git in this folder
git init

# 2. Set your default branch to 'main'
git branch -M main

# 3. Configure your git identity (only needed once per machine)
#    Replace with YOUR name and email
git config user.name "Your Name"
git config user.email "your.email@example.com"

# 4. Stage all files
git add .

# 5. Verify what's about to be committed (sanity check — config.json should NOT appear)
git status

# 6. Make the first commit
git commit -m "Initial commit: APEX v1.0 — Resume Intelligence Agent"

# 7. Connect your local repo to GitHub
#    Replace YOUR_USERNAME with your actual GitHub username
git remote add origin https://github.com/YOUR_USERNAME/apex.git

# 8. Push to GitHub
git push -u origin main
```

If GitHub asks for authentication, use a **Personal Access Token** (not your password):
- [Generate one here](https://github.com/settings/tokens/new) — give it `repo` scope
- Use the token as your password when prompted

---

## Step 4 — Configure the repo for maximum impact

Your code is on GitHub. Now make the repo look polished.

### 4a. Add a description and website
1. Go to your repo's main page
2. Click the ⚙️ gear icon next to "About" (top-right of the file list)
3. Fill in:
   - **Description**: `AI-powered resume optimization agent. 16 analysis tabs from one click. Live job market scraping. ~18¢ per run vs $29/month for paid alternatives.`
   - **Website**: leave blank for now (add later when you build a landing page)
   - **Topics**: add these one at a time:
     - `resume`
     - `ai-agent`
     - `openai`
     - `gpt-4`
     - `python`
     - `ats`
     - `job-search`
     - `career-tools`
     - `llm`
     - `resume-builder`
4. Click **Save changes**

### 4b. Pin the repo to your profile
1. Go to your **profile page** (github.com/YOUR_USERNAME)
2. Click **Customize your pins** (right side)
3. Check the box for `apex`
4. Click **Save pins**

This is the single biggest portfolio impact move. Pinned repos appear at the top of your profile.

### 4c. Enable Discussions (optional but recommended)
1. Repo → **Settings** → **General**
2. Scroll to **Features**
3. Check ☑️ **Discussions**
4. Save

This lets visitors ask questions and gives the repo a more "alive" feel.

### 4d. Add the social preview image (optional, big visual impact)
The image GitHub shows when your repo is shared on Twitter/LinkedIn.
1. Repo → **Settings** → **General** → **Social preview**
2. Upload an image (1280x640px recommended)
3. Quick way to make one: use [Canva](https://canva.com) → Custom size 1280x640 → put "APEX" in big text + a one-line tagline

---

## Step 5 — Verify everything looks right

Open your repo URL in an incognito window (so you see what visitors see):

- [ ] README displays correctly with badges
- [ ] Architecture diagram (Mermaid) renders properly
- [ ] All links in the README work
- [ ] `config.json` does NOT appear in the file list
- [ ] LICENSE shows up in repo header (right side)
- [ ] Topics (chips) appear under the description

If anything looks off, fix it locally and push:
```bash
git add .
git commit -m "Fix: <what you fixed>"
git push
```

---

## Step 6 — Make it shine (optional polish)

These take 30-60 minutes total but make a huge difference for portfolio quality:

### Record a demo GIF
1. Run APEX locally with a real resume
2. Use [Kap](https://getkap.co/) (Mac), [ScreenToGif](https://www.screentogif.com/) (Windows), or `peek` (Linux)
3. Record 30-45 seconds: upload → click Launch → tabs populate → switch through 3-4 tabs → export PDF
4. Save as `assets/demo.gif`, push to repo
5. In `README.md`, replace the demo `<pre>` block with: `![demo](assets/demo.gif)`

### Take screenshots of each main tab
1. Run APEX, switch to each tab once it has data
2. Browser screenshot at 1440x900 (use Cmd+Shift+4 on Mac)
3. Save to `assets/` folder as `screenshot-market.png`, `screenshot-resume.png`, etc.
4. Optional: embed them in the README's Features section

### Write a short "Why I built this" post
1. Make it the README's intro (or a separate `STORY.md`)
2. Personal motivation hits harder than feature lists
3. Link to it from your LinkedIn/Twitter when you launch

---

## Step 7 — Tell the world

Once the repo looks good:

### Post on LinkedIn
Template:
> Just open-sourced **APEX** — an AI agent I built that optimizes resumes using live job market data.
>
> 16 analysis tabs from one click. Self-improvement loop. Costs ~18¢ per run.
>
> Pure Python stdlib + vanilla JS. Zero pip packages. Zero npm packages.
>
> 🔗 github.com/YOUR_USERNAME/apex
>
> If you're job-hunting or know someone who is, give it a try and let me know what breaks.

### Post on Reddit
Best subs:
- `r/SideProject` — open-source builders welcome
- `r/Python` — tag as "Showcase"
- `r/coolgithubprojects` — exactly the audience

### Post on Hacker News
Submit at `news.ycombinator.com/submit`. Title: **"Show HN: APEX – Open-source resume optimizer with self-improvement loop ($0.18/run)"**. Best time: Tuesday-Thursday 9am EST.

### Add the repo link to:
- Your LinkedIn "Featured" section
- Your portfolio website (if you have one)
- Your GitHub profile bio
- Your Twitter/X bio if applicable
- Your email signature

---

## Common issues

**`git push` says "permission denied"**
- You're using your GitHub password instead of a token. [Generate a Personal Access Token](https://github.com/settings/tokens/new) with `repo` scope and use that as your password.

**`config.json` got pushed by mistake**
- Immediately revoke the exposed keys at OpenAI and RapidAPI dashboards
- Generate new keys
- Remove the file from git history:
  ```bash
  git rm --cached config.json
  git commit -m "Remove accidentally committed config.json"
  git push
  ```
- For full removal from history (if needed), use [BFG Repo-Cleaner](https://rtyley.github.io/bfg-repo-cleaner/)

**Mermaid diagram shows as raw code instead of a diagram**
- This means the README isn't being rendered as Markdown. Make sure the file is `README.md` (not `README.txt` or `readme.md`).

**README looks weird on GitHub**
- The `<div align="center">` HTML in the header should work — GitHub supports basic HTML in Markdown
- If it doesn't render, replace it with plain markdown headers

---

## What's next

Once your repo is up:

1. **Star your own repo** (yes, really — first star is the hardest to get)
2. **Watch the repo** so you get notified of issues
3. **Track stars over time** — there's no fancy reward, but seeing the count climb is genuinely motivating
4. **Respond to issues quickly** — a maintained repo is worth 10x an abandoned one in portfolio terms

---

You did the hard part. Hit publish.
