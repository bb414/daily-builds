/*
 * Runs the browser model on a job read from stdin and prints the results as
 * JSON, so the Python tests can check the companion gives the same answers.
 *
 * The model is taken from app/index.html (between the MODEL START and
 * MODEL END markers) when that file exists, otherwise from src/model.js.
 *
 * Job: {analyses: [{files, asOf, extra, aliases, names, manual, overrides,
 * decisions, details, budgetMonths, icsDays, icsIncludeIncome, saved}],
 * amounts, dates, descriptions, headers, delimited, folds, holidays,
 * accountNames, projects}. Every part is optional.
 */
'use strict';

var fs = require('fs');
var path = require('path');

var ROOT = path.resolve(__dirname, '..');

function loadModel() {
  var page = path.join(ROOT, 'app', 'index.html');
  if (fs.existsSync(page)) {
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

function day(v) { return v === null || v === undefined ? undefined : M.fromIso(v); }

function runAnalysis(job) {
  var a = M.analyse({
    files: job.files || [], asOf: day(job.asOf), aliases: job.aliases, names: job.names, manual: job.manual,
    overrides: job.overrides, extra: job.extra ? M.readProject(job.extra).transactions : undefined
  });
  var r = a.result;
  var decisions = job.decisions || {};
  var pl = M.plan(r, decisions, { details: job.details });
  var suggestions = {};
  r.series.forEach(function (s) { suggestions[s.id] = M.suggest(s); });
  return {
    summary: M.summary(r),
    statements: a.statements,
    merged: a.merged,
    result: r,
    registerCsv: M.registerCsv(r, decisions),
    budgetCsv: M.budgetCsv(r, decisions, job.budgetMonths),
    ics: M.buildIcs(r, decisions, { days: job.icsDays, includeIncome: job.icsIncludeIncome, details: job.details }),
    projectText: M.projectFile({
      transactions: a.merged.transactions, result: r, decisions: decisions, accounts: a.merged.accounts,
      aliases: job.aliases, names: job.names, manual: job.manual, overrides: job.overrides, details: job.details
    }),
    plan: { totals: pl.totals, actions: pl.actions },
    forecast: M.forecast(r, 92, decisions),
    monthTotals: M.monthTotals(M.forecast(r, 365, decisions), false),
    suggestions: suggestions,
    since: job.saved ? M.sinceLastReview(r, M.readProject(job.saved)) : null,
    runways: a.merged.accounts.filter(function (acc) { return acc.closing; }).map(function (acc) {
      return M.runway(r, decisions, { account: acc.account, balance: acc.closing.balance, everyday: r.everyday[acc.account] ? r.everyday[acc.account].perDay : 0, overdraft: 50000, leaveOutCancelled: true, days: 60, extraIn: [{ day: r.asOf + 20, amount: 12345, name: 'Loan' }] });
    })
  };
}

function main() {
  var job = JSON.parse(fs.readFileSync(0, 'utf8'));
  var out = {};
  out.analyses = (job.analyses || []).map(runAnalysis);
  out.amounts = (job.amounts || []).map(function (s) { return M.parseAmount(s); });
  out.dates = (job.dates || []).map(function (s) {
    return { shape: M.dateShape(s), dmy: M.parseDate(s, 'DMY'), mdy: M.parseDate(s, 'MDY') };
  });
  out.dateOrder = M.detectDateOrder(job.dates || []);
  out.descriptions = (job.descriptions || []).map(function (d) {
    var key = M.payeeKey(d);
    return { key: key, name: M.displayName(key), clean: M.cleanDescription(d), category: M.categorise(d), method: M.paymentMethod('', d) };
  });
  out.headers = (job.headers || []).map(function (cells) { return M.mapHeader(cells); });
  out.delimited = (job.delimited || []).map(function (d) {
    return { sniffed: M.sniffDelimiter(d.text), parsed: M.parseDelimited(d.text, d.delim || M.sniffDelimiter(d.text)) };
  });
  out.folds = (job.folds || []).map(function (s) { return M.icsFold(s); });
  out.holidays = (job.holidays || []).map(function (y) { return M.bankHolidays(y); });
  out.accountNames = (job.accountNames || []).map(function (n) { return M.defaultAccount(n); });
  out.projects = (job.projects || []).map(function (t) { return M.readProject(t); });
  out.template = M.templateCsv();
  process.stdout.write(JSON.stringify(out));
}

main();
