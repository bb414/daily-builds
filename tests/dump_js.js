// Prints the browser model's results for a fixed set of scenarios as JSON, so
// the Python tests can check that both versions agree number for number.
'use strict';
const { loadModel } = require('./load_model.js');

const M = loadModel();
const train = M.generateCohort(M.DEFAULTS.nTrain, M.DEFAULTS.trainSeed);
const model = M.trainModel(train);
const tables = M.costTables(train);
const background = M.backgroundSample(train, 64);
const cohort = M.generateCohort(M.DEFAULTS.nAudit, M.DEFAULTS.auditSeed);
const settings = M.defaultSettings();
const tight = M.defaultSettings();
tight[0].weight = 2;
tight[1].cap = 6;
tight[4].actionable = true;
tight[5].actionable = true;

function planSummary(r) {
  return { status: r.status, cost: r.cost, score: r.score, values: r.values, explored: r.explored };
}

const out = {
  features: M.FEATURES,
  presets: M.PRESETS,
  randoms: (function () { const r = M.mulberry32(2026); const a = []; for (let i = 0; i < 50; i++) a.push(r()); return a; })(),
  trainLabels: train.map(function (r) { return r.y; }),
  trainX: train.slice(0, 200).map(function (r) { return r.x; }),
  strongX: M.generateCohort(300, 47, 0.7).map(function (r) { return [r.x, r.g, r.y]; }),
  base: model.base,
  splits: model.splits,
  tables: tables,
  preds: cohort.map(function (r) { return M.predict(model, r.x); }),
  recourse: cohort.slice(0, 80).map(function (r) { return planSummary(M.findRecourse(model, tables, r.x, settings)); }),
  recourseTight: cohort.slice(80, 140).map(function (r) { return planSummary(M.findRecourse(model, tables, r.x, tight, { maxLevers: 2, margin: 0.04 })); }),
  options: M.PRESETS.map(function (p) {
    const o = M.recourseOptions(model, tables, p.x, settings);
    return { status: o.status, options: o.options.map(function (q) { return { cost: q.cost, values: q.values, lever: q.lever, mask: q.mask }; }) };
  }),
  shapley: M.PRESETS.map(function (p) { return M.shapley(model, p.x, background); }),
  audit: M.audit(model, tables, cohort, settings).groups,
  auditTight: M.audit(model, tables, cohort, tight, { maxLevers: 2, margin: 0.04 }).groups,
  margins: M.MARGINS,
  nextSplits: M.nextModel(3 / 6, 2).splits,
  hold: (function () {
    const table = M.routeTable(model, tables, cohort.slice(0, 200), tight, { maxLevers: 3 }, M.MARGINS);
    return M.holdSummary(M.nextModel(3 / 6, 2), cohort.slice(0, 200), table, M.MARGINS);
  })()
};
process.stdout.write(JSON.stringify(out));
