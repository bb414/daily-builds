// Tests for the browser app's model, run from the repository root with: node --test
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const M = require('./load_model.js');

const DAY = M.DAY;

function single(extra) {
  return M.normalise(Object.assign({
    name: 'One desk', arrivalsPerDay: 40, slaDays: 5, measureDays: 400, warmupDays: 20,
    steps: [{ name: 'Desk', kind: 'team', staff: 1, minutes: 9, cv: 0.5 }],
    ai: { step: 0, saving: 0, adoption: 1, checkMinutes: 0, errorRate: 0 }
  }, extra || {}));
}

function avg(fn, seeds) {
  let s = 0;
  seeds.forEach((x) => { s += fn(x); });
  return s / seeds.length;
}

test('presets are valid and every case finishes', () => {
  for (const key of Object.keys(M.PRESETS)) {
    const cfg = M.presetConfig(key);
    assert.deepEqual(M.validate(cfg), [], key);
    const r = M.compare(cfg, 42);
    assert.ok(r.complete, key + ' should finish every case');
    assert.ok(r.base.done > 1000, key);
  }
});

test('the same seed gives the same answer, a different seed a different one', () => {
  const cfg = M.presetConfig('claims');
  const a = M.compare(cfg, 5), b = M.compare(cfg, 5), c = M.compare(cfg, 6);
  assert.equal(a.total, b.total);
  assert.equal(a.ai.leadMean, b.ai.leadMean);
  assert.notEqual(a.ai.leadMean, c.ai.leadMean);
});

test('where-the-minutes-went parts add up exactly to the change in end-to-end time', () => {
  for (const key of Object.keys(M.PRESETS)) {
    for (const seed of [1, 42, 99]) {
      const r = M.compare(M.presetConfig(key), seed);
      const sum = r.parts.reduce((s, p) => s + p.value, 0);
      assert.ok(Math.abs(sum - r.total) < 1e-6, key + ' ' + seed + ': ' + sum + ' vs ' + r.total);
      // Lead time is hands-on time plus waiting, case by case.
      assert.ok(Math.abs(r.ai.touchTotal + r.ai.waitTotal - r.ai.leadMean) < 1e-6);
      assert.ok(Math.abs(r.base.touchTotal + r.base.waitTotal - r.base.leadMean) < 1e-6);
    }
  }
});

test('an AI that changes nothing leaves the process exactly as it was', () => {
  const cfg = M.presetConfig('loans');
  cfg.ai = { step: 2, saving: 0, adoption: 1, checkMinutes: 0, errorRate: 0, catchRate: 0.9 };
  const r = M.compare(cfg, 3);
  assert.equal(r.total, 0);
  assert.equal(r.ai.leadMean, r.base.leadMean);
  assert.deepEqual(r.ai.steps.map((s) => s.wait), r.base.steps.map((s) => s.wait));
});

test('the baseline run ignores the AI settings entirely', () => {
  const a = M.presetConfig('complaints');
  const b = M.presetConfig('complaints');
  b.ai.saving = 0.9; b.ai.errorRate = 0.4; b.ai.checkMinutes = 30;
  assert.equal(M.compare(a, 8).base.leadMean, M.compare(b, 8).base.leadMean);
});

test('a single desk matches the Pollaczek-Khinchine formula for the mean wait', () => {
  for (const cv of [0.5, 1]) {
    const cfg = single({ steps: [{ name: 'Desk', kind: 'team', staff: 1, minutes: 9, cv: cv }] });
    const rho = 40 * 9 / DAY; // 0.8
    const expected = rho / (1 - rho) * 9 * (1 + cv * cv) / 2;
    const got = avg((s) => M.simulate(cfg, s, { noAi: true }).steps[0].wait, [1, 2, 3, 4]);
    assert.ok(Math.abs(got - expected) / expected < 0.1, 'cv ' + cv + ': ' + got + ' vs ' + expected);
  }
});

test('utilisation and throughput match the offered load', () => {
  const cfg = single();
  const r = M.simulate(cfg, 11, { noAi: true });
  assert.ok(Math.abs(r.steps[0].utilisation - 0.8) < 0.03, String(r.steps[0].utilisation));
  assert.ok(Math.abs(r.throughputPerDay - 40) < 1.5, String(r.throughputPerDay));
  assert.ok(Math.abs(r.steps[0].touch - 9) < 0.3);
});

test('a daily batch at the start of the day makes cases wait half a day on average', () => {
  const cfg = single({ steps: [{ name: 'Run', kind: 'batch', batchDays: [0, 1, 2, 3, 4], capacity: 500, minutes: 0.1, cv: 0 }] });
  const r = M.simulate(cfg, 4, { noAi: true });
  assert.ok(Math.abs(r.steps[0].wait - DAY / 2) / (DAY / 2) < 0.05, String(r.steps[0].wait));
});

