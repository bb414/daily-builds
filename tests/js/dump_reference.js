// Prints one JSON document of reference outputs from the JavaScript model, read by
// tests/python/test_agreement.py. Numbers JSON cannot carry (NaN, the infinities, -0) and undefined are
// written as {"$js": "NaN"} and so on. Run from anywhere: node tests/js/dump_reference.js
'use strict';
const { loadModel } = require('./load_model.js');

const M = loadModel();

function plain(v) {
  if (typeof v === 'number') {
    if (v !== v) return { $js: 'NaN' };
    if (v === Infinity) return { $js: 'Infinity' };
    if (v === -Infinity) return { $js: '-Infinity' };
    if (v === 0 && 1 / v < 0) return { $js: '-0' };
    return v;
  }
  if (v === undefined) return { $js: 'undefined' };
  if (v === null || typeof v !== 'object') return v;
  if (Array.isArray(v) || ArrayBuffer.isView(v)) return Array.from(v, plain);
  const out = {};
  for (const k of Object.keys(v)) out[k] = plain(v[k]);
  return out;
}

function grid(lo, hi, step) {
  const out = [];
  for (let k = 0; lo + k * step <= hi; k++) out.push(lo + k * step);
  return out;
}

// The double next to x in either direction (for probing branch boundaries).
const view = new DataView(new ArrayBuffer(8));
function nextUp(x, dir) {
  view.setFloat64(0, x);
  const bits = view.getBigUint64(0) + (dir > 0 === x >= 0 ? 1n : -1n);
  view.setBigUint64(0, bits);
  return view.getFloat64(0);
}

const src = new M.Rng(20261127);
function randoms(n, f) { const out = []; for (let k = 0; k < n; k++) out.push(f()); return out; }

// ---------- pure functions: {fn, cases: [[args, result], ...]} ----------
const calls = [];
function record(fn, argLists) {
  calls.push({ fn: fn, cases: argLists.map(function (args) { return [args, M[fn].apply(null, args)]; }) });
}
const one = function (xs) { return xs.map(function (x) { return [x]; }); };

const expPoints = [NaN, Infinity, -Infinity, 0, -0, 1, -1, 0.5, -0.5, 1e-300, -1e-300, 5e-324, 709.78,
  nextUp(709.78, 1), nextUp(709.78, -1), 709.7, -745.1, nextUp(-745.1, 1), nextUp(-745.1, -1), -745, -744.5,
  -740, -730, -720, -708.4, -708.3, -700, 700, 705, 0.34657359027997264, -0.34657359027997264,
  0.6931471805599453, 693.1471805599453, -693.1471805599453, -694, -695]
  .concat(grid(-750, 712, 0.731))
  .concat(randoms(3000, function () { return (src.next() - 0.5) * 2 * Math.pow(10, src.int(6) - 3); }));
const logPoints = [NaN, -1, -0, 0, Infinity, -Infinity, 5e-324, 1e-320, 2.2250738585072014e-308,
  2.225073858507201e-308, 1.7976931348623157e308, 8.98846567431158e307, 1, nextUp(1, 1), nextUp(1, -1),
  Math.SQRT2, nextUp(Math.SQRT2, 1), nextUp(Math.SQRT2, -1), 2, 0.5, 10, 13, 20 / 260, 0.1, 3, 1e300, 1e-300]
  .concat(grid(-1074, 1023, 3).map(function (k) { return Math.pow(2, k) * (1 + src.next()); }))
  .concat(randoms(3000, function () { return M.detExp((src.next() - 0.5) * 60); }));
const normPoints = [-1, -0, 0, 1, 2, NaN, Infinity, -Infinity, 0.02425, nextUp(0.02425, -1), nextUp(0.02425, 1),
  1 - 0.02425, nextUp(1 - 0.02425, 1), nextUp(1 - 0.02425, -1), 1e-300, 5e-324, 1e-16, 1 - 1e-16,
  nextUp(1, -1), 0.5, nextUp(0.5, 1)]
  .concat(grid(0, 2000, 1).map(function (k) { return k / 2000; }))
  .concat(randoms(3000, function () { return src.open(); }));
const cdfPoints = [NaN, Infinity, -Infinity, 0, -0, 40, -40, 1e-300, -1e-300, 1.959963984540054, -1.959963984540054]
  .concat(grid(-40, 40, 0.017))
  .concat(randoms(3000, function () { return 3 * src.normal(); }));

