// Tests for the browser app's model. Run with: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadModel } = require('./load_model');

const M = loadModel();
const cfg = (over) => Object.assign({}, M.DEFAULT_CONFIG, over || {});

test('random numbers are reproducible and in [0, 1)', () => {
  const a = M.mulberry32(42), b = M.mulberry32(42);
  for (let i = 0; i < 1000; i++) {
    const x = a();
    assert.equal(x, b());
    assert.ok(x >= 0 && x < 1);
  }
  assert.notEqual(M.mixSeed(1, 2), M.mixSeed(2, 1));
});

test('the approximate normal has mean near 0 and variance near 1', () => {
  const r = M.mulberry32(7);
  let s = 0, s2 = 0;
  const n = 20000;
  for (let i = 0; i < n; i++) { const z = M.normal(r); s += z; s2 += z * z; }
  assert.ok(Math.abs(s / n) < 0.03);
  assert.ok(Math.abs(s2 / n - 1) < 0.05);
});

test('seasonal interpolation wraps round the year', () => {
  const t = M.PRESETS.windy.demandSeason;
  const first = M.seasonal(t, 0), last = M.seasonal(t, 363);
  assert.ok(Math.abs(first - last) < 0.005, 'the two ends of the year meet');
  // Mid-month days sit on the table values.
  assert.ok(Math.abs(M.seasonal([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], 15) - 1) < 0.02);
  for (let d = 0; d < 364; d++) {
    const v = M.seasonal(t, d);
    assert.ok(v >= Math.min(...t) && v <= Math.max(...t));
  }
});

test('dispatch follows the merit order', () => {
  const p = M.PRESETS.windy;
  // Plenty of wind: renewables are curtailed and the margin is spare clean power.
  const windy = M.dispatch(p, 25, 30, 0);
  assert.equal(windy.code, 0);
  assert.equal(windy.marg, 0);
  assert.ok(windy.curtail > 0);
  assert.equal(windy.thermal[0], p.minThermalGW);
  // Calm and dark: gas meets demand and peakers join when combined cycle is full.
  const calm = M.dispatch(p, 30, 0, 0);
  assert.equal(calm.code, 1);
  assert.ok(calm.marg > p.blocks[0].lo && calm.marg < p.blocks[0].hi);
  const peak = M.dispatch(p, 42, 0, 0);
  assert.equal(peak.code, 2);
  // Beyond every plant: emergency supply.
  const short = M.dispatch(p, 60, 0, 0);
  assert.equal(short.code, p.blocks.length + 1);
  assert.ok(short.shortfall > 0);
  // Energy balances in every case.
  [windy, calm, peak, short].forEach((o, i) => {
    const D = [25, 30, 42, 60][i];
    const gen = o.nuclear + o.wind + o.solar + o.thermal.reduce((a, b) => a + b, 0) + o.shortfall;
    assert.ok(Math.abs(gen - D) < 1e-9);
  });
});

test('on the coal grid, coal is the marginal plant at low demand', () => {
  const p = M.PRESETS.coal;
  const night = M.dispatch(p, 20, 3, 0);
  assert.equal(p.blocks[night.code - 1].key, 'coal');
  const day = M.dispatch(p, 34, 3, 3);
  assert.equal(p.blocks[day.code - 1].key, 'ccgt');
  assert.ok(night.marg > day.marg, 'extra demand at night is dirtier');
});

test('a perfect forecast reproduces the actual grid', () => {
  const c = cfg({ forecastError: 0 });
  const g = M.simulateGrid(c);
  const f = M.forecast(g, c, 1000, 72);
  for (let k = 0; k < 72; k++) {
    assert.equal(f.avg[k], g.avg[1000 + k]);
    assert.equal(f.marg[k], g.marg[1000 + k]);
  }
});

test('with a perfect forecast the marginal scheduler matches hindsight', () => {
  const r = M.run(cfg({ forecastError: 0 }));
  assert.equal(r.policies.marg.real, r.policies.oracle.real);
});

test('hindsight is never beaten on real emissions, job by job', () => {
  for (const preset of Object.keys(M.PRESETS)) {
    const r = M.run(cfg({ preset }));
    const o = r.policies.oracle;
    for (const k of ['now', 'night', 'avg', 'marg']) {
      r.policies[k].perJob.forEach((J, i) => assert.ok(o.perJob[i].real <= J.real + 1e-9, preset + ' ' + k + ' job ' + i));
    }
  }
});

