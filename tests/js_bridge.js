/*
 * Runs the browser model on jobs read from stdin and prints the results as
 * JSON, so the Python tests can check the companion gives the same answers.
 *
 * The model is taken from app/index.html (between the MODEL START and
 * MODEL END markers) when that file exists, otherwise from src/model.js.
 *
 * Input: a list of {fn, args}. "outputs" is a composite job that analyses a
 * text and returns every file the app can download for it.
 */
'use strict';

var fs = require('fs');
var path = require('path');

var ROOT = path.resolve(__dirname, '..');

function loadModel() {
  var page = path.join(ROOT, 'app', 'index.html');
  if (fs.existsSync(page) && !process.env.CBM_FROM_SRC) {
    var html = fs.readFileSync(page, 'utf8');
    var start = html.indexOf('/* MODEL START */'), end = html.indexOf('/* MODEL END */');
    if (start >= 0 && end > start) {
      var mod = { exports: {} };
      new Function('module', 'exports', html.slice(start, end))(mod, mod.exports);
      return mod.exports;
    }
  }
  return require(path.join(ROOT, 'src', 'model.js'));
}

var M = loadModel();

function outputs(input, state) {
  var a = M.analyse(input);
  var st = Object.assign({ asOf: input.asOf }, state || {});
  var out = { summary: M.summarise(a, st.checks || {}, st.refChecks || {}), claimsCsv: M.claimsCsv(a, st.checks || {}),
    refsCsv: M.refsCsv(a, st.refChecks || {}), sessionsCsv: M.sessionsCsv((st.sessions || []).map(M.cleanSession)), declarations: {} };
  M.TEMPLATES.forEach(function (t) {
    var s2 = Object.assign({}, st, { project: Object.assign({}, st.project || {}, { template: t.id }), sessions: (st.sessions || []).map(M.cleanSession) });
    var d = M.declaration(a, s2);
    out.declarations[t.id] = { text: M.declarationText(d), markdown: M.declarationMarkdown(d), warnings: d.warnings };
  });
  out.projectFile = M.projectFile(Object.assign({}, st, { texts: { draft: input.draft, final: input.final, prompt: input.prompt, references: input.references, notes: input.notes } }));
  return out;
}

var jobs = JSON.parse(fs.readFileSync(0, 'utf8'));
var results = jobs.map(function (job) {
  try {
    if (job.fn === 'outputs') return { ok: outputs(job.args[0], job.args[1]) };
    if (typeof M[job.fn] !== 'function') return { error: 'no such function ' + job.fn };
    return { ok: M[job.fn].apply(null, job.args) };
  } catch (err) {
    return { error: String(err && err.stack || err) };
  }
});
process.stdout.write(JSON.stringify(results));
