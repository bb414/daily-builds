/* Exam season: the interface. Everything that decides anything lives in the
   model (ExamSeason); this file reads files, draws the views and keeps the
   project in the browser. */
(function () {
  'use strict';

  var M = ExamSeason;
  var SAMPLES = JSON.parse(document.getElementById('samples').textContent);
  var STORE = 'exam-season-project-v1';
  var VIEWS = ['exams', 'time', 'plan', 'progress', 'topics', 'rules'];
  var KIND_LETTER = { learn: 'learn', review: 'review', paper: 'paper', final: 'final' };

  var state = {
    project: null, plan: null, status: null, summary: null, today: 0, view: 'plan', selected: null, planMode: 'calendar', topicFilter: { code: '', state: '' },
    weekStart: null, alarm: 0,
    isSample: true, imports: { exams: null, topics: null, calendar: null, availability: null }, restored: false
  };

  // ------------------------------------------------------------------
  // Small helpers
  // ------------------------------------------------------------------

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function realToday() {
    var d = new Date();
    return M.dayFromYmd(d.getFullYear(), d.getMonth() + 1, d.getDate());
  }

  function nowMinutes() {
    var d = new Date();
    return d.getHours() * 60 + d.getMinutes();
  }

  function hoursText(min) { return M.fmtHours(min); }

  var toastTimer = null;
  function toast(msg) {
    var t = $('#toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove('show'); }, 2600);
  }

  function download(name, text, type) {
    var blob = new Blob([text], { type: type || 'text/plain;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1000);
  }

  function copyText(text, done) {
    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      ta.remove();
      done(ok);
    }
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { done(true); }, fallback);
        return;
      }
    } catch (e) { /* fall through */ }
    fallback();
  }

  function readFile(file, cb) {
    var r = new FileReader();
    r.onload = function () { cb(String(r.result || '')); };
    r.onerror = function () { cb(null); };
    r.readAsText(file);
  }

  function slugDate(day) { return M.isoDay(day); }

  // ------------------------------------------------------------------
  // Storage (a convenience only; the project file is the real save)
  // ------------------------------------------------------------------

  function persist() {
    if (state.isSample) return;
    try { localStorage.setItem(STORE, M.projectFile(state.project)); } catch (e) { /* storage blocked */ }
  }

  function restore() {
    try {
      var text = localStorage.getItem(STORE);
      if (!text) return null;
      var r = M.readProject(text, realToday());
      return r.project;
    } catch (e) { return null; }
  }

  function forget() {
    try { localStorage.removeItem(STORE); } catch (e) { /* storage blocked */ }
  }

  // ------------------------------------------------------------------
  // Project life cycle
  // ------------------------------------------------------------------

  function loadSample() {
    var r = M.readProject(SAMPLES.project, realToday());
    state.project = r.project;
    state.isSample = true;
    state.imports = { exams: null, topics: null, calendar: null, availability: null };
    state.selected = null;
    recompute();
  }

  function setOwn(project) {
    state.project = project;
    state.isSample = false;
    state.selected = null;
    recompute();
    persist();
  }

  function recompute() {
    var p = state.project;
    state.today = p.asOf !== null ? p.asOf : realToday();
    state.plan = M.buildPlan(p);
    state.status = M.status(p, state.plan, state.today);
    state.summary = M.summary(p, state.plan, state.status);
  }

  // Something the plan depends on changed. Once a plan is under way the
  // change re-plans from today, so what is ticked stays ticked.
  function changed(msg) {
    var p = state.project;
    if (p.planFrom < state.today) {
      M.replan(p, state.plan, state.today, 0);
    } else if (p.planFrom > state.today && !p.done.length) {
      // a plan that has not started yet keeps its start day
    }
    if (state.isSample) state.isSample = false;
    recompute();
    persist();
    renderAll();
    if (msg) toast(msg);
  }

  // A light change (a tick) that does not move the plan.
  function ticked() {
    if (state.isSample) state.isSample = false;
    state.status = M.status(state.project, state.plan, state.today);
    state.summary = M.summary(state.project, state.plan, state.status);
    persist();
    renderAll();
  }

  function startOwn() {
    var today = realToday();
    var p = M.newProject(today);
    p.name = 'My revision plan';
    state.imports = { exams: null, topics: null, calendar: null, availability: null };
    setOwn(p);
    state.view = 'exams';
    renderAll();
    var ta = $('#exam-text');
    if (ta) ta.focus();
    toast('A blank plan: start by loading your exam timetable.');
  }

  function calendarHorizon() {
    var p = state.project;
    var last = null;
    p.exams.forEach(function (e) { if (e.day !== null && (last === null || e.day > last)) last = e.day; });
    var from = Math.min(p.planFrom, state.today) - 7;
    var to = last === null ? state.today + 365 : last + 7;
    return [from, Math.max(to, state.today + 60)];
  }

  function addSource(kind, name, res) {
    var p = state.project;
    p.sources = p.sources.filter(function (s) { return !(s.kind === kind && s.name === name); });
    if (kind === 'exams' || kind === 'availability') p.sources = p.sources.filter(function (s) { return s.kind !== kind; });
    p.sources.push({ kind: kind, name: name || 'pasted text', summary: M.importSummary(kind, res) });
  }

  function ensureOwn() {
    if (state.isSample) {
      // Importing your own data starts a fresh project, so nothing of the sample is mixed in.
      var p = M.newProject(realToday());
      state.project = p;
      state.isSample = false;
    }
  }

  function importExams(text, name) {
    if (text === null) { state.imports.exams = { name: name, messages: [{ level: 'error', text: 'The file could not be read.' }], count: 0 }; renderAll(); return; }
    var res = M.readExams(text, { ref: state.isSample ? realToday() : state.today });
    state.imports.exams = { name: name || 'pasted text', messages: res.messages, count: res.exams.length, format: res.format };
    if (!res.exams.length) { renderAll(); return; }
    ensureOwn();
    var p = state.project;
    p.exams = res.exams.map(function (e) { return { id: e.id, code: e.code, name: e.name, day: e.day, start: e.start, duration: e.duration, room: e.room, seat: e.seat, type: e.type, resit: e.resit, tbc: e.tbc, note: e.note }; });
    addSource('exams', name, res);
    state.project = M.cleanProject(JSON.parse(M.projectFile(p)), realToday());
    changed('Read ' + res.exams.length + ' exams.');
  }

  function importTopics(text, name, replace) {
    if (text === null) { state.imports.topics = { name: name, messages: [{ level: 'error', text: 'The file could not be read.' }], count: 0 }; renderAll(); return; }
    var exams = state.isSample ? [] : state.project.exams;
    var res = M.readTopics(text, { exams: exams });
    state.imports.topics = { name: name || 'pasted text', messages: res.messages, count: res.topics.length, format: res.format };
    if (!res.topics.length) { renderAll(); return; }
    ensureOwn();
    var p = state.project;
    var kept = replace ? [] : p.topics.slice();
    var seen = {};
    kept.forEach(function (t) { seen[t.code + '|' + t.name.toLowerCase()] = true; });
    var added = 0;
    res.topics.forEach(function (t) {
      var key = t.code + '|' + t.name.toLowerCase();
      if (seen[key]) return;
      seen[key] = true;
      kept.push({ id: '', code: t.code, name: t.name, conf: t.conf, size: t.size, mode: t.mode, note: t.note });
      added++;
    });
    p.topics = kept;
    M.assignTopicIds(p.topics);
    addSource('topics', name, res);
    changed((replace ? 'Replaced your topics: ' : 'Added ') + added + ' topics.');
  }

  function importCalendar(text, name) {
    if (text === null) { state.imports.calendar = { name: name, messages: [{ level: 'error', text: 'The file could not be read.' }] }; renderAll(); return; }
    var h = calendarHorizon();
    var res = M.readBusy(text, h[0], h[1]);
    state.imports.calendar = { name: name || 'calendar', messages: res.messages, count: res.busy.length };
    if (!res.busy.length && !res.allDay.length) { renderAll(); return; }
    ensureOwn();
    var p = state.project;
    var seen = {};
    p.busy.forEach(function (b) { seen[b.day + '|' + b.start + '|' + b.end + '|' + b.label] = true; });
    res.busy.forEach(function (b) {
      var k = b.day + '|' + b.start + '|' + b.end + '|' + b.label;
      if (!seen[k]) { seen[k] = true; p.busy.push(b); }
    });
    var seenA = {};
    p.allDay.forEach(function (b) { seenA[b.day + '|' + b.label] = true; });
    res.allDay.forEach(function (b) { if (!seenA[b.day + '|' + b.label]) { seenA[b.day + '|' + b.label] = true; p.allDay.push(b); } });
    addSource('calendar', name, res);
    state.project = M.cleanProject(JSON.parse(M.projectFile(p)), realToday());
    changed('Added ' + res.busy.length + ' busy times from ' + (name || 'the calendar') + '.');
  }

  function importAvailability(text, name) {
    if (text === null) { state.imports.availability = { name: name, messages: [{ level: 'error', text: 'The file could not be read.' }] }; renderAll(); return; }
    var res = M.readAvailability(text, state.project.week);
    state.imports.availability = { name: name || 'availability', messages: res.messages };
    if (!res.rows) { renderAll(); return; }
    ensureOwn();
    var p = state.project;
    p.week = res.week;
    p.overrides = res.overrides;
    addSource('availability', name, res);
    state.project = M.cleanProject(JSON.parse(M.projectFile(p)), realToday());
    changed('Read your week and ' + res.overrides.length + ' dated changes.');
  }

  function openProjectText(text, name) {
    if (text === null) { toast('That file could not be read.'); return; }
    var r = M.readProject(text, realToday());
    if (!r.project) {
      state.imports.exams = { name: name, messages: r.messages, count: 0 };
      state.view = 'exams';
      renderAll();
      toast(r.messages[0].text);
      return;
    }
    state.imports = { exams: null, topics: null, calendar: null, availability: null };
    setOwn(r.project);
    state.view = state.project.done.length ? 'progress' : 'plan';
    renderAll();
    toast('Opened ' + (name || 'the plan') + '.');
  }

  // ------------------------------------------------------------------
  // Rendering: hero, stickers, banner
  // ------------------------------------------------------------------

  function examColour(code) {
    var plan = state.plan;
    for (var i = 0; i < plan.exams.length; i++) if (plan.exams[i].code === code) return plan.exams[i].colour;
    var codes = [];
    state.project.exams.forEach(function (e) { if (codes.indexOf(e.code) < 0) codes.push(e.code); });
    var k = codes.indexOf(code);
    return k < 0 ? 5 : k % 6;
  }

  var HL = ['#ffe74a', '#ff86bd', '#82e297', '#72d0f3', '#ffad55', '#bba2ff'];

  function renderHero() {
    var plan = state.plan, today = state.today;
    var focus = null;
    plan.exams.forEach(function (e) { if (focus === null && e.day >= today) focus = e.day; });
    if (focus === null) focus = plan.exams.length ? plan.exams[0].day : today;
    var ymd = M.ymdFromDay(focus);
    $('#hero-month').textContent = M.MONTHS[ymd[1] - 1] + ' ' + ymd[0];
    var first = M.dayFromYmd(ymd[0], ymd[1], 1), dim = M.daysInMonth(ymd[0], ymd[1]);
    var lead = M.weekday(first);
    var rows = Math.ceil((lead + dim) / 7);
    var x0 = 66, y0 = 96, cw = 52.5, ch = Math.min(46, 262 / rows);
    var byDay = {};
    plan.sessions.forEach(function (s) { (byDay[s.day] = byDay[s.day] || []).push(s); });
    var examOn = {};
    plan.exams.forEach(function (e) { (examOn[e.day] = examOn[e.day] || []).push(e); });
    var parts = [];
    ['M', 'T', 'W', 'T', 'F', 'S', 'S'].forEach(function (w, i) {
      parts.push('<text x="' + (x0 + i * cw + cw / 2) + '" y="' + (y0 - 2) + '" text-anchor="middle" font-size="10" fill="#12708f" font-weight="700">' + w + '</text>');
    });
    for (var d = 0; d < dim; d++) {
      var day = first + d, idx = lead + d;
      var cx = x0 + (idx % 7) * cw, cy = y0 + 6 + Math.floor(idx / 7) * ch;
      parts.push('<rect x="' + cx + '" y="' + cy + '" width="' + (cw - 3) + '" height="' + (ch - 3) + '" fill="none" stroke="#c6e4ee" stroke-width="1"/>');
      var codes = [];
      (byDay[day] || []).forEach(function (s) { if (codes.indexOf(s.code) < 0) codes.push(s.code); });
      codes.slice(0, 3).forEach(function (c, k) {
        parts.push('<rect x="' + (cx + 4) + '" y="' + (cy + 15 + k * 7) + '" width="' + (cw - 12) + '" height="5.5" rx="2.5" fill="' + HL[examColour(c)] + '" transform="skewX(-12)" style="transform-box:fill-box"/>');
      });
      parts.push('<text x="' + (cx + 4) + '" y="' + (cy + 11) + '" font-size="9.5" fill="' + (day === today ? '#1d2141' : '#5b6b80') + '"' + (day === today ? ' font-weight="700"' : '') + '>' + (d + 1) + '</text>');
      if (examOn[day]) {
        var e = examOn[day][0];
        parts.push('<ellipse cx="' + (cx + cw / 2 - 1) + '" cy="' + (cy + ch / 2) + '" rx="' + (cw / 2 - 1) + '" ry="' + (ch / 2 - 2) + '" fill="#fff" fill-opacity=".85" stroke="#d2352b" stroke-width="2.2" transform="rotate(-6 ' + (cx + cw / 2) + ' ' + (cy + ch / 2) + ')"/>');
        parts.push('<text x="' + (cx + cw / 2 - 1) + '" y="' + (cy + ch / 2 + 4) + '" text-anchor="middle" font-family="Shantell Sans, cursive" font-weight="800" font-size="11" fill="#d2352b">' + esc(e.code.replace(/[0-9]+/, '')) + '</text>');
      }
      if (day === today) parts.push('<rect x="' + (cx - 1) + '" y="' + (cy - 1) + '" width="' + (cw - 1) + '" height="' + (ch - 1) + '" fill="none" stroke="#1d2141" stroke-width="2.5" rx="2"/>');
    }
    $('#hero-grid').innerHTML = parts.join('');
    var next = state.summary.next;
    $('#hero-count').textContent = next ? String(next.daysLeft) : '0';
    $('#hero-count-label').textContent = next ? (next.daysLeft === 1 ? 'DAY' : 'DAYS') + ' · ' + next.code : 'NO EXAMS';
    $('#hero-card-code').textContent = 'TODAY · ' + M.fmtShort(today).toUpperCase();
    var lines = state.status.todaySessions.slice(0, 4).map(function (s, i) {
      var done = isDone(s.id);
      var title = (s.kind === 'paper' ? s.code + ' past paper' : s.title);
      if (title.length > 21) title = title.slice(0, 20) + '…';
      return '<text x="10" y="' + (38 + i * 18) + '"' + (done ? ' text-decoration="line-through" fill="#6b6f84"' : '') + '>' + (done ? '✓ ' : '') + esc(title) + '</text>';
    });
    if (!lines.length) lines = ['<text x="10" y="38">Nothing planned</text>'];
    $('#hero-card-lines').innerHTML = lines.join('');
    var years = {};
    plan.exams.forEach(function (e) { years[M.ymdFromDay(e.day)[0]] = true; });
    var ys = Object.keys(years).sort();
    $('#kicker-year').textContent = ys.length ? 'Exams ' + ys.join('/') : 'Exams';
  }

  function isDone(id) {
    var d = state.project.done;
    for (var i = 0; i < d.length; i++) if (d[i].id === id) return true;
    return false;
  }

  function verdictLabel(v) {
    return { ok: 'On track', tight: 'Tight', behind: 'Behind', short: 'Not enough time', sat: 'Done', today: 'Exam today' }[v] || v;
  }

  function renderStickers() {
    var st = state.status, html = [];
    st.exams.forEach(function (r, i) {
      var tilt = [-4, 3, -2, 4, -3, 2][i % 6];
      if (r.verdict === 'sat') {
        html.push('<div class="sticker sat m' + r.colour + '" style="--tilt:' + tilt + 'deg"><div><span class="n">done</span><span class="c">' + esc(r.code) + '</span><span class="dt">' + esc(M.fmtShort(r.day)) + '</span></div></div>');
        return;
      }
      var n = r.daysLeft;
      html.push('<div class="sticker m' + r.colour + '" style="--tilt:' + tilt + 'deg" title="' + esc(r.code + ' ' + r.name + ', ' + M.fmtDay(r.day) + ' at ' + M.fmtTime(r.start)) + '"><div>' +
        '<span class="n">' + (n === 0 ? 'today' : n) + '</span><span class="u">' + (n === 0 ? 'exam' : n === 1 ? 'day to' : 'days to') + '</span>' +
        '<span class="c">' + esc(r.code) + '</span><span class="dt">' + esc(M.fmtShort(r.day)) + '</span></div></div>');
    });
    var sm = state.summary;
    var todayLine = sm.todayCount ? sm.todayCount + (sm.todayCount === 1 ? ' session, ' : ' sessions, ') + M.fmtDur(sm.todayMin) : 'Nothing planned';
    html.push('<div class="card today-card taped pinned plain" style="--tape:repeating-linear-gradient(45deg,#ff9fcb 0 6px,#ffd0e5 6px 12px)"><div class="card-head"><h3>' + esc(M.fmtLong(state.today)) + '</h3>' +
      (state.plan.exams.length ? '<span class="verdict ' + st.verdict + '">' + verdictLabel(st.verdict) + '</span>' : '') + '</div><div class="card-body">' +
      '<div class="big-fig">' + esc(todayLine) + '</div><div class="small muted">' + (sm.todayCount ? M.fmtDur(sm.todayDone) + ' ticked off so far. ' : '') +
      '<button type="button" class="btn-link" data-go="progress">See today and tick off</button></div></div></div>');
    if (!st.exams.length) html.unshift('<div class="sticky" style="max-width:420px">No exams yet. Load your exam timetable under <b>Exams and topics</b> and the countdown appears here.</div>');
    $('#stickers').innerHTML = html.join('');
  }

  function renderBanner() {
    var b = $('#banner'), p = state.project;
    if (state.isSample) {
      b.innerHTML = '<div class="note-strip"><span>You are looking at an <b>invented</b> final-year student\'s plan: five January exams, 40 topics, lectures, cafe shifts and rugby, planned from ' +
        esc(M.fmtShort(p.planFrom)) + ' and ticked off for ten days (one day missed), as if today were <b>' + esc(M.fmtDay(state.today)) + '</b>.</span>' +
        '<span class="btn-row"><button type="button" class="btn btn-small btn-marker" data-action="start-own">Use your own timetable</button>' +
        '<button type="button" class="btn btn-small" data-action="try-messy">Try a messy pasted timetable</button></span></div>';
    } else if (state.restored) {
      b.innerHTML = '<div class="note-strip"><span>Welcome back: this is your plan as you left it in this browser. Save the plan file now and then to keep it safe.</span>' +
        '<span class="btn-row"><button type="button" class="btn btn-small" data-action="save-project">Save plan file</button><button type="button" class="btn btn-small" data-action="show-sample">Show the sample instead</button></span></div>';
    } else {
      b.innerHTML = '';
    }
  }

  // ------------------------------------------------------------------
  // View 1: exams and topics
  // ------------------------------------------------------------------

  function notesHtml(list) {
    if (!list || !list.length) return '';
    return '<ul class="notes">' + list.map(function (m) { return '<li class="' + esc(m.level) + '">' + esc(m.text) + '</li>'; }).join('') + '</ul>';
  }

  function importReport(imp, what) {
    if (!imp) return '';
    var head = imp.count ? [{ level: 'ok', text: 'Read ' + imp.count + ' ' + what + (imp.count === 1 ? '' : 's') + ' from ' + imp.name + '.' }] : [];
    return notesHtml(head.concat(imp.messages));
  }

  function renderExams() {
    var p = state.project, plan = state.plan;
    var h = [];
    h.push('<div class="view-head"><div><h2>Exams and topics</h2><p class="intro">Load your exam timetable and list what each exam covers, with how confident you feel (1 is weak, 5 is strong) and how big each topic is. Weak and big topics are planned first.</p></div>' +
      '<div class="btn-row"><button type="button" class="btn btn-small" data-action="save-project">Save plan file</button><button type="button" class="btn btn-small" data-action="open-project">Open a plan file</button></div></div>');
    h.push('<div class="cols">');
    h.push('<div class="card taped plain"><div class="card-head"><h3>Your exam timetable</h3><span class="tag">CSV, web page, pasted or .ics</span></div><div class="card-body">' +
      '<div class="drop" data-drop="exams"><p class="drop-title">Drop the file here, or paste the table</p>' +
      '<p class="formats">A student-portal export (CSV or TSV), the timetable page saved from your browser (.html), a table copied from a web page or PDF, loose lines such as "ECO3112 Behavioural Economics 13/01/2027 14:00 2h", or your personal exam calendar (.ics). UK, US and ISO dates, "TBC" dates, rooms and repeated headers are all fine.</p>' +
      '<label for="exam-text" class="visually-hidden">Paste your exam timetable</label><textarea id="exam-text" placeholder="Module code, Title, Date, Start time, Duration, Room"></textarea>' +
      '<div class="btn-row" style="margin-top:10px"><button type="button" class="btn btn-small btn-marker" data-action="read-exams">Read the timetable</button>' +
      '<span class="btn btn-small file-btn">Choose a file<input type="file" id="exam-file" accept=".csv,.tsv,.txt,.ics,.html,.htm,text/csv,text/calendar,text/plain,text/html" aria-label="Choose an exam timetable file"></span>' +
      '<button type="button" class="btn-link" data-action="template-exams">CSV template</button><button type="button" class="btn-link" data-action="try-messy">Try a messy paste</button></div>' +
      importReport(state.imports.exams, 'exam') + '</div></div></div>');
    h.push('<div class="card taped plain" style="--tape:repeating-linear-gradient(90deg,#ffe36b 0 8px,#fff3a6 8px 14px)"><div class="card-head"><h3>Your topics</h3><span class="tag">List or CSV</span></div><div class="card-body">' +
      '<div class="drop" data-drop="topics"><p class="drop-title">Paste a list, or drop a CSV</p>' +
      '<p class="formats">One topic per line under a module heading, with confidence and size in brackets: "Prospect theory (2, L)". Sizes are S, M, L or hours ("3h"). Or a CSV with Module, Topic, Confidence and Size columns.</p>' +
      '<label for="topic-text" class="visually-hidden">Paste your topics</label><textarea id="topic-text" placeholder="ECO3112 Behavioural Economics&#10;- Prospect theory (2, L)&#10;- Mental accounting (3, M)"></textarea>' +
      '<div class="btn-row" style="margin-top:10px"><button type="button" class="btn btn-small btn-marker" data-action="read-topics">Add these topics</button>' +
      '<button type="button" class="btn btn-small" data-action="replace-topics">Replace all topics</button>' +
      '<span class="btn btn-small file-btn">Choose a file<input type="file" id="topic-file" accept=".csv,.tsv,.txt,text/csv,text/plain" aria-label="Choose a topics file"></span>' +
      '<button type="button" class="btn-link" data-action="template-topics">CSV template</button><button type="button" class="btn-link" data-action="try-list">Try a pasted list</button></div>' +
      importReport(state.imports.topics, 'topic') + '</div></div></div>');
    h.push('</div>');

    // The exams, editable.
    h.push('<h3 style="margin-top:30px">Exams <span class="muted small" style="font-family:var(--body);font-weight:400">' + p.exams.length + ' listed</span></h3>');
    if (!p.exams.length) {
      h.push('<p class="sticky" style="max-width:520px">No exams yet. Paste or load your timetable above, or add one by hand below.</p>');
    } else {
      h.push('<div class="exam-list"><div class="exam-row head"><span>Module</span><span>Title</span><span>Date</span><span>Start</span><span>Length</span><span class="room-cell">Room</span><span></span></div>');
      p.exams.forEach(function (e, i) {
        var cls = 'exam-row m' + examColour(e.code) + (e.day === null ? ' tbc' : '') + (e.day !== null && e.day < state.today ? ' past' : '');
        var label = e.code + ' ' + e.name;
        h.push('<div class="' + cls + '"><span class="code">' + esc(e.code) + (e.resit ? ' <span class="tag">resit</span>' : '') + '</span>' +
          '<span class="name-cell"><input type="text" value="' + esc(e.name) + '" data-exam="' + i + '" data-field="name" aria-label="Title of ' + esc(e.code) + '"></span>' +
          '<span><input type="date" value="' + (e.day === null ? '' : M.isoDay(e.day)) + '" data-exam="' + i + '" data-field="day" aria-label="Date of ' + esc(label) + '">' + (e.day === null ? '<span class="tag red">date TBC</span>' : '') + '</span>' +
          '<span><input type="time" value="' + M.fmtTime(e.start) + '" data-exam="' + i + '" data-field="start" aria-label="Start time of ' + esc(label) + '"></span>' +
          '<span><input type="number" min="15" max="1440" step="15" value="' + e.duration + '" data-exam="' + i + '" data-field="duration" aria-label="Length in minutes of ' + esc(label) + '"></span>' +
          '<span class="room-cell"><input type="text" value="' + esc(e.room) + '" data-exam="' + i + '" data-field="room" aria-label="Room for ' + esc(label) + '" placeholder="Room"></span>' +
          '<span class="del-cell"><button type="button" class="btn-x" data-action="del-exam" data-i="' + i + '" aria-label="Remove ' + esc(label) + '">×</button></span></div>');
      });
      h.push('</div>');
    }
    h.push('<form class="field-row" data-form="add-exam" style="margin-top:14px"><div class="field"><label for="ne-code">Module code</label><input type="text" id="ne-code" placeholder="ABC1234" size="10" required></div>' +
      '<div class="field"><label for="ne-name">Title</label><input type="text" id="ne-name" placeholder="Module title"></div>' +
      '<div class="field"><label for="ne-day">Date</label><input type="date" id="ne-day"></div>' +
      '<div class="field"><label for="ne-start">Start</label><input type="time" id="ne-start" value="09:30"></div>' +
      '<div class="field"><label for="ne-dur">Minutes</label><input type="number" id="ne-dur" value="120" min="15" max="1440" step="15" style="width:90px"></div>' +
      '<button type="submit" class="btn btn-small">Add exam</button></form>');

    // Topics by module.
    var codes = [];
    p.exams.forEach(function (e) { if (codes.indexOf(e.code) < 0) codes.push(e.code); });
    p.topics.forEach(function (t) { if (codes.indexOf(t.code) < 0) codes.push(t.code); });
    h.push('<h3 style="margin-top:34px">Topics <span class="muted small" style="font-family:var(--body);font-weight:400">' + p.topics.length + ' in ' + codes.length + ' modules</span></h3>');
    h.push('<p class="small muted" style="max-width:60em">First learning time = size × a confidence factor (1: 150%, 2: 125%, 3: 100%, 4: 75%, 5: 50%), in ' + p.settings.learnMin + '-minute sessions. "Quick" gives a topic one short look and one review instead; "Drop" leaves it out.</p>');
    h.push('<div class="module-cards">');
    var s = p.settings;
    codes.forEach(function (code) {
      var ex = null;
      p.exams.forEach(function (e) { if (e.code === code && ex === null) ex = e; });
      var list = [];
      p.topics.forEach(function (t, i) { if (t.code === code) list.push([t, i]); });
      var mins = 0;
      list.forEach(function (x) { if (x[0].mode !== 'drop') mins += M.learnSessions(x[0], s) * M.learnLength(x[0], s); });
      h.push('<div class="card mod taped m' + examColour(code) + '"><div class="card-head"><div><h3>' + esc(code) + ' ' + esc(ex ? ex.name : '') + '</h3><div class="small muted">' +
        (ex ? (ex.day === null ? 'Exam date to be confirmed' : 'Exam ' + esc(M.fmtDay(ex.day)) + ' at ' + M.fmtTime(ex.start)) : '<span class="tag red">no exam for this module</span>') + '</div></div>' +
        '<div class="hours" title="First learning, before reviews">' + list.length + ' topics<br>' + hoursText(mins) + ' to learn</div></div><div class="card-body">');
      if (!list.length) h.push('<p class="small muted">No topics yet for this module.</p>');
      list.forEach(function (x) {
        var t = x[0], i = x[1];
        var conf = '<span class="conf c' + t.conf + '" role="group" aria-label="Confidence in ' + esc(t.name) + '">';
        for (var c = 1; c <= 5; c++) conf += '<button type="button" data-topic="' + i + '" data-conf="' + c + '" aria-pressed="' + (t.conf === c) + '" aria-label="Confidence ' + c + ' of 5">' + c + '</button>';
        conf += '</span>';
        var sizeOpts = ['XS', 'S', 'M', 'L', 'XL'].map(function (k) { var v = M.SIZES[k.toLowerCase()]; return '<option value="' + v + '"' + (t.size === v ? ' selected' : '') + '>' + k + ' (' + M.fmtDur(v) + ')</option>'; });
        if ([60, 120, 180, 300, 420].indexOf(t.size) < 0) sizeOpts.push('<option value="' + t.size + '" selected>' + M.fmtDur(t.size) + '</option>');
        var lm = t.mode === 'drop' ? 0 : M.learnSessions(t, s) * M.learnLength(t, s);
        h.push('<div class="topic-row' + (t.mode === 'drop' ? ' drop-mode' : t.mode === 'quick' ? ' quick-mode' : '') + '"><span class="tname"><input type="text" value="' + esc(t.name) + '" data-topic="' + i + '" data-field="name" aria-label="Topic name"></span>' +
          '<span class="opts">' + conf +
          ' <select data-topic="' + i + '" data-field="size" aria-label="Size of ' + esc(t.name) + '">' + sizeOpts.join('') + '</select>' +
          ' <select data-topic="' + i + '" data-field="mode" aria-label="How to plan ' + esc(t.name) + '"><option value="full"' + (t.mode === 'full' ? ' selected' : '') + '>Full</option><option value="quick"' + (t.mode === 'quick' ? ' selected' : '') + '>Quick</option><option value="drop"' + (t.mode === 'drop' ? ' selected' : '') + '>Drop</option></select>' +
          ' <span class="hours">' + (t.mode === 'drop' ? 'left out' : M.fmtDur(lm)) + '</span></span>' +
          '<span class="tdel"><button type="button" class="btn-x" data-action="del-topic" data-i="' + i + '" aria-label="Remove ' + esc(t.name) + '">×</button></span></div>');
      });
      h.push('<form class="add-topic" data-form="add-topic" data-code="' + esc(code) + '"><label class="visually-hidden" for="nt-' + esc(code) + '">New topic for ' + esc(code) + '</label><input type="text" id="nt-' + esc(code) + '" placeholder="Add a topic, e.g. Elasticity (2, M)"><button type="submit" class="btn btn-small">Add</button></form>');
      h.push('</div></div>');
    });
    h.push('</div>');
    if (p.topics.length) h.push('<p style="margin-top:18px"><button type="button" class="btn-link" data-action="clear-topics">Remove all topics</button></p>');
    $('#view-exams').innerHTML = h.join('');
  }

  // ------------------------------------------------------------------
  // View 2: your time
  // ------------------------------------------------------------------

  function renderTime() {
    var p = state.project, s = p.settings;
    var h = [];
    h.push('<div class="view-head"><div><h2>Your time</h2><p class="intro">Tell the planner when you can revise: a normal week, the days that are different, and your calendar of lectures, shifts and matches. Sessions are only placed in free time inside your window, up to your hours for the day.</p></div></div>');
    h.push('<div class="cols">');
    // Weekly template
    var wk = ['<div class="card taped plain" style="--tape:repeating-linear-gradient(45deg,#9ee8b0 0 6px,#d6f7df 6px 12px)"><div class="card-head"><h3>A normal week</h3><span class="tag">window and hours</span></div><div class="card-body">'];
    var typical = typicalBusy();
    p.week.forEach(function (w, i) {
      var bar = '<span class="window-bar" aria-hidden="true"><span style="left:' + (w.from / 14.4) + '%;width:' + ((w.to - w.from) / 14.4) + '%"></span>' +
        (typical[i] || []).map(function (b) { return '<span class="busy" style="left:' + (b[0] / 14.4) + '%;width:' + ((b[1] - b[0]) / 14.4) + '%"></span>'; }).join('') +
        '<i style="left:' + (720 / 14.4) + '%"></i></span>';
      wk.push('<div class="week-row"><span class="wd">' + M.WD3[i] + '</span>' +
        '<input type="time" value="' + M.fmtTime(Math.min(w.from, 1439)) + '" data-week="' + i + '" data-field="from" aria-label="' + M.WEEKDAYS[i] + ': earliest start">' +
        '<input type="time" value="' + M.fmtTime(Math.min(w.to, 1439)) + '" data-week="' + i + '" data-field="to" aria-label="' + M.WEEKDAYS[i] + ': latest finish">' +
        '<input type="number" min="0" max="16" step="0.5" value="' + M.tenths(w.minutes).replace(/\.0$/, '') + '" data-week="' + i + '" data-field="hours" aria-label="' + M.WEEKDAYS[i] + ': hours of revision">' + bar + '</div>');
    });
    var weekMin = 0;
    p.week.forEach(function (w) { weekMin += w.minutes; });
    wk.push('<p class="small muted" style="margin-top:8px">Up to <b class="mono">' + hoursText(weekMin) + '</b> a week. The bar shows the window from midnight to midnight; grey stripes are a typical week of your calendar.</p></div></div>');
    h.push(wk.join(''));
    // Overrides
    var ov = ['<div class="card taped plain" style="--tape:repeating-linear-gradient(90deg,#ff9fcb 0 8px,#ffd6e8 8px 14px)"><div class="card-head"><h3>Days that are different</h3><span class="tag">' + p.overrides.length + ' set</span></div><div class="card-body">'];
    ov.push('<form class="field-row" data-form="add-override"><div class="field"><label for="ov-from">From</label><input type="date" id="ov-from" required></div><div class="field"><label for="ov-to">To (optional)</label><input type="date" id="ov-to"></div>' +
      '<div class="field"><label for="ov-hours">Hours</label><input type="number" id="ov-hours" value="0" min="0" max="16" step="0.5" style="width:80px"></div><div class="field" style="flex:1"><label for="ov-label">Why</label><input type="text" id="ov-label" placeholder="Travelling home"></div>' +
      '<button type="submit" class="btn btn-small">Add</button></form><p class="hint">0 hours blocks the day. Missed a day or ill? Block it and the plan moves round it.</p>');
    var horizonFrom = Math.min(p.planFrom, state.today) - 7;
    var shown = p.overrides.filter(function (v) { return v.day >= horizonFrom; });
    shown.forEach(function (v) {
      ov.push('<div class="ov-row"><span class="d">' + esc(M.fmtDay(v.day)) + '</span><span class="mono">' + (v.minutes ? hoursText(v.minutes) : '<span class="tag red">blocked</span>') + '</span>' +
        '<span class="l">' + esc(v.label || '') + (v.from !== undefined ? ' <span class="muted small">(' + M.fmtTime(v.from) + ' to ' + M.fmtTime(Math.min(v.to === undefined ? 1440 : v.to, 1440)) + ')</span>' : '') + '</span>' +
        '<button type="button" class="btn-x" data-action="del-override" data-day="' + v.day + '" aria-label="Remove the change on ' + esc(M.fmtDay(v.day)) + '">×</button></div>');
    });
    if (!shown.length) ov.push('<p class="small muted">None yet.</p>');
    ov.push('</div></div>');
    h.push(ov.join(''));
    h.push('</div>');

    // Calendar import and availability file
    h.push('<div class="cols" style="margin-top:30px">');
    var cal = ['<div class="card taped plain"><div class="card-head"><h3>Busy times from your calendar or rota</h3><span class="tag">.ics or CSV</span></div><div class="card-body">' +
      '<div class="drop" data-drop="calendar"><p class="drop-title">Drop a calendar file or a shift rota</p><p class="formats">Your university timetable feed, or an export from Google, Apple or Outlook calendar (.ics): weekly repeats, skipped dates, moved and cancelled events are followed, and all-day entries are listed but not counted as busy. Or a rota as CSV with a date, a start and a finish (or hours) on each row; shifts past midnight carry on into the next day. Load as many as you have.</p>' +
      '<div class="btn-row"><span class="btn btn-small btn-marker file-btn">Choose a calendar or rota<input type="file" id="cal-file" accept=".ics,.csv,.tsv,.txt,text/calendar,text/csv" aria-label="Choose a calendar or rota file"></span>' +
      (p.busy.length ? '<button type="button" class="btn-link" data-action="clear-busy">Remove all busy times</button>' : '') + '</div>' + importReport(state.imports.calendar, 'busy time') + '</div>'];
    var summ = M.busySummary(p.busy.filter(function (b) { return b.day >= horizonFrom; }));
    if (summ.length) {
      cal.push('<h4>What is in your calendar</h4><ul class="busy-list">' + summ.slice(0, 12).map(function (b) {
        return '<li><span>' + esc(b.label) + '<span class="muted small"> · ' + (b.count === 1 ? 'once' : b.count + ' times') + ', ' + esc(M.fmtShort(b.first)) + (b.last !== b.first ? ' to ' + esc(M.fmtShort(b.last)) : '') + '</span></span><span class="mono small">' + hoursText(b.minutes) + '</span></li>';
      }).join('') + '</ul>' + (summ.length > 12 ? '<p class="small muted">and ' + (summ.length - 12) + ' more.</p>' : ''));
    }
    var allDay = {};
    p.allDay.forEach(function (a) { if (a.day >= state.today) (allDay[a.label] = allDay[a.label] || []).push(a.day); });
    var adKeys = Object.keys(allDay);
    if (adKeys.length) {
      cal.push('<h4>All-day entries (not counted as busy)</h4><ul class="busy-list">' + adKeys.slice(0, 8).map(function (k) {
        var ds = allDay[k];
        return '<li><span>' + esc(k) + '<span class="muted small"> · ' + esc(M.fmtShort(ds[0])) + (ds.length > 1 ? ' to ' + esc(M.fmtShort(ds[ds.length - 1])) + ' (' + ds.length + ' days)' : '') + '</span></span>' +
          '<button type="button" class="btn btn-small" data-action="block-allday" data-label="' + esc(k) + '">Block ' + (ds.length > 1 ? 'these days' : 'this day') + '</button></li>';
      }).join('') + '</ul>');
    }
    cal.push('</div></div>');
    h.push(cal.join(''));
    h.push('<div class="card taped plain" style="--tape:repeating-linear-gradient(45deg,#bba2ff 0 6px,#e3d8ff 6px 12px)"><div class="card-head"><h3>Your week as a file</h3><span class="tag">CSV</span></div><div class="card-body">' +
      '<div class="drop" data-drop="availability"><p class="drop-title">Load or save your availability</p><p class="formats">Rows of Day, From, To, Hours, Note. A day is Mon to Sun ("weekdays" and "weekends" work too) or a date or range such as "24/12/2026 - 26/12/2026". Hours of 0 or "off" block the day.</p>' +
      '<div class="btn-row"><span class="btn btn-small file-btn">Choose a file<input type="file" id="avail-file" accept=".csv,.tsv,.txt,text/csv" aria-label="Choose an availability file"></span>' +
      '<button type="button" class="btn btn-small" data-action="save-availability">Save my week as CSV</button></div>' + notesHtml(state.imports.availability && state.imports.availability.messages) + '</div></div></div>');
    h.push('</div>');

    // Settings
    h.push('<div class="card plain" style="margin-top:30px"><div class="card-head"><h3>How sessions are sized</h3><button type="button" class="btn-link" data-action="reset-settings">Back to the defaults</button></div><div class="card-body"><div class="settings-grid">' +
      setting('learnMin', 'Learning session (minutes)', s.learnMin, 15, 180, 5, 'New material, in one sitting.') +
      setting('reviewMin', 'Review session (minutes)', s.reviewMin, 10, 90, 5, 'Test yourself on a topic, then fill the gaps.') +
      setting('breakMin', 'Break between sessions (minutes)', s.breakMin, 0, 60, 5, 'Time between sessions.') +
      setting('taperDays', 'Stop new topics (days before each exam)', s.taperDays, 1, 10, 1, 'The last days are for reviews, past papers and a final review.') +
      setting('papers', 'Past papers per exam', s.papers, 0, 6, 1, 'Timed, as long as the exam (up to ' + M.fmtDur(s.paperMax) + ').') +
      setting('maxShare', 'Most of a day on one module (%)', s.maxShare, 25, 100, 5, 'Keeps modules mixed in every day.') +
      setting('busyGap', 'Gap around commitments (minutes)', s.busyGap, 0, 120, 5, 'Travel and a breather around lectures and shifts.') +
      '<div class="field"><label for="set-examDay">On an exam day</label><select id="set-examDay" data-setting="examDay"><option value="after"' + (s.examDay === 'after' ? ' selected' : '') + '>Revise after the exam, half the hours</option><option value="off"' + (s.examDay === 'off' ? ' selected' : '') + '>No revision</option><option value="normal"' + (s.examDay === 'normal' ? ' selected' : '') + '>Normal hours around the exam</option></select><span class="hint">What else happens on the day of an exam.</span></div>' +
      '<div class="field"><label for="set-planFrom">Plan starts on</label><input type="date" id="set-planFrom" value="' + M.isoDay(p.planFrom) + '" data-setting="planFrom"' + (p.done.length ? ' disabled' : '') + '><span class="hint">' + (p.done.length ? 'Fixed once you have ticked sessions off; use Re-plan instead.' : 'Usually today.') + '</span></div>' +
      '</div></div></div>');
    $('#view-time').innerHTML = h.join('');
  }

  function setting(key, label, value, min, max, step, hint) {
    return '<div class="field"><label for="set-' + key + '">' + esc(label) + '</label><input type="number" id="set-' + key + '" data-setting="' + key + '" value="' + value + '" min="' + min + '" max="' + max + '" step="' + step + '"><span class="hint">' + esc(hint) + '</span></div>';
  }

  // The busy times of the coming week laid onto weekdays, for the week bars.
  function typicalBusy() {
    var out = [[], [], [], [], [], [], []];
    var p = state.project;
    var from = state.today, to = state.today + 6;
    p.busy.forEach(function (b) { if (b.day >= from && b.day <= to) out[M.weekday(b.day)].push([b.start, b.end]); });
    return out;
  }

  // ------------------------------------------------------------------
  // View 3: the plan
  // ------------------------------------------------------------------

  function sessionsByDay() {
    var by = {};
    state.plan.sessions.forEach(function (s) { (by[s.day] = by[s.day] || []).push(s); });
    return by;
  }

  function legendHtml() {
    var h = ['<div class="legend">'];
    state.plan.exams.forEach(function (e) {
      h.push('<span class="sw m' + e.colour + '"><b></b><span class="k">' + esc(e.code) + '</span> ' + esc(e.name) + '</span>');
    });
    h.push('<span class="sw muted">Solid: learn · pale: review · striped: past paper · outlined: final review · <span style="color:var(--red);font-weight:700">circled</span>: exam</span></div>');
    return h.join('');
  }

  function renderPlan() {
    var plan = state.plan, p = state.project, sm = state.summary;
    var h = [];
    h.push('<div class="print-head"><h2>' + esc(p.name) + '</h2><span>Revision wall planner · made ' + esc(M.fmtDay(p.planFrom)) + ' · Exam season</span></div>');
    h.push('<div class="view-head"><div><h2>Your plan</h2><p class="intro">' + (plan.sessions.length ?
      plan.sessions.length + ' sessions on ' + sm.studyDays + ' days from ' + esc(M.fmtShort(plan.from)) + ' to ' + esc(M.fmtShort(plan.last)) + ': <b class="mono">' + hoursText(sm.learnMin) + '</b> learning, <b class="mono">' + hoursText(sm.reviewMin) + '</b> spaced reviews, <b class="mono">' + hoursText(sm.paperMin) + '</b> past papers and <b class="mono">' + hoursText(sm.finalMin) + '</b> final reviews. Click a day to see its sessions.'
      : 'No sessions yet. Load your exam timetable and topics under <button type="button" class="btn-link" data-go="exams">Exams and topics</button>.') + '</p></div>' +
      '<div class="plan-tools no-print"><span class="seg" role="group" aria-label="Show the plan as"><button type="button" data-mode="calendar" aria-pressed="' + (state.planMode === 'calendar') + '">Calendar</button><button type="button" data-mode="week" aria-pressed="' + (state.planMode === 'week') + '">Week</button><button type="button" data-mode="list" aria-pressed="' + (state.planMode === 'list') + '">List</button></span>' +
      '<button type="button" class="btn btn-small btn-blue" data-action="ics-all">Calendar file (.ics)</button><label class="alarm-pick"><span>Reminders</span><select id="alarm" aria-label="Reminder before each session in the calendar file"><option value="0"' + (state.alarm === 0 ? ' selected' : '') + '>none</option><option value="10"' + (state.alarm === 10 ? ' selected' : '') + '>10 min before</option><option value="30"' + (state.alarm === 30 ? ' selected' : '') + '>30 min before</option></select></label>' +
      '<button type="button" class="btn btn-small" data-action="csv">Sessions (CSV)</button><button type="button" class="btn btn-small" data-action="markdown">Checklist (.md)</button><button type="button" class="btn btn-small btn-pink" data-action="print">' + (state.planMode === 'week' ? 'Print this week' : 'Print wall planner') + '</button></div></div>');
    plan.notes.forEach(function () {});
    if (plan.notes.length) h.push(notesHtml(plan.notes.map(function (n) { return { level: n.level, text: n.text }; })));
    if (!plan.exams.length) { $('#view-plan').innerHTML = h.join(''); return; }
    h.push(legendHtml());
    var by = sessionsByDay();
    if (state.planMode === 'list') {
      h.push(listHtml(by));
      $('#view-plan').innerHTML = h.join('');
      return;
    }
    if (state.planMode === 'week') {
      h.push(weekHtml());
      $('#view-plan').innerHTML = h.join('');
      return;
    }
    if (state.selected === null || state.selected < plan.from || state.selected > plan.last) state.selected = Math.min(Math.max(state.today, plan.from), plan.last);
    h.push('<div class="cols-side"><div class="months">' + monthsHtml(by) + '</div><div class="stack day-detail no-print">' + dayDetailHtml(state.selected, by) + weekChartHtml() + '</div></div>');
    $('#view-plan').innerHTML = h.join('');
  }

  // The plan as a timetable for one week: your window, busy times, exams and
  // sessions placed by the clock.
  function weekStartFor(day) { return day - M.weekday(day); }

  function weekHtml() {
    var plan = state.plan, p = state.project;
    var first = weekStartFor(plan.from), last = weekStartFor(plan.last);
    if (state.weekStart === null || state.weekStart < first || state.weekStart > last) state.weekStart = Math.min(Math.max(weekStartFor(state.today), first), last);
    var ws = state.weekStart;
    var days = [];
    for (var i = 0; i < 7; i++) days.push(ws + i);
    var lo = 24 * 60, hi = 0;
    days.forEach(function (d) {
      var w = M.dayWindow(p, d);
      if (!w.blocked) { lo = Math.min(lo, w.from); hi = Math.max(hi, w.to); }
    });
    plan.sessions.forEach(function (se) { if (se.day >= ws && se.day < ws + 7) { lo = Math.min(lo, se.start); hi = Math.max(hi, se.end); } });
    plan.exams.forEach(function (e) { if (e.day >= ws && e.day < ws + 7) { lo = Math.min(lo, e.start); hi = Math.max(hi, e.start + e.duration); } });
    if (hi <= lo) { lo = 9 * 60; hi = 18 * 60; }
    var h0 = Math.floor(lo / 60), h1 = Math.min(24, Math.ceil(hi / 60));
    var PX = 44;
    var height = (h1 - h0) * PX;
    function y(min) { return ((min - h0 * 60) * PX / 60).toFixed(1); }
    function hgt(a, b) { return Math.max(12, (Math.min(b, h1 * 60) - Math.max(a, h0 * 60)) * PX / 60).toFixed(1); }
    var h = ['<div class="week-nav no-print"><button type="button" class="btn btn-small" data-action="week-prev"' + (ws <= first ? ' disabled' : '') + '>Previous week</button>' +
      '<b class="wk-label">Week of ' + esc(M.fmtDay(ws)) + '</b><button type="button" class="btn btn-small" data-action="week-next"' + (ws >= last ? ' disabled' : '') + '>Next week</button>' +
      '<button type="button" class="btn-link" data-action="week-this">This week</button></div>'];
    h.push('<p class="print-only">Week of ' + esc(M.fmtDay(ws)) + '</p>');
    h.push('<div class="wscroll"><div class="wgrid" style="--rows:' + (h1 - h0) + '">');
    h.push('<div class="wtimes" style="height:' + height + 'px">');
    for (var hr = h0; hr < h1; hr++) h.push('<span style="top:' + y(hr * 60) + 'px">' + M.fmtTime(hr * 60) + '</span>');
    h.push('</div>');
    days.forEach(function (d) {
      var info = plan.days[d - plan.from];
      var w = M.dayWindow(p, d);
      var mins = 0;
      plan.sessions.forEach(function (se) { if (se.day === d) mins += se.min; });
      h.push('<div class="wday' + (d === state.today ? ' is-today' : '') + '"><button type="button" class="wdh2" data-action="week-day" data-day="' + d + '" aria-label="' + esc(M.fmtLong(d) + ': show in the calendar') + '">' +
        '<b>' + M.WD3[M.weekday(d)] + ' ' + M.ymdFromDay(d)[2] + '</b><span>' + (mins ? M.fmtHours(mins) : info && info.blocked ? 'off' : '') + '</span></button>');
      h.push('<div class="wcol" style="height:' + height + 'px">');
      for (var r = h0; r < h1; r++) h.push('<i class="hl-line" style="top:' + y(r * 60) + 'px"></i>');
      if (w.blocked || !info) h.push('<div class="wblock off" style="top:0;height:' + height + 'px"><span>' + esc(!info ? '' : (w.label || 'day off')) + '</span></div>');
      else h.push('<div class="wwin" style="top:' + y(Math.max(w.from, h0 * 60)) + 'px;height:' + hgt(w.from, w.to) + 'px"></div>');
      p.busy.forEach(function (b) {
        if (b.day !== d || b.end <= h0 * 60 || b.start >= h1 * 60) return;
        h.push('<div class="wblock busy" style="top:' + y(Math.max(b.start, h0 * 60)) + 'px;height:' + hgt(b.start, b.end) + 'px" title="' + esc(M.fmtTime(b.start) + '-' + M.fmtTime(b.end) + ' ' + b.label) + '"><span>' + esc(b.label) + '</span></div>');
      });
      plan.exams.forEach(function (e) {
        if (e.day !== d) return;
        h.push('<div class="wblock exam" style="top:' + y(e.start) + 'px;height:' + hgt(e.start, e.start + e.duration) + 'px"><span>EXAM ' + esc(e.code) + ' ' + M.fmtTime(e.start) + '</span></div>');
      });
      plan.sessions.forEach(function (se) {
        if (se.day !== d) return;
        h.push('<div class="wblock sess m' + plan.byExam[se.exam].colour + ' k-' + se.kind + (isDone(se.id) ? ' done' : '') + '" style="top:' + y(se.start) + 'px;height:' + hgt(se.start, se.end) + 'px" title="' + esc(M.fmtTime(se.start) + '-' + M.fmtTime(se.end) + ' ' + M.sessionTitle(se)) + '">' +
          '<span><b>' + esc(se.code.replace(/[0-9]+[A-Z]?$/, '')) + '</b> ' + esc(se.kind === 'paper' ? 'past paper' : se.title) + '</span></div>');
      });
      h.push('</div></div>');
    });
    h.push('</div></div><p class="small muted" style="margin-top:8px">Pale blue: your revision window · grey: busy (lectures, shifts, matches) · red: exams · highlighter: sessions.</p>');
    return h.join('');
  }

  function monthsHtml(by) {
    var plan = state.plan, today = state.today;
    var examOn = {};
    plan.exams.forEach(function (e) { (examOn[e.day] = examOn[e.day] || []).push(e); });
    var dayInfo = {};
    plan.days.forEach(function (d) { dayInfo[d.day] = d; });
    var start = M.ymdFromDay(plan.from), end = M.ymdFromDay(plan.last);
    var out = [];
    var y = start[0], m = start[1];
    while (y < end[0] || (y === end[0] && m <= end[1])) {
      var first = M.dayFromYmd(y, m, 1), dim = M.daysInMonth(y, m), lead = M.weekday(first);
      var hrs = 0;
      for (var q = first; q < first + dim; q++) (by[q] || []).forEach(function (s) { hrs += s.min; });
      var h = ['<section class="month" aria-label="' + M.MONTHS[m - 1] + ' ' + y + '"><h3>' + M.MONTHS[m - 1] + ' ' + y + '<span class="mono">' + hoursText(hrs) + ' planned</span></h3><div class="mgrid">'];
      M.WD3.forEach(function (w) { h.push('<div class="wdh" aria-hidden="true">' + w + '</div>'); });
      // Only the weeks that touch the plan are drawn.
      var gridStart = Math.max(first - lead, plan.from - M.weekday(plan.from));
      var gridEnd = Math.min(first + dim - 1 + (6 - M.weekday(first + dim - 1)), plan.last + (6 - M.weekday(plan.last)));
      for (var b = gridStart; b < first; b++) h.push('<div class="cell out" aria-hidden="true"></div>');
      for (var d = 0; d < dim; d++) {
        var day = first + d;
        if (day < gridStart || day > gridEnd) continue;
        var info = dayInfo[day];
        var inPlan = !!info;
        var list = by[day] || [];
        var cls = 'cell' + (inPlan ? '' : ' out') + (day === today ? ' today' : '') + (day < today ? ' past' : '') + (info && info.blocked ? ' blocked' : '');
        var inner = '<span class="dn">' + (d + 1) + '</span>';
        var mins = 0;
        list.forEach(function (s) { mins += s.min; });
        if (mins) inner += '<span class="hrs">' + M.tenths(mins).replace(/\.0$/, '') + 'h</span>';
        (examOn[day] || []).forEach(function (e) { inner += '<span class="exam-mark">' + esc(e.code) + '</span>'; });
        if (info && info.reserved.length) inner += '<span class="res-mark m' + plan.byExam[info.reserved[0]].colour + '">Final review ' + esc(info.reserved.map(function (id) { return plan.byExam[id].code; }).join(' + ')) + '</span>';
        if (info && info.blocked && !list.length) inner += '<span class="why">' + esc(info.label || 'off') + '</span>';
        var shown = info && info.reserved.length ? list.slice(0, 2) : list.slice(0, 5);
        shown.forEach(function (s) {
          inner += '<span class="chip m' + plan.byExam[s.exam].colour + ' k-' + s.kind + (isDone(s.id) ? ' done' : '') + '"><span class="cc">' + esc(s.code.replace(/[0-9]+[A-Z]?$/, '')) + '</span><span class="ck">' + esc(s.kind === 'paper' ? 'past paper' : s.title) + '</span></span>';
        });
        if (list.length > shown.length) inner += '<span class="more">+' + (list.length - shown.length) + ' more</span>';
        var label = M.fmtDay(day) + ': ' + (list.length ? list.length + ' sessions, ' + M.fmtDur(mins) : 'no sessions') + ((examOn[day] || []).length ? ', exam ' + examOn[day].map(function (e) { return e.code; }).join(' and ') : '');
        if (inPlan) h.push('<button type="button" class="' + cls + '" data-day="' + day + '" aria-pressed="' + (state.selected === day) + '" aria-label="' + esc(label) + '">' + inner + '</button>');
        else h.push('<div class="' + cls + '" aria-hidden="true">' + inner + '</div>');
      }
      for (var t = first + dim; t <= gridEnd; t++) h.push('<div class="cell out" aria-hidden="true"></div>');
      h.push('</div></section>');
      out.push(h.join(''));
      m++;
      if (m > 12) { m = 1; y++; }
    }
    return out.join('');
  }

  function ratingOf(id) {
    var d = state.project.done;
    for (var i = 0; i < d.length; i++) if (d[i].id === id) return d[i].rating || 0;
    return 0;
  }

  function sessionRow(s, allowTick) {
    var plan = state.plan;
    var done = isDone(s.id);
    var col = plan.byExam[s.exam].colour;
    var rate = '';
    if (s.kind === 'review' && allowTick) {
      var r = ratingOf(s.id);
      rate = '<span class="rate" role="group" aria-label="How did the review of ' + esc(s.title) + ' go?">' + [1, 2, 3].map(function (k) {
        return '<button type="button" class="r' + k + '" data-rate="' + k + '" data-id="' + esc(s.id) + '" aria-pressed="' + (done && r === k) + '">' + (k === 1 ? 'Shaky' : k === 2 ? 'OK' : 'Solid') + '</button>';
      }).join('') + '</span>';
    }
    return '<div class="sess m' + col + (done ? ' is-done' : '') + '"><input type="checkbox" class="tick" data-id="' + esc(s.id) + '"' + (done ? ' checked' : '') + (allowTick ? '' : ' disabled') + ' aria-label="Done: ' + esc(M.sessionTitle(s)) + '">' +
      '<span class="t">' + M.fmtTime(s.start) + '–' + M.fmtTime(s.end) + '</span><span class="what"><span class="kind">' + esc(M.KIND_WORD[s.kind]) + '</span><b>' + esc(s.code) + ' ' + esc(s.title) + '</b>' +
      '<span class="det">' + esc(s.detail) + '</span>' + rate + '</span></div>';
  }

  function dayDetailHtml(day, by) {
    var plan = state.plan;
    var info = plan.days[day - plan.from];
    var list = by[day] || [];
    var h = ['<div class="card pinned plain"><div class="card-head"><h3>' + esc(M.fmtLong(day)) + '</h3>' + (day === state.today ? '<span class="tag hl m0">today</span>' : '') + '</div><div class="card-body">'];
    plan.exams.forEach(function (e) {
      if (e.day === day) h.push('<p><span class="exam-mark">EXAM</span> <b>' + esc(e.code + ' ' + e.name) + '</b> at <span class="mono">' + M.fmtTime(e.start) + '</span>' + (e.room ? ', ' + esc(e.room) : '') + (e.seat ? ', seat ' + esc(e.seat) : '') + '</p>');
    });
    if (info && info.reserved.length) h.push('<p class="small"><b>Kept for ' + esc(info.reserved.map(function (id) { return plan.byExam[id].code; }).join(' and ')) + '</b>: a light final review of every topic, weakest first. Nothing new today.</p>');
    if (!list.length) h.push('<p class="muted">' + (info && info.blocked ? 'No revision: ' + esc(info.label || 'a day off') + '.' : 'Nothing planned.') + '</p>');
    list.forEach(function (s) { h.push(sessionRow(s, true)); });
    if (info) h.push('<p class="small muted" style="margin-top:10px">Up to ' + M.fmtDur(info.cap) + ' of revision this day; ' + M.fmtDur(info.used) + ' planned' + (info.spare >= 25 ? ', ' + M.fmtDur(info.spare) + ' spare' : '') + '.</p>');
    h.push('<div class="btn-row" style="margin-top:6px"><button type="button" class="btn btn-small" data-action="copy-day" data-day="' + day + '">Copy as text</button><button type="button" class="btn btn-small" data-action="ics-day" data-day="' + day + '">This day (.ics)</button></div>');
    h.push('</div></div>');
    return h.join('');
  }

  function weekChartHtml() {
    var plan = state.plan;
    var weeks = [];
    var start = plan.from - M.weekday(plan.from);
    for (var w = start; w <= plan.last; w += 7) {
      var parts = {}, cap = 0, tot = 0;
      for (var d = w; d < w + 7; d++) {
        var info = plan.days[d - plan.from];
        if (info) cap += info.cap;
      }
      plan.sessions.forEach(function (s) { if (s.day >= w && s.day < w + 7) { parts[s.exam] = (parts[s.exam] || 0) + s.min; tot += s.min; } });
      weeks.push({ w: w, parts: parts, cap: cap, tot: tot });
    }
    var max = 1;
    weeks.forEach(function (x) { max = Math.max(max, x.cap, x.tot); });
    var h = ['<div class="card plain wchart-card"><div class="card-head"><h3>Hours each week</h3><span class="tag">bar: planned · line: available</span></div><div class="card-body"><div class="wchart">'];
    weeks.forEach(function (x) {
      var segs = plan.exams.map(function (e) { var v = x.parts[e.id] || 0; return v ? '<span class="m' + e.colour + '" style="width:' + (v * 100 / max) + '%" title="' + esc(e.code + ': ' + M.fmtHours(v)) + '"></span>' : ''; }).join('');
      h.push('<div class="wbar"><span class="wl">w/c ' + esc(M.fmtShort(x.w).slice(4)) + '</span><span class="track" role="img" aria-label="' + esc('Week of ' + M.fmtShort(x.w) + ': ' + M.fmtHours(x.tot) + ' planned of ' + M.fmtHours(x.cap) + ' available') + '">' + segs + '<i class="cap" style="left:' + (x.cap * 100 / max) + '%"></i></span><span class="wv">' + M.fmtHours(x.tot) + '</span></div>');
    });
    h.push('</div></div></div>');
    return h.join('');
  }

  function listHtml(by) {
    var plan = state.plan;
    var h = ['<div class="table-wrap"><table class="sess-table"><thead><tr><th scope="col">Done</th><th scope="col">Time</th><th scope="col">Module</th><th scope="col">What</th><th scope="col">Topic</th></tr></thead><tbody>'];
    for (var d = plan.from; d <= plan.last; d++) {
      var list = by[d] || [];
      var exams = plan.exams.filter(function (e) { return e.day === d; });
      if (!list.length && !exams.length) continue;
      h.push('<tr class="dayrow"><td colspan="5">' + esc(M.fmtLong(d)) + (exams.length ? ' · <span style="color:var(--red)">EXAM ' + esc(exams.map(function (e) { return e.code + ' at ' + M.fmtTime(e.start); }).join(', ')) + '</span>' : '') + '</td></tr>');
      list.forEach(function (s) {
        var done = isDone(s.id);
        h.push('<tr><td><input type="checkbox" class="tick" data-id="' + esc(s.id) + '"' + (done ? ' checked' : '') + ' aria-label="Done: ' + esc(M.sessionTitle(s)) + '"></td><td class="t">' + M.fmtTime(s.start) + '–' + M.fmtTime(s.end) + '</td><td><span class="tag hl m' + plan.byExam[s.exam].colour + '">' + esc(s.code) + '</span></td><td>' + esc(M.KIND_WORD[s.kind]) + '<div class="small muted">' + esc(s.detail) + '</div></td><td>' + esc(s.kind === 'paper' ? '' : s.title) + '</td></tr>');
      });
    }
    h.push('</tbody></table></div>');
    return h.join('');
  }

  // ------------------------------------------------------------------
  // View 4: progress
  // ------------------------------------------------------------------

  function renderProgress() {
    var p = state.project, plan = state.plan, st = state.status, today = state.today;
    var h = [];
    h.push('<div class="view-head"><div><h2>Progress</h2><p class="intro">Tick sessions off as you do them. If a day goes wrong, re-plan from today: everything you have done stays done, and what is left is spread over the days you still have.</p></div>' +
      '<div class="field today-field"><label for="today-is">Today is</label><input type="date" id="today-is" value="' + M.isoDay(today) + '"><span class="hint">' + (p.asOf !== null ? 'Set by hand (the real date is ' + esc(M.fmtShort(realToday())) + '). <button type="button" class="btn-link" data-action="real-today">Use the real date</button>' : 'Change it to see the plan on another day.') + '</span></div></div>');
    h.push('<div class="cols-3">');
    // Today
    var t = ['<div class="card taped pinned" style="grid-column:span 2"><div class="card-head"><h3>Today, ' + esc(M.fmtShort(today)) + '</h3><span class="mono small">' + M.fmtDur(state.summary.todayDone) + ' of ' + M.fmtDur(state.summary.todayMin) + ' done</span></div><div class="card-body">'];
    plan.exams.forEach(function (e) { if (e.day === today) t.push('<p><span class="exam-mark">EXAM</span> <b>' + esc(e.code + ' ' + e.name) + '</b> at <span class="mono">' + M.fmtTime(e.start) + '</span>' + (e.room ? ', ' + esc(e.room) : '') + '. Good luck.</p>'); });
    if (!st.todaySessions.length) t.push('<p class="muted">Nothing planned today.' + (today < plan.from ? ' The plan starts on ' + esc(M.fmtShort(plan.from)) + '.' : '') + '</p>');
    st.todaySessions.forEach(function (s) { t.push(sessionRow(s, true)); });
    t.push('<div class="btn-row" style="margin-top:10px"><button type="button" class="btn btn-small" data-action="copy-day" data-day="' + today + '">Copy today as text</button><button type="button" class="btn btn-small" data-action="ics-day" data-day="' + today + '">Today (.ics)</button></div></div></div>');
    h.push(t.join(''));
    // Re-plan
    var missedN = st.missed.length, missedMin = 0;
    st.missed.forEach(function (s) { missedMin += s.min; });
    h.push('<div class="card taped" style="--tape:repeating-linear-gradient(45deg,#ff9fcb 0 6px,#ffd0e5 6px 12px)"><div class="card-head"><h3>Fell behind?</h3></div><div class="card-body">' +
      (missedN ? '<p><b class="mono">' + missedN + '</b> sessions (' + hoursText(missedMin) + ') from ' + esc(M.fmtShort(p.planFrom)) + ' to ' + esc(M.fmtShort(today - 1)) + ' are not ticked off.</p>' : '<p>Nothing missed since the plan was made on ' + esc(M.fmtShort(p.planFrom)) + '.</p>') +
      (st.shakyNew ? '<p><b class="mono">' + st.shakyNew + '</b> ' + (st.shakyNew === 1 ? 'review was' : 'reviews were') + ' shaky since then: re-planning brings ' + (st.shakyNew === 1 ? 'that topic' : 'those topics') + ' back the next day.</p>' : '') +
      '<div class="btn-row"><button type="button" class="btn btn-small btn-marker" data-action="replan"' + (missedN || p.planFrom < today ? '' : '') + '>Re-plan from today</button></div>' +
      '<p class="hint" style="margin-top:8px">Re-planning keeps every tick, files the unticked sessions as missed, and rebuilds the rest of the plan from today with the same rules.</p>' +
      '<div class="btn-row" style="margin-top:8px"><button type="button" class="btn btn-small" data-action="block-today">Can\'t revise today: block it and re-plan</button></div></div></div>');
    h.push('</div>');

    // On track?
    h.push('<h3 style="margin-top:32px">On track for each exam?</h3><p class="small muted" style="max-width:60em">Hours needed are what the rules ask for: first learning, three spaced reviews and a final review per topic, plus ' + p.settings.papers + ' past papers. Done and still planned are set against that.</p>');
    if (!st.exams.length) h.push('<p class="sticky" style="max-width:520px">No exams to track yet.</p>');
    h.push('<div class="track-cards">');
    st.exams.forEach(function (r, i) {
      var max = Math.max(r.need, r.done + r.ahead + r.missed, 1);
      var pct = function (v) { return (v * 100 / max) + '%'; };
      var shortMin = Math.max(0, r.need - r.done - r.ahead);
      var bar = '<div class="hbar m' + r.colour + '" role="img" aria-label="' + esc(r.code + ': ' + M.fmtHours(r.done) + ' done, ' + M.fmtHours(r.ahead) + ' still planned, ' + M.fmtHours(r.need) + ' needed') + '">' +
        '<span class="done" style="width:' + pct(r.done) + '"></span><span class="ahead" style="width:' + pct(r.ahead) + '"></span>' + (r.missed ? '<span class="missed" style="width:' + pct(r.missed) + '"></span>' : '') +
        (shortMin && r.verdict !== 'sat' && r.verdict !== 'today' ? '<span class="short" style="width:' + pct(shortMin) + '"></span>' : '') + '<i class="need" style="left:calc(' + pct(r.need) + ' - 2px)"></i></div>';
      var fix = '';
      if (r.verdict === 'short') {
        var names = r.quick.map(function (id) { var tp = null; p.topics.forEach(function (x) { if (x.id === id) tp = x; }); return tp ? tp.name + ' (confidence ' + tp.conf + ')' : id; });
        fix = '<div class="fix"><b>What to drop or shorten</b><ul>' +
          (names.length ? '<li>Give your strongest topics a quick look and one review instead of full learning: ' + esc(names.join(', ')) + '. That frees about ' + hoursText(r.quickSaves) + '. <button type="button" class="btn-link" data-action="quick-apply" data-exam="' + esc(r.id) + '">Do this</button></li>' : '') +
          (r.extraDays ? '<li>Or find room for <b class="mono">' + r.extraSessions + '</b> more ' + p.settings.learnMin + '-minute ' + (r.extraSessions === 1 ? 'session' : 'sessions') + ' before new topics stop on ' + esc(M.fmtShort(plan.byExam[r.id].learnBy)) + ': an extra hour on ' + (r.extraSessions === 1 ? 'one' : r.extraSessions) + ' of the ' + r.extraDays + ' free days, under <button type="button" class="btn-link" data-go="time">Your time</button>.</li>' : '') +
          '<li>Or set a topic you can afford to lose to "Drop" under <button type="button" class="btn-link" data-go="exams">Exams and topics</button>.</li></ul></div>';
      }
      h.push('<div class="card ontrack m' + r.colour + ' mod ' + (i % 2 ? 'tilt-r' : 'tilt-l') + '"><div class="card-head"><div><h3>' + esc(r.code) + ' ' + esc(r.name) + '</h3><div class="when">' + esc(M.fmtDay(r.day)) + ' · ' + (r.verdict === 'sat' ? 'sat' : r.daysLeft === 0 ? 'today' : r.daysLeft + (r.daysLeft === 1 ? ' day' : ' days') + ' to go') + '</div></div><span class="verdict ' + r.verdict + '">' + esc(r.headline) + '</span></div><div class="card-body">' +
        bar + '<div class="hkey"><span>Needed <b>' + hoursText(r.need) + '</b></span><span>Done <b>' + hoursText(r.done) + '</b></span><span>Still planned <b>' + hoursText(r.ahead) + '</b></span>' + (r.missed ? '<span>Missed <b>' + hoursText(r.missed) + '</b></span>' : '') + (shortMin && r.verdict !== 'sat' && r.verdict !== 'today' ? '<span style="color:var(--red)">Short <b>' + hoursText(shortMin) + '</b></span>' : '') + '</div>' +
        '<ul class="reasons">' + r.reasons.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' + fix + '</div></div>');
    });
    h.push('</div>');

    // The last two weeks
    h.push('<h3 style="margin-top:32px">The last two weeks</h3><div class="streak">');
    var by = sessionsByDay();
    var doneByDay = {};
    p.done.forEach(function (d) { doneByDay[d.day] = (doneByDay[d.day] || 0) + d.min; });
    var missedByDay = {};
    p.missed.forEach(function (d) { missedByDay[d.day] = (missedByDay[d.day] || 0) + d.min; });
    for (var d = today - 13; d <= today; d++) {
      var planned = 0, undone = 0;
      (by[d] || []).forEach(function (s) { planned += s.min; if (!isDone(s.id)) undone += s.min; });
      var dn = doneByDay[d] || 0, ms = (missedByDay[d] || 0) + (d < today ? undone : 0);
      var cls = dn && !ms ? 'full' : dn && ms ? 'part' : ms ? 'miss' : 'none';
      h.push('<div class="sday ' + cls + (d === today ? ' now' : '') + '" title="' + esc(M.fmtDay(d) + ': ' + M.fmtDur(dn) + ' done' + (ms ? ', ' + M.fmtDur(ms) + ' missed' : '')) + '"><span class="d">' + esc(M.fmtShort(d).slice(0, 3)) + ' ' + M.ymdFromDay(d)[2] + '</span><span class="v">' + (dn ? M.tenths(dn).replace(/\.0$/, '') + 'h' : ms ? '×' : '–') + '</span></div>');
    }
    h.push('</div><p class="small muted" style="margin-top:8px">Green: everything done · half yellow: some done · red stripes: missed · grey: nothing planned.</p>');
    if (p.missed.length) {
      h.push('<details style="margin-top:14px"><summary>' + p.missed.length + ' sessions filed as missed when you re-planned</summary><ul class="small">' +
        p.missed.slice(-40).map(function (m) { return '<li>' + esc(M.fmtShort(m.day)) + ': ' + esc(m.title) + '</li>'; }).join('') + '</ul></details>');
    }
    h.push('<div class="btn-row" style="margin-top:22px"><button type="button" class="btn btn-small" data-action="save-project">Save plan file</button><button type="button" class="btn btn-small" data-action="status-csv">On-track table (CSV)</button><button type="button" class="btn btn-small" data-action="ics-ahead">Sessions from today (.ics)</button></div>');
    $('#view-progress').innerHTML = h.join('');
  }

  // ------------------------------------------------------------------
  // View 5: the topic tracker
  // ------------------------------------------------------------------

  var STATE_ORDER = ['not started', 'learning', 'learnt', 'reviewing', 'ready', 'not planned', 'dropped'];

  function renderTopics() {
    var p = state.project, plan = state.plan, today = state.today;
    var rows = M.topicStatus(p, plan, today);
    var f = state.topicFilter;
    var counts = {};
    rows.forEach(function (r) { counts[r.state] = (counts[r.state] || 0) + 1; });
    var h = ['<div class="view-head"><div><h2>Topic tracker</h2><p class="intro">Every topic and where it stands on ' + esc(M.fmtShort(today)) + ': learning done and still planned, each review and how it went, and what comes next. Rate a review when you tick it off; once you re-plan, a shaky one brings the topic back the next day and a solid one stretches the gap.</p></div></div>'];
    h.push('<div class="state-counts">' + STATE_ORDER.filter(function (k) { return counts[k]; }).map(function (k) {
      return '<span class="state s-' + k.replace(' ', '-') + '">' + esc(k) + ': ' + counts[k] + '</span>';
    }).join('') + '</div>');
    var codes = [];
    rows.forEach(function (r) { if (codes.indexOf(r.code) < 0) codes.push(r.code); });
    h.push('<div class="filters"><div class="field"><label for="tf-code">Module</label><select id="tf-code" data-filter="code"><option value="">All modules</option>' +
      codes.map(function (c) { return '<option value="' + esc(c) + '"' + (f.code === c ? ' selected' : '') + '>' + esc(c) + '</option>'; }).join('') + '</select></div>' +
      '<div class="field"><label for="tf-state">State</label><select id="tf-state" data-filter="state"><option value="">Any state</option>' +
      STATE_ORDER.map(function (k) { return '<option value="' + esc(k) + '"' + (f.state === k ? ' selected' : '') + '>' + esc(k) + '</option>'; }).join('') + '</select></div></div>');
    if (!rows.length) h.push('<p class="sticky" style="max-width:520px">No topics yet. Add them under <button type="button" class="btn-link" data-go="exams">Exams and topics</button>.</p>');
    h.push('<div class="module-cards">');
    var shown = 0;
    codes.forEach(function (code) {
      if (f.code && f.code !== code) return;
      var list = rows.filter(function (r) { return r.code === code && (!f.state || r.state === f.state); });
      if (!list.length) return;
      shown += list.length;
      var ex = null;
      plan.exams.forEach(function (e) { if (e.code === code && ex === null) ex = e; });
      var col = examColour(code);
      h.push('<div class="card mod taped plain m' + col + '"><div class="card-head"><div><h3>' + esc(code) + ' ' + esc(ex ? ex.name : '') + '</h3><div class="small muted">' +
        (ex ? 'Exam ' + esc(M.fmtDay(ex.day)) : 'No upcoming exam') + '</div></div></div><div class="card-body"><table class="tt"><thead><tr><th scope="col">Topic</th><th scope="col">Learning</th><th scope="col">Reviews</th><th scope="col">Next</th><th scope="col">State</th></tr></thead><tbody>');
      list.forEach(function (r) {
        var blocks = '';
        for (var i = 0; i < r.learnTotal; i++) blocks += '<i class="' + (i < r.learnDone ? 'd' : i < r.learnDone + r.learnAhead ? '' : i < r.learnDone + r.learnAhead + r.learnMissed ? 'x' : 'n') + '"></i>';
        var dots = r.ratings.map(function (k) { return '<i class="r' + k + '" title="' + (k ? M.RATING_WORD[k] : 'not rated') + '"></i>'; }).join('');
        for (var j = 0; j < r.reviewsAhead; j++) dots += '<i class="p" title="planned"></i>';
        if (r.finalDone) dots += '<i class="f r3" title="final review done"></i>';
        else if (r.finalAhead) dots += '<i class="f p" title="final review planned"></i>';
        var next = r.next ? esc(M.fmtShort(r.next.day)) + ' ' + M.fmtTime(r.next.start) + ' <span class="muted">' + esc(M.KIND_WORD[r.next.kind].toLowerCase()) + '</span>' : '<span class="muted">nothing planned</span>';
        var confC = ['', '#ff9b8f', '#ffc27a', '#ffe74a', '#b8eb7d', '#82e297'][r.conf];
        var notFitted = Math.max(0, r.learnTotal - r.learnDone - r.learnAhead - r.learnMissed);
        var learnLabel = r.learnDone + ' of ' + r.learnTotal + ' learning sessions done' + (r.learnAhead ? ', ' + r.learnAhead + ' planned' : '') + (r.learnMissed ? ', ' + r.learnMissed + ' missed' : '') + (notFitted ? ', ' + notFitted + ' not fitted' : '');
        var revLabel = r.reviewsDone + ' reviews done' + (r.shaky ? ' (' + r.shaky + ' shaky)' : '') + ', ' + r.reviewsAhead + ' planned' + (r.finalDone ? ', final review done' : r.finalAhead ? ', final review planned' : '');
        h.push('<tr><td class="tn"><span class="cdot" style="background:' + confC + '" title="confidence ' + r.conf + '">' + r.conf + '</span>' + esc(r.name) + (r.mode === 'quick' ? ' <span class="tag">quick</span>' : '') + '</td>' +
          '<td><span class="blocks" role="img" aria-label="' + esc(learnLabel) + '">' + blocks + '</span></td>' +
          '<td><span class="dots" role="img" aria-label="' + esc(revLabel) + '">' + dots + '</span></td>' +
          '<td class="next">' + next + '</td><td><span class="state s-' + r.state.replace(' ', '-') + '">' + esc(r.state) + '</span></td></tr>');
      });
      h.push('</tbody></table></div></div>');
    });
    h.push('</div>');
    if (rows.length && !shown) h.push('<p class="muted">No topics match these filters.</p>');
    h.push('<p class="small muted" style="margin-top:14px">Learning: filled squares are done, open ones planned, striped ones missed (re-plan to fit them back in), red ones did not fit. Reviews: red was shaky, yellow OK, green solid, grey not rated; dashed circles are planned; the square is the final review.</p>');
    $('#view-topics').innerHTML = h.join('');
  }

  // ------------------------------------------------------------------
  // View 6: the rules in plain English
  // ------------------------------------------------------------------

  function renderRules() {
    var s = state.project.settings;
    var gaps = M.REVIEW_GAPS;
    var cards = [
      ['m0', 'How long each topic needs', '<p>A topic\'s size is the first learning it needs at middling confidence: S is 2 hours, M is 3, L is 5 (XS 1, XL 7), or the hours you type. Confidence scales it: 1 needs 150%, 2 needs 125%, 3 needs 100%, 4 needs 75% and 5 needs 50%. That is rounded up to whole ' + s.learnMin + '-minute learning sessions. A topic marked Quick gets one ' + s.reviewMin + '-minute look and one review; Drop leaves it out.</p>'],
      ['m1', 'Weak and heavy topics first', '<p>Within each module, topics are learnt in order of confidence (weakest first), then size (biggest first), then the order you listed them. So the topics most likely to go wrong get the most time and the most reviews.</p>'],
      ['m2', 'Which module next', '<p>Every module aims to finish its new topics a week before they stop (see the taper), so its last topics still get reviews. The next learning session goes to the module with the least slack: the hours of free time left before that aim, minus the hours of learning it still needs. Early exams come first without starving later ones.</p>'],
      ['m3', 'Mixed, never one module all day', '<p>No module takes more than ' + s.maxShare + '% of a day\'s revision, and two sessions in a row are from different modules, whenever another module has something to do. A topic gets at most one session a day. These only relax when nothing else fits.</p>'],
      ['m4', 'Spaced reviews at growing gaps', '<p>Once a topic is learnt, it comes back for ' + s.reviewMin + '-minute reviews ' + gaps.join(', ').replace(/, ([0-9]+)$/, ' and $1') + ' days apart, each gap counted from the review before. The first three reviews come before new learning (up to ' + s.reviewShare + '% of a day); later top-ups only fill spare time. A review that slips simply happens the next free day.</p>'],
      ['m5', 'A taper into each exam', '<p>New topics stop ' + s.taperDays + ' days before each exam. In the two weeks before it, ' + s.papers + ' timed past papers (as long as the exam, up to ' + M.fmtDur(s.paperMax) + ') are booked as late as possible, at most one a day and never on another exam\'s day.</p>'],
      ['m0', 'The day before is kept for that exam', '<p>The day before each exam (or the nearest free day up to three days before) is kept for it: one final review of every topic, weakest first, and nothing new. On an exam day you ' + (s.examDay === 'after' ? 'revise only after the exam, for at most half your usual hours' : s.examDay === 'off' ? 'do no revision' : 'revise your normal hours around the exam') + '.</p>'],
      ['m1', 'Your time comes first', '<p>Sessions only go inside your window for the day, up to your hours, never over a busy time from your calendar (with ' + s.busyGap + ' minutes either side) or within ' + s.examGap + ' minutes of an exam. Each session is followed by a ' + s.breakMin + '-minute break. Blocked days get nothing.</p>'],
      ['m4', 'Shaky, OK or solid', '<p>When you tick a review off you can say how it went. Once you re-plan, a shaky review starts that topic\'s ladder of gaps again (it comes back the next day), OK moves it one step and solid moves it two. Unrated reviews count as OK.</p>'],
      ['m2', 'Ticks, misses and re-planning', '<p>Ticking a session never moves the plan. Re-planning keeps every tick, files unticked past sessions as missed and builds the rest again from today with the same rules, counting what is already done (a topic half learnt carries on from where it was). Any change to your exams, topics or time re-plans from today in the same way.</p>'],
      ['m3', 'On track, tight or short', '<p>Hours needed per exam are first learning, three spaced reviews and a final review per topic, plus the past papers. <b>Not enough time</b> means some first learning does not fit before new topics stop; you are shown which strong topics to switch to a quick look and how much extra time a day would cover it. <b>Tight</b> means a past paper, a final review or two spaced reviews could not fit. <b>Behind</b> means sessions before today were not ticked.</p>'],
      ['m4', 'Same answer every time', '<p>The plan is deterministic: the same inputs always give the same plan, in this app and in the Python companion (the tests check they agree session by session and byte by byte). Nothing is random and nothing is sent anywhere.</p>'],
      ['m5', 'What it cannot know', '<p>It does not know how hard a module really is, only what you tell it, and it cannot see past papers or mark schemes. Treat the plan as a well-organised starting point: change a confidence rating after a review that went badly and let it re-plan.</p>']
    ];
    var h = ['<div class="view-head"><div><h2>The rules</h2><p class="intro">The plan comes from a handful of plain rules applied the same way every time. The numbers below are your current settings (change them under <button type="button" class="btn-link" data-go="time">Your time</button>).</p></div></div><div class="rules">'];
    cards.forEach(function (c, i) { h.push('<div class="card rule plain ' + c[0] + (i % 3 === 1 ? ' tilt-r' : '') + '"><div class="card-head"><h3>' + esc(c[1]) + '</h3></div><div class="card-body">' + c[2] + '</div></div>'); });
    h.push('</div>');
    $('#view-rules').innerHTML = h.join('');
  }

  // ------------------------------------------------------------------
  // Render all and navigation
  // ------------------------------------------------------------------

  function renderAll() {
    renderHero();
    renderStickers();
    renderBanner();
    VIEWS.forEach(function (v) {
      var tab = $('#tab-' + v), panel = $('#view-' + v);
      var on = v === state.view;
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
      panel.hidden = !on;
    });
    if (state.view === 'exams') renderExams();
    else if (state.view === 'time') renderTime();
    else if (state.view === 'plan') renderPlan();
    else if (state.view === 'progress') renderProgress();
    else if (state.view === 'topics') renderTopics();
    else renderRules();
    try { localStorage.setItem(STORE + '-view', state.view); } catch (e) { /* storage blocked */ }
  }

  function go(view, focusTab) {
    if (VIEWS.indexOf(view) < 0) return;
    state.view = view;
    renderAll();
    if (focusTab) $('#tab-' + view).focus();
  }

  // ------------------------------------------------------------------
  // Events
  // ------------------------------------------------------------------

  function examField(i, field, value) {
    var e = state.project.exams[i];
    if (!e) return;
    if (field === 'name') e.name = value.trim() || e.code;
    else if (field === 'room') e.room = value.trim();
    else if (field === 'day') { e.day = value ? M.fromIso(value) : null; e.tbc = e.day === null; }
    else if (field === 'start') { var t = M.parseClock(value); if (t !== null && t < 1440) e.start = t; }
    else if (field === 'duration') { var n = parseInt(value, 10); if (n > 0) e.duration = Math.min(1440, Math.max(15, n)); }
    state.project = M.cleanProject(JSON.parse(M.projectFile(state.project)), realToday());
    changed(field === 'day' ? 'Exam date changed: the plan has been rebuilt.' : null);
  }

  function topicField(i, field, value) {
    var t = state.project.topics[i];
    if (!t) return;
    if (field === 'name') { var v = value.trim(); if (!v) return; t.name = v; }
    else if (field === 'size') t.size = parseInt(value, 10) || t.size;
    else if (field === 'mode') t.mode = value;
    else if (field === 'conf') t.conf = parseInt(value, 10) || t.conf;
    changed(null);
  }

  function weekField(i, field, value) {
    var w = state.project.week[i];
    if (field === 'from') { var a = M.parseClock(value); if (a !== null) w.from = a; }
    else if (field === 'to') { var b = M.parseClock(value); if (b !== null) w.to = b === 0 ? 1440 : b; }
    else if (field === 'hours') { var hh = M.scaleDecimal(String(value).trim() || '0', 60); if (hh !== null) w.minutes = hh; }
    if (w.to < w.from) w.to = w.from;
    if (w.minutes > w.to - w.from) w.minutes = w.to - w.from;
    changed(null);
  }

  function settingField(key, value) {
    var p = state.project;
    if (key === 'planFrom') {
      var d = M.fromIso(value);
      if (d !== null && !p.done.length) { p.planFrom = d; p.planFromMin = 0; }
      ensureOwnKeep();
      recompute(); persist(); renderAll();
      return;
    }
    var s = JSON.parse(JSON.stringify(p.settings));
    s[key] = key === 'examDay' ? value : parseInt(value, 10);
    p.settings = M.cleanSettings(s);
    changed(null);
  }

  function ensureOwnKeep() { if (state.isSample) state.isSample = false; }

  function onClick(ev) {
    var t = ev.target.closest('[data-action],[data-view],[data-go],[data-day],[data-conf],[data-mode],[data-rate]');
    if (!t) return;
    if (t.hasAttribute('data-view') && t.getAttribute('role') === 'tab') { go(t.getAttribute('data-view')); return; }
    if (t.hasAttribute('data-go')) { go(t.getAttribute('data-go')); window.scrollTo(0, $('.sheet').getBoundingClientRect().top + window.pageYOffset - 10); return; }
    if (t.hasAttribute('data-mode')) { state.planMode = t.getAttribute('data-mode'); renderPlan(); return; }
    if (t.hasAttribute('data-conf')) { topicField(parseInt(t.getAttribute('data-topic'), 10), 'conf', t.getAttribute('data-conf')); return; }
    if (t.hasAttribute('data-rate')) {
      var rid = t.getAttribute('data-id'), rk = parseInt(t.getAttribute('data-rate'), 10);
      M.rate(state.project, state.plan, rid, state.today, ratingOf(rid) === rk && isDone(rid) ? 0 : rk);
      ticked();
      var back = $('[data-rate="' + rk + '"][data-id="' + rid.replace(/"/g, '') + '"]');
      if (back) back.focus();
      if (rk === 1) toast('Marked shaky: re-plan and this topic comes back the next day.');
      return;
    }
    if (t.classList.contains('cell') && t.hasAttribute('data-day')) {
      state.selected = parseInt(t.getAttribute('data-day'), 10);
      renderPlan();
      var again = $('.cell[data-day="' + state.selected + '"]');
      if (again) again.focus();
      if (window.innerWidth < 1060) { var dd = $('.day-detail'); if (dd) dd.scrollIntoView({ block: 'start' }); }
      return;
    }
    var a = t.getAttribute('data-action');
    if (!a) return;
    var p = state.project, plan = state.plan;
    switch (a) {
      case 'start-own': startOwn(); break;
      case 'show-sample': forget(); state.restored = false; loadSample(); state.view = 'plan'; renderAll(); break;
      case 'open-project': $('#file-project').click(); break;
      case 'save-project': download(fileSafe(p.name) + '.json', M.projectFile(p), 'application/json'); toast('Saved the plan file. Open it here any time to carry on.'); break;
      case 'read-exams': importExams($('#exam-text').value, 'pasted text'); break;
      case 'read-topics': importTopics($('#topic-text').value, 'pasted list', false); break;
      case 'replace-topics': importTopics($('#topic-text').value, 'pasted list', true); break;
      case 'try-messy':
        state.view = 'exams'; renderAll();
        $('#exam-text').value = SAMPLES.messy;
        importExams(SAMPLES.messy, 'messy-timetable.txt');
        break;
      case 'try-list':
        $('#topic-text').value = SAMPLES.pasted;
        importTopics(SAMPLES.pasted, 'topics-pasted.txt', false);
        break;
      case 'template-exams': download('exam-timetable-template.csv', M.examTemplate(), 'text/csv;charset=utf-8'); break;
      case 'template-topics': download('topics-template.csv', M.topicTemplate(), 'text/csv;charset=utf-8'); break;
      case 'del-exam': p.exams.splice(parseInt(t.getAttribute('data-i'), 10), 1); changed('Exam removed.'); break;
      case 'del-topic': p.topics.splice(parseInt(t.getAttribute('data-i'), 10), 1); changed('Topic removed.'); break;
      case 'clear-topics': if (window.confirm('Remove all ' + p.topics.length + ' topics?')) { p.topics = []; changed('All topics removed.'); } break;
      case 'clear-busy': p.busy = []; p.allDay = []; p.sources = p.sources.filter(function (s) { return s.kind !== 'calendar'; }); changed('Busy times removed.'); break;
      case 'del-override': var dday = parseInt(t.getAttribute('data-day'), 10); p.overrides = p.overrides.filter(function (v) { return v.day !== dday; }); changed('Change removed.'); break;
      case 'block-allday':
        var lab = t.getAttribute('data-label');
        p.allDay.forEach(function (x) { if (x.label === lab && x.day >= state.today) M.setOverride(p, x.day, 0, lab); });
        changed('Blocked: ' + lab + '.');
        break;
      case 'save-availability': download('availability.csv', M.availabilityCsv(p), 'text/csv;charset=utf-8'); break;
      case 'reset-settings': p.settings = M.cleanSettings({}); changed('Settings back to the defaults.'); break;
      case 'ics-all': download('revision-plan.ics', M.sessionsIcs(p, plan, { name: p.name, alarm: state.alarm }), 'text/calendar;charset=utf-8'); toast('Calendar file saved: import it into Google, Apple or Outlook calendar.'); break;
      case 'markdown': download(fileSafe(p.name) + '.md', M.checklistMarkdown(p, plan, state.today, null), 'text/markdown;charset=utf-8'); toast('Checklist saved from today on: paste or open it in your notes app.'); break;
      case 'week-prev': state.weekStart -= 7; renderPlan(); break;
      case 'week-next': state.weekStart += 7; renderPlan(); break;
      case 'week-this': state.weekStart = null; renderPlan(); break;
      case 'week-day': state.selected = parseInt(t.getAttribute('data-day'), 10); state.planMode = 'calendar'; renderPlan(); break;
      case 'ics-ahead': download('revision-from-' + slugDate(state.today) + '.ics', M.sessionsIcs(p, plan, { name: p.name, fromDay: state.today, skipDone: true, alarm: state.alarm }), 'text/calendar;charset=utf-8'); break;
      case 'ics-day':
        var d1 = parseInt(t.getAttribute('data-day'), 10);
        download('revision-' + slugDate(d1) + '.ics', M.sessionsIcs(p, plan, { name: p.name, fromDay: d1, toDay: d1, exams: false }), 'text/calendar;charset=utf-8');
        break;
      case 'csv': download('revision-sessions.csv', M.sessionsCsv(p, plan), 'text/csv;charset=utf-8'); break;
      case 'status-csv': download('on-track.csv', M.statusCsv(state.status), 'text/csv;charset=utf-8'); break;
      case 'print': if (state.planMode === 'list') { state.planMode = 'calendar'; renderPlan(); } window.print(); break;
      case 'copy-day':
        var d2 = parseInt(t.getAttribute('data-day'), 10);
        copyText(M.dayText(p, plan, d2), function (ok) { toast(ok ? 'Copied ' + M.fmtShort(d2) + ' as text.' : 'Copying is blocked here; use the .ics or CSV instead.'); });
        break;
      case 'replan':
        M.replan(p, plan, state.today, p.asOf === null && state.today === realToday() ? nowMinutes() : 0);
        ensureOwnKeep(); recompute(); persist(); renderAll();
        toast('Re-planned from ' + M.fmtShort(state.today) + '. Ticks kept; ' + p.missed.length + ' sessions filed as missed.');
        break;
      case 'block-today':
        M.setOverride(p, state.today, 0, 'Could not revise');
        M.replan(p, plan, state.today, 0);
        ensureOwnKeep(); recompute(); persist(); renderAll();
        toast('Today is blocked and the plan starts again from here.');
        break;
      case 'real-today': p.asOf = null; ensureOwnKeep(); recompute(); persist(); renderAll(); break;
      case 'quick-apply':
        var r = null;
        state.status.exams.forEach(function (x) { if (x.id === t.getAttribute('data-exam')) r = x; });
        if (r) {
          p.topics.forEach(function (tp) { if (r.quick.indexOf(tp.id) >= 0) tp.mode = 'quick'; });
          changed(r.quick.length + ' topics switched to a quick look.');
        }
        break;
      default: break;
    }
  }

  function fileSafe(name) {
    return (String(name || 'revision-plan').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'revision-plan');
  }

  function onChange(ev) {
    var t = ev.target;
    if (t.id === 'file-project' && t.files && t.files[0]) { var f = t.files[0]; readFile(f, function (txt) { openProjectText(txt, f.name); }); t.value = ''; return; }
    if (t.id === 'exam-file' && t.files[0]) { var f1 = t.files[0]; readFile(f1, function (txt) { importExams(txt, f1.name); }); return; }
    if (t.id === 'topic-file' && t.files[0]) { var f2 = t.files[0]; readFile(f2, function (txt) { importTopics(txt, f2.name, false); }); return; }
    if (t.id === 'cal-file' && t.files[0]) { var f3 = t.files[0]; readFile(f3, function (txt) { importCalendar(txt, f3.name); }); return; }
    if (t.id === 'avail-file' && t.files[0]) { var f4 = t.files[0]; readFile(f4, function (txt) { importAvailability(txt, f4.name); }); return; }
    if (t.id === 'alarm') { state.alarm = parseInt(t.value, 10) || 0; try { localStorage.setItem(STORE + '-alarm', String(state.alarm)); } catch (e) { /* storage blocked */ } return; }
    if (t.hasAttribute('data-filter')) { state.topicFilter[t.getAttribute('data-filter')] = t.value; renderTopics(); var fb = $('#' + t.id); if (fb) fb.focus(); return; }
    if (t.id === 'today-is') {
      var d = M.fromIso(t.value);
      if (d !== null) { state.project.asOf = d === realToday() ? null : d; ensureOwnKeep(); recompute(); persist(); renderAll(); }
      return;
    }
    if (t.classList.contains('tick')) {
      M.tick(state.project, state.plan, t.getAttribute('data-id'), state.today, t.checked);
      var id = t.getAttribute('data-id');
      ticked();
      var again = $('.tick[data-id="' + id.replace(/"/g, '') + '"]');
      if (again) again.focus();
      return;
    }
    if (t.hasAttribute('data-exam')) { examField(parseInt(t.getAttribute('data-exam'), 10), t.getAttribute('data-field'), t.value); return; }
    if (t.hasAttribute('data-topic') && t.hasAttribute('data-field')) { topicField(parseInt(t.getAttribute('data-topic'), 10), t.getAttribute('data-field'), t.value); return; }
    if (t.hasAttribute('data-week')) { weekField(parseInt(t.getAttribute('data-week'), 10), t.getAttribute('data-field'), t.value); return; }
    if (t.hasAttribute('data-setting')) { settingField(t.getAttribute('data-setting'), t.value); return; }
  }

  function onSubmit(ev) {
    var f = ev.target;
    var kind = f.getAttribute('data-form');
    if (!kind) return;
    ev.preventDefault();
    var p = state.project;
    if (kind === 'add-exam') {
      var code = M.normCode($('#ne-code').value);
      if (!code) { toast('Give the exam a module code.'); return; }
      ensureOwnKeep();
      p.exams.push({ id: '', code: code, name: $('#ne-name').value.trim() || code, day: M.fromIso($('#ne-day').value), start: M.parseClock($('#ne-start').value) || 570,
        duration: Math.max(15, parseInt($('#ne-dur').value, 10) || 120), room: '', seat: '', type: '', resit: false, tbc: false, note: '' });
      state.project = M.cleanProject(JSON.parse(M.projectFile(p)), realToday());
      changed('Added ' + code + '.');
    } else if (kind === 'add-topic') {
      var c = f.getAttribute('data-code');
      var input = f.querySelector('input');
      var txt = input.value.trim();
      if (!txt) return;
      var sp = M.splitTopicAttrs(txt);
      if (!sp.name) return;
      ensureOwnKeep();
      p.topics.push({ id: '', code: c, name: sp.name, conf: sp.conf === null ? 3 : sp.conf, size: sp.size === null ? M.SIZES.m : sp.size, mode: 'full', note: '' });
      M.assignTopicIds(p.topics);
      changed('Added "' + sp.name + '".');
      var again = $('#nt-' + c);
      if (again) again.focus();
    } else if (kind === 'add-override') {
      var d1 = M.fromIso($('#ov-from').value), d2 = M.fromIso($('#ov-to').value);
      if (d1 === null) return;
      if (d2 === null || d2 < d1) d2 = d1;
      var hrs = M.scaleDecimal(String($('#ov-hours').value || '0').trim(), 60) || 0;
      ensureOwnKeep();
      for (var d = d1; d <= d2 && d <= d1 + 366; d++) M.setOverride(p, d, hrs, $('#ov-label').value.trim());
      changed(hrs ? 'Hours changed.' : (d2 > d1 ? 'Days blocked.' : 'Day blocked.'));
    }
  }

  function onKey(ev) {
    var t = ev.target;
    if (t.getAttribute && t.getAttribute('role') === 'tab') {
      var i = VIEWS.indexOf(t.getAttribute('data-view'));
      var n = null;
      if (ev.key === 'ArrowRight') n = (i + 1) % VIEWS.length;
      else if (ev.key === 'ArrowLeft') n = (i + VIEWS.length - 1) % VIEWS.length;
      else if (ev.key === 'Home') n = 0;
      else if (ev.key === 'End') n = VIEWS.length - 1;
      if (n !== null) { ev.preventDefault(); go(VIEWS[n], true); }
    }
  }

  function setupDrops() {
    document.addEventListener('dragover', function (ev) {
      var z = ev.target.closest && ev.target.closest('[data-drop]');
      if (z) { ev.preventDefault(); z.classList.add('over'); }
    });
    document.addEventListener('dragleave', function (ev) {
      var z = ev.target.closest && ev.target.closest('[data-drop]');
      if (z) z.classList.remove('over');
    });
    document.addEventListener('drop', function (ev) {
      var z = ev.target.closest && ev.target.closest('[data-drop]');
      if (!z) return;
      ev.preventDefault();
      z.classList.remove('over');
      var f = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
      var kind = z.getAttribute('data-drop');
      if (!f) {
        var txt = ev.dataTransfer && ev.dataTransfer.getData('text');
        if (txt && kind === 'exams') importExams(txt, 'dropped text');
        if (txt && kind === 'topics') importTopics(txt, 'dropped text', false);
        return;
      }
      readFile(f, function (text) {
        if (kind === 'exams') {
          if (/\.json$/i.test(f.name)) openProjectText(text, f.name); else importExams(text, f.name);
        } else if (kind === 'topics') importTopics(text, f.name, false);
        else if (kind === 'calendar') importCalendar(text, f.name);
        else if (kind === 'availability') importAvailability(text, f.name);
      });
    });
  }

  // ------------------------------------------------------------------
  // Start
  // ------------------------------------------------------------------

  function start() {
    var saved = restore();
    if (saved && (saved.exams.length || saved.topics.length)) {
      state.project = saved;
      state.isSample = false;
      state.restored = true;
      recompute();
    } else {
      loadSample();
    }
    try {
      var al = parseInt(localStorage.getItem(STORE + '-alarm') || '0', 10);
      if (al === 10 || al === 30) state.alarm = al;
    } catch (e) { /* storage blocked */ }
    try {
      var v = localStorage.getItem(STORE + '-view');
      if (v && VIEWS.indexOf(v) >= 0 && state.restored) state.view = v;
    } catch (e) { /* storage blocked */ }
    document.addEventListener('click', onClick);
    document.addEventListener('change', onChange);
    document.addEventListener('submit', onSubmit);
    document.addEventListener('keydown', onKey);
    setupDrops();
    renderAll();
  }

  start();
})();
