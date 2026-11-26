// Unit tests for the browser app's model block. Run with: node --test tests/js/model.test.js
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadModel } = require('./load_model.js');

const M = loadModel();
const FAST = { beta: 5e-5, maxPeriods: 200000, stableWindow: 10000 };
const fast = (extra) => Object.assign({}, FAST, extra || {});

test('detExp and detLog match the built-in functions closely', () => {
  for (let x = -30; x <= 30; x += 0.37) {
    const rel = Math.abs(M.detExp(x) - Math.exp(x)) / Math.exp(x);
    assert.ok(rel < 1e-13, 'exp ' + x + ' ' + rel);
  }
  for (const x of [1e-9, 0.001, 0.3, 0.75, 1, 1.4999, 2, 10, 12345.678, 1e12]) {
    assert.ok(Math.abs(M.detLog(x) - Math.log(x)) < 1e-12 * Math.max(1, Math.abs(Math.log(x))), 'log ' + x);
  }
  assert.equal(M.detExp(800), Infinity);
  assert.equal(M.detExp(-800), 0);
  assert.ok(Number.isNaN(M.detExp(NaN)));
  assert.equal(M.detLog(0), -Infinity);
  assert.ok(Number.isNaN(M.detLog(-1)));
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
  const r = new M.Rng(3), counts = [0, 0, 0, 0, 0];
  for (let i = 0; i < 50000; i++) counts[r.int(5)]++;
  counts.forEach((k) => assert.ok(Math.abs(k / 50000 - 0.2) < 0.01));
});

test('validateConfig accepts the defaults and explains bad inputs', () => {
  const ok = M.validateConfig({});
  assert.deepEqual(ok.errors, []);
  assert.equal(ok.config.nFirms, 2);
  const bad = M.validateConfig({ mu: 5, alpha: 'x', memory: 'some', nFirms: 7, seed: -1 });
  assert.equal(bad.config.mu, 1);
  assert.equal(bad.config.nFirms, 3);
  assert.equal(bad.config.alpha, M.defaultConfig().alpha);
  assert.equal(bad.config.memory, 'full');
  assert.equal(bad.errors.length, 5);
  assert.ok(M.validateConfig({ firmTypes: ['nash', 'match'] }).errors.some((e) => /at least one seller must learn/.test(e)));
  assert.ok(M.validateConfig({ firmTypes: 'learn' }).errors.some((e) => /must be a list/.test(e)));
  assert.ok(M.validateConfig({ seed: true }).errors.length === 1);
  assert.equal(M.validateConfig({ seed: '42' }).config.seed, 42);
  const shared = M.validateConfig({ sharedVendor: true, cost: [1, 1.2] });
  assert.equal(shared.config.sharedVendor, false);
  assert.ok(shared.errors.some((e) => /shared vendor/.test(e)));
  const win = M.validateConfig({ stableWindow: 100000, maxPeriods: 50000 });
  assert.equal(win.config.stableWindow, 50000);
});

test('competitive prices satisfy every seller’s first-order condition', () => {
  const cases = [
    [[2, 2], [1, 1], 0, 0.25], [[2, 2.2], [1, 1], 0, 0.25], [[2, 2, 2.5], [1, 0.8, 1.2], 0, 0.1],
    [[1, 3], [0, 2], 1, 0.5], [[2, 2], [1, 1], 0, 0.05], [[2, 2, 2], [1, 1, 1], -1, 1]
  ];
  for (const [q, c, out, mu] of cases) {
    const p = M.nashPrices(q, c, out, mu), s = M.shares(p, q, out, mu);
    p.forEach((pi, i) => assert.ok(Math.abs(pi - c[i] - mu / (1 - s[i])) < 1e-9, JSON.stringify([q, c, mu, p])));
    // and no seller can gain by moving its own price a little
    p.forEach((pi, i) => {
      const base = M.profitsAt(p, q, c, out, mu)[i];
      for (const d of [-0.01, 0.01]) {
        const moved = p.slice(); moved[i] = pi + d;
        assert.ok(M.profitsAt(moved, q, c, out, mu)[i] <= base + 1e-12);
      }
    });
  }
  const p = M.nashPrices([2, 2], [1, 1], 0, 0.25);
  assert.ok(Math.abs(p[0] - 1.4729) < 1e-4);
  assert.equal(p[0], p[1], 'identical sellers get identical prices');
  const p3 = M.nashPrices([2, 2, 2], [1, 1, 1], 0, 0.1);
  assert.ok(p3[0] === p3[1] && p3[1] === p3[2]);
});

