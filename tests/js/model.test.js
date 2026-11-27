// Unit tests for the browser app's model block. Run from the repository root with: node --test tests/js/model.test.js
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadModel } = require('./load_model.js');

const M = loadModel();
const seeds = (from, n) => Array.from({ length: n }, (_, i) => from + i);
const avg = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;

test('detExp and detLog match the built-in functions closely', () => {
  for (let x = -40; x <= 40; x += 0.173) {
    const rel = Math.abs(M.detExp(x) - Math.exp(x)) / Math.exp(x);
    assert.ok(rel < 1e-14, 'exp ' + x + ' ' + rel);
  }
  for (const x of [1e-12, 0.001, 0.3, 0.7071, 1, 1.41, 2, 10, 260, 12345.678, 1e15]) {
    assert.ok(Math.abs(M.detLog(x) - Math.log(x)) < 1e-13 * Math.max(1, Math.abs(Math.log(x))), 'log ' + x);
  }
  assert.equal(M.detExp(800), Infinity);
  assert.equal(M.detExp(-800), 0);
  assert.equal(M.detLog(0), -Infinity);
  assert.ok(Number.isNaN(M.detLog(-1)));
  assert.ok(Number.isNaN(M.detExp(NaN)));
});

test('invNorm inverts normCdf and both are symmetric', () => {
  for (const p of [0.001, 0.01, 0.0242, 0.1, 0.3, 0.5, 0.77, 0.975, 0.999]) {
    assert.ok(Math.abs(M.normCdf(M.invNorm(p)) - p) < 2e-6, 'p ' + p);
    assert.ok(Math.abs(M.invNorm(p) + M.invNorm(1 - p)) < 1e-8);
  }
  assert.ok(Math.abs(M.invNorm(0.975) - 1.959964) < 1e-5);
  assert.equal(M.invNorm(0), -8.5);
  assert.equal(M.invNorm(1), 8.5);
});

test('the random number generator is seeded, uniform and repeatable', () => {
  const a = new M.Rng(7), b = new M.Rng(7), c = new M.Rng(8);
  let same = true, differ = false, sum = 0;
  for (let i = 0; i < 20000; i++) {
    const x = a.next(), y = b.next(), z = c.next();
    assert.ok(x >= 0 && x < 1);
    if (x !== y) same = false;
    if (x !== z) differ = true;
    sum += x;
  }
  assert.ok(same && differ);
  assert.ok(Math.abs(sum / 20000 - 0.5) < 0.01);
  const r = new M.Rng(3);
  let s1 = 0, s2 = 0;
  for (let i = 0; i < 20000; i++) { const z = r.normal(); s1 += z; s2 += z * z; }
  assert.ok(Math.abs(s1 / 20000) < 0.03 && Math.abs(s2 / 20000 - 1) < 0.04);
  assert.notEqual(M.hashSeed(1, 2), M.hashSeed(2, 1));
  assert.equal(M.hashSeed(5, 6, 7), M.hashSeed(5, 6, 7));
});

test('settings are cleaned and clamped', () => {
  const s = M.withDefaults({ threshold: 9, budget: -3, policy: 'nonsense', flag: 'tea', intensity: 'x', rotateAfter: 0.5, unknown: 1 });
  assert.equal(s.threshold, 3);
  assert.equal(s.budget, 1);
  assert.equal(s.policy, 'none');
  assert.equal(s.flag, 'ewma');
  assert.equal(s.intensity, M.DEFAULTS.intensity);
  assert.equal(M.withDefaults({ seasonSeed: 'abc', spike: Infinity }).seasonSeed, M.DEFAULTS.seasonSeed);
  assert.equal(M.withDefaults({ spike: Infinity }).spike, M.DEFAULTS.spike);
  assert.equal(s.rotateAfter, 2);
  assert.equal(s.unknown, undefined);
  assert.equal(M.withDefaults({ preseason: 'whatever' }).preseason, 'gradual');
});

