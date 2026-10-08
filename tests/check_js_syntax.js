// Parse every inline <script> in index.html. A syntax error in the single-file
// SPA blanks the whole app, so this runs first in run_all.py.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const re = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi;
let m, n = 0, fails = 0;
while ((m = re.exec(html))) {
  n++;
  const line = html.slice(0, m.index).split('\n').length;
  try { new vm.Script(m[1], { filename: `index.html:<script #${n} at line ${line}>` }); console.log(`  ok   inline script #${n} (line ${line})`); }
  catch (e) { fails++; console.log(`  FAIL inline script #${n} (line ${line}): ${e.message}`); }
}
if (!n) { console.log('  FAIL no inline scripts found'); fails++; }
console.log(fails ? `\n${fails} FAILURES` : '\nALL PASS');
process.exit(fails ? 1 : 0);
