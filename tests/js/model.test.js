'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadModel } = require('./load_model');

const M = loadModel();

test('eight pots and three people', () => {
  assert.equal(M.CATS.length, 8);
  assert.deepEqual(M.DATA.personas.map((p) => p.id), ['student', 'graduate', 'sixthformer']);
});

test('every habit points at a known merchant and pot', () => {
  for (const p of M.DATA.personas) {
    for (const h of p.monthly.concat(p.habits)) {
      assert.ok(M.MERCHANTS[h.m], h.m);
      assert.ok(M.CATS.includes(h.cat), h.cat);
      if (h.m === 'TRANSFER') assert.ok(h.payee && h.memos.length > 0);
    }
    for (const h of p.habits) assert.equal(h.days.length, 7);
  }
});

test('mulberry32 is deterministic and matches known values', () => {
  const r = M.mulberry32(42);
  assert.deepEqual([r(), r(), r()], [0.6011037519201636, 0.44829055899754167, 0.8524657934904099]);
});

test('arithmetic ln and exp match the built-ins closely', () => {
  for (const x of [1e-9, 0.001, 0.5, 1, 1.5, 2, 3.7, 1234.5, 98765]) {
    assert.ok(Math.abs(M.ln(x) - Math.log(x)) <= 1e-13 * Math.max(1, Math.abs(Math.log(x))), String(x));
  }
  for (const x of [-60, -12.5, -1.3, -0.2, 0, 0.7, 5]) {
    assert.ok(Math.abs(M.exp(x) - Math.exp(x)) <= 1e-13 * Math.exp(x), String(x));
  }
  assert.equal(M.exp(0), 1);
  assert.equal(M.exp(-800), 0);
  assert.throws(() => M.ln(0));
  assert.throws(() => M.ln(-1));
});

test('calendar starts on a Monday and crosses months and years', () => {
  assert.equal(M.dateOf(0).iso, '2026-09-07');
  assert.equal(M.dateOf(24).iso, '2026-10-01');
  assert.equal(M.dateOf(116).iso, '2027-01-01');
  assert.equal(M.dateOf(175).iso, '2027-03-01');
});

test('statements are reproducible and well formed', () => {
  const a = M.generateStatement('student', 13, 3);
  const b = M.generateStatement('student', 13, 3);
  const c = M.generateStatement('student', 13, 4);
  assert.deepEqual(a, b);
  assert.notDeepEqual(a.tx.map((t) => t.desc), c.tx.map((t) => t.desc));
  assert.ok(a.tx.length > 150);
  let lastDay = -1;
  for (const t of a.tx) {
    assert.ok(Number.isInteger(t.pennies) && t.pennies >= 50);
    assert.ok(t.cat >= 0 && t.cat < 8);
    assert.ok(t.day >= lastDay);
    lastDay = t.day;
  }
  // monthly rent lands on the first of each month
  const rent = a.tx.filter((t) => t.merchant === 'HOMESHARE');
  assert.deepEqual(rent.map((t) => t.date), ['2026-10-01', '2026-11-01', '2026-12-01']);
  assert.ok(rent.every((t) => t.pennies === 62000));
});

test('weeks are clamped to 1..52', () => {
  assert.equal(M.generateStatement('graduate', 0, 1).weeks, 1);
  assert.equal(M.generateStatement('graduate', 99, 1).weeks, 52);
  assert.throws(() => M.generateStatement('nobody', 13, 1));
});