test('the squad has 36 players in eight position groups, ordered by ability within each', () => {
  const sq = M.makeSquad(7);
  assert.equal(sq.players.length, 36);
  assert.equal(sq.opponents.length, 11);
  assert.equal(sq.bestXV.length, 15);
  const names = new Set(sq.players.map((p) => p.name));
  assert.equal(names.size, 36);
  M.GROUPS.forEach((g) => {
    const group = sq.players.filter((p) => p.group === g.id);
    assert.equal(group.length, g.count);
    for (let i = 1; i < group.length; i++) assert.ok(group[i - 1].ability >= group[i].ability);
  });
  assert.deepEqual(M.makeSquad(7), sq);
  assert.notDeepEqual(M.makeSquad(8).players[0], sq.players[0]);
});

test('a season has the right fixtures, consistent totals and a full league table', () => {
  const r = M.runSeason({}, 3, { keepDaily: true });
  assert.equal(r.matches.filter((m) => m.type === 'L').length, 22);
  assert.equal(r.matches.length, 24);
  assert.equal(r.injuriesTotal, r.nc + r.contact);
  assert.equal(r.injuriesTotal, r.injuries.length);
  assert.equal(r.points, r.matches.filter((m) => m.type === 'L').reduce((a, m) => a + m.points, 0));
  assert.equal(r.wins + r.draws + r.losses, 22);
  assert.equal(r.table.length, 12);
  assert.equal(r.table.filter((t) => t.us).length, 1);
  assert.equal(r.table.find((t) => t.us).points, r.points);
  assert.ok(r.daysLost >= 0);
  r.matches.forEach((m) => {
    assert.equal(m.starters.length, 15);
    assert.equal(new Set(m.starters.concat(m.bench)).size, 23);
  });
  // Every opponent is played once at home and once away.
  const legs = {};
  r.matches.filter((m) => m.type === 'L').forEach((m) => { legs[m.opponent] = (legs[m.opponent] || '') + (m.home ? 'H' : 'A'); });
  Object.values(legs).forEach((v) => assert.equal(v.split('').sort().join(''), 'AH'));
});

test('injured players never train, play or get injured again while out', () => {
  const r = M.runSeason({ policy: 'none' }, 2, { keepDaily: true });
  const byPlayer = {};
  r.injuries.forEach((inj) => { (byPlayer[inj.player] = byPlayer[inj.player] || []).push(inj); });
  Object.values(byPlayer).forEach((list) => {
    for (let k = 1; k < list.length; k++) assert.ok(list[k].day > list[k - 1].day + list[k - 1].days);
  });
  r.matches.forEach((m) => {
    m.starters.concat(m.bench).forEach((pid) => {
      assert.notEqual(r.status[pid][M.HIST + m.day], 1, 'an injured player was picked');
      assert.notEqual(r.status[pid][M.HIST + m.day], 2, 'a player in graded return was picked');
    });
  });
  for (let p = 0; p < r.status.length; p++) {
    for (let i = 0; i < M.TOTAL_DAYS; i++) {
      if (r.status[p][i] === 1) assert.notEqual(r.kinds[p][i], 3, 'an injured player played a match');
    }
  }
});

test('seasons are repeatable and policies share the same luck', () => {
  assert.deepEqual(M.runSeason({ policy: 'rest', flag: 'model' }, 4), M.runSeason({ policy: 'rest', flag: 'model' }, 4));
  // A light that can never fire leaves a policy that acts on it identical to ignoring it.
  const never = { flag: 'ewma', threshold: 3 };
  const a = M.runSeason(Object.assign({ policy: 'none' }, never), 5);
  const b = M.runSeason(Object.assign({ policy: 'rest' }, never), 5);
  assert.equal(a.injuriesTotal, b.injuriesTotal);
  assert.equal(a.points, b.points);
  assert.deepEqual(a.injuries, b.injuries);
  assert.equal(b.rests, 0);
});

