"""APEX answer benchmark: how much does answering the engine's questions help?

The engine asks the candidate for facts only they know ("How many users?") and rewrites
those lines with the answers. This measures that loop on bench cases that carry `facts`:
true details about the candidate that the resume leaves out. For each case:

  1. engine.optimize on the resume (no judge) -> edits and up to 8 questions
  2. a simulated candidate answers each question from the hidden facts only, or leaves it
     blank ("I don't know"), so no answer is invented
  3. engine.revise with those answers (all first-run edits kept)
  4. the blind hiring-manager judge scores original -> first run and original -> answered
  5. a cover letter written from the first-run resume and one from the answered resume,
     compared blind in both orders
  6. an independent audit of claims the answered resume makes that neither the original
     resume nor the candidate's answers support

    python tools/answer_bench.py --budget 3.5
    python tools/answer_bench.py --only devon_park lena_fischer --budget 1.5
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from benchmark import FABRICATION_SYSTEM, bound_llm, load_cases, make_target  # noqa: E402

CANDIDATE_SYSTEM = ('You are a job candidate answering your resume writer\'s questions. You know only the facts you are '
                    'given. Return ONLY valid JSON.')

LETTER_JUDGE_SYSTEM = ('You are the hiring manager for the role. You compare two cover letters from the same candidate. '
                       'Return ONLY valid JSON.')


def simulate_answers(llm, E, facts, questions):
    """{id: answer} from the hidden facts; a question the facts do not answer is left out."""
    if not questions:
        return {}
    raw = llm(CANDIDATE_SYSTEM, f"""{E.DATA_RULE}
WHAT YOU KNOW ABOUT YOUR OWN WORK (the only facts you may use):
{E._data('FACTS', chr(10).join('- ' + f for f in facts))}

QUESTIONS FROM YOUR RESUME WRITER:
{E._data('QUESTIONS', json.dumps([{'id': q['id'], 'line': q['line'], 'question': q['question']} for q in questions]))}

Answer each question briefly (a few words or one sentence), using only the facts above. If the facts do not answer
it, return "" for that id: do not guess, estimate or round to something you were not told.

Return ONLY JSON: {{"answers": {{"B3": "about 40 clinics", "B5": ""}}}}""", max_tokens=1200, json_mode=True,
              effort='low')
    d = E._jload(raw).get('answers') or {}
    asked = {q['id'] for q in questions}
    return {str(k): str(v).strip()[:300] for k, v in d.items() if k in asked and str(v or '').strip()}


def letter_duel(llm, E, case, first, second):
    raw = llm(LETTER_JUDGE_SYSTEM, f"""{E.DATA_RULE}
Role: {case['title']} at {case.get('company') or 'the company'}
{E._data('JOB_POSTING', case.get('job_desc', ''))}

LETTER A:
{E._data('LETTER_A', first)}

LETTER B:
{E._data('LETTER_B', second)}

Which letter makes you more likely to interview this candidate? Judge specificity, evidence of impact, fit to the
posting and credibility. Return ONLY JSON: {{"score_A": 1-10, "score_B": 1-10, "winner": "A"|"B"|"tie", "why": "..."}}""",
              max_tokens=700, json_mode=True, effort='medium')
    d = E._jload(raw)
    num = lambda x: float(x) if isinstance(x, (int, float)) or str(x).replace('.', '', 1).isdigit() else None
    return num(d.get('score_A')), num(d.get('score_B')), str(d.get('winner', 'tie')).upper(), str(d.get('why', ''))[:300]


def audit(llm, E, evidence, text):
    raw = llm(FABRICATION_SYSTEM, f"""{E.DATA_RULE}
ORIGINAL RESUME AND THE CANDIDATE'S OWN ANSWERS (the only evidence about the candidate):
{E._data('ORIGINAL', evidence)}

REWRITTEN RESUME:
{E._data('REWRITE', text)}

