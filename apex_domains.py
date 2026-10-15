"""Domain packs: what hiring managers in APEX's two fields screen for.

APEX is tuned for two fields: AI and software engineering, and physical therapy. A pack is
written guidance the engine reads in every step (diagnosis, rewrite, judge) through the
target's `domain_brief`: what a strong resume in the field shows, the field's vocabulary,
how to order the page, and the shape of excellent lines. The example lines are patterns
only; their numbers are invented and the fact gate rejects any that reach a resume.

Roles outside both fields still run, with no pack (the engine's general playbook).
"""
import re

AI_SWE = 'ai_swe'
PHYSICAL_THERAPY = 'physical_therapy'

_DETECT = [
    (PHYSICAL_THERAPY, re.compile(
        r'physical\s+therap|physiotherap|\bdpt\b|\bpta\b|\bp\.?t\.?\b(?!\s*time)|rehab(?:ilitation)?\s+(?:therapist|director|manager)'
        r'|(?:outpatient|orthopedic|sports|acute|inpatient|home\s+health|pediatric|neuro|pelvic|vestibular)\s+(?:physical\s+)?therapist',
        re.I)),
    (AI_SWE, re.compile(
        r'engineer|developer|programmer|software|\bswe\b|\bsde\b|\bml\b|machine\s+learning|\bai\b|artificial\s+intelligence'
        r'|\bllm\b|data\s+scien|data\s+analy|analytics|applied\s+scien|research\s+scien|\bsre\b|site\s+reliability|devops|mlops|platform'
        r'|full[\s-]*stack|back[\s-]*end|front[\s-]*end|architect|technical\s+staff', re.I)),
]


def detect(title):
    """The pack for a target job title, or None for roles outside both fields."""
    t = title or ''
    return next((name for name, rx in _DETECT if rx.search(t)), None)


