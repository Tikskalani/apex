# Exporting the Evidence Engine

APEX was frozen at tag `apex-v11-final`. This note is for lifting the resume engine
(`apex_engine.py`) out of APEX and running it somewhere else. Everything below was checked
against the tagged code.

## Files to copy

| File | Why |
|---|---|
| `apex_engine.py` | The engine. |
| `apex_domains.py` | The AI-engineering screening guide, role families and page budget. The engine imports it. |

That is all the engine needs to import. `apex_domains.py` imports only `re`. The engine
imports only the standard library (`contextvars`, `json`, `re`, `collections.Counter`,
`concurrent.futures.ThreadPoolExecutor`, `functools.lru_cache`) plus `apex_domains`. It reads
no environment variables, no files and no config, and it opens no network connections itself.
Every model call goes through the `llm` callable you pass in.

## The `llm` callable

Every public entry point that calls a model takes `llm` as its first argument
(`optimize`, `revise`, `verify_texts`, `check_texts`, `judge`, `diagnose`, `rewrite`, `audit`).
The engine calls it as:

```python
llm(system: str, user: str, *, max_tokens: int, json_mode: bool, effort: str) -> str
```

- **Arguments.** Always passed by keyword, in these exact combinations:

  | System prompt | `max_tokens` | `json_mode` | `effort` |
  |---|---|---|---|
  | `DIAGNOSE_SYSTEM` | 5000 | True | `'medium'` |
  | `REWRITE_SYSTEM` | 7000 | True | `'medium'` |
  | `VERIFY_SYSTEM` (bullet audit) | 3000 | True | `'medium'` |
  | `VERIFY_SYSTEM` (text check) | 3000 | True | `'medium'` |
  | `REPAIR_SYSTEM` | 4000 | True | `'medium'` |
  | `JUDGE_SYSTEM` | 1200 | True | `'low'` |
  | `CUT_SYSTEM` | 1500 | True | `'low'` |

  Accept `**kwargs` anyway, so a future engine change does not break the adapter. The server's
  adapter does: `def engine_llm(system, user, **kw)`.
- **Return value.** The model's reply as text. The engine expects one JSON object and parses it
  leniently with `_jload`: code fences are stripped, the first `{...}` is taken, and trailing
  commas are tolerated. An unparseable reply counts as an empty result, not an error: no edits,
  or a check that fails safe.
- **Errors.** Raise on failure (timeouts, quota, cancellation). The engine does not catch model
  exceptions. They propagate out of `optimize`/`revise`, including from parallel calls
  (`_pmap` re-raises in the caller).
- **Threads.** Calls run up to 6 at once from a `ThreadPoolExecutor`, each in a
  `contextvars.copy_context()` of the caller. So `llm` must be thread-safe, and any per-run
  state it keeps (a cost meter, a cancel flag) should live in `contextvars`, which then
  follows each call.
- **Routing by prompt (optional).** The prompts are module constants (`DIAGNOSE_SYSTEM`,
  `REWRITE_SYSTEM`, `VERIFY_SYSTEM`, `REPAIR_SYSTEM`, `JUDGE_SYSTEM`, `CUT_SYSTEM`), so an adapter
  can choose a model by comparing `system` with them. APEX sends `VERIFY_SYSTEM` to an audit
  model, `DIAGNOSE_SYSTEM` to a review model and `JUDGE_SYSTEM` to a judge model, so the writer
  never grades itself (`agent_server.engine_llm`).

A minimal adapter (Anthropic SDK):

```python
import anthropic, apex_engine as E
client = anthropic.Anthropic()

def llm(system, user, max_tokens=3000, json_mode=False, effort=None, **_):
    msg = client.messages.create(model='claude-opus-5-5', max_tokens=max_tokens, system=system,
                                 messages=[{'role': 'user', 'content': user}])
    return ''.join(b.text for b in msg.content if b.type == 'text')

result = E.optimize(llm, resume_text, target)
```

## The `target` dict

`optimize(llm, resume, target, answers=None, log=print, judge_it=True)` and
`revise(llm, resume, target, answers, kept=None, ...)` read these keys. All of them are
optional, and a missing key means none:

