// Tests for the browser app's MODEL block, run with: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadModel } = require('./model_harness.js');

const M = loadModel();

test('every rule’s errors plus its accuracy add up to one', () => {
  let seed = 11;
  const rand = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
  for (let i = 0; i < 200; i++) {
    const p = {
      human: 0.5 + rand() * 0.49, ai: 0.5 + rand() * 0.49, overlap: rand() * 1.6 - 0.6,
      aiSignal: rand() * 4, humanSignal: rand() * 4, aiBias: rand() * 4 - 2, humanBias: rand() * 4 - 2,
      threshold: 0.5 + rand() * 0.49, deferRate: rand()
    };
    const a = M.analyse(p);
    M.POLICIES.forEach((k) => {
      const r = a.policies[k];
      assert.ok(Math.abs(r.team + r.shared + r.overErrors + r.underErrors - 1) < 1e-12);
      assert.ok(r.team <= a.ceiling + 1e-12, k + ' cannot beat the best possible rule');
    });
    assert.ok(a.policies.fixed.team <= a.best + 1e-12, 'a fixed rate never beats the better solo');
  }
});

test('the gain map has the right shape and matches single evaluations', () => {
  const g = M.gainGrid({ aiSignal: 2 }, 'optimal', 12);
  assert.equal(g.values.length, 12);
  assert.equal(g.gains.length, 12);
  g.gains.forEach((row) => assert.equal(row.length, 12));
  assert.equal(g.values[0], 0.5);
  assert.ok(Math.abs(g.values[11] - 0.99) < 1e-12);
  const one = M.evaluate({ aiSignal: 2, human: g.values[3], ai: g.values[7] }, 'optimal');
  assert.equal(g.gains[3][7], one.gain);
  M.gainGrid({}, 'fixed', 10).gains.forEach((row) => row.forEach((v) => assert.ok(v <= 1e-12)));
});

test('out of every 100 cases always adds up to 100 and matches the rates', () => {
  let seed = 12345;
  const next = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
  for (let i = 0; i < 300; i++) {
    const p = { human: 0.5 + next() * 0.49, ai: 0.5 + next() * 0.49, overlap: next() * 2 - 1,
      aiSignal: next() * 4, humanSignal: next() * 4, aiBias: next() * 4 - 2, humanBias: next() * 4 - 2,
      threshold: 0.5 + next() * 0.49, deferRate: next() };
    M.POLICIES.forEach((rule) => {
      const r = M.per100(p, rule);
      const total = M.OUTCOME_KEYS.reduce((s, k) => s + r.counts[k], 0);
      assert.equal(total, 100);
      M.OUTCOME_KEYS.forEach((k) => assert.ok(Math.abs(r.counts[k] - r.exact[k]) < 1, k));
      const e = M.evaluate(p, rule);
      assert.ok(Math.abs(r.exact.agreedRight + r.exact.switchedRight + r.exact.heldFirm - 100 * e.team) < 1e-9);
      assert.ok(Math.abs(r.exact.overRelied - 100 * e.overErrors) < 1e-9);
      assert.ok(Math.abs(r.exact.bothWrong - 100 * e.shared) < 1e-9);
    });
  }
});

test('whoever is surer equals the best possible rule when honest and independent', () => {
  const p = { human: 0.72, ai: 0.81, overlap: 0, aiSignal: 1.7, humanSignal: 0.6, aiBias: 0, humanBias: 0 };
  assert.ok(Math.abs(M.evaluate(p, 'surer').team - M.evaluate(p, 'optimal').team) < 1e-12);
  const biased = Object.assign({}, p, { aiBias: 1.2 });
  assert.ok(M.evaluate(biased, 'surer').team < M.evaluate(biased, 'optimal').team - 0.005);
});

test('bad inputs are rejected and out-of-range ones clamped', () => {
  assert.throws(() => M.normalise({ human: NaN }), /finite/);
  assert.throws(() => M.normalise({ ai: '0.8' }), /finite/);
  assert.throws(() => M.evaluate({}, 'coin-toss'), /Unknown policy/);
  assert.equal(M.normalise({ human: 2 }).human, 0.99);
  assert.equal(M.normalise({ deferRate: -1 }).deferRate, 0);
});

test('the normal CDF is accurate to double precision', () => {
  const known = [[-3, 0.0013498980316300946], [-1, 0.15865525393145707], [0, 0.5], [1.5, 0.9331927987311419], [8, 0.9999999999999993]];
  known.forEach(([x, p]) => assert.ok(Math.abs(M.normCdf(x) - p) < 1e-15, String(x)));
  assert.equal(M.normCdf(Infinity), 1);
  assert.equal(M.normCdf(-Infinity), 0);
});

test('levers are sorted by swing and respect the limits of each setting', () => {
  const rows = M.sensitivity({}, 'surer');
  assert.equal(rows.length, 7);
  for (let i = 1; i < rows.length; i++) assert.ok(rows[i - 1].swing >= rows[i].swing);
  const atTop = M.sensitivity({ ai: 0.99 }, 'optimal').find((r) => r.key === 'ai');
  assert.equal(atTop.high, 0);
  assert.ok(atTop.low < 0);
  M.sensitivity({}, 'optimal').filter((r) => /Bias/.test(r.key)).forEach((r) => {
    assert.equal(r.low, 0);
    assert.equal(r.high, 0);
  });
});

test('the threshold curve runs from 50% to 99% and never beats the best rule', () => {
  const curve = M.thresholdCurve({}, 49);
  assert.equal(curve.length, 50);
  assert.equal(curve[0].threshold, 0.5);
  assert.ok(Math.abs(curve[49].threshold - 0.99) < 1e-12);
  const ceiling = M.analyse({}).ceiling;
  curve.forEach((c) => assert.ok(c.team <= ceiling + 1e-12));
});
