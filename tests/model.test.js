// Tests for the browser app's model. Run with: node --test
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadModel } = require('./model_bridge.js');

const M = loadModel();
// The model runs in its own VM context, so compare plain copies of its objects.
const plain = function (x) { return JSON.parse(JSON.stringify(x)); };
const near = function (a, b, tol, msg) { assert.ok(Math.abs(a - b) <= (tol || 1e-9), (msg || '') + ' ' + a + ' vs ' + b); };

function randomConfigs(n, seed) {
  let x = seed;
  const rnd = function () { x = (x * 1103515245 + 12345) % 2147483648; return x / 2147483648; };
  const out = [];
  for (let k = 0; k < n; k++) {
    out.push({
      stock: 1 + Math.floor(rnd() * 80), days: 1 + Math.floor(rnd() * 9), price: 1 + rnd() * 20,
      unitCost: rnd() * 5, wasteCost: -1 + rnd() * 4, demand: 0.5 + rnd() * 20, elasticity: rnd() * 4,
      freshness: Math.floor(rnd() * 41), startDay: Math.floor(rnd() * 7), pattern: ['flat', 'highStreet', 'office'][k % 3], monotone: k % 4 !== 0
    });
  }
  return out;
}

test('settings are filled in and kept in range', function () {
  const d = plain(M.normalise({}));
  assert.equal(d.stock, 60); assert.equal(d.days, 7); assert.equal(d.pattern, 'flat'); assert.equal(d.monotone, true);
  const c = plain(M.normalise({ stock: 9999, days: 0, price: 'abc', elasticity: -3, startDay: 6.6, pattern: 'toString', monotone: false }));
  assert.equal(c.stock, 300); assert.equal(c.days, 1); assert.equal(c.price, 12); assert.equal(c.elasticity, 0);
  assert.equal(c.startDay, 6); assert.equal(c.pattern, 'flat'); assert.equal(c.monotone, false);
  assert.equal(plain(M.normalise('text')).stock, 60);
});

test('weekly patterns average one', function () {
  Object.values(M.WEEK_PATTERNS).forEach(function (w) { near(w.reduce(function (a, b) { return a + b; }, 0) / 7, 1, 1e-12); });
});

test('Poisson windows hold all but a negligible share of the probability', function () {
  [0.05, 0.7, 3, 12, 45, 140].forEach(function (lam) {
    const w = M.poissonWindow(lam, 300);
    near(w.p.reduce(function (a, b) { return a + b; }, 0), 1, 1e-12, 'lambda ' + lam);
  });
  const huge = M.poissonWindow(5000, 300);
  assert.ok(huge.lo > huge.hi, 'demand far above stock leaves an empty window: everything sells');
  assert.deepEqual(plain(M.poissonWindow(0, 10)), { lo: 0, hi: 0, p: [1] });
});

test('one unit, one day: matches the formula', function () {
  const cfg = { stock: 1, days: 1, price: 10, wasteCost: 2, demand: 0.7, elasticity: 0 };
  const sol = M.solve(cfg);
  near(sol.value, 10 * (1 - Math.exp(-0.7)) - 2 * Math.exp(-0.7), 1e-12);
  assert.equal(sol.policy[0][0][1], 0, 'no reason to discount when discounts do not lift demand');
});

test('two units, one day, with a discount worth taking', function () {
  // Full price: demand 0.5; 50% off with elasticity 2 lifts demand fourfold to 2.
  const cfg = { stock: 2, days: 1, price: 10, wasteCost: 0, demand: 0.5, elasticity: 2 };
  const ev = function (lam, price) {
    const p0 = Math.exp(-lam), p1 = lam * Math.exp(-lam);
    return price * (p1 * 1 + (1 - p0 - p1) * 2);
  };
  const sol = M.solve(cfg);
  near(sol.Q[0][0][2], ev(0.5, 10), 1e-12);
  near(sol.Q[0][4][2], ev(2, 5), 1e-12);
  near(sol.value, Math.max.apply(null, [0, 1, 2, 3, 4].map(function (j) { return sol.Q[0][j][2]; })), 1e-12);
});

test('the best plan is worth exactly what evaluating it says, and beats every rule', function () {
  randomConfigs(40, 7).forEach(function (cfg) {
    const cmp = M.comparePolicies(cfg, { pct: 20, daysLeft: 1 });
    const best = cmp.rows[0].result;
    near(best.profit, cmp.solution.value, 1e-7, JSON.stringify(cfg));
    cmp.rows.slice(1).forEach(function (r) { assert.ok(best.profit >= r.result.profit - 1e-7, r.name + ' ' + JSON.stringify(cfg)); });
    near(best.sold + best.waste, cmp.solution.cfg.stock, 1e-7, 'every unit is sold or left over');
    near(best.leftover.reduce(function (a, b) { return a + b; }, 0), 1, 1e-9);
  });
});

test('prices only go down unless rises are allowed', function () {
  randomConfigs(20, 3).forEach(function (cfg) {
    cfg.monotone = true;
    const sol = M.solve(cfg);
    sol.policy.forEach(function (byStep) {
      byStep.forEach(function (row, i) { row.forEach(function (j) { assert.ok(j >= i); }); });
    });
  });
  const free = M.solve({ stock: 40, days: 6, demand: 5, elasticity: 2, pattern: 'highStreet', monotone: false });
  const tied = M.solve({ stock: 40, days: 6, demand: 5, elasticity: 2, pattern: 'highStreet', monotone: true });
  assert.ok(free.value >= tied.value - 1e-9, 'freedom to raise prices can only help');
});

