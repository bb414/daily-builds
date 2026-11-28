/* Tests of the browser model, run with: node --test tests/ */
'use strict';

var test = require('node:test');
var assert = require('node:assert/strict');
var fs = require('fs');
var path = require('path');

var ROOT = path.resolve(__dirname, '..');

function loadModel() {
  var page = path.join(ROOT, 'app', 'index.html');
  if (fs.existsSync(page)) {
    var html = fs.readFileSync(page, 'utf8');
    var start = html.indexOf('/* MODEL START */'), end = html.indexOf('/* MODEL END */');
    var mod = { exports: {} };
    new Function('module', 'exports', html.slice(start, end))(mod, mod.exports);
    return mod.exports;
  }
  return require(path.join(ROOT, 'src', 'model.js'));
}

var M = loadModel();
var D = M.dayFromYmd;
var FROM = D(2026, 11, 30);
var TODAY = D(2026, 12, 10);

function data(name) { return fs.readFileSync(path.join(ROOT, 'data', name), 'utf8'); }

function sampleProject() { return M.readProject(data('sample-project.json'), TODAY).project; }

// Alex's plan as first made, with nothing done yet.
function freshProject() { return M.readProject(data('group/alex.json'), FROM).project; }

test('day numbers round-trip and weekdays are right', function () {
  for (var d = D(1999, 1, 1); d < D(2031, 1, 1); d += 37) {
    var t = M.ymdFromDay(d);
    assert.equal(D(t[0], t[1], t[2]), d);
  }
  assert.equal(M.weekday(D(2027, 1, 11)), 0); // a Monday
  assert.equal(M.weekday(D(2026, 12, 25)), 4); // a Friday
  assert.equal(M.fmtDay(D(2027, 1, 22)), 'Fri 22 Jan 2027');
  assert.equal(M.isoDay(D(2028, 2, 29)), '2028-02-29');
});

test('dates in the shapes portals and people write them', function () {
  var want = D(2027, 1, 11);
  ['11/01/2027', '11/1/27', '2027-01-11', '11 Jan 2027', 'Monday 11 January 2027', 'Mon 11-Jan-27', '11.01.2027', 'January 11, 2027',
    '11th January 2027', '20270111', '2027-01-11T09:30:00', '11/01/2027 09:30'].forEach(function (s) {
    assert.equal(M.parseDate(s, 'DMY', FROM), want, s);
  });
  assert.equal(M.parseDate('01/11/2027', 'MDY', FROM), want);
  assert.equal(M.parseDate('11 Jan', 'DMY', FROM), want, 'a missing year is the next one after the reference');
  assert.equal(M.parseDate('31/02/2027', 'DMY', FROM), null);
  assert.equal(M.parseDate('TBC', 'DMY', FROM), null);
  var f = M.findDate('ECO3112 Behavioural Economics 13/01/2027 14:00', 'DMY', FROM);
  assert.equal(f.day, D(2027, 1, 13));
});

test('clock times and lengths', function () {
  assert.equal(M.parseTime('09:30'), 570);
  assert.equal(M.parseTime('9.30am'), 570);
  assert.equal(M.parseTime('2pm'), 840);
  assert.equal(M.parseTime('2:00'), 840, 'an afternoon exam written without pm');
  assert.equal(M.parseTime('1400'), 840);
  assert.equal(M.parseTime('12am'), 0);
  assert.equal(M.parseTime('25:00'), null);
  assert.deepEqual(M.findTimes('09:30 - 11:30').map(function (t) { return t.min; }), [570, 690]);
  assert.equal(M.parseDuration('2 hours'), 120);
  assert.equal(M.parseDuration('1h 30m'), 90);
  assert.equal(M.parseDuration('2:30'), 150);
  assert.equal(M.parseDuration('2.5 hrs'), 150);
  assert.equal(M.parseDuration('90'), 90);
  assert.equal(M.parseDuration('2'), 120, 'a small bare number is hours');
  assert.equal(M.parseDuration('2', 'min'), 2);
  assert.equal(M.parseDuration('(120 mins)'), 120);
  assert.equal(M.fmtHours(75), '1.3 h');
  assert.equal(M.fmtHours(90), '1.5 h');
});

test('UK clock changes for times written in UTC', function () {
  assert.deepEqual(M.utcToLondon(D(2027, 1, 6), 660), [D(2027, 1, 6), 660]);
  assert.deepEqual(M.utcToLondon(D(2027, 6, 1), 660), [D(2027, 6, 1), 720]);
  assert.deepEqual(M.utcToLondon(D(2027, 3, 28), 59), [D(2027, 3, 28), 59], 'just before the clocks go forward');
  assert.deepEqual(M.utcToLondon(D(2027, 3, 28), 60), [D(2027, 3, 28), 120]);
  assert.deepEqual(M.utcToLondon(D(2027, 6, 1), 1400), [D(2027, 6, 2), 20], 'late UTC times move to the next day');
});

