sys_path=None
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import *
ns = load_core()
S, P, N = ns['ats_score'], ns['_present'], ns['_norm']

print("-- ROUND 1: scorer edge cases --")
kw = ['python','sql','docker']
# empty / junk input must not crash
for label, txt in [('empty',''), ('whitespace','   \n\n  '), ('one word','hi'),
                   ('no sections','just a paragraph of text with python and sql in it')]:
    try:
        sc,bd = S(txt, kw); check(f'no crash: {label}', isinstance(sc,int) and 0<=sc<=100, f'got {sc}')
    except Exception as e:
        check(f'no crash: {label}', False, repr(e))
# empty keyword list
try:
    sc,_=S('EXPERIENCE\n- Built things', []); check('empty kw list', 0<=sc<=100, f'got {sc}')
except Exception as e: check('empty kw list', False, repr(e))
# keyword list with junk
try:
    sc,_=S('EXPERIENCE\n- Built things', [None,'','  ',123]); check('junk kw list', 0<=sc<=100)
except Exception as e: check('junk kw list', False, repr(e))
# determinism
a=S('EXPERIENCE\n- Built pipelines in python',kw)[0]; b=S('EXPERIENCE\n- Built pipelines in python',kw)[0]
check('deterministic', a==b, f'{a} vs {b}')
# keyword stuffing should not reach 100 on its own
stuffed = 'SKILLS\n' + ', '.join(kw*20)
sc,bd = S(stuffed, kw)
check('stuffing capped', sc < 85, f'stuffed scored {sc}')
# a real resume beats a stub
stub='John Doe\njohn@x.com\nSUMMARY\nHi\nEXPERIENCE\n- did stuff\nEDUCATION\nBS\nSKILLS\npython'
good='John Doe\njohn@x.com | 555-123-4567\nSUMMARY\nEngineer.\nEXPERIENCE\nDev - Acme\n- Built python pipelines processing 4M rows\n- Designed sql schemas for 12 services\n- Deployed docker containers cutting spin-up 40%\nEDUCATION\nBS CS\nSKILLS\npython, sql, docker'
check('good > stub', S(good,kw)[0] > S(stub,kw)[0], f"{S(good,kw)[0]} vs {S(stub,kw)[0]}")
# presence matching
check('stem match', P('patient education', N('educated patients and families')))
check('no false positive', not P('telehealth', N('outpatient clinic sessions')))
check('exact match', P('docker', N('deployed docker containers')))
summary()
