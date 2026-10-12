"""APEX model benchmark: which model makes the Evidence Engine write the best resumes?

Runs the same engine (apex_engine.optimize) on the same resumes and the same
fixed targets with each candidate model (or, for `chat:<model>`, the plain
"improve my resume" request people make to a chatbot - the baseline APEX has to
beat), then has EVERY judge model score every output (blind A/B vs the original,
both orders). Models tend to prefer their own writing, so scores from a judge of
the same provider are reported separately. Also measured: invented claims
(numbers, tools and names in the output that appear nowhere in the original
resume, per the same deterministic gate the engine uses), an independent fabrication audit (a
separate model - --fabrication-judge, default the first judge - reads the original and each output whole
and lists unsupported claims, so the metric is not only the gate APEX is built to pass), verified edits,
edits reverted by fact-checking, cost, time. The chatbot baseline gets the same brief as the engine and
the judges (title, market keywords, job posting).
Writes a blind review page so a human can pick without knowing which model wrote what.

    python tools/benchmark.py --models gpt-6.1-sol claude-sonnet-5-5 claude-opus-5-5 chat:gpt-6.1-sol \
        --judges gpt-6.1-sol claude-opus-5-5 --budget 3.00

    python tools/benchmark.py --reveal bench/runs/<run>       # after you've made your blind picks
    python tools/benchmark.py ... --fabrication-judge none    # skip the independent fabrication audit

Cases: bench/cases/*.json and bench/private/*.json (private is gitignored, for real resumes):
    {"name": "...", "title": "...", "seniority": "...", "sector": "...", "resume": "file.txt",
     "keywords": ["..."], "job_desc": "optional posting text"}
"""
import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_cases(dirs, only=None):
    cases = []
    for d in dirs:
        for f in sorted(Path(d).glob('*.json')):
            c = json.loads(f.read_text(encoding='utf-8'))
            c['resume_text'] = (f.parent / c['resume']).read_text(encoding='utf-8')
            if not only or c['name'] in only:
                cases.append(c)
    return cases


CHAT_PROMPT = ('Improve my resume for a {title} role so I get more interviews. This is what the role asks for:\n\n'
               '{brief}\n\nReturn only the improved resume text.\n\nMY RESUME:\n{resume}')

FABRICATION_SYSTEM = ('You are an independent reference checker. You compare a rewritten resume with the original and '
                      'list every claim about the candidate that the original does not support. Return ONLY valid JSON.')


def provider(model):
    model = model.split(':', 1)[-1]
    return 'anthropic' if model.startswith('claude-') else 'openai'


def invented(E, final, case, target):
    """Claims in the output with no basis anywhere in the original resume (the engine's own gate)."""
    allowed = E.title_words(case['title']) + list(target['supported']) + ['Summary']   # a created SUMMARY header
    return E.fact_gate(final, case['resume_text'], target['unsupported'], case['resume_text'], allowed)


def fabrication_audit(E, llm, original, final):
    """Independent check: a model reads the original and the output whole and lists unsupported
    claims. Not the engine's gate or audit prompt. -> [claims], or None when the reply is unreadable."""
    raw = llm(FABRICATION_SYSTEM, f"""{E.DATA_RULE}
ORIGINAL RESUME (the only evidence about the candidate):
{E._data('ORIGINAL', original)}

REWRITTEN RESUME:
{E._data('REWRITE', final)}

List every claim in the REWRITTEN resume that the ORIGINAL does not support: a number, tool, employer, title,
credential, scope, team size, user count, outcome, years of experience or seniority that is new or changed, and any
causal claim the original does not make. Rewording, reordering, condensing, counting listed items and the standard
name of something the original clearly shows are fine. Quote each claim once.

Return ONLY JSON: {{"unsupported": [{{"claim": "quote", "why": "..."}}]}} (an empty list when everything is supported)""",
              max_tokens=2500, json_mode=True, effort='medium')
    d = E._jload(raw)
    if not isinstance(d.get('unsupported'), list):
        return None
    return [str(x.get('claim') if isinstance(x, dict) else x)[:200] for x in d['unsupported']]


def make_target(A, case):
    """Fixed, model-independent target: supported/unsupported decided by the
    deterministic matcher, so every model gets the identical brief."""
    hay = A._norm(case['resume_text'])
    kw = case['keywords']
    sup = [k for k in kw if A._present(k, hay)]
    return {'title': case['title'], 'seniority': case.get('seniority', ''), 'sector': case.get('sector', 'general'),
            'job_desc': case.get('job_desc', ''), 'keywords': [{'name': k, 'pct': None} for k in kw],
            'supported': sup, 'unsupported': [k for k in kw if k not in sup]}


def bound_llm(A, model):
    def llm(system, user, **kw):
        kw.pop('fast', None)
        return A.gpt(system, user, model=model, **kw)
    return llm