test('delimited text with quotes, a byte order mark and line breaks in cells', function () {
  var rows = M.parseDelimited('﻿a,"b, with comma","say ""hi"""\r\n1,"two\nlines",3\n', ',');
  assert.deepEqual(rows[0].cells, ['a', 'b, with comma', 'say "hi"']);
  assert.deepEqual(rows[1].cells, ['1', 'two\nlines', '3']);
  assert.equal(M.sniffDelimiter('a\tb\tc\n1\t2\t3'), '\t');
  assert.equal(M.sniffDelimiter('a;b;c\n1;2;3'), ';');
  var csv = M.csvText([['x', 'a,b', 'say "hi"']]);
  assert.equal(csv, '﻿x,"a,b","say ""hi"""\r\n');
});

test('a portal CSV export is read in full', function () {
  var r = M.readExams(data('alex/exam-timetable.csv'), { ref: FROM });
  assert.equal(r.format, 'csv');
  assert.equal(r.exams.length, 5);
  assert.deepEqual(r.messages, []);
  var eco = r.exams[1];
  assert.equal(eco.code, 'ECO3112');
  assert.equal(eco.room, 'Sports Centre, Hall B');
  assert.equal(eco.day, D(2027, 1, 13));
  assert.equal(eco.start, 840);
  assert.equal(r.exams[2].duration, 180, 'the Duration (mins) header says minutes');
});

test('the messy pasted timetable: mixed dates, repeated header, blank row and a resit to be confirmed', function () {
  var r = M.readExams(data('messy-timetable.txt'), { ref: FROM });
  assert.equal(r.format, 'table');
  assert.equal(r.exams.length, 6);
  var byCode = {};
  r.exams.forEach(function (e) { byCode[e.code] = e; });
  assert.equal(byCode.MGT3104.day, D(2027, 1, 11));
  assert.equal(byCode.MGT3104.start, 570);
  assert.equal(byCode.LAW3207.day, D(2027, 1, 19));
  assert.equal(byCode.LAW3207.start, 840);
  assert.equal(byCode.DAT3301.duration, 150);
  assert.equal(byCode.MKT2210.day, null);
  assert.equal(byCode.MKT2210.tbc, true);
  assert.equal(byCode.MKT2210.resit, true);
  var text = r.messages.map(function (m) { return m.text; }).join('\n');
  assert.match(text, /repeats the header row/);
  assert.match(text, /MKT2210 has no date yet/);
  assert.match(text, /1 blank row skipped/);
  assert.match(text, /read as a title/);
});

test('an exam calendar (.ics), loose lines and files that are not timetables', function () {
  var ics = M.readExams(data('exam-timetable.ics'), { ref: FROM });
  assert.equal(ics.exams.length, 5);
  assert.equal(ics.exams[0].name, 'Strategic Management');
  assert.equal(ics.exams[1].room, 'Sports Centre, Hall B');
  var lines = M.readExams('My exams\nECO3112 Behavioural Economics 13/01/2027 14:00 2h\nFIN3020 Corporate Finance Fri 15 Jan 2027 9.30am (3 hours)\nLAW3207 Competition Law TBC\n', { ref: FROM });
  assert.equal(lines.format, 'lines');
  assert.equal(lines.exams.length, 3);
  assert.equal(lines.exams[1].duration, 180);
  assert.equal(lines.exams[1].start, 570);
  assert.equal(lines.exams[2].tbc, true);
  assert.match(M.readExams('%PDF-1.7 binary', {}).messages[0].text, /PDF/);
  assert.match(M.readExams('', {}).messages[0].text, /nothing to read/);
  var bad = M.readExams('Module,Date,Start\nABC1001,32/13/2027,09:00\nABC1001,32/13/2027,09:00\n', { ref: FROM });
  assert.match(bad.messages.map(function (m) { return m.text; }).join(' '), /could not read the date "32\/13\/2027"/);
});

