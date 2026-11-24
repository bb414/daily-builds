// Tests for the browser app's model, run with: node --test
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadModel } = require('./load_model.cjs');

const M = loadModel();

// A tiny dataset with known sales, for checking the methods by hand.
function toyData(series, weeks) {
  return {
    weeks: weeks,
    testStart: weeks - 52,
    skus: [{ id: 'a', name: 'A' }],
    stores: [{ id: 's', name: 'S' }],
    sales: [[series]],
    promo: [new Array(weeks).fill(0)],
    events: [],
    synthetic: false
  };
}

test('settings are filled in and kept in range', () => {
  const d = M.normaliseSettings({});
  assert.equal(d.seed, 7);
  assert.equal(d.horizon, 1);
  const s = M.normaliseSettings({ holidays: 9, noise: -1, horizon: 2.7, seed: -5, optimism: 'lots', buffer: NaN, insight: true });
  assert.equal(s.holidays, 2);
  assert.equal(s.noise, 0);
  assert.equal(s.horizon, 2);
  assert.equal(s.seed, 0);
  assert.equal(s.optimism, 0.12);
  assert.equal(s.buffer, 0.1);
  assert.equal(s.insight, 0.2);
  assert.deepEqual(Object.keys(M.normaliseSettings(null)), Object.keys(M.SETTINGS));
});

test('the synthetic chain has the intended shape and calendar', () => {
  const d = M.simulate({});
  assert.equal(d.weeks, 156);
  assert.equal(d.testStart, 104);
  assert.equal(d.sales.length, 12);
  assert.equal(d.sales[0].length, 8);
  assert.equal(d.sales[0][0].length, 156);
  d.sales.forEach((rows) => rows.forEach((y) => y.forEach((v) => assert.ok(Number.isInteger(v) && v >= 0))));
  // Chinese New Year moves: its peak week is week 5, 3 and 6 of years 1 to 3.
  const peak = d.events.find((e) => e.id === 'cny-1');
  assert.deepEqual(peak.flags.map((f, t) => (f ? t : -1)).filter((t) => t >= 0), [4, 52 + 2, 104 + 5]);
  assert.deepEqual(M.simulate({}), d, 'the same seed gives the same chain');
  assert.notDeepEqual(M.simulate({ seed: 8 }).sales, d.sales);
  // Festival products sell far more around their festival than in an ordinary week.
  const tarts = d.sales[0].reduce((acc, y) => acc.map((v, t) => v + y[t]), new Array(156).fill(0));
  const cnyWeek = 104 + 6 - 1;
  assert.ok(tarts[cnyWeek] > 2.5 * tarts[104 + 30], 'pineapple tarts peak before Chinese New Year');
  const flat = M.simulate({ holidays: 0, promoLift: 0, noise: 0, growth: 0 });
  assert.ok(Math.abs(flat.sales[9][0][110] - 28 * 1.6) <= 2, 'with no effects, sales sit near the base level');
});

test('naive, moving average and seasonal naive do what they say', () => {
  const y = Array.from({ length: 160 }, (_, t) => t);
  const d = toyData(y, 160);
  const fc = M.forecastAll(d, { horizon: 2, overrideRate: 0 }).forecasts;
  assert.equal(fc.naive[0][0][120], 118);
  assert.equal(fc.average[0][0][120], (111 + 118) / 2);
  assert.equal(fc.seasonal[0][0][120], 68);
  assert.equal(fc.naive[0][0][79], null, 'no forecasts before the 28 weeks used to choose methods');
  assert.equal(fc.naive[0][0][80], 78);
});

test('seasonal smoothing settles on a steady series', () => {
  const y = new Array(156).fill(20);
  const fc = M.smoothingSeries(y, 1, 104);
  fc.slice(104).forEach((v) => assert.ok(Math.abs(v - 20) < 1e-9));
  // A repeating seasonal pattern is learned from the first year.
  const pattern = Array.from({ length: 156 }, (_, t) => (t % 52 === 10 ? 60 : 20));
  const f2 = M.smoothingSeries(pattern, 1, 104);
  assert.ok(f2[114] > 30 && f2[114] > 1.5 * f2[120], 'the peak week is forecast high');
  assert.ok(Math.abs(f2[120] - 20) < 2);
});

test('the ridge solver solves a known system', () => {
  // x' x = [[4, 2], [2, 3]] (upper triangle stored), x' y = [10, 9]; penalty 2 on the second term.
  const beta = M.solveRidge([[4, 2], [0, 3]], [10, 9]);
  // (4 b0 + 2 b1 = 10, 2 b0 + 5 b1 = 9) gives b0 = 2, b1 = 1.
  assert.ok(Math.abs(beta[0] - 2) < 1e-12);
  assert.ok(Math.abs(beta[1] - 1) < 1e-12);
  const singular = M.solveRidge([[0, 0], [0, 0]], [0, 0]);
  assert.deepEqual(singular, [0, 0]);
});

test('no method peeks at the future', () => {
  for (const h of [1, 3]) {
    const d = M.simulate({ seed: 11 });
    const base = M.forecastAll(d, { seed: 11, horizon: h });
    const t = 130;
    const changed = JSON.parse(JSON.stringify(d));
    changed.sales.forEach((rows) => rows.forEach((y) => { for (let k = t - h + 1; k < d.weeks; k++) { y[k] = y[k] * 3 + 7; } }));
    const after = M.forecastAll(changed, { seed: 11, horizon: h });
    ['naive', 'average', 'seasonal', 'smoothing', 'ai'].forEach((id) => {
      for (let p = 0; p < 12; p++) {
        for (let s = 0; s < 8; s++) {
          assert.equal(after.forecasts[id][p][s][t], base.forecasts[id][p][s][t], id + ' changed when only later sales changed (h=' + h + ')');
        }
      }
    });
  }
});

