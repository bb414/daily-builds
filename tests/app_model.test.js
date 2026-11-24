// Tests for the browser app's MODEL block, run with: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadModel } = require('./model_harness.js');

const M = loadModel();

test('the same code gives the same payments; a different code does not', () => {
  const a = M.generateCases({ n: 20, code: 'ABC12', aiAccuracy: 0.8 });
  const b = M.generateCases({ n: 20, code: 'ABC12', aiAccuracy: 0.8 });
  const c = M.generateCases({ n: 20, code: 'XYZ99', aiAccuracy: 0.8 });
  assert.deepEqual(a, b);
  assert.notDeepEqual(a.map((x) => x.levels), c.map((x) => x.levels));
});

test('payments are half fraud and the advisor is right exactly as often as set', () => {
  for (const n of [12, 20, 30]) {
    for (const acc of [0.7, 0.8, 0.9]) {
      const cases = M.generateCases({ n, code: 'balance', aiAccuracy: acc });
      assert.equal(cases.length, n);
      assert.equal(cases.filter((c) => c.truth === 'fraud').length, n / 2);
      assert.equal(cases.filter((c) => c.aiCorrect).length, Math.round(n * acc));
      cases.forEach((c) => assert.equal(c.aiCorrect, c.ai === c.truth));
    }
  }
});

test('advisor settings change the advice but not the payments', () => {
  const low = M.generateCases({ n: 20, code: 'class-1', aiAccuracy: 0.7, aiStyle: 'calibrated' });
  const high = M.generateCases({ n: 20, code: 'class-1', aiAccuracy: 0.9, aiStyle: 'confident' });
  assert.deepEqual(low.map((c) => [c.truth, c.levels, c.details]), high.map((c) => [c.truth, c.levels, c.details]));
  low.forEach((c, i) => {
    if (c.aiCorrect) assert.ok(high[i].aiCorrect, 'a better advisor keeps the weaker one’s right answers');
  });
});

test('confidence styles produce the documented ranges', () => {
  const cal = M.generateCases({ n: 60, code: 'styles', aiStyle: 'calibrated' });
  const sure = M.generateCases({ n: 60, code: 'styles', aiStyle: 'confident' });
  const hidden = M.generateCases({ n: 60, code: 'styles', aiStyle: 'hidden' });
  cal.forEach((c) => assert.ok(c.aiConfidence >= 0.5 && c.aiConfidence <= 0.99));
  sure.forEach((c) => assert.ok(c.aiConfidence >= 0.9 && c.aiConfidence <= 0.99));
  hidden.forEach((c) => assert.equal(c.aiConfidence, null));
  const meanRight = (cs, ok) => {
    const sel = cs.filter((c) => c.aiCorrect === ok);
    return sel.reduce((s, c) => s + c.aiConfidence, 0) / sel.length;
  };
  assert.ok(meanRight(cal, true) > meanRight(cal, false) + 0.05, 'honest confidence is higher when right');
});

test('an ideal reader of the six cues gets about 85% right', () => {
  let acc = 0;
  const walk = (i, levels, pg, pf) => {
    if (i === M.FEATURES.length) {
      acc += 0.5 * Math.max(pg, pf);
      return;
    }
    const f = M.FEATURES[i];
    f.levels.forEach((_, k) => walk(i + 1, levels.concat(k), pg * f.genuine[k], pf * f.fraud[k]));
  };
  walk(0, [], 1, 1);
  assert.ok(Math.abs(acc - 0.85) < 0.005, 'ideal accuracy ' + acc);
  M.FEATURES.forEach((f) => {
    assert.ok(Math.abs(f.genuine.reduce((s, v) => s + v, 0) - 1) < 1e-9);
    assert.ok(Math.abs(f.fraud.reduce((s, v) => s + v, 0) - 1) < 1e-9);
  });
});

test('ideal fraud probability is the product of the cue odds', () => {
  const levels = [2, 2, 1, 1, 3, 2];
  let odds = 1;
  M.FEATURES.forEach((f, i) => { odds *= f.fraud[levels[i]] / f.genuine[levels[i]]; });
  assert.ok(Math.abs(M.idealFraudProbability(levels) - odds / (1 + odds)) < 1e-12);
});

test('every rule’s errors plus its accuracy add up to one', () => {
  const rand = M.mulberry32(11);
  for (let i = 0; i < 200; i++) {
    const p = {
      human: 0.5 + rand() * 0.49, ai: 0.5 + rand() * 0.49, overlap: rand() * 1.6 - 0.6,
      aiSignal: rand() * 4, humanSignal: rand() * 4, aiBias: rand() * 4 - 2, humanBias: rand() * 4 - 2,
      threshold: 0.5 + rand() * 0.49, deferRate: rand()
    };
    const a = M.analyse(p);
    M.POLICIES.forEach((k) => {
      const r = a.policies[k];
      assert.ok(Math.abs(r.team + r.shared + r.overErrors + r.underErrors - 1) < 1e-12);
      assert.ok(r.team <= a.ceiling + 1e-12, k + ' cannot beat the best possible rule');
    });
    assert.ok(a.policies.fixed.team <= a.best + 1e-12, 'a fixed rate never beats the better solo');
  }
});

