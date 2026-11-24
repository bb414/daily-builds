// Tests for the browser app's model, run in Node.js: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadModel } = require('./load_model.js');

const M = loadModel();
const small = (extra) => Object.assign(M.presetParams('scam_teens'), { people: 60, rounds: 60 }, extra || {});

test('random numbers are reproducible and in range', () => {
  const a = M.makeRng(7), b = M.makeRng(7), c = M.makeRng(8);
  const xs = [], ys = [], zs = [];
  for (let i = 0; i < 1000; i++) { xs.push(a.uniform()); ys.push(b.uniform()); zs.push(c.uniform()); }
  assert.deepEqual(xs, ys);
  assert.notDeepEqual(xs, zs);
  assert.ok(xs.every((x) => x >= 0 && x < 1));
  const mean = xs.reduce((s, x) => s + x, 0) / xs.length;
  assert.ok(Math.abs(mean - 0.5) < 0.05);
});

test('normal draws have mean near 0 and sd near 1', () => {
  const r = M.makeRng(123);
  const xs = Array.from({ length: 20000 }, () => r.normal());
  const mean = xs.reduce((s, x) => s + x, 0) / xs.length;
  const sd = Math.sqrt(xs.reduce((s, x) => s + (x - mean) ** 2, 0) / xs.length);
  assert.ok(Math.abs(mean) < 0.03, 'mean ' + mean);
  assert.ok(Math.abs(sd - 1) < 0.03, 'sd ' + sd);
});

test('sigmoid and logit are inverses and stable at extremes', () => {
  for (const p of [0.01, 0.2, 0.5, 0.8, 0.99]) assert.ok(Math.abs(M.sigmoid(M.logit(p)) - p) < 1e-12);
  assert.equal(M.sigmoid(-1000), 0);
  assert.equal(M.sigmoid(1000), 1);
  assert.ok(isFinite(M.logit(0)) && isFinite(M.logit(1)));
});

test('calibration hits the target accuracy', () => {
  for (const target of [0.55, 0.7, 0.85, 0.99]) {
    for (const sd of [0.2, 1, 2]) {
      const mu = M.calibrateIntercept(target, sd);
      assert.ok(Math.abs(M.expectedAccuracy(mu, sd) - target) < 1e-9);
    }
  }
});

test('normaliseParams fills defaults, clamps and ignores junk', () => {
  const p = M.normaliseParams({ aiAccuracy: 2, humanAccuracy: 'abc', rounds: 33.4, workflow: 'nonsense', showConfidence: 'false', people: null });
  assert.equal(p.aiAccuracy, 0.99);
  assert.equal(p.humanAccuracy, M.DEFAULTS.humanAccuracy);
  assert.equal(p.rounds, 33);
  assert.equal(p.workflow, M.DEFAULTS.workflow);
  assert.equal(p.showConfidence, false);
  assert.equal(p.people, M.DEFAULTS.people);
  assert.equal(M.normaliseParams({ aiAccuracy: true }).aiAccuracy, M.DEFAULTS.aiAccuracy);
  assert.equal(M.normaliseParams({ rounds: Infinity }).rounds, M.DEFAULTS.rounds);
  assert.equal(M.normaliseParams({ rounds: -5 }).rounds, 20);
});

test('every preset is valid and inside the allowed ranges', () => {
  for (const key of Object.keys(M.PRESETS)) {
    const raw = M.PRESETS[key].params;
    const p = M.presetParams(key);
    for (const k of Object.keys(raw)) assert.equal(p[k], raw[k], key + '.' + k + ' was clamped or rejected');
  }
});

test('simulation is deterministic for a given seed and changes with the seed', () => {
  const a = M.simulate(small()), b = M.simulate(small()), c = M.simulate(small({ seed: 43 }));
  assert.equal(a.teamAccuracy, b.teamAccuracy);
  assert.deepEqual(a.series.skill, b.series.skill);
  assert.notEqual(a.teamAccuracy, c.teamAccuracy);
});

test('starting accuracy matches the setting for a large population', () => {
  const r = M.simulate(small({ people: 1000, rounds: 20, humanAccuracy: 0.75, skillSpread: 0.3 }));
  assert.ok(Math.abs(r.skillBefore - 0.75) < 0.01, 'skillBefore ' + r.skillBefore);
  assert.ok(Math.abs(r.aiRealisedAccuracy - r.params.aiAccuracy) < 0.01, 'AI ' + r.aiRealisedAccuracy);
});

