// Prints one JSON object of reference outputs from the JavaScript model, for
// tests/python/test_agreement.py to compare against the Python port.
//
// Numbers JSON cannot carry (NaN, Infinity, -Infinity and negative zero) are
// written as {"__float__": "NaN"} and so on, so that nothing is lost.
'use strict';
const { loadModel } = require('./load_model.js');
const QC = loadModel();

// ---------------------------------------------------------------- inputs

const EXP_INPUTS = [0, -0, 1, -1, 0.5, -0.5, 1e-10, -1e-10, 0.1, 3.14159, -37.5, 2.302585092994046,
  10, -10, 100, -100, 699.9, 700, 700.1, -700, -700.1, -745, -699.99, 40, -24.7, NaN, Infinity, -Infinity,
  // inputs where term * r / i and term * (r / i) give different results, so the grouping is pinned down
  -30.06829858089075, 37.94591722617071, -2.589814148856796, 11.297820978563365];
const LOG_INPUTS = [0, -0, -1, NaN, Infinity, -Infinity, 1, 2, 0.5, 0.75, 1.5, 1.4999999999, 0.7499999,
  3, 10, 123.456, 1e-5, 1e-300, 5e-324, 1e300, 1.7976931348623157e308, 1.0000001, 0.9999999];
const ROUND_INPUTS = [[0.49999999999999994, 0], [0.5, 0], [-0.5, 0], [-0.4, 0], [2.5, 0], [-2.5, 0],
  [4503599627370497, 0], [-4503599627370497, 0], [1.005, 2], [1.255, 2], [-0.004, 2], [123.4567, 3],
  [0.1 + 0.2, 1], [1e300, 2], [NaN, 2], [Infinity, 1], [-0, 3], [2.675, 2], [1234.5678, 0], [7.5, 0]];
const RNG_SEEDS = [1, 42, 4294967295, 0, 123456789, 2.9, -1, 4294967301];
const STATS_INPUTS = [[], [3], [1, 2], [2.5, -1.25, 7, 0.1, 0.2, 0.3], [5, 4, 3, 2, 1, 1e-9, -1e9],
  [0.1, 0.1, 0.1, 0.1]];
const QUANTILE_QS = [0, 0.05, 0.25, 0.5, 0.75, 0.95, 1, 1 / 3];

const PRICE_MARKETS = [
  { quality: [2, 2], cost: [1, 1], outside: 0, mu: 0.25 },
  { quality: [2, 2], cost: [1, 1], outside: 0, mu: 0.05 },
  { quality: [2, 2], cost: [1, 1], outside: 0, mu: 1 },
  { quality: [2.5, 1.5], cost: [0.5, 1.2], outside: -1, mu: 0.4 },
  { quality: [1, 3], cost: [2, 0], outside: 2, mu: 0.1 },
  { quality: [2, 2, 2], cost: [1, 1, 1], outside: 0, mu: 0.25 },
  { quality: [1.5, 2.5, 3], cost: [0.2, 1.7, 0.9], outside: -1.5, mu: 0.05 },
  { quality: [2.2, 2.1, 1.9], cost: [1, 0.8, 1.3], outside: 0.5, mu: 0.75 }
];

const MARKET_CONFIGS = [
  {},
  { nPrices: 5, mu: 1, xi: 0 },
  { nPrices: 21, mu: 0.05, outside: 2, xi: 0.5 },
  { nFirms: 3, nPrices: 7, demandNoise: 0.2, quality: [1.5, 2.5, 3], cost: [0.2, 1.7, 0.9] },
  { nFirms: 3, nPrices: 21, demandNoise: 0.5, quality: [1.5, 2.5, 3], cost: [0.2, 1.7, 0.9], mu: 0.05, outside: -1.5, xi: 0.5 },
  { quality: [2.5, 1.5], cost: [0.5, 1.2], outside: -1, mu: 0.4, nPrices: 9, demandNoise: 0.35 }
];