PACKS = {
    AI_SWE: {
        'label': 'AI and software engineering',
        'sector': 'tech',
        'brief': """WHAT HIRING MANAGERS FOR AI AND SOFTWARE ENGINEERING ROLES SCREEN FOR (apply to this candidate's real evidence)
- Shipped and used beats built: what the system is, who uses it, and that it runs in production (users, customers,
  requests or records per day, uptime). A live system with real users outranks any amount of coursework.
- Engineering rigor, shown with specifics: automated tests and CI gates, code review, observability, incident
  handling, security and privacy design, migrations done without downtime.
- For AI and LLM roles: the system around the model, not just "used an LLM": retrieval (RAG, embeddings, vector
  search), tool use and agents, how quality was measured (eval sets, held-out cases, pass rates, regressions caught),
  guardrails and human-approval gates, latency and cost per call, and failure analysis that changed the design.
- Ownership and judgment: what the candidate led or owned end to end, decisions and trade-offs, scope (systems,
  teams, clients), and outcomes for the business.
- The numbers that carry weight here: latency (p50/p95/p99), throughput and scale, reliability (uptime, incidents,
  pages), cost, quality metrics (accuracy, eval pass rate, error rate), and delivery speed (deploys, lead time).
- The top third of page 1 decides the screen: the target identity and the single strongest relevant system must be
  readable in 6 seconds. Career changers, new grads and independent builders: the strongest relevant project or
  client work leads; a PROJECTS section may sit above EXPERIENCE; earlier non-engineering roles shrink to the line
  that shows transferable value (domain knowledge, users, operations).
- Skills grouped by area (AI/LLM, languages, frameworks, data, cloud/DevOps, testing), most relevant to the target
  first. No soft-skill lists. Each group short enough to scan.
- One proof per point: do not repeat the same test counts, metrics or claims across summary, bullets and skills.
- Cut duty statements ("responsible for"), unbacked adjectives ("passionate", "cutting-edge", "robust"), tutorials.
- Length: one page under about 5 years of engineering experience, two pages at most.""",
        'vocabulary': ('LLM applications, AI agents, agentic workflows, tool use, RAG, embeddings, vector databases, evals, '
                       'prompt engineering, fine-tuning, guardrails, MLOps, model serving, inference latency, Python, '
                       'TypeScript, FastAPI, React, Next.js, PostgreSQL, Docker, Kubernetes, AWS, GCP, CI/CD, '
                       'distributed systems, system design, REST APIs, data pipelines, observability'),
        'examples': [
            'Built an eval harness of 40 scripted and 12 held-out scenarios that gates every model change; it caught 3 '
            'regressions before release',
            'Cut p95 latency of the retrieval API from 900 ms to 220 ms by moving embeddings to pgvector with HNSW indexes',
            'Shipped a multi-tenant agent platform to 8 paying customers, with per-tenant API keys, audit logs and a '
            'human-approval queue for every outbound action',
        ],
    },
    PHYSICAL_THERAPY: {
        'label': 'physical therapy',
        'sector': 'healthcare',
        'brief': """WHAT PHYSICAL THERAPY HIRING MANAGERS (clinic directors, rehab managers, recruiters) SCREEN FOR
- Licensure first: the state PT license (and compact privilege if stated), the DPT, BLS/CPR, and certifications
  (OCS, SCS, NCS, GCS, PCS, CSCS, dry needling, McKenzie/MDT, LSVT BIG, vestibular, ASTYM, Graston, APTA Credentialed
  Clinical Instructor) in a LICENSES & CERTIFICATIONS section near the top, exactly as held.
- Setting and population fit: outpatient orthopedics, sports, acute care, inpatient rehab, skilled nursing, home
  health, pediatrics, neuro, pelvic health, vestibular. The summary names the settings and patient populations the
  target role serves that the resume shows.
- Caseload and productivity: patients per day or visits per week, caseload size, productivity percentage, timely
  documentation, and the EMR used (WebPT, Epic, Net Health, Raintree, Prompt).
- Outcomes: functional outcome measures (FOTO, LEFS, ODI, NDI, Berg, TUG, 6MWT), discharge to home, return to sport
  or work, falls reduced, plan-of-care completion, patient satisfaction or NPS, retention.
- Clinical skills tied to cases: manual therapy, therapeutic exercise, gait and balance training, post-operative
  protocols (ACL, total knee or hip, rotator cuff), vestibular and neuro rehab, dry needling, home exercise programs.
- Value beyond the caseload: clinical instructor for DPT students, mentoring, in-services, programs started (falls
  prevention, return to sport), physician and community outreach, direct access, Medicare and payer compliance.
- New graduates: each clinical rotation (setting, length, caseload reached by the end), capstone or research, aide or
  tech experience, certifications in progress.
- Cut generic duties ("evaluated and treated patients"), adjectives without evidence, and anything unrelated to care.
- Length: one page; two only with 10+ years or leadership roles.""",
        'vocabulary': ('physical therapist, DPT, state license, outpatient orthopedics, manual therapy, therapeutic exercise, '
                       'gait training, balance, post-operative rehabilitation, sports rehabilitation, vestibular, neuro '
                       'rehab, dry needling, plan of care, home exercise program, functional outcomes, FOTO, caseload, '
                       'productivity, documentation, WebPT, Epic, Medicare, clinical instructor, patient education'),
        'examples': [
            'Managed a caseload of 14-16 outpatient orthopedic patients a day at 92% productivity with same-day '
            'documentation in WebPT',
            'Raised average FOTO functional scores for post-operative knee patients 9 points above the risk-adjusted '
            'national benchmark',
            'Served as Clinical Instructor for 6 DPT students and built the clinic\'s ACL return-to-sport testing protocol',
        ],
    },
}


