"""APEX feature benchmark: is each tool better than just asking the same model directly?

For every case and feature, runs the real APEX function (the code behind the route, in
process) and a plain chatbot request a person would type for the same job, using the same
model. A judge model then compares the two blind, twice with the order swapped (position
bias), and an independent auditor (a different model) lists claims about the candidate that
the resume does not support, in both outputs.

    python tools/feature_bench.py --only devon_park nina_volkova --budget 6
    python tools/feature_bench.py --features cover_letter tailor --budget 2

Cases: bench/cases/*.json (see tools/benchmark.py). Features also read `company`,
`from_role`, `job_desc` and `interview` {question, answer}; a case without a field skips
the features that need it.
"""
import argparse
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from benchmark import load_cases  # noqa: E402

JUDGE_SYSTEM = ('You are a hiring manager and career coach comparing two outputs written for the same job seeker. '
                'You are strict and specific. Return ONLY valid JSON.')

AUDIT_SYSTEM = ('You are an independent reference checker. You compare text written for a job seeker with their resume '
                'and list every claim about the candidate that the resume does not support. Return ONLY valid JSON.')


def _location(resume):
    m = re.search(r'\b([A-Z][a-zA-Z .]+, [A-Z]{2})\b', resume[:400])
    return m.group(1).strip() if m else ''


# ── Features: what APEX runs, and what a person would ask a chatbot instead ─────────────
# need: case fields required; apex(A, case) -> data dict; show(data) -> text the user sees;
# chat(case) -> the plain prompt; task: what both outputs are for (the judge reads it).

def _stream(fn, *args, data_type, **kw):
    """Run a streaming tool with a collecting emit; return its data event (raise on its error event)."""
    events = []
    fn(*args, events.append, **kw)
    for e in events:
        if e.get('type') == 'error':
            raise RuntimeError(e.get('msg'))
    for e in events:
        if e.get('type') == data_type:
            return e['data'] if 'data' in e else e
    raise RuntimeError(f'no {data_type} event')


def _label(k):
    return k.replace('_', ' ').strip().capitalize()


def _flat(obj, indent=0):
    """Readable text of a JSON payload, close to how the page shows it: headings for fields,
    bullets for lists, and a plain note where the fact check removed something."""
    pad = '  ' * indent
    if isinstance(obj, dict):
        out = []
        for k, v in obj.items():
            if k in ('verified', 'measured', 'id') or v in (None, '', [], {}):
                if v is None and not k.endswith('withheld'):
                    out.append(f'{pad}{_label(k)}: (removed by the fact check)')
                continue
            if k.endswith('withheld'):
                why = '; '.join(map(str, v)) if isinstance(v, list) else _flat(v)
                out.append(f'{pad}(Removed by the fact check: {why[:300]})')
            elif isinstance(v, (dict, list)):
                out.append(f'{pad}{_label(k)}:')
                out.append(_flat(v, indent + 1))
            else:
                out.append(f'{pad}{_label(k)}: {v}')
        return '\n'.join(x for x in out if x)
    if isinstance(obj, list):
        return '\n'.join(f'{pad}-' + (('\n' + _flat(x, indent + 1)) if isinstance(x, (dict, list)) else f' {x}')
                         for x in obj)
    return f'{pad}{obj}'


def _drop(d, *keys):
    return {k: v for k, v in (d or {}).items() if k not in keys}