test('monopoly prices maximise joint profit', () => {
  for (const [q, c, mu] of [[[2, 2], [1, 1], 0.25], [[2, 2.4], [1, 1.1], 0.3], [[2, 2, 2], [1, 1, 1], 0.1]]) {
    const p = M.monopolyPrices(q, c, 0, mu);
    const joint = (pr) => M.profitsAt(pr, q, c, 0, mu).reduce((a, b) => a + b, 0);
    const best = joint(p);
    for (let i = 0; i < p.length; i++) for (const d of [-0.02, 0.02]) {
      const moved = p.slice(); moved[i] += d;
      assert.ok(joint(moved) <= best + 1e-12);
    }
  }
  assert.ok(Math.abs(M.monopolyPrices([2, 2], [1, 1], 0, 0.25)[0] - 1.925) < 1e-3);
});

test('the price grid spans competitive to monopoly with a margin', () => {
  const mk = M.buildMarket(M.validateConfig({}).config);
  const g = mk.grids[0], gap = mk.pM[0] - mk.pN[0];
  assert.equal(g.length, 15);
  assert.ok(Math.abs(g[0] - (mk.pN[0] - 0.1 * gap)) < 1e-12);
  assert.ok(Math.abs(g[14] - (mk.pM[0] + 0.1 * gap)) < 1e-12);
  for (let k = 1; k < g.length; k++) assert.ok(g[k] > g[k - 1]);
  assert.equal(mk.nashIdx[0], 1);
  assert.equal(mk.monoIdx[0], 13);
  for (let j = 0; j < mk.nJoint; j++) assert.equal(M.encodeJoint(M.decodeJoint(j, 2, 15), 15), j);
  const noisy = M.buildMarket(M.validateConfig({ demandNoise: 0.2 }).config);
  assert.equal(noisy.levels, 5);
});

test('training is deterministic and can be run in pieces', () => {
  const one = M.train(fast({ seed: 11 }));
  const two = new M.Trainer(fast({ seed: 11 }));
  while (!two.run(7777)) { /* pieces */ }
  assert.equal(one.t, two.t);
  assert.equal(one.last, two.last);
  assert.deepEqual(Array.from(one.best[0]), Array.from(two.best[0]));
  assert.deepEqual(Array.from(one.Q[1]), Array.from(two.Q[1]));
  assert.equal(one.history.length, Math.floor(one.t / 10000));
  const other = M.train(fast({ seed: 12 }));
  assert.notDeepEqual(Array.from(one.Q[0]), Array.from(other.Q[0]));
});

test('the textbook duopoly learns high prices held up by punishment', () => {
  for (const seed of [1, 2, 3]) {
    const s = M.summarise(M.train({ seed }));
    assert.ok(s.converged, 'seed ' + seed + ' settled');
    assert.ok(s.avgGain > 0.6, 'seed ' + seed + ' gain ' + s.avgGain);
    assert.ok(s.punished, 'seed ' + seed + ' punished');
    assert.ok(s.collusive);
    assert.ok(s.harm > 0.4);
  }
});

test('banning rivals’ prices as an input brings prices back to competitive', () => {
  for (const seed of [1, 2]) {
    const s = M.summarise(M.train({ seed, memory: 'own' }));
    assert.ok(Math.abs(s.avgGain) < 0.2, 'gain ' + s.avgGain);
    assert.equal(s.collusive, false);
  }
});

test('memoryless sellers can reach high prices with no threat at all', () => {
  const s = M.summarise(M.train({ seed: 2, memory: 'none' }));
  assert.ok(s.avgGain > 0.5);
  assert.equal(s.punished, false);
  assert.equal(s.collusive, false);
});

test('the limit cycle repeats under the learned strategies', () => {
  const tr = M.train(fast({ seed: 5 }));
  const lc = M.limitCycle(tr);
  let j = lc.states[0];
  for (let k = 1; k <= lc.states.length; k++) {
    j = tr.greedyNext(j);
    assert.equal(j, lc.states[k % lc.states.length]);
  }
});

