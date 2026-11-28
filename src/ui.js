/* Checked by me: the page. Reads what you paste or drop, runs the model and
   draws the views. Everything stays in this page; nothing is fetched or sent. */
(function () {
  'use strict';
  var M = window.CheckedByMe;
  var STORE_KEY = 'checked-by-me/project';
  var VIEWS = ['copy', 'check', 'refs', 'changes', 'declare', 'how'];
  var FIELDS = ['draft', 'final', 'notes', 'references', 'prompt'];
  var EMPTY_PROJECT = { title: '', assignment: '', course: '', institution: '', person: '', date: '', level: 'assisted', template: 'statement' };

  var S = {
    texts: { draft: '', final: '', prompt: '', references: '', notes: '' },
    sessions: [], project: copy(EMPTY_PROJECT), checks: {}, refChecks: {},
    analysis: null, summary: null, view: 'check', isSample: false, dirty: false,
    filter: { risk: 'all', kind: 'all', status: 'all', conflicts: false, order: 'risk', since: false }, baseline: { text: '', on: '' }, versions: null,
    showDiff: true, sessionMsgs: [], fieldMsgs: {}, editing: -1, showAllSessions: true, pickField: null
  };
  var today = todayDay();

  // ---------------------------------------------------------------- small helpers

  function $(id) { return document.getElementById(id); }
  function copy(o) { return JSON.parse(JSON.stringify(o)); }
  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function todayDay() {
    var d = new Date();
    return M.daysFromCivil(d.getFullYear(), d.getMonth() + 1, d.getDate());
  }
  function say(text) { var l = $('live'); l.textContent = ''; setTimeout(function () { l.textContent = text; }, 30); }
  function storeGet() { try { return window.localStorage.getItem(STORE_KEY); } catch (e) { return null; } }
  function storeSet(v) { try { window.localStorage.setItem(STORE_KEY, v); return true; } catch (e) { return false; } }
  function storeDrop() { try { window.localStorage.removeItem(STORE_KEY); } catch (e) { /* storage blocked */ } }
  function wordsIn(text) { var m = String(text || '').match(/[A-Za-z0-9\u00c0-\u017f']+/g); return m ? m.length : 0; }
  function slugName(s) {
    var t = String(s || 'checked-by-me').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    return (t || 'checked-by-me').slice(0, 60);
  }
  function plural(n, one, many) { return M.plural(n, one, many); }

  function download(name, text, type) {
    var blob = new Blob([text], { type: type || 'text/plain;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = name; a.rel = 'noopener';
    document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1500);
    say('Downloaded ' + name);
  }

  function copyText(text, done) {
    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      ta.remove();
      done(ok);
    }
    try {
      if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(function () { done(true); }, fallback);
      else fallback();
    } catch (e) { fallback(); }
  }

  var timers = {};
  function later(name, ms, fn) { clearTimeout(timers[name]); timers[name] = setTimeout(fn, ms); }

  // ---------------------------------------------------------------- state in and out

  function state() {
    return { project: S.project, texts: S.texts, sessions: S.sessions, checks: S.checks, refChecks: S.refChecks, asOf: today, baseline: S.baseline };
  }

  function loadProject(p, opts) {
    opts = opts || {};
    S.project = Object.assign(copy(EMPTY_PROJECT), p.project || {});
    FIELDS.forEach(function (f) { S.texts[f] = (p.texts && p.texts[f]) || ''; });
    S.sessions = (p.sessions || []).map(M.cleanSession);
    S.checks = p.checks || {};
    S.refChecks = p.refChecks || {};
    S.baseline = p.baseline && p.baseline.text ? { text: p.baseline.text, on: p.baseline.on || '' } : { text: '', on: '' };
    S.isSample = !!opts.sample;
    S.dirty = false;
    S.sessionMsgs = []; S.fieldMsgs = {}; S.editing = -1;
    FIELDS.forEach(function (f) { $('in-' + f).value = S.texts[f]; });
    analyseNow();
  }

  function checkedText() { return S.texts.final.trim() ? S.texts.final : S.texts.draft; }

  function changed() {
    S.dirty = true;
    if (S.isSample) S.isSample = false;
    later('save', 400, function () { storeSet(M.projectFile(state())); });
  }

  function analyseNow() {
    var input = { asOf: today };
    FIELDS.forEach(function (f) { input[f] = S.texts[f]; });
    S.analysis = M.analyse(input);
    S.summary = M.summarise(S.analysis, S.checks, S.refChecks);
    S.versions = S.baseline.text && S.baseline.text.trim() !== checkedText().trim() ? M.compareVersions(S.baseline.text, S.analysis, S.checks) : null;
    renderAll();
  }

  // ---------------------------------------------------------------- hero picture

  var LINE_W = [262, 248, 270, 231, 266, 120, 255, 268, 240, 262, 250, 182, 266, 244, 258, 236, 140];

  function topClaim() {
    var a = S.analysis;
    if (!a) return null;
    for (var i = 0; i < a.ranked.length; i++) {
      var c = a.claims[a.ranked[i] - 1];
      if (M.statusOf(S.checks, c.key) === 'unchecked') return c;
    }
    return a.claims.length ? a.claims[a.ranked[0] - 1] : null;
  }

  function figureOf(c) {
    if (!c) return 'checked';
    var order = ['statistic', 'leftover', 'quote', 'date', 'citation', 'person', 'org', 'absolute', 'legal', 'medical', 'financial', 'vague', 'url', 'study'];
    for (var i = 0; i < order.length; i++) {
      for (var j = 0; j < c.spans.length; j++) {
        if (c.spans[j].kind === order[i]) {
          var t = c.spans[j].text;
          if (order[i] === 'statistic') {
            var after = c.text.slice(c.spans[j].end).match(/^ ?([A-Za-z\u00c0-\u017f]+)/);
            if (after && !/^(?:of|a|an|the|and|in|on|by|to|per|from)$/i.test(after[1]) && t.length < 9) t += ' ' + after[1];
          }
          if (order[i] === 'quote') { var w = t.split(' ').slice(0, 2).join(' '); return '\u201c' + (w.length > 10 ? w.slice(0, 9) : w) + '\u2026\u201d'; }
          return t.length > 12 ? t.slice(0, 11) + '\u2026' : t;
        }
      }
    }
    return 'Qy ' + c.q;
  }

  function heroSvg() {
    var a = S.analysis, sum = S.summary;
    var claims = a ? a.claims : [];
    var total = a ? Math.max(1, a.sentences.length) : 1;
    var lines = '', marks = '';
    var y0 = 86, step = 18.5;
    for (var i = 0; i < LINE_W.length; i++) {
      var y = y0 + i * step, x = (i === 0 || i === 6 || i === 12) ? 196 : 182, w = LINE_W[i] - (x - 182);
      lines += '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="5.5" rx="2" fill="#a99f8c" opacity=".62"/>';
    }
    var used = {};
    var shown = claims.slice(0, 40);
    var top = topClaim();
    var loupeLine = 3;
    for (var k = 0; k < shown.length; k++) {
      var c = shown[k];
      var li = Math.min(LINE_W.length - 1, Math.floor(c.sentence * LINE_W.length / total));
      while (used[li] && li < LINE_W.length - 1) li++;
      if (used[li]) continue;
      used[li] = true;
      var ly = y0 + li * step + 2.75, st = M.statusOf(S.checks, c.key);
      var lx = 196 + ((c.q * 37) % 120), lw = 46 + ((c.q * 13) % 34);
      if (top && c.q === top.q) loupeLine = li;
      if (st === 'verified') {
        marks += '<path d="M150 ' + (ly - 1) + ' l6 6 l12 -13" fill="none" stroke="#2c7149" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>';
      } else if (st === 'corrected') {
        marks += '<path d="M' + (lx + lw) + ' ' + (ly + 6) + ' l5 -10 l5 10" fill="none" stroke="#285a9c" stroke-width="2.4" stroke-linecap="round"/>' +
          '<path d="M464 ' + (ly - 4) + ' q8 -6 16 0" fill="none" stroke="#285a9c" stroke-width="2.2"/><text x="468" y="' + (ly + 8) + '" font-family="Spline Sans Mono, monospace" font-size="10" fill="#285a9c">ok</text>';
      } else if (st === 'removed') {
        marks += '<line x1="' + lx + '" y1="' + ly + '" x2="' + (lx + lw) + '" y2="' + ly + '" stroke="#b8322a" stroke-width="2.4"/>' +
          '<path d="M468 ' + (ly + 4) + ' c-6 -10 10 -14 9 -3 c-1 7 -9 7 -6 -1 l6 -9" fill="none" stroke="#b8322a" stroke-width="2"/>';
      } else {
        var col = c.level === 'high' ? '#b8322a' : (c.level === 'medium' ? '#a86d17' : '#857c6c');
        marks += '<ellipse cx="' + (lx + lw / 2) + '" cy="' + ly + '" rx="' + (lw / 2 + 6) + '" ry="8.5" fill="none" stroke="' + col + '" stroke-width="2" transform="rotate(-3 ' + (lx + lw / 2) + ' ' + ly + ')"/>' +
          '<path d="M' + (lx + lw + 6) + ' ' + ly + ' Q' + (lx + lw + 40) + ' ' + (ly - 10) + ' 466 ' + ly + '" fill="none" stroke="' + col + '" stroke-width="1.4"/>' +
          '<circle cx="476" cy="' + ly + '" r="9" fill="#fffaf0" stroke="' + col + '" stroke-width="2"/><text x="476" y="' + (ly + 4) + '" text-anchor="middle" font-family="Spline Sans Mono, monospace" font-weight="600" font-size="11" fill="' + col + '">?</text>';
      }
    }
    var fig = figureOf(top);
    var openQ = sum ? sum.unchecked : 0;
    var complete = sum && sum.complete;
    var ly2 = y0 + loupeLine * step;
    var lcx = 306, lcy = Math.max(150, Math.min(268, ly2 + 34));
    var slug = (S.project.assignment || S.project.title || 'Your draft').toUpperCase().slice(0, 30);
    var stamp = complete
      ? '<g transform="translate(372 352) rotate(-11)" filter="url(#rough)" opacity=".9"><rect x="-86" y="-40" width="172" height="80" rx="8" fill="none" stroke="#2c7149" stroke-width="4"/>' +
        '<rect x="-79" y="-33" width="158" height="66" rx="5" fill="none" stroke="#2c7149" stroke-width="1.5"/>' +
        '<text x="0" y="-12" text-anchor="middle" font-family="Spline Sans Mono, monospace" font-weight="600" font-size="11" letter-spacing="2" fill="#2c7149">PASSED FOR PRESS</text>' +
        '<text x="0" y="12" text-anchor="middle" font-family="Instrument Serif, Georgia, serif" font-size="25" fill="#2c7149">Checked by me</text>' +
        '<text x="0" y="28" text-anchor="middle" font-family="Spline Sans Mono, monospace" font-size="9.5" fill="#2c7149">' + esc(M.longDay(today).toUpperCase()) + '</text></g>'
      : '<g transform="translate(380 366) rotate(-6)"><rect x="-78" y="-30" width="156" height="60" rx="7" fill="rgba(255,250,240,.5)" stroke="#857c6c" stroke-width="1.6" stroke-dasharray="5 4"/>' +
        '<text x="0" y="-6" text-anchor="middle" font-family="Spline Sans Mono, monospace" font-size="10" letter-spacing="1.5" fill="#6a645b">SIGN-OFF STAMP</text>' +
        '<text x="0" y="12" text-anchor="middle" font-family="Spline Sans Mono, monospace" font-size="10" fill="#6a645b">' + esc(openQ ? plural(openQ, 'query', 'queries') + ' open' : 'references to check') + '</text></g>';
    return '<svg viewBox="0 0 600 440" role="img" aria-label="A galley proof with red-pen queries, a loupe over ' + esc(fig) + ', a red pen, a blue pencil and ' + (complete ? 'a signed-off proof stamp' : 'a space for the sign-off stamp') + '">' +
      '<defs><radialGradient id="glass" cx="38%" cy="32%" r="75%"><stop offset="0" stop-color="#fff" stop-opacity=".55"/><stop offset=".5" stop-color="#fff" stop-opacity=".08"/><stop offset="1" stop-color="#cfe1f0" stop-opacity=".22"/></radialGradient>' +
      '<linearGradient id="paperg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fbf6e9"/><stop offset="1" stop-color="#eee4cc"/></linearGradient>' +
      '<filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="7"/></filter>' +
      '<filter id="rough"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="4"/><feDisplacementMap in="SourceGraphic" scale="2.4"/></filter>' +
      '<clipPath id="lens"><circle cx="0" cy="0" r="56"/></clipPath></defs>' +
      '<ellipse cx="318" cy="420" rx="230" ry="16" fill="#000" opacity=".35" filter="url(#soft)"/>' +
      '<g transform="rotate(-4 318 230)">' +
      '<rect x="146" y="22" width="352" height="398" fill="#000" opacity=".35" filter="url(#soft)" transform="translate(6 10)"/>' +
      '<rect x="140" y="18" width="352" height="398" fill="url(#paperg)"/>' +
      '<rect x="140" y="18" width="352" height="398" fill="none" stroke="#d6c8a8"/>' +
      '<text x="182" y="46" font-family="Spline Sans Mono, monospace" font-size="9.5" letter-spacing="1.6" fill="#776d5e">GALLEY 1 \u00b7 ' + esc(slug) + '</text>' +
      '<line x1="182" y1="56" x2="452" y2="56" stroke="#1f1b16" stroke-width="1.2"/>' +
      '<g stroke="#b5a98f" stroke-width="1.1" fill="none"><circle cx="160" cy="38" r="6"/><path d="M160 28v20M150 38h20"/><circle cx="472" cy="398" r="6"/><path d="M472 388v20M462 398h20"/></g>' +
      '<line x1="458" y1="66" x2="458" y2="404" stroke="#d6c8a8" stroke-dasharray="2 4"/>' +
      lines + marks + stamp + '</g>' +
      '<g transform="translate(70 300) rotate(-32)"><rect x="0" y="-7" width="214" height="14" rx="7" fill="#b8322a"/><rect x="150" y="-7" width="64" height="14" rx="5" fill="#7d1f19"/><rect x="160" y="-11" width="40" height="4" rx="2" fill="#d9a441"/>' +
      '<path d="M0 -7 L-20 -2 L-26 0 L-20 2 L0 7 Z" fill="#e8dcc0"/><path d="M-20 -2 L-26 0 L-20 2 Z" fill="#1f1b16"/><rect x="8" y="-4" width="120" height="2" rx="1" fill="#fff" opacity=".25"/></g>' +
      '<g transform="translate(500 120) rotate(64)"><rect x="0" y="-6.5" width="190" height="13" fill="#285a9c"/><rect x="0" y="-1" width="190" height="2.5" fill="#1d4477"/>' +
      '<path d="M0 -6.5 L-26 0 L0 6.5 Z" fill="#e6cf9d"/><path d="M-17 -2.2 L-26 0 L-17 2.2 Z" fill="#285a9c"/><rect x="186" y="-6.5" width="8" height="13" fill="#c9c3b5"/></g>' +
      '<g transform="translate(' + lcx + ' ' + lcy + ')">' +
      '<circle cx="8" cy="12" r="70" fill="#000" opacity=".3" filter="url(#soft)"/>' +
      '<g clip-path="url(#lens)"><rect x="-60" y="-60" width="120" height="120" fill="#fbf6e9"/>' +
      '<text x="0" y="8" text-anchor="middle" font-family="Instrument Serif, Georgia, serif" font-size="' + (fig.length > 9 ? 22 : (fig.length > 6 ? 27 : 34)) + '" fill="#1f1b16">' + esc(fig) + '</text>' +
      '<path d="M-46 20 q6 -5 12 0 t12 0 t12 0 t12 0 t12 0 t12 0 t12 0" fill="none" stroke="#b8322a" stroke-width="2.6"/>' +
      '<text x="0" y="-26" text-anchor="middle" font-family="Spline Sans Mono, monospace" font-size="10" letter-spacing="1" fill="#776d5e">' + esc(top ? 'QY ' + top.q + ' \u00b7 ' + top.level.toUpperCase() : 'ALL CLEAR') + '</text></g>' +
      '<circle r="56" fill="url(#glass)"/>' +
      '<circle r="62" fill="none" stroke="#1d1916" stroke-width="12"/><circle r="56.5" fill="none" stroke="#b8893a" stroke-width="2.5"/>' +
      '<path d="M-40 -30 A50 50 0 0 1 -6 -50" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" opacity=".55"/>' +
      '<rect x="52" y="-9" width="22" height="18" rx="4" fill="#1d1916" transform="rotate(35)"/></g>' +
      '</svg>';
  }

  // ---------------------------------------------------------------- figures under the hero

  var MARK_SVG = {
    query: '<svg class="slip-mark" viewBox="0 0 30 30" aria-hidden="true"><circle cx="15" cy="15" r="12" fill="none" stroke="#b8322a" stroke-width="2.4"/><text x="15" y="20" text-anchor="middle" font-family="Spline Sans Mono, monospace" font-weight="600" font-size="14" fill="#b8322a">?</text></svg>',
    tick: '<svg class="slip-mark" viewBox="0 0 30 30" aria-hidden="true"><path d="M6 16 l6 6 l12 -14" fill="none" stroke="#2c7149" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    caret: '<svg class="slip-mark" viewBox="0 0 30 30" aria-hidden="true"><path d="M7 23 l8 -16 l8 16" fill="none" stroke="#285a9c" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    bracket: '<svg class="slip-mark" viewBox="0 0 30 30" aria-hidden="true"><path d="M11 5 h-5 v20 h5 M19 5 h5 v20 h-5" fill="none" stroke="#b8322a" stroke-width="2.4"/></svg>'
  };

  function slip(cls, key, value, small, detail, mark, view) {
    return '<div class="slip ' + cls + '">' + MARK_SVG[mark] + '<p class="slip-k">' + esc(key) + '</p><p class="slip-v">' + value +
      (small ? ' <small>' + small + '</small>' : '') + '</p><p class="slip-d">' + detail +
      (view ? ' <button type="button" class="linkish" data-go="' + view + '">Open</button>' : '') + '</p></div>';
  }

  function renderSlips() {
    var a = S.analysis, s = S.summary, out = '';
    if (!a || !a.sentences.length) {
      out += slip('', 'Queries open', '0', '', 'Paste a draft to start.', 'query', 'copy');
      out += slip('', 'Against your notes', '\u2013', '', 'Add your notes to compare figures.', 'bracket', 'copy');
      out += slip('', 'References', '\u2013', '', 'No reference list yet.', 'bracket', 'copy');
      out += slip('', 'AI wording kept', '\u2013', '', 'Add your final version to compare.', 'caret', 'copy');
      $('slips').innerHTML = out;
      return;
    }
    var next = topClaim();
    out += slip(s.highUnchecked ? 'hot' : (s.unchecked ? '' : 'good'), 'Queries open', String(s.unchecked), 'of ' + s.claims,
      s.unchecked ? esc(s.highUnchecked + ' high risk still open' + (next && M.statusOf(S.checks, next.key) === 'unchecked' ? '. Next: Qy ' + next.q + '.' : '.')) : 'Every flagged statement is marked.',
      s.unchecked ? 'query' : 'tick', 'check');
    if (a.notesGiven) {
      out += slip(s.conflicts ? 'hot' : 'good', 'Against your notes', String(s.conflicts), s.conflicts === 1 ? 'conflict' : 'conflicts',
        s.conflicts ? 'Figures or quotes in the text that your notes disagree with.' : 'No figure or quote clashes with your notes.', 'bracket', 'check');
    } else {
      out += slip('', 'Against your notes', '\u2013', '', 'Add your notes or sources to compare figures and quotes.', 'bracket', 'copy');
    }
    if (s.refs || s.refMissing) {
      var missing = s.refMissing ? ', ' + s.refMissing + ' cited but missing' : '';
      out += slip(s.refUnresolved || s.refMissing ? 'hot' : 'good', 'References', String(s.refUnresolved), 'of ' + s.refs + ' to look at',
        esc((s.refSuspect ? s.refSuspect + ' look made up' : 'None look made up') + missing + '.'), 'bracket', 'refs');
    } else {
      out += slip('', 'References', '\u2013', '', 'No reference list found.', 'bracket', 'copy');
    }
    if (a.changes) {
      var ch = a.changes;
      out += slip('blue', 'AI wording kept', ch.keptShare + '%', 'of your final', esc(ch.counts.kept + ' of ' + ch.finalSentences + ' sentences kept word for word, ' + ch.counts.yours + ' your own.'), 'caret', 'changes');
    } else {
      out += slip('', 'AI wording kept', '\u2013', '', 'Add your final version to compare it with the AI draft.', 'caret', 'copy');
    }
    $('slips').innerHTML = out;
  }

  function renderHead() {
    $('hero-art').innerHTML = heroSvg();
    var p = S.project;
    var bits = ['Galley 1'];
    if (p.assignment) bits.push(p.assignment);
    if (p.person) bits.push('Reader: ' + p.person);
    bits.push(M.longDay(today));
    $('slug').textContent = bits.join(' \u00b7 ');
    $('pb-title').innerHTML = (S.isSample ? 'Sample project: ' : 'Project: ') + '<strong>' + esc(p.title || p.assignment || 'Untitled') + '</strong>' +
      (S.analysis && S.analysis.sentences.length ? ' \u00b7 ' + esc(plural(S.analysis.words, 'word')) + ' checked in your ' + (S.analysis.hasFinal ? 'final version' : 'AI draft') : '');
    var s = S.summary, a = S.analysis;
    var tc = $('ts-check');
    tc.textContent = s && s.claims ? (s.unchecked ? s.unchecked + ' open, ' + s.highUnchecked + ' high' : 'All marked') : 'Claims to check';
    tc.className = 'ts' + (s && s.highUnchecked ? ' alert' : '');
    var tr = $('ts-refs');
    tr.textContent = s && (s.refs || s.refMissing) ? (s.refUnresolved ? s.refUnresolved + ' to look at' : (s.refMissing ? s.refMissing + ' cited, not listed' : 'All looked at')) : 'Your list';
    tr.className = 'ts' + (s && s.refUnresolved ? ' alert' : '');
    $('ts-changes').textContent = a && a.changes ? a.changes.keptShare + '% AI wording' : 'AI draft to final';
    $('ts-declare').textContent = S.sessions.length ? plural(M.sessionsFor(S.sessions, p.assignment).length, 'session') : 'Log and statement';
  }

  function renderNotice() {
    var n = $('notice');
    if (S.restoreOffer) n.innerHTML = S.restoreOffer;
    else if (S.isSample) {
      n.innerHTML = '<div class="note-card"><p>You are looking at an invented student\'s essay section and AI session log, partly checked: four statements verified, the rest still open. Everything is made up, including the AI tools.</p><button type="button" class="btn small" data-own="1">Use your own text</button></div>';
    } else n.innerHTML = '';
  }

  // ---------------------------------------------------------------- views

  function setView(v, focus) {
    if (VIEWS.indexOf(v) < 0) v = 'check';
    S.view = v;
    VIEWS.forEach(function (name) {
      var tab = $('tab-' + (name === 'declare' ? 'declare' : name));
      var on = name === v;
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
      $('view-' + name).hidden = !on;
    });
    try { history.replaceState(null, '', '#' + v); } catch (e) { /* file pages may refuse */ }
    renderView();
    if (focus) $('tab-' + v).focus();
  }

  function renderView() {
    if (S.view === 'check') renderCheck();
    else if (S.view === 'refs') renderRefs();
    else if (S.view === 'changes') renderChanges();
    else if (S.view === 'declare') renderDeclare();
    else if (S.view === 'copy') renderCopy();
    else if (S.view === 'how') renderHow();
  }

  function renderAll() {
    renderHead();
    renderSlips();
    renderNotice();
    renderView();
  }

  // keeps keyboard focus on the same control after a view is redrawn
  function keepFocus(fn) {
    var act = document.activeElement, id = act && act.id;
    var pos = act && typeof act.selectionStart === 'number' ? act.selectionStart : null;
    fn();
    if (id && $(id) && $(id) !== act) {
      $(id).focus();
      if (pos !== null && typeof $(id).setSelectionRange === 'function') { try { $(id).setSelectionRange(pos, pos); } catch (e) { /* not a text box */ } }
    }
  }

  // ---------------------------------------------------------------- your texts

  var CLEAN_WORDS = { quotes: 'smart quote', markdown: 'Markdown mark', footnotes: 'footnote marker', spaces: 'odd space', invisible: 'invisible character', symbols: 'emoji or symbol', ligatures: 'ligature', html: 'block of HTML' };

  function cleaningText(counts) {
    var bits = [];
    Object.keys(CLEAN_WORDS).forEach(function (k) {
      if (counts && counts[k]) bits.push(plural(counts[k], CLEAN_WORDS[k]));
    });
    return bits.length ? 'Tidied ' + M.listAnd(bits) + '.' : '';
  }

  function renderCopy() {
    var a = S.analysis;
    FIELDS.forEach(function (f) {
      var t = S.texts[f];
      $('count-' + f).textContent = t ? plural(wordsIn(t), 'word') : 'empty';
      var msg = S.fieldMsgs[f] || '';
      if (a && f === 'draft' && t) msg = (msg ? msg + ' ' : '') + cleaningText(a.cleaning.draft);
      if (a && f === 'final' && t) msg = (msg ? msg + ' ' : '') + cleaningText(a.cleaning.final);
      if (a && f === 'references' && t && a.refs.source === 'list') {
        msg = (msg ? msg + ' ' : '') + (a.refs.format === 'text' ? plural(a.refs.entries.length, 'entry', 'entries') + ' read.'
          : plural(a.refs.entries.length, 'record') + ' read from a ' + (a.refs.format === 'ris' ? 'RIS' : 'BibTeX') + ' export' + (a.refs.entries.some(function (r) { return r.entry.citeKey; }) ? ', with citation keys for [@key] or \\cite{key} citations.' : '.'));
      }
      if (a && f === 'notes' && t) msg = (msg ? msg + ' ' : '') + plural(a.notesSentences, 'line') + ' of notes to compare against.';
      if (a && f === 'prompt' && t) {
        var asks = [];
        if (a.prompt.asksStats) asks.push('statistics');
        if (a.prompt.asksSources) asks.push('references');
        if (a.prompt.asksQuotes) asks.push('quotations');
        if (asks.length) msg = (msg ? msg + ' ' : '') + 'You asked for ' + M.listAnd(asks) + ': those claims are flagged harder.';
      }
      var el = $('msg-' + f);
      el.textContent = msg;
      el.className = 'tray-msg' + (S.fieldMsgs[f + 'Err'] ? ' err' : '');
    });
    $('count-sessions').textContent = plural(S.sessions.length, 'session');
    $('msg-sessions').innerHTML = S.sessionMsgs.map(function (m) { return '<li' + (m.err ? ' class="err"' : '') + '>' + esc(m.text) + '</li>'; }).join('');
    if (a && a.messages.length) {
      $('msg-draft').textContent = ($('msg-draft').textContent ? $('msg-draft').textContent + ' ' : '') + a.messages.join(' ');
    }
  }

  // ---------------------------------------------------------------- check

  var STATUS_SVG = {
    verified: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 13 l5 5 l11 -12" fill="none" stroke="#2c7149" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    corrected: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 19 l7 -14 l7 14" fill="none" stroke="#285a9c" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    removed: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 18 c-2 -9 9 -12 10 -5 c1 5 -6 6 -5 1 c1 -4 6 -6 9 -10" fill="none" stroke="#b8322a" stroke-width="2.2" stroke-linecap="round"/></svg>',
    checked: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 13 l5 5 l11 -12" fill="none" stroke="#2c7149" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    fixed: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 19 l7 -14 l7 14" fill="none" stroke="#285a9c" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>'
  };
  var STATUS_WORD = { verified: 'Verified', corrected: 'Corrected', removed: 'Removed', checked: 'Checked', fixed: 'Fixed' };
  var KIND_PRIORITY = ['leftover', 'statistic', 'financial', 'quote', 'legal', 'medical', 'vague', 'absolute', 'citation', 'person', 'org', 'study', 'date', 'url'];

  function markedText(text, spans) {
    if (!spans.length) return esc(text);
    var cuts = [0, text.length];
    spans.forEach(function (s) { cuts.push(s.start, s.end); });
    cuts = cuts.filter(function (v, i, arr) { return arr.indexOf(v) === i; }).sort(function (x, y) { return x - y; });
    var out = '';
    for (var i = 0; i < cuts.length - 1; i++) {
      var a = cuts[i], b = cuts[i + 1], kinds = [];
      spans.forEach(function (s) { if (s.start <= a && s.end >= b && kinds.indexOf(s.kind) < 0) kinds.push(s.kind); });
      var piece = esc(text.slice(a, b));
      if (!kinds.length) { out += piece; continue; }
      kinds.sort(function (x, y) { return KIND_PRIORITY.indexOf(x) - KIND_PRIORITY.indexOf(y); });
      out += '<span class="mk mk-' + kinds[0] + '" title="' + esc(kinds.map(function (k) { return M.KIND_LABELS[k]; }).join(', ')) + '">' + piece + '</span>';
    }
    return out;
  }

  var ORIGIN_WORD = { kept: 'Kept from the AI', edited: 'Edited from the AI', reworded: 'Reworded from the AI', yours: 'Your own words' };
  var NOTES_WORD = { conflict: 'Notes disagree', match: 'Matches your notes', partial: 'Partly in your notes', missing: 'Not in your notes', related: 'Related note' };

  function versionOf(c) {
    var v = S.versions;
    if (!v) return null;
    if (v.newClaims.indexOf(c.q) >= 0) return { kind: 'new' };
    for (var i = 0; i < v.changed.length; i++) if (v.changed[i].q === c.q) return { kind: 'edited', info: v.changed[i] };
    return null;
  }

  function claimHtml(c) {
    var ck = S.checks[c.key] || {}, st = M.statusOf(S.checks, c.key);
    var tags = c.kinds.map(function (k) { return '<li class="tag k-' + k + '">' + esc(M.KIND_LABELS[k]) + '</li>'; }).join('');
    var ver = versionOf(c), verBox = '';
    if (ver) tags = '<li class="tag v-' + ver.kind + '">' + (ver.kind === 'new' ? 'New since last check' : 'Edited since last check') + '</li>' + tags;
    if (ver && ver.kind === 'edited') {
      var was = ver.info.status !== 'unchecked' ? 'Before your edit it was marked ' + STATUS_WORD[ver.info.status].toLowerCase() + (ver.info.note ? ' ("' + ver.info.note + '")' : '') + '. That mark belonged to the old wording, so check it again.' : 'The old wording was not marked.';
      verBox = '<div class="q-note-box was"><b>Since your last check</b><p class="sx">' + opsHtml(ver.info.ops) + '</p><p>' + esc(was) + '</p></div>';
    }
    if (c.origin) tags += '<li class="tag o-' + c.origin + '">' + esc(ORIGIN_WORD[c.origin]) + '</li>';
    if (c.notes.status !== 'none') tags += '<li class="tag n-' + c.notes.status + '">' + esc(NOTES_WORD[c.notes.status]) + '</li>';
    var noteBox = '';
    var nt = c.notes;
    if (nt.status === 'conflict') {
      var bits = nt.items.filter(function (it) { return it.result === 'conflict'; }).map(function (it) {
        return '<p>' + (it.what === 'the quotation' ? 'Your notes give the quotation as <q>' + esc(it.note) + '</q>' : 'The text says <strong>' + esc(it.what) + '</strong>; your note says: <q>' + esc(it.note) + '</q>') + '</p>';
      }).join('');
      noteBox = '<div class="q-note-box conflict"><b>Your notes disagree</b>' + bits + '</div>';
    } else if (nt.status === 'match' || nt.status === 'partial') {
      var m = nt.items.filter(function (it) { return it.result === 'match'; })[0];
      noteBox = '<div class="q-note-box match"><b>' + (nt.status === 'match' ? 'Matches your notes' : 'Partly in your notes') + '</b><q>' + esc(m.note) + '</q></div>';
    } else if (nt.related) {
      noteBox = '<div class="q-note-box"><b>Closest note</b><q>' + esc(nt.related) + '</q></div>';
    }
    var why = c.reasons.map(function (r) {
      return '<li><span class="pts' + (r.points < 0 ? ' neg' : '') + '">' + (r.points > 0 ? '+' : '') + r.points + '</span><span>' + esc(r.text) + '</span></li>';
    }).join('');
    var acts = ['verified', 'corrected', 'removed'].map(function (k) {
      return '<button type="button" class="mark-btn m-' + k + '" id="mk-' + c.key + '-' + k + '" data-act="mark" data-key="' + c.key + '" data-status="' + k + '" aria-pressed="' + (st === k ? 'true' : 'false') + '">' + STATUS_SVG[k] + '<span>' + STATUS_WORD[k] + '</span></button>';
    }).join('');
    return '<li class="query lvl-' + c.level + ' st-' + st + '" id="q' + c.q + '">' +
      '<div class="q-left"><span class="qy"><span>Qy</span><b>' + c.q + '</b></span><span class="q-risk">' + c.level + ' \u00b7 ' + c.score + '</span></div>' +
      '<div class="q-body"><p class="q-text">' + markedText(c.text, c.spans) + '</p><ul class="q-tags">' + tags + '</ul>' + verBox + noteBox +
      '<ul class="q-todo">' + c.checks.map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('') + '</ul>' +
      '<details class="q-why"><summary>Why it is flagged: score ' + c.score + '</summary><ul class="why">' + why + '</ul></details></div>' +
      '<div class="q-right"><div class="q-acts" role="group" aria-label="Mark query ' + c.q + '">' + acts + '</div>' +
      '<label class="q-note-field" for="nt-' + c.key + '"><span>Source or note</span><input type="text" id="nt-' + c.key + '" data-act="note" data-key="' + c.key + '" value="' + esc(ck.note || '') + '" placeholder="Where you checked it"></label>' +
      (st !== 'unchecked' && ck.on ? '<p class="q-done">' + esc(STATUS_WORD[st]) + ' on ' + esc(ck.on) + '</p>' : '') + '</div></li>';
  }

  function renderCheck() {
    var a = S.analysis, s = S.summary, box = $('check-body');
    if (!a || !a.sentences.length) {
      $('check-slug').textContent = 'Nothing to check yet';
      box.innerHTML = '<div class="empty"><h3>No text to check yet</h3><p>Paste the AI\'s draft (and your final version, if you have one) on the Your texts page. The checklist appears here as you type.</p><button type="button" class="btn primary" data-go="copy">Paste your texts</button></div>';
      return;
    }
    $('check-slug').textContent = 'Checking your ' + (a.hasFinal ? 'final version' : 'AI draft') + ' \u00b7 ' + plural(a.sentences.length, 'sentence');
    if (!a.claims.length) {
      box.innerHTML = '<div class="empty"><h3>Nothing flagged</h3><p>No sentence has a figure, date, name, quotation, citation, link, absolute wording, a legal, health or money point, or leftover chat text. Read it through anyway: plain-word claims are not flagged.</p></div>';
      return;
    }
    var f = S.filter;
    var list = (f.order === 'risk' ? a.ranked.map(function (q) { return a.claims[q - 1]; }) : a.claims.slice()).filter(function (c) {
      var st = M.statusOf(S.checks, c.key);
      return (f.risk === 'all' || c.level === f.risk) && (f.kind === 'all' || c.kinds.indexOf(f.kind) >= 0) &&
        (f.status === 'all' || (f.status === 'open' ? st === 'unchecked' : st === f.status)) && (!f.conflicts || c.notes.status === 'conflict') &&
        (!f.since || !!versionOf(c));
    });
    var total = Math.max(1, s.claims);
    var segs = [['verified', s.verified], ['corrected', s.corrected], ['removed', s.removed]];
    var openBy = { high: 0, medium: 0, low: 0 };
    a.claims.forEach(function (c) { if (M.statusOf(S.checks, c.key) === 'unchecked') openBy[c.level]++; });
    segs.push(['high', openBy.high], ['medium', openBy.medium], ['low', openBy.low]);
    var bar = segs.map(function (g) { return g[1] ? '<span class="c-' + g[0] + '" style="width:' + (g[1] * 100 / total) + '%" title="' + esc(g[0] + ': ' + g[1]) + '"></span>' : ''; }).join('');
    var legend = segs.map(function (g) {
      var label = { verified: 'verified', corrected: 'corrected', removed: 'removed', high: 'open, high', medium: 'open, medium', low: 'open, low' }[g[0]];
      return '<span><i class="sw c-' + g[0] + '"></i>' + g[1] + ' ' + label + '</span>';
    }).join('');
    var kindsPresent = M.KIND_ORDER.filter(function (k) { return a.claims.some(function (c) { return c.kinds.indexOf(k) >= 0; }); });
    var lede = s.unchecked
      ? plural(s.claims, 'statement') + ' worth checking, <strong>' + s.high + ' high risk</strong>. ' + s.resolved + ' marked, ' + s.unchecked + ' to go.'
      : 'All ' + plural(s.claims, 'statement') + ' are marked. ' + (s.refUnresolved ? 'Now look at the references.' : 'Ready to sign off.');
    var html = '<div class="ledger"><div><p class="ledger-lede">' + lede + '</p><div class="meter"><div class="meter-bar" role="img" aria-label="' + esc(s.resolved + ' of ' + s.claims + ' marked') + '">' + bar + '</div><div class="meter-legend">' + legend + '</div></div></div>' +
      '<div><p class="small">Work down from the top. Mark <strong>Verified</strong> only when you have seen the original source, <strong>Corrected</strong> when you fixed the text, or <strong>Removed</strong> when you cut it. Your marks are kept with the project; the checker itself looks nothing up.</p>' +
      '<div class="tools-row"><button type="button" class="btn small" data-act="md-proof">Proof copy (.md)</button><button type="button" class="btn small" data-act="csv-claims">Checklist (.csv)</button><button type="button" class="btn small" data-act="print">Print the proof report</button></div></div></div>';
    html += sinceHtml();
    html += '<div class="filters" role="group" aria-label="Filter the checklist"><fieldset><legend>Risk</legend><div class="chips">' +
      ['all', 'high', 'medium', 'low'].map(function (r) { return '<button type="button" class="chip" id="fr-' + r + '" data-act="risk" data-risk="' + r + '" aria-pressed="' + (f.risk === r) + '">' + (r === 'all' ? 'All' : r.charAt(0).toUpperCase() + r.slice(1)) + '</button>'; }).join('') + '</div></fieldset>' +
      '<label><span>What it is</span><select id="f-kind" data-act="kind"><option value="all">Everything</option>' + kindsPresent.map(function (k) { return '<option value="' + k + '"' + (f.kind === k ? ' selected' : '') + '>' + esc(M.KIND_LABELS[k]) + '</option>'; }).join('') + '</select></label>' +
      '<label><span>Status</span><select id="f-status" data-act="status-filter">' + [['all', 'Any'], ['open', 'Still open'], ['verified', 'Verified'], ['corrected', 'Corrected'], ['removed', 'Removed']].map(function (o) { return '<option value="' + o[0] + '"' + (f.status === o[0] ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('') + '</select></label>' +
      '<label><span>Order</span><select id="f-order" data-act="order"><option value="risk"' + (f.order === 'risk' ? ' selected' : '') + '>Highest risk first</option><option value="text"' + (f.order === 'text' ? ' selected' : '') + '>As in the text</option></select></label>' +
      (a.notesGiven ? '<label class="check-inline"><input type="checkbox" id="f-conf" data-act="conflicts"' + (f.conflicts ? ' checked' : '') + '> Only where my notes disagree</label>' : '') +
      (S.versions ? '<label class="check-inline"><input type="checkbox" id="f-since" data-act="since"' + (f.since ? ' checked' : '') + '> Only new or edited since my last check</label>' : '') +
      '<span class="filters-count">' + list.length + ' of ' + a.claims.length + ' shown</span></div>';
    html += list.length ? '<ol class="queries">' + list.map(claimHtml).join('') + '</ol>' : '<div class="empty"><p>No statement matches these filters.</p></div>';
    var keys = {};
    a.claims.forEach(function (c) { keys[c.key] = true; });
    if (S.versions) S.versions.changed.concat(S.versions.gone).forEach(function (x) { keys[x.key] = true; });
    var orphans = Object.keys(S.checks).filter(function (k) { return !keys[k] && S.checks[k].status !== 'unchecked'; });
    if (orphans.length) html += '<p class="orphans">' + esc(plural(orphans.length, 'mark') + ' from earlier ' + (orphans.length === 1 ? 'belongs' : 'belong') + ' to a sentence that has since changed or gone. ' + (orphans.length === 1 ? 'It is' : 'They are') + ' kept in the project but no longer counted.') + '</p>';
    keepFocus(function () { box.innerHTML = html; });
  }

  // The strip at the top of the checklist: what changed since the version you recorded as checked.
  function sinceHtml() {
    var v = S.versions, b = S.baseline;
    var record = '<button type="button" class="btn small" data-act="record">Record this version as checked</button>';
    if (!b.text) {
      return '<div class="since quiet"><p>When you have worked through this version, record it. Next time you revise, the checklist shows only what is new or edited since then, and marks on unchanged sentences carry over.</p>' + record + '</div>';
    }
    var when = b.on && M.parseDate(b.on).day !== null ? M.longDay(M.parseDate(b.on).day) : 'earlier';
    if (!v) return '<div class="since quiet"><p>This is the version you recorded as checked on ' + esc(when) + '.</p></div>';
    var gone = v.gone.map(function (g) {
      return '<li><span class="del">' + esc(M.clip(g.text, 110)) + '</span>' + (g.status !== 'unchecked' ? ' <span class="small">(' + esc(STATUS_WORD[g.status].toLowerCase() + (g.note ? ': ' + g.note : '')) + ')</span>' : '') + '</li>';
    }).join('');
    return '<div class="since"><div><h3>Since the version you checked on ' + esc(when) + '</h3><p>' +
      esc(plural(v.newClaims.length, 'new statement') + ', ' + plural(v.changed.length, 'edited statement') + ' and ' + plural(v.gone.length, 'statement') + ' gone; ' +
        plural(v.unchanged.length, 'statement') + ' unchanged, whose marks still apply.') + '</p>' +
      (gone ? '<p class="small">Gone since then:</p><ul class="gone">' + gone + '</ul>' : '') + '</div>' + record + '</div>';
  }

  function setMark(key, status) {
    var c = S.analysis.claims.filter(function (x) { return x.key === key; })[0];
    var cur = S.checks[key] || {};
    var next = cur.status === status ? 'unchecked' : status;
    var rec = { status: next };
    if (cur.note) rec.note = cur.note;
    if (next !== 'unchecked') rec.on = M.isoDay(today);
    if (c) rec.text = c.text;
    if (next === 'unchecked' && !rec.note) delete S.checks[key]; else S.checks[key] = rec;
    S.summary = M.summarise(S.analysis, S.checks, S.refChecks);
    changed();
    renderHead(); renderSlips(); renderNotice(); renderView();
    say(c ? 'Query ' + c.q + ' marked ' + (next === 'unchecked' ? 'unchecked' : STATUS_WORD[next].toLowerCase()) : 'Marked');
  }

  // ---------------------------------------------------------------- references

  var VERDICT_WORD = { ok: 'Looks fine', warn: 'Worth a look', fix: 'Needs fixing', suspect: 'Look it up by hand' };
  var VERDICT_SVG = {
    ok: '<svg viewBox="0 0 44 44" width="40" height="40" aria-hidden="true"><path d="M10 23 l8 8 l16 -18" fill="none" stroke="#2c7149" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    warn: '<svg viewBox="0 0 44 44" width="40" height="40" aria-hidden="true"><circle cx="22" cy="22" r="16" fill="none" stroke="#a86d17" stroke-width="2.4" stroke-dasharray="4 3"/><text x="22" y="28" text-anchor="middle" font-family="Spline Sans Mono, monospace" font-weight="600" font-size="16" fill="#a86d17">?</text></svg>',
    fix: '<svg viewBox="0 0 44 44" width="40" height="40" aria-hidden="true"><circle cx="22" cy="22" r="16" fill="none" stroke="#b8322a" stroke-width="2.6"/><path d="M15 15 l14 14 M29 15 l-14 14" stroke="#b8322a" stroke-width="2.6" stroke-linecap="round"/></svg>',
    suspect: '<svg viewBox="0 0 44 44" width="40" height="40" aria-hidden="true"><circle cx="22" cy="22" r="17" fill="#fbe9e3" stroke="#b8322a" stroke-width="3"/><text x="22" y="29" text-anchor="middle" font-family="Instrument Serif, Georgia, serif" font-size="22" fill="#b8322a">?!</text></svg>'
  };

  function refHtml(r) {
    var e = r.entry, st = M.refStatusOf(S.refChecks, e.key), ck = S.refChecks[e.key] || {};
    var fields = [];
    function f(label, v) { if (v) fields.push('<li><i>' + label + '</i>' + esc(v) + '</li>'); }
    f('type', e.type); f('authors', e.authors); f('year', e.year); f('title', e.title); f('in', e.container);
    f('vol', e.volume + (e.issue ? '(' + e.issue + ')' : '')); f('pages', e.pages); f('publisher', e.publisher); f('doi', e.doi); f('url', e.url + (e.urlTail ? ' ' + e.urlTail : '')); f('accessed', e.accessed);
    f('key', e.citeKey);
    f('cited', r.cited ? plural(r.cited, 'time') : '');
    var issues = r.issues.map(function (x) { return '<li class="' + x.severity + '">' + esc(x.text) + '</li>'; }).join('');
    var acts = r.verdict === 'ok' ? '<p class="small">Nothing to fix by shape. You still need to have read it.</p>' : '<div class="ref-acts" role="group" aria-label="Mark reference ' + r.number + '">' + ['checked', 'fixed', 'removed'].map(function (k) {
      return '<button type="button" class="mark-btn m-' + (k === 'checked' ? 'verified' : (k === 'fixed' ? 'corrected' : 'removed')) + '" id="rk-' + e.key + '-' + k + '" data-act="refmark" data-key="' + e.key + '" data-status="' + k + '" aria-pressed="' + (st === k) + '">' + STATUS_SVG[k === 'removed' ? 'removed' : k] + '<span>' + STATUS_WORD[k] + '</span></button>';
    }).join('') + '</div><label class="q-note-field" for="rn-' + e.key + '"><span>Note</span><input type="text" id="rn-' + e.key + '" data-act="refnote" data-key="' + e.key + '" value="' + esc(ck.note || '') + '" placeholder="Where you found it"></label>';
    return '<li class="ref v-' + r.verdict + '"><div class="ref-mark">' + VERDICT_SVG[r.verdict] + '<span class="ref-no">' + (e.label ? '[' + esc(e.label) + ']' : '#' + r.number) + '</span></div>' +
      '<div class="ref-body"><p class="ref-text">' + esc(e.text) + '</p><span class="verdict">' + VERDICT_WORD[r.verdict] + '</span>' +
      (issues ? '<ul class="ref-issues">' + issues + '</ul>' : '') + '<ul class="ref-fields" aria-label="What was read from this entry">' + fields.join('') + '</ul></div>' +
      '<div class="ref-right">' + acts + '</div></li>';
  }

  function renderRefs() {
    var a = S.analysis, s = S.summary, box = $('refs-body');
    if (!a || (!a.refs.entries.length && !a.refs.missing.length)) {
      box.innerHTML = '<div class="empty"><h3>No reference list found</h3><p>Put your list under a "References" or "Bibliography" heading at the end of your text, or paste it in box D on the Your texts page. Harvard, APA and numbered lists are read.</p>' +
        (a && a.refs.citations ? '<p>' + esc(plural(a.refs.citations, 'citation') + ' found in the text, with nothing to match them against.') + '</p>' : '') + '<button type="button" class="btn primary" data-go="copy">Add a reference list</button></div>';
      return;
    }
    var src = { list: 'the reference list you pasted (box D)', final: 'the reference section of your final version', draft: 'the reference section of the AI draft', none: 'nowhere' }[a.refs.source];
    if (a.refs.format === 'ris') src = 'the RIS export from your reference manager (box D)';
    else if (a.refs.format === 'bibtex') src = 'the BibTeX export from your reference manager (box D)';
    var html = '<div class="refs-top"><div class="tally"><b>' + s.refs + '</b><span>entries</span></div><div class="tally' + (s.refUnresolved ? ' hot' : '') + '"><b>' + s.refUnresolved + '</b><span>still to look at</span></div>' +
      '<div class="tally' + (s.refSuspect ? ' hot' : '') + '"><b>' + s.refSuspect + '</b><span>look made up</span></div><div class="tally' + (s.refMissing ? ' hot' : '') + '"><b>' + s.refMissing + '</b><span>cited, not listed</span></div></div>';
    html += '<p class="refs-source">Read from ' + esc(src) + ': ' + esc(plural(a.refs.entries.length, 'entry', 'entries')) + ', with ' + esc(plural(a.refs.citations, 'citation')) + ' in the text. Nothing here was looked up online: search your library catalogue or the publisher\'s site for anything flagged, and check each one says what you cite it for.</p>';
    if (a.refs.missing.length) {
      html += '<div class="missing-box"><h3>Cited in the text but not in the list</h3><ul>' + a.refs.missing.map(function (m) {
        return '<li><strong>' + esc(m.text) + '</strong> in "' + esc(M.clip(a.sentences[m.sentence].text, 80)) + '"' + (m.near ? ' (your list has ' + esc(m.near) + ')' : '') + '</li>';
      }).join('') + '</ul></div>';
    }
    var order = a.refs.entries.slice().sort(function (x, y) {
      var rank = { suspect: 0, fix: 1, warn: 2, ok: 3 };
      return rank[x.verdict] - rank[y.verdict] || x.number - y.number;
    });
    html += '<ol class="refs">' + order.map(refHtml).join('') + '</ol>';
    html += '<div class="tools-row" style="margin-top:14px"><button type="button" class="btn small" data-act="csv-refs">Reference report (.csv)</button></div>';
    keepFocus(function () { box.innerHTML = html; });
  }

  function setRefMark(key, status) {
    var cur = S.refChecks[key] || {};
    var next = cur.status === status ? 'unchecked' : status;
    var rec = { status: next };
    if (cur.note) rec.note = cur.note;
    if (next !== 'unchecked') rec.on = M.isoDay(today);
    if (next === 'unchecked' && !rec.note) delete S.refChecks[key]; else S.refChecks[key] = rec;
    S.summary = M.summarise(S.analysis, S.checks, S.refChecks);
    changed();
    renderHead(); renderSlips(); renderView();
    say('Reference marked ' + next);
  }

  // ---------------------------------------------------------------- changes

  function opsHtml(ops) {
    return ops.map(function (o) {
      if (o[0] === '=') return esc(o[1]);
      if (o[0] === '-') return '<span class="del">' + esc(o[1]) + '</span>';
      return '<span class="ins">' + esc(o[1]) + '</span>';
    }).join(' ');
  }

  function renderChanges() {
    var a = S.analysis, box = $('changes-body');
    if (!a || !a.changes) {
      box.innerHTML = '<div class="empty"><h3>' + (a && a.hasFinal ? 'Add the AI draft to compare' : 'Add your final version to compare') + '</h3><p>Paste the AI\'s draft in box A and what you will hand in in box B. This view then shows how much of your final text is still the AI\'s wording, sentence by sentence. It compares those two texts only: it is not a plagiarism or AI detector.</p><button type="button" class="btn primary" data-go="copy">Go to Your texts</button></div>';
      return;
    }
    var ch = a.changes, c = ch.counts, n = Math.max(1, ch.finalSentences);
    var parts = [['kept', 'Kept from the AI', c.kept], ['edited', 'Edited', c.edited], ['reworded', 'Reworded', c.reworded], ['yours', 'Your own', c.yours]];
    var bar = parts.map(function (p) { return p[2] ? '<span class="s-' + p[0] + '" style="width:' + (p[2] * 100 / n) + '%" title="' + esc(p[1] + ': ' + p[2]) + '">' + p[2] + '</span>' : ''; }).join('');
    var html = '<div class="change-top"><div class="bigfig"><div class="n">' + ch.keptShare + '<small>%</small></div><p>of the ' + ch.finalWords + ' words in your final text appear <strong>word for word</strong> in the AI draft, in runs of ' + M.MIN_RUN + ' or more words. ' + ch.survivedShare + '% of the AI draft survives into your final version.</p>' +
      '<div class="waffle" role="img" aria-label="' + ch.keptShare + ' squares in 100 are the AI\'s wording">' + new Array(101).join('.').split('').map(function (x, i) { return '<i' + (i < ch.keptShare ? ' class="k"' : '') + '></i>'; }).join('') + '</div></div>' +
      '<div class="split"><h3>Your ' + plural(ch.finalSentences, 'sentence') + '</h3><div class="split-bar" role="img" aria-label="' + esc(parts.map(function (p) { return p[2] + ' ' + p[1].charAt(0).toLowerCase() + p[1].slice(1); }).join(', ')) + '">' + bar + '</div>' +
      '<div class="split-legend">' + parts.map(function (p) { return '<span><i class="sw s-' + p[0] + '"></i>' + p[2] + ' ' + esc(p[1].charAt(0).toLowerCase() + p[1].slice(1)) + '</span>'; }).join('') + '<span><i class="sw s-dropped"></i>' + c.dropped + ' AI sentences cut</span></div>' +
      '<div class="paras"><h3>Paragraph by paragraph</h3>' + ch.paragraphs.map(function (p, i) {
        var share = M.pct(p.kept, p.words);
        return '<div class="para-row"><span>\u00b6 ' + (i + 1) + '</span><div class="para-track" role="img" aria-label="Paragraph ' + (i + 1) + ': ' + share + '% AI wording"><span style="width:' + share + '%"></span></div><span>' + share + '%</span></div>';
      }).join('') + '<p class="small">Grey: the AI\'s words kept as they were. Blue: your words.</p></div></div></div>';
    html += '<div class="toggle-row"><label class="check-inline"><input type="checkbox" id="t-diff" data-act="diff"' + (S.showDiff ? ' checked' : '') + '> Show what changed inside edited sentences</label>' +
      '<button type="button" class="btn small" data-act="copy-diff">Copy a summary</button></div>';
    html += '<div class="change-legend"><span><span class="sx sx-kept">kept from the AI</span></span><span><span class="sx sx-edited">edited or reworded</span></span><span><span class="sx sx-yours">your own</span></span><span><span class="sx"><span class="del">cut</span> <span class="ins">added</span></span></span></div>';
    var paras = [], cur = -1;
    ch.sentences.forEach(function (s) {
      if (s.para !== cur) { paras.push([]); cur = s.para; }
      var inner = S.showDiff && s.ops && s.cls !== 'kept' ? opsHtml(s.ops) : esc(s.text);
      var title = { kept: 'Kept from the AI draft', edited: 'Edited from the AI draft', reworded: 'Reworded from an AI sentence', yours: 'Your own sentence' }[s.cls];
      paras[paras.length - 1].push('<span class="sx sx-' + s.cls + '" title="' + esc(title + ' (' + s.kept + ' of ' + s.words + ' words kept)') + '">' + inner + '</span>');
    });
    html += '<div class="marked-text">' + paras.map(function (p) { return '<p>' + p.join(' ') + '</p>'; }).join('') + '</div>';
    if (ch.dropped.length) {
      html += '<div class="dropped"><h3>Sentences of the AI draft you cut</h3><ul>' + ch.dropped.map(function (d) { return '<li>' + esc(d.text) + '</li>'; }).join('') + '</ul></div>';
    }
    keepFocus(function () { box.innerHTML = html; });
  }

  // ---------------------------------------------------------------- declaration

  var FORM_FIELDS = [['title', 'Title of the work'], ['assignment', 'Assignment or deliverable'], ['course', 'Module, course or client'], ['institution', 'University or employer'], ['person', 'Your name'], ['date', 'Date (blank for today)']];
  var SESSION_FORM = [['date', 'Date'], ['assignment', 'Assignment'], ['tool', 'AI tool'], ['purpose', 'What you used it for'], ['prompt', 'Your prompt, in brief'], ['used', 'What you used'], ['changed', 'What you changed'], ['checked', 'What you checked'], ['minutes', 'Minutes'], ['person', 'Person']];

  function proofHtml(d) {
    var out = '', i = 0;
    while (i < d.blocks.length) {
      var b = d.blocks[i];
      if (b.type === 'h') out += (i === 0 ? '<h4>' : '<h5>') + esc(b.text) + (i === 0 ? '</h4>' : '</h5>');
      else if (b.type === 'fields') out += '<dl>' + b.items.map(function (x) { return '<dt>' + esc(x[0]) + '</dt><dd>' + esc(x[1]) + '</dd>'; }).join('') + '</dl>';
      else if (b.type === 'li') {
        var items = [];
        while (i < d.blocks.length && d.blocks[i].type === 'li') { items.push('<li>' + esc(d.blocks[i].text) + '</li>'); i++; }
        out += '<ul>' + items.join('') + '</ul>';
        continue;
      } else if (b.type === 'sign') out += '<p class="sign">' + esc(b.text) + '</p>';
      else out += '<p>' + esc(b.text) + '</p>';
      i++;
    }
    return out;
  }

  function stampSvg() {
    return '<svg class="stamp" viewBox="0 0 180 96" aria-label="Proof stamp: passed for press, checked by me"><g filter="url(#rough2)"><rect x="4" y="4" width="172" height="88" rx="9" fill="none" stroke="#2c7149" stroke-width="4"/><rect x="11" y="11" width="158" height="74" rx="6" fill="none" stroke="#2c7149" stroke-width="1.5"/>' +
      '<text x="90" y="32" text-anchor="middle" font-family="Spline Sans Mono, monospace" font-weight="600" font-size="11" letter-spacing="2" fill="#2c7149">PASSED FOR PRESS</text>' +
      '<text x="90" y="58" text-anchor="middle" font-family="Instrument Serif, Georgia, serif" font-size="25" fill="#2c7149">Checked by me</text>' +
      '<text x="90" y="76" text-anchor="middle" font-family="Spline Sans Mono, monospace" font-size="9.5" fill="#2c7149">' + esc(M.longDay(today).toUpperCase()) + '</text></g>' +
      '<defs><filter id="rough2"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="7"/><feDisplacementMap in="SourceGraphic" scale="2.2"/></filter></defs></svg>';
  }

  function currentDeclaration() { return M.declaration(S.analysis, state()); }

  // Submission boxes often limit words or characters, so the size of the plain-text declaration is shown.
  function declCount(d) {
    var text = M.declarationText(d).replace(/\n+$/, '');
    return plural(wordsIn(text), 'word') + ', ' + plural(text.length, 'character') + ' as plain text';
  }

  function renderDeclare() {
    var a = S.analysis, box = $('declare-body');
    var p = S.project, d = currentDeclaration(), s = S.summary;
    var mine = M.sessionsFor(S.sessions, p.assignment);
    var form = '<div class="form-grid">' + FORM_FIELDS.map(function (f) {
      return '<label class="field' + (f[0] === 'title' ? ' wide' : '') + '" for="pf-' + f[0] + '"><span>' + esc(f[1]) + '</span><input type="text" id="pf-' + f[0] + '" data-act="project" data-field="' + f[0] + '" value="' + esc(p[f[0]] || '') + '"></label>';
    }).join('') + '<label class="field wide" for="pf-template"><span>Layout</span><select id="pf-template" data-act="project" data-field="template">' + M.TEMPLATES.map(function (t) { return '<option value="' + t.id + '"' + (p.template === t.id ? ' selected' : '') + '>' + esc(t.name) + '</option>'; }).join('') + '</select></label></div>' +
      '<fieldset class="levels"><legend>How you used AI</legend>' + M.LEVELS.map(function (l) {
        return '<label class="radio" for="lv-' + l.id + '"><input type="radio" name="level" id="lv-' + l.id + '" data-act="project" data-field="level" value="' + l.id + '"' + (p.level === l.id ? ' checked' : '') + '><span>' + esc(l.text) + '</span></label>';
      }).join('') + '</fieldset>';
    var rows = M.sortSessions(S.sessions.map(function (x, i) { var y = Object.assign({}, x); y._i = i; return y; }));
    var table = rows.length ? '<div class="table-wrap"><table class="sessions"><thead><tr><th scope="col">Date</th><th scope="col">Tool</th><th scope="col">Purpose</th><th scope="col">Assignment</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead><tbody>' + rows.map(function (x) {
      var inThis = mine.indexOf(S.sessions[x._i]) >= 0;
      return '<tr class="' + (inThis ? '' : 'other') + '"><td class="d">' + esc(x.date || 'undated') + '</td><td>' + esc(x.tool) + '</td><td>' + esc(x.purpose) + (x.prompt ? '<br><span class="small">' + esc(M.clip(x.prompt, 70)) + '</span>' : '') + '</td><td>' + esc(x.assignment || '\u2013') + (inThis ? '' : '<br><span class="small">not in this declaration</span>') + '</td>' +
        '<td><div class="row-acts"><button type="button" class="btn small" id="se-' + x._i + '" data-act="edit-session" data-i="' + x._i + '" aria-label="Edit the session of ' + esc(x.date || 'no date') + '">Edit</button><button type="button" class="btn small ghost" data-act="del-session" data-i="' + x._i + '" aria-label="Delete the session of ' + esc(x.date || 'no date') + '">Delete</button></div></td></tr>';
    }).join('') + '</tbody></table></div>' : '<div class="empty"><p>No sessions logged yet. Add one for each time you used an AI tool on this work.</p></div>';
    var editing = S.editing >= 0 ? S.sessions[S.editing] : null;
    var draftSession = editing || S.newSession || { date: M.isoDay(today), assignment: p.assignment || '', person: p.person || '' };
    var sform = '<div class="session-form"><h3>' + (editing ? 'Edit this session' : 'Log a session') + '</h3><div class="form-grid">' + SESSION_FORM.map(function (f) {
      var wide = ['prompt', 'used', 'changed', 'checked'].indexOf(f[0]) >= 0;
      return '<label class="field' + (wide ? ' wide' : '') + '" for="sf-' + f[0] + '"><span>' + esc(f[1]) + '</span>' + (wide ? '<textarea id="sf-' + f[0] + '" rows="2">' + esc(draftSession[f[0]] || '') + '</textarea>' : '<input type="text" id="sf-' + f[0] + '" value="' + esc(draftSession[f[0]] || '') + '">') + '</label>';
    }).join('') + '</div><div class="form-acts"><button type="button" class="btn primary small" data-act="save-session">' + (editing ? 'Save changes' : 'Add to the log') + '</button>' +
      (S.texts.prompt ? '<button type="button" class="btn small" data-act="use-prompt">Fill in my prompt</button>' : '') +
      (editing ? '<button type="button" class="btn small ghost" data-act="cancel-session">Cancel</button>' : '') + '</div></div>';
    var left = '<div><h2>About the work</h2>' + form + '<div class="log"><div class="log-head"><h2>Session log</h2><span class="small">' + esc(plural(mine.length, 'session') + ' in this declaration, ' + S.sessions.length + ' in the log') + '</span></div>' +
      '<div class="tools-row"><button type="button" class="btn small" data-pick="sessions">Import a log (.csv)</button><button type="button" class="btn small" data-act="csv-sessions">Download the log (.csv)</button><button type="button" class="btn small ghost" data-act="template">Template</button></div>' + table + sform + '</div></div>';
    var warn = d.warnings.length ? '<ul class="warn-list">' + d.warnings.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') + '</ul>' : '';
    var complete = s && s.complete;
    var right = '<div><h2>Your declaration</h2><div class="decl-acts"><button type="button" class="btn primary small" data-act="copy-decl">Copy the text</button><button type="button" class="btn small" data-act="print">Print</button><button type="button" class="btn small" data-act="md-decl">Markdown (.md)</button><button type="button" class="btn small" data-act="txt-decl">Text (.txt)</button><button type="button" class="btn small" data-act="save">Save project</button><span class="copy-status" id="copy-status" role="status"></span></div>' + warn +
      '<div class="proof ' + (complete ? 'has-stamp' : 'has-pending') + '">' + (complete ? stampSvg() : '<div class="stamp-pending">The sign-off stamp appears when every query and flagged reference is marked</div>') + proofHtml(d) + '</div>' +
      '<p class="decl-count">' + esc(declCount(d)) + '</p></div>';
    keepFocus(function () { box.innerHTML = '<div class="decl-grid">' + left + right + '</div>'; });
  }

  function readSessionForm() {
    var out = {};
    SESSION_FORM.forEach(function (f) { var el = $('sf-' + f[0]); out[f[0]] = el ? el.value.replace(/\s+/g, ' ').trim() : ''; });
    return out;
  }

  // ---------------------------------------------------------------- how it works

  var WEIGHT_TEXT = {
    'leftover': 'Text from the chat window ("As of my last update", "[Insert source]")', 'statistic': 'A figure: money, a percentage, a count with its unit, "twice", "half of"',
    'quote': 'A direct quotation of four words or more', 'vague': 'A vague appeal ("studies show", "experts agree")', 'legal': 'A legal point', 'medical': 'A health or safety point',
    'financial': 'A money or financial point', 'study': 'A named study, survey or report', 'person': 'A named person', 'url': 'A web address or DOI', 'absolute': 'Absolute or superlative wording',
    'org': 'A named organisation', 'date': 'A date, year or "recently"', 'citation': 'A citation (check the source supports the sentence)', 'unsourced': 'A figure, quote or study with no citation in the sentence',
    'missing-ref': 'Cites something missing from the reference list', 'prompt-sources': 'You asked the AI for references', 'prompt-stats': 'You asked the AI for statistics', 'prompt-quotes': 'You asked the AI for a quotation',
    'notes-conflict': 'Your notes give a different figure or quotation', 'notes-match': 'Your notes give the same figures', 'notes-partial': 'Your notes back some of the figures',
    'notes-missing': 'The figures are not in your notes', 'origin-kept': 'Kept word for word from the AI draft', 'origin-yours': 'Written in your own words', 'hedge': 'A figure with hedged wording ("about", "may")'
  };

  function renderHow() {
    var box = $('how-weights');
    if (box.innerHTML) return;
    box.innerHTML = '<table class="weights"><tbody>' + Object.keys(M.WEIGHTS).map(function (k) {
      var v = M.WEIGHTS[k];
      return '<tr><td class="p' + (v < 0 ? ' neg' : '') + '">' + (v > 0 ? '+' : '') + v + '</td><td>' + esc(WEIGHT_TEXT[k] || k) + '</td></tr>';
    }).join('') + '</tbody></table>';
  }

  // ---------------------------------------------------------------- printing

  function printReport() {
    var a = S.analysis, d = currentDeclaration(), s = S.summary, p = S.project;
    var html = '<h1>' + esc(p.title || 'Proof report') + '</h1><p class="pslug">Checked by me \u00b7 ' + esc([p.assignment, p.person, M.longDay(today)].filter(Boolean).join(' \u00b7 ')) + ' \u00b7 checks nothing online, not a plagiarism detector</p>';
    html += '<div class="proof' + (s.complete ? ' has-stamp' : '') + '" style="position:relative">' + (s.complete ? stampSvg() : '') + proofHtml(d) + '</div>';
    if (a.claims.length) {
      html += '<h2>Claims checklist</h2><table><thead><tr><th>Query</th><th>Risk</th><th>Statement</th><th>Status</th><th>Source or note</th></tr></thead><tbody>' + a.ranked.map(function (q) {
        var c = a.claims[q - 1], ck = S.checks[c.key] || {};
        return '<tr><td>Qy ' + c.q + '</td><td class="pill">' + c.level + ' ' + c.score + '</td><td>' + esc(c.text) + '</td><td class="pill">' + M.statusOf(S.checks, c.key) + '</td><td>' + esc(ck.note || '') + '</td></tr>';
      }).join('') + '</tbody></table>';
    }
    if (a.claims.length) {
      var byIndex = {};
      a.claims.forEach(function (c) { byIndex[c.sentence] = c; });
      var paras = [], cur = -1;
      a.sentences.forEach(function (sn, i) {
        if (sn.para !== cur) { paras.push([]); cur = sn.para; }
        var c = byIndex[i];
        paras[paras.length - 1].push(esc(sn.text) + (c ? ' <b class="pill">[Qy ' + c.q + ': ' + c.level + ', ' + M.statusOf(S.checks, c.key).replace('unchecked', 'open') + ']</b>' : ''));
      });
      html += '<h2>The text with its queries</h2>' + paras.map(function (p) { return '<p>' + p.join(' ') + '</p>'; }).join('');
    }
    var flagged = a.refs.entries.filter(function (r) { return r.verdict !== 'ok'; });
    if (flagged.length || a.refs.missing.length) {
      html += '<h2>References to look at</h2><table><thead><tr><th>#</th><th>Entry</th><th>What was found</th><th>Status</th></tr></thead><tbody>' + flagged.map(function (r) {
        return '<tr><td>' + r.number + '</td><td>' + esc(r.entry.text) + '</td><td>' + esc(r.issues.map(function (x) { return x.text; }).join(' ')) + '</td><td class="pill">' + M.refStatusOf(S.refChecks, r.entry.key) + '</td></tr>';
      }).join('') + a.refs.missing.map(function (m) { return '<tr><td></td><td>' + esc(m.text) + '</td><td>Cited in the text but not in the list.</td><td></td></tr>'; }).join('') + '</tbody></table>';
    }
    $('print-sheet').innerHTML = html;
    try { window.print(); } catch (e) { say('Printing is not available here'); }
  }

  // ---------------------------------------------------------------- files

  function readZipEntry(buf, wanted) {
    var dv = new DataView(buf), bytes = new Uint8Array(buf), eocd = -1;
    for (var i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) {
      if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    }
    if (eocd < 0) return Promise.reject(new Error('not a zip file'));
    var count = dv.getUint16(eocd + 10, true), p = dv.getUint32(eocd + 16, true);
    for (var n = 0; n < count && p + 46 <= bytes.length; n++) {
      if (dv.getUint32(p, true) !== 0x02014b50) break;
      var method = dv.getUint16(p + 10, true), size = dv.getUint32(p + 20, true), nameLen = dv.getUint16(p + 28, true);
      var extra = dv.getUint16(p + 30, true), comment = dv.getUint16(p + 32, true), local = dv.getUint32(p + 42, true);
      var name = new TextDecoder().decode(bytes.subarray(p + 46, p + 46 + nameLen));
      if (name === wanted) {
        var start = local + 30 + dv.getUint16(local + 26, true) + dv.getUint16(local + 28, true);
        var data = bytes.subarray(start, start + size);
        if (method === 0) return Promise.resolve(new TextDecoder().decode(data));
        if (method !== 8 || typeof DecompressionStream === 'undefined') return Promise.reject(new Error('this browser cannot unpack .docx files'));
        var stream = new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
        return new Response(stream).text();
      }
      p += 46 + nameLen + extra + comment;
    }
    return Promise.resolve(null);
  }

  function readDocx(buf) {
    return readZipEntry(buf, 'word/document.xml').then(function (doc) {
      if (doc === null) throw new Error('there is no word/document.xml inside');
      return readZipEntry(buf, 'word/footnotes.xml').then(function (notes) { return M.docxText(doc, notes || ''); });
    });
  }

  function readFile(file, done) {
    var name = (file.name || '').toLowerCase();
    if (/\.docx$/.test(name)) {
      file.arrayBuffer().then(readDocx).then(function (text) { done(null, text, 'docx'); }, function (err) { done('Could not read "' + file.name + '" as a Word file: ' + err.message + '. Save it as .txt or paste the text.'); });
      return;
    }
    if (/\.(pdf|doc|odt|pages|rtf|xlsx?|pptx?|zip|png|jpe?g|gif)$/.test(name)) {
      done('"' + file.name + '" is not a text file this page can read. Paste the text, or save it as .txt, .md or .docx first.');
      return;
    }
    if (file.size > 8 * 1024 * 1024) { done('"' + file.name + '" is larger than 8 MB, which is too big to be a draft. Paste the part you need.'); return; }
    var reader = new FileReader();
    reader.onload = function () {
      var text = String(reader.result || '');
      if (/\u0000/.test(text.slice(0, 2000))) { done('"' + file.name + '" looks like a binary file, not text.'); return; }
      done(null, text, /\.html?$/.test(name) ? 'html' : 'text');
    };
    reader.onerror = function () { done('Could not read "' + file.name + '".'); };
    reader.readAsText(file);
  }

  function takeFile(field, file) {
    if (!file) return;
    if (/\.json$/i.test(file.name || '')) { openProjectFile(file); return; }
    if (/\.(ris|bib|bibtex)$/i.test(file.name || '')) field = 'references';
    readFile(file, function (err, text) {
      if (err) {
        if (field === 'sessions') { S.sessionMsgs = [{ text: err, err: true }]; }
        else { S.fieldMsgs[field] = err; S.fieldMsgs[field + 'Err'] = true; }
        renderCopy();
        say(err);
        return;
      }
      if (field === 'sessions') { importSessions(text, file.name); return; }
      S.texts[field] = text;
      $('in-' + field).value = text;
      S.fieldMsgs[field] = 'Read "' + file.name + '".'; S.fieldMsgs[field + 'Err'] = false;
      changed();
      analyseNow();
      say('Read ' + file.name);
    });
  }

  function importSessions(text, name) {
    var r = M.parseSessions(text);
    var msgs = r.messages.map(function (m) { return { text: m, err: /could not|not a number|no date|empty|does not look/i.test(m) }; });
    if (r.sessions.length) {
      var seen = {};
      S.sessions.forEach(function (x) { seen[JSON.stringify([x.date, x.tool, x.purpose, x.prompt])] = true; });
      var added = 0;
      r.sessions.forEach(function (x) {
        var k = JSON.stringify([x.date, x.tool, x.purpose, x.prompt]);
        if (!seen[k]) { S.sessions.push(x); seen[k] = true; added++; }
      });
      msgs.unshift({ text: 'Read ' + plural(r.sessions.length, 'session') + ' from "' + name + '"' + (added < r.sessions.length ? '; ' + (r.sessions.length - added) + ' already in your log' : '') + '.' });
      changed();
    } else msgs.unshift({ text: 'No sessions could be read from "' + name + '".', err: true });
    S.sessionMsgs = msgs;
    analyseNow();
    say(msgs[0].text);
  }

  function openProjectFile(file) {
    var reader = new FileReader();
    reader.onload = function () {
      var r = M.readProject(String(reader.result || ''));
      if (!r.ok) { showNotice(r.message, 'err'); return; }
      loadProject(r);
      S.dirty = true;
      storeSet(M.projectFile(state()));
      showNotice('Opened "' + file.name + '"' + (r.saved ? ', saved on ' + r.saved : '') + '.', 'ok');
    };
    reader.onerror = function () { showNotice('Could not read that file.', 'err'); };
    reader.readAsText(file);
  }

  function showNotice(text, kind) {
    S.restoreOffer = '<div class="note-card ' + (kind || '') + '"><p>' + esc(text) + '</p><button type="button" class="btn small ghost" data-act="dismiss">Dismiss</button></div>';
    renderNotice();
    say(text);
  }

  function startNew(keepLog) {
    var keep = keepLog ? S.sessions.filter(function () { return !S.isSample; }) : [];
    var person = S.isSample ? '' : S.project.person, inst = S.isSample ? '' : S.project.institution;
    loadProject({ project: { person: person, institution: inst }, texts: {}, sessions: keep, checks: {}, refChecks: {} });
    S.dirty = true;
    storeSet(M.projectFile(state()));
  }

  // ---------------------------------------------------------------- events

  function bind() {
    $('tabs').addEventListener('click', function (e) {
      var b = e.target.closest('[data-view]');
      if (b) setView(b.getAttribute('data-view'));
    });
    $('tabs').addEventListener('keydown', function (e) {
      var i = VIEWS.indexOf(S.view);
      if (e.key === 'ArrowRight') { e.preventDefault(); setView(VIEWS[(i + 1) % VIEWS.length], true); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); setView(VIEWS[(i + VIEWS.length - 1) % VIEWS.length], true); }
      else if (e.key === 'Home') { e.preventDefault(); setView(VIEWS[0], true); }
      else if (e.key === 'End') { e.preventDefault(); setView(VIEWS[VIEWS.length - 1], true); }
    });
    FIELDS.forEach(function (f) {
      $('in-' + f).addEventListener('input', function () {
        S.texts[f] = this.value;
        S.fieldMsgs[f] = ''; S.fieldMsgs[f + 'Err'] = false;
        changed();
        later('analyse', 300, analyseNow);
      });
    });
    document.querySelectorAll('.drop').forEach(function (z) {
      var field = z.getAttribute('data-field');
      z.addEventListener('dragover', function (e) { e.preventDefault(); z.classList.add('over'); });
      z.addEventListener('dragleave', function () { z.classList.remove('over'); });
      z.addEventListener('drop', function (e) {
        e.preventDefault(); z.classList.remove('over');
        if (e.dataTransfer && e.dataTransfer.files.length) takeFile(field, e.dataTransfer.files[0]);
      });
    });
    document.querySelectorAll('textarea[data-field]').forEach(function (t) {
      t.addEventListener('dragover', function (e) { if (e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') >= 0) e.preventDefault(); });
      t.addEventListener('drop', function (e) {
        if (e.dataTransfer && e.dataTransfer.files.length) { e.preventDefault(); takeFile(t.getAttribute('data-field'), e.dataTransfer.files[0]); }
      });
    });
    $('file-pick').addEventListener('change', function () {
      var f = this.files && this.files[0];
      if (f) takeFile(S.pickField, f);
      this.value = '';
    });
    $('file-project').addEventListener('change', function () {
      var f = this.files && this.files[0];
      if (f) openProjectFile(f);
      this.value = '';
    });
    document.body.addEventListener('click', onClick);
    document.body.addEventListener('input', onInput);
    document.body.addEventListener('change', onChange);
    $('btn-own').addEventListener('click', useOwn);
    $('btn-open-hero').addEventListener('click', function () { $('file-project').click(); });
    $('btn-open').addEventListener('click', function () { $('file-project').click(); });
    $('btn-save').addEventListener('click', saveProject);
    $('btn-new').addEventListener('click', function () {
      startNew(true);
      setView('copy');
      showNotice('Started a new project. Your session log is kept; paste the AI\'s draft in box A.', 'ok');
      $('in-draft').focus();
    });
    $('btn-sample').addEventListener('click', loadSample);
    $('btn-clear').addEventListener('click', function () {
      FIELDS.forEach(function (f) { S.texts[f] = ''; $('in-' + f).value = ''; });
      S.fieldMsgs = {};
      changed();
      analyseNow();
      $('in-draft').focus();
    });
    $('btn-template').addEventListener('click', function () { download('session-log-template.csv', M.SESSION_TEMPLATE, 'text/csv;charset=utf-8'); });
    $('btn-go-check').addEventListener('click', function () { setView('check'); });
  }

  function useOwn() {
    if (S.isSample) startNew(false);
    setView('copy');
    showNotice('Paste the AI\'s draft in box A, and your final version in box B if you have one. Nothing leaves this page.', 'ok');
    var ta = $('in-draft');
    ta.focus();
    try { ta.scrollIntoView({ block: 'center' }); } catch (e) { /* old browsers */ }
  }

  function loadSample() {
    var el = $('sample-project');
    var r = M.readProject(el.textContent);
    if (r.ok) loadProject(r, { sample: true });
  }

  function saveProject() {
    var text = M.projectFile(state());
    download(slugName(S.project.title || S.project.assignment) + '.checked-by-me.json', text, 'application/json');
    storeSet(text);
  }

  function onClick(e) {
    var t = e.target.closest('button, [data-go]');
    if (!t) return;
    if (t.hasAttribute('data-go')) { setView(t.getAttribute('data-go')); window.scrollTo(0, $('tabs').getBoundingClientRect().top + window.scrollY - 10); return; }
    if (t.hasAttribute('data-own')) { useOwn(); return; }
    if (t.hasAttribute('data-pick')) { S.pickField = t.getAttribute('data-pick'); var fp = $('file-pick'); fp.accept = S.pickField === 'sessions' ? '.csv,.tsv,.txt,text/csv' : (S.pickField === 'references' ? '.txt,.md,.ris,.bib,.docx,text/plain' : '.txt,.md,.markdown,.html,.htm,.docx,text/plain,text/markdown'); fp.click(); return; }
    var act = t.getAttribute('data-act');
    if (!act) return;
    var a = S.analysis;
    if (act === 'mark') setMark(t.getAttribute('data-key'), t.getAttribute('data-status'));
    else if (act === 'refmark') setRefMark(t.getAttribute('data-key'), t.getAttribute('data-status'));
    else if (act === 'risk') { S.filter.risk = t.getAttribute('data-risk'); renderCheck(); }
    else if (act === 'md-proof') download(slugName(S.project.title || 'text') + '-proof-copy.md', M.annotatedMarkdown(a, S.checks, S.refChecks, S.project.title, today), 'text/markdown;charset=utf-8');
    else if (act === 'csv-claims') download(slugName(S.project.title || 'claims') + '-checklist.csv', M.claimsCsv(a, S.checks), 'text/csv;charset=utf-8');
    else if (act === 'csv-refs') download(slugName(S.project.title || 'references') + '-references.csv', M.refsCsv(a, S.refChecks), 'text/csv;charset=utf-8');
    else if (act === 'csv-sessions') download(slugName(S.project.assignment || 'ai') + '-session-log.csv', M.sessionsCsv(S.sessions), 'text/csv;charset=utf-8');
    else if (act === 'template') download('session-log-template.csv', M.SESSION_TEMPLATE, 'text/csv;charset=utf-8');
    else if (act === 'print') printReport();
    else if (act === 'record') {
      S.baseline = { text: checkedText(), on: M.isoDay(today) };
      S.filter.since = false;
      changed(); analyseNow();
      say('Recorded this version as checked');
    }
    else if (act === 'save') saveProject();
    else if (act === 'dismiss') { S.restoreOffer = ''; renderNotice(); }
    else if (act === 'restore') {
      var r = M.readProject(storeGet() || '');
      S.restoreOffer = '';
      if (r.ok) { loadProject(r); showNotice('Reopened the project kept in this browser.', 'ok'); }
    } else if (act === 'copy-decl') {
      copyText(M.declarationText(currentDeclaration()), function (ok) { var st = $('copy-status'); if (st) st.textContent = ok ? 'Copied' : 'Select the text and copy it'; say(ok ? 'Declaration copied' : 'Copy did not work here'); });
    } else if (act === 'md-decl') download(slugName(S.project.title || 'declaration') + '-ai-declaration.md', M.declarationMarkdown(currentDeclaration()), 'text/markdown;charset=utf-8');
    else if (act === 'txt-decl') download(slugName(S.project.title || 'declaration') + '-ai-declaration.txt', M.declarationText(currentDeclaration()), 'text/plain;charset=utf-8');
    else if (act === 'copy-diff') {
      var ch = a.changes;
      var text = 'About ' + ch.keptShare + '% of my final text appears word for word in the AI draft. ' + ch.counts.kept + ' sentences kept, ' + ch.counts.edited + ' edited, ' + ch.counts.reworded + ' reworded, ' + ch.counts.yours + ' my own; ' + ch.counts.dropped + ' AI sentences cut.';
      copyText(text, function (ok) { say(ok ? 'Summary copied' : 'Copy did not work here'); });
    } else if (act === 'edit-session') { S.editing = +t.getAttribute('data-i'); renderDeclare(); var f0 = $('sf-date'); if (f0) f0.focus(); }
    else if (act === 'del-session') {
      S.sessions.splice(+t.getAttribute('data-i'), 1); S.editing = -1; changed(); renderHead(); renderDeclare(); say('Session deleted');
    } else if (act === 'cancel-session') { S.editing = -1; S.newSession = null; renderDeclare(); }
    else if (act === 'use-prompt') {
      var pf = $('sf-prompt');
      if (pf) pf.value = S.analysis.prompt.summary;
    } else if (act === 'save-session') {
      var v = readSessionForm();
      if (!v.tool && !v.purpose) { showNotice('Give the session at least a tool or a purpose.', 'err'); return; }
      var cs = M.cleanSession(v);
      var pd = M.parseDate(v.date);
      if (v.date && pd.day === null) { showNotice('Could not read the date "' + v.date + '". Use a form like 2026-11-05 or 5/11/2026.', 'err'); return; }
      if (S.editing >= 0) S.sessions[S.editing] = cs; else S.sessions.push(cs);
      S.editing = -1; S.newSession = null;
      changed(); renderHead(); renderDeclare(); say('Session saved');
    }
  }

  function onInput(e) {
    var t = e.target, act = t.getAttribute && t.getAttribute('data-act');
    if (act === 'note') {
      var key = t.getAttribute('data-key'), cur = S.checks[key] || { status: 'unchecked' };
      cur.note = t.value;
      if (!cur.note && cur.status === 'unchecked') delete S.checks[key]; else S.checks[key] = cur;
      changed();
    } else if (act === 'refnote') {
      var rk = t.getAttribute('data-key'), rc = S.refChecks[rk] || { status: 'unchecked' };
      rc.note = t.value;
      if (!rc.note && rc.status === 'unchecked') delete S.refChecks[rk]; else S.refChecks[rk] = rc;
      changed();
    } else if (act === 'project' && t.type === 'text') {
      S.project[t.getAttribute('data-field')] = t.value;
      changed();
      later('decl', 250, function () { renderHead(); renderDeclare(); });
    } else if (t.id && /^sf-/.test(t.id) && S.editing < 0) {
      S.newSession = readSessionForm();
    }
  }

  function onChange(e) {
    var t = e.target, act = t.getAttribute && t.getAttribute('data-act');
    if (act === 'kind') { S.filter.kind = t.value; renderCheck(); }
    else if (act === 'status-filter') { S.filter.status = t.value; renderCheck(); }
    else if (act === 'order') { S.filter.order = t.value; renderCheck(); }
    else if (act === 'conflicts') { S.filter.conflicts = t.checked; renderCheck(); }
    else if (act === 'since') { S.filter.since = t.checked; renderCheck(); }
    else if (act === 'diff') { S.showDiff = t.checked; renderChanges(); }
    else if (act === 'project' && t.type !== 'text') {
      S.project[t.getAttribute('data-field')] = t.value;
      changed(); renderHead(); renderDeclare();
    }
  }

  // ---------------------------------------------------------------- start

  function init() {
    bind();
    loadSample();
    var stored = storeGet();
    if (stored) {
      var r = M.readProject(stored);
      if (r.ok) {
        S.restoreOffer = '<div class="note-card"><p>Welcome back. Your last project' + (r.project.title ? ', "' + esc(r.project.title) + '",' : '') + ' is kept in this browser' + (r.saved ? ' (saved ' + esc(r.saved) + ')' : '') + '. The sample is showing now.</p><button type="button" class="btn small primary" data-act="restore">Reopen my project</button><button type="button" class="btn small ghost" data-act="dismiss">Keep the sample</button></div>';
        S.isSample = true;
      }
    }
    var hash = (location.hash || '').replace('#', '');
    setView(VIEWS.indexOf(hash) >= 0 ? hash : 'check');
    window.addEventListener('hashchange', function () {
      var h = (location.hash || '').replace('#', '');
      if (VIEWS.indexOf(h) >= 0 && h !== S.view) setView(h);
    });
    renderNotice();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