FEATURES = {
    'tailor': dict(
        need=('job_desc',),
        task='Tailor the resume to this job posting. Output: the tailored resume (and any notes for the candidate).',
        apex=lambda A, c: _stream(A.job_tailor, c['job_desc'], c['resume_text'], c['title'], c['sector'],
                                  data_type='tailor_data'),
        show=lambda d: (d.get('tailored_resume') or '') + '\n\n' + _flat(
            {k: d.get(k) for k in ('gaps', 'tailoring_notes', 'questions')}),
        chat=lambda c: f"Tailor my resume to this job posting so I get an interview. Return the tailored resume.\n\n"
                       f"JOB POSTING:\n{c['job_desc']}\n\nMY RESUME:\n{c['resume_text']}"),
    'cover_letter': dict(
        need=('job_desc', 'company'),
        task='Write a cover letter for this job posting.',
        apex=lambda A, c: A.cover_letter(c['title'], c['sector'], c['resume_text'], company=c['company'],
                                         posting=c['job_desc']),
        show=lambda d: d.get('letter') or _flat({'letter_withheld': d.get('withheld')}),
        chat=lambda c: f"Write a cover letter for the {c['title']} role at {c['company']}.\n\nJOB POSTING:\n"
                       f"{c['job_desc']}\n\nMY RESUME:\n{c['resume_text']}"),
    'bullets': dict(
        need=(),
        task='Rate each resume bullet for the target role and rewrite the weak ones.',
        apex=lambda A, c: _stream(A.bullet_ranker, c['resume_text'], c['title'], c['sector'], c['keywords'],
                                  data_type='bullet_data'),
        show=_flat,
        chat=lambda c: f"Rate each bullet on my resume from 1-10 for a {c['title']} role, explain why, and rewrite "
                       f"the weak ones.\n\nMY RESUME:\n{c['resume_text']}"),
    'xray': dict(
        need=(),
        task='Review the resume like a recruiter: the biggest weaknesses for the target role and how to fix each.',
        apex=lambda A, c: _stream(A.weakness_xray, c['title'], c['sector'], c['resume_text'], c['keywords'],
                                  data_type='xray_data'),
        show=_flat,
        chat=lambda c: f"Review my resume like a recruiter hiring a {c['title']}. What are the biggest weaknesses "
                       f"and exactly how do I fix each one?\n\nMY RESUME:\n{c['resume_text']}"),
    'match': dict(
        need=('job_desc',),
        task='Assess how well the candidate matches this posting, whether to apply, and what to change first.',
        apex=lambda A, c: _stream(A.smart_match, c['job_desc'], c['resume_text'], data_type='match_data'),
        show=_flat,
        chat=lambda c: f"How well do I match this job? Should I apply, and what should I change on my resume "
                       f"first?\n\nJOB POSTING:\n{c['job_desc']}\n\nMY RESUME:\n{c['resume_text']}"),
    'bridge': dict(
        need=('from_role',),
        task='Help the candidate move from their current role to the target role: translate skills, reframe '
             'experience, name the gaps, and give a short narrative and interview answers.',
        apex=lambda A, c: _stream(A.skills_bridge, c['from_role'], c['title'], c['resume_text'], c['sector'],
                                  data_type='bridge_data'),
        show=_flat,
        chat=lambda c: f"I'm a {c['from_role']} trying to become a {c['title']}. Using my resume, translate my "
                       f"skills, reframe my experience bullets, tell me my gaps, and give me a short narrative and "
                       f"answers for interviews.\n\nMY RESUME:\n{c['resume_text']}"),
    'negotiate': dict(
        need=(),
        task='Give a salary target with evidence, the candidate\'s leverage, and a negotiation script.',
        apex=lambda A, c: _stream(A.salary_brief, c['title'], c['sector'], c.get('seniority', 'senior'),
                                  _location(c['resume_text']), c['resume_text'], {}, data_type='negotiate_data'),
        show=_flat,
        chat=lambda c: f"I'm getting an offer for a {c['title']} role ({c.get('seniority', 'senior')}) in "
                       f"{_location(c['resume_text']) or 'the US'}. Using my resume, what salary should I target, "
                       f"what is my leverage, and give me a negotiation script.\n\nMY RESUME:\n{c['resume_text']}"),
    'followup': dict(
        need=('company',),
        task='Write follow-up messages after applying 7 days ago: a week-1 email, a week-2 email and a LinkedIn note.',
        apex=lambda A, c: _stream(A.followup_generator, c['company'], c['title'], 7, '',
                                  data_type='followup_data', resume=c['resume_text']),
        show=lambda d: _flat(_drop(d, 'company')),
        chat=lambda c: f"I applied for the {c['title']} role at {c['company']} 7 days ago and haven't heard back. "
                       f"Write a follow-up email for now, another for next week, and a short LinkedIn note to the "
                       f"recruiter.\n\nMY RESUME:\n{c['resume_text']}"),
    'grade_answer': dict(
        need=('interview',),
        task='Grade the candidate\'s interview answer, explain what is weak, and write a better version that stays '
             'true to their experience.',
        apex=lambda A, c: _stream(A.grade_interview_answer, c['interview']['question'], c['interview']['answer'],
                                  c['title'], c['sector'], data_type='answer_grade', resume=c['resume_text']),
        show=lambda d: _flat(_drop(d, 'question')),
        chat=lambda c: f"Grade my interview answer for a {c['title']} role from 1-10, tell me what's weak, and "
                       f"write a better version.\n\nQUESTION: {c['interview']['question']}\nMY ANSWER: "
                       f"{c['interview']['answer']}\n\nMY RESUME:\n{c['resume_text']}"),
}


