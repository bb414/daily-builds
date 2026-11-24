// Tests for the browser app's model, run with: node --test
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadModel } = require('./load_model.cjs');

const M = loadModel();

// Fill a session's answers with a simple rule. pick(trial, stage) returns
// [answer, confidence].
function fill(session, pick) {
  session.trials.forEach((t) => {
    const [a, c] = pick(t, 'initial');
    t.initial = { answer: a, confidence: c, ms: 1000 };
    if (t.phase === 'with') {
      const [fa, fc] = pick(t, 'final');
      t.final = { answer: fa, confidence: fc, ms: 800 };
    }
  });
  return session;
}
const other = (x) => (x === 'scam' ? 'genuine' : 'scam');

test('item bank has the intended design', () => {
  assert.equal(M.ITEMS.length, 28);
  const ids = new Set(M.ITEMS.map((i) => i.id));
  assert.equal(ids.size, 28);
  const checker = M.ITEMS.filter((i) => i.role === 'checker');
  const solo = M.ITEMS.filter((i) => i.role === 'solo');
  assert.equal(checker.length, 16);
  assert.equal(solo.length, 12);
  assert.equal(checker.filter((i) => i.ai.verdict === i.truth).length, 12, 'checker right on 12 of 16');
  const falseAlarms = checker.filter((i) => i.truth === 'genuine' && i.ai.verdict === 'scam');
  const misses = checker.filter((i) => i.truth === 'scam' && i.ai.verdict === 'genuine');
  assert.equal(falseAlarms.length, 2);
  assert.equal(misses.length, 2);
  assert.equal(checker.filter((i) => i.truth === 'scam').length, 8);
  const pairs = {};
  solo.forEach((i) => { (pairs[i.pair] = pairs[i.pair] || []).push(i); });
  assert.equal(Object.keys(pairs).length, 6);
  Object.values(pairs).forEach((members) => {
    assert.equal(members.length, 2);
    assert.equal(members[0].truth, members[1].truth, 'pair members share the right answer');
    assert.equal(members[0].difficulty, members[1].difficulty, 'pair members share difficulty');
  });
  assert.equal(solo.filter((i) => i.truth === 'scam').length, 6);
});

test('every message is fictional: .example links and drama phone numbers', () => {
  M.ITEMS.forEach((item) => {
    const text = [item.from, item.address, item.subject, item.context, item.body].join(' ');
    const domains = text.match(/\b[a-z0-9-]+(\.[a-z0-9-]+)*\.(com|co\.uk|org|net|uk|io|info|example)\b/gi) || [];
    domains.forEach((d) => assert.match(d, /\.example$/i, item.id + ' uses a non-reserved domain: ' + d));
    const phones = text.match(/(\+44 ?|0)\d[\d ]{8,}\d/g) || [];
    phones.forEach((p) => {
      const digits = p.replace(/\D/g, '').replace(/^44/, '0');
      assert.ok(/^07700900\d{3}$/.test(digits) || /^01632960\d{3}$/.test(digits), item.id + ' uses a real-looking number: ' + p);
    });
    assert.ok(item.cues.length >= 2, item.id + ' needs debrief cues');
    if (item.role === 'checker') {
      assert.ok(item.ai.reason.length > 20, item.id + ' needs a checker reason');
      assert.ok(item.ai.confidence >= 50 && item.ai.confidence <= 100);
    }
  });
});

test('buildSession is reproducible and follows the design', () => {
  const a = M.buildSession(12345);
  const b = M.buildSession(12345);
  assert.deepEqual(a, b);
  assert.notDeepEqual(M.buildSession(1).trials.map((t) => t.item), M.buildSession(2).trials.map((t) => t.item));
  assert.equal(a.trials.length, 28);
  assert.deepEqual(a.trials.map((t) => t.position), Array.from({ length: 28 }, (_, i) => i + 1));
  const phases = a.trials.map((t) => t.phase);
  assert.deepEqual(phases, [...Array(6).fill('before'), ...Array(16).fill('with'), ...Array(6).fill('after')]);
  assert.equal(a.format, 'second-opinion-session');
  assert.deepEqual(a.condition, { advice: 'reason', feedback: false, assignment: 'fixed' });
});

