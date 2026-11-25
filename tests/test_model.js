// Node.js tests for the browser app's model block. Run: node tests/test_model.js
'use strict';
const assert = require('assert');
const { loadModel } = require('./load_model.js');

const M = loadModel();
let passed = 0;
function test(name, fn) {
  try { fn(); passed++; } catch (e) { console.error('FAIL ' + name + '\n' + e.stack); process.exitCode = 1; }
}

test('exports the documented pieces', function () {
  ['runLab', 'generateWorld', 'buildCrm', 'auditCrm', 'fitLogistic', 'auc', 'normaliseSettings'].forEach(function (k) {
    assert.strictEqual(typeof M[k], 'function', k);
  });
  assert.strictEqual(M.DEFECTS.length, 6);
  Object.keys(M.PRESETS).forEach(function (k) {
    M.DEFECTS.forEach(function (d) { assert.ok(M.PRESETS[k][d.key] <= d.max, k + ' ' + d.key); });
  });
});

test('settings are cleaned up', function () {
  const s = M.normaliseSettings({ seed: 'x', deals: 10, zombies: 3, blanks: -1, retrofill: Infinity });
  assert.strictEqual(s.seed, M.DEFAULTS.seed);
  assert.strictEqual(s.deals, 1000);
  assert.strictEqual(s.zombies, 0.8);
  assert.strictEqual(s.blanks, 0);
  assert.strictEqual(s.retrofill, M.DEFAULTS.retrofill);
  assert.deepStrictEqual(M.normaliseSettings(), M.DEFAULTS);
});

test('the same settings give the same answer', function () {
  const a = M.runLab({ seed: 77 });
  const b = M.runLab({ seed: 77 });
  assert.strictEqual(a.live.auc, b.live.auc);
  assert.strictEqual(a.backtest.auc, b.backtest.auc);
  assert.notStrictEqual(M.runLab({ seed: 78 }).live.auc, a.live.auc);
});

test('a typical CRM flatters the pilot and a clean one does not, on average', function () {
  let clean = 0, typical = 0;
  for (let s = 1; s <= 6; s++) {
    clean += M.runLab(Object.assign({ seed: s }, M.PRESETS.clean)).illusion;
    typical += M.runLab(Object.assign({ seed: s }, M.PRESETS.typical)).illusion;
  }
  assert.ok(Math.abs(clean / 6) < 0.03, 'clean ' + clean / 6);
  assert.ok(typical / 6 > 0.1, 'typical ' + typical / 6);
});

test('names of re-created deals normalise back to the account', function () {
  for (let k = 0; k < 50; k++) {
    const n = M.accountName(k);
    [0.1, 0.3, 0.6, 0.9].forEach(function (u) { assert.strictEqual(M.normName(M.twinName(n, u)), M.normName(n)); });
  }
});

test('auc handles ties and single classes', function () {
  assert.strictEqual(M.auc([0.5, 0.5, 0.5, 0.5], [0, 1, 0, 1]), 0.5);
  assert.strictEqual(M.auc([1, 2, 3], [0, 0, 0]), null);
  assert.strictEqual(M.auc([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]), 0.75);
});

test('the largest, messiest world stays fast enough for a slider', function () {
  const t0 = Date.now();
  M.runLab({ seed: 5, deals: 8000, blanks: 0.6, retrofill: 0.8, zombies: 0.8, recreated: 0.5, placeholders: 0.8, loggingShift: 0.7 });
  const ms = Date.now() - t0;
  assert.ok(ms < 1500, 'took ' + ms + 'ms');
});

test('dates are shown from 1 January 2024', function () {
  assert.strictEqual(M.dayToIso(0), '2024-01-01');
  assert.strictEqual(M.dayToIso(M.GO_LIVE), '2025-06-24');
});

test('fixing every habit lands exactly on the clean ceiling', function () {
  const r = M.runLab({ seed: 21, deals: 2000 });
  assert.strictEqual(r.fixes.path.length, 7);
  assert.ok(Math.abs(r.fixes.path[6].liveAuc - r.ceiling.auc) < 1e-12);
  assert.strictEqual(M.runLab({ seed: 21, deals: 1000 }, { fixes: false }).fixes, null);
});

test('the repaired back-test is far closer to live than the raw one', function () {
  const r = M.runLab(Object.assign({ seed: 3 }, M.PRESETS.chaos), { fixes: false });
  const raw = r.backtest.auc - r.live.auc;
  const rep = r.repaired.backtest.auc - r.repaired.live.auc;
  assert.ok(raw > 0.15, 'raw ' + raw);
  assert.ok(rep < 0.03, 'repaired back-test still overpromises: ' + rep);
  assert.ok(Math.abs(rep) < raw / 2, 'repaired gap ' + rep + ' vs raw ' + raw);
  assert.ok(r.repaired.live.auc > r.live.auc);
});

test('robustness runs the settings on the next worlds', function () {
  const rb = M.robustness({ seed: 40, deals: 1000 }, 3);
  assert.deepStrictEqual(rb.worlds.map(function (w) { return w.seed; }), [41, 42, 43]);
  assert.strictEqual(rb.summary.live.n, 3);
  assert.strictEqual(M.robustness({ seed: 1, deals: 1000 }, 'x').worlds.length, 12);
  assert.strictEqual(M.robustness({ seed: 1, deals: 1000 }, 500).worlds.length, 60);
  const sm = M.summarise([0.3, null, 0.1, NaN, 0.2]);
  assert.deepStrictEqual([sm.n, sm.low, sm.high, sm.median], [3, 0.1, 0.3, 0.2]);
});

console.log(passed + ' Node tests passed' + (process.exitCode ? ' (with failures above)' : ''));