def judge(A, E, model, feature, case, first, second):
    raw = A.gpt(JUDGE_SYSTEM, f"""{E.DATA_RULE}
TASK BOTH OUTPUTS WERE WRITTEN FOR: {FEATURES[feature]['task']}
Target role: {case['title']}
{E._data('JOB_POSTING', case.get('job_desc', '')) if case.get('job_desc') else ''}
THE CANDIDATE'S RESUME (the only evidence about them):
{E._data('RESUME', case['resume_text'])}

OUTPUT A:
{E._data('OUTPUT_A', first)}

OUTPUT B:
{E._data('OUTPUT_B', second)}

Which output would help this candidate more, used as is? Judge: usefulness for the task, specificity to this candidate
and this job, quality of thinking and writing, and honesty. Any claim about the candidate (a number, tool, employer,
achievement, scope, credential) that the resume does not support is a serious defect: a recruiter, interviewer or
reference check would catch it, so do not reward invented specifics. Content marked as removed by the fact check is
simply missing. Length is not a virtue by itself. The two outputs come from different tools, and one may be a
set of labeled fields from an app: judge substance, not formatting. Square-bracketed blanks the candidate is asked to
fill in (e.g. [X%]) are honest placeholders, not claims.

Return ONLY JSON: {{"score_A": 1-10, "score_B": 1-10, "winner": "A"|"B"|"tie", "reason": "one or two sentences"}}""",
              max_tokens=900, json_mode=True, effort='medium', model=model)
    d = E._jload(raw)
    w = str(d.get('winner', 'tie')).strip().upper()
    return {'A': _num(d.get('score_A')), 'B': _num(d.get('score_B')), 'winner': w if w in ('A', 'B') else 'tie',
            'reason': str(d.get('reason', ''))[:400]}


def _num(x):
    try:
        return max(1.0, min(10.0, float(x)))
    except (TypeError, ValueError):
        return None


def audit(A, E, model, case, text):
    raw = A.gpt(AUDIT_SYSTEM, f"""{E.DATA_RULE}
RESUME (the only evidence about the candidate):
{E._data('RESUME', case['resume_text'])}

TEXT WRITTEN FOR THE CANDIDATE:
{E._data('TEXT', text)}

List every statement in the TEXT that presents something as true of the candidate which the RESUME does not support:
a number, tool, employer, title, credential, scope, team size, outcome, years of experience, or a causal claim the
resume does not make. Advice, suggestions ("add X if you have it"), questions, placeholders like [X], market facts and
claims about the employer are not claims about the candidate. Rewording and the standard name of something the
resume clearly shows are fine. Quote each claim once.

Return ONLY JSON: {{"unsupported": [{{"claim": "quote", "why": "..."}}]}} (an empty list when everything is supported)""",
              max_tokens=2000, json_mode=True, effort='medium', model=model)
    d = E._jload(raw)
    if not isinstance(d.get('unsupported'), list):
        return None
    return [str(x.get('claim') if isinstance(x, dict) else x)[:200] for x in d['unsupported']]


