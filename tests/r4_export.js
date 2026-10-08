// Extract the ATS engine from index.html and test it in isolation.
const fs=require('fs');
const html=fs.readFileSync(require('path').join(__dirname,'..','index.html'),'utf8');
const m=html.match(/const ATS = \{[\s\S]*?\n\};/);
if(!m){console.log('FAIL: ATS engine not found');process.exit(1);}
const ATS = eval('(' + m[0].replace(/^const ATS = /,'').replace(/;s*$/,'') + ')');
let fails=[];
const check=(n,c,d)=>{ if(c)console.log('  ok   '+n); else {console.log('  FAIL '+n+'  '+(d||'')); fails.push(n);} };

console.log('── ROUND 4: export field fidelity ──');

// Full struct as the parser now emits it
const full={
  name:'Leena Varma, PT', title:'Licensed Physical Therapist',
  email:'t@x.com', phone:'555-010-0199', location:'Sugar Land, TX',
  authorization:'U.S. Citizen — authorized to work without sponsorship',
  linkedin:'linkedin.com/in/lvarma', website:'',
  summary:'Texas-licensed physical therapist.',
  experience:[{title:'PT & PTA Tutor',company:'Northstar Tutoring',location:'Remote',start:'Nov 2023',end:'Present',
    bullets:['Instruct PT and PTA students across anatomy and kinesiology.','Design individualized study plans.']}],
  education:[{degree:'Bachelor of Physical Therapy',school:'Riverside College of Physiotherapy',
    location:'Nashik, Maharashtra, India',year:'2014 – 2018',gpa:''}],
  skills:{technical:['Patient evaluation','Manual therapy'],tools:[],soft:['Patient education']},
  certifications:[{name:'Licensed Physical Therapist',issuer:'State of Texas',year:''},
                  {name:'Basic Life Support (BLS) Certification',issuer:'',year:''}],
  languages:['English','Hindi','Gujarati'],
  projects:[], awards:[], additional:[{header:'PROFESSIONAL AFFILIATIONS',lines:['APTA Member']}]
};

const d=ATS.norm(full);
check('post-nominal kept', d.name==='Leena Varma, PT', d.name);
check('authorization kept', d.authorization.includes('U.S. Citizen'));
check('authorization in contact line', ATS.contactLine(d).includes('U.S. Citizen'));
check('certs normalised', d.certifications.length===2 && d.certifications[0].includes('State of Texas'), JSON.stringify(d.certifications));
check('languages kept', d.languages.length===3);
check('education range kept', d.education[0].year==='2014 – 2018');
check('education location kept', ATS.eduLine(d.education[0]).includes('Nashik'));
check('additional kept', d.additional.length===1);

// TXT is the readable proof that every field reaches output
let saved=null;
ATS.saveBlob=(blob,fn)=>{saved={fn:fn};};
global.Blob=function(parts){this.text=parts.join('');saved_text=parts.join('');};
let saved_text='';
ATS.saveBlob=(blob,fn)=>{saved={fn,text:blob.text};};
ATS.txt(full,'test');
const t=saved.text;
check('TXT: licenses present', t.includes('State of Texas')&&t.includes('BLS'), t.slice(0,200));
check('TXT: languages present', t.includes('Gujarati'));
check('TXT: authorization present', t.includes('U.S. Citizen'));
check('TXT: edu range present', t.includes('2014 – 2018'));
check('TXT: edu location present', t.includes('Nashik'));
check('TXT: additional present', t.includes('APTA Member'));
check('TXT: filename sane', /Leena_Varma.*\.txt$/.test(saved.fn), saved.fn);

// Degenerate inputs must not throw
[{},{name:'X'},{name:'X',experience:null,skills:null,certifications:'oops'},
 {name:'X',experience:[{title:null,bullets:null}]}].forEach((bad,i)=>{
  try{ ATS.txt(bad,'t'); check('degenerate struct '+i+' no throw',true);}
  catch(e){ check('degenerate struct '+i+' no throw',false,e.message);}
});

// String-form certifications (some parses return plain strings)
try{ ATS.txt({name:'X',certifications:['RN License — CA']},'t');
  check('string certs handled', saved.text.includes('RN License'));}
catch(e){check('string certs handled',false,e.message);}

console.log(fails.length?'\n'+fails.length+' FAILURES: '+fails.join(', '):'\nALL PASS');
