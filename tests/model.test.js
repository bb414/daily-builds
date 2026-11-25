// Tests for the browser app's MODEL block. Run with: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadModel } = require('./load_model.js');

const M = loadModel();
const train = M.generateCohort(M.DEFAULTS.nTrain, M.DEFAULTS.trainSeed);
const model = M.trainModel(train);
const tables = M.costTables(train);
const cohort = M.generateCohort(M.DEFAULTS.nAudit, M.DEFAULTS.auditSeed);
const background = M.backgroundSample(train, 64);
const settings = M.defaultSettings();

// Every integer combination of the movable features within their caps: the
// slow, obviously-correct answer that the search must match.
function bruteForce(x, st, maxLevers, margin) {
  const ranges = M.FEATURES.map(function (f, j) {
    if (!st[j].actionable || st[j].cap <= 0) return [x[j]];
    const out = [];
    if (f.dir > 0) for (let v = x[j]; v <= Math.min(f.max, x[j] + st[j].cap); v++) out.push(v);
    else for (let v = x[j]; v >= Math.max(f.min, x[j] - st[j].cap); v--) out.push(v);
    return out;
  });
  let best = null;
  const z = x.slice();
  (function rec(j) {
    if (j === M.D) {
      let levers = 0;
      let cost = 0;
      for (let k = 0; k < M.D; k++) {
        if (z[k] !== x[k]) levers += 1;
        cost += M.featureCost(tables, st, k, x[k], z[k]);
      }
      if (levers > maxLevers) return;
      if (M.predict(model, z) >= model.threshold + (margin || 0) && (best === null || cost < best - 1e-12)) best = cost;
      return;
    }
    for (const v of ranges[j]) { z[j] = v; rec(j + 1); }
    z[j] = x[j];
  })(0);
  return best;
}

test('random numbers are reproducible and in [0, 1)', function () {
  const a = M.mulberry32(7);
  const b = M.mulberry32(7);
  for (let i = 0; i < 1000; i++) {
    const u = a();
    assert.equal(u, b());
    assert.ok(u >= 0 && u < 1);
  }
});

test('cohort respects feature ranges and the shortlisting quota', function () {
  assert.equal(train.length, 1600);
  const shortlisted = train.filter(function (r) { return r.y === 1; }).length;
  assert.equal(shortlisted, Math.floor(0.38 * 1600 + 0.5));
  train.forEach(function (r) {
    r.x.forEach(function (v, j) {
      assert.ok(Number.isInteger(v));
      assert.ok(v >= M.FEATURES[j].min && v <= M.FEATURES[j].max);
    });
    assert.ok(r.g === 0 || r.g === 1);
  });
});

test('a stronger pool raises average test scores', function () {
  const weak = M.generateCohort(800, 5, 0);
  const strong = M.generateCohort(800, 5, 1);
  const avg = function (rows) { return M.mean(rows.map(function (r) { return r.x[0]; })); };
  assert.ok(avg(strong) > avg(weak) + 3);
});

test('model learns the historic decisions reasonably well', function () {
  let ok = 0;
  cohort.forEach(function (r) { if ((M.predict(model, r.x) >= 0.5 ? 1 : 0) === r.y) ok += 1; });
  assert.ok(ok / cohort.length > 0.75, 'held-out accuracy ' + ok / cohort.length);
  assert.equal(model.trees.length, M.DEFAULTS.trees);
});

test('every split threshold is recorded and sorted', function () {
  model.splits.forEach(function (s) {
    for (let k = 1; k < s.length; k++) assert.ok(s[k] > s[k - 1]);
  });
  assert.ok(model.splits[0].length > 5, 'test score should be split often');
});

test('cost tables are strictly increasing so every change costs something', function () {
  tables.forEach(function (cdf) {
    for (let k = 1; k < cdf.length; k++) assert.ok(cdf[k] > cdf[k - 1]);
    assert.ok(cdf[0] > 0 && cdf[cdf.length - 1] < 1);
  });
});