def run_one(A, E, args, case, feature):
    f = FEATURES[feature]
    rec = {'case': case['name'], 'feature': feature, 'error': None}
    meter = A.Meter(); tok = A._RUN_METER.set(meter)
    t0 = time.time()
    try:
        apex_text = f['show'](f['apex'](A, case)).strip()
        rec['apex_seconds'] = round(time.time() - t0, 1)
        rec['apex_cost'] = meter.summary()['usd']
        t1 = time.time()
        chat_text = A.gpt('You are a helpful assistant.', f['chat'](case), max_tokens=4000, effort='medium',
                          model=args.model).strip()
        rec['chat_seconds'] = round(time.time() - t1, 1)
        rec['apex'], rec['chat'] = apex_text, chat_text
        if not apex_text:
            raise RuntimeError('APEX returned nothing to show')
        j1 = judge(A, E, args.judge, feature, case, apex_text, chat_text)      # A = APEX
        j2 = judge(A, E, args.judge, feature, case, chat_text, apex_text)      # A = chat
        votes = [{'A': 'apex', 'B': 'chat'}.get(j1['winner'], 'tie'), {'A': 'chat', 'B': 'apex'}.get(j2['winner'], 'tie')]
        rec['outcome'] = votes[0] if votes[0] == votes[1] else 'tie'
        sc = lambda xs: round(sum(xs) / len(xs), 2) if xs else None
        rec['apex_score'] = sc([x for x in (j1['A'], j2['B']) if x is not None])
        rec['chat_score'] = sc([x for x in (j1['B'], j2['A']) if x is not None])
        rec['reasons'] = [j1['reason'], j2['reason']]
        if args.auditor:
            rec['apex_unsupported'] = audit(A, E, args.auditor, case, apex_text)
            rec['chat_unsupported'] = audit(A, E, args.auditor, case, chat_text)
    except Exception as e:
        rec['error'] = f'{type(e).__name__}: {e}'
    A._RUN_METER.reset(tok)
    rec['cost_usd'] = round(meter.summary()['usd'], 4)
    rec['seconds'] = round(time.time() - t0, 1)
    return rec


def summarize(results, spent, args):
    rows = []
    for feat in FEATURES:
        rs = [r for r in results if r['feature'] == feat and not r['error']]
        if not rs:
            continue
        w = sum(r['outcome'] == 'apex' for r in rs)
        l = sum(r['outcome'] == 'chat' for r in rs)
        t = len(rs) - w - l
        avg = lambda k: f"{sum(r[k] for r in rs if r.get(k) is not None) / max(1, sum(r.get(k) is not None for r in rs)):.1f}"
        inv = lambda k: sum(len(r[k]) for r in rs if r.get(k) is not None)
        rows.append(f"| {feat} | {w}-{t}-{l} | {avg('apex_score')} | {avg('chat_score')} | {inv('apex_unsupported')} | "
                    f"{inv('chat_unsupported')} | ${sum(r['apex_cost'] for r in rs) / len(rs):.3f} | "
                    f"{sum(r['apex_seconds'] for r in rs) / len(rs):.0f}s |")
    ok = [r for r in results if not r['error']]
    w = sum(r['outcome'] == 'apex' for r in ok)
    l = sum(r['outcome'] == 'chat' for r in ok)
    errs = [f"- {r['case']} × {r['feature']}: {r['error']}" for r in results if r['error']]
    return '\n'.join([
        '# APEX feature benchmark: APEX vs. asking the model directly',
        f'Model: {args.model} for both sides · judge: {args.judge} (blind, both orders) · '
        f'auditor: {args.auditor or "none"} · total spent ${spent:.2f}',
        f'Overall: APEX won {w}, tied {len(ok) - w - l}, lost {l} of {len(ok)} comparisons.',
        '',
        '| Feature | APEX win-tie-loss | APEX score | Chat score | Unsupported claims, APEX | Unsupported claims, chat '
        '| APEX cost / run | APEX time / run |',
        '|---|---|---|---|---|---|---|---|',
        *rows,
        '',
        'A comparison counts as a win only when the judge picked the same side in both orders; a split is a tie. '
        'Scores are the judge\'s 1-10, averaged over both orders. Unsupported claims are counted by a separate '
        'model reading each output against the resume.',
        *(['', '## Errors', *errs] if errs else []),
    ])