test('a timetable page saved from the portal, US dates and time ranges in one cell', function () {
  var html = M.readExams(data('exam-timetable.html'), { ref: FROM });
  assert.equal(html.format, 'html');
  assert.equal(html.exams.length, 5, 'the commented-out row is ignored');
  assert.deepEqual([html.exams[2].code, html.exams[2].start, html.exams[2].duration], ['FIN3020', 570, 180], 'start and end from "15/01/2027 09:30-12:30"');
  assert.equal(html.exams[1].name, 'Behavioural Economics');
  var us = M.readExams('Course,Date,Time,Length\nABC1001,01/13/2027,9:00 AM,2h\nABC1002,01/08/2027,1:30 PM,90\n', { ref: FROM });
  assert.equal(us.exams[0].day, D(2027, 1, 8));
  assert.equal(us.exams[1].day, D(2027, 1, 13));
  assert.match(us.messages.map(function (m) { return m.text; }).join(' '), /month first/);
  var either = M.readExams('Module,Date\nABC1001,02/01/2027\n', { ref: FROM });
  assert.equal(either.exams[0].day, D(2027, 1, 2));
  assert.match(either.messages.map(function (m) { return m.text; }).join(' '), /day first \(UK order\) was assumed/);
  assert.match(M.readExams('<table><tr><td>nothing</td><td>useful</td></tr></table>', {}).messages[0].text, /no header row/);
  assert.equal(M.htmlRows('<table><tr><th>A &amp; B</th><td>caf&eacute; &#233;<br>two</td></tr></table>')[0].cells[1], 'caf&eacute; é two');
});

test('a shift rota as busy times, including shifts past midnight', function () {
  var r = M.readBusy(data('group/sam/shift-rota.csv'), FROM - 7, D(2027, 1, 31));
  assert.equal(r.events, 11);
  var sat = r.busy.filter(function (b) { return b.day === D(2026, 12, 5) || b.day === D(2026, 12, 6); });
  assert.deepEqual(sat.map(function (b) { return [b.day - FROM, b.start, b.end]; }), [[5, 1140, 1440], [6, 0, 60]]);
  assert.equal(r.busy[0].label, 'Bar (Fox and Lantern)');
  var bad = M.readBusy('Date,Start,Hours,Role\n05/12/2026,18:00,5,Bar\nsoon,18:00,5,Bar\n05/12/2026,,5,Bar\n', FROM, FROM + 30);
  assert.equal(bad.busy.length, 1);
  assert.equal(bad.busy[0].end, 1380);
  assert.deepEqual(bad.messages.map(function (m) { return m.level; }), ['warn', 'warn', 'info'], 'two rows skipped, and a note that 05/12 could be read either way');
  assert.match(M.readBusy('just words', FROM, FROM + 1).messages[0].text, /No header row/);
});

test('topics from a CSV and from a pasted list', function () {
  var exams = M.readExams(data('alex/exam-timetable.csv'), { ref: FROM }).exams;
  var csv = M.readTopics(data('alex/topics.csv'), { exams: exams });
  assert.equal(csv.topics.length, 40);
  assert.deepEqual(csv.messages, []);
  var list = M.readTopics(data('topics-pasted.txt'), { exams: exams });
  assert.equal(list.format, 'list');
  var got = list.topics.map(function (t) { return [t.code, t.name, t.conf, t.size]; });
  assert.deepEqual(got[2], ['MGT3104', 'Dynamic capabilities', 2, 300]);
  assert.deepEqual(got[3], ['MGT3104', 'Blue ocean strategy', 4, 120]);
  assert.deepEqual(got[4], ['MGT3104', 'Business models and platforms', 3, 180]);
  assert.deepEqual(got[5], ['ECO3112', 'Prospect theory', 2, 300], 'a heading matched by title');
  assert.deepEqual(got[7], ['ECO3112', 'Nudges and choice architecture', 4, 120]);
  assert.deepEqual(got[8], ['ECO3112', 'Present bias and discounting', 1, 180]);
});

test('topic names that end in numbers or ordinary words keep them', function () {
  var r = M.readTopics('ABC1234\n- Chapter 3\n- Week 5 lecture\n- Theory of light\n- Elasticity 3h\n- Supply (2/5)\n', {});
  assert.deepEqual(r.topics.map(function (t) { return [t.name, t.conf, t.size]; }),
    [['Chapter 3', 3, 180], ['Week 5 lecture', 3, 180], ['Theory of light', 3, 180], ['Elasticity', 3, 180], ['Supply', 2, 180]]);
  assert.equal(M.parseConfidence('amber'), 3);
  assert.equal(M.parseConfidence('★★☆☆☆'), 2);
  assert.equal(M.parseConfidence('70%'), 4);
  assert.equal(M.parseSize('xl'), 420);
  var orphan = M.readTopics('Module,Topic\nZZZ9999,Something\n', { exams: [{ code: 'ABC1234', name: 'X' }] });
  assert.match(orphan.messages.map(function (m) { return m.text; }).join(' '), /not in your exam timetable/);
});

