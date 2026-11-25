// Reads configs and curve requests as JSON on stdin and prints the browser model's results as JSON.
// Used by tests/test_parity.py to check the Python companion gives identical numbers.
'use strict';
const { loadModel } = require('./load_model');
const M = loadModel();

let input = '';
process.stdin.on('data', (d) => { input += d; });
process.stdin.on('end', () => {
  const payload = JSON.parse(input);
  const out = payload.configs.map((over) => {
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
  const curves = payload.curves.map((c) => M.curve(Object.assign({}, M.DEFAULT_CONFIG, c.config), c.field, c.values));
  const rb = M.robustness(Object.assign({}, M.DEFAULT_CONFIG, payload.robustness.config), payload.robustness.seeds);
  const ex = M.run(Object.assign({}, M.DEFAULT_CONFIG, payload.explain.config));
  const explain = payload.explain.indices.map((i) => M.explainRun(ex, i));
  const csvText = M.formatJobsCsv(payload.csvJobs);
  process.stdout.write(JSON.stringify({
    presets: M.PRESETS, jobs: M.DEFAULT_JOBS, results: out, curves: curves, robustness: rb, explain: explain,
    csvText: csvText, csvParsed: M.parseJobsCsv(csvText).jobs
  }));
});
