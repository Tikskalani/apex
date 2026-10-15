"""AI engineering: what hiring managers screen for, by role family.

APEX is built for one niche: AI engineering and the roles around it. Every target title
in the niche gets the field's screening guide (`BRIEF`) plus its role family's own focus:
an AI Platform Engineer is judged on serving, scale and cost; a Forward Deployed Engineer
on customer deployments and outcomes; an Evals Engineer on measurement. The engine reads
this in its review, rewrite and judge (through the target's `domain`, a known name only),
and the job agent scores postings with the family's terms. Example lines are patterns
only; their numbers are invented and the fact gate rejects any that reach a resume.

A title outside the niche runs with no pack (the engine's general playbook).
"""
import re

AI_SWE = 'ai_swe'           # the one domain; the id is kept for stored data and benchmarks

_ENGINEERING = re.compile(
    r'engineer|developer|programmer|software|\bswe\b|\bsde\b|\bml\b|machine\s+learning|\bai\b|artificial\s+intelligence'
    r'|\bllm\b|gen\s*ai|generative|data\s+scien|data\s+analy|analytics|applied\s+scien|research\s+scien|\bsre\b'
    r'|site\s+reliability|devops|mlops|platform|full[\s-]*stack|back[\s-]*end|front[\s-]*end|architect|technical\s+staff'
    r'|forward\s+deployed|solutions?\s+(?:engineer|architect)|prompt|agent', re.I)


_BUILDER = re.compile(
    r'engineer|developer|programmer|scientist|architect|researcher|\bswe\b|\bsde\b|\bmle\b|\bsre\b|devops|mlops'
    r'|technical\s+staff|\bcoder\b', re.I)


_LEADERSHIP = re.compile(r'\b(?:manager|director|vp|vice\s+president|head\s+of|chief|cto|president)\b', re.I)


def builder(title):
    """Does the title name a hands-on building role (engineer, developer, scientist, architect...)?
    "Head of AI Operations", "AI Transformation Owner" and "Manager, Applied AI Architects" do not."""
    t = title or ''
    return bool(_BUILDER.search(t)) and not _LEADERSHIP.search(t)


def detect(title):
    """AI_SWE for a title in the niche (AI, ML and the engineering around them), else None."""
    return AI_SWE if _ENGINEERING.search(title or '') else None


BRIEF = """WHAT HIRING MANAGERS FOR AI ENGINEERING ROLES SCREEN FOR (apply to this candidate's real evidence)
- Shipped and used beats built: what the AI system is, who uses it, and that it runs in production (users, customers,
  calls, requests or documents per day). A live system with real users outranks any number of notebooks or courses.
- The system around the model, not "used an LLM": retrieval (RAG, embeddings, vector search), tool use and agents,
  orchestration, structured outputs, and the deterministic code that keeps the model safe.
- Proof of quality: how output quality was measured (eval sets, held-out cases, pass rates, human review), regressions
  caught before release, and failure analysis that changed the design. This is the strongest AI signal there is.
- Guardrails and judgment: human-approval gates, safety floors, PII handling, prompt-injection defenses, fallbacks.
- The numbers that carry weight: latency (p50/p95, time to first token), cost per call or per task, accuracy or eval
  pass rate, error and hallucination rate, throughput and scale, uptime, and delivery speed.
- Engineering rigor: automated tests and CI gates, typed code, observability and tracing, incident handling.
- Ownership: what the candidate designed and owned end to end, the trade-offs chosen, and the business outcome.
- The top third of page 1 decides the screen: the target identity and the single strongest AI system must be readable
  in 6 seconds. Career changers and independent builders: the strongest AI project or client work leads (PROJECTS may
  sit above EXPERIENCE); earlier non-engineering roles shrink to the line that shows domain value.
- Skills grouped by area (AI and LLM, languages, frameworks, data, cloud and infrastructure, testing), the target's
  stack first. Name models, providers and frameworks the resume shows. No soft-skill lists.
- One proof per point: do not repeat the same test counts, metrics or claims across summary, bullets and skills.
- Cut duty statements ("responsible for"), unbacked adjectives ("cutting-edge", "robust"), tutorials and courses.
- Length: one page under about 5 years of engineering experience, two pages at most."""