test('calendars: weekly repeats, skipped dates, moved and cancelled events, UTC times and all-day entries', function () {
  var r = M.readCalendar(data('alex/busy-calendar.ics'), FROM - 7, D(2027, 1, 31));
  function on(day, label) { return r.busy.filter(function (b) { return b.day === day && b.label === label; }); }
  assert.equal(on(D(2026, 12, 7), 'MGT3104 Lecture').length, 1, 'weekly until the end of term');
  assert.equal(on(D(2026, 12, 14), 'MGT3104 Lecture').length, 0, 'the repeat stops at UNTIL');
  assert.equal(on(D(2026, 12, 2), 'FIN3020 Lecture').length, 0, 'EXDATE skips a week');
  assert.equal(on(D(2026, 12, 9), 'FIN3020 Lecture').length, 1);
  assert.equal(on(D(2026, 12, 3), 'LAW3207 Lecture').length, 0, 'the moved lecture is gone from Thursday');
  assert.equal(on(D(2026, 12, 4), 'LAW3207 Lecture (moved)')[0].start, 840);
  assert.equal(on(D(2026, 12, 8), 'Careers fair').length, 0, 'cancelled events are left out');
  assert.equal(on(D(2027, 1, 6), 'Dentist')[0].start, 660, 'UTC in January is UK time');
  assert.equal(on(D(2026, 12, 26), 'Shift at Wren Lane Coffee').length, 0);
  var rugby = r.busy.filter(function (b) { return b.label === 'Rugby training'; });
  assert.equal(rugby.length, 4, 'COUNT=11 from 6 Oct leaves four in the window');
  assert.equal(rugby[3].day, D(2026, 12, 15), 'and the eleventh is the last');
  assert.ok(r.allDay.some(function (a) { return a.label === 'Home for Christmas' && a.day === D(2026, 12, 25); }));
  assert.ok(!r.allDay.some(function (a) { return a.label === "Gran's birthday"; }), 'free (transparent) entries are left out');
  var night = M.readCalendar('BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:20261205T220000\nDTEND:20261206T020000\nSUMMARY:Night shift\nEND:VEVENT\nEND:VCALENDAR\n', FROM, FROM + 30);
  assert.deepEqual(night.busy.map(function (b) { return [b.day - FROM, b.start, b.end]; }), [[5, 1320, 1440], [6, 0, 120]]);
  assert.match(M.readCalendar('Not a calendar', FROM, FROM + 1).messages[0].text, /not a calendar/);
});

test('availability files: weekdays, ranges and blocked days', function () {
  var r = M.readAvailability(data('alex/availability.csv'));
  assert.equal(r.week[0].minutes, 360);
  assert.equal(r.week[5].from, 600);
  assert.equal(r.overrides.length, 7);
  var r2 = M.readAvailability('Day,From,To,Hours,Note\nWeekdays,10,18,4,\nweekends,,,off,\n24/12/2026 - 26/12/2026,,,0,Christmas\nSomeday,,,2,\n');
  assert.equal(r2.week[2].from, 600);
  assert.equal(r2.week[6].minutes, 0);
  assert.equal(r2.overrides.length, 3);
  assert.match(r2.messages[0].text, /not a weekday or a date/);
  var round = M.readAvailability(M.availabilityCsv({ week: r.week, overrides: r.overrides }));
  assert.deepEqual(round.week, r.week);
  assert.equal(round.overrides.length, r.overrides.length);
});

function planOf(p) { return M.buildPlan(p); }

test('the plan respects your time: windows, hours, busy times and exams', function () {
  var p = freshProject();
  var plan = planOf(p);
  var s = p.settings;
  assert.ok(plan.sessions.length > 250);
  var busyBy = {};
  p.busy.forEach(function (b) { (busyBy[b.day] = busyBy[b.day] || []).push(b); });
  var used = {};
  plan.sessions.forEach(function (se) {
    var w = M.dayWindow(p, se.day);
    assert.ok(!w.blocked, 'no session on a blocked day');
    assert.ok(se.start >= w.from && se.end <= w.to, 'inside the window ' + se.id);
    (busyBy[se.day] || []).forEach(function (b) {
      assert.ok(se.end <= b.start - s.busyGap || se.start >= b.end + s.busyGap, se.id + ' clashes with ' + b.label);
    });
    p.exams.forEach(function (e) {
      if (e.day === se.day) assert.ok(se.start >= e.start + e.duration + s.examGap, 'revise only after the exam');
    });
    used[se.day] = (used[se.day] || 0) + se.min;
  });
  plan.days.forEach(function (d) { assert.ok(d.used <= d.cap, 'within the hours for ' + M.fmtDay(d.day)); });
  // Sessions on one day never overlap.
  var byDay = {};
  plan.sessions.forEach(function (se) { (byDay[se.day] = byDay[se.day] || []).push(se); });
  Object.keys(byDay).forEach(function (k) {
    var list = byDay[k];
    for (var i = 1; i < list.length; i++) assert.ok(list[i].start >= list[i - 1].end + s.breakMin);
  });
});