def run(args):
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    import agent_server as A          # loads config.json itself; keys are never printed
    import apex_engine as E
    cases = load_cases(args.cases, args.only)
    if not cases:
        sys.exit('no cases found')
    out = Path(args.out or ROOT / 'bench' / 'runs' / datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True, exist_ok=True)
    spent = lambda: A.TOTAL_METER.summary()['usd']
    results, log = [], []

    def say(m):
        print(m, flush=True)
        log.append(m)

    say(f'APEX benchmark · {len(cases)} case(s) · models {args.models} · judges {args.judges} · budget ${args.budget:.2f}')
    jobs = [(c, m) for c in cases for m in args.models]
    per_job = []
    for case, model in jobs:
        avg = (sum(per_job) / len(per_job)) if per_job else 0
        if per_job and spent() + avg > args.budget:
            say(f'  ! stopping: next run (~${avg:.2f}) would exceed the ${args.budget:.2f} budget (spent ${spent():.2f})')
            break
        say(f'\n── {case["name"]} × {model}')
        target = make_target(A, case)
        meter = A.Meter(); tok = A._RUN_METER.set(meter)
        t0 = time.time()
        try:
            if model.startswith('chat:'):          # the chatbot baseline: one plain request, no engine
                text = bound_llm(A, model[5:])('You are a helpful assistant.',
                                               CHAT_PROMPT.format(title=case['title'], brief=E._target_block(target),
                                                                  resume=case['resume_text']),
                                               max_tokens=4000, effort='medium')
                strip = getattr(A, 'strip_commentary', None) or (lambda t: re.sub(r'```[a-z]*', '', t or '').strip())
                r = {'final': strip(text) or text, 'changes': [], 'rejected': [], 'questions': []}
            else:
                r = E.optimize(bound_llm(A, model), case['resume_text'], target,
                               log=lambda m: say('  ' + m.strip()), judge_it=False)
            err = None
        except Exception as e:
            r, err = None, str(e)
            say(f'  ✗ {err}')
        A._RUN_METER.reset(tok)
        cost = meter.summary()
        per_job.append(cost['usd'])
        rec = {'case': case['name'], 'model': model, 'error': err, 'seconds': round(time.time() - t0, 1),
               'cost_usd': cost['usd'], 'judges': {}}
        if r:
            inv = invented(E, r['final'], case, target)
            rec.update(changes=len(r['changes']), reverted=len(r['rejected']), questions=len(r['questions']),
                       invented=len(inv), invented_examples=inv[:8], final=r['final'], result=r)
            say(f'  invented claims: {len(inv)}' + (f' (e.g. {"; ".join(inv[:3])})' if inv else ''))
            if args.fabrication_judge and spent() <= args.budget:
                fm = A.Meter(); tok = A._RUN_METER.set(fm)
                try:
                    aud = fabrication_audit(E, bound_llm(A, args.fabrication_judge), case['resume_text'], r['final'])
                except Exception as e:
                    aud = None
                    say(f'  fabrication audit: ✗ {e}')
                A._RUN_METER.reset(tok)
                rec['cost_usd'] = round(rec['cost_usd'] + fm.summary()['usd'], 4)
                rec.update(audit_invented=None if aud is None else len(aud), audit_examples=(aud or [])[:8])
                say(f'  fabrication audit ({args.fabrication_judge}): '
                    + ('unreadable reply' if aud is None else f'{len(aud)}' + (f' (e.g. {"; ".join(aud[:3])})' if aud else '')))
            (out / f'{case["name"]}__{model}.txt').write_text(r['final'], encoding='utf-8')
            for j in args.judges:
                if spent() > args.budget:
                    say('  ! budget reached; skipping remaining judges'); break
                jm = A.Meter(); tok = A._RUN_METER.set(jm)
                try:
                    s = E.judge(bound_llm(A, j), case['resume_text'], r['final'], target)
                    rec['judges'][j] = {'before': s['before'], 'after': s['after'], 'verdict': s['verdict']}
                    say(f'  judge {j}: {s["before"]} → {s["after"]}')
                except Exception as e:
                    rec['judges'][j] = {'error': str(e)}
                    say(f'  judge {j}: ✗ {e}')
                A._RUN_METER.reset(tok)
                rec['cost_usd'] = round(rec['cost_usd'] + jm.summary()['usd'], 4)
        results.append(rec)
        (out / 'results.json').write_text(json.dumps(results, indent=1, ensure_ascii=False, default=str), encoding='utf-8')

    report = summarize(results, args.models, args.judges, spent())
    (out / 'report.md').write_text(report + '\n\n## Log\n```\n' + '\n'.join(log) + '\n```\n', encoding='utf-8')
    blind_page(out, cases, results)
    print('\n' + report)
    print(f'\nWrote {out / "report.md"} and {out / "blind_review.html"}')