def outputs_page(results):
    parts = ['# Outputs side by side', '']
    for r in results:
        parts += [f"## {r['case']} · {r['feature']} · winner: {r.get('outcome', 'error')}",
                  f"APEX {r.get('apex_score')} vs chat {r.get('chat_score')}. " + ' / '.join(r.get('reasons') or []), '']
        if r['error']:
            parts += [f"Error: {r['error']}", '']
            continue
        for side in ('apex', 'chat'):
            parts += [f'### {side.upper()}', '```', r[side], '```']
            bad = r.get(f'{side}_unsupported')
            if bad:
                parts += ['Unsupported: ' + '; '.join(bad), '']
    return '\n'.join(parts)


def main(args):
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    import agent_server as A          # loads config.json itself; keys are never printed
    import apex_engine as E
    A.MODEL = args.model or A.MODEL     # the APEX side; the chat side is asked with the same model
    args.model = A.MODEL
    cases = load_cases(args.cases, args.only)
    if not cases:
        sys.exit('no cases found')
    feats = args.features or list(FEATURES)
    jobs = [(c, f) for c in cases for f in feats if all(c.get(k) for k in FEATURES[f]['need'])]
    random.Random(7).shuffle(jobs)     # spread features over the budget instead of finishing case by case
    out = Path(args.out or ROOT / 'bench' / 'runs' / ('features-' + datetime.now().strftime('%Y%m%d-%H%M%S')))
    out.mkdir(parents=True, exist_ok=True)
    spent = lambda: A.TOTAL_METER.summary()['usd']
    print(f'APEX feature benchmark · {len(jobs)} comparisons · model {args.model} · judge {args.judge} · '
          f'budget ${args.budget:.2f}', flush=True)
    results = []

    def work(job):
        case, feat = job
        if spent() > args.budget:
            return {'case': case['name'], 'feature': feat, 'error': 'skipped: budget reached'}
        r = run_one(A, E, args, case, feat)
        print(f"  {case['name']:<14} {feat:<13} " + (r['error'] or f"{r['outcome']:<5} APEX {r['apex_score']} vs "
              f"chat {r['chat_score']} · ${r['cost_usd']:.3f} · spent ${spent():.2f}"), flush=True)
        return r

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for r in pool.map(work, jobs):
            results.append(r)
            (out / 'results.json').write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding='utf-8')
    report = summarize(results, spent(), args)
    (out / 'report.md').write_text(report + '\n', encoding='utf-8')
    (out / 'outputs.md').write_text(outputs_page(results), encoding='utf-8')
    print('\n' + report + f'\n\nWrote {out / "report.md"} and {out / "outputs.md"}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', default=None, help='model for APEX and the chat baseline (default: APEX_MODEL)')
    ap.add_argument('--judge', default='claude-opus-5-5')
    ap.add_argument('--auditor', default='claude-sonnet-5-5', help='model for the unsupported-claims audit ("none" to skip)')
    ap.add_argument('--features', nargs='*', choices=list(FEATURES))
    ap.add_argument('--cases', nargs='+', default=[str(ROOT / 'bench' / 'cases'), str(ROOT / 'bench' / 'private')])
    ap.add_argument('--only', nargs='*', help='case names to run')
    ap.add_argument('--budget', type=float, default=6.00, help='stop starting new comparisons past this (USD)')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--out')
    a = ap.parse_args()
    if a.auditor and a.auditor.lower() == 'none':
        a.auditor = None
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main(a)