test('workflows behave as described', () => {
  const none = M.simulate(small({ workflow: 'none' }));
  assert.equal(none.consultRate, 0);
  assert.equal(none.deferralRate, 0);
  assert.equal(none.teamAccuracy, none.humanAloneAccuracy);
  assert.equal(none.rescueRate, null);
  const hf = M.simulate(small({ workflow: 'human_first' }));
  assert.equal(hf.consultRate, 1);
  assert.equal(hf.deferralRate, 0);
  assert.equal(hf.engagementRate, 1);
  const af = M.simulate(small({ workflow: 'ai_first' }));
  assert.equal(af.consultRate, 1);
  assert.ok(af.deferralRate > 0.2);
  const req = M.simulate(small({ workflow: 'on_request' }));
  assert.ok(req.consultRate > 0 && req.consultRate < 1);
  assert.equal(req.deferralRate, 0);
});

test('nobody learns or forgets without feedback when thinking for themselves', () => {
  const r = M.simulate(small({ workflow: 'human_first', feedbackRate: 0 }));
  assert.ok(Math.abs(r.skillAfter - r.skillBefore) < 1e-12);
  assert.ok(Math.abs(r.trustEnd - r.params.initialTrust) < 1e-12);
});

test('rubber-stamping erodes skill when there is no feedback', () => {
  const r = M.simulate(small({ workflow: 'ai_first', feedbackRate: 0, decayRate: 0.005 }));
  assert.ok(r.skillAfter < r.skillBefore - 0.02);
});

test('a perfect-feedback, high-trust AI-first setup is a crutch; human first is not', () => {
  const base = small({ people: 200, rounds: 200, feedbackRate: 0.3, decayRate: 0.003, initialTrust: 0.8 });
  const af = M.analyse(Object.assign({}, base, { workflow: 'ai_first' }));
  const hf = M.analyse(Object.assign({}, base, { workflow: 'human_first' }));
  assert.equal(af.verdict.key, 'crutch');
  assert.ok(['helper', 'no_lift'].includes(hf.verdict.key));
  assert.ok(af.result.skillAfter < hf.result.skillAfter);
});

test('overconfident AI misleads people more often', () => {
  const calm = M.simulate(small({ workflow: 'human_first', aiOverconfidence: 0, people: 200 }));
  const loud = M.simulate(small({ workflow: 'human_first', aiOverconfidence: 1, people: 200 }));
  assert.ok(loud.misledRate > calm.misledRate);
});

test('classify follows the four quadrants', () => {
  const mk = (wf, team, skill) => ({ params: { workflow: wf }, teamAccuracy: team, skillAfter: skill });
  const ctrl = mk('none', 0.7, 0.7);
  assert.equal(M.classify(mk('ai_first', 0.8, 0.7), ctrl).key, 'helper');
  assert.equal(M.classify(mk('ai_first', 0.8, 0.65), ctrl).key, 'crutch');
  assert.equal(M.classify(mk('ai_first', 0.705, 0.7), ctrl).key, 'no_lift');
  assert.equal(M.classify(mk('ai_first', 0.69, 0.6), ctrl).key, 'liability');
  assert.equal(M.classify(ctrl, ctrl).key, 'baseline');
});

test('moving average', () => {
  assert.deepEqual(Array.from(M.movingAverage([1, 2, 3, 4], 2)), [1, 1.5, 2.5, 3.5]);
  assert.deepEqual(Array.from(M.movingAverage([], 3)), []);
});

test('extreme settings finish quickly and give finite numbers', () => {
  const p = Object.assign({}, M.DEFAULTS);
  for (const spec of M.PARAMS) p[spec.key] = spec.max;
  p.people = 1000; p.rounds = 500;
  const t0 = Date.now();
  const a = M.analyse(p);
  const ms = Date.now() - t0;
  assert.ok(ms < 8000, 'took ' + ms + 'ms');
  for (const k of ['teamAccuracy', 'skillBefore', 'skillAfter', 'trustEnd']) assert.ok(isFinite(a.result[k]), k);
  const q = Object.assign({}, M.DEFAULTS);
  for (const spec of M.PARAMS) q[spec.key] = spec.min;
  const b = M.analyse(q);
  assert.ok(isFinite(b.result.teamAccuracy));
});

