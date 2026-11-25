// Reads a list of configs as JSON on stdin and prints the browser model's results as JSON.
// Used by tests/test_parity.py to check the Python companion gives identical numbers.
'use strict';
const { loadModel } = require('./load_model');
const M = loadModel();

let input = '';
process.stdin.on('data', (d) => { input += d; });
process.stdin.on('end', () => {
  const configs = JSON.parse(input);
  const out = configs.map((over) => {
    const cfg = Object.assign({}, M.DEFAULT_CONFIG, over);
    const r = M.run(cfg);
    const g = r.grid;
    return {
      instances: r.instances,
      summary: r.summary,
      policies: r.policies,
      grid: { avg: g.avg, marg: g.marg, code: g.code, demand: g.demand, curtail: g.curtail }
    };
  });
  process.stdout.write(JSON.stringify({ presets: M.PRESETS, jobs: M.DEFAULT_JOBS, results: out }));
});
