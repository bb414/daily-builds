// Tests for the app's model, run with: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { loadModel } = require('./load_model');
const M = loadModel();
const D = M.DATA;

function ex(id) { return D.examples.find(function (e) { return e.id === id; }); }

test('probability mapping is monotone and inverts', function () {
  let prev = -1;
  for (let s = 0; s <= 5.0001; s += 0.25) {
    const p = M.toProb(s);
    assert.ok(p > prev || s === 0);
    prev = p;
    assert.ok(Math.abs(M.fromProb(p) - s) < 1e-12, 'round trip at ' + s);
  }
  assert.strictEqual(M.toProb(1), 0.025);
  assert.strictEqual(M.toProb(5), 0.9);
  assert.strictEqual(M.fromProb(0), 0);
  assert.strictEqual(M.toProb(-3), 0);
  assert.strictEqual(M.toProb(9), 0.9);
});

test('inherent risk adds answers and caps at 5', function () {
  const r = M.inherentRisk(M.normaliseInput({ answers: ex('shortlister').answers }));
  const fair = r.find(function (x) { return x.id === 'fairness'; });
  // 1 + 0.5 (signs off) + 1.5 (ML) + 0.5 (personal) + 0.5 (outputs only) + 0.5 (retrained)
  assert.strictEqual(fair.L, 4.5);
  // 1 + 2.5 (decides access) + 1 (public) + 0 (limited roll-out)
  assert.strictEqual(fair.I, 4.5);
  assert.strictEqual(fair.score, 20.25);
  // full scale adds 1 more, capped at 5; a pilot takes 1 off
  const atScale = M.inherentRisk(M.normaliseInput({ answers: Object.assign({}, ex('shortlister').answers, { stage: 'scale' }) }));
  assert.strictEqual(atScale.find(function (x) { return x.id === 'fairness'; }).I, 5);
  const pilot = M.inherentRisk(M.normaliseInput({ answers: Object.assign({}, ex('shortlister').answers, { stage: 'pilot' }) }));
  assert.strictEqual(pilot.find(function (x) { return x.id === 'fairness'; }).I, 3.5);
  assert.strictEqual(fair.band, 'Very high');
  const low = M.inherentRisk(M.normaliseInput({ answers: { stakes: 'advisory', autonomy: 'suggests', model: 'rules', data: 'none', affected: 'staff', source: 'inhouse', change: 'fixed', stage: 'pilot' } }));
  // a pilot's minus one cannot take impact below 1
  assert.deepStrictEqual(low.map(function (x) { return x.score; }), [1.5, 1, 1.5, 1, 1]);
});

test('overrides replace likelihood and impact', function () {
  const r = M.inherentRisk(M.normaliseInput({ answers: ex('policy').answers, overrides: { L: { safety: 5 }, I: { safety: '2' } } }));
  assert.strictEqual(r[0].L, 5);
  assert.strictEqual(r[0].I, 2);
  assert.strictEqual(r[0].score, 10);
  assert.deepStrictEqual(r[0].overridden, { L: true, I: true });
});

test('access and model type switch techniques off with a reason', function () {
  const inp = M.normaliseInput({ answers: Object.assign({}, ex('shortlister').answers, { source: 'docs', model: 'genai' }) });
  const s = M.techniqueStatus(inp);
  const get = function (id) { return s.find(function (x) { return x.id === id; }); };
  assert.strictEqual(get('formal').available, false);
  assert.strictEqual(get('biasInternal').available, false);
  assert.match(get('biasInternal').reason, /test access/);
  assert.strictEqual(get('conformity').factor, 0.4);
  assert.strictEqual(get('supplier').available, true);
  const inhouse = M.techniqueStatus(M.normaliseInput({ answers: ex('maintenance').answers }));
  assert.strictEqual(inhouse.find(function (x) { return x.id === 'supplier'; }).available, false);
  assert.strictEqual(inhouse.find(function (x) { return x.id === 'dpia'; }).available, false);
});

test('ruling out a prerequisite removes what depends on it', function () {
  const r = M.analyse({ answers: ex('fraud').answers, exclude: ['docs'] });
  const conf = r.techniques.find(function (x) { return x.id === 'conformity'; });
  assert.strictEqual(conf.available, false);
  assert.match(conf.reason, /ruled out/);
  assert.ok(r.usable.indexOf('conformity') < 0);
});

test('a must pulls in its prerequisites and appears in every plan', function () {
  const r = M.analyse({ answers: ex('fraud').answers, must: ['aims'] });
  for (const p of [r.cheapest, r.inBudget, r.best]) {
    if (!p) continue;
    for (const id of ['aims', 'risk', 'aia']) assert.ok(p.ids.indexOf(id) >= 0, id + ' in plan');
  }
});