const VALIDATE_INPUTS = [
  null, {}, { nFirms: 3, nPrices: 7 },
  { mu: '0.5', nPrices: ' 7 ', alpha: 'abc', beta: 1, delta: -0.5 },
  { mu: 0, xi: 0.6, outside: '-3', exploreFloor: true, demandNoise: 'Infinity', stableWindow: 300000 },
  { nFirms: 2.6, nPrices: 10.5, maxPeriods: 20000.4, stableWindow: 999.5 },
  { nFirms: '0x3', nPrices: '1e1', xi: '.25', cost: [0.5], quality: [5, null, '2.5'] },
  { quality: 'x', cost: { 0: 1 }, firmTypes: ['nash', 'nash'] },
  { firmTypes: ['bogus', 'match', 'undercut'] }, { firmTypes: 'nl' }, { firmTypes: { 1: 'nash' } },
  { firmTypes: 7 }, { firmTypes: null }, { firmTypes: ['match', null, 'learn', 'nash'] }, { firmTypes: [] },
  { memory: 'partial' }, { memory: 'own' }, { memory: 3 },
  { sharedVendor: true, quality: [2, 2.5] }, { sharedVendor: true, firmTypes: ['learn', 'nash'] },
  { sharedVendor: true }, { sharedVendor: 0 }, { sharedVendor: 'yes' }, { sharedVendor: [] },
  { seed: '12' }, { seed: '1e3' }, { seed: '0x10' }, { seed: -1 }, { seed: 1.5 }, { seed: 4294967296 },
  { seed: 4294967295 }, { seed: null }, { seed: true }, { seed: [] }, { seed: [7] }, { seed: '' },
  { seed: 'abc' }, { seed: [1, 2] }, { seed: {} }, { seed: [[' 9 ']] },
  { seed: false }, { seed: ' 12 ' }, { seed: '\t\n' }, { seed: String.fromCharCode(160) + '7' + String.fromCharCode(8232) },
  { seed: '0x1F' }, { seed: '-0' }, { seed: 0 }, { seed: 'Infinity' },
  { stableWindow: 50000, maxPeriods: 30000 }, { maxPeriods: 7e6, stableWindow: 1000 },
  { xi: [0.1], outside: {}, alpha: null, beta: '5e-7', delta: '0.99', mu: ' \n0.05\t' },
  { nFirms: 3, firmTypes: ['nash', 'match', 'undercut'] }, { nFirms: 3, firmTypes: ['nash', 'match', 'learn'] },
  { mu: '1_0', nPrices: 'Infinity', alpha: '-Infinity', beta: '+0.0001', delta: '0b1', xi: '0o0' }
];

const FAST = { beta: 5e-5, maxPeriods: 150000, stableWindow: 10000 };
function fast(extra) { return Object.assign({}, FAST, extra); }

const TRAIN_CASES = [
  ['baseline', { beta: 4e-5, maxPeriods: 250000, stableWindow: 20000 }],
  ['memory-own', fast({ memory: 'own' })],
  ['memory-none', { memory: 'none', beta: 1e-4, maxPeriods: 60000, stableWindow: 5000 }],
  ['delta-0', fast({ delta: 0 })],
  ['three-firms', { nFirms: 3, nPrices: 5, beta: 5e-5, maxPeriods: 200000, stableWindow: 10000 }],
  ['three-mixed-noisy', { nFirms: 3, nPrices: 5, firmTypes: ['learn', 'match', 'learn'], demandNoise: 0.1,
    beta: 1e-4, maxPeriods: 120000, stableWindow: 8000, seed: 5 }],
  ['learn-nash', fast({ firmTypes: ['learn', 'nash'] })],
  ['learn-match', fast({ firmTypes: ['learn', 'match'] })],
  ['learn-undercut', fast({ firmTypes: ['learn', 'undercut'] })],
  ['undercut-learn', fast({ firmTypes: ['undercut', 'learn'], seed: 31 })],
  ['shared-vendor', fast({ sharedVendor: true })],
  ['three-vendor', { nFirms: 3, nPrices: 5, sharedVendor: true, beta: 1e-4, maxPeriods: 80000, stableWindow: 5000 }],
  ['demand-noise', fast({ demandNoise: 0.2 })],
  ['explore-floor', { exploreFloor: 0.05, beta: 1e-4, maxPeriods: 50000, stableWindow: 20000 }],
  ['asymmetric-cost', fast({ cost: [0.8, 1.2], quality: [2.2, 1.9], mu: 0.4, outside: -0.5 })],
  ['seven-prices', { nPrices: 7, beta: 2e-5, maxPeriods: 200000, stableWindow: 15000, alpha: 0.3, delta: 0.9 }],
  ['other-seed', fast({ seed: 987654321, xi: 0.25 })]
];