test('featurise reads channel, merchant key, words, amount band and day type', () => {
  const card = M.featurise('TAP*BEAN THERE CAFE BRIGHTON', 360, 2);
  assert.equal(card.key, 'BEAN THERE');
  assert.deepEqual(card.feats, ['c:CARD', 'm:BEAN THERE', 'w:BEAN', 'w:THERE', 'w:CAFE', 'a:1', 'd:wd']);
  const tr = M.featurise('TO L CHEN REF PIZZA', 1100, 5);
  assert.equal(tr.key, 'L CHEN');
  assert.deepEqual(tr.feats, ['c:TRANSFER', 'm:L CHEN', 'w:CHEN', 'w:PIZZA', 'a:2', 'd:we']);
  const dd = M.featurise('DD GLOWGRID ENERGY 12345678', 6000, 0);
  assert.deepEqual(dd.feats, ['c:DD', 'm:GLOWGRID ENERGY', 'w:GLOWGRID', 'w:ENERGY', 'a:4', 'd:wd']);
  assert.equal(M.featurise('1234 5678', 100, 0).key, '(blank)');
  assert.equal(M.amountBand(299), 0);
  assert.equal(M.amountBand(300), 1);
  assert.equal(M.amountBand(12000), 5);
});

test('metrics count each misplaced pound once', () => {
  const st = { tx: [
    { pennies: 1000, cat: 0 }, { pennies: 500, cat: 1 }, { pennies: 200, cat: 2 }
  ] };
  const perfect = M.metrics(st, [0, 1, 2]);
  assert.equal(perfect.misP, 0);
  assert.equal(perfect.accuracy, 1);
  const off = M.metrics(st, [1, 1, 2]);
  assert.equal(off.misP, 1000);
  assert.equal(off.misPct, 1000 * 100 / 1700);
  assert.equal(off.correct, 2);
  const swap = M.metrics(st, [1, 0, 2]);
  // a 10 pound and a 5 pound payment swap pots: each pot is only 5 pounds out, so the budget gap is 5 pounds
  assert.equal(swap.misP, 500);
  assert.equal(swap.correct, 1);
  assert.equal(M.metrics({ tx: [] }, []).misPct, 0);
});

test('one correction re-files the same merchant elsewhere in the statement', () => {
  const st = M.generateStatement('graduate', 13, 1);
  const s = new M.Session(st, {});
  // rent to the old flatmate, then (after the move) to a new name: the word RENT carries the lesson across
  const rent = st.tx.map((t, i) => i).filter((i) => / REF RENT$/.test(st.tx[i].desc));
  assert.equal(rent.length, 3);
  assert.ok(rent.every((i) => s.reported(i) !== 3)); // the generic model calls rent to a person a transfer
  s.correct(rent[0], 3);
  assert.ok(rent.every((i) => s.reported(i) === 3));
  assert.equal(s.checks, 1);
});

test('incremental learning matches a full recount', () => {
  const st = M.generateStatement('sixthformer', 6, 2);
  const s = new M.Session(st, { weight: 7 });
  for (const t of [0, 5, 9, 20, 33]) s.correct(t, (st.tx[t].cat + 1) % 8);
  const m = s.model;
  for (let t = 0; t < st.tx.length; t++) {
    for (let c = 0; c < 8; c++) assert.equal(m.featSum[t][c], m.sumFor(t, c));
  }
  const probs = m.probs[0].reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(probs - 1) < 1e-12);
});

test('strategies pick what they say they pick', () => {
  const st = M.generateStatement('student', 8, 5);
  const s = new M.Session(st, {});
  const rng = M.mulberry32(1);
  const big = M.chooseNext('biggest', s, rng);
  assert.equal(st.tx[big].pennies, Math.max(...st.tx.map((t) => t.pennies)));
  const unsure = M.chooseNext('unsure', s, rng);
  assert.equal(s.model.conf[unsure], Math.min(...s.model.conf));
  const common = M.chooseNext('common', s, rng);
  const counts = {};
  s.model.keys.forEach((k) => { counts[k] = (counts[k] || 0) + 1; });
  assert.equal(counts[s.model.keys[common]], Math.max(...Object.values(counts)));
  const risk = M.chooseNext('risk', s, rng);
  assert.ok(risk >= 0 && s.labels[risk] < 0);
  assert.throws(() => M.chooseNext('psychic', s, rng));
});