def summarize(results, models, judges, spent):
    rows = []
    for m in models:
        rs = [r for r in results if r['model'] == m and not r.get('error') and r.get('final')]
        if not rs:
            rows.append(f'| {m} | — | — | — | — | — | — | — | — | — |'); continue
        cross, same, deltas = [], [], []
        for r in rs:
            for j, s in r['judges'].items():
                if s.get('after') is None:
                    continue
                (same if provider(j) == provider(m) else cross).append(s['after'])
                deltas.append(s['after'] - s['before'])
        avg = lambda xs: f'{sum(xs) / len(xs):.1f}' if xs else '—'
        aud = [r['audit_invented'] for r in rs if r.get('audit_invented') is not None]
        rows.append(f'| {m} | {avg(cross)} | {avg(same)} | {avg(deltas)} | {sum(r["invented"] for r in rs)} | '
                    f'{sum(aud) if aud else "—"} | '
                    f'{sum(r["changes"] for r in rs)} | {sum(r["reverted"] for r in rs)} | '
                    f'${sum(r["cost_usd"] for r in rs) / len(rs):.3f} | {sum(r["seconds"] for r in rs) / len(rs):.0f}s |')
    errs = [f'- {r["case"]} × {r["model"]}: {r["error"]}' for r in results if r.get('error')]
    return '\n'.join([
        '# APEX model benchmark',
        f'Total spent: ${spent:.2f} · judges: {", ".join(judges)}',
        '',
        '| Model | After score, other-provider judges | After score, same-provider judges | Avg gain | Invented claims (gate) | Invented claims (independent audit) | Edits kept | Edits reverted (fact check) | Cost / resume | Time / resume |',
        '|---|---|---|---|---|---|---|---|---|---|',
        *rows,
        '',
        'Read the first score column: it excludes a judge grading its own provider\'s writing. '
        '"Invented claims (gate)" counts numbers, tools and names in the output that appear nowhere in the original '
        'resume (a recruiter or reference check would catch these), using the deterministic gate APEX itself is built '
        'on; "(independent audit)" is a separate model reading each output whole ("—" when it was skipped or its '
        'reply was unreadable). `chat:` rows are the plain chatbot baseline, given the same brief. '
        '"Edits reverted" counts APEX rewrites its fact check rejected.',
        *(['', '## Errors', *errs] if errs else []),
    ])


def blind_page(out, cases, results):
    """One section per case: the original and each model's output under a random letter."""
    key, parts = {}, []
    for c in cases:
        rs = [r for r in results if r['case'] == c['name'] and r.get('final')]
        random.shuffle(rs)
        letters = 'ABCDEFGH'
        key[c['name']] = {letters[i]: r['model'] for i, r in enumerate(rs)}
        cols = ''.join(f'<div class="col"><h3>Version {letters[i]}</h3><pre>{escape(r["final"])}</pre></div>'
                       for i, r in enumerate(rs))
        parts.append(f'<section><h2>{escape(c["name"])} · target: {escape(c["title"])}</h2>'
                     f'<details><summary>Original</summary><pre>{escape(c["resume_text"])}</pre></details>'
                     f'<div class="grid">{cols}</div></section>')
    (out / 'blind_key.json').write_text(json.dumps(key, indent=1), encoding='utf-8')
    (out / 'blind_review.html').write_text(f'''<!doctype html><meta charset="utf-8"><title>APEX blind review</title>
<style>body{{font:14px system-ui,sans-serif;margin:24px;background:#fafafa;color:#111}}h2{{margin-top:40px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}}.col{{background:#fff;border:1px solid #ddd;border-radius:10px;padding:12px}}
pre{{white-space:pre-wrap;font:12.5px/1.55 ui-monospace,Consolas,monospace}}details{{margin:8px 0 16px}}</style>
<h1>Which version would get you the interview?</h1>
<p>For each resume, pick the version you'd send. Model names are hidden; tell Claude your picks
(e.g. "jordan: B, marcus: A") and it will reveal them with <code>python tools/benchmark.py --reveal {escape(str(out))}</code>.</p>
{''.join(parts)}''', encoding='utf-8')


def reveal(run_dir):
    key = json.loads((Path(run_dir) / 'blind_key.json').read_text(encoding='utf-8'))
    for case, m in key.items():
        print(case + ': ' + ', '.join(f'{k} = {v}' for k, v in m.items()))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--models', nargs='+', default=['gpt-6.1-sol', 'claude-sonnet-5-5', 'claude-opus-5-5'])
    ap.add_argument('--judges', nargs='+', default=['gpt-6.1-sol', 'claude-opus-5-5'])
    ap.add_argument('--cases', nargs='+', default=[str(ROOT / 'bench' / 'cases'), str(ROOT / 'bench' / 'private')])
    ap.add_argument('--only', nargs='*', help='case names to run')
    ap.add_argument('--budget', type=float, default=3.00, help='stop before spending more than this (USD)')
    ap.add_argument('--fabrication-judge', help='model for the independent invented-claims audit '
                    '(default: the first judge; "none" to skip)')
    ap.add_argument('--out')
    ap.add_argument('--reveal', metavar='RUN_DIR')
    a = ap.parse_args()
    if a.fabrication_judge is None:
        a.fabrication_judge = a.judges[0] if a.judges else None
    elif a.fabrication_judge.lower() == 'none':
        a.fabrication_judge = None
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    reveal(a.reveal) if a.reveal else run(a)