test('a wait outside the team adds its share times its length', () => {
  const cfg = single({ steps: [{ name: 'Wait', kind: 'delay', share: 0.5, minutes: 900, cv: 0.8 }], ai: { step: -1 } });
  const r = M.simulate(cfg, 4, { noAi: true });
  assert.ok(Math.abs(r.steps[0].wait - 450) / 450 < 0.05, String(r.steps[0].wait));
  assert.equal(r.steps[0].touch, 0);
});

test('more people at a busy step cut the wait there', () => {
  const cfg = M.presetConfig('claims');
  const more = M.presetConfig('claims');
  more.steps[1].staff = 6;
  assert.ok(M.simulate(more, 1, { noAi: true }).steps[1].wait < M.simulate(cfg, 1, { noAi: true }).steps[1].wait);
});

test('AI errors are caught by a later check and sent back, or else reach customers', () => {
  const cfg = M.presetConfig('claims');
  cfg.ai.errorRate = 0.2; cfg.ai.catchRate = 1;
  let r = M.compare(cfg, 2);
  assert.ok(r.ai.aiSendBacksPer100 > 10);
  assert.equal(r.ai.escapedPer100, 0);
  assert.equal(r.base.aiSendBacksPer100, 0);
  cfg.ai.catchRate = 0;
  r = M.compare(cfg, 2);
  assert.equal(r.ai.aiSendBacksPer100, 0);
  assert.ok(r.ai.escapedPer100 > 10);
  // With no check after the AI step, nothing is caught.
  const late = M.presetConfig('claims');
  late.ai.step = 5; late.ai.errorRate = 0.2;
  r = M.compare(late, 2);
  assert.equal(r.ai.aiSendBacksPer100, 0);
  assert.ok(r.ai.escapedPer100 > 10);
});

test('a step with too much work never finishes every case and says so', () => {
  const cfg = M.presetConfig('claims');
  cfg.steps[1].staff = 3;
  const r = M.compare(cfg, 1);
  assert.equal(r.complete, false);
  assert.ok(r.base.open > 0);
});

test('validation explains bad settings in plain English', () => {
  const cfg = M.presetConfig('claims');
  cfg.steps[2].reworkTo = 4;
  cfg.ai.step = 3;
  cfg.arrivalsPerDay = NaN;
  const errs = M.validate(cfg);
  assert.ok(errs.some((e) => /earlier step/.test(e)));
  assert.ok(errs.some((e) => /cannot sit on a wait/.test(e)));
  assert.ok(errs.some((e) => /Cases per day/.test(e)));
  assert.deepEqual(M.validate(M.normalise({ steps: [] })).slice(0, 1), ['Add at least one step.']);
});

test('normalise fills in defaults and cleans batch days', () => {
  const c = M.normalise({ steps: [{ kind: 'batch', batchDays: [3, 3, 9, 1] }, { kind: 'odd' }] });
  assert.deepEqual(c.steps[0].batchDays, [1, 3]);
  assert.equal(c.steps[1].kind, 'team');
  assert.equal(c.steps[1].name, 'Step 2');
  assert.equal(c.ai.step, -1);
  assert.equal(c.measureDays, 120);
});

test('durations are formatted in minutes, hours or working days', () => {
  assert.equal(M.fmtDuration(12.4), '12 min');
  assert.equal(M.fmtDuration(-90), '-1.5 h');
  assert.equal(M.fmtDuration(900), '2.0 days');
});

test('the options appraisal includes the current AI with the same result as the comparison', () => {
  const cfg = M.presetConfig('claims');
  const cmp = M.compare(cfg, 42);
  const rows = M.placements(cfg, 42, cmp.base);
  const current = rows.filter((o) => o.current);
  assert.equal(current.length, 1);
  assert.equal(current[0].total, cmp.total);
  // One AI option per work step and one staffing option per team step.
  assert.equal(rows.filter((o) => o.kind === 'ai').length, 5);
  assert.equal(rows.filter((o) => o.kind === 'staff').length, 4);
  for (let i = 1; i < rows.length; i++) assert.ok(rows[i - 1].total <= rows[i].total);
});

test('moving the AI scales its checking time with the step', () => {
  const cfg = M.presetConfig('claims');
  const base = M.simulate(cfg, 3, { noAi: true });
  const opt = M.optionList(cfg).find((o) => o.kind === 'ai' && o.step === 2);
  const row = M.evaluateOption(cfg, 3, opt, base);
  const moved = M.normalise(cfg);
  moved.ai.step = 2; moved.ai.checkMinutes = 5 * 15 / 50;
  assert.equal(row.total, M.simulate(moved, 3).leadMean - base.leadMean);
});