test('solo pairs are split across the two solo parts, for every seed tried', () => {
  for (let seed = 0; seed < 300; seed++) {
    const s = M.buildSession(seed);
    const pairOf = (id) => M.ITEM_BY_ID[id].pair;
    const before = s.trials.filter((t) => t.phase === 'before').map((t) => pairOf(t.item)).sort();
    const after = s.trials.filter((t) => t.phase === 'after').map((t) => pairOf(t.item)).sort();
    assert.deepEqual(before, ['p1', 'p2', 'p3', 'p4', 'p5', 'p6']);
    assert.deepEqual(after, ['p1', 'p2', 'p3', 'p4', 'p5', 'p6']);
    const withTrials = s.trials.filter((t) => t.phase === 'with');
    assert.equal(withTrials[0].ai.verdict, withTrials[0].truth, 'first checker message is right (seed ' + seed + ')');
    assert.equal(withTrials[1].ai.verdict, withTrials[1].truth, 'second checker message is right (seed ' + seed + ')');
    assert.equal(new Set(s.trials.map((t) => t.item)).size, 28);
  }
});

test('odd seeds and conditions are normalised', () => {
  assert.equal(M.buildSession(NaN).seed, 1);
  assert.equal(M.buildSession('abc').seed, 1);
  assert.equal(M.buildSession(-7.9).seed, 7);
  assert.equal(M.buildSession(2 ** 32 + 5).seed, 5);
  assert.deepEqual(M.buildSession(1, { advice: 'shout', feedback: 'yes' }).condition, { advice: 'reason', feedback: false, assignment: 'fixed' });
  assert.deepEqual(M.buildSession(1, { advice: 'verdict', feedback: true }).condition, { advice: 'verdict', feedback: true, assignment: 'fixed' });
});

test('random assignment spreads people evenly over the three advice styles', () => {
  const counts = { verdict: 0, confidence: 0, reason: 0 };
  for (let seed = 1000; seed < 1300; seed++) {
    const c = M.buildSession(seed, { advice: 'random', feedback: true }).condition;
    assert.equal(c.assignment, 'random');
    assert.equal(c.feedback, true);
    counts[c.advice]++;
  }
  assert.deepEqual(counts, { verdict: 100, confidence: 100, reason: 100 });
  // A saved random session keeps its label when normalised again.
  assert.deepEqual(M.normaliseCondition({ advice: 'confidence', feedback: false, assignment: 'random' }, 5),
    { advice: 'confidence', feedback: false, assignment: 'random' });
});

test('reliance over time splits at the checker\'s first mistake', () => {
  const s = M.buildSession(21);
  const w = s.trials.filter((t) => t.phase === 'with');
  const firstWrong = w.findIndex((t) => t.ai.verdict !== t.truth);
  assert.ok(firstWrong >= 2);
  // Disagree with every message; switch only before the first mistake.
  fill(s, (t, stage) => {
    if (t.phase !== 'with') { return [t.truth, 70]; }
    if (stage === 'initial') { return [other(t.ai.verdict), 60]; }
    return [w.indexOf(t) < firstWrong ? t.ai.verdict : other(t.ai.verdict), 60];
  });
  const r = M.score(s).trust;
  assert.equal(r.firstErrorAt, firstWrong + 1);
  assert.deepEqual(r.beforeFirstError, { disagreements: firstWrong, switched: firstWrong, rate: 1 });
  assert.deepEqual(r.afterFirstError, { disagreements: 15 - firstWrong, switched: 0, rate: 0 });
  assert.equal(r.change, -1);
  assert.equal(r.timeline.length, 16);
  assert.equal(r.timeline[firstWrong].checkerRight, false);
  // Trials stored out of order are put back in order first.
  const shuffled = JSON.parse(JSON.stringify(s));
  shuffled.trials.reverse();
  assert.deepEqual(M.score(shuffled).trust, M.score(s).trust);
  // Before the checker has made a mistake, everything is in the "before" window.
  const early = M.buildSession(21);
  early.trials.slice(0, 8).forEach((t) => {
    t.initial = { answer: t.truth, confidence: 70 };
    if (t.phase === 'with') { t.final = { answer: t.truth, confidence: 70 }; }
  });
  const e = M.score(early).trust;
  assert.equal(e.firstErrorAt, null);
  assert.equal(e.afterFirstError.rate, null);
  assert.equal(e.change, null);
});