record('detExp', one(expPoints));
record('detLog', one(logPoints));
record('invNorm', one(normPoints));
record('normCdf', one(cdfPoints));
record('hashSeed', [[], [0], [1], [7, 101], [7, 202], [7, 303], [1, 404, 7], [1, 0, 3, 7], [1, 35, 4, 7],
  [1000000, 900, 7], [4294967295], [4294967296], [-1], [2.9], [-2.9], [1e10], [1e20], [NaN], [Infinity],
  ['15'], [' 15 '], ['0x1f'], ['abc'], [''], [true], [false], [1, 2, 3, 4, 5, 6, 7, 8]]);
record('clamp', [[5, 1, 3], [-2, 1, 3], [2.5, 1, 3], [NaN, 1, 3], [Infinity, 0, 1], [-0, 0, 1], [1, 1, 1]]);
record('roundHalfUp', one([0.5, -0.5, 1.5, -1.5, 2.4999999999999996, 0.49999999999999994, -2.5, 1e16, -7.5,
  NaN, Infinity, -Infinity, 0, -0, 3.7, -3.7]));
record('quantile', [[[1, 2, 3, 4], 0.5], [[1, 2, 3, 4], 0], [[1, 2, 3, 4], 1], [[1, 2, 3, 4], 0.9], [[5], 0.3],
  [[], 0.5], [[1, 2, 3], NaN], [[1, 2, 3], 1.5], [[1, 2, 3], -0.1], [[0.1, 0.2, 0.7], 0.975], [[1, 2, 3], Infinity]]);
record('sortNumbers', one([[3, 1, 2], [0.5, -0, 0, -1, 2.5], [], [1e-300, -1e300, 7]]));
record('mean', one([[1, 2, 3, 4], [], [0.1, 0.2, 0.3], [5]]));
record('sd', one([[1, 2, 3, 4], [], [5], [0.1, 0.2, 0.7, 0.3]]));
record('auc', [[[1, 2, 3, 4], [0, 0, 1, 1]], [[4, 3, 2, 1], [0, 0, 1, 1]], [[1, 1, 1, 1], [0, 1, 0, 1]],
  [[0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]], [[1, 2, 3], [0, 0, 0]], [[1, 2, 3], [1, 1, 1]], [[], []],
  [[0.3, 0.3, 0.1, 0.9, 0.5], [true, false, false, true, 1]]]);
record('rocCurve', [[[0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]], [[1, 1, 2, 2, 3], [0, 1, 0, 1, 1], 2],
  [[5, 4, 3, 2, 1], [1, 1, 0, 0, 0], 0], [[], []]]);
record('confusion', [[[0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1], 0.35], [[1, 2, 3], [0, 0, 0], 5], [[], [], 1]]);
record('bootMean', [[[1, 2, 3, 4, 5], 11], [[0.5, -1, 2], 31, 200], [[], 3], [[7], 1, 10]]);
record('weekInfo', one(grid(0, 37, 1)));
record('makeSquad', one([7, 3, 0, 4294967295]));
record('withDefaults', [[], [{}], [{ threshold: 9, budget: 0, intensity: 2, rotateAfter: 2.7, restTraining: -1,
  spike: 5, contactScale: -2, historySeasons: 99 }],
  [{ threshold: '1.7', budget: '12', squadSeed: '3', seasonSeed: -1 }],
  [{ policy: 'bogus', flag: 'nope', preseason: 'STEEP', gradedReturn: 0 }], [{ gradedReturn: 'false' }],
  [{ gradedReturn: '' }], [{ squadSeed: 3.9, seasonSeed: 4294967297 }], [{ threshold: 'abc', budget: ' ' }],
  [{ rotateAfter: Infinity, historySeasons: -Infinity }], [{ extra: 5, threshold: undefined }],
  [{ squadSeed: '0x10', intensity: ' 1.1 ', budget: true }], [{ policy: 'readiness', flag: 'oracle', spike: '1e0' }]]);