test('the hidden truth behaves as described: spikes, contact rates and steep pre-seasons', () => {
  const run = (s) => seeds(1, 12).map((k) => M.runSeason(s, k));
  const calm = run({ policy: 'none', spike: 0 }), spiky = run({ policy: 'none', spike: 4 });
  assert.ok(avg(spiky.map((r) => r.nc)) > avg(calm.map((r) => r.nc)) + 2);
  const few = run({ policy: 'none', contactScale: 0.5 }), many = run({ policy: 'none', contactScale: 1.5 });
  assert.ok(avg(many.map((r) => r.contact)) > avg(few.map((r) => r.contact)) + 5);
  const pre = (rs) => avg(rs.map((r) => r.injuries.filter((i) => i.type === 'nc' && i.week < M.PRE_WEEKS).length));
  assert.ok(pre(run({ policy: 'none', preseason: 'steep' })) > pre(run({ policy: 'none', preseason: 'gradual' })));
});

test('the truth multiplier rises with spikes, under-training and recent injury', () => {
  const p = { frailty: 1, age: 26, unit: 'F' };
  const base = M.truthMult(p, 260, 260, false, 2)[0];
  assert.ok(Math.abs(base - 1) < 1e-12);
  assert.ok(M.truthMult(p, 500, 260, false, 2)[0] > base * 3);
  assert.ok(M.truthMult(p, 120, 120, false, 2)[0] > base);
  assert.ok(Math.abs(M.truthMult(p, 260, 260, true, 2)[0] / base - 1.6) < 1e-12);
  assert.equal(M.truthMult(p, 500, 260, false, 0)[0], base);
  assert.ok(M.perfMult(200, 300) > M.perfMult(300, 300));
  assert.ok(M.perfMult(9999, 10) >= 0.82 && M.perfMult(0, 9999) <= 1.06);
});

