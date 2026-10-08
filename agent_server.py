#!/usr/bin/env python3
"""
APEX Resume Intelligence Agent v10 — TRUTH-PRESERVING EDITION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

COMPETITIVE ANALYSIS — How we beat every competitor:

  Jobscan ($49/mo)    → We add: live data + self-improvement loop + free
  Rezi ($29/mo)       → We add: real scraping + cover letter + interview prep
  Teal ($29/mo)       → We add: agentic loop + sector intelligence + salary data
  Wobo (free)         → We add: STAR rewrites + 11 live sources + iteration
  Enhancv ($25/mo)    → We add: live market validation + cover letter

INNOVATIONS NO COMPETITOR HAS:
  ▸ Self-Improvement Loop  — 3 iterations, each grading + beating the last
  ▸ Live Market Scraping   — Real JSearch/Indeed/LinkedIn data, not static DB
  ▸ Salary Intelligence    — Which skills add $ to your salary right now
  ▸ Cover Letter Agent     — Tailored to role + company from same live data
  ▸ Interview Prep Agent   — Q&A based on your resume gaps vs job market
  ▸ STAR Framework         — Every bullet rewritten as Situation-Task-Action-Result
  ▸ Hard vs Soft Skills    — Separate analysis like Jobscan but with live data
  ▸ Sector-Aware Routing   — Right sources for every industry

Run: python agent_server.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json, time, re, socket, threading, traceback, base64, uuid, os
import xml.etree.ElementTree as ET
import html as html_lib
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import quote_plus

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PORT          = 7842
FETCH_TIMEOUT = 12
GPT_TIMEOUT   = 90
GPT_RETRIES   = 2
MIN_LISTINGS  = 5
MAX_CORPUS    = 16000
LOOP_ITERS    = 3   # self-improvement iterations

def load_config():
    import os
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    if os.path.exists(config_path):
        try:
            cfg = json.load(open(config_path))
            ok  = cfg.get('OPENAI_KEY','').strip()
            js  = cfg.get('JSEARCH_KEY','').strip()
            if ok:
                print(f'  ✓ Config loaded from {config_path}')
                return ok, js
        except Exception as e:
            print(f'  ⚠ config.json error: {e}')
    # env fallback
    ok = __import__('os').environ.get('OPENAI_API_KEY','').strip()
    js = __import__('os').environ.get('JSEARCH_API_KEY','').strip()
    if ok:
        print('  ✓ Keys from environment variables')
        return ok, js
    print('\n  ERROR: No config.json found and no env vars set.')
    print('  Create config.json with OPENAI_KEY and JSEARCH_KEY.')
    exit(1)

OPENAI_KEY, JSEARCH_KEY = load_config()
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# NETWORK LAYER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def http_get(url, headers=None, timeout=FETCH_TIMEOUT):
    h = {'User-Agent': UA, 'Accept': '*/*', 'Accept-Encoding': 'identity', 'Connection': 'close'}
    if headers: h.update(headers)
    try:
        with urlopen(Request(url, headers=h), timeout=timeout) as r:
            raw = r.read(2_000_000)
        try:    return raw.decode('utf-8')
        except: return raw.decode('latin-1', errors='replace')
    except Exception: return None

def clean(text):
    if not text: return ''
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>',  ' ', text, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html_lib.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()

def parse_rss(xml_text):
    if not xml_text: return []
    items = []
    try:
        x    = re.sub(r'\s+xmlns[^"]*"[^"]*"', '', xml_text)
        root = ET.fromstring(x)
        for node in root.findall('.//item') + root.findall('.//entry'):
            parts = []
            for tag in ('title','description','summary','content'):
                el = node.find(tag)
                if el is not None and el.text: parts.append(clean(el.text))
            if parts: items.append(' '.join(parts)[:900])
    except Exception:
        for m in re.finditer(r'<(?:description|summary|content)[^>]*>(.*?)</(?:description|summary|content)>', xml_text, re.DOTALL):
            t = clean(m.group(1))
            if len(t) > 40: items.append(t[:900])
    return items


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# OPENAI LAYER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def gpt(system, user, max_tokens=3000, temp=0.3):
    body = json.dumps({'model':'gpt-4o','max_tokens':max_tokens,'temperature':temp,
        'messages':[{'role':'system','content':system},{'role':'user','content':user}]}).encode()
    last = None
    for attempt in range(GPT_RETRIES + 1):
        try:
            req = Request('https://api.openai.com/v1/chat/completions', data=body,
                headers={'Content-Type':'application/json','Authorization':f'Bearer {OPENAI_KEY}'}, method='POST')
            with urlopen(req, timeout=GPT_TIMEOUT) as r:
                return json.loads(r.read())['choices'][0]['message']['content']
        except HTTPError as e:
            raise Exception(f'OpenAI {e.code}: {e.reason}')
        except Exception as e:
            last = e
            if attempt < GPT_RETRIES:
                time.sleep(2 ** (attempt + 1))
    raise Exception(f'OpenAI failed after {GPT_RETRIES+1} attempts: {last}')

def jparse(text):
    if not text: return {}
    text = re.sub(r'```(?:json)?', '', text).strip()
    m = re.search(r'\{[\s\S]*\}', text)
    if not m: return {}
    try: return json.loads(m.group())
    except:
        fixed = re.sub(r',\s*([}\]])', r'\1', m.group())
        try: return json.loads(fixed)
        except: return {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DATA SOURCES — all return List[str], never raise
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def src_jsearch(q):
    if not JSEARCH_KEY: return []
    out, hdrs = [], {'X-RapidAPI-Key':JSEARCH_KEY,'X-RapidAPI-Host':'jsearch.p.rapidapi.com','Accept':'application/json'}
    for page in range(1, 4):
        raw = http_get(f'https://jsearch.p.rapidapi.com/search?query={quote_plus(q+" United States")}&page={page}&num_pages=1&date_posted=month', headers=hdrs, timeout=20)
        if not raw: continue
        try:
            for j in json.loads(raw).get('data',[]):
                hl = j.get('job_highlights') or {}
                blob = clean(' '.join(filter(None,[j.get('job_title',''),j.get('employer_name',''),j.get('job_description',''),' '.join(j.get('job_required_skills') or []),hl.get('Qualifications','') if isinstance(hl,dict) else '',hl.get('Responsibilities','') if isinstance(hl,dict) else ''])))
                if blob: out.append(blob[:1500])
        except: pass
        time.sleep(0.3)
    return out

def src_arbeitnow(q):
    raw = http_get(f'https://arbeitnow.com/api/job-board-api?search={quote_plus(q)}', headers={'Accept':'application/json'})
    if not raw: return []
    out = []
    try:
        for j in json.loads(raw).get('data',[])[:30]:
            blob = ' '.join(filter(None,[j.get('title',''),' '.join(j.get('tags',[])),clean(j.get('description',''))]))
            if blob: out.append(blob[:800])
    except: pass
    return out

def src_themuse(q):
    raw = http_get(f'https://www.themuse.com/api/public/jobs?category={quote_plus(q)}&page=1&descending=true', headers={'Accept':'application/json'})
    if not raw: return []
    out = []
    try:
        for j in json.loads(raw).get('results',[])[:25]:
            cats = ' '.join(c.get('name','') for c in j.get('categories',[]))
            blob = ' '.join(filter(None,[j.get('name',''),cats,' '.join(l.get('name','') for l in j.get('levels',[])),clean(j.get('contents',''))]))
            if blob: out.append(blob[:800])
    except: pass
    return out

def src_usajobs(q):
    raw = http_get(f'https://data.usajobs.gov/api/search?Keyword={quote_plus(q)}&ResultsPerPage=25&SortField=OpenDate&SortDirection=Desc',
        headers={'Accept':'application/json','Host':'data.usajobs.gov','User-Agent':'apex-resume@example.com'})
    if not raw: return []
    out = []
    try:
        for item in json.loads(raw).get('SearchResult',{}).get('SearchResultItems',[])[:25]:
            d  = item.get('MatchedObjectDescriptor',{})
            ua = d.get('UserArea',{}).get('Details',{})
            blob = ' '.join(filter(None,[d.get('PositionTitle',''),d.get('QualificationSummary',''),clean(ua.get('MajorDuties','')),clean(ua.get('Requirements',''))]))
            if blob: out.append(blob[:800])
    except: pass
    return out

def src_google(q):
    raw = http_get(f'https://news.google.com/rss/search?q={quote_plus(q+" job hiring")}&hl=en-US&gl=US&ceid=US:en')
    if not raw: return []
    signals = {'hiring','required','experience','responsibilities','qualifications','salary','position'}
    return [i for i in parse_rss(raw) if any(s in i.lower() for s in signals)]

def src_remoteok(q):
    tag = quote_plus(q.lower().replace(' ','-'))
    for url in [f'https://remoteok.com/api?tag={tag}','https://remoteok.com/api']:
        raw = http_get(url, headers={'Accept':'application/json'})
        if not raw: continue
        out, kws = [], q.lower().split()
        try:
            for j in json.loads(raw):
                if not isinstance(j,dict): continue
                title = (j.get('position','')+' '+' '.join(j.get('tags',[]))).lower()
                if any(w in title for w in kws):
                    out.append(f"{j.get('position','')} {' '.join(j.get('tags',[]))} {clean(j.get('description',''))}"[:800])
            if out: return out
        except: pass
    return []

# ── NEW FREE SOURCES (no API key required) ──────────────────────────────────
def src_remotive(q):
    """Remotive — completely free remote-jobs API, no key required."""
    raw = http_get(f'https://remotive.com/api/remote-jobs?search={quote_plus(q)}&limit=50', headers={'Accept':'application/json'})
    if not raw: return []
    out = []
    try:
        for j in json.loads(raw).get('jobs', [])[:40]:
            blob = ' '.join(filter(None, [
                j.get('title',''), j.get('company_name',''), j.get('category',''),
                ' '.join(j.get('tags',[])), clean(j.get('description',''))
            ]))
            if blob: out.append(blob[:1200])
    except Exception: pass
    return out

def src_jobicy(q):
    """Jobicy — free remote-jobs API."""
    raw = http_get(f'https://jobicy.com/api/v2/remote-jobs?count=50&tag={quote_plus(q)}', headers={'Accept':'application/json'})
    if not raw: return []
    out = []
    try:
        for j in json.loads(raw).get('jobs', [])[:40]:
            blob = ' '.join(filter(None, [
                j.get('jobTitle',''), j.get('companyName',''), j.get('jobIndustry',''),
                j.get('jobType',''), clean(j.get('jobDescription',''))
            ]))
            if blob: out.append(blob[:1200])
    except Exception: pass
    return out

def src_findwork(q):
    """Findwork.dev — open jobs API, no key required."""
    raw = http_get(f'https://findwork.dev/api/jobs/?search={quote_plus(q)}&sort_by=date', headers={'Accept':'application/json'})
    if not raw: return []
    out = []
    try:
        for j in json.loads(raw).get('results', [])[:30]:
            blob = ' '.join(filter(None, [
                j.get('role',''), j.get('company_name',''),
                ' '.join(j.get('keywords',[])), clean(j.get('text',''))
            ]))
            if blob: out.append(blob[:1200])
    except Exception: pass
    return out

def src_himalayas(q):
    """Himalayas remote jobs JSON feed."""
    raw = http_get(f'https://himalayas.app/jobs/api?search={quote_plus(q)}', headers={'Accept':'application/json'})
    if not raw: return []
    out = []
    try:
        data = json.loads(raw)
        for j in (data.get('jobs') or data.get('data') or [])[:30]:
            cats = j.get('categories',[])
            if not isinstance(cats, list): cats = []
            blob = ' '.join(filter(None, [
                j.get('title',''), j.get('companyName','') or j.get('company',''),
                ' '.join(cats), clean(j.get('description',''))
            ]))
            if blob: out.append(blob[:1200])
    except Exception: pass
    return out

def src_indeed_rss(q):
    """Indeed Jobs RSS — public, no key required."""
    raw = http_get(f'https://www.indeed.com/rss?q={quote_plus(q)}&l=&sort=date')
    return parse_rss(raw) if raw else []

def src_linkedin_rss(q):
    """LinkedIn-style listings via Google news RSS proxy."""
    raw = http_get(f'https://news.google.com/rss/search?q={quote_plus(q+" linkedin jobs apply now hiring")}&hl=en-US&gl=US&ceid=US:en')
    return parse_rss(raw) if raw else []

# ── CURATED TOP-HIRING COMPANY POOLS (for Greenhouse / Lever aggregators) ───
GREENHOUSE_TOP_COMPANIES = [
    'stripe','airbnb','shopify','discord','robinhood','plaid','asana','dropbox',
    'reddit','duolingo','figma','notion','postman','airtable','retool','vercel',
    'datadoghq','databricks','snowflake','elastic','mongodb','hashicorp','cloudflare',
    'github','gitlab','intercom','zendesk','calendly','linear','rippling','gusto',
    'brex','ramp','mercury','wise','revolut','square','affirm','klarna',
    'doordash','instacart','lyft','uber','wayfair','pinterest','medium','quora',
]
LEVER_TOP_COMPANIES = [
    'netflix','palantir','spotify','revolut','figma','attentive','box',
    'gem','clipboardhealth','automattic','grafana','jasper','jellyfish',
    'mercury','ramp','retool','rippling','superhuman','outschool','sourcegraph',
    'plaid','scaleai','navan','ironcladapp','justworks','snyk',
]

def src_greenhouse_aggregate(query):
    """Pull from public Greenhouse boards of top-hiring companies. No auth."""
    q = (query or '').lower().strip()
    qwords = [w for w in q.split() if len(w) > 2]
    out = []
    for co in GREENHOUSE_TOP_COMPANIES[:18]:
        try:
            raw = http_get(f'https://boards-api.greenhouse.io/v1/boards/{co}/jobs?content=true',
                           headers={'Accept':'application/json'}, timeout=8)
            if not raw: continue
            for j in (json.loads(raw).get('jobs',[]) or [])[:30]:
                title = (j.get('title','') or '').lower()
                if qwords and not any(w in title for w in qwords): continue
                loc = (j.get('location',{}) or {}).get('name','')
                out.append({'title': j.get('title',''),'company': co.capitalize(),
                    'location': loc or 'Remote',
                    'url': j.get('absolute_url',''),
                    'source': 'Greenhouse',
                    'posted': (j.get('updated_at','') or '')[:10],
                    'snippet': clean(j.get('content',''))[:240],'salary':''})
        except Exception: pass
    return out

def src_lever_aggregate(query):
    """Pull from public Lever boards of top-hiring companies."""
    q = (query or '').lower().strip()
    qwords = [w for w in q.split() if len(w) > 2]
    out = []
    for co in LEVER_TOP_COMPANIES[:14]:
        try:
            raw = http_get(f'https://api.lever.co/v0/postings/{co}?mode=json',
                           headers={'Accept':'application/json'}, timeout=8)
            if not raw: continue
            data = json.loads(raw)
            if not isinstance(data, list): continue
            for j in data[:30]:
                title = (j.get('text','') or '').lower()
                if qwords and not any(w in title for w in qwords): continue
                cats = j.get('categories',{}) or {}
                out.append({'title': j.get('text',''),'company': co.capitalize(),
                    'location': cats.get('location','') or 'Remote',
                    'url': j.get('hostedUrl',''),
                    'source': 'Lever',
                    'posted': '',
                    'snippet': clean(j.get('descriptionPlain',''))[:240],'salary':''})
        except Exception: pass
    return out

def src_hn_who_is_hiring(query):
    """Parse 'Who is hiring' threads on Hacker News for relevant postings."""
    try:
        sraw = http_get('https://hn.algolia.com/api/v1/search_by_date?query=Ask%20HN%20Who%20is%20hiring&tags=story&hitsPerPage=3',
                        headers={'Accept':'application/json'}, timeout=8)
        if not sraw: return []
        hits = (json.loads(sraw).get('hits',[]) or [])
        story_id = next((h.get('objectID') for h in hits if 'hiring' in (h.get('title','') or '').lower()), None)
        if not story_id: return []
        craw = http_get(f'https://hn.algolia.com/api/v1/items/{story_id}', headers={'Accept':'application/json'}, timeout=12)
        if not craw: return []
        thread = json.loads(craw)
        q = (query or '').lower()
        qwords = [w for w in q.split() if len(w) > 2]
        out = []
        for c in thread.get('children',[])[:200]:
            text = clean(c.get('text',''))[:1200]
            if not text or len(text) < 40: continue
            tl = text.lower()
            if qwords and not any(w in tl for w in qwords): continue
            first_line = text.split('|')[0].strip()[:90] if '|' in text else text[:90]
            out.append({'title': first_line,'company': '(via HN)',
                'location': ('Remote' if 'remote' in tl else 'See post'),
                'url': f'https://news.ycombinator.com/item?id={c.get("id","")}',
                'source': 'HN Hiring',
                'posted': '',
                'snippet': text[:240],'salary': ''})
            if len(out) >= 25: break
        return out
    except Exception: return []

def src_wellfound_rss(query):
    """Public AngelList/Wellfound listings via Google RSS proxy."""
    raw = http_get(f'https://news.google.com/rss/search?q={quote_plus(query+" site:wellfound.com OR site:angel.co")}&hl=en-US&gl=US&ceid=US:en')
    if not raw: return []
    out = []
    try:
        x = re.sub(r'\s+xmlns[^"]*"[^"]*"', '', raw)
        root = ET.fromstring(x)
        for node in root.findall('.//item')[:15]:
            t = (node.findtext('title') or '').strip()
            link = (node.findtext('link') or '').strip()
            desc = clean(node.findtext('description') or '')
            if not t: continue
            out.append({'title': t[:120],'company': 'Wellfound startup',
                'location': 'Remote / Hybrid','url': link,'source': 'Wellfound',
                'posted': '','snippet': desc[:240],'salary': ''})
    except Exception: pass
    return out

def src_jooble_rss(query, location=''):
    """Jooble jobs via Google RSS proxy."""
    q = query + (' ' + location if location else '')
    raw = http_get(f'https://news.google.com/rss/search?q={quote_plus(q+" site:jooble.org")}&hl=en-US&gl=US&ceid=US:en')
    if not raw: return []
    out = []
    try:
        x = re.sub(r'\s+xmlns[^"]*"[^"]*"', '', raw)
        root = ET.fromstring(x)
        for node in root.findall('.//item')[:15]:
            t = (node.findtext('title') or '').strip()
            link = (node.findtext('link') or '').strip()
            desc = clean(node.findtext('description') or '')
            if not t: continue
            out.append({'title': t[:120],'company': 'via Jooble','location': location or 'Various',
                'url': link,'source': 'Jooble','posted': '','snippet': desc[:240],'salary': ''})
    except Exception: pass
    return out


# ── LOCATION INTELLIGENCE ───────────────────────────────────────────────────
# Top US metros + state mapping for fuzzy location matching across sources.
US_CITY_STATE = {
    'new york':'NY','nyc':'NY','manhattan':'NY','brooklyn':'NY','queens':'NY','bronx':'NY',
    'los angeles':'CA','la':'CA','san francisco':'CA','sf':'CA','san jose':'CA','oakland':'CA',
    'san diego':'CA','sacramento':'CA','palo alto':'CA','mountain view':'CA','sunnyvale':'CA',
    'cupertino':'CA','san mateo':'CA','santa monica':'CA','long beach':'CA','fresno':'CA',
    'chicago':'IL','springfield':'IL',
    'houston':'TX','dallas':'TX','austin':'TX','san antonio':'TX','fort worth':'TX','el paso':'TX','plano':'TX',
    'phoenix':'AZ','tucson':'AZ','mesa':'AZ','scottsdale':'AZ',
    'philadelphia':'PA','pittsburgh':'PA','allentown':'PA',
    'columbus':'OH','cleveland':'OH','cincinnati':'OH','toledo':'OH',
    'atlanta':'GA','savannah':'GA','augusta':'GA',
    'miami':'FL','orlando':'FL','tampa':'FL','jacksonville':'FL','fort lauderdale':'FL','st petersburg':'FL',
    'boston':'MA','cambridge':'MA','worcester':'MA',
    'seattle':'WA','tacoma':'WA','spokane':'WA','bellevue':'WA','redmond':'WA',
    'denver':'CO','colorado springs':'CO','boulder':'CO','aurora':'CO',
    'washington':'DC','dc':'DC','washington dc':'DC',
    'las vegas':'NV','reno':'NV','henderson':'NV',
    'portland':'OR','eugene':'OR','salem':'OR',
    'detroit':'MI','ann arbor':'MI','grand rapids':'MI',
    'minneapolis':'MN','st paul':'MN','saint paul':'MN',
    'nashville':'TN','memphis':'TN','knoxville':'TN','chattanooga':'TN',
    'charlotte':'NC','raleigh':'NC','durham':'NC','greensboro':'NC',
    'indianapolis':'IN','fort wayne':'IN',
    'milwaukee':'WI','madison':'WI','green bay':'WI',
    'kansas city':'MO','st louis':'MO','saint louis':'MO','springfield':'MO',
    'salt lake city':'UT','provo':'UT',
    'oklahoma city':'OK','tulsa':'OK',
    'baltimore':'MD','annapolis':'MD','bethesda':'MD',
    'new orleans':'LA','baton rouge':'LA',
    'birmingham':'AL','huntsville':'AL','montgomery':'AL',
    'louisville':'KY','lexington':'KY',
    'omaha':'NE','lincoln':'NE',
    'wichita':'KS','topeka':'KS',
    'richmond':'VA','virginia beach':'VA','norfolk':'VA','arlington':'VA','alexandria':'VA',
    'newark':'NJ','jersey city':'NJ','trenton':'NJ',
    'hartford':'CT','new haven':'CT','stamford':'CT',
    'providence':'RI','warwick':'RI',
    'des moines':'IA','cedar rapids':'IA',
    'boise':'ID','meridian':'ID',
    'anchorage':'AK',
    'honolulu':'HI',
}
US_STATE_ABBR = {'al','ak','az','ar','ca','co','ct','de','fl','ga','hi','id','il','in','ia','ks','ky','la','me','md','ma','mi','mn','ms','mo','mt','ne','nv','nh','nj','nm','ny','nc','nd','oh','ok','or','pa','ri','sc','sd','tn','tx','ut','vt','va','wa','wv','wi','wy','dc'}
US_STATE_NAMES = {
    'alabama':'al','alaska':'ak','arizona':'az','arkansas':'ar','california':'ca','colorado':'co','connecticut':'ct',
    'delaware':'de','florida':'fl','georgia':'ga','hawaii':'hi','idaho':'id','illinois':'il','indiana':'in','iowa':'ia',
    'kansas':'ks','kentucky':'ky','louisiana':'la','maine':'me','maryland':'md','massachusetts':'ma','michigan':'mi',
    'minnesota':'mn','mississippi':'ms','missouri':'mo','montana':'mt','nebraska':'ne','nevada':'nv','new hampshire':'nh',
    'new jersey':'nj','new mexico':'nm','new york':'ny','north carolina':'nc','north dakota':'nd','ohio':'oh',
    'oklahoma':'ok','oregon':'or','pennsylvania':'pa','rhode island':'ri','south carolina':'sc','south dakota':'sd',
    'tennessee':'tn','texas':'tx','utah':'ut','vermont':'vt','virginia':'va','washington':'wa','west virginia':'wv',
    'wisconsin':'wi','wyoming':'wy',
}

def parse_location_from_query(q):
    """Heuristic: pull a US city/state out of the query string.
    Returns (cleaned_query, detected_location) where detected_location may be ''."""
    if not q: return q, ''
    ql = ' ' + q.lower().strip() + ' '
    # Try multi-word city names (longest first)
    for city in sorted(US_CITY_STATE.keys(), key=len, reverse=True):
        pad = ' ' + city + ' '
        if pad in ql:
            cleaned = ql.replace(pad, ' ').strip()
            return cleaned, city.title()
    # Try full state names
    for sname in sorted(US_STATE_NAMES.keys(), key=len, reverse=True):
        pad = ' ' + sname + ' '
        if pad in ql:
            cleaned = ql.replace(pad, ' ').strip()
            return cleaned, sname.title()
    # State abbreviation as trailing word
    words = q.strip().split()
    if len(words) >= 2 and words[-1].lower() in US_STATE_ABBR:
        return ' '.join(words[:-1]).strip(), words[-1].upper()
    # 'remote' as location signal
    if 'remote' in ql:
        return ql.replace('remote',' ').strip(), 'Remote'
    return q.strip(), ''

def location_aliases(loc):
    """Expand 'Houston' → {'houston','tx','texas','houston tx','houston, tx','houston, texas'} for fuzzy matching."""
    if not loc: return set()
    base = loc.lower().strip()
    aliases = {base}
    # If base is a known city, add CITY+STATE combos only — never bare state
    # (otherwise 'Houston' would match 'Dallas, TX' which is wrong).
    state = US_CITY_STATE.get(base)
    if state:
        state_l = state.lower()
        state_name = None
        for sname, abbr in US_STATE_NAMES.items():
            if abbr == state_l: state_name = sname; break
        aliases.add(base + ', ' + state_l)
        aliases.add(base + ' ' + state_l)
        if state_name:
            aliases.add(base + ', ' + state_name)
            aliases.add(base + ' ' + state_name)
    # If base IS a state abbreviation, add the full name
    if base in US_STATE_ABBR:
        for sname, abbr in US_STATE_NAMES.items():
            if abbr == base:
                aliases.add(sname)
                break
    # If base is a full state name, add abbreviation
    if base in US_STATE_NAMES:
        aliases.add(US_STATE_NAMES[base])
    # remote special case
    if base == 'remote':
        aliases.update({'anywhere', 'worldwide', 'work from home', 'wfh'})
    return aliases

def location_matches(job_location, aliases):
    """Return True if any alias appears in the job's location string.
    When user gave a specific city/state, we DROP pure-remote/worldwide jobs —
    they're not what the user asked for. They can search 'Remote' explicitly
    if that's what they want."""
    if not aliases: return True
    jl = (job_location or '').lower().strip()
    if not jl: return False
    # User explicitly wants Remote — match only remote jobs
    if 'remote' in aliases:
        return any(a in jl for a in aliases) or 'remote' in jl
    # User asked for a specific city/state. Reject jobs that are purely "remote/worldwide/anywhere"
    pure_remote_signals = ('remote', 'worldwide', 'anywhere', 'global', 'work from home', 'wfh', 'remote / hybrid')
    if jl in pure_remote_signals: return False
    # If location contains 'remote' but ALSO contains a real place, accept it (e.g., "Remote — Houston")
    return any(a in jl for a in aliases)