test('recourse is exact: matches brute force over every integer combination', function () {
  const rejected = cohort.filter(function (r) { return M.predict(model, r.x) < 0.5; }).slice(0, 25);
  rejected.forEach(function (r) {
    const res = M.findRecourse(model, tables, r.x, settings);
    const bf = bruteForce(r.x, settings, M.D, 0);
    if (bf === null) assert.equal(res.status, 'none');
    else {
      assert.equal(res.status, 'found');
      assert.ok(Math.abs(res.cost - bf) < 1e-9, 'search ' + res.cost + ' vs brute force ' + bf);
    }
  });
});

test('recourse stays exact with a lever limit, a margin and other weights', function () {
  const st = M.defaultSettings();
  st[0].weight = 3;
  st[1].cap = 6;
  st[5].actionable = true;
  const rejected = cohort.filter(function (r) { return M.predict(model, r.x) < 0.5; }).slice(25, 40);
  rejected.forEach(function (r) {
    const res = M.findRecourse(model, tables, r.x, st, { maxLevers: 2, margin: 0.05 });
    const bf = bruteForce(r.x, st, 2, 0.05);
    if (bf === null) assert.equal(res.status, 'none');
    else assert.ok(Math.abs(res.cost - bf) < 1e-9);
  });
});

test('plans respect direction, caps, fixed features and reach the score', function () {
  cohort.slice(0, 120).forEach(function (r) {
    const res = M.findRecourse(model, tables, r.x, settings, { maxLevers: 2 });
    if (res.status !== 'found') return;
    assert.ok(res.score >= 0.5);
    assert.ok(res.changes.length <= 2);
    let total = 0;
    res.changes.forEach(function (ch) {
      const f = M.FEATURES[ch.j];
      assert.ok(settings[ch.j].actionable, f.key + ' is fixed');
      assert.ok(f.dir > 0 ? ch.to > ch.from : ch.to < ch.from);
      assert.ok(Math.abs(ch.to - ch.from) <= settings[ch.j].cap);
      total += ch.cost;
    });
    assert.ok(Math.abs(total - res.cost) < 1e-9);
    assert.equal(M.predict(model, res.values), res.score);
  });
});

test('shortlisted applicants need nothing; impossible ones get no route', function () {
  const yes = M.findRecourse(model, tables, [90, 20, 4, 2, 4, 0], settings);
  assert.equal(yes.status, 'already');
  const st = M.defaultSettings().map(function (s) { return Object.assign({}, s, { actionable: false }); });
  const no = M.findRecourse(model, tables, [40, 2, 0, 0, 1, 12], st);
  assert.equal(no.status, 'none');
});

test('route options: distinct main levers, cheapest first, first is the optimum', function () {
  cohort.slice(0, 60).forEach(function (r) {
    const best = M.findRecourse(model, tables, r.x, settings);
    const opts = M.recourseOptions(model, tables, r.x, settings);
    if (best.status !== 'found') { assert.equal(opts.options.length, 0); return; }
    assert.ok(opts.options.length >= 1);
    assert.ok(Math.abs(opts.options[0].cost - best.cost) < 1e-9);
    const levers = opts.options.map(function (o) { return o.lever; });
    assert.equal(new Set(levers).size, levers.length);
    for (let k = 1; k < opts.options.length; k++) assert.ok(opts.options[k].cost >= opts.options[k - 1].cost);
  });
});

test('Shapley values add up exactly to score minus average', function () {
  cohort.slice(0, 10).forEach(function (r) {
    const sh = M.shapley(model, r.x, background);
    const sum = sh.phi.reduce(function (a, b) { return a + b; }, 0);
    assert.ok(Math.abs(sum - (sh.value - sh.base)) < 1e-9);
    assert.ok(Math.abs(sh.value - M.predict(model, r.x)) < 1e-12);
  });
});

// The textbook definition: all 64 coalitions of the whole model.
function bruteShapley(x, bg) {
  const n = 1 << M.D;
  const v = [];
  for (let mask = 0; mask < n; mask++) {
    let s = 0;
    bg.forEach(function (b) {
      const z = b.map(function (val, j) { return (mask >> j) & 1 ? x[j] : val; });
      s += M.predict(model, z);
    });
    v.push(s / bg.length);
  }
  const fact = [1, 1, 2, 6, 24, 120, 720];
  const phi = new Array(M.D).fill(0);
  for (let mask = 0; mask < n; mask++) {
    let size = 0;
    for (let j = 0; j < M.D; j++) if ((mask >> j) & 1) size += 1;
    for (let j = 0; j < M.D; j++) if (!((mask >> j) & 1)) phi[j] += fact[size] * fact[M.D - size - 1] / fact[M.D] * (v[mask | (1 << j)] - v[mask]);
  }
  return phi;
}

