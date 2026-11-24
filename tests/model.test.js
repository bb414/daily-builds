// Tests for the browser app's model, run in Node.js: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadModel } = require('./load_model.js');

const M = loadModel();
const small = (extra) => Object.assign(M.presetParams('scam_teens'), { people: 60, rounds: 60 }, extra || {});

test('random numbers are reproducible and in range', () => {
  const a = M.makeRng(7), b = M.makeRng(7), c = M.makeRng(8);
  const xs = [], ys = [], zs = [];
  for (let i = 0; i < 1000; i++) { xs.push(a.uniform()); ys.push(b.uniform()); zs.push(c.uniform()); }
  assert.deepEqual(xs, ys);
  assert.notDeepEqual(xs, zs);
  assert.ok(xs.every((x) => x >= 0 && x < 1));
  const mean = xs.reduce((s, x) => s + x, 0) / xs.length;
  assert.ok(Math.abs(mean - 0.5) < 0.05);
});

test('normal draws have mean near 0 and sd near 1', () => {
  const r = M.makeRng(123);
  const xs = Array.from({ length: 20000 }, () => r.normal());
  const mean = xs.reduce((s, x) => s + x, 0) / xs.length;
  const sd = Math.sqrt(xs.reduce((s, x) => s + (x - mean) ** 2, 0) / xs.length);
  assert.ok(Math.abs(mean) < 0.03, 'mean ' + mean);
  assert.ok(Math.abs(sd - 1) < 0.03, 'sd ' + sd);
});

test('sigmoid and logit are inverses and stable at extremes', () => {
  for (const p of [0.01, 0.2, 0.5, 0.8, 0.99]) assert.ok(Math.abs(M.sigmoid(M.logit(p)) - p) < 1e-12);
  assert.equal(M.sigmoid(-1000), 0);
  assert.equal(M.sigmoid(1000), 1);
  assert.ok(isFinite(M.logit(0)) && isFinite(M.logit(1)));
});

test('calibration hits the target accuracy', () => {
  for (const target of [0.55, 0.7, 0.85, 0.99]) {
    for (const sd of [0.2, 1, 2]) {
      const mu = M.calibrateIntercept(target, sd);
      assert.ok(Math.abs(M.expectedAccuracy(mu, sd) - target) < 1e-9);
    }
  }
});

test('normaliseParams fills defaults, clamps and ignores junk', () => {
  const p = M.normaliseParams({ aiAccuracy: 2, humanAccuracy: 'abc', rounds: 33.4, workflow: 'nonsense', showConfidence: 'false', people: null });
  assert.equal(p.aiAccuracy, 0.99);
  assert.equal(p.humanAccuracy, M.DEFAULTS.humanAccuracy);
  assert.equal(p.rounds, 33);
  assert.equal(p.workflow, M.DEFAULTS.workflow);
  assert.equal(p.showConfidence, false);
  assert.equal(p.people, M.DEFAULTS.people);
  assert.equal(M.normaliseParams({ aiAccuracy: true }).aiAccuracy, M.DEFAULTS.aiAccuracy);
  assert.equal(M.normaliseParams({ rounds: Infinity }).rounds, M.DEFAULTS.rounds);
  assert.equal(M.normaliseParams({ rounds: -5 }).rounds, 20);
});

test('every preset is valid and inside the allowed ranges', () => {
  for (const key of Object.keys(M.PRESETS)) {
    const raw = M.PRESETS[key].params;
    const p = M.presetParams(key);
    for (const k of Object.keys(raw)) assert.equal(p[k], raw[k], key + '.' + k + ' was clamped or rejected');
  }
});

test('simulation is deterministic for a given seed and changes with the seed', () => {
  const a = M.simulate(small()), b = M.simulate(small()), c = M.simulate(small({ seed: 43 }));
  assert.equal(a.teamAccuracy, b.teamAccuracy);
  assert.deepEqual(a.series.skill, b.series.skill);
  assert.notEqual(a.teamAccuracy, c.teamAccuracy);
});

test('starting accuracy matches the setting for a large population', () => {
  const r = M.simulate(small({ people: 1000, rounds: 20, humanAccuracy: 0.75, skillSpread: 0.3 }));
  assert.ok(Math.abs(r.skillBefore - 0.75) < 0.01, 'skillBefore ' + r.skillBefore);
  assert.ok(Math.abs(r.aiRealisedAccuracy - r.params.aiAccuracy) < 0.01, 'AI ' + r.aiRealisedAccuracy);
});