const squad7 = M.makeSquad(7);
const tmCases = [];
[0, 5, 12, 30].forEach(function (p) {
  [[100, 100], [400, 200], [50, 300], [260, 60], [700, 260]].forEach(function (ac, k) {
    tmCases.push([squad7.players[p], ac[0], ac[1], k % 2 === 0, [0, 2, 3.5][k % 3]]);
  });
});
record('truthMult', tmCases);
record('perfMult', grid(0, 20, 1).map(function (k) { return [40 * k, 25 * (20 - k) + 30]; }));
record('solveLinear', [[[[2, 1], [1, 3]], [3, 5]], [[[0, 1], [1, 0]], [2, 3]], [[[1, 2], [2, 4]], [1, 2]],
  [[[4, -2, 1], [-2, 4, -2], [1, -2, 4]], [11, -16, 17]], [[[1e-13, 0], [0, 1]], [1, 2]]]);
const lx = randoms(300, function () { return [src.normal(), 2 + src.next(), src.int(3), 1]; });
const ly = lx.map(function (r) { return src.next() < 1 / (1 + M.detExp(-(r[0] - 1.5))) ? 1 : 0; });
record('trainLogistic', [[lx, ly, 1.0], [lx.slice(0, 40), ly.slice(0, 40), 0.1]]);
const lm = M.trainLogistic(lx, ly, 1.0);
record('predictLogistic', lx.slice(0, 50).map(function (x) { return [lm, x]; }));
const powerCases = [];
[[-3, 4], [-1.5, 6.2], [0, 5], [2, 0], [0, 0], [NaN, 3], [-0.5, NaN]].forEach(function (ds) {
  [1, 2, 5, 10, 40].forEach(function (n) { powerCases.push([ds[0], ds[1], n]); });
});
record('powerTwoSample', powerCases);
record('seasonsFor', [[-3, 4, 0.8], [-1.5, 6.2, 0.8], [0, 5, 0.8], [NaN, 5, 0.8], [2, 0, 0.8], [1, 5, 0.9],
  [-0.01, 7, 0.8], [1e-300, 5, 0.8]]);
record('daysFromCivil', [[1970, 1, 1], [2000, 2, 29], [2026, 7, 20], [1600, 3, 1], [-1, 12, 31], [-400, 1, 1],
  [0, 2, 29], [9999, 12, 31], [2026, 2, 29], [2026, 0, 5], [2026, 13, 1], [2026, -10, 1], [2026, -3, 1]]);
record('civilFromDays', one(grid(-1000000, 1000000, 9973).concat([-719468, -719469, 0, -1, 20654, 2932896])));
record('formatDay', one([0, -1, 20654, M.SEASON_START, -719468, 2932896, -800000]));
record('parseDay', one(['2026-09-05', ' 2026-9-5 ', '2026-02-29', '2024-02-29', '1900-02-29', '2000-02-29',
  '05/09/2026', '5/9/2026', '31/04/2026', '2026-13-01', '2026-00-10', '2026-01-32', 'abc', '', '2026-09-05\n',
  '\u00a02026-09-05\t', '\uff12\uff10\uff12\uff16-09-05', '\u0662\u0660\u0662\u0666-09-05', '2026-09-05 extra',
  '0000-01-01', '2026/09/05', '\ufeff2026-09-05', '2026-09-05\u2028', '2026-09-05\x85', 20260905, undefined]));
record('parseCSV', one(['a,b,c\n1,2,3\n', 'a,b\r\n1,2\r\n', '\ufeffdate;player\n2026-01-01;A\n',
  '"x, y",z\n"he said ""hi""",2\n', 'a\tb\tc\n', '"multi\nline",2\n', '\n\n  \n a \n', 'a,b\n,\n',
  '"unterminated,1\n2', 'a"b,c\n', '"a"b,c\n', '"",x\n', '""""\n', 'x\ry\n', 'a,b', '', '   ', '\ufeff',
  'emoji \ud83c\udfc9,ok\n', 'a;b,c\td\n', '" spaced " , x\n', 'mid\ufeffbom\n', '\u3000\n\u0085\n', 'x\n\r\n\ry']));
