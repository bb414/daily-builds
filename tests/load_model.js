// Loads the model block from app/index.html so Node.js can run it outside the browser.
'use strict';
const fs = require('fs');
const path = require('path');

function loadModel() {
  const html = fs.readFileSync(path.join(__dirname, '..', 'app', 'index.html'), 'utf8');
  const start = html.indexOf('/* MODEL START */');
  const end = html.indexOf('/* MODEL END */');
  if (start < 0 || end < 0) throw new Error('Model markers not found in app/index.html');
  const code = html.slice(start, end);
  const mod = { exports: {} };
  // The block registers itself on module.exports when it is available.
  new Function('module', code).call({}, mod);
  return mod.exports;
}

module.exports = loadModel();

// Used by tests/test_agreement.py: node tests/load_model.js < request.json
if (require.main === module) {
  const M = module.exports;
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const out = input.map((job) => {
    if (job.fn === 'compare') return M.compare(job.config, job.seed);
    if (job.fn === 'simulate') return M.simulate(job.config, job.seed, job.opts || {});
    if (job.fn === 'placements') return M.placements(job.config, job.seed);
    if (job.fn === 'bank') return M.bankSavings(job.config, job.seed, undefined, job.cut === null ? undefined : job.cut);
    if (job.fn === 'validate') return M.validate(M.normalise(job.config));
    if (job.fn === 'normalise') return M.normalise(job.config);
    throw new Error('Unknown function ' + job.fn);
  });
  process.stdout.write(JSON.stringify(out));
}