test('workflows behave as described', () => {
  const none = M.simulate(small({ workflow: 'none' }));
  assert.equal(none.consultRate, 0);
  assert.equal(none.deferralRate, 0);
  assert.equal(none.teamAccuracy, none.humanAloneAccuracy);
  assert.equal(none.rescueRate, null);
  const hf = M.simulate(small({ workflow: 'human_first' }));
  assert.equal(hf.consultRate, 1);
  assert.equal(hf.deferralRate, 0);
  assert.equal(hf.engagementRate, 1);
  const af = M.simulate(small({ workflow: 'ai_first' }));
  assert.equal(af.consultRate, 1);
  assert.ok(af.deferralRate > 0.2);
  const req = M.simulate(small({ workflow: 'on_request' }));
  assert.ok(req.consultRate > 0 && req.consultRate < 1);
  assert.equal(req.deferralRate, 0);
});

test('nobody learns or forgets without feedback when thinking for themselves', () => {
  const r = M.simulate(small({ workflow: 'human_first', feedbackRate: 0 }));
  assert.ok(Math.abs(r.skillAfter - r.skillBefore) < 1e-12);
  assert.ok(Math.abs(r.trustEnd - r.params.initialTrust) < 1e-12);
});

test('rubber-stamping erodes skill when there is no feedback', () => {
  const r = M.simulate(small({ workflow: 'ai_first', feedbackRate: 0, decayRate: 0.005 }));
  assert.ok(r.skillAfter < r.skillBefore - 0.02);
});

test('a perfect-feedback, high-trust AI-first setup is a crutch; human first is not', () => {
  const base = small({ people: 200, rounds: 200, feedbackRate: 0.3, decayRate: 0.003, initialTrust: 0.8 });
  const af = M.analyse(Object.assign({}, base, { workflow: 'ai_first' }));
  const hf = M.analyse(Object.assign({}, base, { workflow: 'human_first' }));
  assert.equal(af.verdict.key, 'crutch');
  assert.ok(['helper', 'no_lift'].includes(hf.verdict.key));
  assert.ok(af.result.skillAfter < hf.result.skillAfter);
});

test('overconfident AI misleads people more often', () => {
  const calm = M.simulate(small({ workflow: 'human_first', aiOverconfidence: 0, people: 200 }));
  const loud = M.simulate(small({ workflow: 'human_first', aiOverconfidence: 1, people: 200 }));
  assert.ok(loud.misledRate > calm.misledRate);
});

test('classify follows the four quadrants', () => {
  const mk = (wf, team, skill) => ({ params: { workflow: wf }, teamAccuracy: team, skillAfter: skill });
  const ctrl = mk('none', 0.7, 0.7);
  assert.equal(M.classify(mk('ai_first', 0.8, 0.7), ctrl).key, 'helper');
  assert.equal(M.classify(mk('ai_first', 0.8, 0.65), ctrl).key, 'crutch');
  assert.equal(M.classify(mk('ai_first', 0.705, 0.7), ctrl).key, 'no_lift');
  assert.equal(M.classify(mk('ai_first', 0.69, 0.6), ctrl).key, 'liability');
  assert.equal(M.classify(ctrl, ctrl).key, 'baseline');
});

test('moving average', () => {
  assert.deepEqual(Array.from(M.movingAverage([1, 2, 3, 4], 2)), [1, 1.5, 2.5, 3.5]);
  assert.deepEqual(Array.from(M.movingAverage([], 3)), []);
});

test('extreme settings finish quickly and give finite numbers', () => {
  const p = Object.assign({}, M.DEFAULTS);
  for (const spec of M.PARAMS) p[spec.key] = spec.max;
  p.people = 1000; p.rounds = 500;
  const t0 = Date.now();
  const a = M.analyse(p);
  const ms = Date.now() - t0;
  assert.ok(ms < 8000, 'took ' + ms + 'ms');
  for (const k of ['teamAccuracy', 'skillBefore', 'skillAfter', 'trustEnd']) assert.ok(isFinite(a.result[k]), k);
  const q = Object.assign({}, M.DEFAULTS);
  for (const spec of M.PARAMS) q[spec.key] = spec.min;
  const b = M.analyse(q);
  assert.ok(isFinite(b.result.teamAccuracy));
});