test('the impulse response follows its definitions', () => {
  const tr = M.train({ seed: 1 });
  const lc = M.limitCycle(tr).states;
  const ir = M.impulseResponse(tr, { cycle: lc });
  assert.ok(ir.tempting && ir.punished && ir.rivalCut);
  assert.ok(ir.gainNow > 0 && ir.net < 0);
  assert.equal(ir.prices[0].length, 26);
  // charging the settled price changes nothing
  const settled = M.decodeJoint(lc[1 % lc.length], 2, 15)[0];
  const none = M.impulseResponse(tr, { cycle: lc, price: settled });
  assert.equal(none.gainNow, 0);
  assert.equal(none.net, 0);
  assert.equal(none.punished, false);
  // horizons are clamped to 2..500
  assert.equal(M.impulseResponse(tr, { horizon: 1 }).horizon, 2);
  assert.equal(M.impulseResponse(tr, { horizon: 9999 }).horizon, 500);
  // a cut that loses money on the day is never counted as punished
  const deep = M.impulseResponse(tr, { cycle: lc, price: 0 });
  if (!deep.tempting) assert.equal(deep.punished, false);
});

test('a fixed competitive rival leaves nothing to punish and a learner that best-replies', () => {
  const tr = M.train({ seed: 1, firmTypes: ['learn', 'nash'] });
  const s = M.summarise(tr);
  assert.ok(Math.abs(s.avgGain) < 0.1);
  assert.equal(s.punished, false);
  const br = M.bestResponseCheck(tr, 0, s.cycle);
  assert.ok(br.onPathOptimal);
  assert.ok(br.bestReplyGain < 1e-9);
  assert.equal(M.bestResponseCheck(tr, 1, s.cycle), null);
});

test('the best-response check finds what learned strategies leave on the table', () => {
  const tr = M.train({ seed: 1 });
  const s = M.summarise(tr);
  const br = M.bestResponseCheck(tr, 0, s.cycle);
  assert.ok(br.settled);
  assert.ok(br.shareOptimal > 0 && br.shareOptimal <= 1);
  assert.ok(br.bestReplyGain >= br.onPathGap);
  assert.ok(br.bestReplyGain > 0.01);
});

test('every scenario produces a valid configuration', () => {
  const base = M.defaultConfig();
  for (const sc of M.SCENARIOS) {
    const cfg = M.applyScenario(base, sc.id);
    assert.deepEqual(M.validateConfig(cfg).errors, [], sc.id);
    for (const k in sc.change) if (k !== 'firmTypes' && k !== 'maxPeriods') assert.deepEqual(cfg[k], sc.change[k]);
  }
  assert.equal(M.applyScenario(base, 'third').nFirms, 3);
  assert.equal(M.applyScenario(base, 'third').maxPeriods, 6000000);
  assert.deepEqual(M.applyScenario(base, 'fixedrival').firmTypes.slice(0, 2), ['learn', 'nash']);
  assert.throws(() => M.applyScenario(base, 'nope'));
  assert.equal(base.memory, 'full', 'the base is not changed');
});

test('aggregate and bootstrap intervals behave', () => {
  const b = M.bootstrapMean([1, 2, 3, 4, 5, NaN], 0.9, 2000, 1);
  assert.equal(b.mean, 3);
  assert.ok(b.lo < 3 && b.hi > 3 && b.lo >= 1 && b.hi <= 5);
  assert.deepEqual(M.bootstrapMean([2], 0.9), { mean: 2, lo: 2, hi: 2 });
  assert.ok(Number.isNaN(M.bootstrapMean([], 0.9).mean));
  const runs = [1, 2, 3].map((seed) => M.runScenario(FAST, 'baseline', seed));
  const agg = M.aggregate(runs);
  assert.equal(agg.runs, 3);
  assert.ok(agg.gain.lo <= agg.gain.mean && agg.gain.mean <= agg.gain.hi);
  assert.ok(agg.punishedShare >= 0 && agg.punishedShare <= 1);
});

test('the ROC curve and confusion counts are right on hand examples', () => {
  assert.equal(M.rocCurve([3, 2, 1, 0], [1, 1, 0, 0]).auc, 1);
  assert.equal(M.rocCurve([0, 1, 2, 3], [1, 1, 0, 0]).auc, 0);
  assert.equal(M.rocCurve([1, 1, 1, 1], [1, 0, 1, 0]).auc, 0.5);
  assert.equal(M.rocCurve([NaN, 5, 4, 1], [1, 1, 0, 0]).auc, 0.5);
  assert.ok(Number.isNaN(M.rocCurve([1, 2], [1, 1]).auc));
  const c = M.confusion([0.9, 0.8, 0.3, 0.1], [true, false, true, false], 0.5);
  assert.deepEqual([c.caught, c.falseAlarms, c.missed, c.cleared], [1, 1, 1, 1]);
});