test('a perfect person who ignores the checker holds firm and is never corrected', () => {
  const s = fill(M.buildSession(9), (t) => [t.truth, 100]);
  const r = M.score(s);
  assert.equal(r.accuracy.before, 1);
  assert.equal(r.accuracy.withFinal, 1);
  assert.equal(r.accuracy.checker, 0.75);
  assert.equal(r.reliance.cells.checkerWrong.n, 4);
  assert.equal(r.reliance.cells.checkerWrong.heldFirm, 4);
  assert.equal(r.reliance.cells.checkerRight.n, 0);
  assert.equal(r.reliance.rair, null);
  assert.equal(r.reliance.rsr, 1);
  assert.equal(r.reliance.followWhenWrong, 0);
  assert.equal(r.complementarity, 0);
  assert.equal(r.profile.key, 'holds-firm');
  assert.equal(r.profile.tentative, true);
  assert.equal(r.confidence.before.brier, 0);
  assert.equal(r.complete, true);
});

test('always following the checker scores exactly the checker and is over-reliant', () => {
  // First answers: always the opposite of the checker, so every message is a disagreement.
  const s = fill(M.buildSession(4), (t, stage) => {
    if (t.phase !== 'with') { return [t.truth, 80]; }
    return stage === 'initial' ? [other(t.ai.verdict), 60] : [t.ai.verdict, 90];
  });
  const r = M.score(s);
  assert.equal(r.accuracy.withFinal, 0.75);
  assert.equal(r.accuracy.withInitial, 0.25);
  assert.equal(r.reliance.rair, 1);
  assert.equal(r.reliance.rsr, 0);
  assert.equal(r.reliance.followWhenWrong, 1);
  assert.equal(r.reliance.switchRate, 1);
  assert.equal(r.reliance.switchWhenDisagree, 1);
  assert.equal(r.reliance.disagreements, 16);
  assert.equal(r.profile.key, 'over');
  assert.equal(r.profile.tentative, false);
  assert.equal(r.complementarity, 0);
});

test('a hand-built session gives the expected numbers', () => {
  const s = M.buildSession(77);
  const w = s.trials.filter((t) => t.phase === 'with');
  const right = w.filter((t) => t.ai.verdict === t.truth);
  const wrong = w.filter((t) => t.ai.verdict !== t.truth);
  // Defaults: everything right and agreeing.
  s.trials.forEach((t) => {
    t.initial = { answer: t.truth, confidence: 80 };
    if (t.phase === 'with') { t.final = { answer: t.truth, confidence: 80 }; }
  });
  // Two correctable mistakes: one corrected, one not.
  right[0].initial = { answer: other(right[0].truth), confidence: 60 };
  right[0].final = { answer: right[0].truth, confidence: 70 };
  right[1].initial = { answer: other(right[1].truth), confidence: 90 };
  right[1].final = { answer: other(right[1].truth), confidence: 90 };
  // Of the four checker errors: two held firm, one misled, one where both were wrong.
  wrong[0].final = { answer: wrong[0].ai.verdict, confidence: 60 };
  wrong[1].initial = { answer: other(wrong[1].truth), confidence: 50 };
  wrong[1].final = { answer: other(wrong[1].truth), confidence: 70 };
  // One talked out of a right answer where both agreed.
  right[2].final = { answer: other(right[2].truth), confidence: 50 };
  const r = M.score(s);
  const c = r.reliance.cells;
  assert.deepEqual(c.checkerRight, { n: 2, corrected: 1 });
  assert.deepEqual(c.checkerWrong, { n: 3, heldFirm: 2 });
  assert.deepEqual(c.bothWrong, { n: 1, finalRight: 0 });
  assert.deepEqual(c.bothRight, { n: 10, finalRight: 9 });
  assert.equal(r.reliance.rair, 0.5);
  assert.equal(r.reliance.rsr, 2 / 3);
  assert.equal(r.reliance.appropriate, 3 / 5);
  assert.equal(r.reliance.followWhenWrong, 2 / 4);
  assert.deepEqual(r.reliance.switches, { towardChecker: 2, awayFromChecker: 1, total: 3 });
  assert.equal(r.correct.withInitial, 13);
  assert.equal(r.correct.withFinal, 12);
  assert.equal(r.profile.key, 'calibrated');
  assert.ok(Math.abs(r.complementarity - (12 / 16 - 13 / 16)) < 1e-12);
});

