// Tests for the browser app's MODEL block, run with: node --test tests/app_model.test.js
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadModel } = require('./model_harness.js');

const M = loadModel();
const SMALL = { sims: 300 };

test('the same settings and luck give the same answer; new luck gives a different one', () => {
  const a = M.simulate(SMALL);
  const b = M.simulate(SMALL);
  const c = M.simulate(Object.assign({}, SMALL, { seed: 2 }));
  assert.deepEqual(a, b);
  assert.notDeepEqual(a.curve, c.curve);
});

test('a run advanced in chunks matches a run done in one go', () => {
  const whole = M.simulate(SMALL);
  const run = M.createRun(SMALL);
  while (!run.advance(7)) { /* keep going */ }
  assert.deepEqual(run.result(), whole);
});

test('ranked on Sharpe ratio, risk makes no difference at all', () => {
  const r = M.simulate({ sims: 400, rule: 'sharpe' });
  r.curve.forEach((c) => {
    assert.equal(c.pWin, r.curve[0].pWin);
    assert.equal(c.meanRank, r.curve[0].meanRank);
  });
});

test('ranked on return, a skilled team gains from extra risk in a short challenge', () => {
  const r = M.simulate({ sims: 800 });
  assert.ok(r.curve[19].pWin > r.curve[3].pWin + 0.1, 'more risk should win more often');
  assert.equal(r.bestVol, 1);
  assert.ok(r.winners.gambler > r.winners.steady, 'gamblers should win more than their share');
});

test('a drawdown limit knocks out more teams as risk rises', () => {
  const r = M.simulate({ sims: 400, rule: 'drawdown', drawdownLimit: 0.1 });
  assert.ok(r.curve[19].pOut > r.curve[3].pOut);
  assert.ok(r.curve[19].pOut > 0.3);
  assert.ok(r.bestVol < 1, 'the best risk should be below the maximum');
});

test('shares and probabilities are consistent', () => {
  const r = M.simulate({ sims: 300, rule: 'drawdown', drawdownLimit: 0.05, gamblers: 0.5 });
  const w = r.winners;
  assert.ok(Math.abs(w.you + w.gambler + w.steady + w.none - 1) < 1e-12);
  assert.ok(w.noEdge <= 1 - w.none + 1e-12);
  assert.equal(w.you, r.you.pWin);
  r.curve.forEach((c) => {
    assert.ok(c.pWin <= c.pTop3);
    assert.ok(c.meanRank >= 1 && c.meanRank <= r.params.teams);
  });
});

test('one sample challenge is the same as that challenge inside the simulation', () => {
  const p = { sims: 100, teams: 12, days: 15, gamblers: 0.25 };
  const r = M.simulate(p);
  let youWins = 0;
  let gamblerWins = 0;
  for (let k = 0; k < 100; k++) {
    const teams = M.sampleCompetition(p, k);
    assert.equal(teams.length, 12);
    assert.deepEqual(teams.map((t) => t.rank), teams.map((_, i) => i + 1));
    if (teams[0].you) youWins += 1;
    if (teams[0].gambler) gamblerWins += 1;
    teams.forEach((t) => assert.equal(t.path.length, 16));
  }
  assert.equal(youWins / 100, r.winners.you);
  assert.equal(gamblerWins / 100, r.winners.gambler);
});

test('extreme risk can blow an account up, and a blown-up team is out under any rule', () => {
  const p = { sims: 50, fieldVol: 0.5, gamblerMultiple: 4, gamblers: 0.8, fatTails: true, days: 250, yourVol: 1 };
  let busts = 0;
  for (let k = 0; k < 20; k++) {
    M.sampleCompetition(p, k).forEach((t) => {
      if (t.bust) {
        busts += 1;
        assert.equal(t.out, true);
        assert.equal(t.score, -Infinity);
        assert.equal(t.ret, -1);
      }
    });
  }
  assert.ok(busts > 0);
});

test('inputs are checked and clamped', () => {
  assert.throws(() => M.normalise({ rule: 'luck' }), /rule/);
  assert.throws(() => M.normalise({ teams: NaN }), /finite/);
  assert.throws(() => M.normalise({ fatTails: 'yes' }), /fatTails/);
  const p = M.normalise({ teams: 2.6, days: 1000, yourVol: 0 });
  assert.equal(p.teams, 3);
  assert.equal(p.days, 250);
  assert.equal(p.yourVol, 0.02);
});

test('the random numbers look right', () => {
  const g = M.makeRng(42);
  let sum = 0;
  let sumSq = 0;
  const n = 20000;
  for (let i = 0; i < n; i++) {
    const z = g.normal();
    sum += z;
    sumSq += z * z;
  }
  assert.ok(Math.abs(sum / n) < 0.03);
  assert.ok(Math.abs(sumSq / n - 1) < 0.04);
});
