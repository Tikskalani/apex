# APEX Agent Analysis — Why It Fabricated, and What "World's Best" Requires

**Date:** 2026-09-06
**Trigger:** A real run on a licensed physical therapist's resume produced an output that (a) claimed telehealth experience she does not have and (b) deleted her state licenses, BLS certification, work authorization, and languages — while reporting an ATS improvement of 55 → 85.

This document covers the root causes, the fix, and an honest gap assessment against the tools APEX claims to beat.

---

## Part 1 — Root cause

Nothing here was the model misbehaving. Every failure traces to an instruction in the prompt, a gap in the rules, or a scoring function that rewarded the wrong thing. Ten distinct defects, all in the v9 self-improvement loop and Phase 5 scoring.

### The fabrication

**1. The rewrite prompt told the model to address gaps.**

```
GAPS TO ADDRESS:
Lack of telehealth and virtual therapy experience
```

This block was passed into every rewrite iteration. The only way a rewriter can "address" a lack of telehealth experience is to add telehealth. The model did what it was asked. The gap report and the rewrite instructions shared the same list — the structural cause.

**2. "Inject ALL validated keywords."**

Iteration 1 focus: *"injecting all validated keywords naturally."* Phase 4 had flagged telehealth, virtual therapy, and remote patient monitoring as salary-premium terms, so they sat in the keyword list. "Inject all" plus a keyword the candidate lacks equals a fabrication mandate. There was no evidence check between the market keyword list and the rewriter.

**3. The anti-fabrication rule was too narrow.**

```
1. NEVER fabricate companies, titles, dates, or credentials
```

Skills, technologies, methods, competencies, languages, and experiences are not on that list. Telehealth is a competency. The model complied with the letter of the rule.

**4. Iteration 2 instructed the model to invent numbers.**

```
quantifying every single achievement with numbers (use [~X%] estimates if needed)
```

Fabrication by design. This is also why iteration 2 regressed in the live run — the estimates were rejected by the scorer as noise, but the instruction itself should never have existed.

### The content loss

**5. No section-preservation rule.** "Improve this resume. Output only resume text." Nothing said keep every section. The model restructured freely and dropped LICENSES & CERTIFICATIONS, LANGUAGES, education location, and the work-authorization line.

**6. The self-scorer only read the first 3,000 characters.**

```python
{resume_text[:3000]}
```

A two-page resume runs 4,000–6,000 characters. Licenses, education, skills, and languages sit at the bottom. **The scorer could not see them.** Dropping them cost zero points. Dropping them and adding market keywords up top *gained* points.

**7. The scoring criteria contained no truthfulness or completeness dimension.**

```
Consider: keyword density, action verb strength, quantification, formatting, sector relevance.
```

Adding a fabricated keyword raises density. Deleting a license section removes text with no market keywords in it. The loop's fitness function selected for fabrication and content loss. It did not merely permit them — it rewarded them.

**8. Iterations were kept on ties.**

```python
if new_score >= best_score:
```

Any rewrite that scored the same replaced the previous best, so drift accumulated across iterations with no improvement to justify it.

### The score itself

**9. The headline numbers were anchored on prompt examples.**

The Phase 5 prompt asked the model to return JSON matching this example:

```
"atsScoreBefore":55,"atsScoreAfter":82
```

The model anchored on the examples. The May test run reported 55 → 85. The September run reported 55 → 82, then 85. Different resumes, same before score. **The number was not a measurement.** And `atsScoreAfter` was *predicted before any rewrite happened* — the model guessing what a score would be after work it had not done.

**10. The displayed after-score could never go down.**

```python
market['atsScoreAfter'] = max(market['atsScoreAfter'], final_ats)
```

The maximum of the pre-rewrite guess and the post-rewrite self-score. Two model estimates, keep the higher. The +30 delta on the pitch deck was substantially an artifact of this line.

---

## Part 2 — What changed in v10

The loop was replaced. The three guarantees it now makes:

### Nothing is fabricated

- **Evidence gate.** Before any rewriting, every market keyword is classified: *supported* (the original resume demonstrates it — substring match, then one strict model check for the remainder) or *unsupported* (no evidence). Only supported keywords go to the rewriter. Unsupported ones go to the gap report, labeled as skills to build.
- **The gap list is gone from the rewrite prompt.** It never reaches the model that writes the resume.
- **Expanded rule.** The rewriter may not add any skill, tool, technology, method, credential, license, certification, language, employer, title, date, location, or metric absent from the current version.
- **Fidelity audit after every iteration.** A separate model call compares candidate to original and quotes any unsupported claim. **Any fabrication rejects the iteration outright**, regardless of score. If the audit itself fails, the iteration is rejected — fail closed.
- **No estimates.** Iteration 2 now quantifies only from numbers present in the original or countable from listed items. Explicit rule: *a number you cannot find does not exist.*

### Nothing protected is lost

- **Protected content extraction.** Before the loop, sections matching licenses, certifications, credentials, languages, work authorization, clearances, education, publications, patents, awards, and affiliations are captured verbatim. Individual lines matching license/certification/citizenship patterns are captured wherever they sit.
- **Checked after every iteration.** If any protected section or line is missing from a candidate, it is restored verbatim before scoring.
- **Final safety net.** The returned text is checked once more. Nothing leaves the loop without every protected item present.
- **Length guard.** A candidate under 50% of the previous best's length is rejected as content loss.

### The score is a measurement

Replaced the model-estimated score with a deterministic function:

| Component | Weight | What it measures |
|---|---|---|
| Keyword coverage | 55 | Share of market keywords present; top 10 count double |
| Section coverage | 15 | Contact, summary, experience, education, skills |
| Verb strength | 15 | Share of bullets opening with a strong verb |
| Quantification | 10 | Share of bullets containing a number |
| Hygiene | 5 | Length band, weak-opener ratio |