record('toCSV', [[['date', 'note', 'n'], [['2026-01-01', 'plain', 4], ['2026-01-02', 'has, comma', 6.5],
  ['x', 'say "hi"', -0], ['x', 'semi;colon', 1e21], ['x', 'line\nbreak', 1e-7], ['x', 'cr\rhere', 0.1 + 0.2],
  ['x', 'tab\there', 123456789012], [null, undefined, NaN], [true, false, Infinity], ['x', '', -1.5],
  ['x', 'tiny', 5e-324], ['x', 'huge', 1.7976931348623157e308], ['x', 'big int', 2.5e20], ['x', 'neg', -1e-7]]],
[[], []]]);
const restSeason = M.runSeason({ policy: 'rest', flag: 'model' }, 5);
record('coachView', [[restSeason], [{ weekly: [], injuries: [] }]]);
record('couplingDemo', [[3], [5, 1], [8, 25]]);
record('readLogbook', one([[], [['date', 'name']], [['Date', 'Athlete', 'Duration']],
  [['x', 'y'], ['1', '2']]]));

// ---------- the generator ----------
const rngSeeds = [0, 1, 2, 7, 42, 123456789, 4294967295];
const rng = {
  seeds: rngSeeds,
  next: rngSeeds.map(function (s) { const r = new M.Rng(s); return randoms(2000, function () { return r.next(); }); }),
  weird: [-1, 3.7, -3.7, 4294967301, '12', NaN, Infinity, 1e20, true].map(function (s) {
    const r = new M.Rng(s);
    return { seed: s, values: randoms(3, function () { return r.next(); }) };
  })
};
const r99 = new M.Rng(99);
rng.mixed = {
  seed: 99,
  open: randoms(500, function () { return r99.open(); }),
  normal: randoms(500, function () { return r99.normal(); }),
  ints: [1, 2, 3, 7, 15, 18, 44, 1000, 4294967296, 0.5, 2.5].map(function (n) {
    return { n: n, values: randoms(50, function () { return r99.int(n); }) };
  })
};

// ---------- constants ----------
const constants = {};
['VERSION', 'HIST', 'PRE_WEEKS', 'COMP_WEEKS', 'WEEKS', 'SEASON_DAYS', 'TOTAL_DAYS', 'COMP_PLAN', 'CTL_REF',
  'GROUPS', 'SLOTS', 'CLUB', 'DEFAULTS', 'POLICIES', 'FLAGS', 'FEATURES', 'BASE', 'FLAG_LABELS', 'POLICY_LABELS',
  'METRICS', 'SEASON_START'].forEach(function (k) { constants[k] = M[k]; });

// ---------- seasons ----------
const seasonCases = [
  {},
  { policy: 'rest', flag: 'model' },
  { policy: 'modify', flag: 'ewma', threshold: 1.3 },
  { policy: 'rotate' },
  { policy: 'readiness' },
  { preseason: 'steep', intensity: 1.2, gradedReturn: false, spike: 3, contactScale: 1.5, squadSeed: 3 },
  { policy: 'rest', flag: 'oracle', budget: 20 },
  { policy: 'rest', flag: 'coupled', threshold: 1.2, restTraining: 0.3 },
  { policy: 'rotate', rotateAfter: 2, flag: 'uncoupled' }
];
const seasons = [];
seasonCases.forEach(function (s) {
  [1, 2].forEach(function (seed) { seasons.push({ settings: s, seed: seed, out: M.runSeason(s, seed) }); });
});
const dailySettings = { policy: 'rest', flag: 'model' };
const daily = M.runSeason(dailySettings, 3, { keepDaily: true });
seasons.push({ settings: dailySettings, seed: 3, opts: { keepDaily: true }, out: daily });
seasons.push({ settings: {}, seed: 4, opts: { collectRows: true }, out: M.runSeason({}, 4, { collectRows: true }) });
seasons.push({ settings: { seasonSeed: 6 }, out: M.runSeason({ seasonSeed: 6 }) });

const prepared = [{}, seasonCases[5], { budget: 20 }].map(function (s) {
  const ctx = M.prepare(s);
  return { settings: s, out: { model: ctx.model, cutoffs: ctx.cutoffs, historyRows: ctx.historyRows,
    historyInjuries: ctx.historyInjuries } };
});

const players = M.prepare(dailySettings).squad.players;
const series = { settings: dailySettings, seed: 3, players: [0, 20],
  out: [players[0], players[20]].map(function (p) { return M.playerSeries(daily, p); }) };