test('the DPIA is required with personal data unless switched off', function () {
  const on = M.analyse({ answers: ex('policy').answers });
  assert.ok(on.cheapest.ids.indexOf('dpia') >= 0);
  assert.strictEqual(on.techniques.find(function (x) { return x.id === 'dpia'; }).required, true);
  const off = M.analyse({ answers: ex('policy').answers, legalMust: false });
  assert.strictEqual(off.techniques.find(function (x) { return x.id === 'dpia'; }).required, false);
  const ruled = M.analyse({ answers: ex('policy').answers, exclude: ['dpia'] });
  assert.ok(ruled.cheapest.ids.indexOf('dpia') >= 0);
  assert.ok(ruled.notes.some(function (n) { return /treated as required/.test(n); }));
});

test('the cheapest plan meets appetite and nothing cheaper does', function () {
  for (const e of D.examples) {
    const input = { answers: e.answers };
    const r = M.analyse(input);
    if (!r.cheapest) continue;
    assert.ok(r.cheapest.meets);
    assert.ok(r.cheapest.weeks <= r.input.weeks);
    // brute force over every subset of the usable techniques
    const n = r.usable.length;
    for (let m = 0; m < (1 << n); m++) {
      const ids = r.usable.filter(function (_, i) { return (m >> i) & 1; });
      const cost = ids.reduce(function (a, id) { return a + D.techniques.find(function (t) { return t.id === id; }).cost; }, 0);
      if (cost >= r.cheapest.cost) continue;
      const p = M.evaluatePlan(input, ids);
      if (p.cost >= r.cheapest.cost) continue; // prerequisites added made it dearer
      assert.ok(!(p.meets && p.fitsDeadline), e.id + ': cheaper plan ' + ids.join(',') + ' meets appetite');
    }
  }
});

test('every technique in a cheapest plan is needed', function () {
  for (const e of D.examples) {
    const r = M.analyse({ answers: e.answers });
    if (!r.cheapest) continue;
    for (const m of r.cheapest.marginal) assert.ok(m.locked || !m.meetsWithout, e.id + ' ' + m.id);
  }
});

test('the frontier falls as cost rises and contains the key plans', function () {
  const r = M.analyse({ answers: ex('billing').answers });
  for (let i = 1; i < r.frontier.length; i++) {
    assert.ok(r.frontier[i].cost > r.frontier[i - 1].cost);
    assert.ok(r.frontier[i].worst < r.frontier[i - 1].worst);
  }
  const last = r.frontier[r.frontier.length - 1];
  assert.strictEqual(last.worst, r.best.worst);
  assert.ok(r.frontier.some(function (p) { return p.cost === r.cheapest.cost && p.worst === r.cheapest.worst; }));
});

test('budget plan respects the budget and minimises the worst principle', function () {
  const r = M.analyse({ answers: ex('shortlister').answers, budget: 60 });
  assert.ok(r.inBudget.cost <= 60);
  for (const p of r.frontier) if (p.cost <= 60) assert.ok(p.worst >= r.inBudget.worst);
  assert.ok(!r.cheapest.withinBudget);
});

test('appetite out of reach gives no cheapest plan but a best plan', function () {
  const r = M.analyse({ answers: ex('shortlister').answers, appetite: 2 });
  assert.strictEqual(r.cheapest, null);
  assert.ok(r.best.worst > 2);
});

test('a deadline that is too short leaves no plan and says why', function () {
  const r = M.analyse({ answers: ex('shortlister').answers, weeks: 1 });
  assert.strictEqual(r.best, null);
  assert.strictEqual(r.cheapest, null);
  assert.ok(r.notes.some(function (n) { return /No plan fits in 1 week:/.test(n); }));
  assert.strictEqual(r.frontier.length, 0);
});

test('the schedule runs stages in order and waits for prerequisites', function () {
  const s = M.schedule(['risk', 'aia', 'aims', 'docs', 'conformity', 'monitor']);
  const row = function (id) { return s.rows.find(function (r) { return r.id === id; }); };
  assert.strictEqual(row('aims').start, 4); // after the 4-week impact assessment
  assert.strictEqual(row('aims').end, 18);
  assert.strictEqual(row('conformity').start, 18);
  assert.strictEqual(s.goLive, 26);
  assert.strictEqual(row('monitor').start, 26);
  assert.strictEqual(M.schedule([]).goLive, 0);
});