List every claim in the REWRITTEN resume that the evidence does not support (numbers, tools, scope, outcomes,
seniority). Rewording and condensing are fine. Return ONLY JSON: {{"unsupported": [{{"claim": "quote", "why": "..."}}]}}""",
              max_tokens=2000, json_mode=True, effort='medium')
    d = E._jload(raw)
    return [str(x.get('claim') if isinstance(x, dict) else x)[:200] for x in d.get('unsupported') or []] \
        if isinstance(d.get('unsupported'), list) else None


def run(args):
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    import agent_server as A          # loads config.json itself; keys are never printed
    import apex_engine as E
    cases = [c for c in load_cases(args.cases, args.only) if c.get('facts')]
    if not cases:
        sys.exit('no cases with "facts" found')
    out = Path(args.out or ROOT / 'bench' / 'runs' / ('answers-' + datetime.now().strftime('%Y%m%d-%H%M%S')))
    out.mkdir(parents=True, exist_ok=True)
    A.MODEL = args.model or A.MODEL     # the engine and the letters
    spent = lambda: A.TOTAL_METER.summary()['usd']
    llm, cand, aud = bound_llm(A, A.MODEL), bound_llm(A, args.candidate), bound_llm(A, args.auditor)
    results = []
    print(f'APEX answer benchmark · {len(cases)} case(s) · budget ${args.budget:.2f}', flush=True)
    for case in cases:
        if results and spent() + spent() / len(results) > args.budget:
            print(f'  ! stopping: the next case would pass the ${args.budget:.2f} budget (spent ${spent():.2f})')
            break
        t0, target = time.time(), make_target(A, case)
        rec = {'case': case['name']}
        try:
            first = E.optimize(llm, case['resume_text'], target, judge_it=False)
            qs = first['questions']
            answers = simulate_answers(cand, E, case['facts'], qs)
            kept = {c['id']: c['after'] for c in first['changes']}
            second = E.revise(llm, case['resume_text'], target, answers, kept=kept, prior_questions=qs,
                              order=first['order'], section_order=first['section_order'], judge_it=False)
            j1 = E.judge(llm, case['resume_text'], first['final'], target)
            j2 = E.judge(llm, case['resume_text'], second['final'], target)
            l1 = A.cover_letter(case['title'], case.get('sector', 'general'), first['final'],
                                company=case.get('company', ''), posting=case.get('job_desc', ''))['letter']
            l2 = A.cover_letter(case['title'], case.get('sector', 'general'), second['final'],
                                company=case.get('company', ''), posting=case.get('job_desc', ''))['letter']
            duel = None
            if l1 and l2:
                a1, b1, w1, why = letter_duel(llm, E, case, l1, l2)        # A = first-run letter
                a2, b2, w2, _ = letter_duel(llm, E, case, l2, l1)          # A = answered letter
                sc = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
                win = {'A': 'first', 'B': 'answered'}.get(w1, 'tie'), {'A': 'answered', 'B': 'first'}.get(w2, 'tie')
                duel = {'first': sc([x for x in (a1, b2) if x is not None]),
                        'answered': sc([x for x in (b1, a2) if x is not None]),
                        'winner': win[0] if win[0] == win[1] else 'tie', 'why': why}
            evidence = case['resume_text'] + '\n\nCANDIDATE ANSWERS:\n' + '\n'.join(f'{k}: {v}' for k, v in answers.items())
            unsupported = audit(aud, E, evidence, second['final'])
            rec.update(questions=len(qs), answered=len(answers), revised=len(second.get('revised') or []),
                       rejected=len(second['rejected']), first_score=[j1['before'], j1['after']],
                       answered_score=[j2['before'], j2['after']], letters=duel,
                       unsupported=unsupported, answers=answers, question_list=qs,
                       first_final=first['final'], answered_final=second['final'], letter_first=l1, letter_answered=l2)
            print(f"  {case['name']:<14} questions {len(qs)}, answered {len(answers)}, rewritten {rec['revised']} · "
                  f"score {j1['before']}→{j1['after']} first run, {j2['before']}→{j2['after']} with answers · "
                  f"letter {duel and duel['winner']} ({duel and duel['first']} vs {duel and duel['answered']}) · "
                  f"unsupported {None if unsupported is None else len(unsupported)} · {time.time() - t0:.0f}s · "
                  f"spent ${spent():.2f}", flush=True)
        except Exception as e:
            rec['error'] = f'{type(e).__name__}: {e}'
            print(f"  {case['name']}: ✗ {rec['error']}", flush=True)
        results.append(rec)
        (out / 'results.json').write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding='utf-8')
    (out / 'report.md').write_text(report(results, spent()), encoding='utf-8')
    print('\n' + report(results, spent()) + f'\nWrote {out / "report.md"}')


def report(results, spent):
    ok = [r for r in results if not r.get('error')]
    rows = [f"| {r['case']} | {r['answered']}/{r['questions']} | {r['revised']} | {r['first_score'][0]} → "
            f"{r['first_score'][1]} | {r['answered_score'][0]} → {r['answered_score'][1]} | "
            f"{(r['letters'] or {}).get('first', '—')} vs {(r['letters'] or {}).get('answered', '—')} "
            f"({(r['letters'] or {}).get('winner', '—')}) | {'—' if r['unsupported'] is None else len(r['unsupported'])} |"
            for r in ok]
    gain = lambda k: [r[k][1] - r[k][0] for r in ok if None not in r[k]]
    g1, g2 = gain('first_score'), gain('answered_score')
    avg = lambda xs: f'{sum(xs) / len(xs):+.1f}' if xs else '—'
    return '\n'.join([
        '# APEX answer benchmark', f'Total spent: ${spent:.2f}', '',
        f'Average judge gain: first run {avg(g1)}, after answering {avg(g2)}.', '',
        '| Case | Questions answered | Lines rewritten | Score, first run | Score, with answers | Cover letter: first vs answered (winner) | Unsupported claims (audit) |',
        '|---|---|---|---|---|---|---|', *rows, '',
        'The simulated candidate answers only from facts the resume leaves out, and leaves a question blank when '
        'those facts do not answer it. Scores are the blind hiring-manager judge (both orders, averaged); the first '
        'number in each pair is the original resume, scored in the same comparison. The audit counts claims in the '
        'answered resume that neither the original resume nor the answers support.',
        *(['', '## Errors', *[f"- {r['case']}: {r['error']}" for r in results if r.get('error')]]
          if any(r.get('error') for r in results) else []),
    ]) + '\n'


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', help='model for the engine, letters and judges (default: APEX_MODEL)')
    ap.add_argument('--candidate', default='claude-sonnet-5-5', help='model playing the candidate')
    ap.add_argument('--auditor', default='claude-sonnet-5-5', help='model for the unsupported-claims audit')
    ap.add_argument('--cases', nargs='+', default=[str(ROOT / 'bench' / 'cases'), str(ROOT / 'bench' / 'private')])
    ap.add_argument('--only', nargs='*', help='case names to run')
    ap.add_argument('--budget', type=float, default=3.5, help='stop before a case that would pass this (USD)')
    ap.add_argument('--out')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    run(a)