# Skills and tools a posting in the field may ask for: the job agent's fit score is the share
# of these that a posting asks for and the resume shows (whole words). Broader than the
# prompt vocabulary on purpose: it has to recognise what a posting wants.
MATCH_TERMS = {
    AI_SWE: [
        # AI / ML
        'LLM', 'large language models', 'generative AI', 'AI agents', 'agentic', 'RAG', 'embeddings', 'vector database', 'pgvector', 'Pinecone', 'evals', 'prompt engineering',
        'fine-tuning', 'guardrails', 'tool use', 'function calling', 'MCP', 'OpenAI', 'Anthropic', 'Claude', 'GPT',
        'LangChain', 'LlamaIndex', 'Hugging Face', 'PyTorch', 'TensorFlow', 'scikit-learn', 'XGBoost',
        'machine learning', 'deep learning', 'NLP', 'computer vision', 'speech recognition', 'recommendation',
        'MLOps', 'model serving', 'inference', 'feature store', 'A/B testing', 'experimentation',
        # languages and frameworks
        'Python', 'TypeScript', 'JavaScript', 'Go', 'Golang', 'Java', 'Kotlin', 'C++', 'Rust', 'Scala', 'Ruby',
        'SQL', 'FastAPI', 'Django', 'Flask', 'Node.js', 'Express', 'React', 'Next.js', 'Vue', 'GraphQL', 'REST',
        'gRPC', 'asyncio', 'microservices',
        # data and infrastructure
        'PostgreSQL', 'MySQL', 'MongoDB', 'Redis', 'Elasticsearch', 'Kafka', 'Spark', 'Airflow', 'dbt',
        'Snowflake', 'Databricks', 'BigQuery', 'data pipelines', 'ETL', 'Supabase', 'Prisma',
        'AWS', 'GCP', 'Azure', 'Docker', 'Kubernetes', 'Terraform', 'Linux', 'nginx', 'serverless', 'Vercel',
        'CI/CD', 'GitHub Actions', 'observability', 'distributed systems', 'system design',
        'authentication', 'webhooks', 'unit tests', 'pytest',
        'integration tests', 'code review', 'Git', 'Twilio', 'telephony', 'mentoring',
    ],
    PHYSICAL_THERAPY: [
        'DPT', 'physical therapist license', 'BLS', 'CPR', 'ACLS', 'outpatient', 'inpatient',
        'acute care', 'ICU', 'skilled nursing', 'SNF', 'home health', 'pediatrics', 'pediatric', 'geriatrics', 'neuro',
        'neurologic', 'stroke', 'orthopedic', 'orthopedics', 'sports', 'spine', 'vestibular', 'pelvic health',
        'cardiopulmonary', 'post-operative', 'post-op', 'ACL', 'total joint', 'manual therapy', 'therapeutic exercise',
        'dry needling', 'gait training', 'balance', 'falls prevention', 'modalities', 'aquatic therapy',
        'home exercise program', 'patient education', 'plan of care', 'discharge planning', 'DME',
        'EMR', 'WebPT', 'Epic', 'Net Health', 'Raintree', 'Medicare', 'productivity', 'caseload',
        'FOTO', 'OCS', 'SCS', 'NCS', 'GCS', 'PCS', 'CSCS', 'McKenzie', 'Graston', 'ASTYM', 'LSVT',
        'clinical instructor', 'mentorship', 'new grad', 'residency', 'fellowship', 'interdisciplinary', 'PRN',
        'school-based', 'early mobility',
    ],
}


def brief(domain):
    """The text the engine reads for a pack: the screening guide, the vocabulary and example lines."""
    p = PACKS.get(domain)
    if not p:
        return ''
    ex = '\n'.join(f'- {e}' for e in p['examples'])
    return (f"{p['brief']}\nFIELD VOCABULARY (use a term only for what the resume shows): {p['vocabulary']}\n"
            f"EXCELLENT LINES IN THIS FIELD (the shape to aim for; their facts are invented, never copy them):\n{ex}")


def sector(domain, default='general'):
    return (PACKS.get(domain) or {}).get('sector', default)