# ── JUNK FILTERS ────────────────────────────────────────────────────────────
_JUNK_TITLE_PATTERNS = [
    'careers - wellfound', 'careers wellfound',
    'explore current opportunities',
    'best tech companies', 'best startups',
    'founder, leadership & team', 'culture & employee benefits',
    'jobs at ', '3.523.000', '3,523,000', 'current vacancies',
    'jooble.org', 'wellfound —',
    'jobs in usa', 'jobs in united states',
    'top companies', 'top startups',
    '— wellfound', '- wellfound',
]
_JUNK_TITLE_PREFIX = ['page ', 'jobs at ', 'wellfound:', 'jooble —', 'jooble:']

def is_real_job_title(t):
    """Heuristic: filter out company directory pages, homepages, aggregator landing pages."""
    if not t: return False
    tl = t.lower().strip()
    if any(p in tl for p in _JUNK_TITLE_PATTERNS): return False
    if any(tl.startswith(p) for p in _JUNK_TITLE_PREFIX): return False
    # A real job title is usually 4+ chars and includes a noun
    if len(tl) < 5: return False
    return True


# ── LIGHTWEIGHT MATCH SCORING (per-job, no GPT call) ────────────────────────
# Used to score every Live Job card against the user's resume in ~5ms each.
STOPWORDS = set('''
a an and the of in on at to for with from by is are was were be been being have has had do does did
this that these those it its their our your you we i my me he she him her his them they
or as if not no nor but so also can will would could should may might must shall just only than
over under more most less least very much some any all each every both either neither one two three
about after before during between against without within along across through into onto off out
who what when where why how which whom whose another such same other own here there now then
job role title company location remote hybrid onsite candidate must required preferred plus
work works working worked help helps helped looking seeking apply applying applied want wants
make made makes making use using used good great strong excellent amazing best top high low
experience year years team teams member members manager managers lead leads led drove driving
new newer newest current currently future past
'''.split())

def _tokens(text):
    """Tokenize text → set of meaningful lowercase tokens."""
    if not text: return set()
    toks = set()
    for w in re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{2,}", text.lower()):
        if w in STOPWORDS: continue
        if len(w) < 3: continue
        # Strip trailing punctuation
        w = w.strip('.-')
        if w and w not in STOPWORDS: toks.add(w)
    return toks

def lightweight_match_score(resume_text, job_snippet, job_title):
    """Fast keyword-overlap match score 0-100 with shared keyword list. ~5ms/job."""
    if not resume_text: return None, []
    resume_t = _tokens(resume_text)
    title_t = _tokens(job_title or '')
    job_t = _tokens((job_snippet or '') + ' ' + (job_title or ''))
    if not job_t: return None, []
    overlap = resume_t & job_t
    title_overlap = resume_t & title_t
    # Base score: overlap ratio of job's tokens that appear in resume
    overlap_ratio = len(overlap) / max(len(job_t), 1)
    score = min(85, int(overlap_ratio * 220))
    # Title bonus: matching words in the role title are weighted higher
    if title_t:
        title_ratio = len(title_overlap) / len(title_t)
        score = min(100, score + int(title_ratio * 35))
    # Top shared keywords (most descriptive — longest first)
    shared_sorted = sorted(overlap, key=lambda w: (-len(w), w))[:6]
    return max(0, score), shared_sorted

def score_jobs_against_resume(jobs, resume_text):
    """Annotate every job dict with match_score (0-100) + shared_keywords (list)."""
    if not resume_text or not jobs: return jobs
    for j in jobs:
        score, shared = lightweight_match_score(
            resume_text, j.get('snippet','') or '', j.get('title','') or ''
        )
        if score is not None:
            j['match_score'] = score
            j['shared_keywords'] = shared
    return jobs


def relevance_score(job, query_words, location, aliases):
    """Rank jobs: title match × location precision × source authority."""
    title = (job.get('title','') or '').lower()
    jloc = (job.get('location','') or '').lower()
    src = job.get('source','')
    score = 0
    # Title relevance
    if query_words:
        matches = sum(1 for w in query_words if w in title)
        score += matches * 18
    # Location precision
    if location:
        if location.lower() in jloc:
            score += 70
        elif any(a in jloc for a in aliases):
            score += 35
        elif jloc in ('remote', 'worldwide', 'anywhere'):
            score += 5   # remote is allowed but ranks last
        else:
            score += 0
    else:
        score += 20
    # Source authority — local APIs rank above aggregator RSS proxies
    src_priority = {
        'JSearch': 30, 'Indeed': 28, 'USAJobs': 26, 'TheMuse': 22,
        'Greenhouse': 22, 'Lever': 22, 'Jobicy': 16, 'Remotive': 14,
        'RemoteOK': 14, 'Arbeitnow': 12, 'Findwork': 10,
        'HN Hiring': 8, 'Wellfound': 3, 'Jooble': 10,
    }
    score += src_priority.get(src, 5)
    # Bonus if job has a real apply URL (not a Google News redirect)
    url = job.get('url','') or ''
    if 'news.google.com' in url: score -= 15
    return score


# ── LOCATION-AWARE SOURCES (only fire when a location is given) ─────────────

def src_jsearch_local(query, location):
    """JSearch — by far the best for US local jobs across all industries."""
    if not JSEARCH_KEY: return []
    hdrs = {'X-RapidAPI-Key': JSEARCH_KEY, 'X-RapidAPI-Host': 'jsearch.p.rapidapi.com', 'Accept': 'application/json'}
    q = (query + ' in ' + location).strip() if location else query
    out = []
    for page in range(1, 3):
        raw = http_get(f'https://jsearch.p.rapidapi.com/search?query={quote_plus(q)}&page={page}&num_pages=1&date_posted=month',
                       headers=hdrs, timeout=18)
        if not raw: continue
        try:
            for j in json.loads(raw).get('data', [])[:25]:
                city = j.get('job_city','') or ''
                state = j.get('job_state','') or ''
                loc = ', '.join(p for p in [city, state] if p) or j.get('job_country','')
                sal_min = j.get('job_min_salary',''); sal_max = j.get('job_max_salary','')
                sal = ''
                if sal_min and sal_max:
                    try: sal = f"${int(sal_min):,}-${int(sal_max):,}"
                    except Exception: sal = f"${sal_min}-${sal_max}"
                out.append({
                    'title': j.get('job_title',''),
                    'company': j.get('employer_name',''),
                    'location': loc or 'Various',
                    'url': j.get('job_apply_link','') or j.get('job_google_link',''),
                    'source': 'JSearch',
                    'posted': (j.get('job_posted_at_datetime_utc','') or '')[:10],
                    'snippet': clean(j.get('job_description',''))[:240],
                    'salary': sal,
                })
        except Exception: pass
    return out

def src_indeed_local(query, location):
    """Indeed RSS with explicit location."""
    if not location: return []
    raw = http_get(f'https://www.indeed.com/rss?q={quote_plus(query)}&l={quote_plus(location)}&sort=date')
    if not raw: return []
    out = []
    try:
        x = re.sub(r'\s+xmlns[^"]*"[^"]*"', '', raw)
        root = ET.fromstring(x)
        for node in root.findall('.//item')[:25]:
            t = (node.findtext('title') or '').strip()
            link = (node.findtext('link') or '').strip()
            desc = clean(node.findtext('description') or '')
            pub = (node.findtext('pubDate') or '')[:16]
            # Indeed title format: "Title - Company - Location"
            parts = [p.strip() for p in t.rsplit(' - ', 2)]
            title = parts[0] if parts else t
            company = parts[1] if len(parts) > 1 else ''
            loc = parts[2] if len(parts) > 2 else location
            out.append({'title': title[:130], 'company': company, 'location': loc,
                'url': link, 'source': 'Indeed', 'posted': pub, 'snippet': desc[:240], 'salary': ''})
    except Exception: pass
    return out

def src_themuse_local(query, location):
    """The Muse public API with location filter."""
    params = f'category={quote_plus(query)}&page=1&descending=true'
    if location:
        params += f'&location={quote_plus(location)}'
    raw = http_get(f'https://www.themuse.com/api/public/jobs?{params}', headers={'Accept':'application/json'})
    if not raw: return []
    out = []
    try:
        for j in json.loads(raw).get('results', [])[:25]:
            locs = j.get('locations', []) or []
            loc_name = (locs[0].get('name','') if locs else '') or 'Remote'
            out.append({'title': j.get('name',''),
                'company': (j.get('company',{}) or {}).get('name',''),
                'location': loc_name,
                'url': (j.get('refs',{}) or {}).get('landing_page',''),
                'source': 'TheMuse',
                'posted': (j.get('publication_date','') or '')[:10],
                'snippet': clean(j.get('contents',''))[:240], 'salary': ''})
    except Exception: pass
    return out

def src_usajobs_local(query, location):
    """USAJobs with proper LocationName filter."""
    params = f'Keyword={quote_plus(query)}&ResultsPerPage=25&SortField=OpenDate&SortDirection=Desc'
    if location:
        params += f'&LocationName={quote_plus(location)}'
    raw = http_get(f'https://data.usajobs.gov/api/search?{params}',
        headers={'Accept':'application/json','Host':'data.usajobs.gov','User-Agent':'apex-resume@example.com'})
    if not raw: return []
    out = []
    try:
        for item in json.loads(raw).get('SearchResult',{}).get('SearchResultItems',[])[:25]:
            d = item.get('MatchedObjectDescriptor',{}) or {}
            pl = (d.get('PositionLocation') or [{}])
            rng = d.get('PositionRemuneration', [{}])
            rng = rng[0] if rng else {}
            rmin = rng.get('MinimumRange','')
            out.append({'title': d.get('PositionTitle',''),
                'company': (d.get('OrganizationName','') or 'US Government'),
                'location': pl[0].get('LocationName','') if pl else (location or 'USA'),
                'url': d.get('PositionURI',''),'source':'USAJobs',
                'posted': (d.get('PublicationStartDate','') or '')[:10],
                'snippet': clean(d.get('QualificationSummary',''))[:240],
                'salary': (f"${rmin}-${rng.get('MaximumRange','')}") if rmin else ''})
    except Exception: pass
    return out


# ── STRUCTURED JOB FETCHER (returns dicts for the live Jobs Feed UI) ────────
def fetch_structured_jobs(query, limit=50, location=''):
    """Fetch real job postings as structured dicts. Used by /live-jobs and alerts.
    Auto-extracts location from query if location is empty. Uses alias-based fuzzy
    matching so 'Houston' matches 'Houston, TX', 'TX', 'Texas', etc."""
    # Smart query parsing: if no location given, try to extract one from the query
    if not location:
        cleaned_query, detected = parse_location_from_query(query)
        if detected:
            query = cleaned_query or query
            location = detected
    aliases = location_aliases(location)
    jobs = []
    seen = set()
    def _add(j):
        key = (j.get('title','').lower().strip(), j.get('company','').lower().strip())
        if key in seen or not key[0]: return
        # Junk filter: drop company directory pages, homepages, aggregator landings
        if not is_real_job_title(j.get('title','')): return
        # Smart location filter: use alias set to match city/state/state-abbr
        if aliases and not location_matches(j.get('location',''), aliases):
            return
        seen.add(key); jobs.append(j)

    # Remotive
    try:
        raw = http_get(f'https://remotive.com/api/remote-jobs?search={quote_plus(query)}&limit=30', headers={'Accept':'application/json'})
        if raw:
            for j in json.loads(raw).get('jobs', [])[:25]:
                _add({'title': j.get('title',''),'company': j.get('company_name',''),
                    'location': j.get('candidate_required_location','Remote'),
                    'url': j.get('url',''),'source': 'Remotive',
                    'posted': (j.get('publication_date','') or '')[:10],
                    'snippet': clean(j.get('description',''))[:240],
                    'salary': j.get('salary','') or ''})
    except Exception: pass

    # Arbeitnow
    try:
        raw = http_get(f'https://arbeitnow.com/api/job-board-api?search={quote_plus(query)}', headers={'Accept':'application/json'})
        if raw:
            for j in json.loads(raw).get('data', [])[:20]:
                _add({'title': j.get('title',''),'company': j.get('company_name',''),
                    'location': j.get('location','') or 'Remote','url': j.get('url',''),
                    'source': 'Arbeitnow','posted': (j.get('created_at','') or '')[:10],
                    'snippet': clean(j.get('description',''))[:240],'salary': ''})
    except Exception: pass

    # Jobicy
    try:
        raw = http_get(f'https://jobicy.com/api/v2/remote-jobs?count=30&tag={quote_plus(query)}', headers={'Accept':'application/json'})
        if raw:
            for j in json.loads(raw).get('jobs', [])[:20]:
                sal_min = j.get('annualSalaryMin','')
                _add({'title': j.get('jobTitle',''),'company': j.get('companyName',''),
                    'location': j.get('jobGeo','') or 'Remote','url': j.get('url',''),
                    'source': 'Jobicy','posted': (j.get('pubDate','') or '')[:10],
                    'snippet': clean(j.get('jobDescription',''))[:240],
                    'salary': (f"${sal_min} - ${j.get('annualSalaryMax','')}") if sal_min else ''})
    except Exception: pass

    # RemoteOK
    try:
        tag = quote_plus(query.lower().replace(' ','-'))
        raw = http_get(f'https://remoteok.com/api?tag={tag}', headers={'Accept':'application/json'})
        if raw:
            for j in json.loads(raw)[:20]:
                if not isinstance(j, dict) or not j.get('position'): continue
                sal_min = j.get('salary_min','')
                _add({'title': j.get('position',''),'company': j.get('company',''),
                    'location': j.get('location','') or 'Remote',
                    'url': j.get('url','') or f"https://remoteok.com/remote-jobs/{j.get('id','')}",
                    'source': 'RemoteOK','posted': (j.get('date','') or '')[:10],
                    'snippet': clean(j.get('description',''))[:240],
                    'salary': (f"${sal_min}-${j.get('salary_max','')}") if sal_min else ''})
    except Exception: pass

    # The Muse
    try:
        raw = http_get(f'https://www.themuse.com/api/public/jobs?category={quote_plus(query)}&page=1&descending=true', headers={'Accept':'application/json'})
        if raw:
            for j in json.loads(raw).get('results', [])[:20]:
                locs = j.get('locations', []) or []
                _add({'title': j.get('name',''),
                    'company': (j.get('company',{}) or {}).get('name',''),
                    'location': (locs[0].get('name','') if locs else 'Remote'),
                    'url': (j.get('refs',{}) or {}).get('landing_page',''),
                    'source': 'TheMuse','posted': (j.get('publication_date','') or '')[:10],
                    'snippet': clean(j.get('contents',''))[:240],'salary': ''})
    except Exception: pass

    # USAJobs
    try:
        raw = http_get(
            f'https://data.usajobs.gov/api/search?Keyword={quote_plus(query)}&ResultsPerPage=20&SortField=OpenDate&SortDirection=Desc',
            headers={'Accept':'application/json','Host':'data.usajobs.gov','User-Agent':'apex-resume@example.com'})
        if raw:
            for item in json.loads(raw).get('SearchResult',{}).get('SearchResultItems',[])[:20]:
                d  = item.get('MatchedObjectDescriptor',{}) or {}
                pl = (d.get('PositionLocation') or [{}])
                rng = d.get('PositionRemuneration', [{}])
                rng = rng[0] if rng else {}
                rmin = rng.get('MinimumRange','')
                _add({'title': d.get('PositionTitle',''),
                    'company': (d.get('OrganizationName','') or 'US Government'),
                    'location': pl[0].get('LocationName','') if pl else 'USA',
                    'url': d.get('PositionURI',''),'source': 'USAJobs',
                    'posted': (d.get('PublicationStartDate','') or '')[:10],
                    'snippet': clean(d.get('QualificationSummary',''))[:240],
                    'salary': (f"${rmin}-${rng.get('MaximumRange','')}") if rmin else ''})
    except Exception: pass

    # NEW sources — run in parallel for speed
    extra_lock = threading.Lock()
    def _pull(fn):
        try:
            items = fn(query)
            with extra_lock:
                for j in items: _add(j)
        except Exception: pass
    def _pull_with_loc(fn, q, loc):
        try:
            items = fn(q, loc)
            with extra_lock:
                for j in items: _add(j)
        except Exception: pass

    threads = [
        # Location-aware first (priority for local queries)
        threading.Thread(target=_pull_with_loc, args=(src_jsearch_local, query, location), daemon=True),
        threading.Thread(target=_pull_with_loc, args=(src_indeed_local, query, location), daemon=True),
        threading.Thread(target=_pull_with_loc, args=(src_themuse_local, query, location), daemon=True),
        threading.Thread(target=_pull_with_loc, args=(src_usajobs_local, query, location), daemon=True),
        # Aggregators (no native location filter but post-filtered)
        threading.Thread(target=_pull, args=(src_greenhouse_aggregate,), daemon=True),
        threading.Thread(target=_pull, args=(src_lever_aggregate,), daemon=True),
        threading.Thread(target=_pull, args=(src_hn_who_is_hiring,), daemon=True),
        # Wellfound RSS removed — Google News proxy returns directory pages, not jobs
        threading.Thread(target=_pull_with_loc, args=(src_jooble_rss, query, location), daemon=True),
    ]
    for t in threads: t.start()
    for t in threads: t.join(timeout=18)

    # Sort by relevance: local matches first, authoritative sources first, junk last
    query_words = [w for w in (query or '').lower().split() if len(w) > 2]
    for j in jobs:
        j['_score'] = relevance_score(j, query_words, location, aliases)
    jobs.sort(key=lambda j: j.get('_score', 0), reverse=True)
    # Strip internal score before returning
    for j in jobs:
        j.pop('_score', None)
    return {'jobs': jobs[:limit], 'parsed_location': location, 'parsed_query': query}