test('tree-by-tree Shapley matches the full 64-coalition definition', function () {
  cohort.slice(0, 12).concat(M.PRESETS.map(function (p) { return { x: p.x }; })).forEach(function (r) {
    const fast = M.shapley(model, r.x, background);
    const slow = bruteShapley(r.x, background);
    fast.phi.forEach(function (v, j) { assert.ok(Math.abs(v - slow[j]) < 1e-12, 'feature ' + j + ': ' + v + ' vs ' + slow[j]); });
  });
  model.trees.forEach(function (t) { assert.ok(M.treeFeatures(t).length <= 3); });
});

test('Shapley gives zero to a feature that matches every reference applicant', function () {
  const bg = background.map(function (b) { const c = b.slice(); c[3] = 2; return c; });
  const sh = M.shapley(model, [60, 8, 2, 2, 3, 0], bg);
  assert.ok(Math.abs(sh.phi[3]) < 1e-12);
});

test('audit counts add up and the groups differ as designed', function () {
  const a = M.audit(model, tables, cohort, settings);
  let n = 0;
  a.groups.forEach(function (G) {
    n += G.n;
    assert.equal(G.shortlisted + G.rejected, G.n);
    assert.ok(G.feasible <= G.rejected);
  });
  assert.equal(n, cohort.length);
  assert.ok(a.groups[1].shortlistRate < a.groups[0].shortlistRate);
  assert.ok(a.groups[1].medianCost > a.groups[0].medianCost);
  assert.equal(a.rows.length, cohort.length);
});

test('every example applicant still matches its name', function () {
  const byName = {};
  M.PRESETS.forEach(function (p) {
    byName[p.name] = {
      score: M.predict(model, p.x),
      opts: M.recourseOptions(model, tables, p.x, settings),
      sh: M.shapley(model, p.x, background)
    };
  });
  const worst = function (sh) { return sh.phi.indexOf(Math.min.apply(null, sh.phi)); };
  assert.ok(byName['Near miss'].score > 0.45 && byName['Near miss'].score < 0.5);
  assert.ok(byName['Four ways in'].opts.options.length >= 4);
  assert.equal(worst(byName['Held back by degree result'].sh), 4);
  assert.equal(byName['Held back by degree result'].opts.status, 'found');
  assert.equal(worst(byName['Held back by a past gap'].sh), 5);
  assert.equal(byName['Held back by a past gap'].opts.status, 'found');
  const se = byName['Strong experience, weak test'];
  assert.equal(se.opts.options[0].lever, 0);
  assert.ok(se.sh.phi[1] > 0);
  assert.equal(byName['No route within a year'].opts.status, 'none');
  assert.ok(byName['Already shortlisted'].score >= 0.5);
});

test('one search answers every margin exactly as separate searches do', function () {
  const st = M.defaultSettings();
  st[5].actionable = true;
  cohort.slice(0, 150).forEach(function (r) {
    const multi = M.searchRoutes(model, tables, r.x, st, { maxLevers: 3 }, M.MARGINS);
    M.MARGINS.forEach(function (m, k) {
      const one = M.findRecourse(model, tables, r.x, st, { maxLevers: 3, margin: m });
      assert.equal(multi[k].status, one.status);
      assert.equal(multi[k].cost, one.cost);
      assert.deepEqual(multi[k].values, one.values);
      assert.equal(multi[k].explored, one.explored);
    });
  });
});

test('routes always hold against the model they were made for', function () {
  const table = M.routeTable(model, tables, cohort, settings, {}, M.MARGINS);
  const same = M.holdSummary(model, cohort, table, M.MARGINS);
  same.forEach(function (r) {
    assert.equal(r.all.kept, r.all.routes);
    assert.equal(r.groups[0].routes + r.groups[1].routes, r.all.routes);
    assert.equal(r.groups[0].rejected + r.groups[1].rejected, r.all.rejected);
  });
  for (let k = 1; k < M.MARGINS.length; k++) {
    assert.ok(same[k].all.routes <= same[k - 1].all.routes, 'a higher margin never adds routes');
    assert.ok(same[k].all.medianCost >= same[k - 1].all.medianCost);
  }
});

