import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import *
ns = load_core()
EX, CK, RS = ns['extract_protected'], ns['check_protected'], ns['restore_protected']

print("-- ROUND 2: protected content across resume shapes --")

cases = {
 'clinician': """JANE DOE, PT, DPT
Austin, TX | j@x.com | U.S. Citizen
SUMMARY
Therapist.
LICENSES & CERTIFICATIONS
Licensed Physical Therapist - State of Texas
Basic Life Support (BLS) Certification
EXPERIENCE
PT - Clinic
- Treated patients
EDUCATION
DPT, UT Austin 2018
LANGUAGES
English, Spanish""",

 'engineer': """SAM LEE
sam@x.com
CERTIFICATIONS
AWS Certified Solutions Architect - 2024
CISSP - 2023
EXPERIENCE
Engineer - Corp
- Built systems
EDUCATION
BS CS 2019
SECURITY CLEARANCE
Active TS/SCI""",

 'lowercase headers': """maria cruz
m@x.com
licenses and certifications
RN License - State of California
experience
Nurse - Hospital
- Cared for patients
education
BSN 2020""",

 'no protected': """BOB SMITH
b@x.com
EXPERIENCE
Dev - Co
- Wrote code
SKILLS
python""",
}

for name, txt in cases.items():
    p = EX(txt)
    print(f"\n  [{name}] sections={list(p['sections'].keys())} lines={len(p['lines'])}")
    if name == 'clinician':
        check('clinician: licenses found', any('LICEN' in h.upper() for h in p['sections']))
        check('clinician: languages found', any('LANGUAG' in h.upper() for h in p['sections']))
    if name == 'engineer':
        check('engineer: certs found', any('CERTIF' in h.upper() for h in p['sections']))
        check('engineer: clearance found', any('CLEARANCE' in h.upper() for h in p['sections']))
    if name == 'lowercase headers':
        check('lowercase: licenses found', any('licen' in h.lower() for h in p['sections']),
              f"got {list(p['sections'].keys())}")
    if name == 'no protected':
        check('no protected: no false positives', len(p['sections'])==0 and len(p['lines'])==0,
              f"got {p['sections']} {p['lines']}")

# round trip: strip a section, verify detect + restore
src = cases['clinician']
stripped = src.replace("LICENSES & CERTIFICATIONS\nLicensed Physical Therapist - State of Texas\nBasic Life Support (BLS) Certification\n","")
p = EX(src); d = CK(stripped, p)
check('detects removal', 'LICENSES & CERTIFICATIONS' in d['dropped_sections'], f"got {d['dropped_sections']}")
fixed = RS(stripped, p, d)
check('restores content', 'State of Texas' in fixed and 'BLS' in fixed)
check('restore idempotent', not CK(fixed,p)['dropped_sections'], f"still {CK(fixed,p)['dropped_sections']}")
# restoring twice must not duplicate
d2 = CK(fixed,p); fixed2 = RS(fixed,p,d2)
check('no duplication', fixed2.count('Basic Life Support')<=1, f"count={fixed2.count('Basic Life Support')}")
# reworded but present content must NOT be flagged as dropped
reworded = src.replace('Licensed Physical Therapist - State of Texas','Physical Therapist License, Texas')
check('tolerates rewording', 'LICENSES & CERTIFICATIONS' not in CK(reworded,EX(src))['dropped_sections'],
      'flagged a reworded-but-present license')
summary()
