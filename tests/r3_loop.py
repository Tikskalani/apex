import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import *
import json, re
ns = load_core()

print("-- ROUND 3: loop behaviour under adversarial model output --")
ORIG = """JANE DOE, PT
Austin, TX | j@x.com | U.S. Citizen
SUMMARY
Physical therapist.
LICENSES & CERTIFICATIONS
Licensed Physical Therapist - State of Texas
Basic Life Support (BLS) Certification
EXPERIENCE
Physical Therapist - Clinic
- Treated patients with manual therapy
- Documented progress notes
EDUCATION
DPT, UT Austin 2018
LANGUAGES
English, Spanish"""

KW = ['manual therapy','documentation','patient care','telehealth','gait training']

def run(rewriter, auditor=None, name=''):
    log=[]
    def gpt(system, user, max_tokens=3000, temp=0.3):
        if 'evidence auditor' in system:
            kws=json.loads(user.split('KEYWORDS:')[1].split('RESUME:')[0].strip())
            bad=[k for k in kws if 'telehealth' in k]
            return json.dumps({'supported':[k for k in kws if k not in bad],'unsupported':bad})
        if 'fraud auditor' in system:
            if auditor: return auditor(user)
            cand=user.split('REWRITTEN:')[1]
            return json.dumps({'fabrications':['"telehealth" - not in original'] if 'telehealth' in cand.lower() else []})
        it=int(re.search(r'Iteration (\d) of',user).group(1))
        return rewriter(it, user)
    n2 = load_core(); n2['gpt']=gpt; n2['jparse']=json.loads
    def emit(e):
        if e.get('type')=='log': log.append(e['msg'])
    best,score,rep = n2['improvement_loop'](ORIG,KW,'healthcare','PT','senior',{},emit)
    return best,score,rep,log

# A. model returns empty string every time
b,s_,r,l = run(lambda it,u: '', name='empty')
check('empty output -> original kept', b==ORIG, 'original was replaced by empty')
check('empty output -> score sane', 0<s_<=100)

# B. model returns None
b,s_,r,l = run(lambda it,u: None)
check('None output -> original kept', b==ORIG)

# C. model returns commentary wrapper
b,s_,r,l = run(lambda it,u: "Here is the improved resume:\n\n"+ORIG+"\n\nLet me know if you need changes!")
check('commentary not silently kept as-is', 'Let me know if you need' not in b, 'commentary leaked into output')

# D. model drops licenses every time
def drop(it,u): return ORIG.replace("LICENSES & CERTIFICATIONS\nLicensed Physical Therapist - State of Texas\nBasic Life Support (BLS) Certification\n","")
b,s_,r,l = run(drop)
check('dropped licenses restored', 'State of Texas' in b and 'BLS' in b, 'licenses lost')

# E. model fabricates every time
def fab(it,u): return ORIG.replace('Physical therapist.','Physical therapist with telehealth expertise.')
b,s_,r,l = run(fab)
check('all-fabrication -> original kept', 'telehealth' not in b.lower(), 'fabrication shipped')
check('fabrication counted', r['rejected_fabrication']==3, f"got {r['rejected_fabrication']}")
check('ceiling explained', any('ceiling' in m for m in l), 'no explanation when nothing improved')

# F. auditor itself errors -> must fail closed
def bad_auditor(u): raise RuntimeError('api down')
b,s_,r,l = run(lambda it,u: ORIG.replace('Treated','Delivered'), auditor=bad_auditor)
check('audit failure -> reject (fail closed)', r['rejected']>0, 'accepted an unaudited rewrite')

# G. legitimate improvement is accepted
def good(it,u):
    return ORIG.replace('- Treated patients with manual therapy',
                        '- Delivered manual therapy to 40 patients weekly, restoring mobility').replace(
                        '- Documented progress notes','- Documented progress notes for 40 patients weekly')
b,s_,r,l = run(good, auditor=lambda u: json.dumps({'fabrications':[]}))
check('genuine improvement accepted', 'Delivered manual therapy' in b, 'good rewrite rejected')
check('licenses survive good path', 'State of Texas' in b)
summary()
