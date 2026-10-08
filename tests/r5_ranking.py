import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import *
ns = load_core(); S = ns['ats_score']
print("-- ROUND 5: does the score rank resumes correctly? --")
KW=['python','sql','etl','airflow','dbt','aws','data modeling','stakeholder communication']

HDR="ALEX RIVERA\nHouston, TX | a@x.com | 555-123-4567\n"
EXCELLENT=HDR+"""SUMMARY
Data engineer building python and sql pipelines on aws.
EXPERIENCE
Senior Data Engineer - Meridian
- Built airflow ETL pipelines processing 4M records daily, cutting latency 60%
- Designed dbt data modeling layer adopted by 12 analysts
- Migrated 40 jobs to aws, reducing spend $180K annually
EDUCATION
BS Computer Science 2018
SKILLS
python, sql, etl, airflow, dbt, aws, data modeling, stakeholder communication"""

MEDIOCRE=HDR+"""SUMMARY
Looking for a data role.
EXPERIENCE
Analyst - Corva
- Responsible for making reports
- Worked with sql to get data
- Helped improve some processes
EDUCATION
BS Business 2019
SKILLS
Excel, sql, Communication"""

KEYWORD_STUFFED=HDR+"""SUMMARY
python sql etl airflow dbt aws data modeling stakeholder communication
EXPERIENCE
Analyst - Corva
- Responsible for python sql etl airflow dbt aws
EDUCATION
BS 2019
SKILLS
python, sql, etl, airflow, dbt, aws, data modeling, stakeholder communication"""

LIAR=HDR+"""SUMMARY
Expert in python sql etl airflow dbt aws data modeling stakeholder communication.
EXPERIENCE
Senior Staff Principal Engineer - Google
- Led 400 engineers building airflow etl at planetary scale, saving $40B
- Architected dbt python aws data modeling for 900M users
EDUCATION
PhD 2019
SKILLS
python, sql, etl, airflow, dbt, aws, data modeling, stakeholder communication"""

NO_SECTIONS="Alex Rivera a@x.com built python sql etl airflow dbt aws pipelines for years and years"

scores={n:S(t,KW)[0] for n,t in [('excellent',EXCELLENT),('mediocre',MEDIOCRE),
        ('stuffed',KEYWORD_STUFFED),('liar',LIAR),('no_sections',NO_SECTIONS)]}
for n,v in scores.items(): print(f"  {n:12} {v:3d}  {S(dict([('excellent',EXCELLENT),('mediocre',MEDIOCRE),('stuffed',KEYWORD_STUFFED),('liar',LIAR),('no_sections',NO_SECTIONS)])[n],KW)[1]}")
print()
check('excellent > mediocre', scores['excellent']>scores['mediocre'], f"{scores['excellent']} vs {scores['mediocre']}")
check('excellent > stuffed', scores['excellent']>scores['stuffed'], f"{scores['excellent']} vs {scores['stuffed']} - stuffing beats real work")
check('excellent > no_sections', scores['excellent']>scores['no_sections'])
check('mediocre not near-perfect', scores['mediocre']<70, f"got {scores['mediocre']}")
check('stuffed penalised vs excellent', scores['excellent']-scores['stuffed']>=8,
      f"gap only {scores['excellent']-scores['stuffed']}")
# The liar has identical keywords to excellent - score can't detect lies, but the
# audit does. Just confirm score doesn't PREFER the liar.
check('liar not above excellent', scores['liar']<=scores['excellent'], f"{scores['liar']} vs {scores['excellent']}")
summary()