test('planners only touch the forecasts they override', () => {
  const d = M.simulate({});
  const none = M.forecastAll(d, { overrideRate: 0 });
  assert.deepEqual(none.forecasts.planner, none.forecasts.ai);
  const all = M.forecastAll(d, { overrideRate: 1, optimism: 0, insight: 1 });
  // With full insight, an override lands on the actual sales plus the planner's own noise.
  const r = M.evaluate(d, all);
  assert.ok(r.methods[5].wape < 0.6 * r.methods[4].wape);
  assert.equal(r.overrides.up.n + r.overrides.down.n, 12 * 8 * 52);
  // Changing the planners never changes the sales or the other methods.
  const other = M.forecastAll(d, { overrideRate: 0.7, optimism: 0.2 });
  assert.deepEqual(other.forecasts.ai, none.forecasts.ai);
});

test('scores add up', () => {
  const run = M.run({});
  const r = run.results;
  assert.equal(r.methods.length, 6);
  r.methods.forEach((m) => assert.equal(m.n, 12 * 8 * 52));
  const total = ['festival', 'promo', 'ordinary'].reduce((a, k) => a + r.byWeekType[k].naive.n, 0);
  assert.equal(total, 12 * 8 * 52);
  assert.ok(Math.abs(r.methods[3].fvaNaive - (r.methods[0].wape - r.methods[3].wape)) < 1e-15);
  assert.ok(Math.abs(r.methods[4].fvaPrevious - (r.methods[3].wape - r.methods[4].wape)) < 1e-15);
  assert.equal(r.methods[0].fvaPrevious, null);
  r.methods.forEach((m) => assert.ok(m.fillRate > 0 && m.fillRate <= 1));
  const actual = r.methods[0].actual;
  r.methods.forEach((m) => assert.equal(m.actual, actual));
  assert.equal(r.deployOn, r.bySku.filter((s) => s.verdict === 'ai').length);
  // Under the defaults the AI is clearly better overall and on festival weeks.
  assert.ok(r.methods[4].wape < r.methods[3].wape - 0.05);
  assert.ok(r.byWeekType.festival.ai.wape < r.byWeekType.festival.smoothing.wape - 0.05);
  // Upward overrides hurt and downward ones help, under the default planner settings.
  assert.ok(r.overrides.up.improved < 0);
  assert.ok(r.overrides.down.improved > 0);
  assert.equal(r.overrides.up.n + r.overrides.down.n, r.overrides.small.n + r.overrides.large.n);
});

test('without festivals or promotions the AI is rarely worth it', () => {
  const r = M.run({ holidays: 0, promoLift: 0 }).results;
  assert.ok(r.deployOn <= 2, 'deployed on ' + r.deployOn);
  const full = M.run({}).results;
  assert.ok(full.deployOn >= 8, 'deployed on ' + full.deployOn);
});

test('a longer horizon makes every method worse but keeps the order', () => {
  const one = M.run({ horizon: 1 }).results.methods;
  const four = M.run({ horizon: 4 }).results.methods;
  ['naive', 'average', 'smoothing', 'ai'].forEach((id) => {
    const a = one.find((m) => m.id === id), b = four.find((m) => m.id === id);
    assert.ok(b.wape >= a.wape - 0.005, id + ' should not improve much with a longer horizon');
  });
  assert.equal(four.find((m) => m.id === 'seasonal').wape, one.find((m) => m.id === 'seasonal').wape);
  assert.ok(four[4].wape < four[3].wape);
});

test('each product\'s method is chosen only from the weeks before the test year', () => {
  const d = M.simulate({});
  const fc = M.forecastAll(d, {});
  const r = M.evaluate(d, fc);
  assert.equal(r.validationWeeks, 28);
  assert.ok(fc.forecasts.ai[0][0][76] !== null && fc.forecasts.ai[0][0][75] === null);
  // Changing the test year's sales cannot change the choices.
  const changed = JSON.parse(JSON.stringify(d));
  changed.sales.forEach((rows) => rows.forEach((y) => { for (let t = 104; t < 156; t++) { y[t] = 0; } }));
  const r2 = M.evaluate(changed, M.forecastAll(changed, {}));
  assert.deepEqual(r2.bySku.map((x) => x.chosen), r.bySku.map((x) => x.chosen));
  // The mix scores exactly what the chosen methods score on the test year.
  let abs = 0, act = 0;
  d.sales.forEach((rows, p) => rows.forEach((y, s) => {
    for (let t = 104; t < 156; t++) { abs += Math.abs(y[t] - fc.forecasts[r.bySku[p].chosen][p][s][t]); act += y[t]; }
  }));
  assert.ok(Math.abs(r.mix.wape - abs / act) < 1e-12);
  assert.equal(r.chosenAi, r.bySku.filter((x) => x.chosen === 'ai').length);
  // The window before the test year has Deepavali and Christmas but no Chinese New
  // Year, so a choice made there undersells the AI on festival products.
  assert.ok(r.chosenAi < r.deployOn);
  assert.ok(r.mix.wape > r.methods[4].wape);
});

test('keeping only downward overrides', () => {
  const r = M.run({}).results;
  assert.ok(r.downOnly.wape < r.methods[5].wape, 'dropping upward overrides helps');
  assert.ok(r.downOnly.wape < r.methods[4].wape, 'downward overrides alone beat the AI');
  const none = M.run({ overrideRate: 0 }).results;
  assert.equal(none.downOnly.wape, none.methods[4].wape);
});
