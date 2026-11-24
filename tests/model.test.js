// Tests for the browser app's model, run in Node.js: node --test "tests/*.test.js"
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadModel } = require('./load_model.js');

const M = loadModel();
const small = (extra) => Object.assign(M.presetParams('assistant'), { people: 90, teams: 6, runs: 10, weeks: 30 }, extra || {});
const plain = (x) => JSON.parse(JSON.stringify(x));

test('random numbers are reproducible and in range', () => {
  const a = M.makeRng(5), b = M.makeRng(5);
  const xs = Array.from({ length: 2000 }, () => a.uniform());
  const ys = Array.from({ length: 2000 }, () => b.uniform());
  assert.deepEqual(xs, ys);
  assert.ok(xs.every((x) => x >= 0 && x < 1));
  assert.ok(Math.abs(xs.reduce((s, x) => s + x, 0) / xs.length - 0.5) < 0.03);
});

test('settings are cleaned up: defaults, ranges, team and department limits', () => {
  const p = M.normaliseParams({ people: 40, teams: 30, departments: 6, champions: 'many', socialProof: 2, strategy: 'magic' });
  assert.equal(p.teams, 13);
  assert.equal(p.departments, 6);
  assert.equal(p.champions, M.DEFAULTS.champions);
  assert.equal(p.socialProof, 0.6);
  assert.equal(p.strategy, M.DEFAULTS.strategy);
  assert.equal(M.normaliseParams({ teams: 2, departments: 5 }).departments, 2);
  for (const raw of [' ', '0x10', [9], true, '1e999', '12abc']) assert.equal(M.normaliseParams({ champions: raw }).champions, M.DEFAULTS.champions);
  assert.equal(M.normaliseParams({ champions: ' 12 ' }).champions, 12);
});

test('every preset survives normalising unchanged', () => {
  for (const key of Object.keys(M.PRESETS)) {
    const p = M.presetParams(key);
    for (const [k, v] of Object.entries(M.PRESETS[key].params)) assert.equal(p[k], v, key + '.' + k);
  }
});

test('the synthetic organisation has the right shape', () => {
  const p = M.normaliseParams({ people: 100, teams: 7, departments: 3, seed: 3 });
  const net = M.buildNetwork(p);
  assert.equal(net.size, 100);
  assert.equal(net.teams, 7);
  assert.deepEqual(Array.from(net.teamSize), [15, 15, 14, 14, 14, 14, 14]);
  let ties = 0;
  for (let i = 0; i < net.size; i++) {
    assert.ok(net.adj[i].length > 0, 'nobody is isolated');
    for (const j of net.adj[i]) { assert.ok(net.adj[j].includes(i), 'ties are mutual'); assert.notEqual(i, j); }
    for (let k = 1; k < net.adj[i].length; k++) assert.ok(net.adj[i][k] > net.adj[i][k - 1], 'sorted, no duplicates');
    ties += net.adj[i].length;
  }
  assert.equal(ties / 2, net.edges);
  assert.ok(net.outsideShare > 0 && net.outsideShare < 0.5);
  assert.ok(Math.abs(net.meanDegree - (5 + 1.2 + 0.4)) < 1.2, 'mean degree near the settings: ' + net.meanDegree);
  assert.ok(net.need.every((x) => x >= 0.5 && x < 1.5));
  assert.deepEqual(plain(M.buildNetwork(p).adj), plain(net.adj));
});

test('betweenness matches a hand-worked path and star', () => {
  // Path 0-1-2-3: pairs through 1 are (0,2),(0,3); through 2 are (0,3),(1,3). Each pair counted twice.
  assert.deepEqual(Array.from(M.betweenness([[1], [0, 2], [1, 3], [2]])), [0, 4, 4, 0]);
  // Star with centre 0 and three leaves: three pairs of leaves, counted twice.
  assert.deepEqual(Array.from(M.betweenness([[1, 2, 3], [0], [0], [0]])), [6, 0, 0, 0]);
});

test('each strategy picks the right kind of champion', () => {
  const p = M.normaliseParams({ people: 120, teams: 8, departments: 2, champions: 8, seed: 11 });
  const net = M.buildNetwork(p);
  const pick = (s) => Array.from(M.pickChampions(net, 8, s, M.makeRng(1)));
  const hubs = pick('hubs');
  const minHub = Math.min(...hubs.map((v) => net.degree[v]));
  assert.ok(net.degree.filter((d, v) => !hubs.includes(v)).every((d) => d <= minHub));
  const bridges = pick('bridges');
  const minB = Math.min(...bridges.map((v) => net.betweenness[v]));
  assert.ok(net.betweenness.filter((b, v) => !bridges.includes(v)).every((b) => b <= minB));
  const cluster = pick('cluster');
  assert.equal(new Set(cluster.map((v) => net.team[v])).size, 1, 'one team first stays in one team');
  const spread = pick('spread');
  assert.equal(new Set(spread.map((v) => net.team[v])).size, 8, 'one per team covers eight teams');
  for (const s of M.STRATEGY_KEYS) { const c = pick(s); assert.equal(new Set(c).size, 8, s + ' picks distinct people'); }
  assert.throws(() => M.pickChampions(net, 3, 'nonsense', M.makeRng(1)), /Unknown strategy/);
});