test('an extra person never slows the process', () => {
  for (const key of Object.keys(M.PRESETS)) {
    const rows = M.placements(M.presetConfig(key), 9);
    rows.filter((o) => o.kind === 'staff').forEach((o) => assert.ok(o.total <= 1e-9, key + ' ' + o.label + ' ' + o.total));
  }
});

test('banking the pilot\'s business case as fewer people', () => {
  const cfg = M.presetConfig('claims');
  const cmp = M.compare(cfg, 42);
  const b = M.bankSavings(cfg, 42, cmp);
  assert.ok(Math.abs(b.claimedPeople - 20 * 40 / M.DAY) < 1e-9);
  assert.equal(b.cut, 2);
  assert.ok(b.freedPeople > 0.5 && b.freedPeople < b.claimedPeople);
  assert.equal(b.stable, false);
  assert.ok(b.vsBase > 0);
  const one = M.bankSavings(cfg, 42, cmp, 1);
  assert.equal(one.cut, 1);
  assert.ok(one.leadMean < b.leadMean);
  const none = M.bankSavings(cfg, 42, cmp, 0);
  assert.equal(none.possible, false);
  const tooMany = M.bankSavings(cfg, 42, cmp, 99);
  assert.equal(tooMany.cut, 4);
  const batch = M.normalise(M.presetConfig('loans'));
  batch.ai.step = 3;
  assert.equal(M.bankSavings(batch, 1).possible, false);
});

test('an overloaded team is flagged even when every case eventually finishes', () => {
  const cfg = M.presetConfig('claims');
  cfg.steps[1].staff = 3;
  cfg.drainDays = 400;
  const r = M.simulate(cfg, 1, { noAi: true });
  assert.deepEqual(r.overloaded, [1]);
  assert.equal(r.stable, false);
  assert.ok(M.simulate(M.presetConfig('claims'), 1).stable);
});

test('robustness re-runs the comparison with consecutive seeds', () => {
  const cfg = M.presetConfig('claims');
  const rb = M.robustness(cfg, 42, 4);
  assert.deepEqual(rb.runs.map((x) => x.seed), [42, 43, 44, 45]);
  assert.equal(rb.runs[0].total, M.compare(cfg, 42).total);
  assert.ok(rb.min <= rb.mean && rb.mean <= rb.max);
  assert.ok(rb.helped + rb.hurt <= rb.n);
  assert.equal(rb.helped, 4);
});

test('the tornado nudges one assumption at a time and sorts by swing', () => {
  const cfg = M.presetConfig('loans');
  const lo = M.variantConfig(cfg, 'adoption', -1), hi = M.variantConfig(cfg, 'errorRate', 1);
  assert.ok(Math.abs(lo.ai.adoption - 0.65) < 1e-12);
  assert.equal(lo.ai.saving, cfg.ai.saving);
  assert.equal(hi.ai.errorRate, 0.1);
  assert.equal(M.variantConfig(cfg, 'saving', 1).ai.saving, 0.55);
  const full = M.normalise(cfg); full.ai.adoption = 0.95;
  assert.equal(M.variantConfig(full, 'adoption', 1).ai.adoption, 1);
  const rows = M.sensitivity(cfg, 42);
  assert.equal(rows.length, M.SENSITIVITY.length);
  for (let i = 1; i < rows.length; i++) assert.ok(rows[i - 1].swing >= rows[i].swing);
  // More errors caught at the committee cost a full committee cycle each.
  const err = rows.find((x) => x.key === 'errorRate');
  assert.ok(err.high > err.low);
});

test('Erlang C and the Allen-Cunneen wait', () => {
  assert.ok(Math.abs(M.erlangC(1, 0.7) - 0.7) < 1e-12);
  assert.ok(Math.abs(M.erlangC(2, 1) - 1 / 3) < 1e-12);
  assert.equal(M.erlangC(3, 3), 1);
  assert.ok(Math.abs(M.waitMultiple(1, 1, 0.8) - 4) < 1e-9);
  assert.equal(M.waitMultiple(4, 0.5, 1), Infinity);
  // The approximation is close to the simulation for a team of five.
  const cfg = M.normalise({ arrivalsPerDay: 45, measureDays: 400, steps: [{ name: 'Team', kind: 'team', staff: 5, minutes: 45, cv: 1 }], ai: { step: -1 } });
  let wait = 0, util = 0;
  [1, 2, 3].forEach((s) => { const r = M.simulate(cfg, s, { noAi: true }); wait += r.steps[0].wait / 3; util += r.steps[0].utilisation / 3; });
  const theory = M.waitMultiple(5, 1, 0.9) * 45;
  assert.ok(Math.abs(util - 0.9) < 0.02, String(util));
  assert.ok(Math.abs(wait - theory) / theory < 0.2, wait + ' vs ' + theory);
});