test('screens read a hand-made punishment pattern correctly', () => {
  const a = [], b = [];
  for (let t = 0; t < 60; t++) { a.push(2); b.push(2); }
  a[10] = 1.8;               // A cuts while B holds still
  b[11] = 1.7; a[11] = 1.8;  // B answers the next day
  // both back to 2 on day 12
  const sc = M.screens([a, b], { cost: [1, 1], detail: true });
  assert.equal(sc.events, 1);
  assert.equal(sc.followRate, 1);
  assert.equal(sc.snapBack, 1);
  assert.equal(sc.punishReturn, 1);
  assert.equal(sc.eventList[0].t, 10);
  assert.equal(sc.eventList[0].who, 0);
  assert.ok(sc.margin > 0.45 && sc.margin < 0.5);
  assert.ok(sc.retaliation > 0.9);
  const flat = M.screens([a.map(() => 2), b.map(() => 2)], {});
  assert.equal(flat.events, 0);
  assert.equal(flat.margin, null);
  assert.ok(Number.isNaN(flat.followRate));
});

test('the permutation test separates linked from unrelated cuts', () => {
  const rng = new M.Rng(9), a = [], b = [], c = [];
  for (let t = 0; t < 300; t++) { a.push(2); b.push(2); c.push(2); }
  for (let t = 5; t < 290; t += 13) { a[t] = 1.8; b[t + 1] = 1.8; }
  for (let t = 3; t < 295; t++) if (rng.next() < 0.05) c[t] = 1.8;
  const linked = M.permutationTest([a, b], { reps: 199 });
  const unrelated = M.permutationTest([a, c], { reps: 199 });
  assert.ok(linked.pValue < 0.05, 'linked ' + linked.pValue);
  assert.ok(unrelated.pValue > 0.05, 'unrelated ' + unrelated.pValue);
  assert.ok(Number.isNaN(M.permutationTest([[1, 2], [1, 2]]).pValue));
});

test('the case file is reproducible and observes what it should', () => {
  const base = Object.assign(M.defaultConfig(), FAST);
  const m1 = M.caseConfig(base, 3, 7), m2 = M.caseConfig(base, 3, 7);
  assert.deepEqual(m1, m2);
  assert.ok(M.CASE_MIX.indexOf(m1.scenario) >= 0 && M.CASE_MU.indexOf(m1.mu) >= 0);
  const c = M.makeCase(base, 3, 7, { days: 120 });
  assert.equal(c.prices[0].length, 120);
  assert.equal(c.id, 4);
  assert.equal(typeof c.truth.coordinated, 'boolean');
  // with no price tests, observed prices just repeat the settled cycle
  const tr = M.train(m1.cfg);
  const quiet = M.observe(tr, { days: 50, experiment: 0 });
  const lc = M.limitCycle(tr).states;
  assert.ok(quiet[0].every((p, d) => p === tr.market.grids[0][M.decodeJoint(lc[(d + 1) % lc.length], 2, tr.market.m)[0]]));
});

test('screen scores and their evaluation line up with the screen list', () => {
  const sc = { margin: 0.4, cv: 0.05, retaliation: 0.3, snapBack: NaN, punishReturn: 0.2 };
  assert.equal(M.screenScore(sc, 'margin'), 0.4);
  assert.equal(M.screenScore(sc, 'stability'), -0.05);
  assert.equal(M.screenScore(sc, 'snapBack'), 0);
  const cases = [
    { truth: { coordinated: true, highPrice: true }, screens: { margin: 0.5, cv: 0.01, retaliation: 0.9, snapBack: 1, punishReturn: 0.9 } },
    { truth: { coordinated: false, highPrice: true }, screens: { margin: 0.45, cv: 0.02, retaliation: 0, snapBack: 0.5, punishReturn: 0 } },
    { truth: { coordinated: false, highPrice: false }, screens: { margin: 0.2, cv: 0.03, retaliation: 0.1, snapBack: 0.2, punishReturn: 0 } }
  ];
  const ev = M.evaluateScreens(cases, 'coordinated');
  assert.deepEqual(ev.map((e) => e.id), M.SCREEN_LIST.map((s) => s.id));
  assert.equal(ev.find((e) => e.id === 'retaliation').auc, 1);
  assert.equal(M.evaluateScreens(cases, 'highPrice').find((e) => e.id === 'margin').auc, 1);
});

