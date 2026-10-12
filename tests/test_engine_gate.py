"""apex_engine.fact_gate: adversarial table. Invented claims must fail, legit rewrites must pass."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import apex_engine as E  # noqa: E402

# The audit's evidence: every word below hides a substring the old gate matched.
EV = 'Reviewed labor laws and storage averages for the associate team. Mentored 2 interns. Led 1,500 employees.'

INVENTED = [
    # substrings of evidence words are not evidence
    ('Deployed on AWS', EV),                                   # laws
    ('Built RAG pipeline', EV),                                # storage / averages
    ('Ran SOC operations', EV),                                # associate
    ('Served as Lead for the leadership team', 'Ran leadership training for the team'),
    ('Wrote Java services', 'Wrote JavaScript services'),
    ('Built forecasting models in Excel', 'Delivered excellent forecasting models'),
    ('Wrote backend services in Go', 'Wrote backend services'),
    # numbers need value AND unit/scale
    ('Generated $2M in pipeline', EV),                         # 2 interns
    ('Scaled to 15K employees', EV),                           # 1,500
    ('Led 1,600 employees', EV),
    ('Saved $1.5M in labor costs', EV),
    ('Cut storage costs by 2%', EV),
    ('Improved review throughput 2x', EV),
    ('Doubled the associate team', EV),
    ('Mentored 3 interns', EV),
    ('Led fifteen employees', EV),
    ('Led a team of ten interns', EV),
    ('5+ years of experience leading teams', EV),
    ('Managed dozens of interns', EV),
    ('Cut review time by 10-15%', 'Cut review time by 10%'),
    ('Grew revenue 40%', EV),
    # tools and employers in any case or position
    ('Deployed with docker and kubernetes', EV),
    ('Kubernetes dashboards for the team', EV),
    ('Automated reviews with python scripts', EV),
    ('Built team dashboards in tableau', EV),
    ('Moved storage reports to Snowflake', EV),
    ('Led 1,500 employees at Amazon', EV),
    ('Partnered with Google on labor reviews', EV),
    ('Earned PMP certification', EV),
    ('Mentored 2 interns in Rust', EV),
    ('Reviewed labor laws (Zephyrline) for the team', EV),
    ('Reviewed labor laws. Kubeflow pipelines cut storage cost', EV),
    ('Reviewed laws: Workday rollout for the associate team', EV),
    ('Built React dashboards for the team', EV),
    ('Moved storage to Amazon S3', 'Moved storage to the cloud'),
]

LEGIT = [
    ('Mentored two interns', EV),
    ('Led 1.5K employees', EV),
    ('Reviewed labor laws and storage averages for the associate team', EV),
    ('Led fifteen analysts', 'Led 15 analysts'),
    ('Led 15 analysts', 'Led fifteen analysts'),
    ('Grew revenue to $2M', 'Grew revenue to $2,000,000'),
    ('Grew revenue to $2M', 'Grew revenue to 2 million dollars'),
    ('Scaled to 15K users', 'Scaled the platform to 15,000 users'),
    ('Doubled throughput', 'Increased throughput 2x'),
    ('Increased throughput 2x', 'Doubled throughput'),
    ('Halved processing time', 'Cut processing time by 50%'),
    ('Cut processing time in half', 'Cut processing time by 50%'),
    ('Cut review time by 10-15%', 'Cut review time by between 10% and 15%'),
    ('6+ years of experience in SQL reporting', 'Analyst with 6+ years of experience in SQL reporting'),
    ('Six years of SQL reporting', 'Analyst with 6 years of SQL reporting'),
    ('Ran 3 reviews', 'Reviewed labor laws, storage averages and payroll'),
    ('Built a RAG system for support search', 'Built a retrieval-augmented generation system for support search'),
    ('Deployed jobs on AWS', 'Deployed batch jobs on Amazon S3'),
    ('Deployed jobs on AWS', 'Deployed batch jobs to S3'),
    ('Built data-driven staffing reports', 'Built staffing reports'),
    ('Validated with tests against PostgreSQL', 'Tests against a real Postgres'),
    ('Built JavaScript services', 'Built JS services'),
    ('Built dashboards in Excel', 'Built dashboards in Excel and SQL'),
    ('Built Microsoft Excel models', 'Built Excel models'),
    ('Built SQL/Excel reports', 'Built reports in SQL and Excel'),
    ('Led leadership training for the team', 'Ran leadership training for the team'),
    ('Spearheaded the associate team review', EV),
    ('Kubernetes migration for 3 services', 'Migrated 3 services to Kubernetes'),
    ('Managed dozens of client accounts', 'Managed 36 client accounts'),
    ('Shipped 12 releases. Reports ran every March', 'Shipped 12 releases with weekly reports'),
    ('Used Go to build backend services', 'Built backend services in Go'),
]


@pytest.mark.parametrize('new,ev', INVENTED, ids=[n for n, _ in INVENTED])
def test_invented_claims_fail(new, ev):
    assert E.fact_gate(new, ev, (), ev) != [], f'{new!r} passed against {ev!r}'


@pytest.mark.parametrize('new,ev', LEGIT, ids=[n for n, _ in LEGIT])
def test_legit_rewrites_pass(new, ev):
    assert E.fact_gate(new, ev, (), ev) == []


def test_table_is_big_enough():
    assert len(INVENTED) + len(LEGIT) >= 40


def test_problem_messages_quote_the_number():
    probs = E.fact_gate('Generated $2M in pipeline', EV)
    assert any('number "2" (2,000,000 dollars)' in p for p in probs), probs
    assert E.fact_gate('Cut costs by 40%', EV) == ['number "40" (40 percent) is not in the source']
    assert any('number "15"' in p for p in E.fact_gate('Led fifteen employees', EV))
    assert any('name "kubernetes"' in p for p in E.fact_gate('Deployed with docker and kubernetes', EV))


# ── allowed words, keywords, context ─────────────────────────────────────────

def test_keywords_match_on_word_boundaries():
    ev = 'Ran data analysis for the testing team'
    assert any('adds "A/B testing"' in p for p in E.fact_gate('Ran A/B testing for the team', ev, ['A/B testing']))
    assert E.fact_gate('Ran data analysis for the testing team', ev, ['A/B testing', 'Python']) == []
    assert any('adds "Python"' in p for p in E.fact_gate('Ran data analysis in Python', ev, ['Python']))


def test_role_keywords_must_be_in_this_evidence():
    role = 'Junior Analyst - Corva\nMade spreadsheets for the sales team'
    probs = E.fact_gate('Built sales reporting spreadsheets', role, role_keywords=['reporting'])
    assert any('"reporting"' in p for p in probs), probs
    assert E.fact_gate('Built sales reports', 'Made reports for the sales team', role_keywords=['reporting']) == []


def test_context_backs_only_sentences_that_claim_nothing():
    ev = 'Built SQL reports for 12 clinic managers'
    posting = 'Meridian Health is hiring. 5 years of SQL experience required. Tableau a plus.'
    ok = 'Meridian Health needs KPI reporting. I build KPI reports in SQL.'
    assert E.fact_gate(ok, ev, context=posting) == []
    for bad in ('I have 5 years of SQL experience.',
                'I build reports for Meridian Health.',
                'My Tableau dashboards fit the role.',
                'Built Tableau dashboards for 12 clinic managers.'):     # an implicit claim (resume line)
        assert E.fact_gate(bad, ev, context=posting), bad
    assert E.fact_gate('The posting asks for 5 years of SQL.', ev, context=posting) == []
    assert E.fact_gate('I build reports for Meridian Health.', ev, context=posting,
                       allowed_words=['Meridian', 'Health']) == [], 'the company name passed as allowed'


def test_allowed_words_never_launder_a_tool():
    """The server passes the target title as allowed words; the title may name a tool."""
    assert E.fact_gate('Senior Data Analyst building KPI reports', 'Built KPI reports',
                       allowed_words=['Senior', 'Data', 'Analyst']) == []
    assert E.fact_gate('AWS Cloud Engineer', 'Built KPI reports', allowed_words=E.title_words('AWS Cloud Engineer'))


def test_number_words_and_quantities_parse():
    q = lambda t: {(v, u) for v, u, *_ in E._quantities(t)}
    assert (15.0, '') in q('fifteen managers') and (25.0, '') in q('twenty-five managers')
    assert (2000000.0, '$') in q('$2M') and (2000000.0, '$') in q('2 million dollars')
    assert (15000.0, '') in q('15K users') and (1200000.0, '') in q('1.2M events')
    assert (2.0, 'x') in q('doubled') and (2.0, 'x') in q('twice as fast') and (3.0, 'x') in q('3x faster')
    assert (5.0, 'yr') in q('5+ years') and (40.0, '%') in q('40 percent')
    assert {(10.0, '%'), (15.0, '%')} <= q('10-15%')
    assert (2021.0, '') in q('March 2021 - Present')
    assert not q('B2B SaaS on S3 and EC2')


def test_message_openers_and_slash_compounds_are_not_names():
    """Real-run regression: outreach messages were withheld for "Would", "Please"
    and "team/product"."""
    ev = 'Senior backend engineer at Ledgerly. Built the payments service in Go.'
    for text in ('Would you be open to a quick chat about the role?', 'Please let me know a good time.',
                 'Happy to share how the team/product split worked.', 'Hope you are well.'):
        assert E.fact_gate(text, ev) == [], text
    assert E.fact_gate('Built the AWS/Kubernetes platform', ev), 'a slash compound of tools still needs evidence'


def test_plural_nouns_opening_a_sentence_are_not_names():
    ev = 'Ran Go services on Kubernetes at Ledgerly.'
    assert E.fact_gate('Containers made deploys repeatable. Dashboards showed latency.', ev) == []
    assert E.fact_gate('Snowflake powered the reports.', ev), 'a tool at a sentence start is still checked'
    assert E.fact_gate('At Acme I ran Go services.', ev), 'a name mid-sentence is still checked'
