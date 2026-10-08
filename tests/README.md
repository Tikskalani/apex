# APEX regression suite

```bash
python tests/run_all.py
```

Run this after any change to `agent_server.py` or the export engine in `index.html`.
Every test here exists because a real bug got through.

| Suite | Guards against |
|---|---|
| `r1_scorer` | Crashes on empty/junk input, non-deterministic scores, keyword stuffing beating real work, stem-matching failures |
| `r2_protected` | Licenses/certs/clearances/languages not detected, lowercase or prefixed headers missed, restore duplicating content |
| `r3_loop` | Model returning empty/None/commentary, dropped licenses, fabrication shipped, audit failure accepted, good rewrites rejected |
| `r4_export` | Fields parsed but never rendered — the bug that deleted a clinician's licenses from every export format |
| `r5_ranking` | Score failing to rank a strong resume above a weak or keyword-stuffed one |
| `r7_e2e` | The full historical failure on a real resume. Needs a PDF in `tests/fixtures/` — skips if absent |
| `r8_weak` | The loop refusing to improve anything (over-correction from the anti-fabrication work) |
| `r10_final` | Unicode, huge inputs, commentary stripping edge cases, restore idempotency |

## Requirements

`python3` only. Everything optional degrades to a clean skip:

| Optional | Used by | Without it |
|---|---|---|
| `node` | `r4_export` | that suite is skipped, others run |
| `pdfplumber` | `r7_e2e` | that suite is skipped, others run |
| a PDF in `tests/fixtures/` | `r7_e2e` | that suite is skipped |

Neither is a dependency of APEX itself — the app remains pure standard library. To enable the full end-to-end suite:

```
pip install pdfplumber
```

then drop any resume PDF into `tests/fixtures/`.

Exit code is 0 on pass, 1 on failure, so this can gate a commit.
