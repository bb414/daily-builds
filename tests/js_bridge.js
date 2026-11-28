/*
 * Runs the browser model on a job read from stdin and prints the answers as
 * JSON, so the Python tests can check the companion gives the same ones.
 *
 * The model is taken from app/index.html (between the MODEL START and
 * MODEL END markers) when that file exists, otherwise from src/model.js.
 *
 * Job: {cases: [{project, files, edits, settings, saved}], exports, numbers,
 * dates, sides, headers, roots, accountNames, projects, sizing}. Every part is
 * optional.
 */
'use strict';

var fs = require('fs');
var path = require('path');

var ROOT = path.resolve(__dirname, '..');

function loadModel() {
  var page = path.join(ROOT, 'app', 'index.html');
  if (!process.env.ROUND_TRIPS_SRC && fs.existsSync(page)) {
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

function runCase(job) {
  var state = job.project ? M.readProject(job.project).state : M.emptyState();
  if (job.settings) Object.keys(job.settings).forEach(function (k) { state.settings[k] = job.settings[k]; });
  if (job.carry) state.carry = job.carry;
  var imp = M.importFiles(state, job.files || []);
  state = imp.state;
  (job.edits || []).forEach(function (e) { state.journal = M.setJournal(state.journal, e.id, e.fields); });
  var result = M.analyse(state);
  var start = M.startBalance(result, result.accounts);
  var out = { reports: imp.reports, result: {}, stats: {}, breakdowns: {}, reviews: [] };
  Object.keys(result).forEach(function (k) { if (k !== 'settings') out.result[k] = result[k]; });
  out.stats.all = M.stats(result.closed, { start: start });
  result.accounts.forEach(function (a) {
    out.stats[a] = M.stats(M.filterTrades(result.closed, { account: a }), { start: M.startBalance(result, [a]) });
  });
  M.BREAKDOWNS.forEach(function (b) { out.breakdowns[b.id] = M.breakdown(result.closed, b.id); });
  out.weekly = M.weekly(result.closed);
  out.histogram = M.rHistogram(result.closed);
  [''].concat(result.accounts).forEach(function (a) {
    result.weeks.forEach(function (w) {
      var rv = M.weekReview(result, { week: w, account: a });
      out.reviews.push({ week: w, account: a, review: rv, text: M.reviewText(rv, result) });
    });
  });
  out.tradesCsv = M.tradesCsv(result);
  out.breachesCsv = M.breachesCsv(result);
  out.fillsCsv = M.fillsCsv(result);
  out.projectFile = M.projectFile(state, job.saved || '2026-11-28');
  return out;
}

function main() {
  var job = JSON.parse(fs.readFileSync(0, 'utf8'));
  var out = {};
  out.cases = (job.cases || []).map(runCase);
  out.exports = (job.exports || []).map(function (e) { return M.readExport(e.name, e.text, e.opts || {}); });
  out.numbers = (job.numbers || []).map(function (s) {
    return { read: M.readNumber(s, false), comma: M.readNumber(s, true), cents: M.parseCents(s), micro: M.parseMicro(s), float: M.parseFloatText(s) };
  });
  out.dates = (job.dates || []).map(function (s) {
    return { shape: M.dateShape(s), dmy: M.parseDateTime(s, 'DMY'), mdy: M.parseDateTime(s, 'MDY'), time: M.parseTime(s) };
  });
  out.dateOrder = M.detectDateOrder(job.dates || []);
  out.sides = (job.sides || []).map(function (s) { return M.classifySide(s); });
  out.headers = (job.headers || []).map(function (s) { return M.normHeader(s); });
  out.roots = (job.roots || []).map(function (s) { return M.symbolRoot(s); });
  out.accountNames = (job.accountNames || []).map(function (s) { return M.cleanAccountName(s); });
  out.projects = (job.projects || []).map(function (t) { return M.readProject(t); });
  out.sizing = (job.sizing || []).map(function (s) { return M.positionSize(s); });
  out.carries = (job.carries || []).map(function (c) { return M.makeCarry(c.u, c.date, c.price); });
  out.delimited = (job.delimited || []).map(function (t) { var d = M.sniffDelimiter(t); return { delim: d, parsed: M.parseDelimited(t, d) }; });
  out.formats = (job.formats || []).map(function (x) {
    return { money: M.money(x, 'USD'), sign: M.money(x, 'GBP', { sign: true }), whole: M.money(x, 'EUR', { whole: true }), num: M.fmtNum(x / 7, 2), pct: M.fmtPct(x / 100000, 1),
      r: M.fmtR(x / 1000), price: M.fmtPrice(x * 1000), qty: M.fmtQty(x * 10000), dur: M.fmtDuration(Math.abs(x)), date: M.fmtDate(20000 + (Math.abs(x) % 3000)) };
  });
  out.template = M.templateCsv();
  process.stdout.write(JSON.stringify(out));
}

main();