VOCABULARY = ('LLM applications, AI agents, agentic workflows, tool use, function calling, RAG, embeddings, vector '
              'databases, evals, prompt engineering, context engineering, fine-tuning, guardrails, structured outputs, '
              'MLOps, model serving, inference latency, Python, TypeScript, FastAPI, React, Next.js, PostgreSQL, '
              'Docker, Kubernetes, AWS, GCP, CI/CD, distributed systems, system design, observability')

EXAMPLES = [
    'Built an eval harness of 40 scripted and 12 held-out scenarios that gates every model change; it caught 3 '
    'regressions before release',
    'Cut p95 latency of the retrieval API from 900 ms to 220 ms by moving embeddings to pgvector with HNSW indexes',
    'Shipped a multi-tenant agent platform to 8 paying customers, with per-tenant API keys, audit logs and a '
    'human-approval queue for every outbound action',
]

# Role families: the titles in each, how to recognise them, what their managers look for
# beyond the field brief, extra terms for the job agent's fit score, and example lines.
FAMILIES = {
    'llm_app': {
        'label': 'AI / LLM application engineering',
        'titles': ['AI Engineer', 'LLM Engineer', 'Generative AI Engineer', 'Applied AI Engineer', 'AI Agent Engineer',
                   'Agentic AI Engineer', 'Prompt Engineer', 'Conversational AI Engineer', 'Senior AI Engineer'],
        'detect': r'\bllm\b|gen(?:erative)?\s*ai|\bagent(?:ic|s)?\b|prompt|conversational|applied\s+ai|\bai\s+engineer',
        'focus': 'Agents and LLM features in production: orchestration, tool use, retrieval, evals and guardrails; '
                 'reliability of model output (structured outputs, retries, fallbacks); latency and cost per task.',
        'terms': ['LangGraph', 'CrewAI', 'AutoGen', 'DSPy', 'structured outputs', 'context engineering', 'reranking',
                  'hybrid search', 'semantic search', 'chunking', 'Bedrock', 'Vertex AI', 'Azure OpenAI', 'Gemini',
                  'Llama', 'Mistral', 'Ollama', 'vLLM'],
        'examples': ['Shipped an agent that triages 2,000 support tickets a day with tool calls to 6 internal APIs; '
                     'a 300-case eval set gates every prompt change'],
    },
    'voice_multimodal': {
        'label': 'voice, speech and multimodal AI',
        'titles': ['Voice AI Engineer', 'Speech Engineer', 'Multimodal AI Engineer', 'Conversational Voice Engineer'],
        'detect': r'voice|speech|multimodal|audio',
        'focus': 'Real-time voice pipelines (ASR, LLM, TTS, telephony), latency per turn, barge-in and noise handling, '
                 'call outcomes, and how quality was measured on real calls.',
        'terms': ['ASR', 'TTS', 'speech-to-text', 'text-to-speech', 'Deepgram', 'ElevenLabs', 'Whisper', 'Twilio',
                  'Telnyx', 'WebRTC', 'telephony', 'LiveKit', 'Pipecat', 'VAD'],
        'examples': ['Cut median voice-agent turn latency from 1.8 s to 1.0 s by streaming ASR into the LLM and '
                     'starting TTS on the first sentence'],
    },
    'ml_engineer': {
        'label': 'machine learning engineering',
        'titles': ['Machine Learning Engineer', 'Applied ML Engineer', 'Deep Learning Engineer', 'NLP Engineer',
                   'Computer Vision Engineer', 'Recommender Systems Engineer', 'Senior Machine Learning Engineer'],
        'detect': r'machine\s+learning|\bml\b|deep\s+learning|\bnlp\b|computer\s+vision|recommend|ranking',
        'focus': 'Models taken from data to production: features, training, offline metrics that predicted online '
                 'results, A/B tests and business lift, serving latency, retraining and monitoring for drift.',
        'terms': ['feature engineering', 'model training', 'hyperparameter', 'learning to rank', 'two-tower',
                  'transformers', 'BERT', 'CNN', 'ONNX', 'TensorRT', 'Ray', 'SageMaker', 'MLflow', 'Weights & Biases',
                  'model drift', 'online metrics', 'offline metrics'],
        'examples': ['Shipped a two-tower retrieval model with a gradient-boosted ranker; an A/B test showed a 6% lift '
                     'in add-to-cart'],
    },
    'mlops_platform': {
        'label': 'MLOps, AI platform and infrastructure',
        'titles': ['MLOps Engineer', 'ML Platform Engineer', 'AI Platform Engineer', 'AI Infrastructure Engineer',
                   'LLMOps Engineer', 'Inference Engineer', 'ML Infrastructure Engineer'],
        'detect': r'mlops|llmops|platform|infrastructure|inference|serving',
        'focus': 'Platforms other teams build on: model serving and inference cost, GPU utilisation, deployment '
                 'pipelines, evaluation and observability infrastructure, reliability and scale.',
        'terms': ['GPU', 'CUDA', 'vLLM', 'TensorRT', 'Triton', 'KServe', 'Ray', 'Kubeflow', 'MLflow', 'Kubernetes',
                  'Terraform', 'autoscaling', 'batching', 'quantization', 'model registry', 'feature store',
                  'OpenTelemetry', 'Prometheus', 'Grafana'],
        'examples': ['Cut inference cost 45% by moving a 7B model to vLLM with continuous batching on 4 GPUs at '
                     'the same p95 latency'],
    },
    'forward_deployed': {
        'label': 'forward deployed, solutions and customer AI engineering',
        'titles': ['Forward Deployed Engineer', 'AI Solutions Engineer', 'Solutions Architect, AI', 'AI Deployment Engineer',
                   'Customer AI Engineer', 'AI Consultant'],
        'detect': r'forward\s+deployed|solutions?\s+(?:engineer|architect)|deployment|customer|consult',
        'focus': 'AI shipped for customers: scoping a messy business problem, building to production fast, the '
                 'customer outcome (hours saved, revenue, accuracy), stakeholder trust, and working in their stack.',
        'terms': ['customer-facing', 'proof of concept', 'POC', 'solutions engineering', 'workflow automation',
                  'technical discovery', 'pre-sales', 'deployment'],
        'examples': ['Scoped and shipped a claims-summary assistant for an insurer in 6 weeks; adjusters cut note '
                     'reading from 20 to 14 minutes per claim'],
    },
    'fullstack_ai': {
        'label': 'full-stack and product engineering for AI products',
        'titles': ['Full-Stack AI Engineer', 'AI Product Engineer', 'Software Engineer, AI', 'Backend Engineer, AI',
                   'Founding AI Engineer', 'Founding Engineer', 'Product Engineer'],
        'detect': r'full[\s-]*stack|product\s+engineer|founding|back[\s-]*end',
        'focus': 'AI features users touch: end-to-end ownership from UI to API to model, speed of shipping, product '
                 'judgment, streaming UX, auth and multi-tenancy, and usage or revenue outcomes.',
        'terms': ['React', 'Next.js', 'TypeScript', 'Node.js', 'FastAPI', 'PostgreSQL', 'Supabase', 'Prisma', 'Vercel',
                  'WebSockets', 'multi-tenant', 'Stripe', 'Tailwind', 'tRPC'],
        'examples': ['Built and launched the product\'s AI assistant end to end (Next.js, FastAPI, Postgres); 40% of '
                     'weekly active users adopted it in the first month'],
    },
    'research': {
        'label': 'research engineering and applied science',
        'titles': ['Research Engineer', 'Applied Scientist', 'AI Research Scientist', 'Member of Technical Staff',
                   'Research Scientist'],
        'detect': r'research|scientist|technical\s+staff',
        'focus': 'Experiments that changed decisions: rigorous evaluation, baselines and ablations, training or '
                 'fine-tuning at scale, reproducibility, papers or open-source work, and speed from idea to result.',
        'terms': ['fine-tuning', 'RLHF', 'DPO', 'LoRA', 'pretraining', 'distillation', 'ablation',
                  'reproducibility', 'JAX', 'PyTorch', 'distributed training', 'publications', 'arXiv'],
        'examples': ['Fine-tuned a 7B model with LoRA on 40k domain examples; it beat the prompted baseline by 12 points '
                     'on a held-out eval'],
    },
    'evals_safety': {
        'label': 'AI evaluation, quality and safety',
        'titles': ['AI Evaluation Engineer', 'Model Evaluation Engineer', 'AI Quality Engineer', 'AI Safety Engineer',
                   'AI Red Team Engineer', 'Trust and Safety ML Engineer'],
        'detect': r'eval|quality|safety|red\s*team|trust',
        'focus': 'Measurement: eval design, held-out and adversarial sets, LLM-as-judge calibration, regression gates in '
                 'CI, red teaming and jailbreak defenses, and the decisions the measurements drove.',
        'terms': ['evals', 'LLM-as-judge', 'red teaming', 'jailbreak', 'prompt injection', 'hallucination',
                  'golden set', 'guardrails', 'AI safety', 'Braintrust', 'LangSmith', 'Langfuse'],
        'examples': ['Built a 500-case adversarial eval suite and LLM-judge calibrated to human labels (0.86 agreement); '
                     'it blocks releases that regress'],
    },
    'data_ai': {
        'label': 'data science and data engineering for AI',
        'titles': ['Data Scientist, Generative AI', 'AI Data Engineer', 'Data Engineer', 'Analytics Engineer',
                   'Data Scientist'],
        'detect': r'data\s+(?:scien|engineer|analy)|analytics',
        'focus': 'Data that makes AI work: pipelines and data quality, labeling and synthetic data, experiments and '
                 'causal reads, and metrics that decision makers used.',
        'terms': ['data pipelines', 'ETL', 'dbt', 'Airflow', 'Spark', 'Snowflake', 'Databricks', 'BigQuery',
                  'data quality', 'labeling', 'synthetic data', 'A/B testing', 'SQL', 'pandas'],
        'examples': ['Built the labeling and data-quality pipeline behind a support classifier; label noise fell from '
                     '14% to 4% and accuracy rose 9 points'],
    },
    'automation': {
        'label': 'AI automation and integration',
        'titles': ['AI Automation Engineer', 'AI Workflow Engineer', 'AI Integration Engineer', 'Automation Engineer'],
        'detect': r'automation|workflow|integration',
        'focus': 'Business workflows automated with AI: which process, how much time or money it saved, how errors '
                 'are caught (human review, validation), and the systems it connects.',
        'terms': ['workflow automation', 'n8n', 'Zapier', 'Make.com', 'RPA', 'UiPath', 'webhooks',
                  'QuickBooks', 'Salesforce', 'HubSpot', 'human-in-the-loop', 'document processing', 'OCR'],
        'examples': ['Automated six-entity financial consolidation with Claude and human review gates; month-end close '
                     'dropped from 5 days to 2'],
    },
}
_FAMILY_RX = [(fid, re.compile(f['detect'], re.I)) for fid, f in FAMILIES.items()]
# Most specific first: a "Voice AI Engineer" is voice, an "ML Platform Engineer" is platform.
_FAMILY_ORDER = ['voice_multimodal', 'evals_safety', 'forward_deployed', 'mlops_platform', 'data_ai', 'automation',
                 'research', 'ml_engineer', 'fullstack_ai', 'llm_app']