test('the taper: no new topics late, papers in the last fortnight, the day before kept', function () {
  var p = freshProject();
  var plan = planOf(p);
  plan.exams.forEach(function (e) {
    plan.sessions.forEach(function (se) {
      if (se.exam !== e.id) return;
      if (se.kind === 'learn') assert.ok(se.day <= e.day - p.settings.taperDays - 1, 'no learning for ' + e.code + ' in the taper');
      if (se.kind === 'paper') assert.ok(se.day >= e.day - 15 && se.day <= e.day - 2);
    });
    assert.equal(e.finalDay, e.day - 1, 'the day before ' + e.code + ' is kept');
    var onFinal = plan.sessions.filter(function (se) { return se.day === e.finalDay; });
    assert.ok(onFinal.length >= 6);
    onFinal.forEach(function (se) { assert.equal(se.exam, e.id); assert.equal(se.kind, 'final'); });
  });
  var paperDays = {};
  plan.sessions.forEach(function (se) {
    if (se.kind !== 'paper') return;
    assert.ok(!paperDays[se.day], 'one past paper a day');
    paperDays[se.day] = true;
  });
});

test('weak and heavy topics first, spaced reviews at growing gaps, modules mixed', function () {
  var p = freshProject();
  var plan = planOf(p);
  var first = {}, reviews = {};
  plan.sessions.forEach(function (se) {
    if (se.kind === 'learn' && first[se.topic] === undefined) first[se.topic] = se.day;
    if (se.kind === 'review') (reviews[se.topic] = reviews[se.topic] || []).push(se.day);
  });
  plan.exams.forEach(function (e) {
    var ts = p.topics.filter(function (t) { return t.code === e.code; });
    var weak = ts.filter(function (t) { return t.conf <= 2; }), strong = ts.filter(function (t) { return t.conf >= 4; });
    if (!weak.length || !strong.length) return;
    var lastWeak = Math.max.apply(null, weak.map(function (t) { return first[t.id]; }));
    var firstStrong = Math.min.apply(null, strong.map(function (t) { return first[t.id]; }));
    assert.ok(lastWeak <= firstStrong, e.code + ': weak topics start before strong ones');
  });
  plan.topics.forEach(function (t) {
    var learnt = t.learnedDay, r = reviews[t.id] || [];
    var prev = learnt;
    r.forEach(function (d, i) { assert.ok(d - prev >= M.REVIEW_GAPS[i], t.id + ' review ' + (i + 1)); prev = d; });
  });
  // On ordinary days with three or more sessions, more than one module appears.
  var byDay = {};
  plan.sessions.forEach(function (se) { (byDay[se.day] = byDay[se.day] || []).push(se); });
  var mixed = 0, total = 0;
  var secondLast = plan.exams[plan.exams.length - 2].day;
  plan.days.forEach(function (d) {
    var list = byDay[d.day] || [];
    if (d.reserved.length || list.length < 3 || d.day >= secondLast) return;
    total++;
    var codes = {};
    list.forEach(function (se) { codes[se.code] = true; });
    if (Object.keys(codes).length > 1) mixed++;
  });
  assert.equal(mixed, total, 'every ordinary day mixes modules');
});

test('the plan is the same every time', function () {
  var a = planOf(freshProject()), b = planOf(freshProject());
  assert.deepEqual(a.sessions, b.sessions);
});

test('ticking never moves the plan; re-planning keeps ticks and files misses', function () {
  var p = sampleProject();
  var plan = planOf(p);
  var before = JSON.stringify(plan.sessions);
  var todays = plan.sessions.filter(function (se) { return se.day === TODAY; });
  M.tick(p, plan, todays[0].id, TODAY, true);
  assert.equal(JSON.stringify(planOf(p).sessions), before);
  var doneBefore = p.done.length;
  var st = M.status(p, plan, TODAY);
  assert.equal(st.missed.length, 8);
  M.replan(p, plan, TODAY, 0);
  assert.equal(p.done.length, doneBefore);
  assert.equal(p.missed.length, 8);
  assert.equal(p.planFrom, TODAY);
  var plan2 = planOf(p);
  plan2.sessions.forEach(function (se) {
    assert.ok(se.day >= TODAY);
    assert.ok(!p.done.some(function (d) { return d.id === se.id; }), 'a done session is not planned again: ' + se.id);
  });
  // Today's ticked session counts against today's hours.
  var todayMin = 0;
  plan2.sessions.forEach(function (se) { if (se.day === TODAY) todayMin += se.min; });
  assert.ok(todayMin + todays[0].min <= plan2.days[0].cap);
  // A half-learnt topic carries on from where it was.
  var ks = p.done.filter(function (d) { return /^learn:fin3020-dcf-valuation:/.test(d.id); }).map(function (d) { return parseInt(d.id.split(':')[2], 10); });
  var next = plan2.sessions.filter(function (se) { return se.topic === 'fin3020-dcf-valuation' && se.kind === 'learn'; });
  assert.ok(ks.length > 0 && next.length > 0);
  assert.equal(next[0].id, 'learn:fin3020-dcf-valuation:' + (Math.max.apply(null, ks) + 1));
  assert.match(next[0].detail, new RegExp('part ' + (ks.length + 1) + ' of'));
});