test('no discounts when they do not lift demand, and none when demand swamps the stock', function () {
  const flat = M.solve({ stock: 50, days: 5, demand: 4, elasticity: 0, wasteCost: 1 });
  flat.policy.forEach(function (byStep) { byStep[0].forEach(function (j) { assert.equal(j, 0); }); });
  const rush = M.comparePolicies({ stock: 20, days: 3, demand: 100, elasticity: 2, price: 5 });
  near(rush.solution.value, 100, 1e-9);
  assert.equal(rush.solution.policy[0][0][20], 0);
});

test('a policy that discounts can only be followed from the right step', function () {
  const sol = M.solve(M.PRESETS.truffles);
  const res = M.evaluate(sol.cfg, function () { return 0; });   // tries to go back to full price
  const never = M.evaluate(sol.cfg, M.POLICIES.never(sol));
  near(res.profit, never.profit, 1e-12);
});

test('rules switch on at the right day', function () {
  const sol = M.solve({ days: 5 });
  const rule = M.POLICIES.rule(sol, 30, 2);
  assert.deepEqual([0, 1, 2, 3, 4].map(function (t) { return rule(t, 10, 0); }), [0, 0, 0, 3, 3]);
  assert.equal(rule(4, 10, 4), 4, 'never back up the ladder');
  assert.equal(M.POLICIES.lastDay(sol)(4, 10, 0), 4);
  assert.equal(M.POLICIES.rule(sol, 25, 2)(4, 10, 0), 0, 'a discount not on the ladder means no discount');
});

test('freshness lowers demand by a fixed share each day', function () {
  const cfg = M.normalise({ demand: 10, freshness: 20, pattern: 'flat' });
  near(M.demandRate(cfg, 0, 0), 10, 1e-12);
  near(M.demandRate(cfg, 3, 0), 10 * Math.pow(0.8, 3), 1e-12);
  near(M.demandRate(cfg, 3, 4), 10 * Math.pow(0.8, 3) * Math.pow(0.5, -cfg.elasticity), 1e-12);
});

test('outcome distributions are consistent with the expectations', function () {
  const res = M.comparePolicies(M.PRESETS.truffles).rows[0].result;
  res.days.forEach(function (d) {
    near(d.stockDist.reduce(function (a, b) { return a + b; }, 0), 1, 1e-9);
    near(d.stepProb.reduce(function (a, b) { return a + b; }, 0), 1, 1e-9);
    assert.ok(d.p10 <= d.p50 && d.p50 <= d.p90);
    const mean = d.stockDist.reduce(function (a, p, s) { return a + p * s; }, 0);
    near(mean, d.stockStart, 1e-9);
  });
  assert.equal(res.days[0].p50, 60, 'everything is still in stock on day one');
  assert.ok(res.leftoverP10 <= res.leftoverP50 && res.leftoverP50 <= res.leftoverP90);
  assert.equal(M.quantile([0.05, 0.05, 0.4, 0.5], 0.1), 1);
  assert.equal(M.quantile([0.05, 0.05, 0.4, 0.5], 0.9), 3);
});

test('the shelf card is scored exactly as printed', function () {
  const odd = { stock: 43, days: 2, price: 4.16, wasteCost: 4.2, demand: 9.6, elasticity: 2.7, freshness: 37, startDay: 6, pattern: 'office' };
  Object.values(M.PRESETS).concat(randomConfigs(15, 11), [odd]).forEach(function (cfg) {
    const sol = M.solve(cfg);
    const card = M.shelfCard(sol);
    const follow = M.POLICIES.card(sol);
    assert.equal(card.rows.length, sol.cfg.days);
    card.rows.forEach(function (r) {
      for (let s = 1; s <= sol.cfg.stock; s++) {
        let j = 0;
        r.from.forEach(function (start, step) { if (start !== null && s >= start) j = step; });
        assert.equal(follow(r.day, s, 0), j, 'the scored card reads the printed thresholds');
        assert.ok(sol.policy[r.day][0][s] >= 1 ? r.from[1] !== null && r.from[1] <= s : true);
      }
    });
    assert.ok(card.gap >= -1e-7, 'the card can never beat the full plan');
    near(card.profit, M.evaluate(sol.cfg, follow).profit, 1e-9);
  });
  const oddCard = M.shelfCard(M.solve(odd));
  assert.ok(oddCard.gap > 0.05, 'a plan that is not monotone in stock loses a little on the card');
});

test('robustness: perfect knowledge is never beaten, and the planned case scores 100%', function () {
  const cells = M.robustness(M.PRESETS.truffles);
  assert.equal(cells.length, 15);
  cells.forEach(function (c) { assert.ok(c.planned <= c.ideal + 1e-7, JSON.stringify(c)); });
  const asPlanned = cells.filter(function (c) { return c.demandFactor === 1 && c.elasticityFactor === 1; })[0];
  near(asPlanned.planned, asPlanned.ideal, 1e-7);
  near(asPlanned.ideal, M.solve(M.PRESETS.truffles).value, 1e-9);
});

test('the robustness check is not capped by the input limits', function () {
  const cfg = { stock: 300, days: 1, price: 5, demand: 100, elasticity: 1, wasteCost: 0.5 };
  const top = M.robustness(cfg).filter(function (c) { return c.demandFactor === 1.5 && c.elasticityFactor === 1; })[0];
  const capped = M.solve(Object.assign({}, cfg, { demand: 150 })).value;   // the input limit would cap demand at 100
  assert.ok(top.ideal > capped, 'true demand of 150 is modelled as 150, not 100');
});