// Run in pieces of 7,777 periods; must match a single run to the end.
const STEPWISE_CASE = ['stepwise', fast({ demandNoise: 0.3, seed: 77 })];

const BOOTSTRAP_INPUTS = [
  [[1, 2, 3, 4, 5.5], 0.9, 1000, 7], [[0.1, -0.3, 2.2], 0.95, 200, undefined], [[], 0.9], [[3.3], 0.9],
  [[0.12, 0.5, 0.33, 0.9, -0.2, 0.71, 0.05, 0.66, 0.4, 0.38, 0.27, 0.91, 0.02, 0.58, 0.44], 0.8, 500, 99],
  [[1, 1, 2], 0.5, 0, 3],
  [[0.5, NaN, 0.7, 0.2], 0.9, 1000, 101], [[NaN, 1, 2, 3, 4, 5, 6, 7], 0.9, 1000, 202],
  [[0.1, 0.2, NaN, NaN, 0.4, 0.9, 0.33, 0.12, 0.8, 0.77], 0.8, 700, 5],
  [[NaN, NaN], 0.9], [[NaN, 2.5, NaN], 0.9, 100, 1]
];
const ROC_INPUTS = [
  [[0.9, 0.8, 0.7, 0.6, 0.55, 0.5, 0.4, 0.3], [true, true, false, true, false, false, true, false]],
  [[1, 1, 0.5, 0.5, 0.5, 0, -0, 0], [true, false, true, false, false, true, false, false]],
  [[0.3, 0.2, 0.1], [true, true, true]],
  [[0.3, 0.2, 0.1], [false, false, false]],
  [[Infinity, 2, -Infinity, 2, Infinity], [true, false, false, true, false]],
  [[], []],
  [[0.2, 0.4, 0.4, 0.1, 0.9, 0.9, 0.9], [1, 0, 1, 0, 1, 1, 0]],
  [[0.3, NaN, 0.9, 0.1, NaN, 0.5, 0.7, NaN, 0.2], [true, false, true, false, true, true, false, false, true]],
  [[NaN, NaN, NaN], [true, false, true]],
  [[NaN, -Infinity, 0.5, NaN, -0, 0, Infinity, 0.5], [true, false, true, true, false, true, false, false]]
];
const CONFUSION_INPUTS = [
  [[0.1, 0.5, 0.9, 0.3], [false, true, true, false], 0.4],
  [[0.1, 0.5, 0.9, 0.3], [false, true, true, false], 1],
  [[0.1, 0.5, 0.9, 0.3], [false, false, false, false], 0],
  [[], [], 0.5]
];
const SCREEN_SCORE_INPUTS = [
  { margin: null, cv: 0.1, retaliation: NaN, snapBack: NaN, punishReturn: 0.3 },
  { margin: 0.42, cv: 0, retaliation: -0.1, snapBack: 0.5, punishReturn: NaN }
];
const SYNTHETIC_PRICES = [
  [[2, 2, 2, 1.8, 1.8, 2, 2, 2, 1.9, 2, 2, 2, 2, 2, 1.5, 1.5, 1.5, 1.5, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1.7, 2, 2, 2],
    [2, 2, 2, 2, 1.7, 1.9, 2, 2, 2, 2, 1.9, 2, 2, 2, 2, 1.6, 1.6, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1.8, 2, 2]],
  [[1, 1, 1, 1, 1, 1], [1, 1, 1, 1, 1, 1]],
  boundarySeries(),
  snapBackSeries()
];

// A clear unprovoked cut, then a recovery that sits exactly on the snap-back threshold for longer
// than the window, so the snap-back decision depends on the threshold's grouping.
function snapBackSeries() {
  const tol = 0.005, a = [], b = [];
  [2.751364, 2.120597, 1.539793, 1.5].forEach(function (p) {
    [p * (1 - tol), p - p * tol, p * (1 - tol) * (1 + 2.3e-16)].forEach(function (q) {
      a.push(p, 0.9 * p);
      for (let k = 0; k < 11; k++) a.push(q);
      a.push(p, p);
      for (let k = 0; k < 15; k++) b.push(p);
    });
  });
  return [a, b];
}