Same input, same score, every time. Reads the full text. No example numbers to anchor on. The after-score is the score of the text that ships — not a maximum over guesses.

Strict improvement only: `>` not `>=`.

### Verification

Tested against the exact Leena Varma case with a mocked model reproducing the observed behavior:

```
🔒 Protected: LICENSES & CERTIFICATIONS, EDUCATION
✓ Keywords with evidence: 12  |  gaps (report only): 3
○ Not injecting (no evidence): telehealth, virtual therapy, remote patient monitoring
Baseline ATS (measured): 68/100

▶ Iteration 1 — [the exact output APEX previously shipped]
✗ REJECTED — fabricated: "telehealth" — not in original
    also: "remote patient monitoring" — not in original
    also: "virtual therapy" — not in original

▶ Iteration 2 — [honest rewrite]
✓ IMPROVED — 68 → 75 (+7)  kw 72% · verbs 100% · quant 0%

Licenses in final output: True
Telehealth in final output: False
Languages in final output: True
```

The output that reached a real candidate can no longer leave the system.

**Expect lower numbers.** The old output scored 88 on the new function — because 3 of 15 keywords were fabricated, giving 100% coverage. The honest ceiling for that resume is ~80%. A lower score that is true beats a higher score that is not.

---

## Part 3 — Gap assessment against industry standard

The pitch says APEX beats every paid tool. Here is where that claim holds, where it does not, and what closes each gap. Ordered by impact.

### Holds

**Live market keywords.** Jobscan, Resume Worded, and Teal all match against a *pasted job description* or a static taxonomy. APEX harvests live postings and derives keywords from the market as it exists this week. No commercial tool does this at the consumer tier. This is the real differentiator.

**Self-improvement with regression guard.** No consumer tool iterates and reverts. Now that the fitness function is honest, this is a genuine advantage.

**Evidence-gated rewriting with a fidelity audit.** Rezi, Kickresume, and Enhancv AI writers all fabricate freely — it is a known, documented complaint. A rewriter that provably refuses to add unsupported claims is, as of this build, ahead of the market.

**Cost.** ~18¢ per full run versus $25–50/month subscriptions.

### Does not hold yet — ranked by damage

**1. No PDF parsing quality check.** The Leena Varma case began with a PDF whose extracted text had no bullet markers. If extraction mangles the input — merged lines, lost bullets, two-column layouts read across — every downstream phase works on garbage. Jobscan shows the user *what the parser saw*. APEX should too: after upload, display the extracted text and let the user confirm or paste clean text before running. Cost: one screen. Impact: prevents an entire class of silent failures.

**2. Source reliability is unmeasured.** 5 of 8 sources returned zero in the live run. Nobody knows if TheMuse, USAJobs, Indeed RSS, and Arbeitnow are dead, rate-limited, or misconfigured, because per-source health is not tracked across runs. Add a persistent source ledger: last success, last failure, rolling hit rate. Surface it in the UI. A source at 0% over ten runs is dead and should be flagged, not silently retried.

**3. Relevance filter accepted a weak corpus.** 13 kept of 35, average relevance 36/100, and the run proceeded at "medium" confidence. Telehealth surfaced as a salary-premium keyword because remote-heavy sources (Remotive, LinkedIn RSS) dominated a thin harvest. The filter should weight keywords by the relevance of the listing they came from — a term from a 90-relevance listing counts more than one from a 30. Currently every kept listing votes equally.

**4. The gap report and the rewrite are still not visually distinct enough.** The candidate saw "telehealth" in the market keywords and in the summary and had no way to know one was a suggestion and the other was a claim. The new Integrity Report panel separates *added with evidence* from *withheld — no evidence*, but the Gap tab should also explicitly label each item: **You have this** / **Consider building this** / **Do not claim this**.

**5. No job-description mode.** The most common real-world task is "tailor my resume to *this posting*." APEX has `/tailor`, but the main pipeline optimizes against the aggregate market. Industry tools default to JD-specific. The right architecture: market keywords as the baseline, JD keywords as the override when a posting is supplied, with the evidence gate applied to both.

**6. Bullet markers are inconsistent.** The scorer now tolerates marker-less text, but the *output* should always use `- ` and the exporter should never emit `•`. Some ATS engines (Taleo, older iCIMS) mis-parse typographic bullets. Currently the template renderer uses `•` in some designs.

**7. Score is not benchmarked.** The deterministic scorer is reproducible, but its weights are chosen, not calibrated. The honest fix is a small validation set: 20–30 resumes with known ATS outcomes, tune weights until the ranking matches. Without this, the score is *consistent* but not *validated*. Say so in the UI until it is.

**8. No structured output contract.** The rewriter returns free text, which then gets re-parsed by `/parse-resume` for export. Two lossy conversions. Better: rewrite into the same structured schema the exporter consumes — `{name, contact, summary, experience[], education[], skills{}}` — so sections cannot be lost because they are fields, not paragraphs.

### Recommended order

1 and 2 are cheap and prevent silent failures. 3 fixes the specific mechanism that surfaced telehealth. 4 and 5 are product-level. 6 is a small exporter fix. 7 is the honest thing to do before calling the score authoritative. 8 is the right architecture but a larger refactor.

---

## Part 4 — What the pitch deck should say now

The old claim: *"55 → 85, +30 points."* That number was substantially anchored and inflated by `max()`.

The defensible claim: *"Every keyword APEX adds is one your resume already proves. Every credential you list survives. Every score is measured, not estimated — and you can see exactly what was added, what was withheld, and why."*

That is a stronger position than a bigger number, because it is the thing competitors demonstrably do not do.