test('checking every payment empties the wrong pot when nobody slips', () => {
  const st = M.generateStatement('sixthformer', 2, 9);
  for (const strat of M.STRATEGIES) {
    const r = M.runCurve(st, strat.id, { checks: st.tx.length + 5 });
    assert.equal(r.points.length, st.tx.length + 1);
    assert.equal(r.points[r.points.length - 1].misPct, 0);
    assert.equal(new Set(r.picks).size, st.tx.length);
  }
});

test('slips leave some money in the wrong pot', () => {
  const st = M.generateStatement('student', 4, 1);
  const r = M.runCurve(st, 'random', { checks: st.tx.length, slip: 0.5 });
  assert.ok(r.points[r.points.length - 1].misPct > 0);
});

test('compareStrategies reports checks to target consistently', () => {
  const st = M.generateStatement('graduate', 13, 1);
  const res = M.compareStrategies(st, { checks: 40, target: 5 });
  assert.equal(res.length, 5);
  for (const r of res) {
    assert.equal(r.points.length, 41);
    if (r.toTarget !== null) {
      assert.ok(r.points[r.toTarget].misPct <= 5);
      for (let k = 0; k < r.toTarget; k++) assert.ok(r.points[k].misPct > 5);
    } else {
      assert.ok(r.points.every((p) => p.misPct > 5));
    }
  }
  assert.equal(M.checksToTarget([{ misPct: 9 }, { misPct: 4 }], 5), 1);
  assert.equal(M.checksToTarget([{ misPct: 9 }], 5), null);
});

test('habit changes start and stop on time', () => {
  const st = M.generateStatement('graduate', 13, 1);
  const oldRent = st.tx.filter((t) => t.desc === 'TO J OKAFOR REF RENT').map((t) => t.date);
  const newRent = st.tx.filter((t) => t.desc === 'TO R SINGH REF RENT').map((t) => t.date);
  assert.deepEqual(oldRent, ['2026-10-01']);
  assert.deepEqual(newRent, ['2026-11-01', '2026-12-01']);
  const alex = M.generateStatement('sixthformer', 13, 1);
  const lessons = alex.tx.filter((t) => t.desc.startsWith('TO STEERWELL'));
  assert.ok(lessons.length >= 7 && lessons.every((t) => t.day >= 35 && t.wd === 6));
});

test('weekly mode: no checks means day-one guesses every month', () => {
  const st = M.generateStatement('student', 13, 2);
  const none = M.runWeekly(st, 'none', { perWeek: 5 });
  assert.equal(none.checks, 0);
  const fresh = new M.Session(st, {});
  for (const m of none.months) {
    const idx = st.tx.map((t, i) => i).filter((i) => st.tx[i].month === m.month);
    assert.equal(m.misPct, M.metricsFor(st, fresh.reportedAll(), idx).misPct);
  }
  assert.deepEqual(none.months.map((m) => [m.month, m.partial]),
    [['2026-09', true], ['2026-10', false], ['2026-11', false], ['2026-12', true]]);
  assert.deepEqual([none.months[0].from, none.months[0].to, none.months[3].from, none.months[3].to], [7, 30, 1, 6]);
});

test('weekly mode respects the weekly allowance and only asks about that week', () => {
  const st = M.generateStatement('sixthformer', 8, 3);
  for (const s of M.STRATEGIES) {
    const r = M.runWeekly(st, s.id, { perWeek: 2 });
    assert.equal(r.checks, 16);
    const last = r.months[r.months.length - 1];
    assert.equal(last.checks, 16);
  }
  const all = M.runWeekly(st, 'risk', { perWeek: 1000 });
  assert.equal(all.checks, st.tx.length);
  // with an allowance only for this week, the first Sunday can only check week-one payments
  const s = new M.Session(st, {});
  const t = M.chooseNext('biggest', s, M.mulberry32(1), (i) => st.tx[i].day <= 6);
  assert.ok(st.tx[t].day <= 6);
  assert.equal(M.chooseNext('biggest', s, M.mulberry32(1), () => false), -1);
});