# ── 28 sectors mapped to the best sources for each industry ──────────────────
# Tech-adjacent boards (remoteok) only for tech roles.
# USAJobs prioritised for government/public sector.
# JSearch always first — it aggregates 20+ boards via Google for Jobs.
SECTOR_SOURCES = {
    # All sectors now use the expanded free-source pool — Remotive/Jobicy/Findwork/Himalayas/Indeed RSS/LinkedIn RSS
    'tech':              [src_jsearch, src_remotive, src_arbeitnow, src_remoteok, src_jobicy, src_findwork, src_himalayas, src_themuse, src_indeed_rss, src_linkedin_rss, src_google],
    'ai_data':           [src_jsearch, src_remotive, src_arbeitnow, src_remoteok, src_jobicy, src_findwork, src_himalayas, src_themuse, src_indeed_rss, src_linkedin_rss, src_google],
    'cybersecurity':     [src_jsearch, src_remotive, src_arbeitnow, src_remoteok, src_jobicy, src_findwork, src_themuse, src_indeed_rss, src_linkedin_rss, src_google],
    'cloud_devops':      [src_jsearch, src_remotive, src_arbeitnow, src_remoteok, src_jobicy, src_findwork, src_himalayas, src_themuse, src_indeed_rss, src_linkedin_rss, src_google],
    'real_estate':       [src_jsearch, src_remotive, src_arbeitnow, src_themuse, src_usajobs, src_indeed_rss, src_linkedin_rss, src_google],
    'construction':      [src_jsearch, src_remotive, src_arbeitnow, src_usajobs, src_indeed_rss, src_linkedin_rss, src_google],
    'architecture':      [src_jsearch, src_remotive, src_themuse, src_arbeitnow, src_indeed_rss, src_linkedin_rss, src_google],
    'healthcare':        [src_jsearch, src_remotive, src_usajobs, src_arbeitnow, src_themuse, src_indeed_rss, src_linkedin_rss, src_google],
    'biotech_pharma':    [src_jsearch, src_remotive, src_usajobs, src_arbeitnow, src_themuse, src_indeed_rss, src_linkedin_rss, src_google],
    'mental_health':     [src_jsearch, src_remotive, src_usajobs, src_arbeitnow, src_themuse, src_indeed_rss, src_linkedin_rss, src_google],
    'finance':           [src_jsearch, src_remotive, src_arbeitnow, src_jobicy, src_themuse, src_indeed_rss, src_linkedin_rss, src_google],
    'accounting':        [src_jsearch, src_remotive, src_arbeitnow, src_jobicy, src_themuse, src_indeed_rss, src_linkedin_rss, src_google],
    'insurance':         [src_jsearch, src_remotive, src_arbeitnow, src_themuse, src_indeed_rss, src_linkedin_rss, src_google],
    'consulting':        [src_jsearch, src_remotive, src_themuse, src_arbeitnow, src_jobicy, src_indeed_rss, src_linkedin_rss, src_google],
    'government':        [src_usajobs, src_jsearch, src_remotive, src_arbeitnow, src_indeed_rss, src_linkedin_rss, src_google],
    'nonprofit':         [src_jsearch, src_remotive, src_usajobs, src_themuse, src_arbeitnow, src_indeed_rss, src_linkedin_rss, src_google],
    'military_defense':  [src_usajobs, src_jsearch, src_remotive, src_indeed_rss, src_linkedin_rss, src_google],
    'creative_design':   [src_jsearch, src_remotive, src_themuse, src_arbeitnow, src_remoteok, src_jobicy, src_indeed_rss, src_linkedin_rss, src_google],
    'marketing':         [src_jsearch, src_remotive, src_themuse, src_arbeitnow, src_remoteok, src_jobicy, src_findwork, src_indeed_rss, src_linkedin_rss, src_google],
    'media_journalism':  [src_jsearch, src_remotive, src_themuse, src_arbeitnow, src_jobicy, src_indeed_rss, src_linkedin_rss, src_google],
    'advertising_pr':    [src_jsearch, src_remotive, src_themuse, src_arbeitnow, src_jobicy, src_indeed_rss, src_linkedin_rss, src_google],
    'operations':        [src_jsearch, src_remotive, src_arbeitnow, src_themuse, src_jobicy, src_indeed_rss, src_linkedin_rss, src_google],
    'logistics':         [src_jsearch, src_remotive, src_arbeitnow, src_usajobs, src_indeed_rss, src_linkedin_rss, src_google],
    'manufacturing':     [src_jsearch, src_remotive, src_arbeitnow, src_usajobs, src_indeed_rss, src_linkedin_rss, src_google],
    'automotive':        [src_jsearch, src_remotive, src_arbeitnow, src_usajobs, src_indeed_rss, src_linkedin_rss, src_google],
    'human_resources':   [src_jsearch, src_remotive, src_themuse, src_arbeitnow, src_jobicy, src_indeed_rss, src_linkedin_rss, src_google],
    'sales':             [src_jsearch, src_remotive, src_arbeitnow, src_themuse, src_jobicy, src_indeed_rss, src_linkedin_rss, src_google],
    'education':         [src_jsearch, src_remotive, src_usajobs, src_arbeitnow, src_themuse, src_indeed_rss, src_linkedin_rss, src_google],
    'energy':            [src_jsearch, src_remotive, src_arbeitnow, src_usajobs, src_indeed_rss, src_linkedin_rss, src_google],
    'hospitality':       [src_jsearch, src_remotive, src_arbeitnow, src_jobicy, src_indeed_rss, src_linkedin_rss, src_google],
    'retail_service':    [src_jsearch, src_remotive, src_arbeitnow, src_themuse, src_indeed_rss, src_linkedin_rss, src_google],
    'sports_fitness':    [src_jsearch, src_remotive, src_themuse, src_arbeitnow, src_jobicy, src_indeed_rss, src_linkedin_rss, src_google],
    'general':           [src_jsearch, src_remotive, src_arbeitnow, src_jobicy, src_themuse, src_findwork, src_indeed_rss, src_linkedin_rss, src_google],
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RELEVANCE SCORING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def score_listing(text, target_words, sector_signals, anti_kw):
    if not text or len(text) < 20: return 0
    t     = text.lower()
    score = 25
    score += min(sum(1 for w in target_words if w in t) * 18, 45)
    score += min(sum(1 for s in sector_signals if s in t) * 5, 20)
    score += 10 if len(text) > 300 else 0
    score -= sum(1 for a in anti_kw if a in t) * 25
    return max(0, min(100, score))

def filter_listings(raw, target_words, sector_signals, anti_kw, emit):
    if not raw: return []
    scored = sorted([(t, score_listing(t, target_words, sector_signals, anti_kw)) for t in raw if t and len(t)>20], key=lambda x: x[1], reverse=True)
    kept = [t for t,s in scored if s >= 35]
    if len(kept) < MIN_LISTINGS:
        kept = [t for t,s in scored if s >= 20]
        emit({'type':'log','msg':'  ↳ Filter relaxed to threshold 20'})
    if len(kept) < MIN_LISTINGS and scored:
        kept = [t for t,_ in scored[:10]]
        emit({'type':'log','msg':'  ↳ Taking top 10 regardless of score'})
    avg = sum(s for _,s in scored[:len(kept)]) / max(len(kept),1)
    emit({'type':'log','msg':f'  ✓ Kept {len(kept)}/{len(raw)} listings · avg relevance {avg:.0f}/100'})
    return kept


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SELF-IMPROVEMENT LOOP
# The innovation no competitor has.
# Runs 3 iterations — each grades its own output
# and rewrites targeting specific weaknesses.
# Only keeps iteration if score improved.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# APEX v10 CORE — TRUTH-PRESERVING OPTIMIZATION
#
# Replaces the v9 self-improvement loop. Three guarantees the old
# loop could not make:
#
#   1. NOTHING IS FABRICATED. Every skill, tool, credential, or
#      experience in the output must have evidence in the original.
#      A fidelity audit rejects any iteration that adds a claim the
#      candidate cannot support.
#
#   2. NOTHING PROTECTED IS LOST. Licenses, certifications, work
#      authorization, languages, education, clearances — extracted
#      from the original, verified present in every candidate, and
#      restored verbatim if the rewriter drops them.
#
#   3. THE SCORE IS A MEASUREMENT. ATS score is computed
#      deterministically from keyword coverage, section completeness,
#      verb strength, and quantification. Same input → same score.
#      No example numbers in prompts for the model to anchor on, no
#      max() over two guesses, no truncation hiding half the resume.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ─── Protected content ────────────────────────────────────────────────────────
# Section headers whose bodies pass through the rewriter untouched.
# Optional qualifier words that commonly prefix a protected header
# ("SECURITY CLEARANCE", "PROFESSIONAL LICENSES", "TECHNICAL CERTIFICATIONS").
_HDR_PREFIX = r'(?:(?:security|professional|technical|clinical|state|active|relevant|key|additional)\s+)*'
_PROTECTED_WORDS = (
    r'licen[cs]es?(?:\s*(?:&|and|/)\s*certifications?)?|'
    r'certifications?(?:\s*(?:&|and|/)\s*licen[cs]es?)?|'
    r'credentials?|registrations?|languages?|'
    r'(?:work\s+)?authori[sz]ation|clearances?|security\s+clearance|'
    r'education(?:\s*(?:&|and)\s*training)?|training|'
    r'publications?|patents?|awards?(?:\s*(?:&|and)\s*honou?rs)?|honou?rs|'
    r'memberships?|affiliations?|professional\s+(?:memberships?|affiliations?|development)|'
    r'volunteer(?:\s+experience)?|military(?:\s+service)?'
)
PROTECTED_HEADERS = re.compile(r'^\s*' + _HDR_PREFIX + r'(?:' + _PROTECTED_WORDS + r')\s*:?\s*$', re.I)

# Individual lines anywhere in the resume that must survive regardless of section.
PROTECTED_LINE = re.compile(
    r'(licen[cs]ed?\b|\bcertif|\bBLS\b|\bCPR\b|\bACLS\b|\bPALS\b|\bRN\b|\bPT\b,|\bDPT\b|'
    r'citizen|work\s+authori|sponsorship|green\s+card|\bvisa\b|clearance|'
    r'\bPMP\b|\bCPA\b|\bCFA\b|\bAWS\s+certified|\bCISSP\b|\bCCNA\b|\bPE\b\s|'
    r'^\s*languages?\s*:)',
    re.I)

# Headers are usually ALL CAPS, but plenty of real resumes use Title Case or
# lowercase. Accept either an all-caps line or a short line whose text matches a
# known section name — case-insensitively.
_SECTION_WORDS = re.compile(
    r'^\s*' + _HDR_PREFIX + r'(?:' + _PROTECTED_WORDS + r'|'
    r'summary|profile|objective|about(?:\s+me)?|'
    r'experience|work\s+experience|professional\s+experience|employment(?:\s+history)?|'
    r'career(?:\s+history)?|work\s+history|'
    r'skills|technical\s+skills|clinical\s+skills|core\s+competencies|competencies|expertise|'
    r'projects?|portfolio|'
    r'contact(?:\s+information)?|references?'
    r')\s*:?\s*$', re.I)
_ALLCAPS_HEADER = re.compile(r'^\s*[A-Z][A-Z0-9 &/\-\.]{2,40}\s*:?\s*$')

def SECTION_HEADER_match(line):
    s = (line or '').strip()
    if not s or len(s.split()) > 6:
        return False
    if s.endswith(('.', ',', ';')):
        return False
    return bool(_ALLCAPS_HEADER.match(s) or _SECTION_WORDS.match(s))

class _SectionHeaderShim:
    """Kept as an object so existing `SECTION_HEADER.match(...)` calls still work."""
    @staticmethod
    def match(line):
        return SECTION_HEADER_match(line)

SECTION_HEADER = _SectionHeaderShim()

STRONG_VERBS = {
    'led','built','drove','scaled','delivered','launched','reduced','increased','engineered',
    'architected','negotiated','spearheaded','designed','developed','implemented','managed',
    'directed','optimized','improved','created','established','executed','generated','achieved',
    'accelerated','streamlined','transformed','mentored','trained','coached','guided','evaluated',
    'diagnosed','treated','assessed','administered','coordinated','facilitated','instructed',
    'documented','analyzed','resolved','automated','deployed','migrated','secured','audited',
    'authored','published','presented','crafted','pioneered','revitalized','maximized','minimized',
    'cut','saved','grew','won','closed','expanded','restructured','overhauled','prepared',
    'monitored','tracked','maintained','supported','partnered','collaborated','owned',
    # Data / engineering
    'queried','benchmarked','consolidated','curated','debugged','deduplicated','instrumented',
    'integrated','interpreted','investigated','modeled','normalized','orchestrated','piloted',
    'profiled','provisioned','quantified','reconciled','refactored','remediated','scoped',
    'standardized','synthesized','validated','visualized','forecasted','forecast','shipped',
    # Clinical / healthcare
    'triaged','screened','charted','rehabilitated','counseled','educated','referred','stabilized',
    'immunized','dispensed','calibrated','sterilized','ambulated',
    # Skilled trades / operations
    'installed','repaired','fabricated','welded','operated','inspected','tested','commissioned',
    'serviced','overhauled','rigged','surveyed',
    # People / business
    'taught','supervised','recruited','hired','onboarded','promoted','drafted','reviewed',
    'approved','certified','scheduled','billed','forecasted','briefed','advised','championed',
    # Irregular past tenses the stemmer cannot derive
    'wrote','oversaw','rebuilt','sold','spoke','taught','led','built','drove','grew','won',
    'ran','began','chose','held','kept','met','set','sought','undertook','withdrew'
}

WEAK_OPENERS = {
    'responsible','worked','helped','assisted','was','were','participated','involved',
    'duties','tasked','handled','did','made','used','utilized'
}

_NUM = re.compile(r'(\d+[\d,]*(\.\d+)?\s*(%|percent|k|m|x|\+)?|\$\s?\d|\d+\s*(patients|clients|students|users|people|team|projects|hours|years|months|weeks|days))', re.I)


def _norm(s):
    if not isinstance(s, str):
        s = '' if s is None else str(s)
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


def _stem(w):
    if not isinstance(w, str):
        return ''
    w = w.lower()
    # Longest suffix first so "ation" wins over "ion" and "s".
    for suf in ('ational', 'ization', 'isation', 'ation', 'ition', 'ement',
                'ment', 'ance', 'ence', 'ings', 'ing', 'ied', 'ies', 'ion',
                'ive', 'ers', 'er', 'ed', 'es', 'al', 's'):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            base = w[:-len(suf)]
            if suf in ('ied', 'ies'):
                base += 'y'
            return base.rstrip('e') or w
    return w.rstrip('e') or w


def _stems(text):
    return {_stem(t) for t in _norm(text).split() if len(t) > 2}

_STRONG_STEMS = None
def _is_strong(word):
    global _STRONG_STEMS
    if _STRONG_STEMS is None:
        _STRONG_STEMS = {_stem(v) for v in STRONG_VERBS} | {_stem(v) + 'e' for v in STRONG_VERBS}
    st = _stem(word)
    return st in _STRONG_STEMS or (st + 'e') in _STRONG_STEMS or st.rstrip('e') in _STRONG_STEMS


def _lines(text):
    return [l.rstrip() for l in (text or '').splitlines()]


def split_sections(text):
    """Return ordered list of (header, [body lines]). Header '' = preamble."""
    out = [('', [])]
    for ln in _lines(text):
        s = ln.strip()
        if s and SECTION_HEADER.match(s) and len(s.split()) <= 6:
            out.append((s.rstrip(':').strip(), []))
        else:
            out[-1][1].append(ln)
    return out


def extract_protected(original):
    """
    Everything that must survive optimization verbatim.
    Returns {'sections': {header: body_text}, 'lines': [line, ...]}
    """
    sections, lines = {}, []
    for header, body in split_sections(original):
        if header and PROTECTED_HEADERS.match(header):
            txt = '\n'.join(l for l in body if l.strip()).strip()
            if txt:
                sections[header] = txt
    for ln in _lines(original):
        s = ln.strip()
        if s and PROTECTED_LINE.search(s) and len(s) < 160:
            lines.append(s)
    return {'sections': sections, 'lines': list(dict.fromkeys(lines))}


_STEM_CACHE = {}
def _present(needle, haystack_norm):
    """Is `needle` evidenced in `haystack_norm` (an already-normalised string)?
    Exact substring first, then stemmed-token overlap so 'patient education'
    matches 'educated patients and families'."""
    n = _norm(needle)
    if not n:
        return True
    if n in haystack_norm:
        return True
    key = id(haystack_norm), len(haystack_norm)
    hs = _STEM_CACHE.get(key)
    if hs is None:
        hs = {_stem(t) for t in haystack_norm.split() if len(t) > 2}
        if len(_STEM_CACHE) > 64:
            _STEM_CACHE.clear()
        _STEM_CACHE[key] = hs
    toks = [t for t in n.split() if len(t) > 3]
    if not toks:
        return n in haystack_norm

    def _tok_hit(t):
        if t in haystack_norm:
            return True
        st = _stem(t)
        if st in hs:
            return True
        # Stemming is lossy and asymmetric ("education"→educ, "educated"→educat),
        # so accept a common prefix of >=4 chars in either direction.
        if len(st) >= 4:
            return any(h.startswith(st) or st.startswith(h) for h in hs if len(h) >= 4)
        return False

    hit = sum(1 for t in toks if _tok_hit(t))
    return hit / len(toks) >= 0.75


def check_protected(candidate, protected):
    """Return {'dropped_sections': [...], 'dropped_lines': [...]}"""
    hay = _norm(candidate)
    ds = [h for h, body in protected['sections'].items()
          if not all(_present(l, hay) for l in body.splitlines() if l.strip())]
    dl = [l for l in protected['lines'] if not _present(l, hay)]
    return {'dropped_sections': ds, 'dropped_lines': dl}


def restore_protected(candidate, protected, dropped):
    """Re-insert dropped protected sections verbatim, before EDUCATION or at end."""
    if not dropped['dropped_sections'] and not dropped['dropped_lines']:
        return candidate
    text = candidate.rstrip()
    blocks = []
    for h in dropped['dropped_sections']:
        blocks.append(f"\n\n{h.upper()}\n{protected['sections'][h]}")
    # Lines not inside a restored section go into a catch-all block
    restored_bodies = ' '.join(protected['sections'][h] for h in dropped['dropped_sections'])
    loose = [l for l in dropped['dropped_lines'] if not _present(l, _norm(restored_bodies))]
    if loose:
        blocks.append("\n\nLICENSES & CREDENTIALS\n" + '\n'.join(loose))
    insert = ''.join(blocks)
    m = re.search(r'\n\s*EDUCATION\s*:?\s*\n', text, re.I)
    if m:
        return text[:m.start()] + insert + text[m.start():]
    return text + insert


# ─── Evidence gate for keywords ───────────────────────────────────────────────
def classify_keywords(original, keywords, sector, job_title):
    """
    Split market keywords into:
      supported   — original resume has evidence the candidate has this
      unsupported — no evidence → gap report ONLY, never injected
    Deterministic substring match first; one GPT call for the remainder.
    """
    hay = _norm(original)
    supported, unknown = [], []
    for k in keywords:
        if _present(k, hay):
            supported.append(k)
        else:
            unknown.append(k)
    if unknown:
        try:
            verdict = jparse(gpt(
                'You are a strict evidence auditor. You never infer skills the text does not demonstrate. ONLY valid JSON.',
                f'''For each keyword, answer supported if the resume describes the candidate doing this, using this, or holding this — in any wording. The exact phrase is not required: "educated patients and families on home exercise programs" supports "patient education". A merely adjacent skill is NOT evidence: outpatient clinic work does not support "telehealth". When genuinely uncertain, unsupported.

Role: {job_title} ({sector})

KEYWORDS:
{json.dumps(unknown)}

RESUME:
{original[:9000]}

Return ONLY: {{"supported": ["keyword", ...], "unsupported": ["keyword", ...]}}''',
                max_tokens=600, temp=0.0))
            supported += [k for k in verdict.get('supported', []) if k in unknown]
            unsupported = [k for k in unknown if k not in verdict.get('supported', [])]
        except Exception:
            unsupported = unknown  # fail closed: unknown → not injectable
    else:
        unsupported = []
    return supported, unsupported


# ─── Fidelity audit ───────────────────────────────────────────────────────────
def fidelity_audit(original, candidate, sector):
    """
    Detect claims in CANDIDATE with no basis in ORIGINAL.
    Returns {'fabrications': [...], 'ok': bool}
    """
    try:
        r = jparse(gpt(
            'You are a resume fraud auditor. Your only job is to find claims the original does not support. ONLY valid JSON.',
            f'''Compare REWRITTEN against ORIGINAL. List every skill, technology, tool, credential, license, certification, experience, employer, title, metric, or competency that appears in REWRITTEN but has no supporting evidence in ORIGINAL.

NOT fabrication (do not flag):
- Stronger or different verbs for the same action (assisted → supported, made → built)
- Rephrasing, condensing, reordering, merging or splitting bullets
- Naming a skill the ORIGINAL demonstrates in other words (e.g. "educated patients on home programs" → "patient education")
- Standard section headers, formatting, punctuation
- Summarizing several original bullets into one summary sentence

Fabrication (flag):
- A skill, tool, technology, method, or setting the ORIGINAL never describes doing or using
- A license, certification, degree, employer, title, or location not in ORIGINAL
- Any number, percentage, or count not present in ORIGINAL and not a literal count of items listed there
- Seniority or scope inflation (e.g. "led a team" when ORIGINAL shows no leadership)

Be precise. Quote the offending phrase. If nothing qualifies, return an empty list.

ORIGINAL:
{original[:9000]}

REWRITTEN:
{candidate[:9000]}

Return ONLY: {{"fabrications": ["quoted phrase — why", ...]}}  (empty list if none)''',
            max_tokens=700, temp=0.0))
        fab = [f for f in r.get('fabrications', []) if isinstance(f, str) and f.strip()]
        return {'fabrications': fab, 'ok': len(fab) == 0}
    except Exception as e:
        # Fail closed: if we cannot audit, we cannot certify
        return {'fabrications': [f'audit unavailable: {e}'], 'ok': False}


# ─── Deterministic ATS score ──────────────────────────────────────────────────
def ats_score(text, keywords, weights=None):
    """
    Reproducible 0-100. Mirrors what commercial ATS scanners measure.
      keyword coverage   55   weighted: first 10 keywords count double
      section coverage   15   contact / summary / experience / education / skills
      verb strength      15   share of bullets opening with a strong verb
      quantification     10   share of experience bullets containing a number
      hygiene             5   length band, no weak openers dominating
    Returns (score, breakdown dict)
    """
    hay = _norm(text)
    kws = [k for k in keywords if k]
    if kws:
        wts = [2.0 if i < 10 else 1.0 for i in range(len(kws))]
        got = sum(w for k, w in zip(kws, wts) if _present(k, hay))
        kw_cov = got / sum(wts)
    else:
        kw_cov = 0.0

    heads = {h.lower() for h, _ in split_sections(text) if h}
    has = lambda *alts: any(any(a in h for a in alts) for h in heads)
    contact = bool(re.search(r'@|\(\d{3}\)|\d{3}[-.\s]\d{3}[-.\s]\d{4}', text))
    sec_hits = sum([contact, has('summary','profile','objective'), has('experience','employment','work history'),
                    has('education'), has('skills','competencies','expertise')])
    sec_cov = sec_hits / 5

    # Only experience-section bullets carry verb/quant expectations. A skills
    # list separated with "•" is not a bullet and must not drag the ratio down.
    exp_lines = []
    for h, body in split_sections(text):
        if h and re.search(r'experience|employment|work history|career', h, re.I):
            exp_lines += body
    if not exp_lines:
        exp_lines = _lines(text)
    bullets = [l.strip() for l in exp_lines if re.match(r'^\s*[-•*▪◦]\s+\S', l)]
    if not bullets:
        # No explicit markers (common in PDF-extracted text). Treat sentence-like
        # lines inside experience sections as bullets so verb/quant metrics still apply.
        for h, body in split_sections(text):
            if h and re.search(r'experience|employment|work history', h, re.I):
                bullets += [l.strip() for l in body
                            if len(l.split()) >= 7 and not re.search(r'\d{4}\s*[–-]\s*(\d{4}|present)', l, re.I)]
    if bullets:
        first = lambda b: _norm(re.sub(r'^[-•*▪◦]\s*', '', b)).split(' ')[0]
        strong = sum(1 for b in bullets if _is_strong(first(b)))
        weakop = sum(1 for b in bullets if first(b) in WEAK_OPENERS)
        quant  = sum(1 for b in bullets if _NUM.search(b))
        verb   = strong / len(bullets)
        qnt    = quant / len(bullets)
        weak_ratio = weakop / len(bullets)
    else:
        verb = qnt = 0.0
        weak_ratio = 1.0

    words = len(text.split())
    length_ok = 1.0 if 250 <= words <= 1100 else (0.6 if 150 <= words <= 1400 else 0.2)
    hygiene = 0.5 * length_ok + 0.5 * (1.0 - min(1.0, weak_ratio * 2))

    score = round(55 * kw_cov + 15 * sec_cov + 15 * verb + 10 * min(1.0, qnt * 1.5) + 5 * hygiene)
    return max(0, min(100, score)), {
        'keyword_coverage': round(kw_cov * 100), 'sections': sec_hits, 'bullets': len(bullets),
        'strong_verb_pct': round(verb * 100), 'quantified_pct': round(qnt * 100), 'words': words
    }


_PREAMBLE = re.compile(
    r'^\s*(?:(?:sure|certainly|of course|absolutely)[,!.]?\s*)?'
    r'(?:here(?:\'s| is| are)|below is|the following is|i(?:\'ve| have) (?:rewritten|revised|updated|improved))'
    r'[^\n]{0,120}:?\s*\n+', re.I)
_POSTAMBLE = re.compile(
    r'\n+\s*(?:let me know|i hope|hope this|feel free|would you like|please let|'
    r'note:|notes?:|changes made|summary of changes|key changes|explanation)[\s\S]*$', re.I)
_FENCE = re.compile(r'^\s*```[a-z]*\s*\n|\n\s*```\s*$', re.I)

def strip_commentary(text):
    """Remove model preamble/postamble/code fences so only resume text remains."""
    if not isinstance(text, str):
        return ''
    t = text.strip()
    t = _FENCE.sub('', t)
    prev = None
    while prev != t:                      # models sometimes stack two preambles
        prev = t
        t = _PREAMBLE.sub('', t, count=1).strip()
    t = _POSTAMBLE.sub('', t).strip()
    return t


def added_unsupported(original, candidate, unsupported):
    """Deterministic fabrication check: unsupported keywords that appear in the
    candidate but not the original. Runs before the model audit so a missed
    audit cannot be rewarded by the scorer."""
    if not unsupported:
        return []
    o, c = _norm(original), _norm(candidate)
    return [k for k in unsupported if _present(k, c) and not _present(k, o)]


# ─── The loop ─────────────────────────────────────────────────────────────────
ITER_FOCUS = {
    1: "Keyword integration. Weave each SUPPORTED keyword into the bullet or summary line where the original already demonstrates it. Replace weak openers (responsible for, worked with, helped) with strong verbs. Remove passive voice.",
    2: "Quantification from evidence only. Where the original states a number, make it prominent. Where the original lists countable items (e.g. three clinics, two states), count them. Where no number exists, strengthen the outcome language instead — do NOT invent a figure or an estimate.",
    3: "Readability. Tighten every bullet to one line where possible. Ensure the summary reads as a specific person, not a template. Vary sentence openings. Preserve every section and every credential exactly.",
}

def improvement_loop(initial_resume, all_kw, sector, job_title, seniority, analysis, emit):
    """
    Truth-preserving optimization loop.
    Each iteration: rewrite → fidelity audit → protected-content check →
    deterministic score → keep only if strictly better AND clean.
    Returns (best_text, best_score, report)
    """
    emit({'type':'log','msg':'\n🔄 SELF-IMPROVEMENT LOOP — truth-preserving'})
    original  = initial_resume
    protected = extract_protected(original)
    if protected['sections']:
        emit({'type':'log','msg':f"  🔒 Protected: {', '.join(protected['sections'].keys())}"})

    supported, unsupported = classify_keywords(original, all_kw, sector, job_title)
    emit({'type':'log','msg':f'  ✓ Keywords with evidence: {len(supported)}  |  gaps (report only): {len(unsupported)}'})
    if unsupported:
        emit({'type':'log','msg':f"  ○ Not injecting (no evidence): {', '.join(unsupported[:6])}{'…' if len(unsupported)>6 else ''}"})

    best_text = original
    best_score, best_bd = ats_score(original, all_kw)
    emit({'type':'log','msg':f'  Baseline ATS (measured): {best_score}/100  — kw {best_bd["keyword_coverage"]}%, verbs {best_bd["strong_verb_pct"]}%, quantified {best_bd["quantified_pct"]}%'})

    weak   = '\n'.join(analysis.get('weakBullets', [])[:4])
    unq    = '\n'.join(analysis.get('missingQuantification', [])[:3])
    report = {'iterations': [], 'rejected': 0, 'rejected_fabrication': 0, 'restored': [], 'supported': supported, 'unsupported': unsupported}

    for i in range(1, LOOP_ITERS + 1):
        emit({'type':'log','msg':f'\n  ▶ Iteration {i}/{LOOP_ITERS} — {ITER_FOCUS[i].split(".")[0]}'})
        emit({'type':'step','id':'rewrite','status':'running','msg':f'Iteration {i}/{LOOP_ITERS}…'})
        try:
            candidate = gpt(
                system=(f'You are an elite {sector} resume editor. You improve wording, structure, and keyword placement. '
                        'You NEVER add anything the candidate did not do. Output ONLY the resume text.'),
                user=f'''Edit this {job_title} ({seniority}) resume. Iteration {i} of {LOOP_ITERS}.

FOCUS THIS PASS:
{ITER_FOCUS[i]}

SUPPORTED KEYWORDS — the original already demonstrates these; place them where that evidence lives:
{', '.join(supported[:30]) or '(none)'}

WEAK BULLETS TO STRENGTHEN (reword, do not change facts):
{weak or '(none flagged)'}

BULLETS LACKING NUMBERS (add a number ONLY if the original contains it):
{unq or '(none flagged)'}

CURRENT VERSION:
{best_text}

NON-NEGOTIABLE RULES:
1. Do not add any skill, tool, technology, method, credential, license, certification, language, employer, title, date, location, or metric that is absent from the current version. If it is not there, it does not go in.
2. Keep EVERY section present in the current version. Never remove or merge LICENSES, CERTIFICATIONS, LANGUAGES, EDUCATION, WORK AUTHORIZATION, AWARDS, or PUBLICATIONS. Copy their contents verbatim.
3. Keep every employer, title, date range, and location exactly as written.
4. Bullets begin with "- " and a strong verb.
5. No estimates, no "[~X%]", no approximations. A number you cannot find in the current version does not exist.
6. Output ONLY the resume text. No commentary, no headings like "Here is".''',
                max_tokens=4000, temp=0.25
            )
            candidate = strip_commentary(clean(candidate))
            if len(candidate) < 0.5 * len(best_text):
                emit({'type':'log','msg':'  ✗ REJECTED — output too short (content loss)'})
                report['rejected'] += 1; continue

            # 1a. Deterministic gate — cheap, runs first, no model needed.
            hard = added_unsupported(original, candidate, unsupported)
            if hard:
                emit({'type':'log','msg':f"  ✗ REJECTED — added unsupported keyword(s): {', '.join(hard[:4])}"})
                report['rejected'] += 1; report['rejected_fabrication'] += 1
                report['iterations'].append({'i': i, 'kept': False, 'reason': 'unsupported_keyword', 'detail': hard})
                continue

            # 1b. Fidelity: reject any remaining fabrication outright
            audit = fidelity_audit(original, candidate, sector)
            if not audit['ok']:
                emit({'type':'log','msg':f"  ✗ REJECTED — fabricated: {audit['fabrications'][0][:110]}"})
                for f in audit['fabrications'][1:3]:
                    emit({'type':'log','msg':f'      also: {f[:110]}'})
                report['rejected'] += 1; report['rejected_fabrication'] += 1
                report['iterations'].append({'i': i, 'kept': False, 'reason': 'fabrication', 'detail': audit['fabrications'][:3]})
                continue

            # 2. Protected content: restore anything dropped
            dropped = check_protected(candidate, protected)
            if dropped['dropped_sections'] or dropped['dropped_lines']:
                what = dropped['dropped_sections'] or dropped['dropped_lines'][:2]
                emit({'type':'log','msg':f"  🔒 Restored dropped content: {', '.join(what)[:100]}"})
                candidate = restore_protected(candidate, protected, dropped)
                report['restored'] += what

            # 3. Score — same function, same keyword list, full text
            new_score, bd = ats_score(candidate, all_kw)
            delta = new_score - best_score
            icon  = '✓ IMPROVED' if delta > 0 else ('○ no gain' if delta == 0 else '✗ regressed')
            emit({'type':'log','msg':f'  {icon} — {best_score} → {new_score} ({delta:+d})  kw {bd["keyword_coverage"]}% · verbs {bd["strong_verb_pct"]}% · quant {bd["quantified_pct"]}%'})
            report['iterations'].append({'i': i, 'kept': delta > 0, 'score': new_score, 'breakdown': bd})

            if delta > 0:          # strictly better only
                best_text, best_score, best_bd = candidate, new_score, bd

        except Exception as e:
            emit({'type':'log','msg':f'  ⚠ Iteration {i} error: {str(e)[:120]}'})

    # Final safety net — the returned text must still carry every protected item
    dropped = check_protected(best_text, protected)
    if dropped['dropped_sections'] or dropped['dropped_lines']:
        best_text = restore_protected(best_text, protected, dropped)
        best_score, best_bd = ats_score(best_text, all_kw)
        emit({'type':'log','msg':'  🔒 Final check restored protected content'})

    emit({'type':'log','msg':f'\n  ✓ Loop complete — final ATS (measured): {best_score}/100  |  {report["rejected_fabrication"]} rejected for fabrication, {report["rejected"]-report["rejected_fabrication"]} for content loss'})
    if best_text is original:
        # No candidate beat the original. Say why, in terms the candidate can act on.
        reasons = []
        if best_bd.get('keyword_coverage', 0) >= 75 and unsupported:
            reasons.append(f"keyword coverage is already {best_bd['keyword_coverage']}% — the remaining {len(unsupported)} are skills you have not demonstrated, and APEX will not claim them")
        if best_bd.get('strong_verb_pct', 0) >= 85:
            reasons.append(f"{best_bd['strong_verb_pct']}% of bullets already open with strong verbs")
        if best_bd.get('quantified_pct', 0) == 0:
            reasons.append("no bullet contains a number — APEX cannot add one truthfully; add real figures (patients/week, caseload, outcomes) and re-run")
        if report['rejected_fabrication'] == LOOP_ITERS:
            reasons.append("every rewrite attempt added an unsupported claim and was rejected")
        emit({'type':'log','msg':'  ○ Original kept — it is at its truthful ceiling for this market:'})
        for r in (reasons or ['no rewrite produced a measurable gain without changing facts']):
            emit({'type':'log','msg':f'      · {r}'})
    report['final_breakdown'] = best_bd
    return best_text, best_score, report



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LINKEDIN OPTIMIZER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def linkedin_optimizer(job_title, sector, seniority, resume, market_keywords, emit):
    emit({"type":"log","msg":"\n💼 LINKEDIN OPTIMIZER"})
    emit({"type":"step","id":"rewrite","status":"running","msg":"Optimizing LinkedIn profile..."})
    try:
        kw_str = ", ".join(market_keywords[:25])
        raw = gpt(
            f"Expert LinkedIn profile writer for {sector} sector. Return ONLY valid JSON.",
            f"""Optimize LinkedIn for: {job_title} | {sector} | {seniority}
Keywords: {kw_str}
Resume: {resume[:2000]}

Return ONLY JSON:
{{
  "headline": "compelling 220-char headline with keywords",
  "about": "2000-char About section — story + keywords + CTA",
  "skills": ["skill1","skill2","skill3","skill4","skill5","skill6","skill7","skill8","skill9","skill10"],
  "experience_bullets": [{{"role":"latest role","bullets":["bullet1","bullet2","bullet3"]}}],
  "featured_tips": ["what to put in Featured section","idea 2"],
  "connection_strategy": ["growth tip 1","tip 2","tip 3"]
}}""",
            max_tokens=2200, temp=0.4
        )
        data = jparse(raw)
        emit({"type":"step","id":"rewrite","status":"done"})
        emit({"type":"step","id":"report","status":"done"})
        emit({"type":"linkedin_data","data":data})
        emit({"type":"done","msg":"LinkedIn profile optimized"})
    except Exception as e:
        emit({"type":"error","msg":f"LinkedIn error: {e}"})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# OUTREACH GENERATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def outreach_generator(job_title, sector, company_name, resume, market_keywords, emit):
    co = company_name or "the company"
    emit({"type":"log","msg":f"\n📨 OUTREACH GENERATOR — {co}"})
    emit({"type":"step","id":"rewrite","status":"running","msg":"Generating outreach templates..."})
    try:
        kw_str = ", ".join(market_keywords[:20])
        raw = gpt(
            "Expert career coach. Return ONLY valid JSON.",
            f"""Outreach templates for: {job_title} | {sector} | Company: {co}
Keywords: {kw_str}
Resume: {resume[:1600]}

Return ONLY JSON:
{{
  "linkedin_dm": {{
    "message": "personalized 300-char LinkedIn DM to hiring manager",
    "followup": "follow-up DM after 1 week"
  }},
  "cold_email": {{
    "subject": "compelling subject line",
    "body": "personalized 3-paragraph cold email",
    "followup": "follow-up email after 1 week"
  }},
  "referral_request": "message to mutual connection for intro",
  "thank_you_note": "post-interview thank you email",
  "negotiation_script": "salary negotiation email when offer comes",
  "tips": ["personalization tip","best send time","subject line tip","follow-up cadence"]
}}""",
            max_tokens=2200, temp=0.4
        )
        data = jparse(raw)
        emit({"type":"step","id":"rewrite","status":"done"})
        emit({"type":"step","id":"report","status":"done"})
        emit({"type":"outreach_data","data":data,"company":co})
        emit({"type":"done","msg":"Outreach templates ready"})
    except Exception as e:
        emit({"type":"error","msg":f"Outreach error: {e}"})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COST ESTIMATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def estimate_cost(mode="optimize"):
    costs = {
        "optimize":       {"calls":5,"input_k":12,"output_k":8},
        "cover_letter":   {"calls":2,"input_k":6, "output_k":2},
        "interview_prep": {"calls":2,"input_k":5, "output_k":4},
        "linkedin":       {"calls":1,"input_k":4, "output_k":3},
        "outreach":       {"calls":1,"input_k":4, "output_k":3},
    }
    c = costs.get(mode, costs["optimize"])
    total = (c["input_k"]/1000)*5.00 + (c["output_k"]/1000)*15.00
    return {"mode":mode,"calls":c["calls"],"est_usd":round(total,4),"est_cents":round(total*100,2)}


# AGENT LOOP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def agent_loop(job_title, industry, seniority, job_desc, resume, mode, emit):
    def log(m): emit({'type':'log','msg':m})
    def step(i,s,m=''): emit({'type':'step','id':i,'status':s,'msg':m})

    log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    log('  APEX Resume Agent v10')
    log('  Truth-Preserving Edition')
    log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    log(f'  Role : {job_title} | {seniority}')
    log(f'  Mode : {mode}')

    desc_ctx = f'\nJob Description:\n{job_desc[:600]}' if job_desc else ''

    # Shared state
    cls = {}; sector='general'; primary=job_title; alt_terms=[]
    anti_kw=[]; sector_signals=[]; target_words=[]
    corpus=''; final_count=0; confidence='minimal'; conf_pct=20
    market={}; analysis={}; optimized_text=''

    # ── PHASE 0: Role Classification ──────────────────────────────────────────
    log('\n🧠 PHASE 0 — Role Classification')
    step('market','running','Classifying role...')
    try:
        cls = jparse(gpt(
            system='Job role classifier. Return ONLY valid JSON.',
            user=f'''Classify: {job_title} | {seniority}{desc_ctx}

Return ONLY:
{{
  "sector": "tech|ai_data|cybersecurity|cloud_devops|real_estate|construction|architecture|healthcare|biotech_pharma|mental_health|finance|accounting|insurance|consulting|government|nonprofit|military_defense|creative_design|marketing|media_journalism|advertising_pr|operations|logistics|manufacturing|automotive|human_resources|sales|education|energy|hospitality|retail_service|sports_fitness|general",
  "function": "management|engineering|sales|marketing|finance_accounting|hr|customer_service|clinical|operations|creative|analytical",
  "level": "entry|mid|senior|manager|director|executive",
  "primary_search_term": "2-4 word job board search term",
  "alternate_terms": ["broader term", "related title", "senior variant"],
  "sector_signals": ["domain jargon 1","jargon 2","jargon 3","jargon 4","jargon 5"],
  "anti_keywords": ["obviously wrong skill"],
  "reasoning": "one sentence"
}}
Be conservative with anti_keywords — only obvious mismatches.
sector_signals must be real industry jargon (e.g. real_estate: NOI, cap rate, Yardi, CAPEX).''',
            max_tokens=500, temp=0.1
        ))
        sector        = cls.get('sector','general')
        primary       = cls.get('primary_search_term', job_title)
        alt_terms     = cls.get('alternate_terms', [job_title])
        sector_signals= [s.lower() for s in cls.get('sector_signals',[])]
        anti_kw       = [k.lower() for k in cls.get('anti_keywords',[])]
        target_words  = [w.lower() for w in job_title.split() if len(w)>2]
        log(f'  ✓ Sector  : {sector} | {cls.get("function","?")}')
        log(f'  ✓ Search  : "{primary}"')
        log(f'  ✓ Signals : {", ".join(cls.get("sector_signals",[])[:5])}')
        log(f'  ✓ Exclude : {", ".join(cls.get("anti_keywords",[])[:4])}')
    except Exception as e:
        log(f'  ⚠ Classification error: {e} — using defaults')

    # ── PHASE 1: Parallel Live Harvest ────────────────────────────────────────
    sources = SECTOR_SOURCES.get(sector, SECTOR_SOURCES['general'])
    log(f'\n🌐 PHASE 1 — Live Harvest ({len(sources)} {sector} sources)')
    step('market','running',f'Scraping {len(sources)} sources...')

    raw, stats, lock = [], {}, threading.Lock()
    scraped_jobs_store = []  # stores raw listings for job board tab
    def run(fn):
        name = fn.__name__.replace('src_','').title()
        try:
            log(f'  ↳ [{name}] connecting...')
            items = fn(primary)
            with lock:
                stats[name] = len(items)
                raw.extend(items)
                for item in items[:4]:
                    scraped_jobs_store.append({'source': name, 'text': item[:600], 'query': primary if 'primary' in dir() else job_title})
            log(f'  {"✓" if items else "○"} {name}: {len(items)} listings')
        except Exception as e:
            with lock: stats[name]=0
            log(f'  ✗ {name}: {str(e)[:50]}')

    threads = [threading.Thread(target=run, args=(fn,), daemon=True) for fn in sources]
    for t in threads: t.start()
    for t in threads: t.join(timeout=25)

    raw_count = len(raw)
    log(f'\n  📊 Raw: {raw_count} listings from {sum(1 for c in stats.values() if c>0)}/{len(sources)} sources')

    # ── PHASE 2: Retry if sparse ──────────────────────────────────────────────
    if raw_count < MIN_LISTINGS and alt_terms:
        log(f'\n🔄 PHASE 2 — Retry (sparse: {raw_count})')
        for alt in alt_terms[:3]:
            log(f'  ↳ Trying: "{alt}"')
            for fn in sources[:3]:
                try: raw.extend(fn(alt))
                except: pass
            if len(raw) >= MIN_LISTINGS: break
            time.sleep(0.5)
    else:
        log(f'\n✓ PHASE 2 — Skipped (sufficient: {raw_count} listings)')

    # ── PHASE 3: Relevance Filter ─────────────────────────────────────────────
    log('\n🎯 PHASE 3 — Relevance Filter')
    filtered    = filter_listings(raw, target_words, sector_signals, anti_kw, emit)
    final_count = len(filtered)
    corpus      = '\n\n'.join(filtered[:35])[:MAX_CORPUS]
    active      = [n for n,c in stats.items() if c>0]

    if   final_count >= 20: confidence,conf_pct = 'high',90
    elif final_count >= 10: confidence,conf_pct = 'medium',70
    elif final_count >= 5:  confidence,conf_pct = 'low',45
    else:                   confidence,conf_pct = 'minimal',20

    log(f'  ✓ Corpus: {final_count} listings / {len(corpus):,} chars')
    log(f'  ✓ Confidence: {confidence.upper()} ({conf_pct}%)')
    step('market','done',f'{final_count} relevant listings ({confidence})')
    # Emit job listings for the Jobs Board tab
    if scraped_jobs_store:
        emit({'type':'jobs_data','jobs': scraped_jobs_store[:30],'query': primary,'sector': sector})

    # ── PHASE 4: Keyword Intelligence ─────────────────────────────────────────
    log('\n🔑 PHASE 4 — Keyword Intelligence (Hard + Soft Skills)')
    step('heat','running',f'Extracting from {final_count} listings...')

    kw_prompt = f'''Extract keywords from real {sector} job postings for a {job_title} resume.
EXCLUDE: {", ".join(anti_kw[:8]) if anti_kw else "none"}
DATA ({final_count} listings):
{corpus[:12000]}

Return ONLY this JSON:
{{
  "hot":          [{{"name":"skill","freq":85}}],
  "warm":         [{{"name":"skill","freq":52}}],
  "cold":         [{{"name":"skill","freq":22}}],
  "emerging":     [{{"name":"skill","freq":28}}],
  "frequency":    [{{"name":"skill","pct":85}}],
  "hard_skills":  [{{"name":"technical skill","freq":80}}],
  "soft_skills":  [{{"name":"soft skill","freq":65}}],
  "salary_skills":[{{"name":"premium skill","impact":"high|medium","note":"adds value"}}],
  "validation_note": "X keywords from Y real listings"
}}
hot=65%+(12 items), warm=30-64%(10), cold=<30%(6), emerging=trending(5)
frequency=top 12 ranked. hard_skills=technical/tools(8). soft_skills=interpersonal(6).
salary_skills=top 5 skills commanding premium pay in this sector.
NEVER include: {", ".join(anti_kw[:6]) if anti_kw else "none"}''' if corpus and len(corpus)>200 else f'''
No live data. Use expert {sector} knowledge for {job_title} 2025.
EXCLUDE: {", ".join(anti_kw[:8]) if anti_kw else "none"}
Same JSON structure. validation_note: "model knowledge — limited live data".'''

    try:
        market = jparse(gpt('Keyword analyst. ONLY valid JSON. Never include excluded keywords.', kw_prompt, max_tokens=2200, temp=0.2))
        for k in ('hot','warm','cold','emerging','frequency','hard_skills','soft_skills','salary_skills'):
            market[k] = [x for x in market.get(k,[]) if x.get('name','').lower() not in anti_kw]
        market.update({'confidence':confidence,'confidence_pct':conf_pct,'total_jobs_analyzed':final_count,'sector':sector})
        log(f'  ✓ {len(market.get("hot",[]))} hot | {len(market.get("hard_skills",[]))} hard skills | {len(market.get("soft_skills",[]))} soft skills')
        if market.get('salary_skills'): log(f'  💰 Salary premium: {", ".join(s.get("name","") for s in market["salary_skills"][:3])}')
    except Exception as e:
        log(f'  ⚠ Keyword error: {e}')
        market = {'hot':[],'warm':[],'cold':[],'emerging':[],'frequency':[],'hard_skills':[],'soft_skills':[],'salary_skills':[],'confidence':confidence,'total_jobs_analyzed':final_count}

    step('heat','done','Keywords extracted')

    # ── PHASE 5: ATS Scoring ──────────────────────────────────────────────────
    log('\n📊 PHASE 5 — ATS Scoring')
    step('analyze','running','Scoring...')

    all_kw = list(dict.fromkeys(filter(None,
        [k.get('name','') for k in market.get('hot',[])] +
        [k.get('name','') for k in market.get('warm',[])] +
        [k.get('name','') for k in market.get('emerging',[])]
    )))

    try:
        analysis = jparse(gpt(
            f'ATS for {sector}. Honest scoring. ONLY valid JSON.',
            f'''Target: {job_title} | {sector} | {seniority}
Market keywords ({final_count} real listings): {", ".join(all_kw[:30])}
NEVER suggest: {", ".join(anti_kw[:6]) if anti_kw else "none"}
Resume:
{resume}

Do NOT output a numeric score — scoring is computed separately. Analyze only.

Return ONLY:
{{
  "keywords":[{{"keyword":"<name>","status":"present|missing","priority":"P1|P2|P3","freq":<int>}}],
  "weakBullets":["<exact verbatim bullet from the resume>"],
  "missingQuantification":["<exact verbatim bullet from the resume>"],
  "topGaps":["<skill the market wants that this resume shows NO evidence of — this goes in a report for the candidate, it will NOT be added to the resume>"],
  "strengths":["<strength>"],
  "atsRedFlags":["<formatting or structural flag>"]
}}''',
            max_tokens=2500, temp=0.2
        ))
    except Exception as e:
        log(f'  ⚠ Scoring error: {e}')
        analysis = {'atsScoreBefore':50,'atsScoreAfter':72}

    _before, _before_bd = ats_score(resume, all_kw)
    market['atsScoreBefore']   = _before
    market['atsScoreAfter']    = _before          # updated after the loop runs
    market['scoreBreakdownBefore'] = _before_bd
    market['humanReadability'] = analysis.get('humanReadability',0)
    market['uniquenessScore']  = analysis.get('uniquenessScore',0)
    market['grammarIssues']    = analysis.get('grammarIssues',[])
    market['uniquenessFixes']  = analysis.get('uniquenessFixes',[])
    market['salaryByLocation'] = analysis.get('salaryByLocation',[])
    market['scrape_info']    = {'sources':active,'jobs_analyzed':final_count,'data_quality':confidence,'sector':sector,'search_term':primary}

    log(f'  ✓ ATS baseline (measured): {market["atsScoreBefore"]}/100 — keyword coverage {_before_bd["keyword_coverage"]}%')
    if analysis.get('topGaps'): log(f'  ⚠ Gaps: {", ".join(analysis["topGaps"][:3])}')
    if analysis.get('strengths'): log(f'  ✓ Strong: {", ".join(analysis["strengths"][:2])}')

    step('analyze','done')
    emit({'type':'market_data','data':market})

    # Mode routing removed — every run now populates ALL tabs automatically
    # The parallel Phase 8 generator handles cover letter, interview, LinkedIn, outreach

    # ── PHASE 6: Self-Improvement Loop ────────────────────────────────────────
    # This is where APEX beats every competitor.
    # 3 iterations of rewriting — each one graded, only kept if better.
    step('rewrite','running','Starting self-improvement loop...')
    optimized_text, final_ats, loop_report = improvement_loop(
        resume, all_kw, sector, job_title, seniority, analysis, emit
    )

    # The after-score is the measured score of the text we actually ship.
    market['atsScoreAfter']       = final_ats
    market['scoreBreakdownAfter'] = loop_report.get('final_breakdown', {})
    market['keywordsInjected']    = loop_report.get('supported', [])
    market['keywordsGapsOnly']    = loop_report.get('unsupported', [])
    market['iterationsRejected']  = loop_report.get('rejected', 0)
    market['fabricationsBlocked']  = loop_report.get('rejected_fabrication', 0)
    market['protectedRestored']   = loop_report.get('restored', [])
    analysis['topGaps'] = list(dict.fromkeys((analysis.get('topGaps') or []) + loop_report.get('unsupported', [])))[:8]
    emit({'type':'market_data','data':market})
    step('rewrite','done')
    emit({'type':'resume_data','original':resume,'optimized':optimized_text,'added':analysis.get('addedKeywords',[])})
    log(f'  ✓ Final ATS: {market["atsScoreAfter"]}/100')

    # ── PHASE 7: Gap Report ───────────────────────────────────────────────────
    log('\n📋 PHASE 7 — Gap Report')
    step('report','running','Generating...')

    hard_skills = [k.get('name','') for k in market.get('hard_skills',[])]
    soft_skills = [k.get('name','') for k in market.get('soft_skills',[])]

    try:
        rpt = jparse(gpt(
            f'{sector} resume consultant. ONLY valid JSON.',
            f'''Target: {job_title} | {sector} | {seniority}
Live data: {final_count} listings | confidence: {confidence}

Original: {resume[:1800]}
Optimized: {optimized_text[:1800]}

Return ONLY:
{{
  "changes":[{{"before":"exact original","after":"exact rewritten","why":"reason naming keyword"}}],
  "recommendations":["specific {sector}-appropriate action"],
  "sectorInsights":["insight about {sector} hiring 2025"],
  "hardSkillsGap":["missing hard skill"],
  "softSkillsGap":["missing soft skill"],
  "salaryInsights":["how this resume could command higher salary"],
  "nextSteps":["immediately actionable step"]
}}
changes=6-8 pairs exact text. recommendations=5 SECTOR-APPROPRIATE actions.
sectorInsights=3 insights. hardSkillsGap from: {", ".join(hard_skills[:8])}.
softSkillsGap from: {", ".join(soft_skills[:6])}. salaryInsights=2. nextSteps=3.''',
            max_tokens=2500, temp=0.3
        ))
    except Exception as e:
        log(f'  ⚠ Report error: {e}')
        rpt = {'changes':[],'recommendations':[],'sectorInsights':[]}

    rpt['atsScoreBefore'] = market['atsScoreBefore']
    rpt['atsScoreAfter']  = market['atsScoreAfter']
    rpt['keywords']             = analysis.get('keywords',[])
    rpt['certificationRoadmap'] = analysis.get('certificationRoadmap',[])
    rpt['salaryByLocation']     = analysis.get('salaryByLocation',[])
    rpt['grammarIssues']        = analysis.get('grammarIssues',[])
    rpt['uniquenessFixes']      = analysis.get('uniquenessFixes',[])
    rpt['scrape_info']    = market['scrape_info']

    step('report','done')
    emit({'type':'report_data','data':rpt})

    log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    log(f'  ✓ Complete | Sector: {sector} | Confidence: {confidence}')
    log(f'  ✓ {final_count} listings analyzed | {len(active)} sources active')
    log(f'  ✓ ATS: {market["atsScoreBefore"]} → {market["atsScoreAfter"]} (+{market["atsScoreAfter"]-market["atsScoreBefore"]})')
    log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 8 — PARALLEL GENERATION: ALL TABS AT ONCE
    # Every tab populates from a single run. No mode switching. Ever.
    # Cover letter, interview prep, LinkedIn, outreach — all fire together.
    # ═══════════════════════════════════════════════════════════════════════
    log('\n⚡ PHASE 8 — Generating all content in parallel...')
    emit({'type':'step','id':'report','status':'running','msg':'Generating cover letter, interview prep, LinkedIn & outreach...'})

    company_name = ''  # Can be passed via payload in future

    def gen_cover_letter():
        try:
            letter = gpt(
                f'Expert cover letter writer for {sector} sector. Output ONLY the letter text.',
                f'''Write a compelling cover letter:
Role: {job_title} | {sector} | {seniority}
Market keywords: {", ".join(all_kw[:20])}
Resume: {resume[:2000]}

3 paragraphs: Hook → Value proposition → Call to action.
Inject validated keywords. Quantify 2-3 achievements. Output ONLY the letter.''',
                max_tokens=800, temp=0.5
            )
            emit({'type':'cover_letter_data','letter':letter})
        except Exception as e:
            log(f'  ⚠ Cover letter: {e}')

    def gen_interview():
        try:
            prep_raw = gpt(
                f'Senior {sector} hiring manager. Return ONLY valid JSON.',
                f'''Interview prep for: {job_title} | {sector} | {seniority}
Gaps: {", ".join(analysis.get("topGaps",[])[:3])}
Strengths: {", ".join(analysis.get("strengths",[])[:3])}
Return ONLY JSON:
{{"behavioral":[{{"q":"question","a":"STAR answer","tip":"tip"}}],
  "technical":[{{"q":"question","a":"answer","tip":"tip"}}],
  "situational":[{{"q":"question","a":"answer","tip":"tip"}}],
  "questions_to_ask":["smart question for interviewer"],
  "salary_negotiation":["negotiation tip for {sector}"],
  "red_flags_to_address":["how to address weakness"]}}''',
                max_tokens=2000, temp=0.4
            )
            emit({'type':'interview_data','data':jparse(prep_raw)})
        except Exception as e:
            log(f'  ⚠ Interview prep: {e}')

    def gen_linkedin():
        try:
            raw = gpt(
                f'Expert LinkedIn profile writer for {sector}. Return ONLY valid JSON.',
                f'''Optimize LinkedIn for: {job_title} | {sector} | {seniority}
Keywords: {", ".join(all_kw[:25])}
Resume: {resume[:2000]}
Return ONLY JSON:
{{"headline":"220-char keyword-rich headline",
  "about":"2000-char About — story + keywords + CTA",
  "skills":["skill1","skill2","skill3","skill4","skill5","skill6","skill7","skill8","skill9","skill10"],
  "experience_bullets":[{{"role":"latest role","bullets":["bullet1","bullet2","bullet3"]}}],
  "featured_tips":["Featured section idea 1","idea 2"],
  "connection_strategy":["growth tip 1","tip 2","tip 3"]}}''',
                max_tokens=2000, temp=0.4
            )
            emit({'type':'linkedin_data','data':jparse(raw)})
        except Exception as e:
            log(f'  ⚠ LinkedIn: {e}')

    def gen_outreach():
        try:
            raw = gpt(
                'Expert career coach. Return ONLY valid JSON.',
                f'''Outreach templates for: {job_title} | {sector}
Keywords: {", ".join(all_kw[:20])}
Resume: {resume[:1600]}
Return ONLY JSON:
{{"linkedin_dm":{{"message":"personalized 300-char LinkedIn DM","followup":"follow-up after 1 week"}},
  "cold_email":{{"subject":"compelling subject line","body":"3-paragraph cold email","followup":"follow-up after 1 week"}},
  "referral_request":"message to mutual connection for intro",
  "thank_you_note":"post-interview thank you email",
  "negotiation_script":"salary negotiation email when offer comes",
  "tips":["personalization tip","best send time","subject line tip","follow-up cadence"]}}''',
                max_tokens=2000, temp=0.4
            )
            emit({'type':'outreach_data','data':jparse(raw),'company':company_name or 'the company'})
        except Exception as e:
            log(f'  ⚠ Outreach: {e}')

    def gen_velocity():
        try:
            vraw = gpt(
                f'Career strategist for {sector}. Return ONLY valid JSON.',
                f'''Career velocity analysis: {job_title} | {sector} | {seniority}
Resume: {resume[:1800]}
Return ONLY JSON:
{{"velocity_score":72,"trajectory":"ascending|plateau|declining",
  "next_level_title":"natural next role","years_to_next_level":2,
  "market_position":"ahead|at|behind","market_position_note":"vs peers",
  "acceleration_moves":["move 1","move 2","move 3"],
  "10_year_projection":"realistic path",
  "peer_comparison":"vs others at same level"}}''',
                max_tokens=800, temp=0.4
            )
            emit({'type':'velocity_data','data':jparse(vraw)})
        except Exception as e:
            log(f'  ⚠ Velocity: {e}')

    # Fire all generators in parallel threads
    gen_threads = [
        threading.Thread(target=gen_cover_letter, daemon=True),
        threading.Thread(target=gen_interview,    daemon=True),
        threading.Thread(target=gen_linkedin,     daemon=True),
        threading.Thread(target=gen_outreach,     daemon=True),
        threading.Thread(target=gen_velocity,     daemon=True),
    ]
    for t in gen_threads: t.start()
    for t in gen_threads: t.join(timeout=60)

    emit({'type':'step','id':'report','status':'done'})

    cost = estimate_cost('optimize')
    emit({'type':'cost_data','data': cost})
    log(f'\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    log(f'  ✓ ALL TABS POPULATED')
    log(f'  ✓ {final_count} live jobs analyzed')
    log(f'  ✓ ATS: {market["atsScoreBefore"]} → {market["atsScoreAfter"]}')
    log(f'  ✓ Cost: ~{cost["est_cents"]}¢')
    log(f'━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    emit({'type':'done','msg':f'All tabs populated — {final_count} listings — ~{cost["est_cents"]}¢'})


def _cover_letter(job_title, sector, seniority, resume, all_kw, corpus, market, emit):
    emit({'type':'log','msg':'\n✉ COVER LETTER AGENT'})
    emit({'type':'step','id':'rewrite','status':'running','msg':'Writing cover letter...'})
    try:
        letter = gpt(
            f'Expert cover letter writer for {sector} sector. Output ONLY the cover letter text.',
            f'''Write a compelling cover letter for: {job_title} | {sector} | {seniority}

Market keywords from live data: {", ".join(all_kw[:20])}

Candidate resume summary:
{resume[:2000]}

Rules:
1. 3 paragraphs: Opening hook → Core value proposition → Call to action
2. Inject validated market keywords naturally
3. Quantify 2-3 achievements from the resume
4. Confident, specific, not generic
5. Output ONLY the letter text — no subject line, no explanation''',
            max_tokens=1000, temp=0.5
        )
        emit({'type':'step','id':'rewrite','status':'done'})
        emit({'type':'cover_letter_data','letter':letter})
        emit({'type':'step','id':'report','status':'done'})
        emit({'type':'done','msg':'Cover letter generated'})
    except Exception as e:
        emit({'type':'error','msg':f'Cover letter error: {e}'})


def _interview_prep(job_title, sector, seniority, resume, analysis, market, emit):
    emit({'type':'log','msg':'\n🎯 INTERVIEW PREP AGENT'})
    emit({'type':'step','id':'rewrite','status':'running','msg':'Generating interview Q&A...'})
    try:
        prep_raw = gpt(
            f'Senior hiring manager for {sector} sector with 15 years experience. Return ONLY valid JSON.',
            f'''Generate interview preparation for: {job_title} | {sector} | {seniority}

Resume gaps to address: {", ".join(analysis.get("topGaps",[])[:5])}
Candidate strengths: {", ".join(analysis.get("strengths",[])[:3])}

Return ONLY:
{{
  "behavioral":[{{"q":"behavioral question","a":"STAR-format sample answer using resume context","tip":"coaching tip"}}],
  "technical":[{{"q":"technical question","a":"strong answer","tip":"tip"}}],
  "situational":[{{"q":"situational question","a":"sample answer","tip":"tip"}}],
  "questions_to_ask":["smart question to ask the interviewer"],
  "salary_negotiation":["negotiation tip specific to {sector}"],
  "red_flags_to_address":["how to address resume gap or weakness"]
}}
behavioral=5 questions. technical=4 sector-specific questions. situational=3. questions_to_ask=4. salary_tips=3. red_flags=2.''',
            max_tokens=3000, temp=0.4
        )
        prep = jparse(prep_raw)
        emit({'type':'step','id':'rewrite','status':'done'})
        emit({'type':'step','id':'report','status':'done'})
        emit({'type':'interview_data','data':prep})
        emit({'type':'done','msg':'Interview prep ready'})
    except Exception as e:
        emit({'type':'error','msg':f'Interview prep error: {e}'})




# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MARKET DRIFT DETECTION
# Saves baseline score. Re-runs weekly. Alerts on decay.
# Patent-worthy: no competitor does this.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def drift_check(job_title, sector, resume, baseline_score, emit):
    """
    Re-scrape live market for a role and compare current keyword
    match against a saved baseline score. Returns drift analysis.
    """
    emit({'type':'log','msg':f'\n📡 DRIFT CHECK — {job_title}'})
    try:
        sources = SECTOR_SOURCES.get(sector, SECTOR_SOURCES['general'])
        raw = []
        lock = threading.Lock()

        def quick_scrape(fn):
            try:
                items = fn(job_title)
                with lock: raw.extend(items[:5])
            except Exception: pass

        threads = [threading.Thread(target=quick_scrape, args=(fn,), daemon=True)
                   for fn in sources[:3]]
        for t in threads: t.start()
        for t in threads: t.join(timeout=15)

        corpus = ' '.join(raw)[:8000]

        result_raw = gpt(
            'You are a resume market analyst. Return ONLY valid JSON.',
            f'''Compare this resume against current live job postings for: {job_title}

Live market data (today):
{corpus[:6000]}

Resume to evaluate:
{resume[:2000]}

Baseline ATS score from last check: {baseline_score}

Return ONLY JSON:
{{
  "current_score": 72,
  "baseline_score": {baseline_score},
  "drift": -6,
  "drifted": true,
  "new_keywords": ["keyword that appeared since last check","keyword2"],
  "faded_keywords": ["keyword that was hot but now less common"],
  "verdict": "one sentence on what changed in the market",
  "urgency": "high|medium|low"
}}''',
            max_tokens=600, temp=0.2
        )
        result = jparse(result_raw)
        emit({'type':'drift_data','data':result,'role':job_title})
        emit({'type':'done','msg':f'Drift check complete — score moved {result.get("drift",0):+d} pts'})
    except Exception as e:
        emit({'type':'error','msg':f'Drift check error: {e}'})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SMART JOB MATCH SCORER
# Paste any job posting → get instant % match + missing keywords
# before you apply. Save yourself applying to jobs you won't get.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def smart_match(job_posting, resume, emit):
    """Score resume match % against a specific job posting."""
    emit({'type':'log','msg':'\n🎯 SMART MATCH SCORING'})
    emit({'type':'step','id':'analyze','status':'running','msg':'Scoring match against this posting...'})
    try:
        raw = gpt(
            'You are an ATS system. Score resume match against a specific job posting. Return ONLY valid JSON.',
            f'''Score this resume against this specific job posting.

JOB POSTING:
{job_posting[:3000]}

RESUME:
{resume[:2500]}

Return ONLY JSON:
{{
  "match_pct": 73,
  "should_apply": true,
  "apply_confidence": "high|medium|low",
  "verdict": "one sentence — is this a strong match?",
  "matching_keywords": ["keyword in both posting and resume"],
  "missing_critical": ["critical keyword in posting but not resume"],
  "missing_nice": ["nice-to-have keyword missing"],
  "quick_fixes": [
    {{"add_to_resume":"exact phrase to add","where":"skills section or which bullet","impact":"high|medium"}}
  ],
  "red_flags": ["reason this application might struggle"],
  "green_flags": ["reason this is a strong match"],
  "estimated_competition": "high|medium|low",
  "role_title_extracted": "title extracted from posting",
  "company_extracted": "company name if mentioned"
}}''',
            max_tokens=1200, temp=0.2
        )
        result = jparse(raw)
        emit({'type':'step','id':'analyze','status':'done'})
        emit({'type':'match_data','data':result})
        emit({'type':'done','msg':f'Match score: {result.get("match_pct",0)}% — {result.get("verdict","")}'})
    except Exception as e:
        emit({'type':'error','msg':f'Smart match error: {e}'})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RESUME WEAKNESS X-RAY
# Finds the exact 3 bullets that are most hurting your chances.
# Not generic feedback — pinpoints the specific cancer cells.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def weakness_xray(job_title, sector, resume, market_keywords, emit):
    """Deep-dive surgical analysis of the weakest resume elements."""
    emit({'type':'log','msg':'\n🔬 WEAKNESS X-RAY ANALYSIS'})
    emit({'type':'step','id':'analyze','status':'running','msg':'X-Ray scanning resume...'})
    try:
        raw = gpt(
            f'Expert {sector} resume analyst. Brutally honest. Return ONLY valid JSON.',
            f'''Perform a surgical weakness analysis on this {job_title} resume.

Market keywords in demand: {", ".join(market_keywords[:20])}

Resume:
{resume[:3000]}

Find the SPECIFIC elements that are most hurting this resume.
Be brutally honest and specific — quote exact text.

Return ONLY JSON:
{{
  "killer_bullets": [
    {{
      "quote": "exact bullet text from resume",
      "problem": "why this is hurting them",
      "fix": "exact rewrite",
      "impact": "high|medium"
    }}
  ],
  "summary_verdict": "one-paragraph verdict on the resume opening/summary",
  "first_impression_score": 62,
  "first_impression_note": "what a recruiter thinks in the first 3 seconds",
  "biggest_missed_opportunity": "the single biggest thing they could change for maximum impact",
  "generic_phrases": ["responsible for...","helped with...","assisted in..."],
  "strong_elements": ["what is actually working well — be specific"],
  "formatting_score": 78,
  "formatting_notes": ["formatting observation 1","observation 2"]
}}''',
            max_tokens=1800, temp=0.3
        )
        result = jparse(raw)
        emit({'type':'step','id':'analyze','status':'done'})
        emit({'type':'xray_data','data':result})
        emit({'type':'done','msg':'X-Ray complete'})
    except Exception as e:
        emit({'type':'error','msg':f'X-Ray error: {e}'})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# INTERVIEW SIMULATOR
# AI plays the interviewer. User types answers.
# AI grades each answer and gives coaching.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def grade_interview_answer(question, answer, job_title, sector, emit):
    """Grade a user's interview answer and provide coaching."""
    try:
        raw = gpt(
            f'You are a senior {sector} hiring manager with 15 years experience. Return ONLY valid JSON.',
            f'''Grade this interview answer for a {job_title} position.

QUESTION: {question}
CANDIDATE ANSWER: {answer}

Return ONLY JSON:
{{
  "score": 72,
  "grade": "B",
  "verdict": "one sentence assessment",
  "strengths": ["what they did well"],
  "weaknesses": ["what was missing or weak"],
  "ideal_answer_structure": "what a perfect answer would include",
  "better_version": "rewritten version of their answer using STAR format",
  "keywords_used": ["keywords they included"],
  "keywords_missed": ["keywords they should have mentioned"],
  "coaching_tip": "the single most important thing to improve"
}}''',
            max_tokens=1000, temp=0.3
        )
        result = jparse(raw)
        emit({'type':'answer_grade','data':result,'question':question})
    except Exception as e:
        emit({'type':'error','msg':f'Grading error: {e}'})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CAREER VELOCITY SCORE
# Are you trending up or sideways? 
# Compares trajectory vs market expectations for your level.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def career_velocity(job_title, sector, seniority, resume, emit):
    """Analyze career trajectory and velocity vs market expectations."""
    emit({'type':'log','msg':'\n🚀 CAREER VELOCITY ANALYSIS'})
    try:
        raw = gpt(
            f'Expert {sector} career strategist. Honest assessment. Return ONLY valid JSON.',
            f'''Analyze career velocity for: {job_title} | {sector} | {seniority}

Resume:
{resume[:2500]}

Return ONLY JSON:
{{
  "velocity_score": 72,
  "trajectory": "ascending|plateau|declining",
  "years_to_next_level": 2,
  "next_level_title": "what the natural next role is",
  "velocity_factors": [
    {{"factor":"promotion cadence","assessment":"positive|neutral|negative","note":"explanation"}}
  ],
  "market_position": "ahead|at|behind",
  "market_position_note": "how they compare to peers at same level",
  "acceleration_moves": ["specific move that would accelerate career","move 2","move 3"],
  "risk_factors": ["career risk 1","risk 2"],
  "10_year_projection": "realistic 10-year career trajectory based on current path",
  "peer_comparison": "how this resume compares to others at the same level"
}}''',
            max_tokens=1200, temp=0.4
        )
        result = jparse(raw)
        emit({'type':'velocity_data','data':result})
        emit({'type':'done','msg':f'Velocity score: {result.get("velocity_score",0)} — {result.get("trajectory","unknown")} trajectory'})
    except Exception as e:
        emit({'type':'error','msg':f'Velocity error: {e}'})



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# JOB-SPECIFIC TAILORING — THE KILLER FEATURE
# Paste any posting → resume rewritten for THAT job in 30 seconds
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def job_tailor(job_posting, resume, job_title, sector, emit):
    emit({"type":"log","msg":"\n⚡ JOB-SPECIFIC TAILORING ENGINE"})
    emit({"type":"step","id":"analyze","status":"running","msg":"Extracting job DNA..."})
    try:
        raw = gpt(
            "You are an expert resume tailor. Return ONLY valid JSON.",
            f"""Tailor this resume SPECIFICALLY for this job posting.

JOB POSTING:
{job_posting[:3000]}

CURRENT RESUME:
{resume[:2500]}

Extract every requirement from the posting. Rewrite the resume to mirror the posting's exact language, prioritize matching requirements, and maximize ATS score for THIS specific role.

Return ONLY JSON:
{{
  "tailored_resume": "complete rewritten resume tailored to this posting",
  "match_score_before": 58,
  "match_score_after": 91,
  "keywords_injected": ["exact keyword from posting added to resume"],
  "sections_reordered": ["Experience moved before Skills because posting emphasizes it"],
  "top_matches": ["requirement from posting matched perfectly"],
  "gaps_addressed": ["gap and how it was bridged"],
  "company_name": "extracted company name",
  "role_title": "extracted role title",
  "key_requirements": ["top 5 requirements from posting"],
  "tailoring_notes": ["specific change made and why"]
}}""",
            max_tokens=3000, temp=0.3
        )
        result = jparse(raw)
        emit({"type":"step","id":"analyze","status":"done"})
        emit({"type":"step","id":"rewrite","status":"done"})
        emit({"type":"tailor_data","data":result})
        emit({"type":"done","msg":f"Resume tailored — {result.get('match_score_before',0)} → {result.get('match_score_after',0)} match score"})
    except Exception as e:
        emit({"type":"error","msg":f"Tailor error: {e}"})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BULLET STRENGTH RANKER
# Every bullet ranked 1-100. Bottom 5 rewritten. Surgical.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def bullet_ranker(resume, job_title, sector, market_keywords, emit):
    emit({"type":"log","msg":"\n🎯 BULLET STRENGTH RANKER"})
    try:
        kw_str = ", ".join(market_keywords[:20])
        raw = gpt(
            f"Expert {sector} resume analyst. Return ONLY valid JSON.",
            f"""Analyze every bullet point in this {job_title} resume.

Market keywords in demand: {kw_str}

RESUME:
{resume[:2500]}

Score each bullet 0-100 on: action verb strength, quantification, keyword density, specificity, impact clarity.

Return ONLY JSON:
{{
  "ranked_bullets": [
    {{
      "text": "exact bullet text",
      "score": 85,
      "rank": 1,
      "strengths": ["strong action verb", "quantified"],
      "weaknesses": [],
      "rewrite": null
    }},
    {{
      "text": "weak bullet",
      "score": 32,
      "rank": 12,
      "strengths": [],
      "weaknesses": ["passive voice", "no metrics", "vague"],
      "rewrite": "Led cross-functional team of 8 to deliver X, resulting in Y% improvement"
    }}
  ],
  "average_score": 67,
  "strongest_bullet": "exact text of #1 bullet",
  "weakest_bullet": "exact text of last bullet",
  "overall_verdict": "one sentence assessment"
}}""",
            max_tokens=2500, temp=0.2
        )
        result = jparse(raw)
        emit({"type":"bullet_data","data":result})
        emit({"type":"done","msg":f"Ranked {len(result.get('ranked_bullets',[]))} bullets · avg score {result.get('average_score',0)}/100"})
    except Exception as e:
        emit({"type":"error","msg":f"Bullet ranker error: {e}"})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SALARY NEGOTIATION BRIEF
# Real leverage. Real numbers. Real script.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def salary_brief(job_title, sector, seniority, location, resume, market_data, emit):
    emit({"type":"log","msg":"\n💰 SALARY NEGOTIATION INTELLIGENCE"})
    try:
        raw = gpt(
            "Expert salary negotiation strategist. Return ONLY valid JSON.",
            f"""Generate a complete salary negotiation brief.

Role: {job_title} | {sector} | {seniority}
Location: {location or "United States"}
Market salary data: {str(market_data.get("salaryByLocation", []))[:500]}
Salary premium skills: {str(market_data.get("salary_skills", []))[:400]}

Resume summary:
{resume[:1500]}

Return ONLY JSON:
{{
  "target_salary": "$118,000",
  "minimum_acceptable": "$98,000",
  "opening_ask": "$128,000",
  "rationale": "why you deserve this number specifically",
  "your_leverage": ["specific leverage point 1", "leverage 2"],
  "market_evidence": ["data point supporting your ask"],
  "premium_skills_value": ["skill X adds $Y based on market data"],
  "negotiation_script": {{
    "opening_line": "exact words to say when they give you the number",
    "counter_script": "exact counter-offer language",
    "if_they_push_back": "exact response to pushback",
    "closing_line": "how to seal the deal"
  }},
  "red_flags": ["things that suggest this company lowballs"],
  "equity_considerations": "how to think about equity vs cash here",
  "timing_advice": "when and how to bring up compensation",
  "benefits_to_negotiate": ["PTO", "remote flexibility", "signing bonus"]
}}""",
            max_tokens=2000, temp=0.3
        )
        result = jparse(raw)
        emit({"type":"negotiate_data","data":result})
        emit({"type":"done","msg":f"Negotiation brief ready — target: {result.get('target_salary','—')}"})
    except Exception as e:
        emit({"type":"error","msg":f"Negotiation error: {e}"})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SKILLS BRIDGE — Career Change Intelligence
# "You said patient triage. Employers hear incident prioritization."
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def skills_bridge(from_role, to_role, resume, target_sector, emit):
    emit({"type":"log","msg":f"\n🌉 SKILLS BRIDGE: {from_role} → {to_role}"})
    try:
        raw = gpt(
            "Expert career transition strategist. Return ONLY valid JSON.",
            f"""Build a transferable skills bridge for this career transition.

FROM: {from_role}
TO: {to_role} in {target_sector}

RESUME:
{resume[:2000]}

Map every skill from the old role into the language of the new role.

Return ONLY JSON:
{{
  "transition_score": 72,
  "transition_verdict": "Strong transferable base — here is what translates",
  "skill_translations": [
    {{
      "old_language": "patient triage and prioritization",
      "new_language": "incident prioritization and escalation protocols",
      "value": "high",
      "where_to_use": "Skills section and first Experience bullet"
    }}
  ],
  "hidden_strengths": ["unexpected strength that gives you edge in new field"],
  "experience_reframes": [
    {{
      "original_bullet": "exact bullet from resume",
      "reframed_bullet": "same experience in new field language",
      "why": "explanation of the translation"
    }}
  ],
  "gaps_to_address": ["skill needed in new role not present"],
  "quick_wins": ["fastest path to plug the gaps"],
  "narrative": "2-paragraph career transition story for your summary section",
  "interview_bridge_answers": [
    {{
      "question": "why are you changing careers?",
      "answer": "compelling bridge answer"
    }}
  ]
}}""",
            max_tokens=2500, temp=0.4
        )
        result = jparse(raw)
        emit({"type":"bridge_data","data":result})
        emit({"type":"done","msg":f"Skills bridge built — {result.get('transition_score',0)}% transferable"})
    except Exception as e:
        emit({"type":"error","msg":f"Skills bridge error: {e}"})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FOLLOW-UP EMAIL GENERATOR
# Timed, specific, impossible to ignore
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def followup_generator(company, role, days_since_apply, resume_summary, emit):
    emit({"type":"log","msg":f"\n📬 FOLLOW-UP GENERATOR — {company}"})
    try:
        raw = gpt(
            "Expert job search strategist. Return ONLY valid JSON.",
            f"""Generate strategic follow-up emails for a job application.

Company: {company}
Role: {role}
Days since applying: {days_since_apply}
Candidate summary: {resume_summary[:800]}

Return ONLY JSON:
{{
  "week_1_email": {{
    "subject": "compelling subject line",
    "body": "brief, specific follow-up email — 3 paragraphs max",
    "send_time": "best day and time to send"
  }},
  "week_2_email": {{
    "subject": "subject line",
    "body": "second follow-up if no response",
    "send_time": "best timing"
  }},
  "linkedin_note": "connection request message to hiring manager — 300 chars",
  "value_add": "specific thing you could offer/share that adds value before they respond",
  "when_to_give_up": "realistic timeline before moving on",
  "personalization_tips": ["research angle 1", "hook idea 2"]
}}""",
            max_tokens=1500, temp=0.4
        )
        result = jparse(raw)
        emit({"type":"followup_data","data":result,"company":company})
        emit({"type":"done","msg":f"Follow-up sequence generated for {company}"})
    except Exception as e:
        emit({"type":"error","msg":f"Follow-up error: {e}"})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RESUME PARSER + PDF TEMPLATE ENGINE (6 templates)
# Pure stdlib. Browser print-to-PDF. ATS-friendly.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def parse_resume_struct(resume_text):
    '''Use GPT to extract structured fields from raw resume text.'''
    try:
        raw = gpt(
            'You are a resume parser. Extract structured data. Return ONLY valid JSON.',
            f'''Parse this resume into structured fields. Use exact text from the resume. Preserve everything — nothing on the resume may be dropped.

Rules:
- "name" keeps post-nominal credentials exactly as written (e.g. "Jane Doe, PT" or "John Smith, CPA, MBA").
- "authorization" captures any work-status line: "U.S. Citizen", "Authorized to work without sponsorship", "Green Card", visa status. Empty if absent.
- education "year" keeps the full range if given ("2014 – 2018"), not just the end year.
- "certifications" includes every license, certification, registration, and clearance — one entry each, exact wording.
- "languages" keeps proficiency notes if present.
- Any section that fits none of the fields goes into "additional" as {{"header": "...", "lines": [...]}} — never discarded.

RESUME:
{resume_text[:9000]}

Return ONLY this JSON (use empty string/array if missing):
{{
  "name": "Full Name, Credentials",
  "title": "Current job title or target role",
  "authorization": "U.S. Citizen — authorized to work without sponsorship",
  "email": "email@example.com",
  "phone": "+1 ...",
  "location": "City, State",
  "linkedin": "linkedin.com/in/...",
  "website": "github.com/... or portfolio url",
  "summary": "2-4 sentence professional summary",
  "experience": [
    {{
      "title": "Job Title",
      "company": "Company Name",
      "location": "City, ST",
      "start": "Jan 2022",
      "end": "Present",
      "bullets": ["achievement 1", "bullet 2", "bullet 3"]
    }}
  ],
  "education": [
    {{"degree":"BS Computer Science","school":"University","location":"City, State, Country","year":"2016 – 2020","gpa":""}}
  ],
  "skills": {{
    "technical": ["Python","React","AWS"],
    "tools": ["Git","Docker","Jira"],
    "soft": ["Leadership","Communication"]
  }},
  "certifications": [{{"name":"AWS SA","issuer":"Amazon","year":"2023"}}],
  "projects": [{{"name":"Project","description":"brief","tech":["t1","t2"]}}],
  "languages": ["English (native)", "Spanish (professional)"],
  "awards": ["Award 1"],
  "additional": [{{"header":"PUBLICATIONS","lines":["line 1","line 2"]}}]
}}''',
            max_tokens=3200, temp=0.1
        )
        return jparse(raw)
    except Exception as e:
        print(f'  Parse error: {e}')
        return {}


def _esc(s):
    if s is None: return ''
    return html_lib.escape(str(s))


def _render_modern(d):
    name  = _esc(d.get('name','Your Name'))
    title = _esc(d.get('title','Professional Title'))
    contact = ' &nbsp;·&nbsp; '.join(filter(None, [_esc(d.get('email','')), _esc(d.get('phone','')), _esc(d.get('location','')), _esc(d.get('linkedin','')), _esc(d.get('website',''))]))
    exp_html = ''
    for e in d.get('experience', []):
        bullets = ''.join(f'<li>{_esc(b)}</li>' for b in e.get('bullets', []))
        exp_html += '<div class="exp-item"><div class="exp-row"><div class="exp-left"><strong>%s</strong> · %s</div><div class="exp-right">%s – %s</div></div><div class="exp-loc">%s</div><ul>%s</ul></div>' % (_esc(e.get('title','')), _esc(e.get('company','')), _esc(e.get('start','')), _esc(e.get('end','')), _esc(e.get('location','')), bullets)
    edu_html = ''
    for ed in d.get('education', []):
        edu_html += '<div class="edu-item"><strong>%s</strong> · %s <span class="edu-year">%s</span></div>' % (_esc(ed.get('degree','')), _esc(ed.get('school','')), _esc(ed.get('year','')))
    skills = d.get('skills', {}) if isinstance(d.get('skills'), dict) else {}
    sk_tech = ', '.join(_esc(s) for s in skills.get('technical', []))
    sk_tools = ', '.join(_esc(s) for s in skills.get('tools', []))
    sk_soft = ', '.join(_esc(s) for s in skills.get('soft', []))
    certs = ''.join('<li>%s · %s %s</li>' % (_esc(c.get('name','')), _esc(c.get('issuer','')), _esc(c.get('year',''))) for c in d.get('certifications', []))
    cert_block = '<h2>Certifications</h2><ul>' + certs + '</ul>' if certs else ''
    summary = _esc(d.get('summary',''))
    return '''<!doctype html><html><head><meta charset="utf-8"><title>__NAME__ — Resume</title>
<style>
  @page { size: Letter; margin: 0.5in; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Calibri','Helvetica Neue',Arial,sans-serif; color: #1a1a1a; font-size: 10.5pt; line-height: 1.45; }
  .header { border-left: 5px solid #2563eb; padding: 4px 0 8px 14px; margin-bottom: 14px; }
  h1 { font-size: 26pt; font-weight: 700; letter-spacing: -0.5px; color: #0a0a0a; }
  .title { font-size: 12pt; color: #2563eb; font-weight: 600; margin-top: 2px; }
  .contact { font-size: 9.5pt; color: #4a4a4a; margin-top: 6px; }
  h2 { font-size: 11pt; text-transform: uppercase; letter-spacing: 1.5px; color: #2563eb; border-bottom: 1.5px solid #e5e7eb; padding-bottom: 4px; margin: 14px 0 8px; font-weight: 700; }
  .summary { font-size: 10pt; color: #2a2a2a; margin-bottom: 8px; }
  .exp-item { margin-bottom: 10px; page-break-inside: avoid; }
  .exp-row { display: flex; justify-content: space-between; align-items: baseline; }
  .exp-right { font-size: 9.5pt; color: #6a6a6a; }
  .exp-loc { font-size: 9.5pt; color: #6a6a6a; font-style: italic; margin-bottom: 4px; }
  ul { margin-left: 16px; }
  li { margin-bottom: 2px; font-size: 10pt; }
  .skills-grid { display: grid; grid-template-columns: 110px 1fr; gap: 4px 12px; font-size: 10pt; }
  .skills-label { font-weight: 700; color: #2563eb; }
  .edu-item { margin-bottom: 4px; font-size: 10pt; }
  .edu-year { float: right; color: #6a6a6a; }
</style></head><body>
<div class="header"><h1>__NAME__</h1><div class="title">__TITLE__</div><div class="contact">__CONTACT__</div></div>
<h2>Professional Summary</h2><p class="summary">__SUMMARY__</p>
<h2>Experience</h2>__EXP__
<h2>Education</h2>__EDU__
<h2>Skills</h2>
<div class="skills-grid">
  <div class="skills-label">Technical</div><div>__SKTECH__</div>
  <div class="skills-label">Tools</div><div>__SKTOOLS__</div>
  <div class="skills-label">Soft</div><div>__SKSOFT__</div>
</div>
__CERTS__
</body></html>'''.replace('__NAME__', name).replace('__TITLE__', title).replace('__CONTACT__', contact).replace('__SUMMARY__', summary).replace('__EXP__', exp_html).replace('__EDU__', edu_html).replace('__SKTECH__', sk_tech).replace('__SKTOOLS__', sk_tools).replace('__SKSOFT__', sk_soft).replace('__CERTS__', cert_block)


def _render_classic(d):
    name  = _esc(d.get('name','Your Name'))
    contact = ' | '.join(filter(None, [_esc(d.get('email','')), _esc(d.get('phone','')), _esc(d.get('location','')), _esc(d.get('linkedin',''))]))
    exp_html = ''
    for e in d.get('experience', []):
        bullets = ''.join(f'<li>{_esc(b)}</li>' for b in e.get('bullets', []))
        exp_html += '<div class="exp"><div class="row"><strong>%s</strong>, %s<span class="r">%s – %s</span></div><div class="title-line"><em>%s</em></div><ul>%s</ul></div>' % (_esc(e.get('company','')), _esc(e.get('location','')), _esc(e.get('start','')), _esc(e.get('end','')), _esc(e.get('title','')), bullets)
    edu_html = ''
    for ed in d.get('education', []):
        edu_html += '<div class="edu"><strong>%s</strong>, %s — %s <span class="r">%s</span></div>' % (_esc(ed.get('school','')), _esc(ed.get('location','')), _esc(ed.get('degree','')), _esc(ed.get('year','')))
    skills = d.get('skills', {}) if isinstance(d.get('skills'), dict) else {}
    all_sk = []
    for k in ('technical','tools','soft'):
        all_sk.extend(skills.get(k, []))
    sk_html = ' • '.join(_esc(s) for s in all_sk)
    certs = ''.join('<li>%s, %s (%s)</li>' % (_esc(c.get('name','')), _esc(c.get('issuer','')), _esc(c.get('year',''))) for c in d.get('certifications', []))
    cert_block = '<h2>Certifications</h2><ul>' + certs + '</ul>' if certs else ''
    return '''<!doctype html><html><head><meta charset="utf-8"><title>__NAME__ — Resume</title>
<style>
  @page { size: Letter; margin: 0.6in; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Times New Roman',Times,serif; color: #000; font-size: 11pt; line-height: 1.4; }
  .header { text-align: center; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1.5px solid #000; }
  h1 { font-size: 22pt; font-weight: 700; letter-spacing: 1px; }
  .contact { font-size: 10pt; margin-top: 4px; }
  h2 { font-size: 12pt; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #000; padding-bottom: 2px; margin: 12px 0 6px; }
  .summary { margin-bottom: 6px; text-align: justify; }
  .exp { margin-bottom: 8px; page-break-inside: avoid; }
  .row { font-size: 11pt; }
  .r { float: right; font-weight: normal; font-style: normal; }
  .title-line { font-size: 10.5pt; margin-bottom: 3px; }
  ul { margin-left: 18px; }
  li { margin-bottom: 2px; }
  .edu { margin-bottom: 4px; }
  .skills-line { font-size: 10.5pt; }
</style></head><body>
<div class="header"><h1>__NAME__</h1><div class="contact">__CONTACT__</div></div>
<h2>Professional Summary</h2><p class="summary">__SUMMARY__</p>
<h2>Professional Experience</h2>__EXP__
<h2>Education</h2>__EDU__
<h2>Skills</h2><p class="skills-line">__SK__</p>
__CERTS__
</body></html>'''.replace('__NAME__', name).replace('__CONTACT__', contact).replace('__SUMMARY__', _esc(d.get('summary',''))).replace('__EXP__', exp_html).replace('__EDU__', edu_html).replace('__SK__', sk_html).replace('__CERTS__', cert_block)


def _render_tech(d):
    name  = _esc(d.get('name','Your Name'))
    title = _esc(d.get('title','Software Engineer'))
    contact = ' &nbsp;·&nbsp; '.join(filter(None, [_esc(d.get('email','')), _esc(d.get('phone','')), _esc(d.get('location','')), _esc(d.get('linkedin','')), _esc(d.get('website',''))]))
    exp_html = ''
    for e in d.get('experience', []):
        bullets = ''.join(f'<li>{_esc(b)}</li>' for b in e.get('bullets', []))
        exp_html += '<div class="exp"><div class="row"><span class="mono">▸</span> <strong>%s</strong> @ <span class="co">%s</span><span class="r">%s – %s</span></div><ul>%s</ul></div>' % (_esc(e.get('title','')), _esc(e.get('company','')), _esc(e.get('start','')), _esc(e.get('end','')), bullets)
    skills = d.get('skills', {}) if isinstance(d.get('skills'), dict) else {}
    sk_tech = ' '.join('<span class="chip">%s</span>' % _esc(s) for s in skills.get('technical', []))
    sk_tools = ' '.join('<span class="chip">%s</span>' % _esc(s) for s in skills.get('tools', []))
    proj_html = ''
    for p in d.get('projects', []):
        tech = ', '.join(_esc(t) for t in p.get('tech', []))
        proj_html += '<div class="proj"><strong>%s</strong> <span class="mono">[%s]</span><div>%s</div></div>' % (_esc(p.get('name','')), tech, _esc(p.get('description','')))
    edu_html = ''
    for ed in d.get('education', []):
        edu_html += '<div class="edu">%s · %s <span class="r">%s</span></div>' % (_esc(ed.get('degree','')), _esc(ed.get('school','')), _esc(ed.get('year','')))
    proj_block = '<h2>Projects</h2>' + proj_html if proj_html else ''
    tools_block = '<h2>Tools</h2><div>' + sk_tools + '</div>' if sk_tools else ''
    return '''<!doctype html><html><head><meta charset="utf-8"><title>__NAME__ — Resume</title>
<style>
  @page { size: Letter; margin: 0.5in; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Inter','Helvetica Neue',Arial,sans-serif; color: #0f172a; font-size: 10.5pt; line-height: 1.45; }
  .mono { font-family: 'JetBrains Mono','Consolas',monospace; color: #6366f1; }
  h1 { font-size: 24pt; font-weight: 800; letter-spacing: -0.5px; }
  .title { font-family: monospace; color: #6366f1; font-size: 11pt; margin-top: 2px; }
  .contact { font-size: 9.5pt; color: #475569; margin-top: 4px; }
  .header { margin-bottom: 12px; padding-bottom: 10px; border-bottom: 2px dashed #e2e8f0; }
  h2 { font-size: 10.5pt; text-transform: uppercase; letter-spacing: 2px; color: #6366f1; margin: 12px 0 6px; font-weight: 700; }
  h2::before { content: "// "; color: #94a3b8; }
  .summary { font-size: 10pt; }
  .exp { margin-bottom: 8px; page-break-inside: avoid; }
  .row { font-size: 10.5pt; }
  .co { color: #6366f1; font-weight: 600; }
  .r { float: right; font-family: monospace; font-size: 9.5pt; color: #64748b; }
  ul { margin-left: 18px; }
  li { margin-bottom: 2px; font-size: 10pt; }
  .chip { display: inline-block; background: #eef2ff; color: #4338ca; font-size: 9pt; padding: 2px 8px; border-radius: 3px; margin: 2px 3px 2px 0; font-family: monospace; }
  .proj { margin-bottom: 6px; font-size: 10pt; }
  .edu { font-size: 10pt; }
</style></head><body>
<div class="header"><h1>__NAME__</h1><div class="title">&gt; __TITLE__</div><div class="contact">__CONTACT__</div></div>
<h2>About</h2><p class="summary">__SUMMARY__</p>
<h2>Experience</h2>__EXP__
__PROJ__
<h2>Tech Stack</h2><div>__SKTECH__</div>
__TOOLS__
<h2>Education</h2>__EDU__
</body></html>'''.replace('__NAME__', name).replace('__TITLE__', title).replace('__CONTACT__', contact).replace('__SUMMARY__', _esc(d.get('summary',''))).replace('__EXP__', exp_html).replace('__PROJ__', proj_block).replace('__SKTECH__', sk_tech).replace('__TOOLS__', tools_block).replace('__EDU__', edu_html)


def _render_executive(d):
    name  = _esc(d.get('name','Your Name')).upper()
    title = _esc(d.get('title','Executive Title'))
    contact = ' • '.join(filter(None, [_esc(d.get('email','')), _esc(d.get('phone','')), _esc(d.get('location','')), _esc(d.get('linkedin',''))]))
    exp_html = ''
    for e in d.get('experience', []):
        bullets = ''.join(f'<li>{_esc(b)}</li>' for b in e.get('bullets', []))
        exp_html += '<div class="exp"><div class="row"><strong class="big">%s</strong></div><div class="company">%s | %s <span class="r">%s – %s</span></div><ul>%s</ul></div>' % (_esc(e.get('title','')), _esc(e.get('company','')), _esc(e.get('location','')), _esc(e.get('start','')), _esc(e.get('end','')), bullets)
    edu_html = ''
    for ed in d.get('education', []):
        edu_html += '<div class="edu"><strong>%s</strong>, %s <span class="r">%s</span></div>' % (_esc(ed.get('degree','')), _esc(ed.get('school','')), _esc(ed.get('year','')))
    skills = d.get('skills', {}) if isinstance(d.get('skills'), dict) else {}
    all_sk = skills.get('technical', []) + skills.get('soft', [])
    sk_html = ' &nbsp;|&nbsp; '.join(_esc(s) for s in all_sk)
    return '''<!doctype html><html><head><meta charset="utf-8"><title>__NAME__ — Resume</title>
<style>
  @page { size: Letter; margin: 0.6in; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Georgia','Cambria',serif; color: #1a1a1a; font-size: 10.5pt; line-height: 1.5; }
  .header { text-align: center; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 3px double #1a1a1a; }
  h1 { font-size: 28pt; font-weight: 700; letter-spacing: 4px; }
  .title { font-size: 12pt; color: #555; margin-top: 4px; font-style: italic; letter-spacing: 2px; text-transform: uppercase; }
  .contact { font-size: 10pt; margin-top: 6px; color: #444; }
  h2 { font-size: 12pt; text-align: center; text-transform: uppercase; letter-spacing: 3px; margin: 14px 0 8px; font-weight: 700; border-top: 1px solid #999; border-bottom: 1px solid #999; padding: 4px 0; }
  .summary { font-size: 11pt; text-align: justify; font-style: italic; margin-bottom: 8px; }
  .exp { margin-bottom: 10px; page-break-inside: avoid; }
  .big { font-size: 12pt; }
  .company { font-size: 10.5pt; color: #555; margin-bottom: 4px; }
  .r { float: right; font-style: italic; font-size: 10pt; }
  ul { margin-left: 22px; }
  li { margin-bottom: 3px; }
  .skills-line { text-align: center; font-size: 10.5pt; }
  .edu { margin-bottom: 4px; }
</style></head><body>
<div class="header"><h1>__NAME__</h1><div class="title">__TITLE__</div><div class="contact">__CONTACT__</div></div>
<h2>Executive Summary</h2><p class="summary">__SUMMARY__</p>
<h2>Leadership Experience</h2>__EXP__
<h2>Core Competencies</h2><p class="skills-line">__SK__</p>
<h2>Education</h2>__EDU__
</body></html>'''.replace('__NAME__', name).replace('__TITLE__', title).replace('__CONTACT__', contact).replace('__SUMMARY__', _esc(d.get('summary',''))).replace('__EXP__', exp_html).replace('__SK__', sk_html).replace('__EDU__', edu_html)


def _render_creative(d):
    name  = _esc(d.get('name','Your Name'))
    title = _esc(d.get('title','Creative Professional'))
    contact = '<br>'.join(filter(None, [_esc(d.get('email','')), _esc(d.get('phone','')), _esc(d.get('location','')), _esc(d.get('linkedin','')), _esc(d.get('website',''))]))
    exp_html = ''
    for e in d.get('experience', []):
        bullets = ''.join(f'<li>{_esc(b)}</li>' for b in e.get('bullets', []))
        exp_html += '<div class="exp"><div class="dot"></div><div class="exp-content"><div class="exp-title">%s</div><div class="exp-meta">%s · %s · <span class="dt">%s – %s</span></div><ul>%s</ul></div></div>' % (_esc(e.get('title','')), _esc(e.get('company','')), _esc(e.get('location','')), _esc(e.get('start','')), _esc(e.get('end','')), bullets)
    skills = d.get('skills', {}) if isinstance(d.get('skills'), dict) else {}
    sk_html = ''.join('<span class="tag">%s</span>' % _esc(s) for s in skills.get('technical', []) + skills.get('tools', []))
    edu_html = ''
    for ed in d.get('education', []):
        edu_html += '<div class="edu"><strong>%s</strong><br>%s · %s</div>' % (_esc(ed.get('degree','')), _esc(ed.get('school','')), _esc(ed.get('year','')))
    return '''<!doctype html><html><head><meta charset="utf-8"><title>__NAME__ — Resume</title>
<style>
  @page { size: Letter; margin: 0; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Helvetica Neue',Arial,sans-serif; color: #1a1a1a; font-size: 10.5pt; line-height: 1.45; }
  .layout { display: grid; grid-template-columns: 220px 1fr; min-height: 100vh; }
  .sidebar { background: #ec4899; color: #fff; padding: 32px 22px; }
  .sidebar h1 { font-size: 22pt; font-weight: 800; line-height: 1.05; letter-spacing: -0.5px; }
  .sidebar .title { font-size: 11pt; margin-top: 6px; opacity: 0.9; font-weight: 500; }
  .sidebar .contact { font-size: 9pt; margin-top: 14px; line-height: 1.6; word-break: break-word; }
  .sidebar h3 { font-size: 9.5pt; text-transform: uppercase; letter-spacing: 2px; margin: 18px 0 6px; opacity: 0.9; }
  .sidebar .tag { display: inline-block; background: rgba(255,255,255,0.18); padding: 3px 8px; border-radius: 10px; font-size: 8.5pt; margin: 2px 3px 2px 0; }
  .sidebar .edu { font-size: 9pt; margin-bottom: 8px; line-height: 1.4; }
  .main { padding: 32px 28px; }
  h2 { font-size: 12pt; text-transform: uppercase; letter-spacing: 2px; color: #ec4899; margin: 14px 0 10px; font-weight: 700; }
  h2:first-child { margin-top: 0; }
  .summary { font-size: 10.5pt; margin-bottom: 8px; }
  .exp { display: flex; gap: 10px; margin-bottom: 12px; page-break-inside: avoid; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: #ec4899; margin-top: 6px; flex-shrink: 0; }
  .exp-content { flex: 1; }
  .exp-title { font-size: 11pt; font-weight: 700; }
  .exp-meta { font-size: 9.5pt; color: #666; margin: 1px 0 4px; }
  .dt { color: #ec4899; font-weight: 600; }
  ul { margin-left: 16px; }
  li { margin-bottom: 2px; font-size: 10pt; }
</style></head><body>
<div class="layout">
  <aside class="sidebar"><h1>__NAME__</h1><div class="title">__TITLE__</div><div class="contact">__CONTACT__</div><h3>Skills</h3><div>__SK__</div><h3>Education</h3>__EDU__</aside>
  <main class="main"><h2>About</h2><p class="summary">__SUMMARY__</p><h2>Experience</h2>__EXP__</main>
</div></body></html>'''.replace('__NAME__', name).replace('__TITLE__', title).replace('__CONTACT__', contact).replace('__SUMMARY__', _esc(d.get('summary',''))).replace('__EXP__', exp_html).replace('__SK__', sk_html).replace('__EDU__', edu_html)


def _render_minimal(d):
    name  = _esc(d.get('name','Your Name'))
    title = _esc(d.get('title',''))
    contact = '  ·  '.join(filter(None, [_esc(d.get('email','')), _esc(d.get('phone','')), _esc(d.get('location','')), _esc(d.get('linkedin',''))]))
    exp_html = ''
    for e in d.get('experience', []):
        bullets = ''.join(f'<li>{_esc(b)}</li>' for b in e.get('bullets', []))
        exp_html += '<div class="exp"><div class="left"><div class="dt">%s<br>%s</div></div><div class="right"><div class="t">%s</div><div class="c">%s · %s</div><ul>%s</ul></div></div>' % (_esc(e.get('start','')), _esc(e.get('end','')), _esc(e.get('title','')), _esc(e.get('company','')), _esc(e.get('location','')), bullets)
    skills = d.get('skills', {}) if isinstance(d.get('skills'), dict) else {}
    all_sk = skills.get('technical', []) + skills.get('tools', []) + skills.get('soft', [])
    sk_html = '  ·  '.join(_esc(s) for s in all_sk)
    edu_html = ''
    for ed in d.get('education', []):
        edu_html += '<div class="edu"><div class="dt">%s</div><div>%s · %s</div></div>' % (_esc(ed.get('year','')), _esc(ed.get('degree','')), _esc(ed.get('school','')))
    title_block = '<div class="title">' + title + '</div>' if title else ''
    return '''<!doctype html><html><head><meta charset="utf-8"><title>__NAME__ — Resume</title>
<style>
  @page { size: Letter; margin: 0.7in; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Helvetica Neue',Arial,sans-serif; color: #2a2a2a; font-size: 10pt; line-height: 1.6; font-weight: 300; }
  .header { margin-bottom: 28px; }
  h1 { font-size: 32pt; font-weight: 200; letter-spacing: -1px; }
  .title { font-size: 11pt; color: #888; margin-top: 4px; font-weight: 400; letter-spacing: 1px; text-transform: uppercase; }
  .contact { font-size: 9.5pt; color: #888; margin-top: 14px; }
  h2 { font-size: 9pt; text-transform: uppercase; letter-spacing: 3px; color: #888; margin: 22px 0 12px; font-weight: 400; }
  .summary { font-size: 11pt; color: #444; max-width: 580px; }
  .exp, .edu { display: grid; grid-template-columns: 100px 1fr; gap: 18px; margin-bottom: 14px; page-break-inside: avoid; }
  .left .dt { font-size: 9pt; color: #888; }
  .t { font-size: 11pt; font-weight: 500; color: #1a1a1a; }
  .c { font-size: 10pt; color: #888; margin-bottom: 4px; }
  ul { margin-left: 14px; }
  li { margin-bottom: 2px; font-size: 10pt; color: #444; font-weight: 300; }
  .skills { font-size: 10.5pt; color: #444; }
</style></head><body>
<div class="header"><h1>__NAME__</h1>__TITLEBLOCK__<div class="contact">__CONTACT__</div></div>
<h2>About</h2><p class="summary">__SUMMARY__</p>
<h2>Experience</h2>__EXP__
<h2>Education</h2>__EDU__
<h2>Skills</h2><p class="skills">__SK__</p>
</body></html>'''.replace('__NAME__', name).replace('__TITLEBLOCK__', title_block).replace('__CONTACT__', contact).replace('__SUMMARY__', _esc(d.get('summary',''))).replace('__EXP__', exp_html).replace('__EDU__', edu_html).replace('__SK__', sk_html)


TEMPLATES = {
    'modern':    {'name': 'Modern Professional', 'desc': 'Clean, ATS-friendly, blue accent. Universal best choice.', 'render': _render_modern},
    'classic':   {'name': 'Classic ATS',         'desc': 'Traditional Times New Roman. Highest ATS pass rate.',     'render': _render_classic},
    'tech':      {'name': 'Tech / Developer',    'desc': 'Mono accents, project-forward. Built for engineers.',    'render': _render_tech},
    'executive': {'name': 'Executive',           'desc': 'Bold serif, leadership-forward. Director+ roles.',        'render': _render_executive},
    'creative':  {'name': 'Creative',            'desc': 'Magazine layout, pink accent. Designers & marketers.',   'render': _render_creative},
    'minimal':   {'name': 'Minimalist',          'desc': 'Ultra-clean, generous whitespace, premium feel.',         'render': _render_minimal},
}


def render_template(template_id, struct):
    tpl = TEMPLATES.get(template_id) or TEMPLATES['modern']
    return tpl['render'](struct or {})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# JOB ALERTS — SMTP via Gmail. Persistent subscriptions.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import smtplib, hashlib, os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

ALERTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'alerts.json')
ALERTS_LOCK = threading.Lock()

def _load_alerts():
    if not os.path.exists(ALERTS_FILE): return {'subscriptions': [], 'sent': {}}
    try:
        with open(ALERTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'subscriptions': [], 'sent': {}}

def _save_alerts(data):
    try:
        with open(ALERTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f'[alerts] save error: {e}')

def _load_smtp_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    try:
        cfg = json.load(open(config_path))
        return {
            'host': cfg.get('SMTP_HOST', 'smtp.gmail.com'),
            'port': int(cfg.get('SMTP_PORT', 587)),
            'user': cfg.get('SMTP_USER', '').strip(),
            'pass': cfg.get('SMTP_PASS', '').strip(),
            'from': cfg.get('SMTP_FROM', '').strip() or cfg.get('SMTP_USER', '').strip(),
        }
    except Exception:
        return {'host':'smtp.gmail.com','port':587,'user':'','pass':'','from':''}

def send_alert_email(to_email, subject, html_body):
    smtp = _load_smtp_config()
    if not smtp['user'] or not smtp['pass']:
        return False, 'SMTP not configured (set SMTP_USER + SMTP_PASS in config.json)'
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = smtp['from'] or smtp['user']
        msg['To']      = to_email
        msg.attach(MIMEText(html_body, 'html'))
        with smtplib.SMTP(smtp['host'], smtp['port'], timeout=30) as server:
            server.starttls()
            server.login(smtp['user'], smtp['pass'])
            server.sendmail(smtp['from'] or smtp['user'], [to_email], msg.as_string())
        return True, 'sent'
    except Exception as e:
        return False, str(e)

def add_alert_subscription(payload):
    with ALERTS_LOCK:
        data = _load_alerts()
        sub_id = hashlib.sha1(f"{payload.get('email','')}{payload.get('jobTitle','')}{time.time()}".encode()).hexdigest()[:12]
        sub = {
            'id': sub_id,
            'email': payload.get('email','').strip(),
            'jobTitle': payload.get('jobTitle','').strip(),
            'location': payload.get('location','').strip(),
            'sector': payload.get('sector','general'),
            'keywords': payload.get('keywords', []),
            'resumeSummary': (payload.get('resumeSummary','') or '')[:500],
            'frequency': payload.get('frequency','daily'),
            'created': int(time.time()),
            'last_run': 0,
            'active': True,
        }
        data['subscriptions'].append(sub)
        _save_alerts(data)
        return sub

def list_alerts(email=None):
    data = _load_alerts()
    subs = data.get('subscriptions', [])
    if email:
        subs = [s for s in subs if s.get('email','').lower() == email.lower()]
    return subs

def remove_alert(sub_id):
    with ALERTS_LOCK:
        data = _load_alerts()
        before = len(data['subscriptions'])
        data['subscriptions'] = [s for s in data['subscriptions'] if s.get('id') != sub_id]
        _save_alerts(data)
        return before > len(data['subscriptions'])

def _job_signature(job):
    return hashlib.sha1((job.get('title','') + '|' + job.get('company','') + '|' + job.get('url','')).encode()).hexdigest()[:16]

def _alert_job_row(job):
    title = _esc(job.get('title','Untitled'))
    company = _esc(job.get('company',''))
    location = _esc(job.get('location','Remote'))
    source = _esc(job.get('source',''))
    posted = _esc(job.get('posted',''))
    url = _esc(job.get('url','#'))
    salary = _esc(job.get('salary',''))
    snippet = _esc((job.get('snippet','') or '')[:160])
    salary_html = ('<div style="font-size:12px;color:#16a34a;margin-top:2px">'+salary+'</div>') if salary else ''
    snippet_html = ('<div style="font-size:12px;color:#64748b;margin-top:8px;line-height:1.5">'+snippet+'…</div>') if snippet else ''
    return ('<div style="border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin-bottom:10px">'
            '<div style="display:flex;justify-content:space-between;gap:12px">'
            '<div style="flex:1">'
            f'<a href="{url}" style="font-size:15px;font-weight:700;color:#0f172a;text-decoration:none">{title}</a>'
            f'<div style="font-size:13px;color:#475569;margin-top:2px">{company} · {location}</div>'
            f'{salary_html}'
            '</div>'
            f'<div style="font-size:11px;color:#94a3b8;text-align:right;flex-shrink:0">{source}<br>{posted}</div>'
            '</div>'
            f'{snippet_html}'
            f'<a href="{url}" style="display:inline-block;margin-top:10px;background:#4f8ef7;color:#fff;text-decoration:none;font-size:12px;padding:6px 14px;border-radius:8px;font-weight:600">View &amp; Apply →</a>'
            '</div>')

def alerts_scan_once():
    data = _load_alerts()
    now  = int(time.time())
    intervals = {'instant': 60*30, 'hourly': 60*60, 'daily': 60*60*24}
    sent_log = data.get('sent', {})
    changed = False
    for sub in data.get('subscriptions', []):
        if not sub.get('active', True): continue
        interval = intervals.get(sub.get('frequency','daily'), 86400)
        if now - sub.get('last_run', 0) < interval: continue
        try:
            query = sub.get('jobTitle','')
            loc = (sub.get('location','') or '').strip()
            result = fetch_structured_jobs(query, limit=40, location=loc)
            jobs = result['jobs'] if isinstance(result, dict) else result
            loc = (loc or (result.get('parsed_location','') if isinstance(result, dict) else '')).lower()
            sent_for_sub = set(sent_log.get(sub['id'], []))
            new_jobs = [j for j in jobs if _job_signature(j) not in sent_for_sub]
            if new_jobs:
                rows = ''.join(_alert_job_row(j) for j in new_jobs[:15])
                loc_label = ' near ' + _esc(loc).title() if loc else ''
                html = ('<!doctype html><html><body style="font-family:-apple-system,Arial,sans-serif;background:#f8fafc;padding:24px;color:#0f172a">'
                        '<div style="max-width:640px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,0.06)">'
                        '<div style="background:linear-gradient(135deg,#4f8ef7,#9b7cf4);padding:24px;color:#fff">'
                        '<div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;opacity:0.85">APEX Job Alerts</div>'
                        f'<h1 style="margin:6px 0 0;font-size:24px;font-weight:700">{len(new_jobs)} new {_esc(query)} jobs</h1>'
                        '</div><div style="padding:24px">'
                        f'<p style="margin:0 0 16px;color:#475569">Hi! Here are the latest matches for your <b>{_esc(query)}</b> alert{loc_label}:</p>'
                        f'{rows}'
                        '<p style="margin-top:24px;color:#94a3b8;font-size:12px;text-align:center">You\'re getting these because you subscribed to APEX job alerts.</p>'
                        '</div></div></body></html>')
                ok, msg = send_alert_email(sub['email'], f'[APEX] {len(new_jobs)} new {query} jobs', html)
                if ok:
                    sent_for_sub.update(_job_signature(j) for j in new_jobs)
                    sent_log[sub['id']] = list(sent_for_sub)[-200:]
                    sub['last_run'] = now
                    changed = True
                    print(f'[alerts] sent {len(new_jobs)} jobs to {sub["email"]}')
                else:
                    print(f'[alerts] send failed for {sub["email"]}: {msg}')
            else:
                sub['last_run'] = now
                changed = True
        except Exception as e:
            print(f'[alerts] sub {sub.get("id","?")} error: {e}')
    if changed:
        with ALERTS_LOCK:
            data['sent'] = sent_log
            _save_alerts(data)

def alerts_background_loop():
    while True:
        try:
            alerts_scan_once()
        except Exception as e:
            print(f'[alerts loop] {e}')
        time.sleep(60 * 15)


# ────────────────────────────────────────────────────────────────────────────
# v8.4 NEW AGENTS: standalone cover letter, Gmail inbox scan, audio transcribe
# ────────────────────────────────────────────────────────────────────────────

def standalone_cover_letter(job_title, company, posting, resume, sector="general"):
    """Tailored cover letter for a single job posting. Synchronous."""
    try:
        return gpt(
            "Expert cover letter writer for " + sector + " sector. Output ONLY the letter text — no subject line, no preamble.",
            "Write a compelling 3-paragraph cover letter for this exact role.\n\n" +
            "Role: " + job_title + "\n" +
            "Company: " + (company or "the hiring company") + "\n" +
            "Job posting:\n" + posting[:2500] + "\n\n" +
            "Candidate resume:\n" + resume[:2500] + "\n\n" +
            "Rules: 1) Hook (P1): pull a specific detail from the posting. " +
            "2) Value (P2): 2-3 quantified achievements that map to the posting needs. " +
            "3) CTA (P3): concrete next step. Inject keywords naturally. Output only the letter.",
            max_tokens=900, temp=0.5
        )
    except Exception as e:
        return "[cover letter error: " + str(e) + "]"


# ── Gmail inbox scanner via IMAP (uses Gmail App Password, no OAuth) ──
import imaplib, email as _email
from email.header import decode_header

def _decode_mime_header(h):
    if not h: return ""
    parts = decode_header(h)
    out = []
    for txt, enc in parts:
        if isinstance(txt, bytes):
            try: out.append(txt.decode(enc or "utf-8", errors="replace"))
            except: out.append(txt.decode("latin-1", errors="replace"))
        else:
            out.append(txt)
    return "".join(out)

def fetch_recent_emails(user, app_password, host="imap.gmail.com", port=993, days=30, limit=80):
    """Fetch recent inbox emails via IMAP."""
    out = []
    try:
        from datetime import datetime, timedelta
        M = imaplib.IMAP4_SSL(host, port, timeout=20)
        M.login(user, app_password)
        M.select("INBOX")
        since = (datetime.utcnow() - timedelta(days=days)).strftime("%d-%b-%Y")
        typ, data = M.search(None, "(SINCE " + since + ")")
        if typ != "OK": return []
        ids = data[0].split()[-limit:]
        for mid in reversed(ids):
            try:
                t, msg_data = M.fetch(mid, "(RFC822)")
                if t != "OK": continue
                msg = _email.message_from_bytes(msg_data[0][1])
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            try:
                                body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                                break
                            except: pass
                    if not body:
                        for part in msg.walk():
                            if part.get_content_type() == "text/html":
                                try:
                                    raw = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                                    body = clean(raw)
                                    break
                                except: pass
                else:
                    try: body = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="replace")
                    except: body = str(msg.get_payload())
                out.append({
                    "from": _decode_mime_header(msg.get("From","")),
                    "subject": _decode_mime_header(msg.get("Subject","")),
                    "date": _decode_mime_header(msg.get("Date",""))[:25],
                    "body": (body or "")[:1500],
                    "msg_id": mid.decode("ascii","replace"),
                })
            except Exception:
                continue
        try: M.logout()
        except: pass
    except Exception as e:
        print("[inbox] fetch error: " + str(e))
    return out

def classify_inbox_emails(emails):
    """GPT batch classification: applied/interview/offer/rejected/recruiter_outreach/not_relevant."""
    if not emails: return []
    items = []
    for i, e in enumerate(emails[:40]):
        items.append("#" + str(i) + ": FROM=" + e.get("from","")[:80] + " | SUBJECT=" + e.get("subject","")[:120] + " | BODY=" + e.get("body","")[:300])
    batch = "\n---\n".join(items)
    try:
        raw = gpt(
            "You classify recruiter and job-search emails. Return ONLY valid JSON.",
            "Classify each email by job-search relevance. For each output: id, status (one of: applied, interview_invite, interview_followup, offer, rejected, recruiter_outreach, ghosted, not_relevant), company (or empty), role (or empty), confidence 0-100.\n\nEMAILS:\n" + batch[:14000] + "\n\nReturn ONLY JSON: {\"classifications\": [{\"id\":0,\"status\":\"applied\",\"company\":\"Stripe\",\"role\":\"Senior Engineer\",\"confidence\":85}]}",
            max_tokens=2200, temp=0.1
        )
        return jparse(raw).get("classifications", [])
    except Exception as e:
        return [{"id": i, "status": "not_relevant", "company": "", "role": "", "confidence": 0} for i in range(len(emails))]


# ── Whisper audio transcription ──
def transcribe_audio_bytes(audio_bytes, mime="audio/webm"):
    """Send audio to OpenAI Whisper. Returns transcript text or error string."""
    if not audio_bytes: return ""
    boundary = "----APEXBoundary" + str(int(time.time()))
    parts = []
    parts.append(("--" + boundary).encode())
    parts.append(b"Content-Disposition: form-data; name=\"model\"")
    parts.append(b"")
    parts.append(b"whisper-1")
    parts.append(("--" + boundary).encode())
    ext = "webm" if "webm" in mime else "mp3" if "mp3" in mime else "wav"
    parts.append(("Content-Disposition: form-data; name=\"file\"; filename=\"rec." + ext + "\"").encode())
    parts.append(("Content-Type: " + mime).encode())
    parts.append(b"")
    parts.append(audio_bytes)
    parts.append(("--" + boundary + "--").encode())
    parts.append(b"")
    payload = b"\r\n".join(parts)
    req = Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=payload,
        headers={"Authorization": "Bearer " + OPENAI_KEY, "Content-Type": "multipart/form-data; boundary=" + boundary},
        method="POST",
    )
    try:
        with urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
            return data.get("text", "")
    except HTTPError as e:
        return "[transcribe error " + str(e.code) + ": " + str(e.reason) + "]"
    except Exception as e:
        return "[transcribe error: " + str(e) + "]"