def family(title):
    """The role family of a title in the niche, or None."""
    if not detect(title):
        return None
    t = title or ''
    rx = dict(_FAMILY_RX)
    return next((fid for fid in _FAMILY_ORDER if rx[fid].search(t)), 'fullstack_ai')


def all_terms():
    """Every skill term the niche knows (the field's and every family's), for the market radar."""
    out = list(BASE_TERMS)
    for f in FAMILIES.values():
        out += f.get('terms', [])
    return list(dict.fromkeys(out))


def label(fid):
    return (FAMILIES.get(fid) or {}).get('label', fid or 'Other')


def titles():
    """Every title APEX knows, grouped: [{family, label, titles}] (for pickers)."""
    return [{'family': fid, 'label': f['label'], 'titles': f['titles']} for fid, f in FAMILIES.items()]


# Skills and tools a posting may ask for: the job agent's fit score is the share of these a
# posting asks for that the resume shows (whole words). Broader than the prompt vocabulary
# on purpose: it has to recognise what a posting wants.
BASE_TERMS = [
    'LLM', 'large language models', 'generative AI', 'AI agents', 'agentic', 'RAG', 'embeddings', 'vector database',
    'pgvector', 'Pinecone', 'evals', 'prompt engineering', 'fine-tuning', 'guardrails', 'tool use', 'function calling',
    'MCP', 'OpenAI', 'Anthropic', 'Claude', 'GPT', 'LangChain', 'LlamaIndex', 'Hugging Face', 'PyTorch', 'TensorFlow',
    'scikit-learn', 'XGBoost', 'machine learning', 'deep learning', 'NLP', 'computer vision', 'speech recognition',
    'recommendation', 'MLOps', 'model serving', 'inference', 'feature store', 'A/B testing', 'experimentation',
    'Python', 'TypeScript', 'JavaScript', 'Go', 'Golang', 'Java', 'Kotlin', 'C++', 'Rust', 'Scala', 'SQL', 'FastAPI',
    'Django', 'Flask', 'Node.js', 'React', 'Next.js', 'GraphQL', 'REST', 'gRPC', 'asyncio', 'microservices',
    'PostgreSQL', 'MySQL', 'MongoDB', 'Redis', 'Elasticsearch', 'Kafka', 'Spark', 'Airflow', 'dbt', 'Snowflake',
    'Databricks', 'BigQuery', 'data pipelines', 'ETL', 'Supabase', 'Prisma', 'AWS', 'GCP', 'Azure', 'Docker',
    'Kubernetes', 'Terraform', 'Linux', 'nginx', 'serverless', 'Vercel', 'CI/CD', 'GitHub Actions', 'observability',
    'distributed systems', 'system design', 'authentication', 'webhooks', 'unit tests', 'pytest', 'integration tests',
    'code review', 'Git', 'Twilio', 'telephony', 'mentoring',
]
MATCH_TERMS = {AI_SWE: BASE_TERMS}