test('more champions than people in a team spill into the next team, and one per team wraps round', () => {
  const p = M.normaliseParams({ people: 40, teams: 4, champions: 15 });
  const net = M.buildNetwork(p);
  const cluster = Array.from(M.pickChampions(net, 15, 'cluster', M.makeRng(1)));
  assert.equal(new Set(cluster.map((v) => net.team[v])).size, 2);
  const spread = Array.from(M.pickChampions(net, 15, 'spread', M.makeRng(1)));
  assert.equal(spread.length, 15);
  assert.equal(Array.from(M.pickChampions(net, 99, 'hubs', M.makeRng(1))).length, 40);
});

test('rollouts are reproducible and keep champions using the tool', () => {
  const p = M.normaliseParams(small());
  const net = M.buildNetwork(p);
  const champs = M.pickChampions(net, p.champions, 'spread', M.makeRng(1));
  const a = M.simulateRollout(net, p, champs, M.makeRng(9), true);
  const b = M.simulateRollout(net, p, champs, M.makeRng(9), true);
  assert.deepEqual(plain(a.curve), plain(b.curve));
  assert.equal(a.curve.length, p.weeks + 1);
  for (const week of a.states) for (const c of champs) assert.equal(week[c], 1);
  assert.ok(a.ever >= a.final);
});

test('nobody adopts without champions, peers or prompts, and nobody it does not suit ever adopts', () => {
  const p = M.normaliseParams(small({ spontaneous: 0, champions: 1, peerPull: 0.4, socialProof: 0 }));
  const net = M.buildNetwork(p);
  const r = M.simulateRollout(net, p, [], M.makeRng(3), false);
  assert.equal(r.final, 0);
  const q = M.normaliseParams(small({ spontaneous: 0.03, fit: 0.3, weeks: 104, lapse: 0 }));
  const r2 = M.simulateRollout(net, q, [], M.makeRng(3), true);
  const last = r2.states[r2.states.length - 1];
  for (let i = 0; i < net.size; i++) if (net.suit[i] >= q.fit) assert.equal(last[i], 0);
});

test('with no social proof needed and strong pull, use spreads to everyone it suits', () => {
  const p = M.normaliseParams(small({ socialProof: 0, peerPull: 0.4, lapse: 0, fit: 1, weeks: 60 }));
  const res = M.runStrategy(M.buildNetwork(p), p, 'spread');
  assert.ok(res.finalMean > 0.98);
  assert.equal(res.reachShare, 1);
});

test('summaries are consistent', () => {
  const p = M.normaliseParams(small());
  const res = M.runStrategy(M.buildNetwork(p), p, 'hubs');
  assert.equal(res.curveMean.length, p.weeks + 1);
  for (let k = 0; k <= p.weeks; k++) assert.ok(res.curveLow[k] <= res.curveHigh[k] + 1e-12);
  assert.ok(Math.abs(res.curveMean[p.weeks] - res.finalMean) < 1e-12);
  assert.ok(res.reachShare >= 0 && res.reachShare <= 1);
});

test('the default scenario shows the main finding', () => {
  const c = M.compareStrategies(M.presetParams('assistant'));
  assert.equal(c.ranking[0], 'spread');
  assert.equal(c.ranking[c.ranking.length - 1], 'cluster');
  const text = M.explain(c).join(' ');
  assert.match(text, /One per team does best/);
  assert.match(text, /pilot team is the weakest/);
  assert.doesNotMatch(text, /\u2014/);
});

test('extreme settings finish and give sensible numbers', () => {
  const hi = {}; const lo = {};
  for (const s of M.PARAMS) { hi[s.key] = s.max; lo[s.key] = s.min; }
  for (const p of [hi, lo]) {
    const t0 = Date.now();
    const c = M.compareStrategies(Object.assign({}, p, { runs: 10 }));
    assert.ok(Date.now() - t0 < 20000);
    for (const r of c.results) assert.ok(r.finalMean >= 0 && r.finalMean <= 1);
    assert.ok(M.explain(c).length >= 1);
  }
});