test('auc, roc and confusion agree with hand-worked examples', () => {
  assert.equal(M.auc([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]), 0.75);
  assert.equal(M.auc([1, 1, 1, 1], [0, 1, 0, 1]), 0.5);
  assert.equal(M.auc([3, 2, 1], [1, 0, 0]), 1);
  assert.ok(Number.isNaN(M.auc([1, 2], [0, 0])));
  const roc = M.rocCurve([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1], 10);
  assert.deepEqual(roc[0], [0, 0]);
  assert.deepEqual(roc[roc.length - 1], [1, 1]);
  const c = M.confusion([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1], 0.36);
  assert.deepEqual([c.tp, c.fp, c.fn, c.tn], [1, 1, 1, 1]);
  assert.equal(c.precision, 0.5);
  const ci = M.bootMean([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 500);
  assert.ok(ci[0] < 5.5 && ci[1] > 5.5 && ci[0] > 2 && ci[1] < 9);
});

test('logistic regression recovers a clear signal', () => {
  const rng = new M.Rng(9), X = [], y = [];
  for (let i = 0; i < 3000; i++) {
    const x = [rng.normal(), rng.normal()];
    X.push(x);
    y.push(rng.next() < 1 / (1 + Math.exp(-(-1 + 1.5 * x[0]))) ? 1 : 0);
  }
  const model = M.trainLogistic(X, y, 0.001);
  const slopeA = model.w[1] / model.sd[0], slopeB = model.w[2] / model.sd[1];
  assert.ok(Math.abs(slopeA - 1.5) < 0.2, 'slope ' + slopeA);
  assert.ok(Math.abs(slopeB) < 0.15);
  assert.ok(M.predictLogistic(model, [2, 0]) > M.predictLogistic(model, [-2, 0]));
  assert.deepEqual(M.solveLinear([[2, 1], [1, 3]], [3, 5]).map((v) => +v.toFixed(12)), [0.8, 1.4]);
});

test('the risk model is trained on past seasons and sets cut-offs for its alarm budget', () => {
  const ctx = M.prepare({ budget: 10 });
  assert.ok(ctx.historyRows > 2000 && ctx.historyInjuries > 5);
  assert.equal(ctx.model.w.length, M.FEATURES.length + 1);
  assert.ok(ctx.cutoffs.model > 0 && ctx.cutoffs.oracle > 0);
  assert.ok(M.prepare({ budget: 20 }).cutoffs.model < ctx.cutoffs.model);
  assert.equal(M.prepare({ budget: 10 }), ctx, 'prepare is cached');
});

test('the warning-light scorecard: coupled and uncoupled ratios rank identically, the ceiling is highest', () => {
  const ev = M.evaluateFlags({}, seeds(1, 8));
  const by = Object.fromEntries(ev.flags.map((f) => [f.id, f]));
  assert.equal(by.coupled.auc, by.uncoupled.auc);
  assert.ok(by.oracle.auc > by.coupled.auc && by.oracle.auc > by.ewma.auc && by.oracle.auc > by.model.auc);
  ev.flags.forEach((f) => {
    assert.ok(f.auc > 0.5 && f.auc < 0.8, f.id + ' ' + f.auc);
    assert.ok(f.seasonAuc.lo <= f.seasonAuc.mean && f.seasonAuc.mean <= f.seasonAuc.hi);
    assert.ok(f.atRule.share >= 0 && f.atRule.share <= 1);
  });
  assert.ok(ev.contactShare > 0.4 && ev.contactShare < 0.8);
  assert.ok(ev.baseRate > 0 && ev.baseRate < 0.03);
  // At an equal alarm budget every light flags the same share of player-weeks.
  ev.flags.forEach((f) => assert.ok(Math.abs(f.atBudget.share - 0.1) < 0.03, f.id + ' ' + f.atBudget.share));
});

test('the coupling demonstration shows the bound and the induced correlation', () => {
  const cd = M.couplingDemo(3, 600);
  assert.ok(cd.maxCoupled <= 4);
  assert.ok(cd.corrCoupled > 0.35 && Math.abs(cd.corrUncoupled) < 0.15);
  cd.points.forEach((p) => assert.ok(Math.abs(p.uncoupled - 3 * p.coupled / (4 - p.coupled)) < 1e-9));
});

test('policy comparison uses paired seasons and the reference differs from itself by nothing', () => {
  const cp = M.comparePolicies({ flag: 'model' }, seeds(101, 6));
  assert.deepEqual(cp.policies, M.POLICIES);
  const none = cp.table[0];
  M.METRICS.forEach((m) => assert.equal(none.metrics[m].diff, 0));
  const rest = cp.table.find((r) => r.policy === 'rest');
  assert.ok(rest.metrics.rests.mean > 20);
  assert.ok(rest.metrics.points.diff < 0, 'resting costs points');
  const rot = cp.table.find((r) => r.policy === 'rotate');
  assert.ok(rot.metrics.rests.mean > 20);
});

test('the pilot study separates the measured from the true effect', () => {
  const ps = M.pilotStudy({ policy: 'rest', flag: 'model' }, 8);
  assert.equal(ps.measured.length, 8);
  assert.equal(ps.power.length, 100);
  for (let k = 1; k < ps.power.length; k++) assert.ok(ps.power[k].power >= ps.power[k - 1].power);
  assert.ok(ps.looksBetter + ps.looksWorse <= 1);
  assert.ok(ps.quietShare > 0.8 && ps.quietShare <= 1);
  assert.ok(ps.seasonSd > 0);
  assert.ok(Number.isFinite(ps.seasonsNeeded) || ps.trueEffect === 0);
  assert.equal(M.pilotStudy({ policy: 'none' }, 1).policy, 'rest');
});

test('power and sample size are consistent with each other', () => {
  const n = M.seasonsFor(-2, 5, 0.8);
  assert.ok(M.powerTwoSample(-2, 5, n) >= 0.8);
  assert.ok(M.powerTwoSample(-2, 5, n - 1) < 0.8);
  assert.ok(Math.abs(M.powerTwoSample(0, 5, 10) - 0.05) < 1e-6);
  assert.equal(M.seasonsFor(0, 5, 0.8), Infinity);
  assert.equal(M.seasonsFor(-1, 0, 0.8), 1);
});

test('dates round-trip and reject impossible days', () => {
  for (let z = -1000; z < 40000; z += 97) assert.equal(M.parseDay(M.formatDay(z)), z);
  assert.equal(M.formatDay(M.daysFromCivil(2026, 9, 5)), '2026-09-05');
  assert.equal(M.parseDay('05/09/2026'), M.daysFromCivil(2026, 9, 5));
  assert.equal(M.parseDay('2026-02-29'), null);
  assert.equal(M.parseDay('2028-02-29'), M.daysFromCivil(2028, 2, 29));
  assert.equal(M.parseDay('yesterday'), null);
  assert.equal(M.formatDay(M.SEASON_START), '2026-06-22');
});

test('CSV parsing copes with quotes, commas, semicolons, CRLF and a byte-order mark', () => {
  const rows = M.parseCSV('﻿a,b,c\r\n"x, y","he said ""hi""",3\r\n\r\nd;e;f\n');
  assert.deepEqual(rows, [['a', 'b', 'c'], ['x, y', 'he said "hi"', '3'], ['d', 'e', 'f']]);
  const text = M.toCSV(['h1', 'h2'], [['a,b', 'tab\there'], [1, null]]);
  assert.deepEqual(M.parseCSV(text), [['h1', 'h2'], ['a,b', 'tab\there'], ['1', '']]);
});

test('reading a logbook reports problems instead of failing', () => {
  assert.ok(M.readLogbook([]).error);
  assert.ok(M.readLogbook([['when', 'who']]).error);
  assert.ok(M.readLogbook([['date', 'player', 'minutes']]).error);
  assert.ok(M.readLogbook([['date', 'player', 'load'], ['not a date', 'A', '300']]).error);
  const ok = M.readLogbook(M.parseCSV('date,player,load,injury\n2026-09-01,constructor,300,\n2026-09-02,toString,250,n/a\n2026-09-03,A,bad,\n'));
  assert.equal(ok.names.length, 2);
  assert.equal(ok.injuries.length, 0);
  assert.equal(ok.warnings.length, 2);
});

test('the sample logbook reproduces the season and its analysis finds the injuries', () => {
  const lb = M.seasonLogbook({}, 1);
  assert.ok(lb.rows.length > 6000);
  assert.equal(lb.rows.filter((r) => r.injury).length, lb.season.injuriesTotal);
  const text = M.toCSV(['date', 'player', 'position', 'session', 'minutes', 'rpe', 'injury'],
    lb.rows.map((r) => [r.date, r.player, r.position, r.session, r.minutes, r.rpe, r.injury]));
  const book = M.readLogbook(M.parseCSV(text));
  assert.equal(book.names.length, 36);
  assert.equal(book.sessions, lb.rows.length);
  const an = M.analyseLogbook(book, { threshold: 1.5, permutations: 40, seed: 2 });
  assert.equal(an.only, 'non-contact');
  assert.equal(an.counted, lb.season.nc);
  const by = Object.fromEntries(an.results.map((r) => [r.id, r]));
  assert.equal(by.coupled.auc, by.uncoupled.auc);
  an.results.forEach((r) => assert.ok(r.p > 0 && r.p <= 1));
  assert.equal(an.latest.length, 36);
  const all = M.analyseLogbook(book, { only: 'all', permutations: 0 });
  assert.equal(all.counted, lb.season.injuriesTotal);
  assert.equal(all.results[0].p, undefined);
});

test('player series follow the season loads', () => {
  const ctx = M.prepare({});
  const r = M.runSeason({}, 1, { keepDaily: true });
  const s = M.playerSeries(r, ctx.squad.players[5]);
  assert.equal(s.fitness.length, M.TOTAL_DAYS);
  assert.equal(s.weekly.length, M.TOTAL_DAYS / 7);
  assert.ok(Number.isNaN(s.coupled[10]) && Number.isFinite(s.coupled[40]));
  const total = Array.from(r.load[5]).reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(s.weekly.reduce((a, b) => a + b, 0) - total) < 1e-6 * total);
});