// Prices sitting exactly on the cut and "still" thresholds, worked out in several groupings,
// so that any change to how the screens group their arithmetic changes a decision.
function boundarySeries() {
  const tol = 0.005, a = [], b = [];
  // the last three are prices where p * (1 - tol) and p - p * tol differ
  [1.7377012974373751, 1.5, 2.25, 0.3, 2.751364, 2.120597, 1.539793].forEach(function (p) {
    const qs = [p * (1 - tol), p - p * tol, (1 - tol) * p, p * (1 - tol) * (1 - 2.3e-16),
      p * (1 - tol) * (1 + 2.3e-16), p + tol * p, p - tol * p, p * (1 + tol)];
    qs.forEach(function (q) { a.push(p, q, p, p); b.push(p, p, q, p); });
  });
  return [a, b];
}

// Arrays long enough for the sort's merges, with ties, both zeros and both infinities, so that the
// stability of the sort (the order of -0 and 0, which keeps its sign) is checked too. The model never
// sorts NaN any more, so these contain none.
function sortCases() {
  const r = new QC.Rng(2024), out = [], sizes = [2, 5, 31, 64, 65, 130, 257, 700, 1500];
  const special = [-0, 0, Infinity, -Infinity];
  for (let k = 0; k < 60; k++) {
    const n = sizes[k % sizes.length], kind = r.int(5), rate = [0, 0.01, 0.1, 0.5, 1][r.int(5)], xs = [];
    for (let i = 0; i < n; i++) {
      let v;
      if (kind === 0) v = Math.floor(r.next() * 50) / 4;
      else if (kind === 1) v = i + (r.next() < 0.05 ? -30 * r.next() : 0);
      else if (kind === 2) v = n - i + (r.next() < 0.05 ? 30 * r.next() : 0);
      else if (kind === 3) v = Math.floor(i / 40) % 2 ? i : -i;
      else v = r.next() < 0.5 ? Math.floor(r.next() * 3) : r.next();
      xs.push(r.next() < rate ? special[r.int(special.length)] : v);
    }
    out.push(xs);
  }
  return out;
}

const CASE_BASE_INPUT = { beta: 5e-5, maxPeriods: 150000, stableWindow: 10000 };
const CASE_SEED = 2026;
const CASE_KS = [0, 1, 2, 3];
const CASE_OPTS = { days: 200 };
const EXTRA_METAS = [[17, 1], [0, 4294967295], [5, 0.5]];
const SCENARIO_RUNS = [['vendor', 11], ['myopic', 3]];
const SPARSE_BASE = { nFirms: 3, quality: [2.5, 1, 3], cost: [0.5, 1, 2], firmTypes: ['learn'], maxPeriods: 8e6 };
const SPARSE_IDS = ['fixedrival', 'third', 'vendor'];

// ---------------------------------------------------------------- helpers

function arr(x) { return x === null || x === undefined ? x : Array.from(x); }
function loopSum(xs) { let s = 0; for (let k = 0; k < xs.length; k++) s += xs[k]; return s; }

function marketView(mk, full) {
  const out = {
    n: mk.n, m: mk.m, nJoint: mk.nJoint, quality: mk.quality, cost: mk.cost, outside: mk.outside, mu: mk.mu,
    pN: mk.pN, pM: mk.pM, piN: mk.piN, piM: mk.piM, csN: mk.csN, csM: mk.csM, grids: mk.grids,
    levels: mk.levels, nashIdx: mk.nashIdx, monoIdx: mk.monoIdx,
    profitSums: mk.profit.map(function (lv) { return lv.map(loopSum); })
  };
  const total = mk.levels * mk.n * mk.nJoint;
  if (full || total <= 4000) {
    out.profit = mk.profit.map(function (lv) { return lv.map(arr); });
  } else {
    const sample = [];
    for (let l = 0; l < mk.levels; l++) {
      for (let i = 0; i < mk.n; i++) {
        for (let j = (l * 7 + i * 3) % 97; j < mk.nJoint; j += 97) sample.push([l, i, j, mk.profit[l][i][j]]);
      }
    }
    out.profitSample = sample;
  }
  return out;
}