test('review ratings move a topic along its ladder once you re-plan', function () {
  function nextReviewAfter(rating) {
    var p = freshProject();
    var plan = planOf(p);
    var first = plan.sessions.filter(function (se) { return se.kind === 'review' && se.topic === 'eco3112-heuristics-and-biases'; })[0];
    // Tick everything up to and including that review's day, rating that review.
    plan.sessions.forEach(function (se) { if (se.day <= first.day) M.tick(p, plan, se.id, se.day, true); });
    M.rate(p, plan, first.id, first.day, rating);
    M.replan(p, plan, first.day + 1, 0);
    var again = planOf(p).sessions.filter(function (se) { return se.kind === 'review' && se.topic === first.topic; })[0];
    return again.day - first.day;
  }
  assert.equal(nextReviewAfter(1), 1, 'shaky: back the next day');
  assert.equal(nextReviewAfter(2), 3, 'OK: the usual next gap');
  assert.equal(nextReviewAfter(3), 7, 'solid: skips a step');
  var p = sampleProject();
  var plan = planOf(p);
  var st = M.status(p, plan, TODAY);
  assert.equal(st.shakyNew, 3, 'three shaky reviews in the sample since the plan was made');
  M.replan(p, plan, TODAY, 0);
  assert.equal(M.status(p, planOf(p), TODAY).shakyNew, 0, 'settled by the re-plan');
});

test('the topic tracker says where each topic stands', function () {
  var p = sampleProject();
  var plan = planOf(p);
  var rows = M.topicStatus(p, plan, TODAY);
  assert.equal(rows.length, 40);
  var by = {};
  rows.forEach(function (r) { by[r.id] = r; });
  var wacc = by['fin3020-cost-of-capital-wacc'];
  assert.equal(wacc.state, 'learning', 'its last learning part fell on the missed Saturday');
  assert.equal(wacc.learnDone, wacc.learnTotal - 1);
  assert.equal(wacc.learnMissed, 1);
  assert.deepEqual(wacc.ratings, [1, 2], 'its first review was shaky, the second OK');
  assert.equal(by['fin3020-dividend-policy'].state, 'reviewing');
  var counts = {};
  rows.forEach(function (r) { counts[r.state] = (counts[r.state] || 0) + 1; });
  assert.ok(counts['not started'] > 0 && counts.learning > 0 && counts.reviewing > 0);
  rows.forEach(function (r) { if (r.next) assert.ok(r.next.day >= TODAY); });
});

test('on track, behind, tight and short, with what to drop', function () {
  var p = sampleProject();
  var plan = planOf(p);
  var st = M.status(p, plan, TODAY);
  assert.deepEqual(st.exams.map(function (r) { return r.verdict; }), ['behind', 'behind', 'behind', 'tight', 'tight']);
  M.replan(p, plan, TODAY, 0);
  plan = planOf(p);
  st = M.status(p, plan, TODAY);
  var dat = st.exams[4];
  assert.equal(dat.verdict, 'short');
  assert.ok(dat.quick.length >= 1);
  assert.ok(dat.quickSaves >= 50);
  assert.equal(dat.extraSessions, 1);
  assert.ok(dat.extraDays > 20);
  // Taking the suggestion makes the learning fit.
  p.topics.forEach(function (t) { if (dat.quick.indexOf(t.id) >= 0) t.mode = 'quick'; });
  plan = planOf(p);
  st = M.status(p, plan, TODAY);
  assert.notEqual(st.exams[4].verdict, 'short');
});

test('changing your time moves the plan round it', function () {
  var p = freshProject();
  var day = D(2026, 12, 15);
  M.setOverride(p, day, 0, 'Ill');
  var plan = planOf(p);
  assert.equal(plan.sessions.filter(function (se) { return se.day === day; }).length, 0);
  assert.equal(plan.days[day - plan.from].label, 'Ill');
});

