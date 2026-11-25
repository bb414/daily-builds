// Runs the browser app's model in Node and prints the result as JSON.
// Usage: node tests/run_model.js '{"seed": 7, "zombies": 0.5}'
'use strict';
const { loadModel } = require('./load_model.js');

const M = loadModel();
const settings = JSON.parse(process.argv[2] || '{}');
const r = M.runLab(settings);
const out = {};
for (const k of Object.keys(r)) if (k !== 'crm') out[k] = r[k];
out.sample = r.crm.history.slice(0, 40).concat(r.crm.history.slice(-10)).map(function (rec) {
  const c = {};
  for (const k of Object.keys(rec)) if (k !== 'truth') c[k] = rec[k];
  return c;
});
out.random = (function () { const g = M.mulberry32(12345); const a = []; for (let i = 0; i < 5; i++) a.push(g()); return a; })();
out.mix = [M.mix(0, 0), M.mix(2026, 1), M.mix(4294967295, 1000123)];
if (process.argv[3]) out.robustness = M.robustness(settings, Number(process.argv[3]));
process.stdout.write(JSON.stringify(out));