function trainerState(tr) {
  return {
    cfg: tr.cfg, errors: tr.errors, t: tr.t, converged: tr.converged, done: tr.done, eps: tr.eps,
    last: tr.last, stable: tr.stable, learn: tr.learn, stateSize: tr.stateSize,
    stateTab: tr.stateTab.map(arr), ruleTab: tr.ruleTab.map(arr),
    best: tr.best.map(arr), bestV: tr.bestV.map(arr), Q: tr.Q.map(arr),
    qSum: tr.Q.map(function (q) { return q ? loopSum(q) : null; }),
    qFirst: tr.Q.map(function (q) { return q ? q[0] : null; }),
    qLast: tr.Q.map(function (q) { return q ? q[q.length - 1] : null; }),
    history: tr.history, acc: tr._acc, rngState: tr.rng.a
  };
}

function analyse(tr) {
  const mk = tr.market, n = mk.n, out = trainerState(tr);
  out.market = marketView(mk, false);
  const lc = QC.limitCycle(tr);
  out.limitCycle = lc;
  out.limitCycleFrom = [0, mk.nJoint - 1, Math.floor(mk.nJoint / 3)].map(function (j) { return QC.limitCycle(tr, j); });
  out.greedy = [0, 1, mk.nJoint - 1, tr.last].map(function (j) { return tr.greedyActions(j); });
  out.greedyNext = [0, 1, mk.nJoint - 1, tr.last].map(function (j) { return tr.greedyNext(j); });
  out.staticBR = [];
  for (let i = 0; i < n; i++) out.staticBR.push([0, tr.last, lc.states[0]].map(function (j) { return QC.staticBestResponse(mk, i, j); }));
  out.outcome = QC.outcomeOf(mk, lc.states);
  out.outcomeAll = QC.outcomeOf(mk, [0, 1, 2, mk.nJoint - 1]);
  out.summary = QC.summarise(tr);
  out.impulse = [];
  for (let d = 0; d < n; d++) out.impulse.push(QC.impulseResponse(tr, { deviator: d }));
  out.impulseCustom = QC.impulseResponse(tr, { deviator: n - 1, price: 0, horizon: 8 });
  out.impulseBest = QC.impulseResponse(tr, { deviator: 0, price: 'best', horizon: 30, cycle: [lc.states[0], 0] });
  out.impulseShort = QC.impulseResponse(tr, { deviator: 1, horizon: 1 });
  // horizons are floored and kept within 2 to 500
  out.impulseHorizons = [0, 2.7, 1000, NaN, '7', -3, Infinity].map(function (h) {
    return QC.impulseResponse(tr, { deviator: 0, horizon: h });
  });
  out.bestResponse = [];
  for (let i = 0; i < n; i++) out.bestResponse.push(QC.bestResponseCheck(tr, i, lc.states));
  out.bestResponseNoCycle = QC.bestResponseCheck(tr, n - 1);
  const prices = QC.observe(tr, { days: 120 });
  const pricesAlt = QC.observe(tr, { days: 60, experiment: 0.2, seed: 5 });
  out.prices = prices;
  out.pricesAlt = pricesAlt;
  out.screens = QC.screens(prices, { cost: mk.cost, detail: true });
  out.screensAlt = QC.screens(pricesAlt, { cost: mk.cost, detail: true, tol: 0.02, window: 5 });
  out.screensPlain = QC.screens(pricesAlt);
  out.perm = QC.permutationTest(prices, { reps: 99, cost: mk.cost });
  out.permAlt = QC.permutationTest(pricesAlt, { reps: 99, seed: 8, window: 5 });
  return out;
}

// ---------------------------------------------------------------- reference

const ref = {};

ref.constants = {
  LIMITS: QC.LIMITS, FIRM_TYPES: QC.FIRM_TYPES, MEMORY: QC.MEMORY, SHOCKS: QC.SHOCKS,
  SCENARIOS: QC.SCENARIOS, CASE_MIX: QC.CASE_MIX, CASE_MU: QC.CASE_MU, SCREEN_LIST: QC.SCREEN_LIST,
  defaultConfig: QC.defaultConfig()
};

ref.detExp = EXP_INPUTS.map(function (x) { return [x, QC.detExp(x)]; });
ref.detLog = LOG_INPUTS.map(function (x) { return [x, QC.detLog(x)]; });
ref.round = ROUND_INPUTS.map(function (p) { return [p[0], p[1], QC.round(p[0], p[1])]; });

