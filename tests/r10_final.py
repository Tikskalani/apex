import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import *
import json, re
print("-- ROUND 10: full regression + robustness --")
ns=load_core()

# Unicode / non-English / weird whitespace must not crash anything
odd = ["JOSÉ MARTÍNEZ\nLICENCIAS\nLicensed PT — Texas\nEXPERIENCE\n- Trató pacientes",
       "李明\nCERTIFICATIONS\nAWS Certified\nEXPERIENCE\n- Built systems",
       "A\tB\r\nC\u00a0D\nEXPERIENCE\n- did\u2014things",
       "x"*20000]
for i,t in enumerate(odd):
    try:
        ns['extract_protected'](t); ns['ats_score'](t,['aws']); ns['split_sections'](t)
        check(f'odd input {i} survives', True)
    except Exception as e:
        check(f'odd input {i} survives', False, repr(e))

# strip_commentary robustness
sc = ns['strip_commentary']
check('strips preamble', 'Here is' not in sc("Here is the improved resume:\n\nJOHN\n- did"))
check('strips postamble', 'Let me know' not in sc("JOHN\n- did\n\nLet me know if you want changes"))
check('strips fences', '```' not in sc("```\nJOHN\n- did\n```"))
check('keeps clean text intact', sc("JOHN DOE\nEXPERIENCE\n- Built things")=="JOHN DOE\nEXPERIENCE\n- Built things")
check('non-string safe', sc(None)=='' and sc(42)=='')
check('does not eat a real bullet', 'Here is a summary of findings' in sc("JOHN\n- Here is a summary of findings for clients"))

# added_unsupported
au = ns['added_unsupported']
check('detects added kw', au('resume with sql','resume with sql and telehealth',['telehealth'])==['telehealth'])
check('ignores pre-existing', au('resume telehealth','resume telehealth',['telehealth'])==[])
check('empty unsupported safe', au('a','b',[])==[])

# restore is stable across repeated application
src="X\nLICENSES\nRN License — CA\nEXPERIENCE\n- Cared"
p_=ns['extract_protected'](src); stripped="X\nEXPERIENCE\n- Cared"
r1=ns['restore_protected'](stripped,p_,ns['check_protected'](stripped,p_))
r2=ns['restore_protected'](r1,p_,ns['check_protected'](r1,p_))
check('restore stable', r1==r2 or r2.count('RN License')==1, f"count {r2.count('RN License')}")
summary()
