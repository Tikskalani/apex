import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import *
import json, re
print("-- ROUND 8: weak resume must actually improve --")
WEAK = """MARCUS DELGADO
Houston, TX | marcus.delgado@email.com | (713) 555-0142
SUMMARY
Experienced professional looking for a new opportunity in data analysis.
Hard worker and team player with good communication skills.
EXPERIENCE
Data Analyst - Brightline Logistics, Houston TX
March 2021 - Present
- Responsible for making reports for the management team
- Worked with SQL to get data from databases
- Helped improve some processes
- Was part of a team that did dashboards
EDUCATION
B.S. Business Administration, University of Houston, 2019
SKILLS
Excel, SQL, PowerPoint, Communication, Teamwork"""

KW=['sql','python','tableau','dashboards','data analysis','stakeholder communication',
    'etl','reporting','excel','a/b testing']

ns=load_core()
base,bd = ns['ats_score'](WEAK,KW)
print(f"  baseline: {base}  {bd}")
check('weak resume scores low', base < 60, f"scored {base} - scorer too generous")

# Honest rewriter: strong verbs, no new facts
IMPROVED = WEAK.replace(
 '- Responsible for making reports for the management team','- Built recurring reports for the management team')\
 .replace('- Worked with SQL to get data from databases','- Queried SQL databases to extract reporting datasets')\
 .replace('- Helped improve some processes','- Streamlined reporting processes')\
 .replace('- Was part of a team that did dashboards','- Delivered dashboards as part of the analytics team')\
 .replace('Experienced professional looking for a new opportunity in data analysis.\nHard worker and team player with good communication skills.',
          'Data analyst experienced in sql, reporting, dashboards, and excel for data analysis.')

def gpt(system,user,max_tokens=3000,temp=0.3):
    if 'evidence auditor' in system:
        kws=json.loads(user.split('KEYWORDS:')[1].split('RESUME:')[0].strip())
        bad=[k for k in kws if k in ('python','tableau','etl','a/b testing')]
        return json.dumps({'supported':[k for k in kws if k not in bad],'unsupported':bad})
    if 'fraud auditor' in system: return json.dumps({'fabrications':[]})
    it=int(re.search(r'Iteration (\d) of',user).group(1))
    return IMPROVED if it==1 else user.split('CURRENT VERSION:')[1].split('NON-NEGOTIABLE')[0].strip()

n=load_core(); n['gpt']=gpt; n['jparse']=json.loads
logs=[]
best,score,rep = n['improvement_loop'](WEAK,KW,'tech','data analyst','mid',
    {'weakBullets':['Responsible for making reports for the management team']},
    lambda e: logs.append(e.get('msg','')) if e.get('type')=='log' else None)
print('\n'.join(m for m in logs if m))
print()
check('score improved', score > base, f"{base} -> {score}")
check('improvement is meaningful', score-base >= 8, f"only +{score-base}")
check('rewrite was kept', 'Built recurring reports' in best, 'good rewrite rejected')
check('no unsupported kw added', not any(k in best.lower() for k in ('python','tableau','a/b testing')),
      'fabricated a skill')
check('education preserved', 'University of Houston' in best)
summary()