ref.rng = RNG_SEEDS.map(function (seed) {
  const r = new QC.Rng(seed), values = [], ints = [];
  for (let k = 0; k < 50; k++) values.push(r.next());
  for (let k = 0; k < 20; k++) ints.push(r.int(k + 1));
  return { seed: seed, values: values, ints: ints, state: r.a };
});

ref.stats = STATS_INPUTS.map(function (xs) {
  const sorted = QC.sortedCopy(xs);
  return {
    xs: xs, mean: QC.mean(xs), sd: QC.sd(xs), sorted: sorted,
    quantiles: QUANTILE_QS.map(function (q) { return [q, QC.quantile(sorted, q)]; })
  };
});

ref.prices = PRICE_MARKETS.map(function (p) {
  const pN = QC.nashPrices(p.quality, p.cost, p.outside, p.mu);
  const pM = QC.monopolyPrices(p.quality, p.cost, p.outside, p.mu);
  const mid = pN.map(function (x, i) { return (x + pM[i]) / 2; });
  return {
    input: p, nash: pN, monopoly: pM,
    sharesNash: QC.shares(pN, p.quality, p.outside, p.mu),
    profitsNash: QC.profitsAt(pN, p.quality, p.cost, p.outside, p.mu),
    profitsMid: QC.profitsAt(mid, p.quality, p.cost, p.outside, p.mu),
    csNash: QC.consumerSurplus(pN, p.quality, p.outside, p.mu),
    csMonopoly: QC.consumerSurplus(pM, p.quality, p.outside, p.mu)
  };
});

ref.markets = MARKET_CONFIGS.map(function (input) {
  const cfg = QC.validateConfig(input).config, mk = QC.buildMarket(cfg);
  const joints = [0, 1, mk.nJoint - 1, Math.floor(mk.nJoint / 2)];
  return {
    input: input, market: marketView(mk, false),
    decoded: joints.map(function (j) { return QC.decodeJoint(j, mk.n, mk.m); }),
    encoded: joints.map(function (j) { return QC.encodeJoint(QC.decodeJoint(j, mk.n, mk.m), mk.m); }),
    nearest: mk.grids.map(function (g) { return [g[0] - 1, g[2] + 1e-9, (g[3] + g[4]) / 2, 100].map(function (p) { return QC.nearestIndex(g, p); }); })
  };
});

ref.validate = VALIDATE_INPUTS.map(function (input) {
  const v = QC.validateConfig(input);
  return { input: input, config: v.config, errors: v.errors };
});

ref.train = TRAIN_CASES.map(function (c) {
  const tr = QC.train(c[1]), out = analyse(tr);
  out.name = c[0]; out.input = c[1];
  return out;
});

(function () {
  const tr = new QC.Trainer(STEPWISE_CASE[1]);
  const marks = [];
  while (!tr.run(7777)) marks.push([tr.t, tr.eps, tr.stable, tr.last]);
  const out = trainerState(tr);
  out.name = STEPWISE_CASE[0]; out.input = STEPWISE_CASE[1]; out.marks = marks;
  out.summary = QC.summarise(tr);
  ref.stepwise = out;
})();

// Stopped before the first 10,000-period block, so there is no history and the realised gain
// falls back on the cycle's gain.
const SHORT_CASE = ['short', fast({ seed: 3 }), 5000];
(function () {
  const tr = new QC.Trainer(SHORT_CASE[1]);
  const finished = tr.run(SHORT_CASE[2]);
  const out = trainerState(tr);
  out.name = SHORT_CASE[0]; out.input = SHORT_CASE[1]; out.steps = SHORT_CASE[2]; out.finished = finished;
  out.summary = QC.summarise(tr);
  out.bestResponse = QC.bestResponseCheck(tr, 0, out.summary.cycle);
  ref.short = out;
})();

// Value iteration that cannot settle within 5,000 sweeps: a validated delta is at most 0.99, so the
// discount factor is raised after training to reach the cap.
const UNSETTLED_CASE = [fast({ nPrices: 5, seed: 9 }), 3000, 0.9999];
(function () {
  const tr = new QC.Trainer(UNSETTLED_CASE[0]);
  tr.run(UNSETTLED_CASE[1]);
  tr.cfg.delta = UNSETTLED_CASE[2];
  ref.unsettled = { spec: UNSETTLED_CASE, out: QC.bestResponseCheck(tr, 0) };
})();

