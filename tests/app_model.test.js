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

test('going for broke at your current risk changes nothing but the record of switching', () => {
  const off = M.simulate({ sims: 200 });
  const same = M.simulate({ sims: 200, catchUp: true, catchUpVol: 0.2 });
  assert.equal(same.you.pWin, off.you.pWin);
  assert.equal(same.you.meanRank, off.you.meanRank);
  assert.ok(same.you.pSwitched > 0.5);
  assert.equal(off.you.pSwitched, 0);
});

test('going for broke when behind lifts a skilled team’s chance of a podium', () => {
  const off = M.simulate({ sims: 500 });
  const on = M.simulate({ sims: 500, catchUp: true });
  assert.ok(on.you.pTop3 > off.you.pTop3 + 0.1);
  assert.ok(on.you.pWin > off.you.pWin);
});

test('rivals who chase the lead switch only when behind, and show up among the winners', () => {
  const r = M.simulate({ sims: 300, rivalsCatchUp: 1 });
  assert.ok(r.winners.switched > 0.1);
  const teams = M.sampleCompetition({ rivalsCatchUp: 1, teams: 20 }, 3);
  const cp = M.checkpointDay(M.normalise({ teams: 20 }));
  teams.filter((t) => !t.you).forEach((t) => {
    if (t.switchDay !== null) {
      assert.equal(t.switchDay, cp);
      assert.equal(t.gambler, false);
    }
  });
  assert.ok(teams.some((t) => t.switchDay !== null));
});

test('the checkpoint is always inside the challenge', () => {
  [5, 6, 20, 250].forEach((days) => {
    [0.25, 0.5, 0.9].forEach((checkpoint) => {
      const d = M.checkpointDay(M.normalise({ days, checkpoint }));
      assert.ok(d >= 1 && d <= days - 1, days + ' ' + checkpoint + ' ' + d);
    });
  });
});

test('average ranks share tied places, and correlation behaves', () => {
  assert.deepEqual(M.averageRanks([3, 1, 3, -Infinity, -Infinity]), [1.5, 3, 1.5, 4.5, 4.5]);
  assert.equal(M.correlation([1, 2, 3], [3, 2, 1]), -1);
  assert.equal(M.correlation([1, 2, 3], [2, 4, 6]), 1);
  assert.equal(M.correlation([1, 1, 1], [1, 2, 3]), 0);
});

test('skill shows more clearly the longer the challenge runs', () => {
  const rows = M.skillByLength({ teams: 20 }, 60);
  assert.equal(rows.length, M.RULES.length * M.DURATIONS.length);
  M.RULES.forEach((rule) => {
    const week = rows.find((r) => r.rule === rule && r.days === 5);
    const year = rows.find((r) => r.rule === rule && r.days === 250);
    assert.ok(year.rankCorr > week.rankCorr + 0.15, rule);
  });
  const run = M.createSkillRun({ teams: 20 }, 60);
  while (!run.advance(13)) { /* keep going */ }
  assert.deepEqual(run.result(), rows);
});

test('when skills tie, a win by any of the most skilled teams counts', () => {
  const r = M.simulate({ sims: 100, skillSpread: 0, yourSharpe: 0 });
  assert.equal(r.winners.mostSkilled, 1);
  const rows = M.skillByLength({ skillSpread: 0, yourSharpe: 0, teams: 6 }, 5);
  // Under the drawdown rule every team can be knocked out, leaving no winner, so check the others.
  rows.filter((row) => row.rule !== 'drawdown').forEach((row) => assert.equal(row.pBestWins, 1));
});

test('the chi-square distribution matches published tables', () => {
  assert.ok(Math.abs(M.chiSquareQuantile(0.95, 29) - 42.557) < 0.001);
  assert.ok(Math.abs(M.chiSquareQuantile(0.05, 29) - 17.708) < 0.001);
  assert.ok(Math.abs(M.chiSquareTail(2, 2) - Math.exp(-1)) < 1e-10);
  assert.ok(Math.abs(M.logGamma(5) - Math.log(24)) < 1e-9);
});

test('a pasted table is read with its units, and bad tables are explained', () => {
  const t = M.parseTable('Team\tReturn\tVolatility\nOak\t+8.4%\t21%\nElm\t−1.5%\t\nAsh\tn/a\t30%\n');
  assert.equal(t.teams.length, 2);
  assert.equal(t.skipped, 1);
  assert.ok(Math.abs(t.teams[0].ret - 0.084) < 1e-12);
  assert.equal(t.teams[1].vol, null);
  assert.throws(() => M.parseTable(''), /empty/);
  assert.throws(() => M.parseTable('Team,Volatility\nA,20\n'), /No return or Sharpe ratio column/);
  assert.throws(() => M.checkLeaderboard(M.parseTable('Team,Return\nA,1\nB,2\n')), /At least three teams/);
});

test('the leaderboard check tells a month of luck from a year of skill', () => {
  const month = M.exampleTable('month');
  const r1 = M.checkLeaderboard(M.parseTable(month.text), { days: month.days });
  assert.equal(r1.verdict, 'luck');
  assert.equal(r1.edgeSd, 0);
  const year = M.exampleTable('year');
  const r2 = M.checkLeaderboard(M.parseTable(year.text), { days: year.days });
  assert.notEqual(r2.verdict, 'luck');
  assert.ok(r2.skillSpreadLow < 0.75 && 0.75 < r2.skillSpreadHigh);
  assert.ok(r2.truthCorrelation > 0.5);
  r2.rows.forEach((row) => assert.ok(row.edgeLow < row.edge && row.edge < row.edgeHigh));
});

test('Sortino ratio, like Sharpe ratio, makes risk irrelevant; return over drawdown nearly does', () => {
  const sortino = M.simulate({ sims: 300, rule: 'sortino' });
  assert.equal(new Set(sortino.curve.map((c) => c.pWin)).size, 1);
  const calmar = M.simulate({ sims: 300, rule: 'calmar' });
  const wins = calmar.curve.map((c) => c.pWin);
  assert.ok(Math.max(...wins) - Math.min(...wins) < 0.05);
  const rows = M.skillByLength({ teams: 8 }, 4);
  assert.equal(rows.length, 35);
  assert.deepEqual([...new Set(rows.map((r) => r.rule))], M.RULES);
});
