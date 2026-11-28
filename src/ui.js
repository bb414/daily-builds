/* Still paying? interface: wires the model to the page. Everything stays in this browser tab. */
(function () {
  'use strict';
  var M = window.StillPaying;
  var doc = document;
  var $ = function (sel, root) { return (root || doc).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || doc).querySelectorAll(sel)); };

  /* Browser storage is a convenience only: it can be blocked inside a frame or a private window. */
  var store = {
    get: function (k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { window.localStorage.setItem(k, v); return true; } catch (e) { return false; } },
    remove: function (k) { try { window.localStorage.removeItem(k); } catch (e) { /* storage unavailable */ } }
  };
  var KEY_LAST = 'still-paying:last-review';
  var KEY_PREFS = 'still-paying:prefs';

  var now = new Date();
  var TODAY = M.dayFromYMD(now.getFullYear(), now.getMonth() + 1, now.getDate());

  var state = {
    files: [], extra: [], saved: null,
    decisions: {}, names: {}, aliases: {}, manual: [], overrides: {}, details: { name: '', account: '' },
    isSample: false, view: 'regulars',
    filter: 'all', search: '', sort: 'yearly',
    calMonths: 3, hideCancelled: false, showIncome: true,
    mapperFor: null, open: {}, ticked: {}
  };
  var A = null; // the latest analysis
  var P = null; // the latest plan
  var uidN = 0;
  function uid() { uidN += 1; return 'f' + uidN; }

  /* ---------------------------------------------------------------- */
  /* Small helpers                                                     */
  /* ---------------------------------------------------------------- */

  function esc(s) { return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function hid(s) { var h = 5381; for (var i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0; return 'x' + (h >>> 0).toString(36); }
  var money = M.money;
  function wholeMoney(p) { return M.money(M.roundHalfUp(p / 100) * 100, { whole: true }); }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
  function dayLabel(d) { return M.DAY_NAMES[M.weekday(d)].slice(0, 3) + ' ' + M.shortDate(d); }
  var PER = { weekly: 'a week', fortnightly: 'every 2 weeks', 'four-weekly': 'every 4 weeks', monthly: 'a month', 'two-monthly': 'every 2 months', quarterly: 'a quarter', 'six-monthly': 'every 6 months', yearly: 'a year' };
  function catOf(id) { return M.CATEGORY_BY_ID[id] || M.CATEGORY_BY_ID.other; }
  function catClass(id) { var c = catOf(id); return c.cost === false ? 'nocost' : (c.essential ? '' : 'optional'); }
  function decisionOf(id) { var d = state.decisions[id]; return d && d.decision ? d.decision : ''; }

  var toastTimer = null;
  function toast(msg) {
    var t = $('#toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove('show'); }, 3600);
  }

  function download(name, text, type) {
    try {
      var blob = new Blob([text], { type: type || 'text/plain;charset=utf-8' });
      var url = URL.createObjectURL(blob);
      var a = doc.createElement('a');
      a.href = url; a.download = name; a.rel = 'noopener';
      doc.body.appendChild(a);
      a.click();
      setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1500);
      toast('Downloaded ' + name);
    } catch (e) {
      toast('Your browser blocked the download. Try opening the app in its own tab.');
    }
  }
  function copyText(text, what) {
    var done = function () { toast((what || 'Text') + ' copied, ready to paste'); };
    var fallback = function () {
      var ta = doc.createElement('textarea');
      ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
      doc.body.appendChild(ta); ta.select();
      var ok = false;
      try { ok = doc.execCommand('copy'); } catch (e) { ok = false; }
      ta.remove();
      if (ok) done(); else toast('Copying was blocked here. Select the text and copy it yourself.');
    };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, fallback);
    else fallback();
  }

  /* ---------------------------------------------------------------- */
  /* Running the model                                                 */
  /* ---------------------------------------------------------------- */

  function analyse() {
    A = M.analyse({
      files: state.files.map(function (f) { return { name: f.name, text: f.text, account: f.accountGiven ? f.account : undefined, options: f.options }; }),
      extra: state.extra, aliases: state.aliases, names: state.names, manual: state.manual, overrides: state.overrides
    });
    // Remember the account each file ended up in, so the input shows it.
    A.statements.forEach(function (st, i) { if (state.files[i] && !state.files[i].accountGiven) state.files[i].account = st.account; });
    replan();
  }
  function replan() {
    P = M.plan(A.result, state.decisions, { details: state.details });
    A.since = state.saved ? M.sinceLastReview(A.result, state.saved) : null;
  }
  function hasData() { return A && A.merged.transactions.length > 0; }

  function rerender() {
    var active = doc.activeElement;
    var focusId = active && active.id ? active.id : null;
    var y = window.scrollY;
    renderMeters(); renderGauge(); renderBanner();
    renderStatements(); renderRegulars(); renderCalendar(); renderPlan();
    if (focusId) { var el = doc.getElementById(focusId); if (el) { try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); } } }
    window.scrollTo(0, y);
    autosave();
  }
  function refresh() { analyse(); rerender(); }

  function autosave() {
    if (state.isSample || !hasData()) return;
    store.set(KEY_LAST, reviewText());
  }
  function savePrefs() { store.set(KEY_PREFS, JSON.stringify({ view: state.view, details: state.details })); }

  /* ---------------------------------------------------------------- */
  /* Hero: meters and the gauge                                        */
  /* ---------------------------------------------------------------- */

  function meterDigits(p) {
    var s = money(p);
    var m = /^(-?\u00a3)([\d,]+)\.(\d\d)$/.exec(s);
    if (!m) return esc(s);
    return '<span>' + m[1] + '</span>' + m[2].split('').map(function (c) { return c === ',' ? '<span>,</span>' : '<span class="digit">' + c + '</span>'; }).join('') + '<span class="pence">.' + m[3] + '</span>';
  }
  function renderMeters() {
    var el = $('#meters');
    if (!hasData()) {
      el.innerHTML = '<div class="meter"><p class="meter-label">Leaves on its own</p><p class="meter-value">\u00a3<span class="digit">0</span><span class="pence">.00</span></p><p class="meter-note">Add a statement to start.</p></div>';
      return;
    }
    var r = A.result, t = P.totals;
    var active = r.series.filter(M.isCost);
    var checks = active.filter(function (s) { return s.flags.some(function (f) { return f.tone === 'warn' || f.tone === 'alert'; }); }).length;
    var still = A.since ? A.since.stillCharging.length : 0;
    var next = P.forecast.filter(function (it) { return it.direction === 'out' && it.decision !== 'ignore' && catOf(it.category).cost !== false; })[0];
    var stopped = r.series.filter(function (s) { return s.status === 'stopped'; }).length;
    var html = '';
    html += '<div class="meter"><p class="meter-label">Leaves on its own</p><p class="meter-value">' + meterDigits(t.monthly) + '<span class="unit">a month</span></p><p class="meter-note">' + wholeMoney(t.annual) + ' a year, not counting money moved to your own accounts</p></div>';
    html += '<div class="meter"><p class="meter-label">Regular payments</p><p class="meter-value"><span class="digit">' + active.length + '</span><span class="unit">running</span></p><p class="meter-note">' + stopped + (stopped === 1 ? ' looks' : ' look') + ' stopped, ' + plural(r.candidates.length, 'possible yearly one') + '</p></div>';
    html += '<div class="meter' + (still ? ' alert' : '') + '"><p class="meter-label">' + (still ? 'Still charging' : 'Checks to look at') + '</p><p class="meter-value"><span class="digit">' + (still || checks) + '</span><span class="unit">' + (still ? 'after you cancelled' : 'flagged') + '</span></p><p class="meter-note">' + (still ? 'and ' + plural(checks, 'other check') : 'price rises, intro prices ending, double charges and overlaps') + '</p></div>';
    html += '<div class="meter"><p class="meter-label">Next to leave</p><p class="meter-value">' + (next ? meterDigits(next.amount) : '<span class="digit">-</span>') + '</p><p class="meter-note">' + (next ? esc(next.name) + ', ' + dayLabel(next.day) : 'Nothing due') + '</p></div>';
    el.innerHTML = html;
  }
  var gaugeTicksDrawn = false;
  function renderGauge() {
    var ticks = $('#gauge-ticks');
    if (ticks && !gaugeTicksDrawn) {
      var t = '';
      for (var i = 0; i <= 12; i++) {
        var a = (-120 + i * 20) * Math.PI / 180, r1 = i % 3 === 0 ? 40 : 45, r2 = 51;
        t += '<line x1="' + (Math.sin(a) * r1).toFixed(1) + '" y1="' + (-Math.cos(a) * r1).toFixed(1) + '" x2="' + (Math.sin(a) * r2).toFixed(1) + '" y2="' + (-Math.cos(a) * r2).toFixed(1) + '"/>';
      }
      ticks.innerHTML = t;
      gaugeTicksDrawn = true;
    }
    var monthly = hasData() ? P.totals.monthly : 0;
    var scale = 50000;
    while (monthly > scale * 0.85) scale *= 2;
    var angle = -120 + Math.min(1, monthly / scale) * 240;
    var needle = $('#gauge-needle');
    if (needle) needle.setAttribute('transform', 'rotate(' + angle.toFixed(1) + ')');
    var read = $('#gauge-readout');
    if (read) read.textContent = wholeMoney(monthly);
  }

  function renderBanner() {
    var b = $('#banner');
    var last = store.get(KEY_LAST);
    var html = '';
    if (state.isSample) {
      html = '<div class="banner-inner"><p>You are looking at an invented student\'s statements (four exports, one of them deliberately messy), reopened a month after their last review. Bring your own to see yours.</p><button type="button" class="btn btn-copper btn-small" data-go="statements">Use your own statement</button>' + (last ? '<button type="button" class="btn btn-plain btn-small" data-action="reopen-last">Reopen your last review in this browser</button>' : '') + '</div>';
    } else if (state.saved && !state.files.length) {
      html = '<div class="banner-inner"><p>Reopened your review from ' + M.longDate(state.saved.reviewedOn) + '. Add this month\'s export to see what changed and check that anything you cancelled really stopped.</p><button type="button" class="btn btn-copper btn-small" data-action="choose-files">Add this month\'s export</button></div>';
    }
    b.innerHTML = html;
    b.hidden = !html;
  }

  /* ---------------------------------------------------------------- */
  /* View 1: statements                                                */
  /* ---------------------------------------------------------------- */

  var MAP_ROLES = ['date', 'payee', 'memo', 'amount', 'out', 'in', 'sign', 'type', 'category', 'status'];

  function renderStatements() {
    var el = $('#statements-body');
    if (!state.files.length && !state.extra.length) {
      el.innerHTML = '<div class="plate empty-state" style="margin-top:18px"><svg viewBox="0 0 140 90" aria-hidden="true"><rect x="10" y="38" width="120" height="16" rx="4" fill="#b4643a"/><rect x="60" y="54" width="20" height="26" fill="#b4643a"/><circle cx="70" cy="30" r="16" fill="none" stroke="#8a9a96" stroke-width="5"/><path d="M54 30h32M70 14v32" stroke="#8a9a96" stroke-width="3"/></svg><h3>No statements yet</h3><p>Drop a CSV export from your bank above, or paste a table. A year of history finds yearly renewals as well as monthly ones.</p><button type="button" class="btn btn-plain" data-action="load-sample">Show the sample again</button></div>';
      return;
    }
    var html = '<div class="files">';
    if (state.extra.length) {
      var accs = {};
      state.extra.forEach(function (t) { accs[t.account] = 1; });
      var s0 = Math.min.apply(null, state.extra.map(function (t) { return t.day; })), e0 = Math.max.apply(null, state.extra.map(function (t) { return t.day; }));
      html += '<article class="plate file-card"><div class="file-icon">JSON</div><div><div class="file-name">Saved review' + (state.saved ? ' from ' + esc(M.longDate(state.saved.reviewedOn)) : '') + '</div><div class="file-meta"><span><b>' + state.extra.length + '</b> payments kept from before</span><span>' + esc(M.longDate(s0)) + ' to ' + esc(M.longDate(e0)) + '</span><span>' + esc(Object.keys(accs).join(', ')) + '</span></div><p class="file-layout">Payments from your earlier review are combined with any new exports; months that overlap are only counted once.</p></div><div class="file-actions"><button type="button" class="btn btn-small btn-danger" data-action="drop-saved">Remove</button></div></article>';
    }
    state.files.forEach(function (f, i) {
      var st = A.statements[i];
      var ext = (/\.([a-z0-9]{2,4})$/i.exec(f.name) || [0, 'TXT'])[1].toUpperCase();
      var linked = (A.merged.linked || []).filter(function (l) { return l.file === f.name; })[0];
      var notes = [];
      if (st.error) notes.push('<li class="bad">' + esc(st.error) + '</li>');
      st.warnings.forEach(function (w) { notes.push('<li>' + esc(w) + '</li>'); });
      if (linked) notes.push('<li class="info">' + esc(linked.share + '% of its payments also appear in ' + linked.other + ', so it was treated as the same account (' + linked.account + ') and the overlap is counted once.') + '</li>');
      if (st.ok && !st.skipped.length && !st.warnings.length) notes.push('<li class="good">Every row was read.</li>');
      html += '<article class="plate file-card' + (st.ok ? '' : ' bad') + '" id="file-' + f.uid + '">';
      html += '<div class="file-icon">' + esc(ext) + '</div><div>';
      html += '<div class="file-name">' + esc(f.name) + '</div>';
      html += '<div class="file-meta"><label class="acct">Account <input type="text" id="acct-' + f.uid + '" data-file="' + f.uid + '" data-field="account" value="' + esc(st.account) + '" aria-label="Account name for ' + esc(f.name) + '"></label>';
      if (st.ok) html += '<span><b>' + st.transactions.length + '</b> payments read</span><span><b>' + st.skipped.length + '</b> skipped</span><span>' + esc(M.longDate(st.start)) + ' to ' + esc(M.longDate(st.end)) + '</span>';
      html += '</div>';
      if (st.layout) html += '<p class="file-layout">Read ' + esc(st.layout.description) + '.</p>';
      html += '<ul class="notes">' + notes.join('') + '</ul>';
      if (st.skipped.length) {
        html += '<details class="skips"' + (state.open['skips-' + f.uid] ? ' open' : '') + ' data-open-key="skips-' + f.uid + '"><summary>' + plural(st.skipped.length, 'row') + ' not used, and why</summary><div class="table-wrap"><table><thead><tr><th class="num">Line</th><th>Reason</th><th>What the row said</th></tr></thead><tbody>';
        st.skipped.slice(0, 200).forEach(function (k) { html += '<tr><td class="num">' + k.line + '</td><td>' + esc(k.reason) + '</td><td class="raw">' + esc(k.raw) + '</td></tr>'; });
        html += '</tbody></table></div>' + (st.skipped.length > 200 ? '<p class="hint">Showing the first 200.</p>' : '') + '</details>';
      }
      if (state.mapperFor === f.uid) html += mapperHtml(f, st);
      html += '</div><div class="file-actions"><button type="button" class="btn btn-small" data-action="map" data-file="' + f.uid + '" aria-expanded="' + (state.mapperFor === f.uid) + '">' + (state.mapperFor === f.uid ? 'Close columns' : 'Change columns') + '</button><button type="button" class="btn btn-small btn-danger" data-action="remove-file" data-file="' + f.uid + '">Remove</button></div>';
      html += '</article>';
    });
    html += '</div>';
    if (hasData()) html += coverageHtml() + checksHtml();
    html += '<div class="toolbar no-print" style="margin-top:18px"><button type="button" class="btn btn-plain btn-small" data-action="load-sample">Load the sample again</button><button type="button" class="btn btn-small btn-danger" data-action="clear-all">Clear everything</button>' + (hasData() ? '<button type="button" class="btn btn-copper btn-small" data-go="regulars">See the regular payments</button>' : '') + '</div>';
    el.innerHTML = html;
  }

  function mapperHtml(f, st) {
    var layout = st.layout || {};
    var map = layout.mapping || {};
    var headers = layout.headers || st.headers || [];
    var width = headers.length || 0;
    if (!width) {
      var rows = M.parseDelimited(f.text.replace(/^\ufeff/, ''), st.delimiter || (layout.delimiter) || M.sniffDelimiter(f.text)).rows;
      rows.slice(0, 10).forEach(function (r) { width = Math.max(width, r.length); });
      headers = [];
      for (var c = 0; c < width; c++) headers.push('Column ' + (c + 1));
    }
    var opt = function (role) {
      var cur = f.options.mapping ? f.options.mapping[role] : map[role];
      var o = '<option value="">(none)</option>';
      headers.forEach(function (h, idx) { o += '<option value="' + idx + '"' + (cur === idx ? ' selected' : '') + '>' + esc((h || 'Column ' + (idx + 1)).slice(0, 40)) + '</option>'; });
      return o;
    };
    var html = '<div class="mapper" role="group" aria-label="Choose columns for ' + esc(f.name) + '"><h4>Which column is which?</h4><p class="hint">Pick the columns by hand if the guess was wrong. Use either one signed amount column, or separate money out and money in columns.</p><div class="mapper-grid">';
    MAP_ROLES.forEach(function (role) {
      html += '<label class="field"><span>' + esc(M.ROLE_LABELS[role]) + '</span><select id="map-' + f.uid + '-' + role + '" data-map-role="' + role + '">' + opt(role) + '</select></label>';
    });
    var hr = f.options.headerRow !== undefined ? f.options.headerRow : (layout.headerRow !== undefined ? layout.headerRow : -1);
    html += '<label class="field"><span>Header row (0 for none)</span><input type="number" min="0" max="40" id="map-' + f.uid + '-header" data-map-header value="' + (hr + 1) + '"></label>';
    var order = f.options.dateOrder || layout.dateOrder || 'DMY';
    html += '<label class="field"><span>Dates</span><select id="map-' + f.uid + '-order" data-map-order><option value="DMY"' + (order === 'DMY' ? ' selected' : '') + '>Day first (UK: 14/03/2026)</option><option value="MDY"' + (order === 'MDY' ? ' selected' : '') + '>Month first (US: 03/14/2026)</option></select></label>';
    var sign = f.options.signConvention || 'auto';
    html += '<label class="field"><span>A signed amount means</span><select id="map-' + f.uid + '-sign" data-map-sign><option value="auto"' + (sign === 'auto' ? ' selected' : '') + '>Work it out</option><option value="negative-out"' + (sign === 'negative-out' ? ' selected' : '') + '>Negative is money out</option><option value="positive-out"' + (sign === 'positive-out' ? ' selected' : '') + '>Positive is money out (credit cards)</option></select></label>';
    html += '</div><div class="drop-actions"><button type="button" class="btn btn-copper btn-small" data-action="apply-map" data-file="' + f.uid + '">Read it again with these choices</button><button type="button" class="btn btn-plain btn-small" data-action="reset-map" data-file="' + f.uid + '">Go back to the automatic guess</button></div></div>';
    return html;
  }

  function coverageHtml() {
    var accs = A.merged.accounts;
    if (!accs.length) return '';
    var s = Math.min.apply(null, accs.map(function (a) { return a.start; })), e = Math.max.apply(null, accs.map(function (a) { return a.end; }));
    var span = Math.max(1, e - s);
    var ps = M.ymd(s), pe = M.ymd(e);
    var months = (pe.y - ps.y) * 12 + pe.m - ps.m + 1;
    var html = '<div class="section-title"><h3>What the statements cover</h3><p>' + esc(M.longDate(s)) + ' to ' + esc(M.longDate(e)) + '</p></div><div class="plate coverage" style="--months:' + months + '">';
    accs.forEach(function (a) {
      var left = (a.start - s) / span * 100, width = Math.max(1.5, (a.end - a.start) / span * 100);
      var days = a.end - a.start + 1;
      html += '<div class="cov-row"><div class="cov-name">' + esc(a.account) + '</div><div class="cov-track" style="--months:' + months + '"><div class="cov-bar" style="left:' + left.toFixed(2) + '%;width:' + width.toFixed(2) + '%"><span>' + (days >= 60 ? Math.round(days / 30.44) + ' months' : days + ' days') + '</span></div></div></div>';
    });
    var ticks = '';
    var step = Math.max(1, Math.ceil(months / 6));
    for (var k = 1; k <= months; k += step) {
      var tm = ps.y * 12 + ps.m - 1 + k, ty = Math.floor(tm / 12), tmo = tm % 12 + 1;
      var at = (M.dayFromYMD(ty, tmo, 1) - s) / span * 100;
      if (at > 96) break;
      ticks += '<span style="left:' + at.toFixed(2) + '%">' + esc(M.MONTH_NAMES[tmo - 1].slice(0, 3) + (tmo === 1 || k === 1 ? ' ' + String(ty).slice(2) : '')) + '</span>';
    }
    html += '<div class="cov-axis" aria-hidden="true"><div></div><div class="cov-ticks">' + ticks + '</div></div></div>';
    return html;
  }

  function checksHtml() {
    var items = [];
    var accs = A.merged.accounts;
    accs.forEach(function (a) {
      var days = a.end - a.start + 1;
      if (days < 80) items.push(['', esc(a.account) + ' covers only ' + days + ' days. Monthly payments need about three months to be picked out with confidence; download a longer range if you can.']);
      else if (days < 360) items.push(['info', esc(a.account) + ' covers ' + Math.round(days / 30.44) + ' months: enough for monthly payments. Yearly renewals need more than a year, so single payments that look like renewals are listed as possible regulars.']);
      else items.push(['good', esc(a.account) + ' covers ' + Math.round(days / 30.44) + ' months: enough to spot yearly renewals too.']);
    });
    if (A.merged.duplicates) items.push(['info', plural(A.merged.duplicates, 'payment') + ' appeared in more than one file and ' + (A.merged.duplicates === 1 ? 'was' : 'were') + ' counted once.']);
    var skipped = A.statements.reduce(function (n, st) { return n + st.skipped.length; }, 0);
    if (skipped) items.push(['', plural(skipped, 'row') + ' could not be used. Each file above lists them with the reason; none of them changes the regular payments unless the reason says it is a real payment.']);
    if (A.result.transferCount) items.push(['info', plural(A.result.transferCount / 2, 'transfer') + ' between your own accounts ' + (A.result.transferCount === 2 ? 'was' : 'were') + ' matched up, so moving money around is not counted as spending.']);
    return '<div class="section-title"><h3>Checks on your data</h3></div><div class="plate"><ul class="notes checklist">' + items.map(function (it) { return '<li class="' + it[0] + '">' + it[1] + '</li>'; }).join('') + '</ul></div>';
  }

  /* ---------------------------------------------------------------- */
  /* View 2: regular payments                                          */
  /* ---------------------------------------------------------------- */

  var VALVE = '<svg viewBox="-25 -25 50 50" aria-hidden="true"><circle r="19" fill="none" stroke="currentColor" stroke-width="5"/><path d="M-19 0H19M0-19V19M-13.4-13.4L13.4 13.4M13.4-13.4L-13.4 13.4" stroke="currentColor" stroke-width="3"/><circle r="6" fill="#1b1b1b" stroke="currentColor" stroke-width="2.5"/></svg>';

  function hasCheck(s) { return s.flags.some(function (f) { return f.tone === 'warn' || f.tone === 'alert'; }); }
  function filterSeries(list) {
    var q = state.search.trim().toLowerCase();
    return list.filter(function (s) {
      if (q && (s.name + ' ' + catOf(s.category).label + ' ' + s.method).toLowerCase().indexOf(q) < 0) return false;
      switch (state.filter) {
        case 'check': return s.status === 'active' && hasCheck(s);
        case 'undecided': return s.status === 'active' && !decisionOf(s.id) && catOf(s.category).cost !== false;
        case 'essential': return s.status === 'active' && catOf(s.category).essential;
        case 'optional': return s.status === 'active' && !catOf(s.category).essential && catOf(s.category).cost !== false;
        case 'stopped': return s.status === 'stopped';
        default: return true;
      }
    });
  }
  function sortSeries(list) {
    var by = state.sort;
    return list.slice().sort(function (a, b) {
      if (a.status !== b.status) return a.status === 'stopped' ? 1 : -1;
      if (by === 'next') return (a.nextDue === null ? 1e9 : a.nextDue) - (b.nextDue === null ? 1e9 : b.nextDue) || b.annual - a.annual;
      if (by === 'name') return a.name.toLowerCase() < b.name.toLowerCase() ? -1 : a.name.toLowerCase() > b.name.toLowerCase() ? 1 : 0;
      if (by === 'confidence') return a.confidence - b.confidence || b.annual - a.annual;
      return b.annual - a.annual;
    });
  }

  function renderRegulars() {
    var el = $('#regulars-body');
    if (!hasData()) { el.innerHTML = emptyRegulars(); return; }
    var r = A.result, t = P.totals;
    var all = r.series;
    var counts = {
      all: all.length,
      check: all.filter(function (s) { return s.status === 'active' && hasCheck(s); }).length,
      undecided: all.filter(function (s) { return s.status === 'active' && !decisionOf(s.id) && catOf(s.category).cost !== false; }).length,
      essential: all.filter(function (s) { return s.status === 'active' && catOf(s.category).essential; }).length,
      optional: all.filter(function (s) { return s.status === 'active' && !catOf(s.category).essential && catOf(s.category).cost !== false; }).length,
      stopped: all.filter(function (s) { return s.status === 'stopped'; }).length
    };
    var html = '';
    var e = t.essentialMonthly, o = t.optionalMonthly, tot = Math.max(1, e + o);
    var dec = { keep: 0, cancel: 0, review: 0, none: 0 };
    all.filter(M.isCost).forEach(function (s) { var d = decisionOf(s.id); if (d === 'ignore') return; dec[d || 'none']++; });
    html += '<div class="plate"><div class="grid-2"><div><span class="label-tag">Committed every month</span><p style="margin:8px 0 0"><span class="amount" style="font-size:34px;font-weight:700">' + money(t.monthly) + '</span> <span class="hint">a month, ' + money(t.annual) + ' a year</span></p>';
    html += '<div class="split-bar" role="img" aria-label="' + esc('Essentials ' + money(e) + ' a month, optional ' + money(o) + ' a month') + '"><span style="width:' + (e / tot * 100).toFixed(2) + '%;background:var(--essential)"></span><span style="width:' + (o / tot * 100).toFixed(2) + '%;background:var(--optional)"></span></div>';
    html += '<ul class="legend"><li><i style="background:var(--essential)"></i>Essentials ' + money(e) + '</li><li><i style="background:var(--optional)"></i>Optional ' + money(o) + '</li></ul></div>';
    html += '<div><span class="label-tag">Your decisions so far</span><ul class="legend" style="margin-top:12px;display:grid;gap:6px"><li><i style="background:var(--green)"></i>Keep: ' + dec.keep + '</li><li><i style="background:var(--red)"></i>Cancel: ' + dec.cancel + ' (' + money(t.cancelMonthly) + ' a month)</li><li><i style="background:var(--amber)"></i>Look again: ' + dec.review + '</li><li><i style="background:var(--enamel)"></i>Not decided: ' + dec.none + '</li></ul>' + (Object.keys(state.aliases).length ? '<p class="hint" style="margin-top:10px">Merged payees: ' + Object.keys(state.aliases).map(function (k) { return esc(M.displayName(k)) + ' into ' + esc(M.displayName(state.aliases[k])) + ' <button type="button" class="linkish" data-action="unmerge" data-key="' + esc(k) + '">undo</button>'; }).join('; ') + '</p>' : '') + '</div></div></div>';

    var chips = [['all', 'All'], ['check', 'To check'], ['undecided', 'Not decided'], ['essential', 'Essentials'], ['optional', 'Optional'], ['stopped', 'Stopped']];
    html += '<div class="toolbar" style="margin-top:18px"><div class="chips" role="group" aria-label="Show">' + chips.map(function (c) { return '<button type="button" class="chip" data-filter="' + c[0] + '" aria-pressed="' + (state.filter === c[0]) + '">' + c[1] + '<span class="count">' + counts[c[0]] + '</span></button>'; }).join('') + '</div>';
    html += '<input type="search" class="search" id="reg-search" placeholder="Search by name or category" aria-label="Search regular payments" value="' + esc(state.search) + '">';
    html += '<select class="sort" id="reg-sort" aria-label="Sort by"><option value="yearly"' + (state.sort === 'yearly' ? ' selected' : '') + '>Biggest yearly cost first</option><option value="next"' + (state.sort === 'next' ? ' selected' : '') + '>Next due first</option><option value="name"' + (state.sort === 'name' ? ' selected' : '') + '>Name</option><option value="confidence"' + (state.sort === 'confidence' ? ' selected' : '') + '>Least sure first</option></select></div>';

    var list = sortSeries(filterSeries(all));
    html += '<div class="manifold">';
    if (!list.length) html += '<div class="plate none-match">Nothing matches this filter. <button type="button" class="linkish" data-filter="all">Show them all</button></div>';
    list.forEach(function (s) { html += regCard(s); });
    html += '</div>';

    if (r.candidates.length) {
      html += '<div class="section-title"><h3>Possible regular payments</h3><p>Not enough payments yet to be sure. Confirm any that do come round.</p></div><div class="candidates">';
      r.candidates.forEach(function (c) {
        html += '<article class="cand"><h4>' + esc(c.name) + '</h4><div class="amount">' + money(c.amount) + '</div><p>' + esc(c.reason) + '</p><div class="row"><button type="button" class="btn btn-small" data-action="confirm" data-id="' + esc(c.id) + '" data-cadence="yearly">It renews yearly</button><button type="button" class="btn btn-small" data-action="confirm" data-id="' + esc(c.id) + '" data-cadence="monthly">It is monthly</button></div></article>';
      });
      html += '</div>';
    }
    if (r.income.length) {
      html += '<div class="section-title"><h3>Money coming in regularly</h3><p>Used to work out what is due before payday.</p></div><div class="plate">';
      r.income.forEach(function (s) {
        html += '<div class="income-row"><div><b>' + esc(s.name) + '</b><div class="hint">' + esc(M.CADENCE_BY_ID[s.cadence].label + ', ' + M.whenText(s) + ', ' + s.count + ' payments') + '</div></div><div class="amount" style="font-weight:700">' + (s.amounts.kind === 'variable' ? 'about ' : '') + money(s.typical) + '<div class="hint" style="text-align:right">' + (s.status === 'active' && s.nextDue !== null ? 'next ' + esc(dayLabel(s.nextDue)) : 'stopped') + '</div></div></div>';
      });
      html += '</div>';
    }
    el.innerHTML = html;
  }
  function emptyRegulars() {
    return '<div class="plate empty-state"><h3>Nothing to show yet</h3><p>Add a bank statement on the Statements step and every regular payment will appear here as a valve you can open or shut.</p><button type="button" class="btn btn-copper" data-go="statements">Add a statement</button></div>';
  }

  function timelineSvg(s) {
    var r = A.result;
    var start = r.dataStart, end = Math.max(r.asOf + 35, r.dataEnd);
    var span = Math.max(1, end - start);
    var x = function (d) { return 6 + (d - start) / span * 588; };
    var out = '<svg class="timeline" viewBox="0 0 600 26" preserveAspectRatio="none" aria-hidden="true"><line x1="4" y1="13" x2="596" y2="13" stroke="#cfc6b1" stroke-width="2"/>';
    out += '<line x1="' + x(r.asOf).toFixed(1) + '" y1="3" x2="' + x(r.asOf).toFixed(1) + '" y2="23" stroke="#3d5a55" stroke-width="1.5" stroke-dasharray="3 2"/>';
    var extras = {};
    s.extras.forEach(function (d) { extras[d] = 1; });
    s.payments.forEach(function (p) {
      out += '<circle cx="' + x(p.day).toFixed(1) + '" cy="13" r="5" fill="' + (extras[p.day] ? '#c23b2a' : '#b4643a') + '" stroke="#13312d" stroke-width="1.5"/>';
    });
    if (s.nextDue !== null && s.nextDue <= end) out += '<circle cx="' + x(s.nextDue).toFixed(1) + '" cy="13" r="5" fill="#fbf7ee" stroke="#b4643a" stroke-width="2.5" stroke-dasharray="3 2"/>';
    return out + '</svg>';
  }

  function regCard(s) {
    var d = state.decisions[s.id] || {};
    var dec = d.decision || '';
    var cat = catOf(s.category);
    var key = hid(s.id);
    var variable = s.amounts.kind === 'variable';
    var sub = [M.CADENCE_BY_ID[s.cadence].label + ' ' + M.whenText(s)];
    if (s.method !== 'unknown') sub.push('by ' + s.method);
    if (s.status === 'active' && s.nextDue !== null) sub.push('next ' + dayLabel(s.nextDue));
    else sub.push('last ' + M.longDate(s.last));
    sub.push(s.confidenceLabel.toLowerCase() + ' (' + s.confidence + ')');
    var html = '<article class="plate reg" id="reg-' + key + '" data-id="' + esc(s.id) + '" data-decision="' + dec + '" data-status="' + s.status + '">';
    html += '<div class="reg-main"><div class="valve">' + VALVE + '</div><div><div class="reg-name"><h4>' + esc(s.name) + '</h4><span class="cat-tag ' + catClass(s.category) + '">' + esc(cat.label) + '</span>' + (s.manual ? '<span class="cat-tag nocost">Confirmed by you</span>' : '') + '</div><p class="reg-sub">' + esc(sub.join(' \u00b7 ')) + '</p></div>';
    html += '<div class="reg-amount"><div class="big">' + (variable ? '<span class="per">about </span>' : '') + money(s.typical) + '</div><div class="per">' + esc(PER[s.cadence]) + (s.cadence !== 'monthly' ? ', ' + money(s.monthly) + ' a month' : '') + '</div><div class="year">' + money(s.annual) + ' a year</div></div>';
    var flags = s.flags.slice();
    if (A.since) {
      A.since.stillCharging.forEach(function (c) { if (c.id === s.id) flags.unshift({ tone: 'alert', text: 'Still charging: ' + plural(c.payments.length, 'payment') + ' (' + money(c.total) + ') since you decided to cancel on ' + M.longDate(c.decidedOn) + '.' }); });
    }
    if (flags.length) html += '<ul class="flags">' + flags.map(function (f) { return '<li class="flag ' + f.tone + '">' + esc(f.text) + '</li>'; }).join('') + '</ul>';
    html += '</div><div class="reg-foot">' + timelineSvg(s);
    var opts = [['keep', 'Keep'], ['cancel', 'Cancel'], ['review', 'Look again'], ['ignore', 'Not a cost']];
    html += '<fieldset class="decide"><legend>Decision for ' + esc(s.name) + '</legend>' + opts.map(function (o) { return '<label><input type="radio" name="dec-' + key + '" value="' + o[0] + '" data-decide="' + esc(s.id) + '"' + (dec === o[0] ? ' checked' : '') + '><span>' + o[1] + '</span></label>'; }).join('') + '</fieldset>';
    html += '<details class="reg-more"' + (state.open[s.id] ? ' open' : '') + ' data-open-key="' + esc(s.id) + '"><summary>Why it was picked out, and every payment</summary>' + (state.open[s.id] ? detailHtml(s, key, d) : '') + '</details>';
    html += '</div></article>';
    return html;
  }

  function detailHtml(s, key, d) {
    var sug = M.suggest(s);
    var html = '<div class="reg-detail"><div><h4>Why it counts as regular</h4><ul class="reasons">' + s.reasons.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') + '</ul>';
    html += '<div class="suggest"><b>Suggestion:</b> ' + esc(sug.text) + '</div>';
    html += '<h4>Every payment</h4><div class="table-wrap"><table><thead><tr><th>Date</th><th class="num">Amount</th><th>As it appears</th></tr></thead><tbody>';
    s.payments.slice().reverse().forEach(function (p) { html += '<tr><td>' + esc(M.longDate(p.day)) + '</td><td class="num">' + money(p.amount) + '</td><td>' + esc(p.desc) + (s.accounts.length > 1 ? ' <span class="hint">(' + esc(p.account) + ')</span>' : '') + '</td></tr>'; });
    html += '</tbody></table></div></div><div>';
    html += '<h4>Tidy it up</h4><div class="edit-grid">';
    html += '<label class="field"><span>Name</span><input type="text" id="name-' + key + '" data-series="' + esc(s.id) + '" data-edit="name" value="' + esc(s.name) + '"></label>';
    html += '<label class="field"><span>Paid by</span><select id="method-' + key + '" data-series="' + esc(s.id) + '" data-edit="method">' + M.METHODS.map(function (m) { return '<option value="' + m + '"' + (s.method === m ? ' selected' : '') + '>' + (m === 'unknown' ? 'Not sure' : m.charAt(0).toUpperCase() + m.slice(1)) + '</option>'; }).join('') + '</select></label>';
    html += '<label class="field"><span>Category</span><select id="cat-' + key + '" data-series="' + esc(s.id) + '" data-edit="category">' + M.CATEGORIES.filter(function (c) { return c.id !== 'income'; }).map(function (c) { return '<option value="' + c.id + '"' + (s.category === c.id ? ' selected' : '') + '>' + esc(c.label) + '</option>'; }).join('') + '</select></label>';
    var others = {};
    A.result.series.forEach(function (o) { if (o.key !== s.key) others[o.key] = o.name; });
    var keys = Object.keys(others).sort();
    html += '<label class="field"><span>Same company as</span><select id="merge-' + key + '" data-series="' + esc(s.id) + '" data-key="' + esc(s.key) + '" data-edit="merge"><option value="">(keep separate)</option>' + keys.map(function (k) { return '<option value="' + esc(k) + '">' + esc(others[k]) + '</option>'; }).join('') + '</select></label>';
    html += '</div><label class="field"><span>Note to yourself</span><textarea id="note-' + key + '" rows="2" data-series="' + esc(s.id) + '" data-edit="note" placeholder="For example: cheaper plan available, check in March">' + esc(d.note || '') + '</textarea></label>';
    html += '<label class="field"><span>Days of notice before the next payment (for the cancel-by date)</span><input type="number" min="0" max="90" id="notice-' + key + '" data-series="' + esc(s.id) + '" data-edit="notice" value="' + (d.noticeDays !== undefined && d.noticeDays !== null ? d.noticeDays : M.noticeDaysFor(s)) + '"></label>';
    html += '</div></div>';
    return html;
  }

  /* ---------------------------------------------------------------- */
  /* View 3: calendar                                                  */
  /* ---------------------------------------------------------------- */

  /** The first month the calendar shows: this month, or next month if this one is nearly over. */
  function calStart() {
    var asOf = A.result.asOf, p = M.ymd(asOf);
    var left = M.daysInMonth(p.y, p.m) - p.d + 1;
    var total = p.y * 12 + p.m - 1 + (left < 10 ? 1 : 0);
    return total;
  }
  function horizonDays() {
    var total = calStart() + state.calMonths;
    return M.dayFromYMD(Math.floor(total / 12), total % 12 + 1, 1) - A.result.asOf;
  }
  function calendarItems(days) {
    return M.forecast(A.result, days, state.decisions).filter(function (it) {
      if (it.decision === 'ignore' && it.direction === 'out') return false;
      if (state.hideCancelled && it.decision === 'cancel') return false;
      if (!state.showIncome && it.direction === 'in') return false;
      return true;
    });
  }
  function isCostItem(it) { return it.direction === 'out' && catOf(it.category).cost !== false; }

  function renderCalendar() {
    var el = $('#calendar-body');
    if (!hasData()) { el.innerHTML = emptyRegulars(); return; }
    var r = A.result;
    var items = calendarItems(horizonDays());
    var html = '<div class="cal-controls"><div class="seg" role="group" aria-label="How far ahead">' + [[2, '2 months'], [3, '3 months'], [12, '12 months']].map(function (o) { return '<button type="button" data-months="' + o[0] + '" aria-pressed="' + (state.calMonths === o[0]) + '">' + o[1] + '</button>'; }).join('') + '</div>';
    html += '<label class="check"><input type="checkbox" id="hide-cancel"' + (state.hideCancelled ? ' checked' : '') + '> Leave out payments I plan to cancel</label>';
    html += '<label class="check"><input type="checkbox" id="show-income"' + (state.showIncome ? ' checked' : '') + '> Show money coming in</label></div>';
    if (r.payday) {
      var before = items.filter(function (it) { return isCostItem(it) && it.day < r.payday.next && it.decision !== 'cancel'; });
      var sum = before.reduce(function (a, it) { return a + it.amount; }, 0);
      var biggest = before.slice().sort(function (a, b) { return b.amount - a.amount; })[0];
      html += '<div class="plate plate-dark payday"><div class="big">' + money(sum) + '</div><div><h3 style="color:#fbf7ee">Due before payday on ' + esc(dayLabel(r.payday.next)) + '</h3><p>' + plural(before.length, 'payment') + ' leave' + (before.length === 1 ? 's' : '') + ' between ' + esc(dayLabel(r.asOf)) + ' and the day before your next ' + esc(r.payday.name) + ' (about ' + money(r.payday.typical) + ')' + (biggest ? '; the biggest is ' + esc(biggest.name) + ' at ' + money(biggest.amount) + ' on ' + esc(dayLabel(biggest.day)) : '') + '. Payments you plan to cancel are left out.</p></div></div>';
    }
    // Month grids
    var start = calStart();
    var grids = Math.min(3, state.calMonths);
    html += '<div class="months">';
    for (var g = 0; g < grids; g++) {
      var total = start + g, y = Math.floor(total / 12), m = total % 12 + 1;
      html += monthGrid(y, m, items);
    }
    html += '</div>';
    html += '<ul class="legend" style="margin-top:12px"><li><i style="background:var(--essential)"></i>Essential bill</li><li><i style="background:var(--optional)"></i>Optional</li><li><i style="background:var(--income);border-radius:2px"></i>Money in</li><li><i style="background:#fff;border:1.5px dashed var(--red)"></i>You plan to cancel</li><li><i style="background:repeating-linear-gradient(-45deg,#f5f0e4 0 3px,#ebe3d2 3px 6px)"></i>Bank holiday</li></ul>';
    // Twelve month bars
    var year = M.monthTotals(M.forecast(r, 366, state.decisions), false).slice(0, 12);
    var max = Math.max.apply(null, year.map(function (b) { return b.total; }).concat([1]));
    html += '<div class="section-title"><h3>The next twelve months</h3><p>Committed spending each month if nothing changes, after the cancellations you have marked. Yearly renewals and seasonal bills make some months heavier.</p></div><div class="plate"><div class="bars" role="img" aria-label="' + esc(year.map(function (b) { return M.MONTH_NAMES[b.m - 1] + ' ' + money(b.total); }).join(', ')) + '">';
    year.forEach(function (b) {
      var share = b.total / max, ePart = b.total ? b.essential / b.total : 0;
      html += '<div class="bar" data-label="' + M.MONTH_NAMES[b.m - 1].slice(0, 3) + ' ' + String(b.y).slice(2) + '" style="--share:' + share.toFixed(4) + ';--e:' + ePart.toFixed(4) + '"><div class="val">' + wholeMoney(b.total) + '</div><div class="bar-stack"><span class="seg-e"></span><span class="seg-o"></span></div></div>';
    });
    html += '</div><div class="bar-labels" aria-hidden="true">' + year.map(function (b) { return '<span>' + M.MONTH_NAMES[b.m - 1].slice(0, 3) + '</span>'; }).join('') + '</div><ul class="legend" style="margin-top:10px"><li><i style="background:var(--essential)"></i>Essentials</li><li><i style="background:var(--optional)"></i>Optional</li></ul></div>';
    // Agenda
    html += '<div class="section-title"><h3>Every payment, in order</h3><button type="button" class="btn btn-copper btn-small" data-action="ics">Add these to your calendar (.ics)</button></div><div class="plate"><ul class="agenda">';
    var run = 0, lastWeek = null;
    if (!items.length) html += '<li>Nothing is expected in this period.</li>';
    items.forEach(function (it) {
      var wk = it.day - ((M.weekday(it.day) + 6) % 7);
      if (wk !== lastWeek) { html += '<li class="week">Week of ' + esc(M.shortDate(wk)) + '</li>'; lastWeek = wk; }
      var cost = isCostItem(it) && it.decision !== 'cancel';
      if (cost) run += it.amount;
      var s = M.findSeries(r, it.id);
      var variable = s && s.amounts.kind === 'variable';
      html += '<li class="' + (it.direction === 'in' ? 'in' : '') + (it.decision === 'cancel' ? ' cancel' : '') + '"><span class="when">' + esc(dayLabel(it.day)) + '</span><span class="who">' + esc(it.name) + (it.late ? ' <span class="hint">(due, not in your statement yet)</span>' : '') + (it.decision === 'cancel' ? ' <span class="hint">(you plan to cancel)</span>' : '') + '</span><span class="amt">' + (it.direction === 'in' ? '+' : (variable ? '~' : '')) + money(it.amount) + '</span><span class="run">' + (it.direction === 'out' && cost ? money(run) : '') + '</span></li>';
    });
    html += '</ul></div>';
    el.innerHTML = html;
  }
  function monthGrid(y, m, items) {
    var first = M.dayFromYMD(y, m, 1), n = M.daysInMonth(y, m);
    var byDay = {};
    items.forEach(function (it) { if (it.day >= first && it.day < first + n) (byDay[it.day] = byDay[it.day] || []).push(it); });
    var monthTotal = 0;
    Object.keys(byDay).forEach(function (k) { byDay[k].forEach(function (it) { if (isCostItem(it) && it.decision !== 'cancel') monthTotal += it.amount; }); });
    var payday = A.result.payday ? A.result.payday.next : null;
    var holidays = M.bankHolidays(y);
    var html = '<div class="plate month"><h4>' + M.MONTH_NAMES[m - 1] + ' ' + y + '</h4><p class="mtotal">' + money(monthTotal) + ' committed</p><div class="cal-grid">';
    ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].forEach(function (dname) { html += '<div class="cal-dow" aria-hidden="true">' + dname + '</div>'; });
    var lead = (M.weekday(first) + 6) % 7;
    for (var i = 0; i < lead; i++) html += '<div class="cal-day blank" aria-hidden="true"></div>';
    for (var d = first; d < first + n; d++) {
      var list = byDay[d] || [];
      var sum = 0;
      list.forEach(function (it) { if (isCostItem(it) && it.decision !== 'cancel') sum += it.amount; });
      var heat = sum >= 20000 ? 3 : sum >= 5000 ? 2 : sum > 0 ? 1 : 0;
      var cls = ['cal-day'];
      var wd = M.weekday(d);
      if (wd === 0 || wd === 6) cls.push('weekend');
      if (holidays.indexOf(d) >= 0) cls.push('holiday');
      if (d === A.result.asOf) cls.push('today');
      if (d < A.result.asOf) cls.push('past');
      if (d === payday) cls.push('payday-day');
      var label = M.DAY_NAMES[wd] + ' ' + M.longDate(d) + (holidays.indexOf(d) >= 0 ? ', bank holiday' : '') + (d === payday ? ', payday' : '') + (list.length ? ': ' + list.map(function (it) { return it.name + ' ' + money(it.amount) + (it.direction === 'in' ? ' in' : '') + (it.decision === 'cancel' ? ' (plan to cancel)' : ''); }).join(', ') : ': nothing due');
      html += '<div class="' + cls.join(' ') + '" data-heat="' + heat + '" role="img" aria-label="' + esc(label) + '" title="' + esc(label) + '"><span class="dnum">' + (d - first + 1) + '</span><div class="pips">';
      list.forEach(function (it) {
        var c = it.direction === 'in' ? 'income' : it.decision === 'cancel' ? 'cancel' : (catOf(it.category).essential ? 'essential' : 'optional');
        html += '<span class="pip ' + c + '"></span>';
      });
      html += '</div>' + (sum ? '<span class="dsum">' + wholeMoney(sum) + '</span>' : '') + '</div>';
    }
    html += '</div></div>';
    return html;
  }

  /* ---------------------------------------------------------------- */
  /* View 4: the plan                                                  */
  /* ---------------------------------------------------------------- */

  function renderPlan() {
    var el = $('#plan-body');
    if (!hasData()) { el.innerHTML = emptyRegulars(); return; }
    var r = A.result, t = P.totals;
    var html = '<div class="print-only"><h2>Still paying? Regular payments checklist</h2><p>Review of statements up to ' + esc(M.longDate(r.dataEnd)) + '. Printed ' + esc(M.longDate(TODAY)) + '.</p></div>';
    if (A.since) html += sinceHtml(A.since);
    html += '<div class="savings">';
    html += '<div class="plate saving"><span class="label-tag">Cancelling saves</span><div class="big">' + money(t.cancelMonthly) + '</div><p>a month, ' + money(t.cancelAnnual) + ' a year, from ' + plural(P.actions.length, 'payment') + ' you marked to cancel.</p></div>';
    html += '<div class="plate saving"><span class="label-tag">Over the next 12 months</span><div class="big">' + money(t.cancelNext12) + '</div><p>stays in your account if each one is cancelled before its next payment.</p></div>';
    html += '<div class="plate saving"><span class="label-tag">Still to decide</span><div class="big">' + money(t.undecidedMonthly + t.reviewMonthly) + '</div><p>a month across the payments you have not decided on or want to look at again.</p></div></div>';

    html += '<div class="section-title"><h3>Cancel, in date order</h3><p>Cancel-by dates leave a few days before the next payment (change the notice on any payment\'s details).</p></div>';
    if (!P.actions.length) html += '<div class="plate"><p>Nothing marked to cancel yet. Mark payments with <b>Cancel</b> on the Regulars step and they will appear here with what to do and a message ready to send.</p><button type="button" class="btn btn-plain btn-small" data-go="regulars">Go to the regular payments</button></div>';
    P.actions.forEach(function (a) {
      var key = hid(a.id);
      var ticks = state.ticked[a.id] || [];
      var dd = M.ymd(a.cancelBy);
      html += '<article class="plate action"><div class="cancel-by"><small>Cancel by</small><b>' + dd.d + '</b><span>' + M.MONTH_NAMES[dd.m - 1].slice(0, 3) + ' ' + dd.y + '</span></div><div>';
      html += '<h3>' + esc(a.name) + '</h3><p class="hint">' + money(a.amount) + ' ' + esc(PER[a.cadence]) + ' by ' + esc(a.method === 'unknown' ? 'an unknown method' : a.method) + (a.nextDue !== null ? '; next payment ' + esc(dayLabel(a.nextDue)) : '') + '. Saves ' + money(a.saveNext12) + ' over the next 12 months.' + (a.note ? ' Note: ' + esc(a.note) : '') + '</p>';
      html += '<ul class="steps">' + a.steps.map(function (st, i) { return '<li><label><input type="checkbox" data-tick="' + esc(a.id) + '" data-step="' + i + '"' + (ticks[i] ? ' checked' : '') + '><span>' + esc(st) + '</span></label></li>'; }).join('') + '</ul>';
      html += '<details class="no-print"' + (state.open['draft-' + a.id] ? ' open' : '') + ' data-open-key="draft-' + esc(a.id) + '"><summary class="linkish">Message to send</summary><label class="sr-only" for="draft-' + key + '">Message to ' + esc(a.name) + '</label><textarea class="draft" id="draft-' + key + '" spellcheck="true">' + esc(a.message) + '</textarea><div class="draft-row"><button type="button" class="btn btn-small" data-action="copy-draft" data-target="draft-' + key + '">Copy the message</button><span class="hint">Fill in your name and account below and it updates.</span></div></details>';
      html += '</div></article>';
    });
    html += '<div class="plate no-print" style="margin-top:16px"><h3>Your details for the messages</h3><p class="hint">Used only to fill in the drafts above. They are saved with your review file.</p><div class="details-form"><label class="field"><span>Your name</span><input type="text" id="det-name" data-detail="name" value="' + esc(state.details.name) + '" autocomplete="name"></label><label class="field"><span>Account email or customer number</span><input type="text" id="det-account" data-detail="account" value="' + esc(state.details.account) + '" autocomplete="email"></label></div></div>';

    var reviews = r.series.filter(function (s) { return M.isCost(s) && decisionOf(s.id) === 'review'; });
    var undecided = r.series.filter(function (s) { return M.isCost(s) && !decisionOf(s.id); });
    html += '<div class="grid-2" style="margin-top:18px"><div class="plate"><h3>To look at again</h3>' + (reviews.length ? '<ul class="review-list">' + reviews.map(function (s) { return '<li><span><b>' + esc(s.name) + '</b><br><span class="hint">' + esc(M.suggest(s).text) + ((state.decisions[s.id] || {}).note ? ' Note: ' + esc(state.decisions[s.id].note) : '') + '</span></span><span class="amount">' + money(s.monthly) + '/mo</span></li>'; }).join('') + '</ul>' : '<p class="hint">Nothing marked to look at again.</p>') + '</div>';
    html += '<div class="plate"><h3>Not decided yet</h3>' + (undecided.length ? '<ul class="review-list">' + undecided.map(function (s) { return '<li><span><b>' + esc(s.name) + '</b><br><span class="hint">' + esc(M.suggest(s).text) + '</span></span><span class="amount">' + money(s.monthly) + '/mo</span></li>'; }).join('') + '</ul><button type="button" class="btn btn-plain btn-small no-print" data-go="regulars" data-filter-go="undecided">Decide on these</button>' : '<p class="hint">Every regular payment has a decision.</p>') + '</div></div>';

    html += '<div class="section-title no-print"><h3>Take it with you</h3><p>Every file is made here in your browser.</p></div><div class="exports no-print">';
    var exp = [
      ['Your review file', 'Save everything (payments, decisions, notes) and reopen it next month to check what changed and that cancelled payments stopped.', 'save-review', 'Save the review (.json)'],
      ['Calendar reminders', 'Every expected payment for the next three months with a reminder the day before, plus a reminder on each cancel-by date.', 'ics', 'Download the calendar (.ics)'],
      ['The register', 'One row per regular payment: how often, typical amount, yearly cost, next due, checks and your decision. Opens in any spreadsheet.', 'register', 'Download the register (.csv)'],
      ['Twelve-month budget', 'Committed spending by category for each of the next twelve months, after your cancellations, ready for a budget spreadsheet.', 'budget', 'Download the budget (.csv)'],
      ['A printed checklist', 'This plan as a tidy checklist with tick boxes, for the fridge door or a folder.', 'print', 'Print the checklist'],
      ['A summary to paste', 'A short plain-text summary of what you pay and what you are cancelling, for notes, a housemate or yourself.', 'copy-summary', 'Copy the summary']
    ];
    exp.forEach(function (x) { html += '<div class="plate export"><h4>' + x[0] + '</h4><p>' + x[1] + '</p><button type="button" class="btn ' + (x[2] === 'save-review' ? 'btn-copper' : 'btn-plain') + ' btn-small" data-action="' + x[2] + '">' + x[3] + '</button></div>'; });
    html += '</div>';
    el.innerHTML = html;
  }

  function sinceHtml(s) {
    var items = [];
    s.stillCharging.forEach(function (c) { items.push('<li class="alert">' + esc(c.name) + ' took ' + plural(c.payments.length, 'payment') + ' (' + money(c.total) + ', last on ' + M.longDate(c.payments[c.payments.length - 1].day) + ') after you decided to cancel it on ' + esc(M.longDate(c.decidedOn)) + '. ' + (c.method === 'card' ? 'If you did cancel, ask your card provider to stop the recurring payment and claim it back.' : c.method === 'direct debit' ? 'If you did cancel, claim it back from your bank under the Direct Debit Guarantee.' : 'Check it was cancelled, and ask for a refund.') + '</li>'); });
    s.newSince.forEach(function (n) { items.push('<li>Found since then: ' + esc(n.name) + ', ' + money(n.amount) + ' ' + esc(PER[n.cadence]) + ' (first seen ' + esc(M.longDate(n.first)) + ').</li>'); });
    s.priceChanges.forEach(function (c) { items.push('<li>' + esc(c.name) + ' changed from ' + money(c.from) + ' to ' + money(c.to) + '.</li>'); });
    s.stoppedSince.forEach(function (c) { items.push('<li>' + esc(c.name) + ' has stopped (last payment ' + esc(M.longDate(c.last)) + ').</li>'); });
    if (!items.length) items.push('<li>Nothing has changed since then, and nothing you cancelled has charged you again.</li>');
    return '<div class="plate recheck" style="margin-bottom:18px"><h3>Since your last review on ' + esc(M.longDate(s.reviewedOn)) + '</h3><ul class="recheck-list">' + items.join('') + '</ul></div>';
  }

  function summaryText() {
    var r = A.result, t = P.totals;
    var lines = ['Regular payments, from statements up to ' + M.longDate(r.dataEnd), ''];
    lines.push('Committed: ' + money(t.monthly) + ' a month (' + money(t.annual) + ' a year), essentials ' + money(t.essentialMonthly) + ' and optional ' + money(t.optionalMonthly) + ' a month.');
    lines.push('');
    r.series.filter(M.isCost).forEach(function (s) {
      var d = decisionOf(s.id);
      if (d === 'ignore') return;
      lines.push('- ' + s.name + ': ' + (s.amounts.kind === 'variable' ? 'about ' : '') + money(s.typical) + ' ' + PER[s.cadence] + (s.nextDue !== null ? ', next ' + M.longDate(s.nextDue) : '') + (d ? ' [' + M.DECISION_LABELS[d] + ']' : ''));
    });
    if (P.actions.length) {
      lines.push('', 'Cancelling ' + plural(P.actions.length, 'payment') + ' saves ' + money(t.cancelMonthly) + ' a month (' + money(t.cancelNext12) + ' over the next 12 months):');
      P.actions.forEach(function (a) { lines.push('- ' + a.name + ': cancel by ' + M.longDate(a.cancelBy)); });
    }
    return lines.join('\n');
  }

  function reviewText() {
    return M.projectFile({
      transactions: A.merged.transactions, result: A.result, decisions: state.decisions, aliases: state.aliases, names: state.names,
      manual: state.manual, overrides: state.overrides, details: state.details, accounts: A.merged.accounts, reviewedOn: A.result.asOf
    });
  }

  /* ---------------------------------------------------------------- */
  /* How it works                                                      */
  /* ---------------------------------------------------------------- */

  function renderHow() {
    var cad = M.CADENCES.map(function (c) { return '<tr><td>' + esc(c.label) + '</td><td>' + (c.months ? 'Same day of the month (or a rule such as the last Friday), within ' + c.tol + ' days late or 3 early' : 'Every ' + c.days + ' days, within ' + c.tol + (c.tol === 1 ? ' day' : ' days')) + '</td><td class="num">' + c.min + '</td></tr>'; }).join('');
    $('#how-body').innerHTML = '<div class="how">' +
      '<div class="plate"><h3>1. Reading your export</h3><p>The app looks for a header row anywhere in the first 40 lines, matches column names that banks use (Date, Transaction date, Description, Name, Counter party, Amount, Paid out, Paid in, Money out, Debit, Credit and many more), and reads amounts with pound signs, thousands separators, brackets, a trailing minus, DR and CR. Dates can be UK (14/03/2026), ISO (2026-03-14), written out (14 Mar 2026) or timestamps. If every date could be read either way it assumes UK order and says so. Rows it cannot use are listed with the reason, never silently dropped. Declined, reversed and pending payments are left out because no money left.</p><p>Two files that are the same account exported twice are spotted when at least 80% of one\'s payments also appear in the other, and payments in overlapping months are only counted once. Money that leaves one of your accounts and arrives in another within three days is matched as a transfer, not spending.</p></div>' +
      '<div class="plate"><h3>2. Finding what is regular</h3><p>Descriptions are cleaned of the parts that change every time (dates, card numbers, references, "CARD PAYMENT TO", payment processors before a star) to give each payee a key. Each payee\'s payments are then tested against eight schedules:</p><div class="table-wrap"><table class="cadence-table"><thead><tr><th>Schedule</th><th>What counts as on time</th><th class="num">Payments needed</th></tr></thead><tbody>' + cad + '</tbody></table></div><p class="hint" style="margin-top:8px">Direct debits and standing orders need one fewer payment, as do monthly payments whose description names a kind of subscription. One missed payment in four is allowed. A payee with several subscriptions at different prices (an app store bill, say) is split by amount, and runs at different prices that follow on from each other are joined as a price change.</p></div>' +
      '<div class="plate"><h3>3. The checks</h3><ul><li><b>Price rise:</b> the amount stepped up and stayed up.</li><li><b>Intro price ended:</b> the first one to three payments were less than half the later price.</li><li><b>Charged twice:</b> an extra payment of the same amount within a quarter of the usual gap.</li><li><b>New:</b> first taken recently, after the statement had already been running for a while.</li><li><b>Stopped:</b> at least one expected payment is missing at the end of the statement.</li><li><b>Overlap:</b> two or more active services of the same kind (video, music, cloud storage, gyms and so on).</li><li><b>Still charging:</b> when you reopen a saved review, any payment taken after the date you decided to cancel plus your notice days.</li></ul></div>' +
      '<div class="plate"><h3>4. Forecasting</h3><p>Each payment is projected forward from its last due date. Monthly payments keep their usual day of the month (the last day where the month is shorter); direct debits and standing orders due on a weekend or an England and Wales bank holiday move to the next working day. Bills that vary use the same month last year when there is a year of history (so winter energy bills look like winter), otherwise the median of the last three. Costs a month are worked out from the yearly total, so a weekly £15.50 is £67.17 a month, not £62.</p></div>' +
      '<div class="plate"><h3>Your data stays here</h3><p>This page makes no network requests at all. Files you drop are read by your browser, held in memory, and gone when you close the tab unless you save a review file (and, as a convenience, the browser may keep a copy of your last review on this device; you can clear it any time).</p><button type="button" class="btn btn-small btn-danger" data-action="forget-local">Forget the copy kept in this browser</button></div>' +
      '<div class="plate"><h3>Limits worth knowing</h3><ul><li>It only sees what is in your exports: a yearly renewal paid from an account you did not load will not appear.</li><li>Payments that change payee name completely (after a rebrand, say) look like a stop and a new start; use "Same company as" to join them.</li><li>Irregular but real commitments (termly fees, quarterly bills that drift) may only show as possible regulars.</li><li>Bank holiday rules cover England and Wales. Scottish and Northern Irish holidays differ.</li><li>It is a checking tool, not financial advice; the steps for cancelling are general and the company\'s own terms apply.</li></ul></div>' +
      '</div>';
  }

  /* ---------------------------------------------------------------- */
  /* Loading files, the sample and saved reviews                       */
  /* ---------------------------------------------------------------- */

  function readFiles(fileList) {
    var files = Array.prototype.slice.call(fileList || []);
    if (!files.length) return;
    var dz = $('#dropzone');
    dz.classList.add('busy');
    var reviews = files.filter(function (f) { return /\.json$/i.test(f.name); });
    var others = files.filter(function (f) { return !/\.json$/i.test(f.name); });
    var tooBig = others.filter(function (f) { return f.size > 40 * 1024 * 1024; });
    others = others.filter(function (f) { return f.size <= 40 * 1024 * 1024; });
    var pending = others.length + reviews.length;
    var added = [];
    var finish = function () {
      pending--;
      if (pending > 0) return;
      dz.classList.remove('busy');
      if (state.isSample && added.length) { clearData(); state.isSample = false; }
      added.forEach(function (f) { state.files.push(f); });
      setTimeout(function () {
        refresh();
        var st = A.statements.slice(-added.length);
        var read = st.filter(function (s) { return s.ok; }).length;
        if (added.length) toast(read === added.length ? 'Read ' + plural(added.length, 'file') + '. ' + plural(A.result.series.length, 'regular payment') + ' found.' : 'Read ' + read + ' of ' + plural(added.length, 'file') + '. See the notes on each file.');
        if (added.length) show('statements');
      }, 0);
    };
    if (tooBig.length) toast(tooBig.map(function (f) { return f.name; }).join(', ') + ' is over 40 MB, so it was not opened.');
    if (!pending) { dz.classList.remove('busy'); return; }
    reviews.forEach(function (f) {
      var rd = new FileReader();
      rd.onload = function () { openReview(String(rd.result), f.name, true); finish(); };
      rd.onerror = function () { toast('Could not open ' + f.name + '.'); finish(); };
      rd.readAsText(f);
    });
    others.forEach(function (f) {
      var rd = new FileReader();
      rd.onload = function () {
        var text = String(rd.result);
        if (text.indexOf('\ufffd') >= 0 && !f._retried) {
          // Not UTF-8: read it again as Windows-1252, which older bank exports use.
          var rd2 = new FileReader();
          rd2.onload = function () { added.push({ uid: uid(), name: f.name, text: String(rd2.result), account: '', accountGiven: false, options: {} }); finish(); };
          rd2.onerror = function () { added.push({ uid: uid(), name: f.name, text: text, account: '', accountGiven: false, options: {} }); finish(); };
          rd2.readAsText(f, 'windows-1252');
          return;
        }
        added.push({ uid: uid(), name: f.name, text: text, account: '', accountGiven: false, options: {} });
        finish();
      };
      rd.onerror = function () { toast('Could not open ' + f.name + '.'); finish(); };
      rd.readAsText(f);
    });
  }

  function clearData() {
    state.files = []; state.extra = []; state.saved = null;
    state.decisions = {}; state.names = {}; state.aliases = {}; state.manual = []; state.overrides = {};
    state.open = {}; state.ticked = {}; state.mapperFor = null;
  }

  function openReview(text, name, quiet) {
    var data = M.readProject(text);
    if (data.error) { toast((name ? name + ': ' : '') + data.error); return false; }
    clearData();
    state.isSample = false;
    state.extra = data.transactions;
    state.decisions = data.decisions;
    state.names = data.names; state.aliases = data.aliases; state.manual = data.manual; state.overrides = data.overrides || {};
    state.details = { name: (data.details && data.details.name) || state.details.name || '', account: (data.details && data.details.account) || state.details.account || '' };
    var decisionsCopy = {};
    Object.keys(data.decisions).forEach(function (k) { decisionsCopy[k] = Object.assign({}, data.decisions[k]); });
    state.saved = { reviewedOn: data.reviewedOn, decisions: decisionsCopy, known: data.known };
    if (!quiet) { refresh(); show('statements'); }
    toast('Reopened the review from ' + M.longDate(data.reviewedOn) + (data.badRows ? ' (' + plural(data.badRows, 'row') + ' could not be read)' : '') + '.');
    return true;
  }

  var SAMPLE_DECISIONS = {
    'HARBOUR LETTINGS RENT~monthly~1': { decision: 'keep' },
    'BRIGHTSPARK ENERGY~monthly~1': { decision: 'keep', note: 'Fixed tariff ends in March: compare then.' },
    'HILLTOP BROADBAND~monthly~1': { decision: 'review', note: 'Ask for the out-of-contract deal.' },
    'MOBI-MOTO SIM ONLY~monthly~1': { decision: 'keep' },
    'IRONWORKS GYM~monthly~1': { decision: 'cancel', note: 'Use the university sports centre instead.' },
    'GADGETGUARD PHONE COVER~monthly~1': { decision: 'cancel', decidedOn: '2026-10-20', note: 'Phone is covered by the contents insurance.' },
    'SAVINGS TRANSFER~monthly~1': { decision: 'ignore' },
    'STUDENT CARD REPAYMENT~monthly~1': { decision: 'ignore' },
    'RIVERWATCH TRUST~monthly~1': { decision: 'keep' },
    'TUNEWAVE MUSIC~monthly~1': { decision: 'keep' },
    'STREAMCRATE.TV~monthly~1': { decision: 'cancel', note: 'Only watched one series.' },
    'REELHOUSE+~monthly~1': { decision: 'keep' },
    'LINGOLEAP LANGUAGE~monthly~1': { decision: 'review', note: 'Worth it only if I keep up the Czech practice.' }
  };
  function loadSample() {
    var data;
    try { data = JSON.parse($('#sample-files').textContent); } catch (e) { return; }
    clearData();
    state.isSample = true;
    state.files = data.files.map(function (f) { return { uid: uid(), name: f.name, text: f.text, account: f.account || '', accountGiven: !!f.account, options: {} }; });
    state.details = { name: 'A. Holder', account: 'a.holder@example.com' };
    Object.keys(SAMPLE_DECISIONS).forEach(function (id) {
      var d = SAMPLE_DECISIONS[id];
      state.decisions[id] = { decision: d.decision, note: d.note || '', decidedOn: d.decidedOn ? M.fromIso(d.decidedOn) : M.fromIso('2026-11-28'), noticeDays: undefined };
    });
    // The review the account holder saved on 20 October, before this month's export.
    analyse();
    var reviewed = M.fromIso('2026-10-20');
    var earlier = M.findRegulars(A.merged.transactions.filter(function (t) { return t.day < reviewed; }), { asOf: reviewed });
    var known = {};
    earlier.series.forEach(function (s) { known[s.id] = { typical: s.typical, status: s.status, name: s.name }; });
    state.saved = { reviewedOn: reviewed, known: known, decisions: { 'GADGETGUARD PHONE COVER~monthly~1': state.decisions['GADGETGUARD PHONE COVER~monthly~1'], 'HARBOUR LETTINGS RENT~monthly~1': { decision: 'keep' } } };
    replan();
  }

  /* ---------------------------------------------------------------- */
  /* Navigation                                                        */
  /* ---------------------------------------------------------------- */

  var VIEWS = ['statements', 'regulars', 'calendar', 'plan', 'how'];
  function show(view, focus) {
    if (VIEWS.indexOf(view) < 0) view = 'regulars';
    state.view = view;
    VIEWS.forEach(function (v) {
      var tab = $('#tab-' + v), panel = $('#view-' + v);
      var on = v === view;
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
      panel.hidden = !on;
    });
    savePrefs();
    if (focus) {
      var nav = $('.pipe-nav');
      var top = $('#view-' + view).getBoundingClientRect().top + window.scrollY - (nav ? nav.offsetHeight : 0) - 12;
      if (window.scrollY > top) window.scrollTo(0, top);
      $('#view-' + view).focus({ preventScroll: true });
    }
  }

  /* ---------------------------------------------------------------- */
  /* Events                                                            */
  /* ---------------------------------------------------------------- */

  function setDecision(id, value) {
    var d = state.decisions[id] || {};
    state.decisions[id] = { decision: value, note: d.note || '', decidedOn: Math.max(TODAY, A.result.asOf - 1), noticeDays: d.noticeDays };
    replan();
    var card = doc.querySelector('.reg[data-id="' + cssEscape(id) + '"]');
    if (card) card.setAttribute('data-decision', value);
    renderMeters(); renderGauge(); renderCalendar(); renderPlan();
    autosave();
    var s = M.findSeries(A.result, id);
    if (s) toast(s.name + ': ' + M.DECISION_LABELS[value].toLowerCase() + (value === 'cancel' ? '. Added to your plan.' : '.'));
    // Keep the summary plate in step without redrawing the list (so focus stays put).
    var list = $('#regulars-body .manifold');
    if (list) { var keep = list; renderRegulars(); var fresh = $('#regulars-body .manifold'); if (fresh && keep) fresh.parentNode.replaceChild(keep, fresh); }
  }
  function cssEscape(s) { return window.CSS && CSS.escape ? CSS.escape(s) : String(s).replace(/["\\]/g, '\\$&'); }

  function onClick(e) {
    var t = e.target.closest('button, [data-go]');
    if (!t) return;
    if (t.hasAttribute('data-go')) {
      if (t.getAttribute('data-filter-go')) state.filter = t.getAttribute('data-filter-go');
      show(t.getAttribute('data-go'), true);
      if (t.getAttribute('data-filter-go')) renderRegulars();
      return;
    }
    if (t.hasAttribute('data-filter')) { state.filter = t.getAttribute('data-filter'); renderRegulars(); var b = doc.querySelector('.chip[data-filter="' + state.filter + '"]'); if (b) b.focus(); return; }
    if (t.hasAttribute('data-months')) { state.calMonths = +t.getAttribute('data-months'); renderCalendar(); var mb = doc.querySelector('[data-months="' + state.calMonths + '"]'); if (mb) mb.focus(); return; }
    var action = t.getAttribute('data-action');
    var fileId = t.getAttribute('data-file');
    var f = fileId ? state.files.filter(function (x) { return x.uid === fileId; })[0] : null;
    switch (action) {
      case 'choose-files': $('#file-input').click(); break;
      case 'open-review': $('#review-input').click(); break;
      case 'download-template': download('still-paying-template.csv', M.templateCsv(), 'text/csv;charset=utf-8'); break;
      case 'read-paste': {
        var text = $('#paste-text').value;
        if (!text.trim()) { toast('Paste a table first.'); return; }
        if (state.isSample) { clearData(); state.isSample = false; }
        var acc = $('#paste-account').value.trim() || 'Pasted account';
        state.files.push({ uid: uid(), name: 'Pasted table ' + (state.files.length + 1), text: text, account: acc, accountGiven: true, options: {} });
        $('#paste-text').value = '';
        refresh();
        var st = A.statements[A.statements.length - 1];
        toast(st.ok ? 'Read ' + plural(st.transactions.length, 'payment') + ' from the pasted table.' : 'Could not read the pasted table. See the notes below.');
        break;
      }
      case 'remove-file': state.files = state.files.filter(function (x) { return x.uid !== fileId; }); if (state.mapperFor === fileId) state.mapperFor = null; refresh(); toast('Removed ' + (f ? f.name : 'the file') + '.'); break;
      case 'drop-saved': state.extra = []; state.saved = null; refresh(); break;
      case 'map': state.mapperFor = state.mapperFor === fileId ? null : fileId; renderStatements(); var mp = $('#map-' + fileId + '-date'); if (mp) mp.focus(); break;
      case 'apply-map': applyMapping(f); break;
      case 'reset-map': if (f) { f.options = {}; state.mapperFor = null; refresh(); toast('Back to the automatic guess for ' + f.name + '.'); } break;
      case 'load-sample': loadSample(); rerender(); show('regulars', true); toast('Loaded the sample statements.'); break;
      case 'clear-all': clearData(); state.isSample = false; refresh(); toast('Cleared. Nothing was stored anywhere.'); break;
      case 'confirm': state.manual.push({ id: t.getAttribute('data-id'), cadence: t.getAttribute('data-cadence') }); refresh(); toast('Added as a ' + t.getAttribute('data-cadence') + ' payment.'); break;
      case 'unmerge': delete state.aliases[t.getAttribute('data-key')]; refresh(); break;
      case 'ics': { var ics = M.buildIcs(A.result, state.decisions, { days: state.view === 'calendar' ? horizonDays() : 92 }); download('regular-payments.ics', ics.text, 'text/calendar;charset=utf-8'); break; }
      case 'register': download('regular-payments.csv', M.registerCsv(A.result, state.decisions), 'text/csv;charset=utf-8'); break;
      case 'budget': download('budget-12-months.csv', M.budgetCsv(A.result, state.decisions, 12), 'text/csv;charset=utf-8'); break;
      case 'save-review': download('still-paying-review-' + M.iso(A.result.asOf) + '.json', reviewText(), 'application/json'); break;
      case 'print': show('plan'); window.print(); break;
      case 'copy-summary': copyText(summaryText(), 'Summary'); break;
      case 'copy-draft': { var ta = doc.getElementById(t.getAttribute('data-target')); if (ta) copyText(ta.value, 'Message'); break; }
      case 'reopen-last': { var last = store.get(KEY_LAST); if (last) { openReview(last, '', false); } break; }
      case 'forget-local': store.remove(KEY_LAST); store.remove(KEY_PREFS); renderBanner(); toast('Forgot the copy kept in this browser.'); break;
      default: break;
    }
  }

  function applyMapping(f) {
    if (!f) return;
    var mapping = {};
    MAP_ROLES.forEach(function (role) {
      var v = $('#map-' + f.uid + '-' + role).value;
      if (v !== '') mapping[role] = +v;
    });
    if (mapping.date === undefined || (mapping.amount === undefined && mapping.out === undefined && mapping['in'] === undefined)) { toast('Choose at least a date column and an amount (or money out) column.'); return; }
    if (mapping.payee === undefined && mapping.memo === undefined) { toast('Choose a description or payee column too.'); return; }
    var hr = parseInt($('#map-' + f.uid + '-header').value, 10);
    f.options = { mapping: mapping, headerRow: isFinite(hr) && hr > 0 ? hr - 1 : -1, dateOrder: $('#map-' + f.uid + '-order').value, signConvention: $('#map-' + f.uid + '-sign').value };
    refresh();
    var i = state.files.indexOf(f);
    var st = A.statements[i];
    toast(st && st.ok ? 'Read ' + plural(st.transactions.length, 'payment') + ' with your column choices.' : 'Still could not read it. Check the columns.');
  }

  function onChange(e) {
    var t = e.target;
    if (t.matches('[data-decide]')) { setDecision(t.getAttribute('data-decide'), t.value); return; }
    if (t.id === 'file-input') { readFiles(t.files); t.value = ''; return; }
    if (t.id === 'review-input') { var f = t.files && t.files[0]; if (f) { var rd = new FileReader(); rd.onload = function () { openReview(String(rd.result), f.name, false); }; rd.readAsText(f); } t.value = ''; return; }
    if (t.id === 'reg-sort') { state.sort = t.value; renderRegulars(); $('#reg-sort').focus(); return; }
    if (t.id === 'hide-cancel') { state.hideCancelled = t.checked; renderCalendar(); $('#hide-cancel').focus(); return; }
    if (t.id === 'show-income') { state.showIncome = t.checked; renderCalendar(); $('#show-income').focus(); return; }
    if (t.matches('[data-tick]')) { var id = t.getAttribute('data-tick'); var arr = state.ticked[id] || []; arr[+t.getAttribute('data-step')] = t.checked; state.ticked[id] = arr; return; }
    if (t.matches('[data-field=account]')) {
      var file = state.files.filter(function (x) { return x.uid === t.getAttribute('data-file'); })[0];
      if (file) { file.account = t.value.trim() || 'Account'; file.accountGiven = true; refresh(); toast('Account renamed. Files with the same account name are combined.'); }
      return;
    }
    if (t.matches('[data-detail]')) { state.details[t.getAttribute('data-detail')] = t.value; replan(); renderPlan(); savePrefs(); autosave(); return; }
    if (t.matches('[data-edit]')) {
      var sid = t.getAttribute('data-series'), what = t.getAttribute('data-edit');
      var d = state.decisions[sid] || { decision: null, note: '' };
      if (what === 'name') { if (t.value.trim()) state.names[sid] = t.value.trim(); else delete state.names[sid]; refresh(); }
      else if (what === 'note') { d.note = t.value; state.decisions[sid] = d; replan(); renderPlan(); autosave(); }
      else if (what === 'notice') { var n = parseInt(t.value, 10); d.noticeDays = isFinite(n) && n >= 0 ? Math.min(90, n) : undefined; state.decisions[sid] = d; replan(); renderPlan(); renderCalendar(); autosave(); }
      else if (what === 'method' || what === 'category') { var o = state.overrides[sid] || {}; o[what] = t.value; state.overrides[sid] = o; refresh(); }
      else if (what === 'merge' && t.value) { state.aliases[t.getAttribute('data-key')] = t.value; refresh(); toast('Merged. Undo it from the summary at the top of the list.'); }
    }
  }
  function onInput(e) {
    var t = e.target;
    if (t.id === 'reg-search') {
      state.search = t.value;
      var list = sortSeries(filterSeries(A.result.series));
      var m = $('#regulars-body .manifold');
      if (m) m.innerHTML = list.length ? list.map(regCard).join('') : '<div class="plate none-match">Nothing matches "' + esc(state.search) + '".</div>';
    }
  }
  function onToggle(e) {
    var d = e.target;
    if (!d.matches || !d.matches('details[data-open-key]')) return;
    var k = d.getAttribute('data-open-key');
    state.open[k] = d.open;
    if (d.open && d.classList.contains('reg-more') && !d.querySelector('.reg-detail')) {
      var s = M.findSeries(A.result, k);
      if (s) d.insertAdjacentHTML('beforeend', detailHtml(s, hid(s.id), state.decisions[s.id] || {}));
    }
  }
  function onKeyTabs(e) {
    var t = e.target.closest('[role=tab]');
    if (!t) return;
    var tabs = $$('.pipe-run [role=tab]');
    var i = tabs.indexOf(t);
    var j = null;
    if (e.key === 'ArrowRight') j = (i + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') j = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') j = 0;
    else if (e.key === 'End') j = tabs.length - 1;
    if (j === null) return;
    e.preventDefault();
    tabs[j].focus();
    show(tabs[j].getAttribute('data-view'));
  }

  function initDrop() {
    var dz = $('#dropzone');
    ['dragenter', 'dragover'].forEach(function (ev) { dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.add('over'); }); });
    ['dragleave', 'drop'].forEach(function (ev) { dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.remove('over'); }); });
    dz.addEventListener('drop', function (e) { readFiles(e.dataTransfer && e.dataTransfer.files); });
    dz.addEventListener('click', function (e) { if (!e.target.closest('button')) $('#file-input').click(); });
    dz.addEventListener('keydown', function (e) { if ((e.key === 'Enter' || e.key === ' ') && e.target === dz) { e.preventDefault(); $('#file-input').click(); } });
    // Dropping a file anywhere else on the page should not navigate away from the app.
    window.addEventListener('dragover', function (e) { e.preventDefault(); });
    window.addEventListener('drop', function (e) { if (!e.target.closest('#dropzone')) { e.preventDefault(); if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) readFiles(e.dataTransfer.files); } });
  }

  function init() {
    doc.addEventListener('click', onClick);
    doc.addEventListener('change', onChange);
    doc.addEventListener('input', onInput);
    doc.addEventListener('toggle', onToggle, true);
    $('.pipe-run').addEventListener('keydown', onKeyTabs);
    $$('.pipe-run [role=tab]').forEach(function (b) { b.addEventListener('click', function () { show(b.getAttribute('data-view')); }); });
    initDrop();
    var prefs = null;
    try { prefs = JSON.parse(store.get(KEY_PREFS) || 'null'); } catch (e) { prefs = null; }
    renderHow();
    loadSample();
    rerender();
    show(prefs && prefs.view && prefs.view !== 'how' ? prefs.view : 'regulars');
  }

  window.StillPayingApp = { state: state, analysis: function () { return A; }, plan: function () { return P; }, show: show, refresh: refresh, loadSample: loadSample, openReview: openReview };
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', init); else init();
})();
