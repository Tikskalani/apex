# APEX v11 — Manual Test Suite

Most of this is automated (`python tests/run_all.py` and `.venv\Scripts\python -m pytest`,
see CLAUDE.md). The steps below are the manual checks, against real models and live job boards.

Run in order. Each test ends in a PASS/FAIL verdict, not a narrative.

## Preconditions

- `agent_server.py` running (PowerShell window open)
- App open at **`http://localhost:7842/`** — not `file://`
- If the app only exists on disk, fix that first (see CLAUDE.md rule 1)
  before running anything below. A `file://` origin makes Tests 2, 5, 6, 7
  fail for reasons that have nothing to do with the app.

## Test fixture — resume

Deliberately mediocre: weak verbs, no numbers, vague bullets. The optimizer
should have real work to do, so a flat before/after score means the
optimizer is not running.

```
MARCUS DELGADO
Houston, TX | marcus.delgado@email.com | (713) 555-0142
linkedin.com/in/marcusdelgado

SUMMARY
Experienced professional looking for a new opportunity in data analysis.
Hard worker and team player with good communication skills.

EXPERIENCE

Data Analyst - Brightline Logistics, Houston TX
March 2021 - Present
- Responsible for making reports for the management team
- Worked with SQL to get data from databases
- Helped improve some processes
- Was part of a team that did dashboards

Junior Analyst - Corva Retail Group, Houston TX
June 2019 - February 2021
- Assisted with data entry and cleaning
- Made spreadsheets for the sales team
- Participated in meetings about metrics

EDUCATION
B.S. Business Administration, University of Houston, 2019

SKILLS
Excel, SQL, PowerPoint, Communication, Teamwork, Time Management
```

Target job title for all tests: **Senior Data Analyst**

## Test fixture — job posting (Test 5)

```
Senior Data Analyst - Meridian Health Systems, Houston TX
We need a Senior Data Analyst to own reporting for our clinical operations group.
Requirements: 4+ years in analytics, advanced SQL, Python (pandas), Tableau or Power BI,
experience with A/B testing and statistical analysis, stakeholder communication,
healthcare data experience preferred. You will build dashboards, define KPIs,
and partner with clinical leaders to drive measurable outcomes.
```

---

## TEST 1 — Smoke test

Change nothing. Report only.

1. Does the server status badge (top right) show connected/green or
   disconnected/red?
2. List every console error and warning, verbatim. Pay attention to failed
   script loads from `cdnjs.cloudflare.com`.
3. The libraries load on first use, so load them, then report the exact output:
   ```js
   (await Promise.all(['jspdf','docx','pdfjs','mammoth'].map(k =>
     loadLib(k).then(() => k + ': LOADED', e => k + ': MISSING (' + e.message + ')')))).join('\n')
   ```
4. Count the navigation tabs and list their names.

**PASS** if the badge is green, there are no console errors, and all four
libraries report LOADED. Otherwise FAIL, naming the exact check that failed.

*Why:* `jspdf` and `docx` are new in v10. If either is MISSING, every export
fails and nothing below is worth running.

---

## TEST 2 — Full agent run

1. Open the Launch panel, paste the fixture resume into the resume field.
2. Set job title to "Senior Data Analyst".
3. Start the agent.
4. Watch the live log. Report each phase as it completes, and total run time.
5. On completion report: the hiring-manager score before and after (Resume
   X-Ray), the number of verified edits and of lines kept original, the number
   of live postings analysed, and the measured cost in the footer.
6. List any log lines containing an X mark or the word "error".

**PASS** if the run completes, at least one posting was analysed, every edit
shown is true to the resume (check each against the original), and either the
hiring-manager score went up or the page says the original was kept and why.
The keyword-match number is NOT the pass criterion: it is blind to writing
quality (CLAUDE.md rule 9). Otherwise FAIL with the specific failure.

*Why:* Exercises every phase and the Evidence Engine end to end.

---

## TEST 3 — Every tab populates

With the agent run complete, visit each nav tab in turn. For each report:
tab name, real content vs empty/placeholder state, any visible error text.

Flag specifically any tab displaying generic placeholder content — for
example "Your Name", "Recent Company", "Senior PM", "TechCorp", "Skill 1".
That means real data never bound to the view.

**PASS** if every tab shows content derived from the submitted resume.
FAIL listing any tab that is empty, erroring, or showing placeholder text.

*Why:* The historical failure was tabs rendering demo content regardless of
input. This is the regression test for that.