test('a rule seller can start learning part-way through training', () => {
  const v = M.validateConfig({ firmTypes: ['learn', 'nash'], adoptAt: [-1, 60000] });
  assert.deepEqual(v.errors, []);
  assert.ok(M.validateConfig({ adoptAt: [5, -1] }).errors.some((e) => /starts with a rule/.test(e)));
  assert.ok(M.validateConfig({ firmTypes: ['learn', 'nash'], adoptAt: [-1, 4000000] }).errors.some((e) => /before maxPeriods/.test(e)));
  assert.ok(M.validateConfig({ adoptAt: 3 }).errors.some((e) => /must be a list/.test(e)));
  assert.deepEqual(M.validateConfig({ firmTypes: ['nash', 'match'], adoptAt: [-1, 0] }).errors, []);
  const tr = new M.Trainer(fast({ firmTypes: ['learn', 'nash'], adoptAt: [-1, 60000], seed: 3, maxPeriods: 600000 }));
  assert.deepEqual(tr.learn, [true, false]);
  assert.equal(tr.epsF[1], 0);
  tr.run(60000);
  assert.equal(tr.t, 60000);
  assert.equal(tr.done, false, 'cannot settle while an adoption is pending');
  tr.run(1);
  assert.deepEqual(tr.learn, [true, true]);
  assert.ok(tr.epsF[1] > 0.99 && tr.epsF[0] < tr.epsF[1]);
  tr.runToEnd();
  assert.ok(tr.converged && tr.t > 60000 + 10000);
});

test('adoption leaves runs without it unchanged', () => {
  const a = M.train(fast({ seed: 21 })), b = M.train(fast({ seed: 21, adoptAt: [-1, -1, -1] }));
  assert.equal(a.t, b.t);
  assert.deepEqual(Array.from(a.Q[0]), Array.from(b.Q[0]));
});

test('the pilot helpers measure each stage against the status quo', () => {
  const base = Object.assign(M.defaultConfig(), FAST);
  const r = M.pilotRun(base, 'nash', 100000, 2);
  for (const k of ['pilot', 'scaled', 'together']) {
    assert.ok(k in r.upliftA && k in r.upliftB);
    assert.equal(typeof r[k].avgGain, 'number');
  }
  // against a rival that keeps the competitive price, the pilot cannot do better than about competitive
  assert.ok(Math.abs(r.upliftA.pilot) < 0.05, 'pilot uplift ' + r.upliftA.pilot);
  assert.equal(r.upliftB.pilot, 0);
  assert.equal(r.statusQuo.price[0], r.statusQuo.price[1]);
  assert.ok(r.pilotBlocks === 10 && r.history.length > r.pilotBlocks);
  const cfg = M.pilotConfig(base, 'match', 100000, 5);
  assert.deepEqual([cfg.firmTypes[1], cfg.adoptAt[1], cfg.seed, cfg.nFirms], ['match', 100000, 5, 2]);
  assert.ok(cfg.maxPeriods >= 3100000);
  assert.deepEqual(M.togetherConfig(base, 5).adoptAt, [-1, -1, -1]);
});

test('the permutation test is one-sided and q-values follow Benjamini-Hochberg', () => {
  const a = [], b = [];
  for (let t = 0; t < 200; t++) { a.push(2); b.push(2); }
  for (let t = 5; t < 190; t += 17) a[t] = 1.8;           // A cuts now and then, B never answers
  for (let t = 13; t < 190; t += 23) b[t] = 1.8;           // B cuts on its own schedule
  const r = M.permutationTest([a, b], { reps: 99 });
  assert.ok(r.observed <= 0);
  assert.equal(r.pValue, 1);
  // hand-worked example: p = 0.01, 0.04, 0.03, 0.2, 0.5 with m = 5
  const q = M.benjaminiHochberg([0.01, 0.04, 0.03, 0.2, 0.5]);
  const want = [0.05, 0.05, 0.05, 0.25, 0.5];
  q.forEach((x, i) => assert.ok(Math.abs(x - want[i]) < 1e-12, i + ': ' + x));
  const withGap = M.benjaminiHochberg([0.01, NaN]);
  assert.ok(Math.abs(withGap[0] - 0.02) < 1e-12, 'a missing p-value still counts as a test');
  assert.ok(Number.isNaN(withGap[1]));
  assert.deepEqual(M.benjaminiHochberg([]), []);
});
