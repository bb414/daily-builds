// Loads the MODEL block out of app/index.html so the browser app's logic can run in Node.
// Used directly by app_model.test.js, and as a command by the Python agreement tests:
//   echo '[{"fn": "analyse", "args": [{}]}]' | node tests/model_harness.js
'use strict';
const fs = require('fs');
const path = require('path');

function loadModel() {
  const html = fs.readFileSync(path.join(__dirname, '..', 'app', 'index.html'), 'utf8');
  const start = html.indexOf('/* MODEL START */');
  const end = html.indexOf('/* MODEL END */');
  if (start < 0 || end < 0) throw new Error('MODEL block not found in app/index.html');
  const mod = { exports: {} };
  new Function('module', html.slice(start, end))(mod);
  return mod.exports;
}

module.exports = { loadModel };

if (require.main === module) {
  const M = loadModel();
  const calls = JSON.parse(fs.readFileSync(0, 'utf8'));
  const results = calls.map((call) => M[call.fn].apply(null, call.args || []));
  process.stdout.write(JSON.stringify(results, (key, value) => {
    if (value === Infinity) return 'Infinity';
    if (value === -Infinity) return '-Infinity';
    return value;
  }));
}