ref.bootstrap = BOOTSTRAP_INPUTS.map(function (b) {
  return { args: b.slice(), out: QC.bootstrapMean(b[0], b[1], b[2], b[3]) };
});
ref.roc = ROC_INPUTS.map(function (r) { return { scores: r[0], labels: r[1], out: QC.rocCurve(r[0], r[1]) }; });
ref.confusion = CONFUSION_INPUTS.map(function (c) { return { args: c, out: QC.confusion(c[0], c[1], c[2]) }; });
ref.screenScore = SCREEN_SCORE_INPUTS.map(function (sc) {
  return { sc: sc, out: ['margin', 'stability', 'retaliation', 'snapBack', 'punishReturn', 'other'].map(function (id) { return QC.screenScore(sc, id); }) };
});
ref.syntheticScreens = SYNTHETIC_PRICES.map(function (p) {
  return {
    prices: p,
    screens: QC.screens(p, { detail: true, cost: [1, 1] }),
    screensTight: QC.screens(p, { tol: 0, window: 3 }),
    perm: QC.permutationTest(p, { reps: 50, seed: 1 })
  };
});

ref.sorting = sortCases().map(function (xs) { return { xs: xs, sorted: QC.sortedCopy(xs) }; });

ref.aggregate = {
  fromTraining: QC.aggregate(ref.train.slice(0, 6).map(function (r) { return r.summary; })),
  // NaN realised gains, which bootstrapMean now drops
  withNaN: QC.aggregate(ref.train.slice(0, 6).map(function (r, i) {
    return Object.assign({}, r.summary, i % 2 ? { realisedGain: NaN } : {});
  })),
  allNaN: QC.aggregate(ref.train.slice(0, 3).map(function (r) {
    return Object.assign({}, r.summary, { realisedGain: NaN });
  })),
  withShort: QC.aggregate([ref.short.summary, ref.train[0].summary, ref.train[1].summary]),
  empty: QC.aggregate([]),
  single: QC.aggregate([ref.train[0].summary])
};

(function () {
  const base = QC.validateConfig(CASE_BASE_INPUT).config;
  ref.scenarios = {
    base: base,
    applied: QC.SCENARIOS.map(function (sc) {
      return { id: sc.id, onDefault: QC.applyScenario(QC.defaultConfig(), sc.id), onBase: QC.applyScenario(base, sc.id) };
    }),
    sparseBase: SPARSE_BASE, sparseIds: SPARSE_IDS,
    onSparse: SPARSE_IDS.map(function (id) { return QC.applyScenario(SPARSE_BASE, id); }),
    byId: ['own', 'nope'].map(function (id) { return QC.scenarioById(id); }),
    unknown: (function () { try { QC.applyScenario(base, 'nope'); return null; } catch (e) { return e.message; } })(),
    runSpecs: SCENARIO_RUNS,
    runs: SCENARIO_RUNS.map(function (r) { return QC.runScenario(base, r[0], r[1]); })
  };
  ref.aggregate.fromScenarios = QC.aggregate(ref.scenarios.runs);
  const metas = CASE_KS.map(function (k) { return QC.caseConfig(base, k, CASE_SEED); });
  const cases = CASE_KS.map(function (k) { return QC.makeCase(base, k, CASE_SEED, CASE_OPTS); });
  ref.cases = {
    baseInput: CASE_BASE_INPUT, seed: CASE_SEED, ks: CASE_KS, opts: CASE_OPTS,
    metas: metas, cases: cases,
    extraMetaSpecs: EXTRA_METAS,
    extraMetas: EXTRA_METAS.map(function (a) { return QC.caseConfig(base, a[0], a[1]); }),
    evaluate: {
      coordinated: QC.evaluateScreens(cases, 'coordinated'),
      highPrice: QC.evaluateScreens(cases, 'highPrice')
    }
  };
})();

function replacer(key, value) {
  if (typeof value === 'number') {
    if (value !== value) return { __float__: 'NaN' };
    if (value === Infinity) return { __float__: 'Infinity' };
    if (value === -Infinity) return { __float__: '-Infinity' };
    if (value === 0 && 1 / value < 0) return { __float__: '-0' };
  }
  return value;
}

process.stdout.write(JSON.stringify(ref, replacer));
