// Reads a JSON list of jobs on stdin, runs each through the app's model, prints the results as JSON.
// Used by tests/test_parity.py to check the Python port gives identical answers.
'use strict';
const { loadModel } = require('./load_model');
const M = loadModel();
let raw = '';
process.stdin.on('data', function (c) { raw += c; });
process.stdin.on('end', function () {
  const jobs = JSON.parse(raw);
  const out = jobs.map(function (job) {
    if (job.kind === 'analyse') return M.analyse(job.input);
    if (job.kind === 'evaluate') return M.evaluatePlan(job.input, job.ids);
    if (job.kind === 'toProb') return job.values.map(M.toProb);
    if (job.kind === 'fromProb') return job.values.map(M.fromProb);
    if (job.kind === 'catalogue') return M.DATA;
    throw new Error('Unknown job ' + job.kind);
  });
  process.stdout.write(JSON.stringify(out));
});