test('no flexibility means every scheduler runs on release', () => {
  const r = M.run(cfg({ slack: 0 }));
  for (const k of ['night', 'avg', 'marg', 'oracle']) {
    assert.equal(r.policies[k].real, r.policies.now.real);
    assert.equal(r.policies[k].reportedSavedT, 0);
    assert.equal(r.policies[k].verdict, 'nothing');
  }
});

test('every placement stays inside its window and uses the right number of hours', () => {
  const c = cfg({ slack: 1.5 });
  const r = M.run(c);
  const inst = M.buildInstances(c.jobs, c.slack);
  for (const k of Object.keys(r.policies)) {
    const pl = r.policies[k].placements;
    assert.equal(pl.length, inst.length);
    pl.forEach((p, i) => {
      assert.equal(p.offsets.length, inst[i].hours);
      assert.ok(p.offsets[0] >= 0 && p.offsets[p.offsets.length - 1] < inst[i].window);
      for (let j = 1; j < p.offsets.length; j++) {
        assert.ok(p.offsets[j] > p.offsets[j - 1]);
        if (!inst[i].pausable || k === 'now' || k === 'night') assert.equal(p.offsets[j], p.offsets[j - 1] + 1);
      }
    });
  }
});

test('energy is the same under every scheduler', () => {
  const r = M.run(cfg());
  for (const k of Object.keys(r.policies)) assert.equal(r.policies[k].mwh, r.policies.now.mwh);
});

test('the three example grids tell three different stories', () => {
  const v = (preset) => M.run(cfg({ preset })).policies.avg.verdict;
  assert.equal(v('windy'), 'understates');
  assert.equal(v('sunny'), 'overstates');
  assert.equal(v('coal'), 'backfires');
});

test('choosing hours: cheapest hours for pausable jobs, cheapest block otherwise', () => {
  const vals = [5, 1, 4, 1, 3, 9];
  assert.deepEqual(M.chooseHours(vals, 2, 6, true), [1, 3]);
  assert.deepEqual(M.chooseHours(vals, 2, 6, false), [3, 4]);
  assert.deepEqual(M.chooseHours(vals, 3, 3, false), [0, 1, 2]);
  // Ties go to the earliest hour.
  assert.deepEqual(M.chooseHours([2, 2, 2, 2], 2, 4, false), [0, 1]);
  assert.deepEqual(M.chooseHours([2, 2, 2, 2], 2, 4, true), [0, 1]);
});

test('the midnight rule starts at midnight only if the job still fits', () => {
  assert.deepEqual(M.midnightHours({ release: 20, hours: 3, window: 10 }), [4, 5, 6]);
  assert.deepEqual(M.midnightHours({ release: 20, hours: 8, window: 10 }), [0, 1, 2, 3, 4, 5, 6, 7]);
});

test('job validation catches bad input', () => {
  assert.deepEqual(M.validateJobs(M.DEFAULT_JOBS), []);
  assert.ok(M.validateJobs([]).length > 0);
  const bad = Object.assign({}, M.DEFAULT_JOBS[1], { hours: 10, window: 5 });
  assert.ok(M.validateJobs([bad])[0].includes('window'));
  assert.ok(M.validateJobs([Object.assign({}, bad, { window: 12, mw: NaN })])[0].includes('power'));
  assert.ok(M.validateJobs([Object.assign({}, M.DEFAULT_JOBS[1], { releaseHour: 24 })]).length === 1);
  assert.ok(M.validateJobs([Object.assign({}, M.DEFAULT_JOBS[1], { everyDays: 0 })]).length === 1);
});

test('instances never run past the end of the year', () => {
  const inst = M.buildInstances(M.DEFAULT_JOBS, 3);
  inst.forEach((it) => assert.ok(it.release + it.window <= M.HOURS));
});

test('the spare-power chaser uses forecast surplus hours, otherwise runs now', () => {
  // values are forecast marginal intensities; 0 means spare clean power.
  assert.deepEqual(M.spareHours([400, 380, 0, 0, 390, 0], 2, 6, true), [2, 3]);
  assert.deepEqual(M.spareHours([400, 380, 0, 390, 390, 390], 3, 6, true), [0, 1, 2]);
  assert.deepEqual(M.spareHours([400, 380, 390, 390], 2, 4, true), [0, 1]);
  assert.deepEqual(M.spareHours([400, 0, 390, 0, 0, 390], 2, 6, false), [3, 4]);
  assert.deepEqual(M.spareHours([400, 380, 390, 390], 2, 4, false), [0, 1]);
});