# ────────────────────────────────────────────────────────────────────────────
# v8.5 APPLY-ALL: merge every recommendation into a single final resume
# ────────────────────────────────────────────────────────────────────────────

def apply_all_recommendations(original_resume, optimized_resume, changes, bullet_rewrites, added_keywords, sector="general", job_title=""):
    """One final GPT pass that merges every recommendation into ONE polished resume.
    Inputs: original + already-optimized + explicit before/after pairs + bullet rewrites + new keywords.
    Output: the final resume text with every specific change applied."""
    try:
        # Build a compact recommendations payload
        changes_str = ""
        for c in (changes or [])[:12]:
            b = (c.get("before","") or "")[:200]
            a = (c.get("after","") or "")[:240]
            if b and a:
                changes_str += "REPLACE: " + b + "\n   WITH:    " + a + "\n"
        rewrites_str = ""
        for r in (bullet_rewrites or [])[:15]:
            txt = (r.get("text","") or "")[:200]
            rw  = (r.get("rewrite","") or "")[:240]
            if txt and rw:
                rewrites_str += "WEAK:    " + txt + "\n   STRONG:  " + rw + "\n"
        kw_str = ", ".join((added_keywords or [])[:25])
        prompt = (
            "You are merging multiple resume recommendations into ONE final, polished resume. "
            "Start with the optimized version below, then apply every specific change listed. "
            "If a bullet appears in REPLACE list, swap it for the WITH version. "
            "If a bullet appears in WEAK list, swap it for the STRONG version. "
            "Ensure every keyword in the KEYWORDS list appears at least once where natural. "
            "Preserve dates, company names, titles exactly. NEVER fabricate experience.\n\n"
            "ROLE TARGET: " + (job_title or "—") + " in " + sector + "\n\n"
            "OPTIMIZED RESUME (start from this):\n" + (optimized_resume or original_resume)[:5000] + "\n\n"
            "SPECIFIC BEFORE/AFTER CHANGES TO APPLY:\n" + (changes_str or "(none)") + "\n\n"
            "BULLET REWRITES TO APPLY:\n" + (rewrites_str or "(none)") + "\n\n"
            "KEYWORDS TO ENSURE PRESENT: " + kw_str + "\n\n"
            "Output ONLY the final merged resume text. No commentary, no markdown headers, no preamble. "
            "Use the same section ordering as the optimized version. Keep formatting clean and ATS-friendly: "
            "Name on top, contact line, Summary, Experience (each role with bullets starting with strong action verbs), "
            "Education, Skills, Certifications."
        )
        return gpt(
            "You are an elite resume merge engine. Output ONLY the final resume text.",
            prompt,
            max_tokens=4000, temp=0.25
        )
    except Exception as e:
        return "[merge error: " + str(e) + "]\n\n" + (optimized_resume or original_resume or "")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HTTP SERVER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Handler(BaseHTTPRequestHandler):
    timeout          = 300
    protocol_version = 'HTTP/1.1'
    def log_message(self, *a): pass
    def setup(self):
        super().setup()
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.connection.setsockopt(socket.SOL_SOCKET,  socket.SO_KEEPALIVE, 1)
        except OSError: pass

    def cors(self):
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type')

    def do_OPTIONS(self):
        self.send_response(200); self.cors(); self.end_headers()

    def _send_json(self, code_, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code_); self.cors()
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers(); self.wfile.write(body)

    def _send_html(self, code_, html):
        body = html.encode('utf-8')
        self.send_response(code_); self.cors()
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        path = u.path
        qs = parse_qs(u.query or '')

        # ── STATIC FILES ──────────────────────────────────────────────────────
        # Serve index.html from the server so the page and the API share one
        # origin. Avoids file:// quirks (blocked extensions, null origin,
        # strict MIME on some asset loads) and makes the demo a single URL.
        if path == '/' or path == '/index.html':
            try:
                here = os.path.dirname(os.path.abspath(__file__))
                target = os.path.join(here, 'index.html')
                if not os.path.exists(target):
                    self._send_json(404, {'error': 'index.html not found beside agent_server.py'}); return
                with open(target, 'rb') as fh:
                    body = fh.read()
                self.send_response(200); self.cors()
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        # Any other static asset sitting next to the server (css, js, images).
        # Path is confined to the server directory — no traversal.
        if '.' in path.rsplit('/', 1)[-1] and not path.startswith('/api'):
            try:
                here = os.path.dirname(os.path.abspath(__file__))
                rel = path.lstrip('/').replace('\\', '/')
                target = os.path.normpath(os.path.join(here, rel))
                if not target.startswith(here) or not os.path.isfile(target):
                    self._send_json(404, {'error': 'not found'}); return
                if os.path.basename(target).lower() in ('config.json', 'agent_server.py'):
                    self._send_json(403, {'error': 'forbidden'}); return
                ctype = {
                    '.html':'text/html; charset=utf-8', '.css':'text/css; charset=utf-8',
                    '.js':'application/javascript; charset=utf-8', '.json':'application/json',
                    '.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg',
                    '.svg':'image/svg+xml', '.ico':'image/x-icon', '.woff2':'font/woff2',
                }.get(os.path.splitext(target)[1].lower(), 'application/octet-stream')
                with open(target, 'rb') as fh:
                    body = fh.read()
                self.send_response(200); self.cors()
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        if path == '/health':
            self._send_json(200, {'status':'ok','version':'10.0','jsearch':'active' if JSEARCH_KEY else 'inactive','sectors':list(SECTOR_SOURCES.keys()),'templates':list(TEMPLATES.keys())})
            return
        if path == '/config':
            smtp = _load_smtp_config()
            self._send_json(200, {'JSEARCH_KEY': JSEARCH_KEY or '', 'SMTP_CONFIGURED': bool(smtp['user'] and smtp['pass'])})
            return
        if path == '/templates':
            self._send_json(200, {'templates': [{'id':k,'name':v['name'],'desc':v['desc']} for k,v in TEMPLATES.items()]})
            return
        if path == '/live-jobs':
            q = (qs.get('q',[''])[0] or '').strip()
            location = (qs.get('location',[''])[0] or '').strip()
            limit = int(qs.get('limit',['40'])[0])
            if not q: self._send_json(400, {'error':'q required'}); return
            result = fetch_structured_jobs(q, limit=limit, location=location)
            jobs = result['jobs'] if isinstance(result, dict) else result
            parsed_loc = result.get('parsed_location','') if isinstance(result, dict) else location
            parsed_q = result.get('parsed_query', q) if isinstance(result, dict) else q
            # GET version doesn't accept resume (too long for URL); UI uses POST when scoring needed
            self._send_json(200, {'jobs': jobs, 'count': len(jobs), 'query': parsed_q, 'parsed_location': parsed_loc, 'requested_location': location})
            return
        if path == '/cities':
            # Top US metros for autocomplete; pre-formatted as "City, State"
            cities = []
            for city, st in US_CITY_STATE.items():
                cities.append(city.title() + ', ' + st)
            cities = sorted(set(cities))
            extras = ['Remote', 'Anywhere'] + sorted(set(s.upper() for s in US_STATE_ABBR))
            self._send_json(200, {'cities': cities, 'extras': extras})
            return
        if path == '/alerts/list':
            email = (qs.get('email',[''])[0] or '').strip()
            self._send_json(200, {'subscriptions': list_alerts(email if email else None)})
            return
        if path == '/render-resume':
            import base64
            tpl_id = qs.get('template',['modern'])[0]
            d_raw = qs.get('data',[''])[0]
            try:
                struct = json.loads(base64.urlsafe_b64decode(d_raw + '==').decode('utf-8')) if d_raw else {}
            except Exception:
                struct = {}
            self._send_html(200, render_template(tpl_id, struct))
            return
        self.send_response(404); self.end_headers()

    def _sse_start(self):
        """Send SSE response headers."""
        self.send_response(200)
        self.cors()
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()

    def _make_emitter(self):
        """Return a thread-safe SSE emit function."""
        alive = [True]
        def emit(ev):
            if not alive[0]:
                return
            try:
                data = json.dumps(ev, ensure_ascii=False)
                self.wfile.write(f'data: {data}\n\n'.encode('utf-8'))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                alive[0] = False
            except Exception as ex:
                print(f'[emit] {ex}')
        return emit

    def _read_json_body(self):
        """Read and parse JSON POST body."""
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length))

    def do_POST(self):
        # Read body — needed for all POST routes
        try:
            p = self._read_json_body()
        except Exception as e:
            self.send_response(400)
            self.cors()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': f'Bad JSON: {e}'}).encode())
            return

        path = self.path

        # ── JOB-SPECIFIC TAILORING ───────────────────────────────────────────
        if path == '/tailor':
            self._sse_start()
            emit = self._make_emitter()
            try:
                job_tailor(
                    p.get('jobPosting',''), p.get('resume',''),
                    p.get('jobTitle',''), p.get('sector','general'), emit
                )
            except Exception as e:
                try: emit({'type':'error','msg':str(e)})
                except: pass
            return

        # ── BULLET RANKER ─────────────────────────────────────────────────────
        if path == '/bullets':
            self._sse_start()
            emit = self._make_emitter()
            try:
                bullet_ranker(
                    p.get('resume',''), p.get('jobTitle',''),
                    p.get('sector','general'), p.get('keywords',[]), emit
                )
            except Exception as e:
                try: emit({'type':'error','msg':str(e)})
                except: pass
            return

        # ── SALARY NEGOTIATION ────────────────────────────────────────────────
        if path == '/negotiate':
            self._sse_start()
            emit = self._make_emitter()
            try:
                salary_brief(
                    p.get('jobTitle',''), p.get('sector','general'),
                    p.get('seniority','senior'), p.get('location',''),
                    p.get('resume',''), p.get('marketData',{}), emit
                )
            except Exception as e:
                try: emit({'type':'error','msg':str(e)})
                except: pass
            return

        # ── SKILLS BRIDGE ─────────────────────────────────────────────────────
        if path == '/bridge':
            self._sse_start()
            emit = self._make_emitter()
            try:
                skills_bridge(
                    p.get('fromRole',''), p.get('toRole',''),
                    p.get('resume',''), p.get('sector','general'), emit
                )
            except Exception as e:
                try: emit({'type':'error','msg':str(e)})
                except: pass
            return

        # ── FOLLOW-UP GENERATOR ───────────────────────────────────────────────
        if path == '/followup':
            self._sse_start()
            emit = self._make_emitter()
            try:
                followup_generator(
                    p.get('company',''), p.get('role',''),
                    p.get('daysSince',7), p.get('resumeSummary',''), emit
                )
            except Exception as e:
                try: emit({'type':'error','msg':str(e)})
                except: pass
            return

        # ── MAIN AGENT ROUTE ─────────────────────────────────────────────────
        if path == '/analyze':
            if not p.get('jobTitle') or not p.get('resume'):
                self.send_response(400)
                self.cors()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'jobTitle and resume required'}).encode())
                return

            self._sse_start()
            emit = self._make_emitter()
            try:
                agent_loop(
                    job_title = p.get('jobTitle', '').strip(),
                    industry  = p.get('industry',  'general').strip(),
                    seniority = p.get('seniority', 'senior').strip(),
                    job_desc  = p.get('jobDesc',   '').strip(),
                    resume    = p.get('resume',    '').strip(),
                    mode      = p.get('mode',      'optimize'),
                    emit      = emit,
                )
            except Exception as e:
                err = f'{type(e).__name__}: {e}'
                print(f'\n[AGENT ERROR] {err}')
                traceback.print_exc()
                try:
                    emit({'type': 'error', 'msg': err})
                except Exception:
                    pass
            return

        # ── DRIFT CHECK ──────────────────────────────────────────────────────
        if path == '/drift':
            self._sse_start()
            emit = self._make_emitter()
            try:
                drift_check(
                    p.get('jobTitle', ''),
                    p.get('sector',   'general'),
                    p.get('resume',   ''),
                    p.get('baselineScore', 50),
                    emit,
                )
            except Exception as e:
                try: emit({'type': 'error', 'msg': str(e)})
                except Exception: pass
            return

        # ── SMART MATCH ──────────────────────────────────────────────────────
        if path == '/match':
            self._sse_start()
            emit = self._make_emitter()
            try:
                smart_match(p.get('jobPosting', ''), p.get('resume', ''), emit)
            except Exception as e:
                try: emit({'type': 'error', 'msg': str(e)})
                except Exception: pass
            return

        # ── WEAKNESS X-RAY ───────────────────────────────────────────────────
        if path == '/xray':
            self._sse_start()
            emit = self._make_emitter()
            try:
                weakness_xray(
                    p.get('jobTitle',  ''),
                    p.get('sector',    'general'),
                    p.get('resume',    ''),
                    p.get('keywords',  []),
                    emit,
                )
            except Exception as e:
                try: emit({'type': 'error', 'msg': str(e)})
                except Exception: pass
            return

        # ── GRADE INTERVIEW ANSWER ───────────────────────────────────────────
        if path == '/grade-answer':
            self._sse_start()
            emit = self._make_emitter()
            try:
                grade_interview_answer(
                    p.get('question', ''),
                    p.get('answer',   ''),
                    p.get('jobTitle', ''),
                    p.get('sector',   'general'),
                    emit,
                )
            except Exception as e:
                try: emit({'type': 'error', 'msg': str(e)})
                except Exception: pass
            return

        # ── CAREER VELOCITY ──────────────────────────────────────────────────
        if path == '/velocity':
            self._sse_start()
            emit = self._make_emitter()
            try:
                career_velocity(
                    p.get('jobTitle',  ''),
                    p.get('sector',    'general'),
                    p.get('seniority', 'senior'),
                    p.get('resume',    ''),
                    emit,
                )
            except Exception as e:
                try: emit({'type': 'error', 'msg': str(e)})
                except Exception: pass
            return

        # ── PARSE RESUME (returns structured JSON) ────────────────────────────
        # ── TRANSCRIBE (Whisper) ──────────────────────────────────────────────
        # Voice-interview practice posts base64 audio here. Was missing server-side.
        if path == '/transcribe':
            try:
                b64 = p.get('audio_b64') or ''
                if not b64:
                    self._send_json(400, {'error': 'audio_b64 required', 'text': ''}); return
                mime = p.get('mime') or 'audio/webm'
                ext = {'audio/webm':'webm','audio/ogg':'ogg','audio/mp4':'mp4',
                       'audio/mpeg':'mp3','audio/wav':'wav'}.get(mime, 'webm')
                audio = base64.b64decode(b64)
                if len(audio) > 25 * 1024 * 1024:
                    self._send_json(413, {'error': 'audio exceeds 25MB Whisper limit', 'text': ''}); return

                # multipart/form-data body, hand-rolled to stay stdlib-only
                boundary = '----APEXAudio' + uuid.uuid4().hex
                pre = (
                    f'--{boundary}\r\n'
                    f'Content-Disposition: form-data; name="file"; filename="answer.{ext}"\r\n'
                    f'Content-Type: {mime}\r\n\r\n'
                ).encode()
                mid = (
                    f'\r\n--{boundary}\r\n'
                    f'Content-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n'
                    f'--{boundary}--\r\n'
                ).encode()
                body = pre + audio + mid

                req = Request(
                    'https://api.openai.com/v1/audio/transcriptions',
                    data=body,
                    headers={'Content-Type': f'multipart/form-data; boundary={boundary}',
                             'Authorization': f'Bearer {OPENAI_KEY}'},
                    method='POST')
                with urlopen(req, timeout=120) as r:
                    result = json.loads(r.read().decode('utf-8', 'replace'))
                self._send_json(200, {'text': (result.get('text') or '').strip()})
            except Exception as e:
                self._send_json(500, {'error': str(e), 'text': ''})
            return

        # ── DRAFT COVER LETTER (synchronous JSON) ─────────────────────────────
        # The tailoring modal calls this alongside /tailor. It was missing
        # server-side, so the cover-letter pane always rendered a fetch error.
        if path == '/draft-cover-letter':
            try:
                resume = (p.get('resume') or '').strip()
                if not resume:
                    self._send_json(400, {'error': 'resume required'}); return
                job_title = p.get('jobTitle') or 'the role'
                company   = p.get('company') or 'the company'
                posting   = (p.get('posting') or '')[:6000]
                sector    = p.get('sector') or 'general'

                sys_p = (
                    'You write concise, specific cover letters. Rules: 200-280 words. '
                    'Four short paragraphs. No greeting cliches, no "I am writing to apply". '
                    'Open with a concrete hook tied to the company or role. '
                    'Body paragraphs must cite real achievements from the resume with numbers where present. '
                    'Mirror the exact terminology used in the job posting. '
                    'Close with a direct, confident call to action. '
                    'Never invent facts that are not in the resume. Return the letter body only.'
                )
                usr_p = (
                    f'Sector: {sector}\nTarget role: {job_title}\nCompany: {company}\n\n'
                    f'JOB POSTING:\n{posting}\n\nCANDIDATE RESUME:\n{resume[:8000]}'
                )
                letter = clean(gpt(sys_p, usr_p, max_tokens=900, temp=0.4))
                self._send_json(200, {'letter': letter, 'jobTitle': job_title, 'company': company})
            except Exception as e:
                self._send_json(500, {'error': str(e), 'letter': ''})
            return

        # ── APPLY ALL RECOMMENDATIONS (synchronous JSON) ──────────────────────
        # Merges the optimized resume with Gap changes, bullet rewrites and
        # missing keywords into one final document.
        if path == '/apply-all-recommendations':
            try:
                optimized = (p.get('optimized') or p.get('original') or '').strip()
                if not optimized:
                    self._send_json(400, {'error': 'optimized or original resume required'}); return

                changes  = p.get('changes') or []
                rewrites = p.get('bulletRewrites') or []
                keywords = p.get('addedKeywords') or []
                sector   = p.get('sector') or 'general'
                job_title= p.get('jobTitle') or 'the role'

                # Only bullets that actually carry a rewrite are worth sending.
                rw = []
                for b in rewrites:
                    if isinstance(b, dict) and b.get('rewrite'):
                        rw.append({'original': b.get('bullet') or b.get('original') or '',
                                   'rewrite': b.get('rewrite')})

                def _fmt(items, limit=40):
                    out = []
                    for it in items[:limit]:
                        if isinstance(it, dict):
                            out.append('- ' + json.dumps(it, ensure_ascii=False)[:400])
                        else:
                            out.append('- ' + str(it)[:300])
                    return '\n'.join(out) if out else '(none)'

                sys_p = (
                    'You merge resume edits into one final ATS-optimized resume. Rules: '
                    'Apply every bullet rewrite exactly as given. '
                    'Weave the missing keywords in naturally where they are truthful; never bolt on a keyword list. '
                    'Apply the listed changes. Preserve all real facts, dates, employers and numbers. '
                    'Never fabricate experience, employers, degrees or metrics. '
                    'Keep clean plain-text structure with standard section headers. '
                    'Return ONLY the final resume text, no commentary.'
                )
                usr_p = (
                    f'Target role: {job_title}\nSector: {sector}\n\n'
                    f'CURRENT OPTIMIZED RESUME:\n{optimized[:12000]}\n\n'
                    f'BULLET REWRITES TO APPLY:\n{_fmt(rw)}\n\n'
                    f'RECOMMENDED CHANGES:\n{_fmt(changes)}\n\n'
                    f'KEYWORDS TO INTEGRATE:\n{", ".join(str(k) for k in keywords[:60]) or "(none)"}'
                )
                merged = clean(gpt(sys_p, usr_p, max_tokens=3600, temp=0.25))
                if not merged or len(merged) < 200:
                    merged = optimized
                self._send_json(200, {
                    'merged': merged,
                    'applied': {'rewrites': len(rw), 'changes': len(changes), 'keywords': len(keywords)}
                })
            except Exception as e:
                self._send_json(500, {'error': str(e), 'merged': p.get('optimized', '')})
            return

        if path == '/parse-resume':
            try:
                struct = parse_resume_struct(p.get('resume',''))
                self._send_json(200, {'struct': struct})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        # ── RENDER RESUME (returns HTML for chosen template) ──────────────────
        if path == '/render-resume':
            try:
                tpl_id = p.get('template','modern')
                struct = p.get('struct')
                if not struct and p.get('resume'):
                    struct = parse_resume_struct(p.get('resume',''))
                html = render_template(tpl_id, struct or {})
                self._send_json(200, {'html': html, 'template': tpl_id, 'struct': struct})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        # ── EMAIL ALERTS: SUBSCRIBE ───────────────────────────────────────────
        if path == '/alerts/subscribe':
            try:
                if not p.get('email') or not p.get('jobTitle'):
                    self._send_json(400, {'error':'email and jobTitle required'}); return
                sub = add_alert_subscription(p)
                smtp = _load_smtp_config()
                if smtp['user'] and smtp['pass']:
                    confirm_html = (
                        '<!doctype html><html><body style="font-family:-apple-system,Arial,sans-serif;background:#f8fafc;padding:24px">'
                        '<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,0.06)">'
                        '<div style="background:linear-gradient(135deg,#4f8ef7,#9b7cf4);padding:28px;color:#fff;text-align:center">'
                        '<div style="font-size:11px;letter-spacing:3px;text-transform:uppercase;opacity:0.85">APEX Job Alerts</div>'
                        + '<h1 style="margin:8px 0 0;font-size:24px">You\'re subscribed!</h1>'
                        + '</div><div style="padding:28px;color:#0f172a">'
                        + '<p>You\'ll get fresh <b>' + _esc(sub.get("jobTitle","")) + '</b> jobs'
                        + ((' near ' + _esc(sub.get("location",""))) if sub.get("location") else '')
                        + ' delivered to your inbox <b>' + _esc(sub.get("frequency","daily")) + '</b>.</p>'
                        + '<p style="color:#475569">First scan starts within 15 minutes.</p>'
                        + '<p style="color:#94a3b8;font-size:12px;margin-top:24px">Subscription ID: ' + _esc(sub.get("id","")) + '</p>'
                        + '</div></div></body></html>'
                    )
                    threading.Thread(target=send_alert_email, args=(sub['email'], '[APEX] Job alerts subscribed', confirm_html), daemon=True).start()
                    threading.Thread(target=alerts_scan_once, daemon=True).start()
                self._send_json(200, {'subscription': sub, 'smtp_configured': bool(smtp['user'] and smtp['pass'])})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        # ── EMAIL ALERTS: UNSUBSCRIBE ─────────────────────────────────────────
        if path == '/alerts/unsubscribe':
            try:
                ok = remove_alert(p.get('id',''))
                self._send_json(200, {'removed': ok})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        # ── EMAIL ALERTS: TEST SEND ───────────────────────────────────────────
        if path == '/alerts/test':
            try:
                ok, msg = send_alert_email(p.get('email',''), 'APEX SMTP test', '<p>SMTP is working</p>')
                self._send_json(200 if ok else 500, {'ok': ok, 'msg': msg})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        # ── SMTP SETUP: WRITE CREDS TO CONFIG ─────────────────────────────────
        if path == '/config/smtp':
            try:
                cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                cfg['SMTP_HOST'] = (p.get('host') or 'smtp.gmail.com').strip()
                cfg['SMTP_PORT'] = int(p.get('port') or 587)
                cfg['SMTP_USER'] = (p.get('user') or '').strip()
                cfg['SMTP_PASS'] = (p.get('password') or '').strip()
                cfg['SMTP_FROM'] = (p.get('from_addr') or p.get('user') or '').strip()
                with open(cfg_path, 'w', encoding='utf-8') as f:
                    json.dump(cfg, f, indent=2)
                self._send_json(200, {'saved': True, 'smtp_configured': bool(cfg['SMTP_USER'] and cfg['SMTP_PASS'])})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        # ── SMTP SETUP: TEST CREDS WITHOUT SAVING ─────────────────────────────
        if path == '/config/smtp/test':
            try:
                host = (p.get('host') or 'smtp.gmail.com').strip()
                port = int(p.get('port') or 587)
                pwd  = (p.get('password') or '').strip()
                if not user or not pwd:
                    self._send_json(400, {'ok': False, 'msg': 'user and password required'}); return
                msg = MIMEMultipart('alternative')
                msg['Subject'] = '[APEX] SMTP test'
                msg['From'] = user; msg['To'] = user
                msg.attach(MIMEText('<p>APEX SMTP test successful.</p>', 'html'))
                with smtplib.SMTP(host, port, timeout=15) as server:
                    server.starttls()
                    server.login(user, pwd)
                    server.sendmail(user, [user], msg.as_string())
                self._send_json(200, {'ok': True, 'msg': 'Test email sent to ' + user})
            except Exception as e:
                self._send_json(200, {'ok': False, 'msg': str(e)})
            return

        if path == '/alerts/scan':
            threading.Thread(target=alerts_scan_once, daemon=True).start()
            self._send_json(200, {'started': True})
            return

        if path == '/live-jobs':
            try:
                q = (p.get('q','') or '').strip()
                location = (p.get('location','') or '').strip()
                resume_text = (p.get('resume','') or '').strip()
                min_score = int(p.get('minScore') or 0)
                if not q: self._send_json(400, {'error':'q required'}); return
                result = fetch_structured_jobs(q, limit=int(p.get('limit', 40)), location=location)
                jobs = result['jobs'] if isinstance(result, dict) else result
                if resume_text:
                    jobs = score_jobs_against_resume(jobs, resume_text)
                    if min_score > 0:
                        jobs = [j for j in jobs if (j.get('match_score') or 0) >= min_score]
                parsed_loc = result.get('parsed_location','') if isinstance(result, dict) else location
                parsed_q = result.get('parsed_query', q) if isinstance(result, dict) else q
                self._send_json(200, {'jobs': jobs, 'count': len(jobs), 'query': parsed_q, 'parsed_location': parsed_loc, 'requested_location': location})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        # ── ONE-CLICK COVER LETTER (standalone, fast) ────────────────────────
        if path == "/draft-cover-letter":
            try:
                letter = standalone_cover_letter(
                    p.get("jobTitle",""), p.get("company",""),
                    p.get("posting",""), p.get("resume",""),
                    p.get("sector","general"),
                )
                self._send_json(200, {"letter": letter})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── INBOX SCAN: IMAP fetch + GPT classify ────────────────────────────
        if path == "/inbox/scan":
            try:
                user = (p.get("user") or "").strip()
                pwd  = (p.get("password") or "").strip()
                host = (p.get("host") or "imap.gmail.com").strip()
                days = int(p.get("days") or 30)
                if not user or not pwd:
                    self._send_json(400, {"error": "user and password required"}); return
                emails = fetch_recent_emails(user, pwd, host=host, days=days, limit=60)
                if not emails:
                    self._send_json(200, {"rows": [], "msg": "No emails fetched (check creds, app-password, or IMAP enabled)"}); return
                classifications = classify_inbox_emails(emails)
                cl_by_id = {int(c.get("id", -1)): c for c in classifications if "id" in c}
                merged = []
                for i, em in enumerate(emails):
                    cl = cl_by_id.get(i, {})
                    if cl.get("status") in ("not_relevant", None): continue
                    merged.append({
                        "from": em.get("from",""), "subject": em.get("subject",""),
                        "date": em.get("date",""),
                        "status": cl.get("status",""),
                        "company": cl.get("company",""),
                        "role": cl.get("role",""),
                        "confidence": cl.get("confidence", 50),
                    })
                self._send_json(200, {"count": len(merged), "rows": merged, "scanned": len(emails)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── TRANSCRIBE AUDIO (Whisper) ───────────────────────────────────────
        if path == "/transcribe":
            try:
                import base64
                b64 = p.get("audio_b64", "")
                mime = p.get("mime", "audio/webm")
                if not b64:
                    self._send_json(400, {"error": "audio_b64 required"}); return
                audio = base64.b64decode(b64)
                text = transcribe_audio_bytes(audio, mime=mime)
                self._send_json(200, {"text": text})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── APPLY ALL RECOMMENDATIONS (final merge into one resume) ──────────
        if path == "/apply-all-recommendations":
            try:
                merged = apply_all_recommendations(
                    original_resume = p.get("original",""),
                    optimized_resume = p.get("optimized",""),
                    changes = p.get("changes", []),
                    bullet_rewrites = p.get("bulletRewrites", []),
                    added_keywords = p.get("addedKeywords", []),
                    sector = p.get("sector","general"),
                    job_title = p.get("jobTitle",""),
                )
                self._send_json(200, {"merged": merged})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── UNKNOWN ROUTE ────────────────────────────────────────────────────
        self.send_response(404)
        self.end_headers()


def run():
    server = ThreadingHTTPServer(('localhost', PORT), Handler)
    server.daemon_threads = True
    js_ok = bool(JSEARCH_KEY)
    smtp_cfg = _load_smtp_config()
    smtp_ok = bool(smtp_cfg['user'] and smtp_cfg['pass'])
    threading.Thread(target=alerts_background_loop, daemon=True).start()
    bar = '=' * 64
    print('')
    print(bar)
    print('  APEX Resume Intelligence Agent  v10  -  ATS Text-Layer Edition')
    print(bar)
    print('  RUNNING  ->  http://localhost:' + str(PORT))
    print(bar)
    print('  Live jobs:  14 sources + per-job match scoring + relevance sort')
    print('  Match:      lightweight keyword overlap (~5ms/job, no GPT call)')
    print('  Filters:    match >=70, >=50, all  /  sort by match or newest')
    print('  Autocomp:   100+ US cities suggested as you type location')
    print('  PDF tpls:   6 ATS templates, direct download (no print dialog)')
    print('  Alerts:     in-app SMTP setup wizard')
    print(bar)
    print('  JSearch:  ' + ('ACTIVE' if js_ok else 'off (free APIs cover it)'))
    print('  SMTP:     ' + ('ACTIVE' if smtp_ok else 'off (set up in Alerts tab)'))
    print(bar)
    print('  OPEN:  http://localhost:7842/   (page + API on one origin)')
    print('  Ctrl+C to stop')
    print(bar + '\n', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
        server.shutdown()


if __name__ == '__main__':
    run()