test('scoring a small hand-made session', () => {
  const trials = [
    { truth: 'fraud', initial: 'genuine', initialConfidence: 0.55, ai: 'fraud', aiConfidence: 0.9, final: 'fraud' },
    { truth: 'fraud', initial: 'fraud', initialConfidence: 0.95, ai: 'genuine', aiConfidence: 0.6, final: 'fraud' },
    { truth: 'genuine', initial: 'genuine', initialConfidence: 0.7, ai: 'fraud', aiConfidence: 0.8, final: 'fraud' },
    { truth: 'genuine', initial: 'fraud', initialConfidence: 0.85, ai: 'fraud', aiConfidence: 0.7, final: 'fraud' }
  ];
  const s = M.scoreSession(trials);
  assert.equal(s.initialAccuracy, 0.5);
  assert.equal(s.aiAccuracy, 0.25);
  assert.equal(s.finalAccuracy, 0.5);
  assert.equal(s.rair, 1);
  assert.equal(s.rsr, 0.5);
  assert.equal(s.outcomes.goodSwitch, 1);
  assert.equal(s.outcomes.heldFirm, 1);
  assert.equal(s.outcomes.overRelied, 1);
  assert.equal(s.outcomes.sharedMiss, 1);
  assert.throws(() => M.scoreSession([]), /at least one trial/);
  assert.throws(() => M.scoreSession([{ truth: 'maybe' }]), /truth/);
});

test('mistakes on the tricky payments fall where the cues mislead', () => {
  const pTruth = (c) => (c.truth === 'fraud' ? c.idealFraudProbability : 1 - c.idealFraudProbability);
  const meanWrong = (mistakes) => {
    let total = 0;
    let count = 0;
    for (let i = 0; i < 40; i++) {
      M.generateCases({ n: 30, code: 'm' + i, aiAccuracy: 0.8, mistakes }).forEach((c) => {
        if (!c.aiCorrect) { total += pTruth(c); count += 1; }
      });
    }
    return total / count;
  };
  const hard = meanWrong('hard');
  const random = meanWrong('random');
  const easy = meanWrong('easy');
  assert.ok(hard < random - 0.1 && random < easy - 0.05, [hard, random, easy].join(', '));
  const a = M.generateCases({ n: 20, code: 'same', mistakes: 'hard' });
  const b = M.generateCases({ n: 20, code: 'same', mistakes: 'easy' });
  assert.deepEqual(a.map((c) => c.details), b.map((c) => c.details));
});

test('the gain map has the right shape and matches single evaluations', () => {
  const g = M.gainGrid({ aiSignal: 2 }, 'optimal', 12);
  assert.equal(g.values.length, 12);
  assert.equal(g.gains.length, 12);
  g.gains.forEach((row) => assert.equal(row.length, 12));
  assert.equal(g.values[0], 0.5);
  assert.ok(Math.abs(g.values[11] - 0.99) < 1e-12);
  const one = M.evaluate({ aiSignal: 2, human: g.values[3], ai: g.values[7] }, 'optimal');
  assert.equal(g.gains[3][7], one.gain);
  M.gainGrid({}, 'fixed', 10).gains.forEach((row) => row.forEach((v) => assert.ok(v <= 1e-12)));
});

test('honest confidence is calibrated: answers shown at c% are right about c% of the time', () => {
  for (const acc of [0.7, 0.8, 0.9]) {
    const bins = {};
    for (let i = 0; i < 600; i++) {
      M.generateCases({ n: 20, code: 'cal' + i, aiAccuracy: acc, aiStyle: 'calibrated' }).forEach((c) => {
        const b = Math.min(4, Math.floor((c.aiConfidence - 0.5) / 0.1));
        bins[b] = bins[b] || { n: 0, right: 0, shown: 0 };
        bins[b].n += 1;
        bins[b].right += c.aiCorrect ? 1 : 0;
        bins[b].shown += c.aiConfidence;
      });
    }
    Object.values(bins).forEach((b) => {
      if (b.n < 400) return;
      const gap = Math.abs(b.right / b.n - b.shown / b.n);
      assert.ok(gap < 0.04, 'accuracy ' + acc + ': shown ' + (b.shown / b.n).toFixed(3) + ' vs right ' + (b.right / b.n).toFixed(3));
    });
  }
});

test('session checks reject malformed trials', () => {
  assert.throws(() => M.scoreSession([null]), /must be an object/);
  assert.throws(() => M.counterfactuals([]), /at least one trial/);
  assert.throws(() => M.scoreSession([{ truth: 'fraud', initial: 'fraud', ai: 'fraud', final: 'fraud', initialConfidence: 0.4 }]), /initialConfidence/);
});
