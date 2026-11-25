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
