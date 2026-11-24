// Reads a JSON list of settings on stdin and prints the browser model's analyse() output for each.
// Used by tests/test_parity.py to check the Python and JavaScript versions agree.
'use strict';
const { loadModel } = require('./load_model.js');

const M = loadModel();
let input = '';
process.stdin.on('data', (chunk) => { input += chunk; });
process.stdin.on('end', () => {
  const configs = JSON.parse(input);
  const out = configs.map((c) => (c.__compare ? M.compareWorkflows(c.__compare) : M.analyse(c)));
  process.stdout.write(JSON.stringify(out));
});
