// Reads a JSON list of jobs on stdin and prints the browser model's answers.
// Used by tests/test_parity.py to check the Python and JavaScript versions agree.
'use strict';
const { loadModel } = require('./load_model.js');

const M = loadModel();
let input = '';
process.stdin.on('data', (chunk) => { input += chunk; });
process.stdin.on('end', () => {
  const out = JSON.parse(input).map((job) => {
    if (job.normalise) return M.normaliseParams(job.normalise);
    if (job.network) {
      const n = M.buildNetwork(job.network);
      return { adj: n.adj, team: n.team, need: n.need, suit: n.suit, betweenness: n.betweenness, degree: n.degree,
        outsideShare: n.outsideShare, teamTies: n.teamTies };
    }
    if (job.compare) { const c = M.compareStrategies(job.compare); return { compare: c, why: M.explain(c) }; }
    throw new Error('Unknown job');
  });
  process.stdout.write(JSON.stringify(out));
});