def match_terms(domain, title=''):
    """The fit-score terms for a title: the field's, plus its family's."""
    if domain != AI_SWE:
        return []
    fam = FAMILIES.get(family(title)) or {}
    return list(dict.fromkeys(BASE_TERMS + fam.get('terms', [])))


# Page budget: about 500 words fill a page in APEX's exports; two pages at most.
WORDS_PER_PAGE = 500
PAGES = {AI_SWE: 2}


def page_budget(domain, seniority=''):
    """(pages, words) a resume should fit, or (None, None) outside the niche."""
    pages = PAGES.get(domain)
    return (pages, pages * WORDS_PER_PAGE) if pages else (None, None)


def brief(domain, title=''):
    """The text the engine reads: the field guide, the role family's focus, vocabulary and example lines."""
    if domain != AI_SWE:
        return ''
    fam = FAMILIES.get(family(title or 'AI Engineer')) or {}
    focus = (f"\nTHIS ROLE FAMILY ({fam['label']}) IS JUDGED MOST ON: {fam['focus']}" if fam else '')
    ex = '\n'.join(f'- {e}' for e in fam.get('examples', []) + EXAMPLES)
    return (f"{BRIEF}{focus}\nFIELD VOCABULARY (use a term only for what the resume shows): {VOCABULARY}"
            + (f", {', '.join(fam.get('terms', []))}" if fam else '')
            + f"\nEXCELLENT LINES IN THIS FIELD (the shape to aim for; their facts are invented, never copy them):\n{ex}")


def sector(domain, default='general'):
    return 'tech' if domain == AI_SWE else default