test('a hand-built plan adds prerequisites and required techniques', function () {
  const p = M.evaluatePlan({ answers: ex('shortlister').answers }, ['conformity']);
  assert.deepStrictEqual(p.ids.slice().sort(), ['conformity', 'docs', 'dpia'].sort());
  assert.ok(p.notes.some(function (n) { return /needs model and data documentation/.test(n); }));
  const q = M.evaluatePlan({ answers: ex('shortlister').answers }, ['formal']);
  assert.ok(q.notes.some(function (n) { return /cannot be used here/.test(n); }));
});

test('odd input is repaired and reported', function () {
  const inp = M.normaliseInput({ answers: { stakes: 'banana' }, appetite: 'lots', budget: -5, weeks: '12', must: 'risk; nope', exclude: ['risk'] });
  assert.strictEqual(inp.answers.stakes, D.defaults.answers.stakes);
  assert.strictEqual(inp.appetite, D.defaults.appetite);
  assert.strictEqual(inp.budget, 0);
  assert.strictEqual(inp.weeks, 12);
  assert.deepStrictEqual(inp.must, ['risk']);
  assert.deepStrictEqual(inp.exclude, []);
  assert.strictEqual(inp.notes.length, 5);
  assert.strictEqual(M.normaliseInput({ budget: '0x10' }).budget, D.defaults.budget);
  assert.strictEqual(M.normaliseInput(null).appetite, D.defaults.appetite);
});

test('the catalogue is consistent', function () {
  const ids = D.techniques.map(function (t) { return t.id; });
  assert.ok(ids.length <= 16, 'at most 16 techniques so every subset can be searched');
  for (const t of D.techniques) {
    for (const p of M.PRINCIPLES) assert.ok(t.coverage[p] >= 0 && t.coverage[p] < 1, t.id + ' ' + p);
    for (const r of t.requires || []) assert.ok(ids.indexOf(r) >= 0 && ids.indexOf(r) < ids.indexOf(t.id), t.id + ' requires ' + r + ' listed earlier');
    assert.ok(Number.isInteger(t.cost) && t.cost > 0);
  }
  for (const e of D.examples) for (const q of D.questions) assert.ok(q.options.some(function (o) { return o.id === e.answers[q.id]; }));
});

test('techniques already done cost nothing, take no time and stay in the plan', function () {
  const r = M.analyse({ answers: ex('fraud').answers, done: ['risk', 'aia'] });
  for (const id of ['risk', 'aia']) assert.ok(r.cheapest.ids.indexOf(id) >= 0);
  const fresh = M.evaluatePlan({ answers: ex('fraud').answers }, r.cheapest.ids);
  assert.strictEqual(r.cheapest.cost, fresh.cost - 4 - 9);
  assert.strictEqual(M.schedule(['risk', 'aia', 'aims'], ['risk', 'aia']).goLive, 14);
  const both = M.normaliseInput({ done: ['docs'], exclude: ['docs'] });
  assert.deepStrictEqual(both.exclude, []);
  assert.ok(both.notes.some(function (n) { return /kept as done/.test(n); }));
});

test('the pilot-to-scale ladder builds on each stage', function () {
  for (const e of D.examples) {
    const L = M.ladder({ answers: e.answers });
    const steps = L.stepwise.steps;
    assert.deepStrictEqual(steps.map(function (s) { return s.stage; }), ['pilot', 'rollout', 'scale']);
    const seen = [];
    let total = 0;
    for (const s of steps) {
      for (const id of s.added) { assert.ok(seen.indexOf(id) < 0, 'added once'); seen.push(id); }
      for (const id of seen) assert.ok(s.ids.indexOf(id) >= 0, 'earlier work kept');
      total += s.cost;
    }
    assert.strictEqual(total, L.stepwise.total);
    // planned for scale: ends at the cheapest full-scale plan, and never costs more
    const atScale = M.analyse({ answers: Object.assign({}, e.answers, { stage: 'scale' }) });
    assert.strictEqual(L.planned.total, atScale.cheapest.cost);
    assert.deepStrictEqual(L.planned.target, atScale.cheapest.ids);
    assert.ok(L.premium >= 0);
    // the stepwise route's final plan meets appetite at full scale
    assert.ok(M.evaluatePlan({ answers: Object.assign({}, e.answers, { stage: 'scale' }) }, L.stepwise.final).meets);
  }
  const grant = M.ladder({ answers: ex('grant').answers });
  assert.strictEqual(grant.premium, 5);
  assert.deepStrictEqual(grant.extra, ['docs', 'compliance']);
});