---

## TEST 4 — Export (the one that matters)

Go to the Templates tab.

1. Confirm these three buttons exist: "Download PDF", "Download DOCX",
   "Download TXT".
2. Click Download PDF. Report the filename, and whether a download started
   or an error toast appeared.
3. Click Download DOCX. Same report.
4. Click Download TXT. Same report.
5. Report console errors during each.

**PASS** if all three buttons exist and all three trigger a download with no
console error. FAIL otherwise, quoting the exact error.

### Manual verification — must be done by a human

A download firing does not prove the PDF contains real text.

1. Open the downloaded PDF.
2. Drag the cursor across a line of text.
3. Text highlights → **PASS**. The ATS fix works.
4. Nothing highlights, or the whole page selects as one block → **FAIL**.
   It is still an image. This is the most important line in the suite.
5. Second confirmation: `Ctrl+F` inside the PDF, search a word you know is
   present. A real text layer finds it. An image finds nothing.

---

## TEST 5 — Tailoring and cover letter

Go to the Tailor tab.

1. Paste the fixture job posting above and run the tailoring.
2. Report match score before and after.
3. Does the Tailored Resume pane fill with real content?
4. Does the Cover Letter pane fill with real content, or show an error?
5. In the modal footer, confirm PDF, DOCX and TXT buttons exist, click each.

**PASS** if both panes populate and all three downloads fire. FAIL with details.

*Why:* The Cover Letter pane called `/draft-cover-letter`, which did not
exist server-side until v10. Direct regression test for that fix.

---

## TEST 6 — Endpoint reachability

Run in the console on the APEX page:

```js
(async () => {
  const S = 'http://localhost:7842';
  const gets = ['/health','/cities','/templates','/config'];
  for (const p of gets) {
    try { const r = await fetch(S+p); console.log(p, r.status, r.ok ? 'OK' : 'FAIL'); }
    catch(e) { console.log(p, 'NETWORK ERROR', e.message); }
  }
  const posts = {
    '/parse-resume': { resume: 'Jane Doe\njane@x.com\nEXPERIENCE\nAnalyst at Acme 2020-2024\n- Did things' },
    '/draft-cover-letter': { resume: 'Jane Doe, analyst, 4 years SQL', jobTitle: 'Data Analyst', company: 'Acme', posting: 'SQL required' },
    '/apply-all-recommendations': { optimized: 'Jane Doe\nEXPERIENCE\n- Built reports', changes: [], bulletRewrites: [], addedKeywords: ['SQL'] }
  };
  for (const [p, body] of Object.entries(posts)) {
    try {
      const r = await fetch(S+p, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
      console.log(p, r.status, r.ok ? 'OK' : 'FAIL');
    } catch(e) { console.log(p, 'NETWORK ERROR', e.message); }
  }
})();
```

Wait for all seven lines, then report each verbatim.

**PASS** if all seven return 200. FAIL listing any non-200 with its status.

*Why:* The last three were added in v10. A 404 means the backend file was
not replaced. A NETWORK ERROR on all seven means a CORS or origin problem,
not a missing endpoint — check the page is served over HTTP first.

Note: the two GPT-backed POSTs cost a fraction of a cent each and take a
few seconds.

---

## TEST 7 — Interview, negotiation, bridge

1. **Interview tab** — confirm behavioral and technical questions are
   present with STAR-format answers.
2. **Negotiate tab** — enter location "Houston, TX" and run. Report whether
   you get a target ask, opening counter, minimum, and a negotiation script.
3. **Bridge tab** — current role "Data Analyst", target role "Data
   Scientist". Report whether you get a skills mapping.

**PASS** if all three produce real, resume-specific content. FAIL with
details on any that error or stay empty.

---

## TEST 8 — Error handling

A clear error message is correct behavior. A silent failure or an uncaught
JavaScript exception is a bug. Report exactly what happens for each:

1. Clear the resume field entirely, try to run the agent.
2. Clear the job title, try to run the agent.
3. Templates tab, click Download PDF before parsing any resume.
4. Paste a single character "x" as the resume and run.

**PASS** if each shows a helpful error message and nothing throws an
uncaught exception in the console. FAIL with details.

*Why:* Demo safety. This is the failure mode that shows up when someone
else drives the app in front of an audience.

---

## Reporting format

1. PASS/FAIL verdict per test
2. Every console error, verbatim
3. Result of the manual PDF text-selection check
4. Any tab showing placeholder content
