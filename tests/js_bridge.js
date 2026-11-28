/*
 * Runs the browser model on a job read from stdin and prints the results as
 * JSON, so the Python tests can check the companion gives the same answers.
 *
 * The model is taken from app/index.html (between the MODEL START and MODEL
 * END markers) when that file exists, otherwise from src/model.js.
 */
'use strict';

var fs = require('fs');
var path = require('path');

var ROOT = path.resolve(__dirname, '..');

function loadModel() {
  var page = path.join(ROOT, 'app', 'index.html');
  if (fs.existsSync(page) && !process.env.EXAM_SEASON_SRC) {
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

function planOut(plan) {
  return {
    from: plan.from, fromMin: plan.fromMin, last: plan.last, notes: plan.notes, sessions: plan.sessions, days: plan.days,
    exams: plan.exams, topics: plan.topics
  };
}

// One project job: {project (file text), today, ticks: [[id, day]], replan: {day, min}, overrides: [...]}
function runProject(job) {
  var read = M.readProject(job.project, job.today);
  var p = read.project;
  var plan = M.buildPlan(p);
  (job.ticks || []).forEach(function (t) { M.tick(p, plan, t[0], t[1], t[2] !== false); });
  (job.rates || []).forEach(function (r) { M.rate(p, plan, r[0], r[1], r[2]); });
  if (job.replan) {
    M.replan(p, plan, job.replan.day, job.replan.min || 0);
    plan = M.buildPlan(p);
  }
  (job.overrides || []).forEach(function (o) { M.setOverride(p, o.day, o.minutes, o.label); });
  if (job.overrides && job.overrides.length) plan = M.buildPlan(p);
  var st = M.status(p, plan, job.today);
  return {
    messages: read.messages, plan: planOut(plan), status: st, summary: M.summary(p, plan, st),
    csv: M.sessionsCsv(p, plan), statusCsv: M.statusCsv(st), ics: M.sessionsIcs(p, plan, { name: p.name }),
    icsToday: M.sessionsIcs(p, plan, { fromDay: job.today, toDay: job.today, exams: false, skipDone: true }),
    dayText: M.dayText(p, plan, job.today), projectFile: M.projectFile(p), availabilityCsv: M.availabilityCsv(p),
    topics: M.topicStatus(p, plan, job.today)
  };
}

function main() {
  var job = JSON.parse(fs.readFileSync(0, 'utf8'));
  var out = {};
  out.projects = (job.projects || []).map(runProject);
  out.exams = (job.exams || []).map(function (x) { return M.readExams(x.text, { ref: x.ref }); });
  out.topics = (job.topics || []).map(function (x) {
    var r = M.readTopics(x.text, { exams: x.exams || [], code: x.code || '' });
    M.assignTopicIds(r.topics);
    return r;
  });
  out.calendars = (job.calendars || []).map(function (x) { return M.readCalendar(x.text, x.from, x.to); });
  out.busy = (job.busy || []).map(function (x) { return M.readBusy(x.text, x.from, x.to); });
  out.availability = (job.availability || []).map(function (x) { return M.readAvailability(x.text); });
  out.dates = (job.dates || []).map(function (s) { return [M.parseDate(s, 'DMY', 20788), M.parseDate(s, 'MDY', 20788), M.findDate(s, 'DMY', 20788)]; });
  out.times = (job.times || []).map(function (s) { return [M.parseTime(s), M.findTimes(s), M.parseClock(s)]; });
  out.durations = (job.durations || []).map(function (s) { return [M.parseDuration(s, ''), M.parseDuration(s, 'min'), M.parseDuration(s, 'hour')]; });
  out.confidence = (job.confidence || []).map(function (s) { return [M.parseConfidence(s), M.parseSize(s, true), M.parseSize(s, false), M.splitTopicAttrs(s)]; });
  out.delimited = (job.delimited || []).map(function (t) { return [M.sniffDelimiter(t), M.parseDelimited(t, M.sniffDelimiter(t)), M.readTable(t)]; });
  out.folds = (job.folds || []).map(function (s) { return M.icsFold(s); });
  out.slugs = (job.slugs || []).map(function (s) { return M.slugify(s); });
  out.codes = (job.codes || []).map(function (s) { return [M.findCode(s), M.normCode(s)]; });
  out.utc = (job.utc || []).map(function (x) { return M.utcToLondon(x[0], x[1]); });
  out.cleaned = (job.cleaned || []).map(function (t) { var r = M.readProject(t, 20788); return r.project ? M.projectFile(r.project) : r.messages; });
  out.templates = [M.examTemplate(), M.topicTemplate()];
  process.stdout.write(JSON.stringify(out));
}

main();