test('unfinished sessions score only what was answered', () => {
  const s = M.buildSession(3);
  for (let i = 0; i < 8; i++) {
    const t = s.trials[i];
    t.initial = { answer: t.truth, confidence: 70 };
  }
  // Message 7 is in the checker phase: first answer given, final not yet.
  const r = M.score(s);
  assert.equal(r.n.before, 6);
  assert.equal(r.n['with'], 0);
  assert.equal(r.accuracy.withFinal, null);
  assert.equal(r.complementarity, null);
  assert.equal(r.change, null);
  assert.equal(r.complete, false);
  assert.equal(r.profile.key, 'untested');
  const empty = M.score({ trials: [] });
  assert.equal(empty.n.total, 0);
  assert.equal(empty.complete, false);
  assert.equal(M.score(null).n.total, 0);
});

test('profiles cover every combination', () => {
  assert.equal(M.profileFor(null, null, 0, 0).key, 'untested');
  assert.equal(M.profileFor(1, 1, 2, 2).key, 'calibrated');
  assert.equal(M.profileFor(1, 0, 2, 2).key, 'over');
  assert.equal(M.profileFor(0, 1, 2, 2).key, 'under');
  assert.equal(M.profileFor(0, 0, 2, 2).key, 'misplaced');
  assert.equal(M.profileFor(1, null, 2, 0).key, 'takes-advice');
  assert.equal(M.profileFor(0, null, 2, 0).key, 'under');
  assert.equal(M.profileFor(null, 1, 0, 2).key, 'holds-firm');
  assert.equal(M.profileFor(null, 0, 0, 2).key, 'over');
  assert.equal(M.profileFor(1, 1, 1, 1).tentative, true);
  assert.equal(M.profileFor(0.5, 0.5, 2, 2).key, 'calibrated');
  assert.equal(M.profileFor(null, null, 0, 0).tentative, false);
});

test('validateSession accepts real sessions and explains bad ones', () => {
  const s = fill(M.buildSession(5), (t) => [t.truth, 70]);
  assert.deepEqual(M.validateSession(s), []);
  assert.deepEqual(M.validateSession(M.buildSession(5)), [], 'an unstarted session is still valid');
  assert.ok(M.validateSession(null).length > 0);
  assert.ok(M.validateSession({}).length > 0);
  assert.match(M.validateSession({ format: 'x', version: 1, trials: [] }).join(' '), /not a Second opinion/);
  const bad = JSON.parse(JSON.stringify(s));
  bad.trials[0].initial.confidence = 55;
  bad.trials[1].phase = 'during';
  bad.trials[7].ai = null;
  const problems = M.validateSession(bad);
  assert.equal(problems.length, 3);
  const many = JSON.parse(JSON.stringify(s));
  many.trials.forEach((t) => { t.truth = 'maybe'; });
  assert.equal(M.validateSession(many).length, 5, 'problems are capped at five');
  assert.ok(M.validateSession({ format: 'second-opinion-session', version: 99, trials: s.trials }).length > 0);
});

test('CSV export has one row per message and escapes properly', () => {
  const s = fill(M.buildSession(8), (t) => [t.truth, 90]);
  const csv = M.sessionToCsv(s);
  const lines = csv.trim().split('\n');
  assert.equal(lines.length, 29);
  assert.equal(lines[0], M.CSV_COLUMNS.join(','));
  const withRow = lines.find((l) => l.includes(',with,'));
  assert.equal(withRow.split(',').length, M.CSV_COLUMNS.length);
  s.id = 'a,"b"';
  assert.ok(M.sessionToCsv(s).split('\n')[1].startsWith('"a,""b"""'));
});