test('odd plans: no exams, no topics, past exams, same-day exams and no revision on exam days', function () {
  var empty = M.newProject(FROM);
  var plan = planOf(empty);
  assert.equal(plan.sessions.length, 0);
  assert.match(plan.notes[0].text, /No exams yet/);
  var p = M.newProject(FROM);
  p.exams = [
    { id: '', code: 'AAA1001', name: 'Alpha', day: FROM + 20, start: 570, duration: 120, room: '', seat: '', type: '', resit: false, tbc: false, note: '' },
    { id: '', code: 'BBB1001', name: 'Beta', day: FROM + 20, start: 840, duration: 120, room: '', seat: '', type: '', resit: false, tbc: false, note: '' },
    { id: '', code: 'CCC1001', name: 'Gamma', day: FROM - 3, start: 570, duration: 120, room: '', seat: '', type: '', resit: false, tbc: false, note: '' }
  ];
  p = M.cleanProject(JSON.parse(M.projectFile(p)), FROM);
  plan = planOf(p);
  var notes = plan.notes.map(function (n) { return n.text; }).join(' ');
  assert.match(notes, /before this plan starts/);
  assert.match(notes, /Two exams on/);
  assert.match(notes, /has no topics yet/);
  var dayBefore = plan.days[19];
  assert.deepEqual(dayBefore.reserved.sort(), ['aaa1001', 'bbb1001']);
  p.topics = [{ id: '', code: 'AAA1001', name: 'One', conf: 2, size: 180, mode: 'full', note: '' }, { id: '', code: 'BBB1001', name: 'Two', conf: 4, size: 120, mode: 'quick', note: '' }];
  M.assignTopicIds(p.topics);
  p.settings.examDay = 'off';
  plan = planOf(p);
  assert.equal(plan.sessions.filter(function (se) { return se.day === FROM + 20; }).length, 0);
  var quick = plan.sessions.filter(function (se) { return se.topic === 'bbb1001-two' && se.kind === 'learn'; });
  assert.equal(quick.length, 1);
  assert.equal(quick[0].min, p.settings.reviewMin);
});

test('files out: calendar folding, CSV, text and the project round trip', function () {
  var p = sampleProject();
  var plan = planOf(p);
  var ics = M.sessionsIcs(p, plan, { name: p.name });
  assert.ok(ics.indexOf('BEGIN:VTIMEZONE') > 0);
  ics.split('\r\n').forEach(function (line) { assert.ok(Buffer.byteLength(line, 'utf8') <= 75, line); });
  assert.equal((ics.match(/BEGIN:VEVENT/g) || []).length, plan.sessions.length + plan.exams.length);
  assert.equal(M.icsFold('x'.repeat(80)), 'x'.repeat(75) + '\r\n ' + 'x'.repeat(5));
  var folded = M.icsFold('é'.repeat(40));
  folded.split('\r\n').forEach(function (l) { assert.ok(Buffer.byteLength(l, 'utf8') <= 75); });
  var csv = M.sessionsCsv(p, plan);
  assert.equal(csv.split('\r\n').length - 2, plan.sessions.length);
  var txt = M.dayText(p, plan, TODAY);
  assert.match(txt, /^Thursday 10 December 2026\n/);
  var again = M.readProject(M.projectFile(p), TODAY).project;
  assert.equal(M.projectFile(again), M.projectFile(p));
  assert.equal(M.readProject('not json', TODAY).project, null);
  assert.equal(M.readProject('{"hello":1}', TODAY).project, null);
  assert.match(M.examTemplate(), /Module code,Module title,Date/);
});