| Key | Type | Used for |
|---|---|---|
| `title` | str | Target role. Also picks the role family in `apex_domains.brief`. |
| `seniority` | str | Level shown to the model and used for the page budget. |
| `sector` | str | Shown to the model (default `general`). |
| `domain` | `'ai_swe'` or None | Turns on the AI-engineering guide and the 2-page budget. Use `apex_domains.detect(title)`. |
| `keywords` | list of `{name, pct}` | Market keywords and the share of postings asking for each. |
| `supported` | list of str | Keywords the resume already shows (preferred wording). |
| `unsupported` | list of str | Keywords it does not show. The fact gate blocks them; they are reported as gaps. |
| `job_desc` | str | The posting text (first 12,000 characters). |
| `facts` | list of `{topic, text}` | Facts the candidate confirmed (the evidence vault). A fact counts as evidence for the role whose heading matches its topic, and for the summary. |

The result is a dict:
- `final`: the rewritten resume text;
- `changes`: the edits that were made;
- `rejected`: edits the fact check refused;
- `questions` for the candidate;
- `order` and `section_order`;
- `problems`, `strengths` and `summary_verdict`;
- `line_scores` and `score`, which includes the judge result when `judge_it=True`.

## Tests that cover the engine alone

These run with only `apex_engine.py`, `apex_domains.py`, `tools/benchmark.py` and
`tests/e2e/fixtures/marcus_delgado.txt` present. I checked this by copying just those files
into an empty folder and running pytest there: **175 passed**. Every model call in them goes
to a scripted stub.

| File | Tests | Needs |
|---|---|---|
| `tests/test_engine.py` | 26 | `tests/e2e/fixtures/marcus_delgado.txt` |
| `tests/test_engine_flow.py` | 13 | `tests/e2e/fixtures/marcus_delgado.txt` |
| `tests/test_engine_gate.py` | 11 | nothing else |
| `tests/test_engine_parse.py` | 9 | nothing else |
| `tests/test_engine_benchmark.py` | 4 | `tools/benchmark.py`, for its pure helpers (`invented`, `fabrication_audit`, `summarize`, `FABRICATION_SYSTEM`, `CHAT_PROMPT`). The file never imports `agent_server`. |

The table counts test functions; pytest collects more cases than that because some tests are
parametrized.

```bash
python -m pytest tests/test_engine.py tests/test_engine_flow.py tests/test_engine_gate.py tests/test_engine_parse.py tests/test_engine_benchmark.py -q
```

**Mixed files.** The engine tests in these also run alone; deselect the others:
- `tests/test_quality_fixes.py`: 11 engine tests pass alone. They cover the prune, blanks,
  summary prune, question ranking and page-budget cuts. The 4 tests that take the `server`
  fixture need `agent_server.py` (title matching, seniority bands, posted pay).
- `tests/test_vault.py`: `test_facts_join_the_evidence_of_their_role_or_project` and
  `test_no_facts_no_change` are engine-only. The rest use the store or the `server` fixture.

The `server` fixture (`tests/conftest.py`) copies `agent_server.py`, so any test that takes it
is not engine-only.

## Bench scripts and `agent_server.py`

**No bench script runs a benchmark without `agent_server.py`.** Each one imports it inside its
run function, for the model client, the cost meter and the deterministic keyword matcher.

| Script | Without `agent_server.py` | What it takes from `agent_server` |
|---|---|---|
| `tools/benchmark.py` | Only `--reveal RUN_DIR` (it reads `blind_key.json`), and importing the module for its helpers. A real run imports `agent_server` in `run()`. | `gpt` (through `bound_llm`), `Meter`, `TOTAL_METER`, `_RUN_METER`, and `_norm` and `_present` (in `make_target`) |
| `tools/answer_bench.py` | No: `run()` imports it first. | `cover_letter`, `MODEL`, `TOTAL_METER`, and `gpt` through `benchmark.bound_llm` |
| `tools/feature_bench.py` | No: `main()` imports it first. It benchmarks server features, not just the engine. | `job_tailor`, `cover_letter`, `bullet_ranker`, `smart_match`, `weakness_xray`, `followup_generator`, `grade_interview_answer`, `salary_brief`, `skills_bridge`, `gpt`, `MODEL`, `Meter`, `TOTAL_METER`, `_RUN_METER` |

To run `benchmark.py` against the engine alone, replace three things:
- `bound_llm` with your own `llm` (above);
- `A._norm` / `A._present` in `make_target` with a whole-word matcher, or a precomputed
  `supported` list;
- the meter calls with your own budget check.

The cases are `bench/cases/*.json`, plus `bench/private/*.json`, which is gitignored and holds
real resumes; leave those out of anything you share.
