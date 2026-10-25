"""Find the applicant-tracking boards of AI companies, so the job agent can read their postings
the day they go up (before aggregators copy them).

Candidates come from the public YC company directory (yc-oss.github.io, no key) filtered to AI
tags and companies marked hiring, plus any names passed on the command line. Each candidate's
likely board names are probed on Greenhouse, Ashby and Lever; only boards that answer with a job
list are kept. Writes data/boards.json: {"greenhouse": {slug: company}, "ashby": {...}, "lever": {...}}.

    python tools/discover_boards.py                 # YC AI companies that are hiring
    python tools/discover_boards.py --names "Scale AI" "Together AI"
    python tools/discover_boards.py --max 400 --threads 24
"""
import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'boards.json'
YC_HIRING = 'https://yc-oss.github.io/api/companies/hiring.json'
AI_TAGS = re.compile(r'\b(?:ai|artificial intelligence|machine learning|generative ai|ai assistant|ai agents?|llm|'
                     r'computer vision|nlp|conversational ai|ml ?ops|data science|robotics|speech)\b', re.I)
NOISE = re.compile(r'\b(?:inc|llc|ltd|corp|co|company|labs|ai|the|technologies|technology)\b')


def get(url, timeout=8):
    try:
        with urlopen(Request(url, headers={'User-Agent': 'APEX-board-discovery', 'Accept': 'application/json'}),
                     timeout=timeout) as r:
            return r.read(60_000_000)
    except Exception:
        return None


def slugs(name, website=''):
    raw = re.sub(r'[^a-z0-9 ]', ' ', name.lower().replace('&', ' and ')).split()
    core = NOISE.sub(' ', ' '.join(raw)).split()
    out = [''.join(core), '-'.join(core), ''.join(raw), '-'.join(raw)]
    host = re.sub(r'^https?://(?:www\.)?', '', website or '').split('/')[0]
    if host:
        out.append(host.split('.')[0])
    return [s for s in dict.fromkeys(out) if len(s) >= 3]


def probe(kind, slug):
    """A job count when the board exists, else None."""
    if kind == 'greenhouse':
        raw = get(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs')
        key = 'jobs'
    elif kind == 'ashby':
        raw = get(f'https://api.ashbyhq.com/posting-api/job-board/{slug}')
        key = 'jobs'
    else:
        raw = get(f'https://api.lever.co/v0/postings/{slug}?mode=json')
        key = None
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    jobs = d.get(key) if key else d
    return len(jobs) if isinstance(jobs, list) else None


def candidates(max_n):
    raw = get(YC_HIRING, timeout=30)
    if not raw:
        sys.exit('could not read the YC directory')
    out = []
    for c in json.loads(raw):
        tags = ' '.join(c.get('tags') or []) + ' ' + (c.get('industry') or '') + ' ' + (c.get('one_liner') or '')
        if AI_TAGS.search(tags) and c.get('name'):
            out.append((c['name'], c.get('website') or ''))
    return out[:max_n]


def main(a):
    found = {'greenhouse': {}, 'ashby': {}, 'lever': {}}
    if OUT.exists():
        found.update(json.loads(OUT.read_text(encoding='utf-8')))
    names = [(n, '') for n in a.names] if a.names else candidates(a.max)
    print(f'{len(names)} candidate companies', flush=True)
    lock = threading.Lock()
    done = [0]

    def one(item):
        name, site = item
        for slug in slugs(name, site)[:4]:
            for kind in ('greenhouse', 'ashby', 'lever'):
                if slug in found[kind]:
                    return
                n = probe(kind, slug)
                if n:
                    with lock:
                        found[kind][slug] = name
                    print(f'  {name} -> {kind}/{slug} ({n} jobs)', flush=True)
                    return
        with lock:
            done[0] += 1
    t = time.time()
    with ThreadPoolExecutor(max_workers=a.threads) as ex:
        list(ex.map(one, names))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(found, indent=1, sort_keys=True), encoding='utf-8')
    total = sum(len(v) for v in found.values())
    print(f'{total} boards in {OUT} ({time.time() - t:.0f}s)')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--names', nargs='*')
    ap.add_argument('--max', type=int, default=1200)
    ap.add_argument('--threads', type=int, default=24)
    main(ap.parse_args())