test('a Markdown checklist and reminders before each session', function () {
  var p = sampleProject();
  var plan = planOf(p);
  var md = M.checklistMarkdown(p, plan, TODAY - 1, TODAY);
  assert.match(md, /^# Alex's January exams\n/);
  assert.match(md, /## Wednesday 9 December 2026\n\n- \[x\] 11:15-11:40 MGT3104 Dynamic capabilities \(review\)/);
  assert.match(md, /## Thursday 10 December 2026\n\n- \[ \] 09:00-09:25 MGT3104 Blue ocean strategy/);
  var all = M.checklistMarkdown(p, plan);
  assert.equal((all.match(/^- \[[ x]\]/gm) || []).length, plan.sessions.length);
  assert.equal((all.match(/^- \*\*Exam\*\*/gm) || []).length, 5);
  var ics = M.sessionsIcs(p, plan, { fromDay: TODAY, toDay: TODAY, alarm: 10, exams: false });
  assert.equal((ics.match(/TRIGGER:-PT10M/g) || []).length, 4);
  assert.equal(M.sessionsIcs(p, plan, { fromDay: TODAY, toDay: TODAY, exams: false }).indexOf('VALARM'), -1);
});

test('checks catch the slips that make a bad plan', function () {
  var p = M.newProject(FROM);
  function ex(code, day, start, dur) { return { id: '', code: code, name: 'Module ' + code, day: day, start: start, duration: dur, room: '', seat: '', type: '', resit: false, tbc: false, note: '' }; }
  p.exams = [ex('AAA1001', FROM + 20, 120, 120), ex('BBB1001', FROM + 22, 570, 400), ex('CCC1001', FROM + 22, 600, 90), ex('DDD1001', FROM + 400, 570, 20), ex('EEE1001', FROM + 30, 570, 120)];
  for (var k = 0; k < 6; k++) p.topics.push({ id: '', code: 'AAA1001', name: 'T' + k, conf: 3, size: 180, mode: 'full', note: '' });
  p.topics.push({ id: '', code: 'BBB1001', name: 'Huge', conf: 2, size: 3000, mode: 'full', note: '' });
  p.week = p.week.map(function (w, i) { return { from: w.from, to: w.to, minutes: i === 0 ? 720 : 0 }; });
  p = M.cleanProject(JSON.parse(M.projectFile(p)), FROM);
  var text = M.checkInputs(p, M.buildPlan(p), FROM).map(function (c) { return c.level + ': ' + c.text; });
  var all = text.join('\n');
  assert.match(text[0], /^error/, 'errors come first');
  assert.match(all, /AAA1001 Module AAA1001 starts at 02:00\. Check it is not meant to be 14:00/);
  assert.match(all, /BBB1001 Module BBB1001 lasts 6 h 40 min, which is long for an exam/);
  assert.match(all, /DDD1001 .* more than eight months away/);
  assert.match(all, /DDD1001 .* lasts only 20 min/);
  assert.match(all, /BBB1001 and CCC1001 overlap/);
  assert.match(all, /EEE1001 Module EEE1001 has no topics/);
  assert.match(all, /Every AAA1001 topic is rated 3/);
  assert.match(all, /"Huge" \(BBB1001\) is sized at 50 h/);
  assert.match(all, /Mondays are set to 11 h/, 'the twelve hours asked for are held to the eleven-hour window');
  var tight = M.newProject(FROM);
  tight.exams = [ex('FFF1001', FROM + 4, 570, 120)];
  tight.topics = [{ id: '', code: 'FFF1001', name: 'Everything', conf: 1, size: 2400, mode: 'full', note: '' }];
  tight = M.cleanProject(JSON.parse(M.projectFile(tight)), FROM);
  assert.match(M.checkInputs(tight, M.buildPlan(tight), FROM)[0].text, /^The time is not there: the rules ask for 65\.7 h more/);
  assert.deepEqual(M.checkInputs(freshProject(), planOf(freshProject()), FROM), [], 'the sample has nothing to fix');
});

test('how you keep to the plan, by weekday', function () {
  var p = sampleProject();
  var ad = M.adherence(p, planOf(p), TODAY);
  assert.equal(ad.days, 10);
  assert.equal(ad.pct, 89);
  assert.equal(ad.done, 2275);
  assert.equal(ad.weekdays[5].pct, 0, 'the missed Saturday');
  assert.equal(ad.weekdays[5].suggest, null, 'one Saturday is not enough to suggest a change');
  // Miss a second Saturday and the app suggests planning what Alex really does.
  var later = D(2026, 12, 13);
  var q = M.readProject(data('sample-project.json'), later).project;
  var plan = planOf(q);
  plan.sessions.forEach(function (se) { if (se.day >= TODAY && se.day < later && se.day !== D(2026, 12, 12)) M.tick(q, plan, se.id, se.day, true); });
  var ad2 = M.adherence(q, plan, later);
  assert.equal(ad2.weekdays[5].days, 2);
  assert.equal(ad2.weekdays[5].suggest, 0);
});

test('a large plan stays quick', function () {
  var p = M.newProject(FROM);
  for (var i = 0; i < 12; i++) {
    p.exams.push({ id: '', code: 'BIG' + (1000 + i), name: 'Module ' + i, day: FROM + 60 + i * 3, start: 570, duration: 120, room: '', seat: '', type: '', resit: false, tbc: false, note: '' });
    for (var k = 0; k < 40; k++) p.topics.push({ id: '', code: 'BIG' + (1000 + i), name: 'Topic ' + k, conf: 1 + (k % 5), size: [60, 120, 180, 300][k % 4], mode: 'full', note: '' });
  }
  p = M.cleanProject(JSON.parse(M.projectFile(p)), FROM);
  var t0 = Date.now();
  var plan = M.buildPlan(p);
  var ms = Date.now() - t0;
  assert.ok(plan.sessions.length > 500);
  assert.ok(ms < 5000, 'took ' + ms + ' ms');
});
