# APEX: the complete guide

APEX is a career app that runs on your own computer. You give it your resume and the job you want; it reads live job postings, works out what employers for that role actually ask for, and rewrites your resume the way a top recruiter would, **without inventing anything**. Every change is fact-checked against your own resume, shown to you with the reason for it, and yours to keep or undo. Around that it builds the rest of a job search: cover letters, interview prep, LinkedIn copy, outreach messages, salary negotiation, job search, and a tracker for your applications.

Version 11.0 · Code: https://github.com/Tikskalani/apex

---

## 1. Opening and closing it

| To | Do this |
|---|---|
| Open APEX | Double-click **APEX** on your desktop. It starts the server if needed (about 7 seconds), then opens your browser at **http://localhost:7842/**. |
| Stop APEX | Double-click **Stop APEX** on your desktop. |
| Open it again later | Bookmark `http://localhost:7842/`. It works whenever APEX is running. After a computer restart, double-click APEX once. |
| Start it by hand | In the APEX folder: `.\.venv\Scripts\python.exe agent_server.py` (then open the address above). |

Notes:
- It only works on this computer (your phone and other devices can't reach it). That keeps your resume and your API key private.
- Always use the address above. Opening `index.html` directly from the folder will not work.
- If it doesn't open, a message points you to `apex.log` in the project folder, which says why.

---

## 2. Your first run

1. Click **Launch** (top right).
2. Paste your resume (or upload a PDF, Word `.docx` or `.txt` file). Old Word `.doc`, `.rtf` and `.odt` files: save them as PDF or DOCX first.
3. Type the job title you're aiming for, pick the seniority, and (best results) paste a real job posting you like.
4. Press **Launch**. A progress bar shows each step; you can **Cancel** at any time (it stops spending immediately).
5. A run takes about **2 minutes** and costs about **70 cents** with the default model (measured on a real run).

When it finishes, each tab that has new results gets a dot. Start with **Resume X-Ray**.

---

## 3. What happens during a run

| Step | What it does |
|---|---|
| Understand the role | Classifies the job (industry, level) and picks search terms. |
| Read the market | Pulls live postings from job sites in parallel (about 30 seconds), and keeps only postings that are really this role (a "Backend Engineer" search ignores "Security Engineer"). |
| Measure demand | The AI proposes the skills and tools these postings ask for; APEX then **counts** how many postings actually mention each one ("Python in 29% of postings"). Percentages are measured, not guessed. |
| Check your resume | Splits those requirements into ones your resume shows and ones it doesn't. Ones it doesn't show are listed as gaps and are **never** added. |
| Rewrite (the Evidence Engine) | A recruiter-style review of every line, a rewrite, a fact check of every edit, then a blind before/after review by a simulated hiring manager. Details in section 5. |
| Everything else | Cover letter, interview prep, LinkedIn, outreach and career velocity are written in parallel and fact-checked too. |
| Report | Gap report, questions for you, and the measured cost of the run. |

---

## 4. Every tab

APEX is built for one niche: **AI engineering and the roles around it**, about 60 titles in 10 families: AI/LLM application engineering, voice and multimodal AI, machine learning, MLOps and AI platform, forward deployed and solutions, full-stack AI products, research engineering, evals and safety, data for AI, and AI automation. Pick a title from the suggestions in the job-title box (or **Add a role** in a job-agent profile). For each title APEX reads what AI hiring managers screen for plus its family's own focus (a platform engineer is judged on serving and cost, a forward deployed engineer on customer outcomes), so its review, rewrites and scoring follow that standard.

**Focus mode** (on by default) shows only Home, Resume X-Ray, PDF Templates, Apply Queue, Live Jobs, Cover Letter and Tracker. The **⋯ More tools** button at the bottom of the left bar shows the rest (Market Intel, Gap Report, Interview, LinkedIn and the single tools). In focus mode a run skips the interview, LinkedIn, outreach and velocity tabs, so it is faster and cheaper.

**Apply Queue (the job agent).** Make a profile for each person: a name, the job titles to look for, a location, and the base resume you are happy with. Every morning (after 7 am, while APEX is running) and whenever you press **Scan now**, APEX searches for new postings for each title, keeps the ones for the right role at the right level, and lists the best matches with a fit score and which of the posting's skills you show. The best few new matches (5 per profile by default, set in the profile, about 30¢ each) are prepared straight away: APEX tailors your resume to the posting and writes a cover letter, both fact-checked. For any other job, press **Apply** (or **Prepare only**). **Apply** is one tap: APEX makes the resume PDF and opens the application in its own browser window with your name, email, phone, links, resume and cover letter filled in (Greenhouse, Lever and Ashby forms fully; other sites where the labels are clear). Check it, answer what is left, press the site's **Submit**, then **I submitted it** here: the job goes into the Tracker with its resume and letter. Sign in to job sites once in that window and it remembers. APEX never submits an application for you, and never proposes the same job twice.

**Market radar.** Also in the Apply Queue tab. Every scan notes what the postings ask for, so after a few mornings the radar shows the skills AI roles want right now (the share of postings asking for each, rising or falling), which of them your resume or vault shows (✓) and which it does not (○). The **Today** card at the top lists the morning's new matches, the kits ready to apply and your top three gaps. **Suggest projects for my gaps** asks for three small projects that close them, built on what you already did, each with a number to measure; build one, add what you measured to the vault, and every resume after that can use it.

**Evidence vault.** At the bottom of the Apply Queue tab. Everything you confirm once is kept and used in every later resume, cover letter and application: when you answer APEX's questions after an optimization, the answers are saved here with the role or project they are about; **Import public repos** adds your GitHub projects (what each is, its language, stars and the start of its README); and you can add any fact yourself ("The support bot handled 12,000 chats a month"). APEX still writes nothing that is not in your resume or the vault, so the more true facts it holds, the stronger every resume gets. Delete anything that is out of date.


| Tab | What you get |
|---|---|
| **Home** | Start here; shows the setup card if no AI key is set, and the cost of your last run. |
| **Market Intel** | What postings for your role ask for, with measured percentages; how many postings were analysed; **Check drift now** (how the market moved since your last run). |
| **Resume X-Ray** | Every edit with its reason and a Keep toggle; the hiring-manager score before and after; questions only you can answer ("How many managers used these reports?"), the most valuable first (lines that matter most for the job and show the least impact). Answer them and press **Rewrite with my answers**: only those lines are rewritten. This is the biggest upgrade APEX can make: in tests on five tech resumes, answering a few of these questions raised the hiring-manager score by about 12 points on average, against about 7 for the rewrite alone. **Restore my original** at any time. |
| **Gap Report** | Specific problems a recruiter would flag, requirements you don't show yet (with how often postings ask for them), next steps. |
| **PDF Templates** | Download your resume as PDF, Word or text in six styles (Modern, Classic, Tech, Executive, Creative, Minimal). PDFs have a real text layer that application systems can read, and keep accented names (Zoë, Łukasiewicz). You choose: the edited resume (with your Keep choices) or your original. |
| **Live Jobs** | Search live postings, filter (remote, posted within N days, text), hide duplicates, see how well each matches your resume, and open **Tailor & Apply** on any job (which can save the job and its apply kit to the Tracker). |
| **Job Alerts** | Email alerts for new postings (needs your email settings; optional). |
| **Cover Letter** | A fact-checked letter; download as PDF, Word or text. The run writes it before you answer APEX's questions, so after answering press **Rewrite with my latest resume** to get a letter that uses those facts (it reads your edited resume, with the edits you kept). |
| **Interview** | Likely questions with example answers built only from your real experience (answers it couldn't verify are hidden, with the reason), questions to ask them, how to address weak spots, and voice practice (needs an OpenAI key). |
| **LinkedIn** | Headline, About section and experience bullets, all fact-checked; a skills list limited to skills your resume shows. |
| **Outreach** | LinkedIn message, cold email, referral request, thank-you note, negotiation email, all fact-checked. |
| **Velocity** | Where your career is heading and the next step up (filled by a run). |
| **Bullets** | Every resume bullet scored, with fact-checked rewrites for weak ones. A rewrite may leave a highlighted blank such as **[by X%]** where only you know the number: fill it in only if it's true. |
| **Tailor** | Paste a specific job posting: APEX rewrites your resume for that posting with the same fact-checked engine, scores it against the posting, lists what the posting wants that you don't show, and lets you export it or save it to the Tracker. **Tailor & Apply** from a job card does this plus a cover letter in one step, and saves both as an "apply kit". |
| **Match** | How well you fit a specific posting, what's missing, red and green flags. Suggested phrases you don't show yet are marked "only add this if it's true". |
| **Weakness X-Ray** | The lines hurting you most, with fact-checked fixes (with highlighted blanks for numbers only you know). |
| **Negotiate** | Target, opening and minimum salary with a negotiation script. Figures come from real pay ranges in live postings at your level (entry-level searches count only entry-level postings) and name the employers most of them come from; when there aren't enough, they're clearly labelled as an AI estimate. |
| **Career Bridge** | For career changers: how your skills translate, your bullets reframed in the new field's language, a transition story and interview answers, all fact-checked. |
| **Tracker** | Your job pipeline: Saved → Applied → Interview → Offer / Rejected / Withdrawn, a timeline per application, saved apply kits, follow-up reminders (overdue ones are highlighted with a count on the icon), and fact-checked follow-up emails. |

Also in the page: your work is saved in the browser (a reload loses nothing; **Clear saved data** in the drawer removes it), saved resume versions you can compare and restore, saved target roles you can switch between, keyboard navigation and screen-reader support, and a layout that works on phone-sized screens.

---

## 5. How APEX keeps everything true

This is what sets APEX apart from asking a chatbot to "improve my resume".

**Structure-locked editing.** Only your summary and your experience/project bullets can be edited; your skills line can only be reordered (never added to). Everything else (contact details, education, licences) is copied through untouched, and the document is rebuilt from your original lines, so formatting can't drift. If your resume has no summary, APEX can add one, built only from what the resume says.

**The fact check, for every edit and every generated text:**
1. **An automatic check** compares the new text with your resume: every number must be backed with its unit and scale ("$2M" is not backed by "2 interns"; "15K" is backed by "15,000"), and every tool, platform, certification or employer name must already be there, in any capitalisation, matched as whole words ("AWS" is not hiding in "laws").
2. **An AI audit** then checks each edit for anything added (a tool, a number, a team size, a result, a seniority) or anything important deleted.
3. A failed edit gets **one retry** with the reason; if it still fails, that line keeps its original wording. Other good edits are never thrown away because of one bad one. A new summary that still fails loses just the sentence that couldn't be verified, if the rest holds up.
4. For letters, LinkedIn copy, messages and answers: a failed text gets one repair attempt. If it still fails, APEX cuts only the sentences that couldn't be verified (when most of the text survives) and checks the rest again; only if that fails too is it **withheld**, and the page tells you why.
5. Advice you edit before using (suggested rewrites, sample interview answers) may contain a highlighted **[blank]** for a fact only you know. A blank claims nothing; everything stated outright is still checked.

**The hiring-manager review.** A simulated hiring manager for your target role scores the before and after versions, in both orders, and averages them. If it scores the rewrite **lower** than your original, your original is kept and you're told why (the "veto").

**What APEX will never do:** add a skill, tool, number, employer, title or result your resume doesn't show; quietly add keywords; or ship text that failed the check.

**Your answers count as evidence.** When APEX asks "how many?" and you answer, your answer can be used in the rewrite.

---

## 6. Where the market data comes from

Free sources, no key needed: Remotive, Arbeitnow, Jobicy, RemoteOK, Himalayas, The Muse, the Greenhouse, Ashby and Lever career pages of 53 tech and AI employers (OpenAI, Anthropic, Databricks, Stripe, Snowflake and more; full postings, usually with pay), and Hacker News "Who is hiring". Optional, with their own keys: JSearch (yours is set up; it covers many boards and is best for local and non-tech roles), USAJobs, Findwork.

All sources are searched at the same time with one time limit; a slow or failing source is skipped and named in the log. Only postings whose titles match what the role is about are used.

---

## 7. AI models and cost

| Setting | Default (Anthropic key only) | Used for |
|---|---|---|
| `MODEL` | Claude Opus 5.5 | Writing, reviewing, the fact-check audit and the hiring-manager review |
| `MODEL_FAST` | Claude Haiku 5.5 | Quick extraction and classification |
| `MODEL_AUDIT` (optional) | same as `MODEL` | The fact-check audit (can be a different model so the writer never checks itself) |
| `MODEL_JUDGE` (optional) | same as `MODEL_AUDIT` | The hiring-manager review |

Measured on a real run (fictional staff backend engineer, 2026-10-11): **about 70 cents and 2 minutes** per full run with Opus; hiring-manager score 60 → 68; 9 verified edits, nothing invented. Sonnet 5.5 costs about half as much per run. The cost of each run is measured from real token usage and shown on the Home tile and in the log.

OpenAI models also work (put `OPENAI_KEY` in `config.json` and pick a `gpt-...` model). Voice answers in Interview need an OpenAI key, because Anthropic has no speech-to-text.

To compare models on your own resumes instead of guessing: `python tools/benchmark.py` (runs APEX and a plain chatbot side by side, scored by the same judges, with invented claims counted).

---

## 8. Settings (`config.json`)

`config.json` sits in the project folder, holds your keys, and is never uploaded to GitHub. Copy `config.example.json` to start one.

| Key | Needed? | What it's for |
|---|---|---|
| `ANTHROPIC_KEY` | Yes (or an OpenAI key) | Claude models. Key names are matched loosely (`Anthropic_API_Key` works). |
| `ANTHROPIC_WORKSPACE_ID` | Only for organisation-level keys | The workspace the key belongs to. |
| `OPENAI_KEY` | Optional | OpenAI models and voice answers. |
| `JSEARCH_KEY` | Optional | The JSearch job source. |
| `MODEL`, `MODEL_FAST`, `MODEL_AUDIT`, `MODEL_JUDGE` | Optional | See section 7. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` | Optional | Email job alerts (for Gmail use an App Password). Can be set from the Job Alerts tab. |

If no AI key is set, APEX still opens and shows how to add one; the AI features stay off until you do and restart.

---

## 9. Your data and privacy

- **Everything stays on your computer.** Your applications, timeline, saved documents and run history are in `apex.db` in the project folder. Your current work (resume text, last results, choices) is also saved in your browser.
- **What leaves your computer:** your resume and the job details go to the AI provider (Anthropic) for each AI step, and searches go to the job sites. Nothing else.
- **Keys** stay in `config.json`, which is never served to the page, never shown in any response, and never committed to GitHub.
- **Gmail inbox scan** (optional) uses an App Password you type each time; it isn't saved, and the connection checks the mail server's certificate.

---

## 10. Security

APEX listens only on your own computer. Because any website open in your browser could try to talk to `localhost`, the server only answers its own page: requests from other sites are refused, there is no open cross-site access, only the app's own files are served, and the page runs under a strict security policy that blocks injected scripts. Requests are checked (size and required fields) before anything is spent, and a run stops making AI calls the moment you close the tab or press Cancel.

---

## 11. Hosting it online (optional, not active)

APEX also has a public "demo" mode for hosting on Fly.io, with a permanent link, an access code you hand out, private data per visitor, and spending limits per visitor, per network and per day so your credits are protected. The configuration and step-by-step guide are ready in `DEPLOY.md`. It isn't running anywhere; you chose to keep APEX local. Vercel is not a good fit (it can't keep the database or run 2-minute streams).

---

## 12. What's in the folder

| File / folder | What it is |
|---|---|
| `agent_server.py` | The server: the page, all features, job sources, model calls, security. |
| `apex_engine.py` | The Evidence Engine: parsing, rewriting, the fact check, the hiring-manager review. |
| `apex_store.py` | The database (your pipeline and run history). |
| `index.html` | The whole app page. |
| `launch_apex.pyw` | The one-click launcher behind the desktop icons. |
| `config.json` / `config.example.json` | Your settings and keys / the template. |
| `apex.db`, `apex.log` | Your data / the server's log (both local only). |
| `assets/` | Fonts used for PDF export (Noto Sans, open licence in `OFL.txt`). |
| `tests/` | 394 automated tests. |
| `tools/benchmark.py` | The model comparison tool. |
| `docs/API.md`, `docs/ARCHITECTURE.md` | Technical reference: every route and event / how it fits together. |
| `README.md`, `CHANGELOG.md`, `DEPLOY.md`, `TESTS.md`, `CLAUDE.md` | Overview, change history, hosting guide, manual test steps, rules for working on the code. |

---

## 13. Quality checks

- **394 automated tests** cover the engine and fact check (including dozens of deliberately invented claims that must be caught), the database, the server (including security and the online demo mode), and the page itself in a real browser. They run offline against a stand-in AI and saved job postings, so they cost nothing.
- They run automatically on GitHub for every change, and passed on the latest version.
- To run them yourself: `.\.venv\Scripts\python.exe -m pytest` and `python tests\run_all.py`.

---

## 14. Known limits

- **Years of experience** are not worked out from dates, so a true "5 years" is flagged unless it's written somewhere in your resume. The check errs toward caution.
- **PDF characters:** the built-in font has no Chinese, Japanese or Korean, and no arrows. In PDFs, → becomes "->" and missing characters are left out (you're told which); Word and text downloads keep everything.
- **Skills Keep toggle:** unticking one skills change undoes all skills changes.
- **Job sources** sometimes return few postings for unusual roles; pasting a real job posting gives the best results in that case.
- **Scanned PDFs** (images of text) can't be read; you'll be asked for a text PDF or Word file.
- **The fact check can be strict:** occasionally a true line is held back (you see why), so the summary or a message may stay unchanged. It never goes the other way on purpose.

---

## 15. Troubleshooting

| Problem | Fix |
|---|---|
| The APEX icon does nothing / says it could not start | Open `apex.log` in the project folder: the last lines say why (often a missing or wrong key in `config.json`). |
| "No AI key is set up yet" | Put your key in `config.json`, then **Stop APEX** and open it again. |
| "Your Anthropic account has no credits left" | Add credits at console.anthropic.com → Plans & Billing. |
| "not scoped to a workspace" | Add `ANTHROPIC_WORKSPACE_ID` to `config.json`, or use a key created inside a workspace. |
| Page says "Opened from file://" | Use `http://localhost:7842/`, not the file on disk. |
| Few or no postings found | Paste a real job posting in Launch; try a broader job title. |
| Port already in use | Another copy is running: use Stop APEX (or close the old window), then open APEX again. |

---

## 16. History

- **v1.0** (May 2026): first version.
- **v10**: rebuilt around a "truth-preserving" loop, which in practice often returned resumes unchanged.
- **v11** (2026-10-09): the Evidence Engine (line-by-line fact-checked edits, recruiter review, hiring-manager scoring), measured market demand, Claude support, the job pipeline, a hosted demo mode, and a benchmark against a plain chatbot.
- **2026-10-11** (on GitHub): a full audit fixed and every finding addressed. Everything written about you is now fact-checked; the fact check was rebuilt; PDF resumes and many more layouts are readable; real market data and posted salaries; drift on real data; cancel, progress and saved work in the page; better exports; accessibility; security and reliability hardening; automated testing on GitHub. Verified with real Claude runs.
- **Since then** (local only): the one-click desktop launcher.

Full details: `CHANGELOG.md`.