test('a silent AI shock leaves everything before it unchanged', () => {
  const base = small({ rounds: 80 });
  const calm = M.simulate(base);
  const shocked = M.simulate(Object.assign({}, base, { driftAt: 40, driftAccuracy: 0.6 }));
  assert.deepEqual(Array.from(shocked.series.team.slice(0, 40)), Array.from(calm.series.team.slice(0, 40)));
  assert.deepEqual(Array.from(shocked.series.trust.slice(0, 41)), Array.from(calm.series.trust.slice(0, 41)));
  assert.equal(calm.shock, null);
  assert.equal(shocked.shock.at, 40);
  assert.ok(shocked.shock.aiAfter < shocked.shock.aiBefore - 0.15);
  assert.ok(shocked.teamAccuracy < calm.teamAccuracy);
});

test('the AI accuracy after the shock matches the setting', () => {
  const r = M.simulate(small({ people: 400, rounds: 100, driftAt: 20, driftAccuracy: 0.62 }));
  assert.ok(Math.abs(r.shock.aiAfter - 0.62) < 0.015, 'aiAfter ' + r.shock.aiAfter);
});

test('a shock at or after the last case is ignored', () => {
  assert.equal(M.simulate(small({ rounds: 60, driftAt: 60 })).shock, null);
  assert.equal(M.simulate(small({ rounds: 60, driftAt: 0 })).shock, null);
});

test('time per case follows the workflow', () => {
  const t = (wf) => M.simulate(small({ workflow: wf })).minutesPerCase;
  assert.ok(Math.abs(t('none') - M.CONSTANTS.timeThink) < 1e-9);
  assert.ok(Math.abs(t('human_first') - M.CONSTANTS.timeThink - M.CONSTANTS.timeCheck) < 1e-9);
  assert.ok(t('ai_first') < t('none'));
  assert.ok(t('on_request') > t('none') && t('on_request') < t('human_first'));
});

test('compareWorkflows shares one comparison group and matches analyse', () => {
  const p = small({ driftAt: 30 });
  const rows = M.compareWorkflows(p);
  assert.deepEqual(rows.map((r) => r.workflow), M.WORKFLOW_KEYS);
  for (const row of rows) {
    assert.equal(row.control, rows[0].result);
    const single = M.analyse(Object.assign({}, p, { workflow: row.workflow }));
    assert.equal(single.verdict.key, row.verdict.key);
    assert.equal(single.result.teamAccuracy, row.result.teamAccuracy);
    assert.equal(single.verdict.shock.gap, row.verdict.shock.gap);
  }
  assert.equal(rows[0].verdict.timeSaved, 0);
});

test('robustness check moves each assumption and keeps the base verdict', () => {
  const p = small({ people: 40, rounds: 40 });
  const sens = M.sensitivity(p);
  const a = M.analyse(p);
  assert.equal(sens.base.verdict, a.verdict.key);
  assert.equal(sens.base.skillGap, a.verdict.skillGap);
  assert.equal(sens.rows.length, M.SENSITIVITY.length);
  for (const row of sens.rows) {
    const spec = M.PARAMS.find((s) => s.key === row.key);
    assert.ok(row.low.value <= row.base && row.high.value >= row.base, row.key);
    assert.ok(row.low.value >= spec.min && row.high.value <= spec.max, row.key);
  }
  const trust = sens.rows.find((r) => r.key === 'initialTrust');
  assert.ok(Math.abs(trust.low.value - 0.45) < 1e-12 && Math.abs(trust.high.value - 0.85) < 1e-12);
  // The shortcut of reusing the comparison group must give the same answer as re-running it.
  const direct = M.analyse(Object.assign({}, p, { initialTrust: trust.high.value }));
  assert.equal(direct.verdict.skillGap, trust.high.skillGap);
});

test('settings marked as control-free really do not affect people working alone', () => {
  const p = small({ workflow: 'none', people: 40, rounds: 50 });
  const base = M.simulate(p);
  for (const key of M.CONTROL_FREE) {
    const spec = M.PARAMS.find((s) => s.key === key);
    for (const v of [spec.min, spec.max]) {
      const r = M.simulate(Object.assign({}, p, { [key]: v }));
      assert.equal(r.teamAccuracy, base.teamAccuracy, key);
      assert.equal(r.skillAfter, base.skillAfter, key);
    }
  }
});

test('explanations describe the result in words', () => {
  const crutch = M.analyse(M.presetParams('scam_teens'));
  const text = M.explain(crutch).join(' ');
  assert.match(text, /without thinking on \d+% of cases/);
  assert.match(text, /right more often than people working alone/);
  const none = M.explain(M.analyse(Object.assign(M.presetParams('scam_teens'), { workflow: 'none' })));
  assert.equal(none.length, 1);
  assert.match(none[0], /Working alone/);
  const shock = M.explain(M.analyse(Object.assign(M.presetParams('scam_teens'), { driftAt: 40, driftAccuracy: 0.55 })));
  assert.ok(shock.some((t) => /After the AI got worse/.test(t)));
  for (const t of text.split(' ')) assert.ok(!t.includes('\u2014'));
});