// ---------- analyses ----------
const evaluations = [{ settings: {}, seeds: [1, 2, 3] }].map(function (c) {
  return { settings: c.settings, seeds: c.seeds, out: M.evaluateFlags(c.settings, c.seeds) };
});
const comparisons = [{ settings: {}, seeds: [1, 2, 3] },
  { settings: { flag: 'model' }, seeds: [4, 5], policies: ['rest', 'none'] }].map(function (c) {
  return { settings: c.settings, seeds: c.seeds, policies: c.policies,
    out: M.comparePolicies(c.settings, c.seeds, c.policies) };
});
const pilots = [{ settings: {}, pairs: 3 }, { settings: { policy: 'modify', flag: 'model' }, pairs: 2 },
  { settings: {}, pairs: 0 }].map(function (c) {
  return { settings: c.settings, pairs: c.pairs, out: M.pilotStudy(c.settings, c.pairs) };
});

// ---------- the inquest ----------
const inquests = [{ settings: { policy: 'rest', flag: 'model' }, seed: 6 }, { settings: { policy: 'none', spike: 3 }, seed: 2 },
  { settings: { policy: 'modify', flag: 'ewma', threshold: 1.3, contactScale: 0.5 }, seed: 9 }].map(function (c) {
  return { settings: c.settings, seed: c.seed, out: M.inquest(c.settings, c.seed) };
});

// ---------- logbooks ----------
const COLUMNS = ['date', 'player', 'position', 'session', 'minutes', 'rpe', 'injury'];
const lb = M.seasonLogbook({}, 1);
const csv = M.toCSV(COLUMNS, lb.rows.map(function (r) { return COLUMNS.map(function (k) { return r[k]; }); }));
const book = M.readLogbook(M.parseCSV(csv));
const s = lb.season;
const logbook = {
  settings: {}, seed: 1, rowCount: lb.rows.length, firstRows: lb.rows.slice(0, 60), csv: csv,
  season: { injuriesTotal: s.injuriesTotal, nc: s.nc, daysLost: s.daysLost, points: s.points, injuries: s.injuries },
  book: book,
  analyses: [{ permutations: 20 }, { permutations: 5, only: 'all', threshold: 1.3, seed: 9 }].map(function (o) {
    return { opts: o, out: M.analyseLogbook(book, o) };
  })
};

// A small hand-rolled club logbook: three players, ten weeks, messy rows and a few injuries.
const g = new M.Rng(4242);
const lines = ['Date;Athlete;Duration;sRPE;Injury Type'];
for (let day = 0; day < 70; day++) {
  ['Ann Oak', 'Bo Reed', 'Cy Ash'].forEach(function (name, k) {
    if (g.next() < 0.3) return;
    const date = M.formatDay(M.daysFromCivil(2026, 8, 3) + day);
    const shown = k === 1 ? date.slice(8) + '/' + date.slice(5, 7) + '/' + date.slice(0, 4) : date;
    const inj = g.next() < 0.04 ? (g.next() < 0.5 ? 'contact' : 'hamstring') : (g.next() < 0.5 ? 'no' : '');
    lines.push([shown, name, 30 + g.int(70), 3 + g.int(7), inj].join(';'));
  });
}
lines.push('not a date;Ann Oak;40;5;', '2026-08-10;;40;5;', '2026-08-11;Bo Reed;abc;5;', '2026-08-12;Cy Ash;9000;1;');
const small = lines.join('\r\n');
const tricky = [small, 'date,player,load\n2026-09-01,A,100\n2026-09-02,A,\n2026-09-03,B,50\n',
  'day,name,minutes,rpe,injured\n2026-01-05,A,60,5,yes\n2026-01-06,A,60,5,non-contact\n2026-01-20,A,60,5,0\n',
  'date,player,load\n2020-01-01,A,10\n2026-01-01,A,10\n', 'date,player,load\nbad,A,10\n',
  'date,player,minutes\n2026-01-01,A,10\n', 'date,player,load,minutes,rpe\n2026-01-01,A,,30,4\n2026-01-02,A,0x10,,\n'];
const logbooks = tricky.map(function (text) {
  const b = M.readLogbook(M.parseCSV(text));
  const entry = { csv: text, book: b };
  const opts = { permutations: 10, seed: 3 };
  if (!b.error) entry.analysis = { opts: opts, out: M.analyseLogbook(b, opts) };
  return entry;
});

process.stdout.write(JSON.stringify(plain({
  calls: calls, rng: rng, constants: constants, seasons: seasons, prepared: prepared, series: series,
  evaluations: evaluations, comparisons: comparisons, pilots: pilots, inquests: inquests, logbook: logbook, logbooks: logbooks
})));