test('the spare-power chaser waits much less than the forecast schedulers', () => {
  const r = M.run(cfg());
  assert.ok(r.policies.spare.meanDelay < r.policies.avg.meanDelay / 2);
  assert.ok(r.policies.spare.realSavedT > 0);
});

test('curves reuse the grid for settings that do not change it, and match full runs', () => {
  const c = cfg({ preset: 'sunny' });
  const pts = M.curve(c, 'slack', [0, 1, 2]);
  assert.deepEqual(pts.map((p) => p.value), [0, 1, 2]);
  const full = M.run(Object.assign({}, c, { slack: 2 }));
  for (const k of Object.keys(full.policies)) {
    assert.equal(pts[2].policies[k].realSavedT, full.policies[k].realSavedT);
    assert.equal(pts[2].policies[k].reportedSavedT, full.policies[k].reportedSavedT);
  }
  assert.equal(pts[0].policies.oracle.realSavedT, 0);
  const wind = M.curve(c, 'windScale', [0.5, 2]);
  assert.ok(wind[1].curtailShare > wind[0].curtailShare, 'more wind, more spare power');
});

test('a worst-case custom job (long, daily, in one block) still runs quickly', () => {
  const heavy = { name: 'Heavy', mw: 5, hours: 336, everyDays: 1, firstDay: 0, releaseHour: 0, window: 672, pausable: false };
  assert.deepEqual(M.validateJobs([heavy]), []);
  const t0 = Date.now();
  const r = M.run(cfg({ jobs: [heavy, Object.assign({}, heavy, { pausable: true })] }));
  assert.ok(Date.now() - t0 < 5000, 'took ' + (Date.now() - t0) + ' ms');
  assert.ok(r.instances > 0);
});

test('contiguous choice with running totals matches a brute-force search', () => {
  const r = M.mulberry32(99);
  for (let trial = 0; trial < 200; trial++) {
    const win = 2 + Math.floor(r() * 40), hours = 1 + Math.floor(r() * (win - 1));
    const vals = [];
    for (let k = 0; k < win; k++) vals.push(Math.floor(r() * 50));   // whole numbers: exact sums, real ties
    let best = 0, bestSum = Infinity;
    for (let s = 0; s + hours <= win; s++) {
      let sum = 0;
      for (let k = s; k < s + hours; k++) sum += vals[k];
      if (sum < bestSum) { best = s; bestSum = sum; }
    }
    assert.equal(M.chooseHours(vals, hours, win, false)[0], best);
  }
});

test('validation survives things that are not jobs', () => {
  const errs = M.validateJobs([null, 3, M.DEFAULT_JOBS[0]]);
  assert.equal(errs.length, 2);
  assert.ok(errs[0].includes('not a job'));
});

test('dispatch copes with demand below the must-run plant', () => {
  const p = M.PRESETS.windy;
  const o = M.dispatch(p, 2, 10, 0);
  assert.ok(o.nuclear >= 0 && o.thermal[0] >= 0);
  const gen = o.nuclear + o.wind + o.solar + o.thermal.reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(gen - 2) < 1e-9);
});

test('jobs CSV: round trip, quoting and strict numbers', () => {
  const jobs = M.DEFAULT_JOBS.concat([{ name: 'Has, comma "and" quotes', mw: 0.5, hours: 2, everyDays: 3, firstDay: 1, releaseHour: 4, window: 9, pausable: false }]);
  const text = M.formatJobsCsv(jobs);
  assert.deepEqual(M.parseJobsCsv(text).jobs, jobs);
  assert.deepEqual(M.parseJobsCsv(text.replace(/\n/g, '\r\n')).jobs, jobs);
  const head = 'name,mw,hours,every_days,first_day,release_hour,window,pausable\n';
  assert.ok(M.parseJobsCsv(head + 'A,0x10,4,1,0,18,14,yes\n').error.includes('mw'));
  assert.ok(M.parseJobsCsv(head + 'A,2,4,1,0,18,,yes\n').error.includes('window'));
  assert.ok(M.parseJobsCsv('name,mw\nA,2\n').error.includes('Missing column'));
  assert.ok(M.parseJobsCsv('').error);
});
