// Reads a JSON list of settings on stdin and prints the browser model's analyse() output for each.
// Used by tests/test_parity.py to check the Python and JavaScript versions agree.
'use strict';
const { loadModel } = require('./load_model.js');

const M = loadModel();
let input = '';
process.stdin.on('data', (chunk) => { input += chunk; });
process.stdin.on('end', () => {
  const configs = JSON.parse(input);
  const out = configs.map((c) => {
    if (c.__compare) return M.compareWorkflows(c.__compare);
    if (c.__sensitivity) return M.sensitivity(c.__sensitivity);
    if (c.__explain) return M.explain(M.analyse(c.__explain));
    return M.analyse(c);
  });
  process.stdout.write(JSON.stringify(out));
});
