import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import *
import json, re
print("-- ROUND 7: real resume, full loop --")
import os, glob
try:
    import pdfplumber  # noqa: F401
except ImportError:
    print("  SKIP - pdfplumber not installed (test-only dependency; APEX itself needs none).")
    print("ALL PASS")
    raise SystemExit(0)
_pdfs = glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', '*.pdf'))
if not _pdfs:
    print("  SKIP - no fixture PDF in tests/fixtures/. Drop a resume PDF there to enable this test.")
    print("ALL PASS")
    raise SystemExit(0)
ORIG = pdf_text(_pdfs[0])
ns = load_core()
prot = ns['extract_protected'](ORIG)
print("  protected:", list(prot['sections'].keys()))
check('licenses detected in real resume', any('LICEN' in h.upper() for h in prot['sections']),
      f"got {list(prot['sections'].keys())}")
check('languages detected', any('LANGUAG' in h.upper() for h in prot['sections']) or
      any('gujarati' in l.lower() for l in prot['lines']), 'languages not protected')

KW=['patient care','rehabilitation','manual therapy','treatment planning','exercise programs',
    'documentation','patient education','gait training','therapeutic exercise','assessment',
    'telehealth','virtual therapy','remote patient monitoring','healthcare regulations','team collaboration']

# Simulate the real failure: model drops licenses AND adds telehealth
def gpt(system,user,max_tokens=3000,temp=0.3):
    if 'evidence auditor' in system:
        kws=json.loads(user.split('KEYWORDS:')[1].split('RESUME:')[0].strip())
        bad=[k for k in kws if any(x in k for x in ('telehealth','virtual','remote'))]
        return json.dumps({'supported':[k for k in kws if k not in bad],'unsupported':bad})
    if 'fraud auditor' in system:
        cand=user.split('REWRITTEN:')[1].lower()
        return json.dumps({'fabrications':[f'"{t}" - not in original' for t in
                          ('telehealth','virtual therapy') if t in cand]})
    it=int(re.search(r'Iteration (\d) of',user).group(1))
    if it==1:  # the historical bad output
        t=re.sub(r'LICENSES & CERTIFICATIONS[\s\S]*?(?=PROFESSIONAL EXPERIENCE)','',ORIG)
        return t.replace('Experienced in patient evaluation','Experienced in telehealth, virtual therapy, and patient evaluation')
    if it==2:  # honest improvement
        return ORIG.replace('Instruct PT and PTA students','Instructed PT and PTA students')
    return ORIG

n=load_core(); n['gpt']=gpt; n['jparse']=json.loads
logs=[]
best,score,rep = n['improvement_loop'](ORIG,KW,'healthcare','physical therapist','senior',{},
                                       lambda e: logs.append(e.get('msg','')) if e.get('type')=='log' else None)
print('\n'.join(m for m in logs if m))
print()
check('telehealth NOT in output', 'telehealth' not in best.lower())
check('virtual therapy NOT in output', 'virtual therapy' not in best.lower())
check('licenses survive', 'State of Texas' in best, 'LICENSE LOST')
check('BLS survives', 'BLS' in best or 'Basic Life Support' in best)
check('languages survive', 'Gujarati' in best)
check('citizenship survives', 'Citizen' in best)
check('education range survives', '2014' in best)
check('fabrication was blocked', rep['rejected_fabrication']>=1, f"blocked {rep['rejected_fabrication']}")
check('gaps routed to report', any('telehealth' in g for g in rep['unsupported']))
check('score is measured int', isinstance(score,int) and 0<score<=100, score)
summary()