test('settings survive a round trip through the link and the file', () => {
  const p = Object.assign(M.presetParams('lead_triage'), { driftAt: 70, showConfidence: false, seed: 1234 });
  assert.deepEqual(Object.assign({}, M.decodeParams('#' + M.encodeParams(p))), Object.assign({}, M.normaliseParams(p)));
  const file = JSON.parse(JSON.stringify(M.settingsFile(p)));
  assert.equal(file.app, 'reliance-lab');
  assert.deepEqual(Object.assign({}, M.readSettingsFile(file)), Object.assign({}, M.normaliseParams(p)));
  assert.equal(M.readSettingsFile({ aiAccuracy: 0.7 }).aiAccuracy, 0.7);
});

test('bad links and files are handled safely', () => {
  const p = M.decodeParams('#aiAccuracy=%E0%A4%A&rounds=70&=5&junk&people=abc');
  assert.equal(p.aiAccuracy, M.DEFAULTS.aiAccuracy);
  assert.equal(p.rounds, 70);
  assert.equal(p.people, M.DEFAULTS.people);
  assert.deepEqual(Object.assign({}, M.decodeParams('')), Object.assign({}, M.DEFAULTS));
  assert.throws(() => M.readSettingsFile(null), /does not contain/);
  assert.throws(() => M.readSettingsFile({ hello: 1 }), /does not contain/);
  assert.throws(() => M.readSettingsFile('text'), /does not contain/);
});

test('only plain numbers are accepted from links and files', () => {
  const def = M.DEFAULTS.rounds;
  for (const raw of [' ', '0x40', [100], '1_000', '١٢٠', '1e999', 'Infinity', '12abc', {}, true]) {
    assert.equal(M.normaliseParams({ rounds: raw }).rounds, def, JSON.stringify(raw));
  }
  assert.equal(M.normaliseParams({ rounds: ' 120 ' }).rounds, 120);
  assert.equal(M.normaliseParams({ rounds: '1e2' }).rounds, 100);
  assert.equal(M.normaliseParams({ aiAccuracy: '.9' }).aiAccuracy, 0.9);
  assert.equal(M.normaliseParams({ driftAt: 0.49999999999999994 }).driftAt, 1);
  assert.equal(M.normaliseParams(null).rounds, def);
  assert.equal(M.normaliseParams('rounds=40').rounds, def);
});

test('the stress test can only make the AI worse', () => {
  const p = M.normaliseParams({ aiAccuracy: 0.7, driftAccuracy: 0.95, driftAt: 60 });
  assert.equal(p.driftAccuracy, 0.7);
  assert.equal(M.normaliseParams({ aiAccuracy: 0.9, driftAccuracy: 0.6 }).driftAccuracy, 0.6);
  const r = M.simulate(Object.assign(small(), { aiAccuracy: 0.7, driftAccuracy: 0.95, driftAt: 30 }));
  assert.ok(r.shock.aiAfter < r.shock.aiBefore + 0.03);
});

test('explanations do not claim learning or fading that is switched off', () => {
  const noLearn = M.explain(M.analyse(small({ workflow: 'none', feedbackRate: 0.25, learningRate: 0 })));
  assert.match(noLearn[0], /Learning from practice is set to zero/);
  const noFeedback = M.explain(M.analyse(small({ workflow: 'none', feedbackRate: 0 })));
  assert.match(noFeedback[0], /Without feedback/);
  const noDecay = M.explain(M.analyse(small({ workflow: 'ai_first', decayRate: 0 }))).join(' ');
  assert.match(noDecay, /give no practice\./);
  assert.doesNotMatch(noDecay, /skill fades/);
});

test('the step-by-step robustness check matches the one-shot version', () => {
  const p = small({ people: 50, rounds: 30 });
  const ctx = M.sensitivityStart(p);
  for (const item of M.SENSITIVITY) {
    ctx.summary.rows.push({ key: item.key, base: ctx.p[item.key], low: M.sensitivityPoint(ctx, item, 'low'), high: M.sensitivityPoint(ctx, item, 'high') });
  }
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.summary)), JSON.parse(JSON.stringify(M.sensitivity(p))));
});