test('a retrained model breaks many minimal routes and a margin repairs most', function () {
  const table = M.routeTable(model, tables, cohort, settings, {}, M.MARGINS);
  const next = M.nextModel(0, 1);
  assert.notDeepEqual(next.splits, model.splits);
  const h = M.holdSummary(next, cohort, table, M.MARGINS);
  h.forEach(function (r) { assert.ok(r.all.kept <= r.all.routes && r.all.routes <= r.all.rejected); });
  assert.ok(h[0].all.keptShare < 0.6, 'minimal routes are fragile');
  assert.ok(h[h.length - 1].all.keptShare > 0.85, 'a wide margin keeps most');
  const stronger = M.holdSummary(M.nextModel(4 / 6, 1), cohort, table, M.MARGINS);
  assert.ok(stronger[0].all.keptShare < h[0].all.keptShare, 'a stronger pool raises the bar');
});

test('explanation versus advice: counts are consistent with the audit', function () {
  const a = M.audit(model, tables, cohort, settings);
  const gap = M.explainGap(model, cohort, a.rows, background, settings);
  [0, 1].forEach(function (g) {
    assert.equal(gap[g].rejected, a.groups[g].rejected);
    assert.equal(gap[g].routed, a.groups[g].feasible);
    assert.ok(gap[g].mismatch <= gap[g].routed);
  });
  const total = gap[2].matrix.reduce(function (s, row) { return s + row.reduce(function (t, v) { return t + v; }, 0); }, 0);
  assert.equal(total, gap[2].rejected);
  const noRoute = gap[2].matrix.reduce(function (s, row) { return s + row[M.D]; }, 0);
  assert.equal(noRoute, gap[2].rejected - gap[2].routed);
  assert.ok(gap[2].mismatchShare > 0.1, 'advice often points away from the explanation');
  assert.equal(M.biggestDrag([0.1, 0, 0.2, 0, 0, 0]), -1);
  assert.equal(M.biggestDrag([0.1, -0.2, -0.3, 0, -0.3, 0]), 2);
});

test('setups round-trip and fill gaps with defaults', function () {
  const st = M.defaultSettings();
  st[1].weight = 2.5;
  st[4].actionable = true;
  st[0].cap = 15;
  const setup = M.makeSetup([50, 3, 2, 0, 2, 6], st, 2, 0.1, 4, 7);
  const plain = function (v) { return JSON.parse(JSON.stringify(v)); };
  const back = M.parseSetup(plain(setup));
  assert.deepEqual(plain(back), plain({ x: [50, 3, 2, 0, 2, 6], settings: st, maxLevers: 2, margin: 0.1, points: 4, retrain: 7 }));
  const partial = M.parseSetup({ applicant: { test: 80 } });
  assert.deepEqual(plain(partial.x), [80].concat(plain(M.PRESETS[0].x.slice(1))));
  assert.deepEqual(plain(partial.settings), plain(M.defaultSettings()));
  assert.equal(partial.margin, 0);
  assert.equal(partial.maxLevers, M.D);
});

test('bad setups are refused with a clear message', function () {
  const bad = [
    [null, /JSON object/], [[1, 2], /JSON object/], [{ tool: 'other' }, /not a setup/],
    [{ applicant: { test: 101 } }, /applicant.test/], [{ applicant: { gap: 2.5 } }, /applicant.gap/],
    [{ applicant: { test: '60' } }, /applicant.test/], [{ rules: { test: { weight: 0 } } }, /weight/],
    [{ rules: { test: { upTo: -1 } } }, /upTo/], [{ rules: { degree: { canChange: 'yes' } } }, /canChange/],
    [{ rules: [] }, /rules/], [{ margin: 0.07 }, /margin/], [{ maxLevers: 0 }, /maxLevers/],
    [{ nextYear: { points: 9 } }, /points/], [{ nextYear: { retrain: 0 } }, /retrain/]
  ];
  bad.forEach(function (b) { assert.throws(function () { M.parseSetup(b[0]); }, b[1]); });
});
