/*
 * Round trips: the page. Everything that touches the document lives here;
 * every calculation comes from the model (window.RoundTrips).
 */
(function () {
  'use strict';

  var M = window.RoundTrips;
  var STORE_KEY = 'round-trips-journal-v1';
  var VIEWS = ['fills', 'trades', 'review', 'days', 'rules', 'how'];

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function esc(v) {
    return String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function cls(v) { return v > 0 ? 'gain' : v < 0 ? 'loss' : ''; }
  function todayIso() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  /* ---------- state ---------- */

  var S = {
    sample: true,
    base: M.emptyState(),
    files: [],
    state: null,
    reports: [],
    result: null,
    view: 'review',
    dirty: {},
    review: { week: null, account: '', all: false },
    trades: { account: '', week: '', setup: '', outcome: '', needs: false, fresh: false, q: '', selected: null, limit: 80 },
    opened: null,
    chat: 'full',
    fills: { account: '', symbol: '', limit: 60 },
    breakdown: 'setup',
    days: { account: '', day: null },
    resume: null
  };

  function storeGet(key) { try { return window.localStorage.getItem(key); } catch (e) { return null; } }
  function storeSet(key, value) { try { window.localStorage.setItem(key, value); return true; } catch (e) { return false; } }
  function storeDel(key) { try { window.localStorage.removeItem(key); } catch (e) { /* storage blocked */ } }

  var saveTimer = null;
  function autosave() {
    if (S.sample) return;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      var text = M.projectFile(S.state, todayIso());
      // Browser storage holds about 5 MB; a bigger journal lives only in the file you save.
      if (text.length > 4500000 || !storeSet(STORE_KEY, JSON.stringify({ when: new Date().toISOString(), journal: text }))) storeDel(STORE_KEY);
    }, 700);
  }

  // Re-read every export added this session on top of the journal they were added to.
  function reimport() {
    var imp = M.importFiles(S.base, S.files);
    S.state = imp.state;
    S.reports = imp.reports;
    reanalyse();
  }
  function reanalyse() {
    S.state.settings = S.base.settings;
    S.state.journal = S.base.journal;
    S.result = M.analyse(S.state);
    var weeks = closedWeeks();
    if (S.review.week === null || weeks.indexOf(S.review.week) < 0) S.review.week = weeks.length ? weeks[weeks.length - 1] : (S.result.weeks.length ? S.result.weeks[S.result.weeks.length - 1] : null);
    if (S.review.account && S.result.accounts.indexOf(S.review.account) < 0) S.review.account = '';
    VIEWS.forEach(function (v) { S.dirty[v] = true; });
    renderAll();
    autosave();
  }
  function closedWeeks() {
    var seen = {}, out = [];
    S.result.closed.forEach(function (t) {
      if (S.review.account && t.account !== S.review.account) return;
      var w = M.weekStart(t.closeDay);
      if (!seen[w]) { seen[w] = true; out.push(w); }
    });
    return out.sort(function (a, b) { return a - b; });
  }

  function loadSample() {
    var data = JSON.parse(document.getElementById('samples').textContent);
    var pr = M.readProject(data.journal);
    S.base = pr.state;
    S.files = data.files.map(function (f) { return { name: f.name, text: f.text }; });
    S.sample = true;
    S.review = { week: null, account: '', all: false };
    S.trades.selected = null;
    reimport();
  }

  function startFresh() {
    S.opened = null;
    S.base = M.emptyState();
    S.files = [];
    S.sample = false;
    S.review = { week: null, account: '', all: false };
    S.trades.selected = null;
  }

  function addFiles(list) {
    if (!list.length) return;
    if (S.sample) { startFresh(); toast('Cleared the sample: reading your files'); }
    list.forEach(function (f) { S.files.push(f); });
    reimport();
    var last = S.reports.slice(-list.length);
    var added = 0, dupes = 0, bad = 0;
    last.forEach(function (r) { added += r.added; dupes += r.duplicates; if (!r.ok) bad++; });
    toast(bad ? bad + (bad === 1 ? ' file' : ' files') + ' could not be read: see the import log' : M.plural(added, 'new fill') + ' added' + (dupes ? ', ' + dupes + ' already in the journal' : ''));
    show('fills');
  }

  function readFiles(fileList) {
    var files = Array.prototype.slice.call(fileList || []);
    if (!files.length) return;
    var out = new Array(files.length), left = files.length;
    files.forEach(function (file, i) {
      var reader = new FileReader();
      reader.onload = function () { out[i] = { name: file.name, text: String(reader.result) }; if (--left === 0) addFiles(out); };
      reader.onerror = function () { out[i] = { name: file.name, text: '' }; if (--left === 0) addFiles(out); };
      reader.readAsText(file);
    });
  }

  function openJournal(text, label) {
    var pr = M.readProject(text);
    if (!pr.ok) { toast(pr.error); return false; }
    S.base = pr.state;
    S.files = [];
    S.sample = false;
    S.review = { week: null, account: '', all: false };
    S.trades.selected = null;
    S.opened = null;
    reimport();
    S.opened = snapshot(label || 'the journal');
    renderNotice();
    toast('Opened ' + (label || 'the journal') + ': ' + S.state.fills.length + ' fills, ' + S.base.journal.length + ' journal entries' + (pr.error ? '. ' + pr.error : ''));
    return true;
  }

  // What the journal held when it was opened, to show what next week's export added.
  function breachKey(b) { return [b.rule, b.trade, b.account, b.day, b.sec === null ? '' : b.sec].join('|'); }
  function snapshot(label) {
    var closed = {}, breaches = {};
    S.result.closed.forEach(function (t) { closed[t.id] = true; });
    S.result.breaches.forEach(function (b) { breaches[breachKey(b)] = true; });
    return { label: label, fills: S.state.fills.length, closed: closed, breaches: breaches };
  }
  function sinceOpened() {
    if (!S.opened || !S.result) return null;
    var fresh = S.result.closed.filter(function (t) { return !S.opened.closed[t.id]; });
    var net = 0;
    fresh.forEach(function (t) { if (t.netBase !== null) net += t.netBase; });
    return {
      fills: S.state.fills.length - S.opened.fills, trades: fresh, net: net,
      breaches: S.result.breaches.filter(function (b) { return !S.opened.breaches[breachKey(b)]; }).length,
      needs: fresh.filter(function (t) { return !t.setup || t.plannedRisk === null; }).length
    };
  }

  /* ---------- small output helpers ---------- */

  var toastTimer = null;
  function toast(msg) {
    var el = $('#toast');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove('show'); }, 3200);
  }

  function download(name, text, type) {
    var blob = new Blob([text], { type: type || 'text/csv;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1000);
    toast('Downloaded ' + name);
  }

  function copyText(text, fallbackEl) {
    function fallback() {
      if (fallbackEl) { fallbackEl.focus(); fallbackEl.select(); }
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      toast(ok ? 'Copied the review' : 'Selected the text: press Ctrl+C (or Cmd+C) to copy it');
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { toast('Copied the review: paste it into the team chat'); }, fallback);
    } else fallback();
  }

  var base = function () { return S.result.settings.base; };
  function m(c, opts) { return M.money(c, base(), opts); }
  function mc(c, cur, opts) { return M.money(c, cur, opts); }
  function tradeById(id) {
    for (var i = 0; i < S.result.trades.length; i++) if (S.result.trades[i].id === id) return S.result.trades[i];
    return null;
  }
  function sideWord(t) { return t.dir > 0 ? 'Long' : 'Short'; }
  // Average prices to four decimals at most (two in the hero), so a VWAP does not run to six places.
  function avgPrice(micro, dp) { var f = dp === 2 ? 10000 : 100; return M.fmtPrice(M.rnd(micro / f) * f, true); }

  function periodRange() {
    if (S.review.all || S.review.week === null) return { from: null, to: null };
    return { from: S.review.week, to: S.review.week + 6 };
  }
  function periodLabel() {
    if (S.review.all || S.review.week === null) return 'all weeks';
    return M.weekLabel(S.review.week);
  }
  function periodTrades() {
    var r = periodRange();
    return M.filterTrades(S.result.closed, { account: S.review.account, from: r.from, to: r.to });
  }

  /* ---------- hero, headline and notice ---------- */

  function setText(id, text) { var el = document.getElementById(id); if (el) el.textContent = text; }

  function renderHero() {
    var res = S.result;
    var list = periodTrades();
    var st = M.stats(list, {});
    var best = st.best ? tradeById(st.best.id) : (res.closed.length ? res.closed[res.closed.length - 1] : null);
    setText('ticket-no', 'TICKET ' + String(res.closed.length).padStart(4, '0'));
    setText('hero-ticket-no', 'No. ' + String(res.trades.length).padStart(4, '0'));
    if (best) {
      setText('hero-qty', M.fmtQty(best.maxPos));
      setText('hero-symbol', best.symbol + (best.dir > 0 ? ' long' : ' short'));
      setText('hero-price', avgPrice(best.avgEntry, 2) + ' \u2192 ' + (best.qtyOut ? avgPrice(best.avgExit, 2) : 'open'));
      setText('hero-net', best.netBase === null ? mc(best.net, best.currency, { sign: true, whole: true }) : m(best.netBase, { sign: true, whole: true }));
      setText('hero-setup', best.setup || 'no setup yet');
      var net = document.getElementById('hero-net');
      if (net) net.setAttribute('class', best.net < 0 ? 'loss-ink' : '');
      var tick = document.getElementById('hero-tick');
      if (tick) tick.setAttribute('d', best.dir > 0 ? 'M343 140 L348 145 L357 132' : 'M405 140 L410 145 L419 132');
      if (tick) tick.setAttribute('stroke', best.dir > 0 ? '#26307a' : '#b3301d');
    } else {
      ['hero-qty', 'hero-symbol', 'hero-price', 'hero-net', 'hero-setup'].forEach(function (id) { setText(id, ''); });
      var none = document.getElementById('hero-tick');
      if (none) none.setAttribute('d', '');
    }
    setText('hero-week', S.review.all || S.review.week === null ? 'all weeks' : 'w/c ' + M.fmtShort(S.review.week));
    setText('hero-line1', st.n ? 'net ' + m(st.net, { sign: true, whole: true }) : 'no trades closed');
    setText('hero-line2', st.n ? 'won ' + st.wins + ' of ' + st.n : '');
    setText('hero-line3', st.profitFactor !== null ? 'PF ' + M.fmtNum(st.profitFactor, 2) : (st.n ? 'no losses' : ''));
    var r = periodRange();
    var nb = res.breaches.filter(function (b) { return (!S.review.account || b.account === S.review.account) && (r.from === null || (b.day >= r.from && b.day <= r.to)); }).length;
    setText('hero-line4', 'rules broken: ' + nb);
    var setups = M.breakdown(list, 'setup').filter(function (x) { return x.key !== '(no setup)'; });
    setText('hero-line5', setups.length ? 'best: ' + shortSetup(setups[0].label) : '');
    var worst = setups.length > 1 ? setups[setups.length - 1] : null;
    setText('hero-line6', worst && worst.net < 0 ? 'cut: ' + shortSetup(worst.label) : '');
    // The tape: this period's trades, or the latest ones.
    var tapeTrades = (list.length >= 6 ? list : res.closed.slice(-24)).slice(-24);
    var tapeText = tapeTrades.map(function (t) {
      var v = t.netBase === null ? t.net : t.netBase;
      return t.symbol + ' ' + M.money(v, t.netBase === null ? t.currency : base(), { sign: true, whole: true }) + (v >= 0 ? ' \u25b2' : ' \u25bc');
    }).join('   ');
    setText('hero-tape', tapeText || 'Waiting for your fills');
    var run = document.getElementById('tape-run');
    var items = tapeTrades.map(function (t) {
      var v = t.netBase === null ? t.net : t.netBase;
      return '<span class="' + (v >= 0 ? 'up' : 'down') + '">' + esc(t.symbol) + ' ' + esc(sideWord(t).toLowerCase()) + ' ' + esc(M.money(v, t.netBase === null ? t.currency : base(), { sign: true })) + '</span>';
    }).join('');
    run.innerHTML = items ? items + items : '<span>Drop your fills export on the in-tray to start the tape</span>';
    run.classList.toggle('still', !items);
  }
  function shortSetup(label) {
    var words = label.split(' ');
    if (label.length <= 12) return label;
    return words.map(function (w) { return w.charAt(0).toUpperCase(); }).join('');
  }

  function renderHeadline() {
    var list = periodTrades();
    var r = periodRange();
    var st = M.stats(list, {});
    var label = S.review.all || S.review.week === null ? 'All weeks' : 'Week of ' + M.fmtShort(S.review.week);
    var who = S.review.account || 'all accounts';
    var breaches = S.result.breaches.filter(function (b) { return (!S.review.account || b.account === S.review.account) && (r.from === null || (b.day >= r.from && b.day <= r.to)); });
    var broke = list.filter(function (t) { return t.breaches.length; });
    var brokeNet = 0;
    broke.forEach(function (t) { if (t.netBase !== null) brokeNet += t.netBase; });
    var html = '';
    html += '<article class="hticket"><h2>Net after fees</h2><div class="big ' + cls(st.net) + '">' + (st.n ? esc(m(st.net, { sign: true })) : '&ndash;') + '</div>' +
      '<p>' + esc(label) + ', ' + esc(who) + '. ' + (st.n ? 'Before fees ' + esc(m(st.gross, { sign: true })) + '; fees ' + esc(m(st.fees)) + '.' : 'No trades closed.') + '</p></article>';
    html += '<article class="hticket"><h2>Win rate</h2><div class="big">' + (st.n ? esc(M.fmtPct(st.winRate)) : '&ndash;') + '</div>' +
      '<p>' + (st.n ? st.wins + ' won, ' + st.losses + ' lost' + (st.flat ? ', ' + st.flat + ' flat' : '') + '. Profit factor ' + (st.profitFactor === null ? 'n/a' : esc(M.fmtNum(st.profitFactor, 2))) + '.' : 'Closed trades only.') + '</p></article>';
    html += '<article class="hticket"><h2>Expectancy</h2><div class="big ' + cls(st.expectancy || 0) + '">' + (st.n ? esc(m(M.rnd(st.expectancy), { sign: true })) : '&ndash;') + '</div>' +
      '<p>' + (st.n ? 'A trade, after fees. ' + (st.rCount ? 'Average ' + esc(M.fmtR(st.avgR)) + ' on ' + st.rCount + ' with planned risk.' : 'Add stops in the journal to see R.') : 'Net divided by closed trades.') + '</p></article>';
    html += '<article class="hticket' + (breaches.length ? ' alert' : '') + '"><h2>Rule breaches</h2><div class="big">' + breaches.length + '</div>' +
      '<p>' + (broke.length ? broke.length + (broke.length === 1 ? ' trade broke a rule and made ' : ' trades broke a rule and made ') + esc(m(brokeNet, { sign: true })) + '.' : st.n ? 'Every closed trade kept to the rules.' : 'No trades yet.') + '</p></article>';
    $('#headline').innerHTML = html;
  }

  function renderNotice() {
    var el = $('#notice');
    var foot = document.getElementById('foot-text');
    if (foot) foot.innerHTML = '<strong>Round trips</strong> reads exports in your browser and keeps them there. ' + (S.sample ? 'The sample is invented: the team, accounts, tickers and the Larkfield 50 index future are all made up. ' : '') + 'Not financial advice: it describes trades you have already made.';
    var since = sinceOpened();
    if (since && since.fills > 0) {
      el.innerHTML = '<p><strong>Since you opened ' + esc(S.opened.label) + ':</strong> ' + M.plural(since.fills, 'new fill') + ', ' + M.plural(since.trades.length, 'trade') + ' closed (' + esc(m(since.net, { sign: true })) + ' after fees), ' +
        M.plural(since.breaches, 'new rule breach', 'new rule breaches') + '. ' + (since.needs ? M.plural(since.needs, 'of them needs', 'of them need') + ' a setup or a stop.' : 'All of them are written up.') + '</p>' +
        '<div class="btn-row"><button type="button" class="btn btn-ink btn-small" data-action="write-new">Write up the new trades</button><button type="button" class="btn btn-line btn-small" data-action="review-latest">Review the latest week</button><button type="button" class="btn btn-line btn-small" data-action="save">Save journal file</button></div>';
      return;
    }
    if (S.resume) {
      el.innerHTML = '<p><strong>Pick up where you left off.</strong> A journal you were working on is saved in this browser (' + esc(S.resume.when.slice(0, 10)) + ').</p>' +
        '<div class="btn-row"><button type="button" class="btn btn-ink btn-small" data-action="resume">Reopen it</button><button type="button" class="btn btn-line btn-small" data-action="forget">Forget it</button></div>';
      return;
    }
    if (S.sample) {
      el.innerHTML = '<p><strong>You are looking at an invented trading-challenge team.</strong> Ten weeks of fills in three exports (a challenge platform, a messy futures export and a UK dealing account), with journal notes already filled in. Every name and ticker is made up.</p>' +
        '<div class="btn-row"><button type="button" class="btn btn-ink btn-small" data-go="fills">Use your own fills</button><button type="button" class="btn btn-line btn-small" data-action="clear">Clear the sample</button></div>';
      return;
    }
    el.innerHTML = '';
  }

  /* ---------- tabs ---------- */

  function show(view, focus) {
    if (VIEWS.indexOf(view) < 0) view = 'review';
    S.view = view;
    VIEWS.forEach(function (v) {
      var tab = document.getElementById('tab-' + v), panel = document.getElementById('view-' + v);
      var on = v === view;
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
      panel.hidden = !on;
    });
    renderView(view);
    if (view === 'review') drawEquity();
    if (view === 'days') drawDayChart();
    if (focus) document.getElementById('tab-' + view).focus();
  }

  function renderView(view, force) {
    if (!S.result) return;
    if (!S.dirty[view] && !force) return;
    var panel = document.getElementById('view-' + view);
    var active = document.activeElement;
    var activeId = active && active.id && panel.contains(active) ? active.id : null;
    var sel = null;
    try { if (activeId && active.selectionStart !== undefined) sel = [active.selectionStart, active.selectionEnd]; } catch (e) { sel = null; }
    ({ fills: renderFills, trades: renderTrades, review: renderReview, days: renderDays, rules: renderRules, how: renderHow })[view](panel);
    S.dirty[view] = false;
    if (activeId) {
      var el = document.getElementById(activeId);
      if (el) { el.focus({ preventScroll: true }); if (sel) { try { el.setSelectionRange(sel[0], sel[1]); } catch (e) { /* not a text field */ } } }
    }
  }

  function renderAll() {
    renderHero();
    renderHeadline();
    renderNotice();
    renderView(S.view);
  }

  /* ---------- view 1: fills ---------- */

  function accountOptions(selected, allLabel) {
    return '<option value="">' + esc(allLabel || 'All accounts') + '</option>' + S.result.accounts.map(function (a) {
      return '<option value="' + esc(a) + '"' + (a === selected ? ' selected' : '') + '>' + esc(a) + '</option>';
    }).join('');
  }

  function renderFills(panel) {
    var res = S.result, st = S.state;
    var html = '';
    html += '<div class="intray" id="intray">' +
      '<span class="intray-label">In-tray: fills exports</span>' +
      '<p>Drop the trade-history or fills export from your broker or challenge platform here: CSV, TSV or text, with a date, symbol, buy or sell (or a signed quantity), quantity and price. Fees, currency, account, order IDs and status columns are used when present. Add next week\'s export to a saved journal and fills already in it are skipped, never counted twice.</p>' +
      '<div class="btn-row"><button type="button" class="btn btn-brass" data-action="pick">Choose exports</button>' +
      '<button type="button" class="btn btn-line" data-action="open">Open journal file</button>' +
      '<button type="button" class="btn btn-line" data-action="save">Save journal file</button>' +
      '<button type="button" class="btn btn-line" data-action="template">Download the template</button></div>' +
      '<div class="row-fields" style="justify-content:center;margin-top:14px">' +
      '<label class="field"><span>Dates written as</span><select id="date-order" class="inline-select">' +
      [['auto', 'Work it out (UK if unclear)'], ['DMY', 'Day first: 07/10 is 7 October'], ['MDY', 'Month first: 07/10 is 10 July']].map(function (o) {
        return '<option value="' + o[0] + '"' + (S.base.settings.dateOrder === o[0] ? ' selected' : '') + '>' + o[1] + '</option>';
      }).join('') + '</select></label></div>' +
      '<details class="paste"><summary>Or paste the export as text</summary>' +
      '<label class="field"><span>Exported text</span><textarea id="paste-text" spellcheck="false" placeholder="Date,Time,Symbol,Side,Quantity,Price,Commission"></textarea></label>' +
      '<div class="row-fields"><label class="field"><span>Account name, if the text has no account column</span><input id="paste-account" type="text" class="inline-input" placeholder="Pasted"></label>' +
      '<button type="button" class="btn btn-ink" data-action="paste">Read the pasted text</button></div></details>' +
      '</div>';

    // Import log.
    var sessionStart = S.base.sources.length;
    html += '<div class="sources">';
    if (!st.sources.length) html += '<p class="empty">No exports yet. Choose a file above, or download the template to see the layout.</p>';
    st.sources.slice().reverse().forEach(function (src) {
      var idx = st.sources.indexOf(src);
      var session = idx >= sessionStart;
      var fileIndex = idx - sessionStart;
      html += '<article class="source' + (src.error ? ' bad' : '') + '">';
      html += '<h3>' + esc(src.name) + '</h3>';
      if (src.error) {
        html += '<p class="meta"><strong>Could not read this file.</strong> ' + esc(src.error) + '</p>';
      } else {
        html += '<p class="meta">' + (src.account ? 'Account <strong>' + esc(src.account) + '</strong>' : '') +
          (src.first !== null && src.first !== undefined ? ' &middot; ' + esc(M.fmtDayMonthYear(src.first)) + ' to ' + esc(M.fmtDayMonthYear(src.last)) : '') +
          (src.saved ? ' &middot; saved in the journal' : '') + '</p>';
        html += '<ul class="counts">' +
          '<li><b>' + src.added + '</b> ' + (src.added === 1 ? 'fill' : 'fills') + ' added</li>' +
          (src.duplicates ? '<li><b>' + src.duplicates + '</b> already in the journal, skipped</li>' : '') +
          (src.feesAdded ? '<li><b>' + src.feesAdded + '</b> ' + (src.feesAdded === 1 ? 'fee row' : 'fee rows') + ' attached</li>' : '') +
          (src.counts ? '<li><b>' + src.counts.skipped + '</b> ' + (src.counts.skipped === 1 ? 'row' : 'rows') + ' set aside</li>' : '') +
          (src.counts && src.counts.blank ? '<li><b>' + src.counts.blank + '</b> blank ' + (src.counts.blank === 1 ? 'line' : 'lines') + '</li>' : '') + '</ul>';
      }
      var cols = src.columns || {};
      var names = { date: 'Date', time: 'Time', symbol: 'Symbol', qty: 'Quantity', price: 'Price', side: 'Side', fees: 'Fees', currency: 'Currency', account: 'Account', mult: 'Multiplier', status: 'Status', orderId: 'Order ID', execId: 'Fill ID', openClose: 'Open or close', asset: 'Asset type', recordType: 'Row type', amount: 'Amount', description: 'Description' };
      var keys = Object.keys(cols);
      if (keys.length) html += '<ul class="chips" aria-label="Columns used">' + keys.map(function (k) { return '<li class="chip">' + esc(names[k] || k) + ': ' + esc(cols[k]) + '</li>'; }).join('') + '</ul>';
      var notes = (src.notes || []).slice();
      if (src.dateNote) notes.unshift(src.dateNote);
      if (notes.length) html += '<ul class="chips">' + notes.map(function (n) { return '<li class="chip warn">' + esc(n) + '</li>'; }).join('') + '</ul>';
      if (session && src.headerCells && src.headerCells.length) html += columnChooser(fileIndex, src);
      if (session && !src.error && !cols.account) {
        html += '<div class="row-fields"><label class="field"><span>This file has no account column. Account name</span><input type="text" class="inline-input" id="acct-' + fileIndex + '" data-file="' + fileIndex + '" data-role="file-account" value="' + esc(src.account) + '"></label></div>';
      }
      if (src.skipped && src.skipped.length) {
        html += '<details class="skipped"><summary>' + src.skipped.length + (src.skipped.length === 1 ? ' row' : ' rows') + ' set aside, and why</summary><ul class="skip-list">' +
          src.skipped.map(function (s) { return '<li><span class="mono">Line ' + s.line + '</span> <span class="reason">' + esc(s.reason) + '</span><code>' + esc(s.text) + '</code></li>'; }).join('') + '</ul></details>';
      }
      if (session) html += '<div class="more-row"><button type="button" class="btn btn-danger btn-small" data-action="remove-file" data-file="' + fileIndex + '">Remove this export</button></div>';
      html += '</article>';
    });
    html += '</div>';

    // Warnings.
    if (res.warnings.length) {
      html += '<div class="sheet plain" style="margin-top:22px"><h2>Check these</h2><ul class="breach-list">' + res.warnings.map(function (w) { return '<li>' + esc(w.text) + '</li>'; }).join('') + '</ul></div>';
    }

    if (!res.fills.length) {
      html += '<section class="sheet" style="margin-top:22px"><span class="eyebrow">Getting started</span><h2>Four steps to your first review</h2><ol class="steps">' +
        '<li><strong>Export your fills.</strong> On your broker or challenge platform, find the trade history, executions or fills page and export it as CSV (or copy the table and paste it above).</li>' +
        '<li><strong>Drop it on the in-tray.</strong> Check the import log: the columns it used, the date order, and any rows it set aside and why.</li>' +
        '<li><strong>Set your accounts and rules.</strong> Under Rules, give each account its starting balance and set your limits; under Fills, the multiplier of any futures contract.</li>' +
        '<li><strong>Write up the week.</strong> Add a setup and a stop to each trade, then copy the weekly review for the team chat and save the journal file for next week.</li></ol>' +
        '<div class="btn-row"><button type="button" class="btn btn-line btn-small" data-action="sample">Show the sample again</button></div></section>';
      panel.innerHTML = html;
      return;
    }
    html += '<div class="grid-2" style="margin-top:22px">';
    // Contract multipliers.
    html += '<section class="sheet"><span class="eyebrow">Contracts</span><h2>Contract multipliers</h2><p class="intro">Futures and options profit is price change times quantity times the multiplier (the money each point is worth). Set it for a contract root (LKF covers LKFZ6 and LKFH7) or a single symbol.</p>';
    var mults = {};
    res.symbols.forEach(function (s) {
      var key = s.root || s.symbol;
      if (!s.looksFuture && !s.multSet && !s.fileMult) return;
      if (!mults[key]) mults[key] = { key: key, symbols: [], mult: s.mult };
      if (mults[key].symbols.indexOf(s.symbol) < 0) mults[key].symbols.push(s.symbol);
    });
    (S.base.settings.multipliers || []).forEach(function (e) { if (!mults[e.symbol]) mults[e.symbol] = { key: e.symbol, symbols: [], mult: M.parseFloatText(e.value) || 1 }; });
    var mkeys = Object.keys(mults).sort(M.cmp);
    if (mkeys.length) {
      html += '<div class="table-wrap"><table class="ledger"><thead><tr><th>Root or symbol</th><th>Seen as</th><th class="num">Multiplier</th></tr></thead><tbody>' +
        mkeys.map(function (k, i) {
          var e = (S.base.settings.multipliers || []).filter(function (x) { return x.symbol === k; })[0];
          return '<tr><td class="mono">' + esc(k) + '</td><td>' + esc(mults[k].symbols.join(', ')) + '</td><td class="num"><label class="sr" for="mult-' + i + '">Multiplier for ' + esc(k) + '</label><input type="text" inputmode="decimal" class="inline-input" style="width:6em;text-align:right" id="mult-' + i + '" data-role="mult" data-key="' + esc(k) + '" value="' + esc(e ? e.value : (mults[k].mult === 1 ? '' : mults[k].mult)) + '" placeholder="1"></td></tr>';
        }).join('') + '</tbody></table></div>';
    } else {
      html += '<p class="muted">No futures-style symbols in these fills, so every point counts once.</p>';
    }
    html += '<div class="row-fields" style="margin-top:10px"><label class="field"><span>Add a root or symbol</span><input type="text" id="mult-new-key" class="inline-input" placeholder="e.g. LKF"></label><label class="field"><span>Multiplier</span><input type="text" inputmode="decimal" id="mult-new-value" class="inline-input" placeholder="20"></label><button type="button" class="btn btn-line btn-small" data-action="mult-add">Add</button></div>';
    html += '</section>';

    // Open positions and unmatched closes.
    html += '<section class="sheet"><span class="eyebrow">Still open</span><h2>Open positions</h2><p class="intro">Positions not yet back to flat at the end of the fills. Their profit counts once they close.</p>';
    if (res.open.length) {
      html += '<div class="table-wrap"><table class="ledger"><thead><tr><th>Symbol</th><th class="hide-sm">Account</th><th>Side</th><th class="num">Open</th><th class="num">Avg cost</th><th>Since</th></tr></thead><tbody>' +
        res.open.map(function (t) {
          var q = 0, v = 0;
          t.openLots.forEach(function (l) { q += l.q; v += l.price * l.q; });
          return '<tr><td><button type="button" class="linkish" data-trade="' + esc(t.id) + '">' + esc(t.symbol) + '</button></td><td class="hide-sm">' + esc(t.account) + '</td><td><span class="side-tag side-' + (t.dir > 0 ? 'long' : 'short') + '">' + sideWord(t).toUpperCase() + '</span></td><td class="num">' + esc(M.fmtQty(q)) + '</td><td class="num">' + esc(avgPrice(q ? v / q : 0)) + '</td><td>' + esc(M.fmtShort(t.openDay)) + '</td></tr>';
        }).join('') + '</tbody></table></div>';
    } else html += '<p class="muted">Every position is back to flat.</p>';
    if (res.unmatched.length) {
      html += '<h3>Closes with no opening fill</h3><p class="hint">These sell (or cover) more than the exports show was bought (or shorted), usually because the position was opened before the first export. They are not counted as trades until you add the opening: the date and price it was bought (or shorted) at. Mark an account as long only under Rules if a sale from nothing should never open a short.</p>' +
        '<ul class="carry-list">' + res.unmatched.map(function (u, i) {
          return '<li><p><span class="side-tag side-' + u.side + '">' + (u.side === 'B' ? 'BUY' : 'SELL') + '</span> <strong>' + esc(M.fmtQty(u.q) + ' ' + u.symbol) + '</strong> at ' + esc(M.fmtPrice(u.price, true)) + ' on ' + esc(M.fmtDate(u.day)) + ' <span class="muted">(' + esc(u.account) + ', ' + esc(u.file) + ' line ' + u.line + ')</span></p>' +
            '<div class="row-fields"><label class="field"><span>' + (u.side === 'S' ? 'Bought on' : 'Shorted on') + '</span><input type="date" class="inline-input" id="carry-date-' + i + '" max="' + esc(M.toIso(u.day)) + '"></label>' +
            '<label class="field"><span>At a price of</span><input type="text" inputmode="decimal" class="inline-input" id="carry-price-' + i + '" placeholder="' + esc(M.fmtPrice(u.price)) + '" style="width:8em"></label>' +
            '<button type="button" class="btn btn-line btn-small" data-action="carry-add" data-index="' + i + '">Add the opening</button></div></li>';
        }).join('') + '</ul>';
    }
    if ((S.base.carry || []).length) {
      html += '<h3>Openings you added</h3><ul class="carry-list">' + S.base.carry.map(function (c, i) {
        return '<li class="row-fields" style="justify-content:space-between"><span>' + esc((c.side === 'B' ? 'Bought ' : 'Shorted ') + M.fmtQty(c.q) + ' ' + c.symbol + ' at ' + M.fmtPrice(c.price, true) + ' on ' + M.fmtDate(c.day) + ' (' + c.account + ')') + '</span>' +
          '<button type="button" class="btn btn-danger btn-small" data-action="carry-remove" data-index="' + i + '">Remove</button></li>';
      }).join('') + '</ul>';
    }
    if (res.unattached.length) {
      var feeTotal = 0;
      res.unattached.forEach(function (e) { feeTotal += e.amount; });
      html += '<h3>Fees not tied to a trade</h3><p class="hint">' + res.unattached.length + ' fee rows with no matching fill, ' + esc(M.money(feeTotal, '')) + ' in all. They count against the day for the daily loss rule.</p>';
    }
    html += '</section></div>';

    // The blotter.
    var f = S.fills;
    var symbols = {};
    res.fills.forEach(function (x) { if (!f.account || x.account === f.account) symbols[x.symbol] = true; });
    var rows = res.fills.filter(function (x) { return (!f.account || x.account === f.account) && (!f.symbol || x.symbol === f.symbol); });
    html += '<section class="sheet"><span class="eyebrow">Blotter</span><h2>Every fill, and the trade it belongs to</h2>' +
      '<div class="filters"><label class="field"><span>Account</span><select id="fills-account">' + accountOptions(f.account) + '</select></label>' +
      '<label class="field"><span>Symbol</span><select id="fills-symbol"><option value="">All symbols</option>' + Object.keys(symbols).sort(M.cmp).map(function (s) { return '<option' + (s === f.symbol ? ' selected' : '') + '>' + esc(s) + '</option>'; }).join('') + '</select></label>' +
      '<button type="button" class="btn btn-line btn-small" data-action="fills-csv">Download fills CSV</button></div>';
    if (rows.length) {
      var shown = rows.slice(-f.limit).reverse();
      html += '<div class="table-wrap"><table class="ledger"><thead><tr><th>When</th><th>Symbol</th><th>Side</th><th class="num">Qty</th><th class="num">Price</th><th class="num hide-sm">Fees</th><th class="hide-sm">Trade</th><th class="hide-sm">Account</th></tr></thead><tbody>' +
        shown.map(function (x) {
          var legs = res.legsByFill[x.key] || [];
          return '<tr><td class="mono nowrap" style="font-size:.74rem" title="' + esc(M.toIso(x.day)) + '">' + esc(M.fmtShort(x.day) + ' ' + String(M.civil(x.day)[0]).slice(2)) + '<br>' + esc(M.fmtTimeLong(x.sec)) + '</td><td><strong>' + esc(x.symbol) + '</strong><span class="show-sm">' + tradeLinks(legs) + '</span></td>' +
            '<td><span class="side-tag side-' + x.side + '">' + (x.side === 'B' ? 'BUY' : 'SELL') + '</span></td><td class="num">' + esc(M.fmtQty(x.q)) + '</td><td class="num">' + esc(M.fmtPrice(x.price, true)) + '</td>' +
            '<td class="num hide-sm">' + esc(M.money(res.feeOf[x.key], '')) + '</td><td class="hide-sm">' + tradeLinks(legs) + '</td><td class="hide-sm" style="font-size:.8rem">' + esc(x.account) + '</td></tr>';
        }).join('') + '</tbody></table></div>';
      html += '<div class="more-row"><span class="muted">Showing the latest ' + shown.length + ' of ' + rows.length + ' fills.</span>' + (rows.length > f.limit ? '<button type="button" class="btn btn-line btn-small" data-action="fills-more">Show 200 more</button>' : '') + '</div>';
    } else html += '<p class="empty">No fills to show.</p>';
    html += '</section>';
    html += '<div class="btn-row"><button type="button" class="btn btn-danger" data-action="clear">Clear everything and start again</button></div>';
    panel.innerHTML = html;
  }

  var FIELD_NAMES = { date: 'Date (and time)', time: 'Time', symbol: 'Symbol', side: 'Buy or sell', qty: 'Quantity', price: 'Price', fees: 'Fees', account: 'Account', currency: 'Currency', orderId: 'Order ID' };

  // Pick the column for each field by hand, for layouts it does not recognise or reads wrongly.
  function columnChooser(fileIndex, src) {
    var chosen = S.files[fileIndex].columns || {};
    var cells = src.headerCells.filter(function (c, i, a) { return c !== '' && a.indexOf(c) === i; });
    var html = '<details class="paste"' + (src.error || Object.keys(chosen).length ? ' open' : '') + '><summary>' + (src.error ? 'Choose the columns yourself' : 'Change the columns used') + '</summary>' +
      '<p class="hint">Point each field at a column from the file. Leave a field on "work it out" to let Round trips choose.</p><div class="row-fields chooser">';
    M.COLUMN_FIELDS.forEach(function (f) {
      var id = 'col-' + fileIndex + '-' + f;
      var value = Object.prototype.hasOwnProperty.call(chosen, f) ? chosen[f] : '__auto';
      html += '<label class="field"><span>' + esc(FIELD_NAMES[f]) + '</span><select class="inline-select" id="' + id + '" data-role="file-column" data-file="' + fileIndex + '" data-field="' + f + '">' +
        '<option value="__auto"' + (value === '__auto' ? ' selected' : '') + '>Work it out</option><option value=""' + (value === '' ? ' selected' : '') + '>Not in this file</option>' +
        cells.map(function (c) { return '<option value="' + esc(c) + '"' + (c === value ? ' selected' : '') + '>' + esc(c) + '</option>'; }).join('') + '</select></label>';
    });
    return html + '</div></details>';
  }

  /* ---------- view 2: trades (the journal) ---------- */

  function tradeFilter() {
    var f = S.trades;
    return S.result.trades.filter(function (t) {
      if (f.account && t.account !== f.account) return false;
      if (f.week) {
        var w = +f.week, d = t.status === 'closed' ? t.closeDay : t.openDay;
        if (d < w || d > w + 6) return false;
      }
      if (f.setup) { if (f.setup === '(none)' ? t.setup : t.setup !== f.setup) return false; }
      if (f.outcome === 'win' && !(t.status === 'closed' && t.net > 0)) return false;
      if (f.outcome === 'loss' && !(t.status === 'closed' && t.net < 0)) return false;
      if (f.outcome === 'open' && t.status !== 'open') return false;
      if (f.outcome === 'breach' && !t.breaches.length) return false;
      if (f.needs && t.setup && t.plannedRisk !== null) return false;
      if (f.fresh && S.opened && S.opened.closed[t.id]) return false;
      if (f.q && (t.symbol + ' ' + t.setup + ' ' + t.notes + ' ' + t.mistakes.join(' ')).toLowerCase().indexOf(f.q.toLowerCase()) < 0) return false;
      return true;
    }).sort(function (a, b) { return (b.openT - a.openT) || M.cmp(a.id, b.id); });
  }

  function renderTrades(panel) {
    var f = S.trades, res = S.result;
    var list = tradeFilter();
    if (f.selected && !tradeById(f.selected)) f.selected = null;
    if (!f.selected && list.length && !isNarrow()) f.selected = list[0].id;
    var setups = {};
    res.trades.forEach(function (t) { if (t.setup) setups[t.setup] = true; });
    (S.base.settings.setups || []).forEach(function (s) { setups[s] = true; });
    var weeks = res.weeks.slice().reverse();
    var html = '<div class="filters">' +
      '<label class="field"><span>Account</span><select id="tr-account">' + accountOptions(f.account) + '</select></label>' +
      '<label class="field"><span>Week</span><select id="tr-week"><option value="">All weeks</option>' + weeks.map(function (w) { return '<option value="' + w + '"' + (String(w) === String(f.week) ? ' selected' : '') + '>' + esc(M.weekLabel(w)) + '</option>'; }).join('') + '</select></label>' +
      '<label class="field"><span>Setup</span><select id="tr-setup"><option value="">Any setup</option><option value="(none)"' + (f.setup === '(none)' ? ' selected' : '') + '>No setup yet</option>' + Object.keys(setups).sort(M.cmp).map(function (s) { return '<option' + (s === f.setup ? ' selected' : '') + '>' + esc(s) + '</option>'; }).join('') + '</select></label>' +
      '<label class="field"><span>Outcome</span><select id="tr-outcome">' + [['', 'Any'], ['win', 'Winners'], ['loss', 'Losers'], ['open', 'Still open'], ['breach', 'Broke a rule']].map(function (o) { return '<option value="' + o[0] + '"' + (o[0] === f.outcome ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('') + '</select></label>' +
      '<label class="field"><span>Search</span><input type="search" id="tr-q" value="' + esc(f.q) + '" placeholder="Symbol, setup, note"></label>' +
      '<label class="check"><input type="checkbox" id="tr-needs"' + (f.needs ? ' checked' : '') + '> Needs journal notes</label>' +
      (S.opened ? '<label class="check"><input type="checkbox" id="tr-fresh"' + (f.fresh ? ' checked' : '') + '> New since the journal was opened</label>' : '') +
      '</div>';
    // On a phone the ticket opens under the trade you picked; on a wide screen it sits beside the list.
    var narrow = isNarrow();
    var shown = list.slice(0, f.limit);
    var selectedShown = shown.some(function (t) { return t.id === f.selected; });
    var ticket = ticketHtml(f.selected ? tradeById(f.selected) : null, list);
    html += '<div class="split">';
    // The list.
    html += '<section class="sheet plain" aria-label="Trades"><span class="eyebrow">The journal</span><h2>Round trips</h2>';
    if (list.length) {
      if (narrow && f.selected && !selectedShown) html += '<div class="trade-ticket" id="trade-ticket">' + ticket + '</div>';
      if (narrow && !f.selected) html += '<p class="hint">Tap a trade to open its ticket and journal.</p>';
      html += '<ul class="trade-list">' + shown.map(function (t) {
        var net = t.netBase === null ? t.net : t.netBase, cur = t.netBase === null ? t.currency : base();
        return '<li><button type="button" class="trade-row" data-select="' + esc(t.id) + '"' + (t.id === f.selected ? ' aria-current="true"' : '') + '>' +
          '<span class="tr-date">' + esc(M.fmtShort(t.openDay)) + '<br>' + esc(M.fmtTime(t.openSec)) + '</span>' +
          '<span class="tr-main"><span class="tr-sym">' + esc(t.symbol) + '</span> <span class="side-tag side-' + (t.dir > 0 ? 'long' : 'short') + '">' + sideWord(t).toUpperCase() + '</span>' +
          '<span class="tr-sub">' + esc(M.fmtQty(t.maxPos)) + ' &middot; ' + esc(t.status === 'open' ? 'still open' : M.fmtDuration(t.holdSec, t.timeKnown)) + (t.setup ? ' &middot; ' + esc(t.setup) : ' &middot; no setup') + '</span></span>' +
          '<span class="tr-net ' + (t.status === 'open' ? '' : cls(net)) + '">' + (t.status === 'open' ? 'open' : esc(M.money(net, cur, { sign: true }))) + '</span>' +
          '<span class="tr-r">' + esc(t.r === null ? '' : M.fmtR(t.r)) + '</span>' +
          ((t.breaches.length || t.mistakes.length) ? '<span class="tr-flags">' + (t.breaches.length ? '<span class="flag-breach">' + t.breaches.length + (t.breaches.length === 1 ? ' rule broken' : ' rules broken') + '</span>' : '') + t.mistakes.map(function (x) { return '<span class="chip mistake">' + esc(x) + '</span>'; }).join('') + '</span>' : '') +
          '</button></li>' + (narrow && t.id === f.selected ? '<li class="inline-ticket"><div class="trade-ticket" id="trade-ticket">' + ticket + '</div></li>' : '');
      }).join('') + '</ul>';
      html += '<p class="count-line">' + Math.min(list.length, f.limit) + ' of ' + list.length + ' trades shown.' + (list.length > f.limit ? ' <button type="button" class="linkish" data-action="trades-more">Show more</button>' : '') + '</p>';
    } else html += '<p class="empty">No trades match these filters.</p>';
    html += '<div class="btn-row" style="margin-top:12px"><button type="button" class="btn btn-line btn-small" data-action="trades-csv">Download round trips CSV</button><button type="button" class="btn btn-line btn-small" data-action="save">Save journal file</button></div>';
    html += '</section>';
    // The ticket.
    if (!narrow) html += '<div class="trade-ticket" id="trade-ticket">' + ticket + '</div>';
    html += '</div>';
    panel.innerHTML = html;
  }

  function ticketHtml(t, list) {
    if (!t) return '<div class="ticket"><div class="ticket-head"><h2>Trade ticket</h2></div><p class="empty">Pick a trade to see its fills and write up the journal.</p></div>';
    var cur = t.currency;
    var html = '<article class="ticket" aria-label="Trade ticket for ' + esc(M.tradeName(t)) + '">';
    html += '<div class="ticket-head"><h2>' + esc(t.symbol) + ' ' + sideWord(t).toLowerCase() + '</h2><span class="mono">' + esc(t.account) + ' &middot; ' + esc(M.fmtDate(t.openDay)) + ' ' + esc(M.fmtTime(t.openSec)) + '</span></div>';
    var net = t.status === 'closed' ? M.money(t.net, cur, { sign: true }) : 'still open';
    html += '<dl class="figs">' +
      fig('Net after fees', net, t.status === 'closed' ? cls(t.net) : '') +
      fig('R multiple', t.r === null ? (t.status === 'closed' ? 'no risk set' : '') : M.fmtR(t.r), t.r === null ? '' : cls(t.r)) +
      fig('Held', t.status === 'closed' ? M.fmtDuration(t.holdSec, t.timeKnown) : 'open') +
      fig('Before fees', M.money(t.gross, cur, { sign: true })) +
      fig('Fees', M.money(t.fees, cur)) +
      fig('Max position', M.fmtQty(t.maxPos)) +
      fig('Average entry', avgPrice(t.avgEntry)) +
      fig('Average exit', t.qtyOut ? avgPrice(t.avgExit) : '') +
      fig('Orders in, out', t.entryOrders + ', ' + t.exitOrders) +
      fig('Risk at the stop', t.initialRisk === null ? 'no stop' : M.money(t.initialRisk, cur)) +
      fig('Most at risk', t.maxRisk === null ? 'no stop' : M.money(t.maxRisk, cur)) +
      fig('Multiplier', M.fmtNum(t.mult, 2).replace(/\.00$/, '') + ' ' + cur) +
      '</dl>';
    if (t.netBase !== null && cur !== base() && t.status === 'closed') html += '<p class="hint">In ' + esc(base()) + ': ' + esc(m(t.netBase, { sign: true })) + ' at ' + esc(String(t.rate)) + '.</p>';
    // Fills.
    html += '<h3>Fills</h3><div class="table-wrap"><table class="ledger"><thead><tr><th>When</th><th>Side</th><th class="num">Qty</th><th class="num">Price</th><th class="num hide-sm">Fee</th><th>Role</th></tr></thead><tbody>' +
      t.legs.map(function (l) {
        return '<tr><td class="mono" style="font-size:.74rem">' + esc((l.day !== t.openDay ? M.fmtShort(l.day) + ' ' : '') + M.fmtTimeLong(l.sec)) + '</td><td><span class="side-tag side-' + l.side + '">' + (l.side === 'B' ? 'BUY' : 'SELL') + '</span></td><td class="num">' + esc(M.fmtQty(l.q)) + '</td><td class="num">' + esc(M.fmtPrice(l.price, true)) + '</td><td class="num hide-sm">' + esc(M.money(l.fee, '')) + '</td><td>' + esc(l.role) + '</td></tr>';
      }).join('') + '</tbody></table></div>';
    if (t.matches.length) {
      html += '<details><summary class="linkish">How the closes were matched (first in, first out)</summary><ul class="breach-list" style="margin-top:6px">' + t.matches.map(function (x) {
        return '<li class="no-mark">' + esc(M.fmtQty(x.q)) + ' opened at ' + esc(M.fmtPrice(x.entry, true)) + ', closed at ' + esc(M.fmtPrice(x.exit, true)) + ': <strong class="' + cls(x.pnl) + '">' + esc(M.money(x.pnl, cur, { sign: true })) + '</strong> before fees, held ' + esc(M.fmtDuration(x.holdSec, t.timeKnown)) + '</li>';
      }).join('') + '</ul></details>';
    }
    if (t.breaches.length) {
      var mine = S.result.breaches.filter(function (b) { return b.trade === t.id; });
      html += '<h3>Rules broken</h3><ul class="breach-list">' + mine.map(function (b) { return '<li><span class="rule-chip">' + esc(b.label) + '</span>' + esc(b.detail) + '</li>'; }).join('') + '</ul>';
    }
    // The journal fields.
    var setups = (S.base.settings.setups || []).slice();
    var mistakes = (S.base.settings.mistakes || []).slice();
    t.mistakes.forEach(function (x) { if (mistakes.indexOf(x) < 0) mistakes.push(x); });
    html += '<h3>Journal</h3>';
    html += '<datalist id="setup-list">' + setups.map(function (s) { return '<option value="' + esc(s) + '">'; }).join('') + '</datalist>';
    html += '<div class="form-grid">' +
      '<label class="field"><span>Setup</span><input type="text" id="j-setup" list="setup-list" value="' + esc(t.setup) + '" placeholder="e.g. Opening range break" data-role="journal"></label>' +
      '<label class="field"><span>Stop price</span><input type="text" inputmode="decimal" id="j-stop" value="' + esc(t.stopText) + '" placeholder="e.g. ' + esc(avgPrice(t.avgEntry)) + '" data-role="journal"><small>Gives the risk at the stop and the R multiple.</small></label>' +
      '<label class="field"><span>Planned risk (' + esc(cur) + ')</span><input type="text" inputmode="decimal" id="j-risk" value="' + esc(t.riskText) + '" placeholder="' + esc(t.initialRisk ? M.plainMoney(t.initialRisk) : 'e.g. 500') + '" data-role="journal"><small>Use instead of a stop, or to override it.</small></label>' +
      '<label class="field"><span>Target price</span><input type="text" inputmode="decimal" id="j-target" value="' + esc(t.targetText) + '" data-role="journal"></label>' +
      '</div>';
    html += '<fieldset style="border:0;padding:0;margin:0 0 12px"><legend class="field" style="font-weight:700;font-size:.88rem;margin-bottom:6px">Mistakes</legend><div class="mistake-picks">' +
      mistakes.map(function (x, i) { return '<label><input type="checkbox" id="j-m-' + i + '" data-role="journal-mistake" value="' + esc(x) + '"' + (t.mistakes.indexOf(x) >= 0 ? ' checked' : '') + '> ' + esc(x) + '</label>'; }).join('') + '</div></fieldset>';
    html += '<label class="field"><span>Notes</span><textarea id="j-notes" class="pencil-notes" data-role="journal-notes" placeholder="What was the plan? What happened? What would you do again?">' + esc(t.notes) + '</textarea></label>';
    var idx = -1;
    for (var i = 0; i < list.length; i++) if (list[i].id === t.id) idx = i;
    html += '<div class="btn-row"><button type="button" class="btn btn-line btn-small" data-action="prev-trade"' + (idx <= 0 ? ' disabled' : '') + '>Newer trade</button>' +
      '<button type="button" class="btn btn-line btn-small" data-action="next-trade"' + (idx < 0 || idx >= list.length - 1 ? ' disabled' : '') + '>Older trade</button>' +
      '<button type="button" class="btn btn-ink btn-small" data-action="next-needs">Next trade needing notes</button></div>';
    html += '<p class="hint mono" style="margin:10px 0 0;word-break:break-all">' + esc(t.id) + '</p>';
    html += '</article>';
    return html;
  }
  function tradeLinks(legs) {
    return legs.length ? legs.map(function (l) { return '<button type="button" class="linkish" data-trade="' + esc(l.trade) + '">' + esc(l.role) + '</button>'; }).join(' ') : '<span class="flag-breach">no opening fill</span>';
  }
  function isNarrow() { return !!(window.matchMedia && window.matchMedia('(max-width: 1040px)').matches); }
  function fig(label, value, klass) { return '<div class="fig"><dt>' + esc(label) + '</dt><dd class="' + (klass || '') + '">' + esc(value) + '</dd></div>'; }

  function saveJournalFromTicket(full) {
    var t = tradeById(S.trades.selected);
    if (!t) return;
    var ticket = $('#trade-ticket');
    var fields = {
      setup: $('#j-setup', ticket).value, stop: $('#j-stop', ticket).value, risk: $('#j-risk', ticket).value, target: $('#j-target', ticket).value,
      notes: $('#j-notes', ticket).value,
      mistakes: $$('[data-role="journal-mistake"]', ticket).filter(function (x) { return x.checked; }).map(function (x) { return x.value; })
    };
    S.base.journal = M.setJournal(S.base.journal, t.id, fields);
    if (full) reanalyse();
    else { t.notes = fields.notes; autosave(); }
  }

  /* ---------- view 3: review ---------- */

  function renderReview(panel) {
    var res = S.result;
    var weeks = closedWeeks();
    var html = '<div class="review-controls">' +
      '<label class="field"><span>Week</span><select id="rv-week">' + weeks.slice().reverse().map(function (w) {
        var n = M.filterTrades(res.closed, { account: S.review.account, from: w, to: w + 6 }).length;
        return '<option value="' + w + '"' + (!S.review.all && w === S.review.week ? ' selected' : '') + '>' + esc(M.weekLabel(w)) + ' (' + n + ')</option>';
      }).join('') + '<option value="all"' + (S.review.all ? ' selected' : '') + '>All weeks</option></select></label>' +
      '<label class="field"><span>Account</span><select id="rv-account">' + accountOptions(S.review.account) + '</select></label>' +
      '<div class="btn-row no-print"><button type="button" class="btn btn-line btn-small" data-action="trades-csv">Round trips CSV</button><button type="button" class="btn btn-line btn-small" data-action="breaches-csv">Breaches CSV</button><button type="button" class="btn btn-line btn-small" data-action="save">Save journal file</button></div>' +
      '</div>';
    if (!res.closed.length) {
      panel.innerHTML = html + '<div class="empty"><p>No closed trades yet. Add a fills export on the Fills tab: the review appears as soon as a position goes back to flat.</p><div class="btn-row" style="justify-content:center"><button type="button" class="btn btn-ink btn-small" data-go="fills">Add your fills</button><button type="button" class="btn btn-line btn-small" data-action="sample">Show the sample again</button></div></div>';
      return;
    }
    var list = periodTrades();
    var r = periodRange();
    var st = M.stats(list, {});
    // The weekly review sheet.
    if (!S.review.all && S.review.week !== null) {
      var rv = M.weekReview(res, { week: S.review.week, account: S.review.account });
      var text = S.chat === 'short' ? M.reviewShort(rv) : M.reviewText(rv, res);
      html += '<article class="ticket review-sheet" id="review-sheet"><div class="ticket-head"><h2>Weekly review</h2><span class="mono">' + esc(rv.label) + ' &middot; ' + esc(S.review.account || 'all accounts') + '</span></div>';
      html += reviewStatsHtml(rv.stats, rv);
      html += '<h3>What the week says</h3><ul class="notes-list">' + rv.notes.map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('') + '</ul>';
      if (rv.bySetup.length) html += '<h3>By setup</h3>' + barRows(rv.bySetup, function (x) { return x.n + (x.n === 1 ? ' trade' : ' trades') + ', ' + x.wins + ' won' + (x.avgR !== null ? ', avg ' + M.fmtR(x.avgR) : ''); });
      html += '<h3>Rule breaches this week</h3>' + (rv.breaches.length ? breachListHtml(rv.breaches) : '<p class="muted">None.</p>');
      if (rv.openAtEnd.length) html += '<h3>Open at the end of the week</h3><p>' + rv.openAtEnd.map(function (o) { return esc(o.symbol + ' ' + (o.dir > 0 ? 'long ' : 'short ') + M.fmtQty(o.q) + ' at ' + avgPrice(o.avgEntry)); }).join('; ') + '</p>';
      html += '<div class="no-print"><h3>For the team chat</h3><div class="seg" role="group" aria-label="Length of the text"><button type="button" data-action="chat-short" aria-pressed="' + (S.chat === 'short') + '">Short</button><button type="button" data-action="chat-full" aria-pressed="' + (S.chat !== 'short') + '">Full</button></div><label class="sr" for="review-text">Review as text</label><textarea class="copy-text" id="review-text" readonly>' + esc(text) + '</textarea>' +
        '<div class="btn-row" style="margin-top:10px"><button type="button" class="btn btn-ink" data-action="copy-review">Copy for the team chat</button><button type="button" class="btn btn-line" data-action="print-review">Print the review</button><button type="button" class="btn btn-line" data-action="review-txt">Download as text</button></div></div>';
      html += '<p class="hint" style="margin-top:12px">Not financial advice: a record of trades already made.</p></article>';
    } else {
      var allStats = M.stats(list, { start: M.startBalance(res, S.review.account ? [S.review.account] : res.accounts) });
      html += '<article class="ticket review-sheet" id="review-sheet"><div class="ticket-head"><h2>All weeks</h2><span class="mono">' + esc(S.review.account || 'all accounts') + '</span></div>' + reviewStatsHtml(allStats, null) + '<p class="hint">Pick a single week above for the weekly review and the text for the team chat.</p></article>';
    }
    // Equity curve and weeks.
    var accountTrades = M.filterTrades(res.closed, { account: S.review.account });
    var start = M.startBalance(res, S.review.account ? [S.review.account] : res.accounts);
    var all = M.stats(accountTrades, { start: start });
    html += '<section class="sheet plain"><span class="eyebrow">Closed-trade equity</span><h2>Running total after fees</h2>' +
      '<p class="intro">Every closed trade in order, ' + esc(S.review.account || 'all accounts') + ', in ' + esc(base()) + '. The red band is the drop from the last high; the yellow band is ' + esc(periodLabel()) + '.</p>' +
      '<div class="chart chart-paper" id="equity-chart" data-from="' + (r.from === null ? '' : r.from) + '" data-to="' + (r.to === null ? '' : r.to) + '"></div>' +
      '<ul class="chart-legend"><li><i style="background:var(--ink)"></i>Net after fees, running total</li><li><i style="background:var(--brass)"></i>Previous high</li><li><i style="background:var(--loss)"></i>Drop from the high</li></ul>' +
      '<p class="hint">' + esc(summaryLine(all, start)) + '</p></section>';
    html += '<div class="grid-2">';
    var wk = M.weekly(accountTrades);
    html += '<section class="sheet plain"><span class="eyebrow">Week by week</span><h2>Net after fees each week</h2><div class="bars">' + weekBarsHtml(wk) + '</div></section>';
    html += '<section class="sheet plain"><span class="eyebrow">' + esc(periodLabel()) + '</span><h2>R multiples</h2>' + histHtml(M.rHistogram(list)) +
      '<p class="hint">' + (st.rCount ? st.rCount + ' of ' + st.n + ' trades have a stop or planned risk. ' + st.rWins + ' made more than nothing; average ' + esc(M.fmtR(st.avgR)) + '.' : 'Add a stop or planned risk to trades in the journal to see R multiples.') + '</p></section>';
    html += '</div>';
    // Breakdowns.
    html += '<section class="sheet plain"><span class="eyebrow">' + esc(periodLabel()) + '</span><h2>Where the money came from</h2><div class="seg" role="group" aria-label="Break down by">' +
      M.BREAKDOWNS.map(function (b) { return '<button type="button" data-breakdown="' + b.id + '" aria-pressed="' + (S.breakdown === b.id ? 'true' : 'false') + '">' + esc(b.label) + '</button>'; }).join('') + '</div>';
    var rows = M.breakdown(list, S.breakdown);
    html += rows.length ? barRows(rows, function (x) {
      return x.n + (x.n === 1 ? ' trade' : ' trades') + ', ' + M.fmtPct(x.winRate) + ' won, ' + M.money(M.rnd(x.avg), base(), { sign: true }) + ' a trade' + (x.profitFactor !== null ? ', PF ' + M.fmtNum(x.profitFactor, 2) : '') + (x.avgR !== null ? ', avg ' + M.fmtR(x.avgR) : '');
    }) : '<p class="muted">No closed trades in this period.</p>';
    if (S.breakdown === 'mistake') html += '<p class="hint">A trade with two mistake tags counts under both.</p>';
    html += '</section>';
    // What keeping to the rules would have changed.
    var wi = M.whatIf(res, { account: S.review.account, from: r.from, to: r.to });
    html += '<section class="sheet plain"><span class="eyebrow">' + esc(periodLabel()) + '</span><h2>If you had kept to your rules</h2>' +
      '<p class="intro">An estimate, trade by trade: leave out the trades a rule said not to take (after the daily limit, over the daily count, outside trading hours, after a losing run), size oversized trades down to the risk limit, and take every stop as planned so no loss before fees goes beyond the planned risk. Everything else is left as it was, though in real life it would have changed too.</p>' +
      '<dl class="stat-grid whatif">' +
      '<div class="stat"><dt>What happened</dt><dd class="' + cls(wi.actual) + '">' + esc(m(wi.actual, { sign: true })) + '<small>' + M.plural(wi.n, 'closed trade') + '</small></dd></div>' +
      '<div class="stat"><dt>Skip the trades ruled out</dt><dd class="' + cls(wi.skip.change) + '">' + esc(m(wi.skip.change, { sign: true })) + '<small>' + M.plural(wi.skip.n, 'trade') + '</small></dd></div>' +
      '<div class="stat"><dt>Size within the risk limit</dt><dd class="' + cls(wi.size.change) + '">' + esc(m(wi.size.change, { sign: true })) + '<small>' + M.plural(wi.size.n, 'trade') + '</small></dd></div>' +
      '<div class="stat"><dt>Take stops as planned</dt><dd class="' + cls(wi.cap.change) + '">' + esc(m(wi.cap.change, { sign: true })) + '<small>' + M.plural(wi.cap.n, 'trade') + ' lost more than planned</small></dd></div>' +
      '</dl><p class="whatif-total">All three together: <strong class="' + cls(wi.combined) + '">' + esc(m(wi.combined, { sign: true })) + '</strong> instead of <strong class="' + cls(wi.actual) + '">' + esc(m(wi.actual, { sign: true })) + '</strong>' +
      (wi.combined > wi.actual ? ', ' + esc(m(wi.combined - wi.actual)) + ' better.' : wi.combined < wi.actual ? ': the rules would have cost ' + esc(m(wi.actual - wi.combined)) + ' this time.' : ': no change.') + '</p></section>';
    // Breaches for the period.
    var breaches = res.breaches.filter(function (b) { return (!S.review.account || b.account === S.review.account) && (r.from === null || (b.day >= r.from && b.day <= r.to)); });
    html += '<section class="sheet plain"><span class="eyebrow">' + esc(periodLabel()) + '</span><h2>Rule breaches</h2>';
    html += '<ul class="chips">' + res.ruleSummary.filter(function (x) { return x.on; }).map(function (x) {
      var n = breaches.filter(function (b) { return b.rule === x.id; }).length;
      return '<li class="chip' + (n ? ' bad' : '') + '">' + esc(x.label) + ': ' + n + '</li>';
    }).join('') + '</ul>';
    html += breaches.length ? breachListHtml(breaches.slice(0, 120)) + (breaches.length > 120 ? '<p class="hint">Showing the first 120 of ' + breaches.length + '. The breaches CSV has them all.</p>' : '') : '<p class="muted">No rules broken in this period.</p>';
    html += '</section>';
    panel.innerHTML = html;
    drawEquity();
  }

  function summaryLine(s, start) {
    if (!s.n) return '';
    var txt = 'Net ' + m(s.net, { sign: true }) + ' over ' + s.n + ' closed trades.';
    if (s.maxDD > 0) txt += ' Largest drop from a high: ' + m(s.maxDD) + (s.maxDDPct !== null ? ' (' + M.fmtNum(s.maxDDPct, 1) + '% of the account at its high)' : '') + (s.ddFrom !== null ? ', from ' + M.fmtShort(Math.floor(s.ddFrom / 86400)) : '') + ' to ' + M.fmtShort(Math.floor(s.ddTo / 86400)) + '.';
    if (!start) txt += ' Set starting balances under Rules to see the drop as a percentage.';
    return txt;
  }

  function reviewStatsHtml(s, rv) {
    if (!s.n) return '<p class="empty">No trades closed in this period.</p>';
    function stat(label, value, sub, klass) { return '<div class="stat"><dt>' + esc(label) + '</dt><dd class="' + (klass || '') + '">' + esc(value) + (sub ? '<small>' + esc(sub) + '</small>' : '') + '</dd></div>'; }
    var prev = rv && rv.prev;
    var html = '<dl class="stat-grid">' +
      stat('Net after fees', m(s.net, { sign: true }), 'before fees ' + m(s.gross, { sign: true }) + ', fees ' + m(s.fees), cls(s.net)) +
      stat('Closed trades', String(s.n), s.wins + ' won, ' + s.losses + ' lost' + (s.flat ? ', ' + s.flat + ' flat' : '')) +
      stat('Win rate', M.fmtPct(s.winRate), prev && prev.winRate !== null ? 'previous weeks ' + M.fmtPct(prev.winRate) : '') +
      stat('Expectancy', m(M.rnd(s.expectancy), { sign: true }), prev && prev.expectancy !== null ? 'previous weeks ' + m(M.rnd(prev.expectancy), { sign: true }) : 'a trade', cls(s.expectancy)) +
      stat('Average win', s.avgWin === null ? 'n/a' : m(M.rnd(s.avgWin)), s.payoff !== null ? 'payoff ratio ' + M.fmtNum(s.payoff, 2) : '') +
      stat('Average loss', s.avgLoss === null ? 'n/a' : m(M.rnd(s.avgLoss)), 'longest losing run ' + s.maxLossStreak) +
      stat('Profit factor', s.profitFactor === null ? 'no losses' : M.fmtNum(s.profitFactor, 2), 'gross wins over gross losses') +
      stat('Average R', s.avgR === null ? 'n/a' : M.fmtR(s.avgR), s.rCount + ' of ' + s.n + ' with planned risk', s.avgR === null ? '' : cls(s.avgR)) +
      stat('Largest drop', m(s.maxDD), s.recovery !== null ? 'net is ' + M.fmtNum(s.recovery, 2) + ' times the drop' : 'from the running high') +
      stat('Held, winners', s.avgHoldWin === null ? 'n/a' : M.fmtDuration(s.avgHoldWin), 'losers ' + (s.avgHoldLoss === null ? 'n/a' : M.fmtDuration(s.avgHoldLoss))) +
      stat('Long, short', m(s.longNet, { sign: true, whole: true }) + ' / ' + m(s.shortNet, { sign: true, whole: true }), s.longN + ' long, ' + s.shortN + ' short') +
      (rv ? stat('Best, worst', m(s.best.net, { sign: true, whole: true }) + ' / ' + m(s.worst.net, { sign: true, whole: true }), 'single trades')
        : stat('Daily Sharpe', s.sharpe === null ? 'n/a' : M.fmtNum(s.sharpe, 2), s.sharpe === null ? 'needs starting balances and 2 days' : 'Sortino ' + (s.sortino === null ? 'n/a' : M.fmtNum(s.sortino, 2)) + ', over ' + s.days.length + ' days')) +
      '</dl>';
    return html;
  }

  function barRows(rows, sub) {
    var max = 1;
    rows.forEach(function (x) { if (Math.abs(x.net) > max) max = Math.abs(x.net); });
    var hasNeg = rows.some(function (x) { return x.net < 0; });
    var zero = hasNeg ? 50 : 0;
    return '<div class="bars">' + rows.map(function (x) {
      var w = Math.abs(x.net) / max * (hasNeg ? 50 : 100);
      var left = x.net >= 0 ? zero : zero - w;
      return '<div class="bar-row"><span class="label" title="' + esc(x.label) + '">' + esc(x.label) + '</span><span class="bar-track">' + (hasNeg ? '<span class="zero" style="left:' + zero + '%"></span>' : '') +
        '<span class="bar-fill ' + (x.net >= 0 ? 'pos' : 'neg') + '" style="left:' + left.toFixed(2) + '%;width:' + Math.max(w, 0.6).toFixed(2) + '%"></span></span><span class="val ' + cls(x.net) + '">' + esc(m(x.net, { sign: true, whole: true })) + '</span>' +
        '<span class="hint" style="grid-column:1/-1;margin-top:-2px">' + esc(sub(x)) + '</span></div>';
    }).join('') + '</div>';
  }

  function weekBarsHtml(wk) {
    if (!wk.length) return '<p class="muted">No closed trades.</p>';
    var max = 1;
    wk.forEach(function (x) { if (Math.abs(x.net) > max) max = Math.abs(x.net); });
    return wk.map(function (x) {
      var w = Math.abs(x.net) / max * 50;
      var current = !S.review.all && x.week === S.review.week;
      return '<button type="button" class="bar-row linkish-row' + (current ? ' current' : '') + '" data-week="' + x.week + '" aria-label="' + esc(M.weekLabel(x.week) + ': ' + m(x.net, { sign: true }) + ' from ' + x.n + ' trades') + '" style="background:none;border:0;padding:2px 0;cursor:pointer;text-align:left;color:inherit;font:inherit">' +
        '<span class="label">' + esc(M.fmtShort(x.week)) + ' <span class="muted">(' + x.n + ')</span></span><span class="bar-track"><span class="zero" style="left:50%"></span><span class="bar-fill ' + (x.net >= 0 ? 'pos' : 'neg') + '" style="left:' + (x.net >= 0 ? 50 : 50 - w).toFixed(2) + '%;width:' + Math.max(w, 0.6).toFixed(2) + '%"></span></span><span class="val ' + cls(x.net) + '">' + esc(m(x.net, { sign: true, whole: true })) + '</span></button>';
    }).join('') + '<p class="hint">Pick a week to review it.</p>';
  }

  function histHtml(h) {
    var max = 1;
    h.forEach(function (b) { if (b.n > max) max = b.n; });
    return '<div class="hist" role="img" aria-label="' + esc(h.map(function (b) { return b.n + ' trades from ' + b.from + 'R to ' + b.to + 'R'; }).join('; ')) + '">' + h.map(function (b) {
      return '<div class="' + (b.from < 0 ? 'neg' : '') + '" style="height:' + (b.n / max * 100).toFixed(1) + '%">' + (b.n ? '<span>' + b.n + '</span>' : '') + '</div>';
    }).join('') + '</div><div class="hist-axis" aria-hidden="true">' + h.map(function (b, i) { return '<span>' + (i % 2 === 0 ? (b.from > 0 ? '+' : '') + b.from : '') + '</span>'; }).join('') + '</div>';
  }

  function breachListHtml(list) {
    return '<ul class="breach-list">' + list.map(function (b) {
      var t = b.trade ? tradeById(b.trade) : null;
      return '<li><span class="rule-chip">' + esc(b.label) + '</span>' + esc(b.detail) + ' <span class="muted">(' + esc(M.fmtShort(b.day) + (b.sec !== null ? ' ' + M.fmtTime(b.sec) : '')) + (t ? ', ' : '') + '</span>' +
        (t ? '<button type="button" class="linkish" data-trade="' + esc(t.id) + '">' + esc(M.tradeName(t)) + (t.status === 'closed' ? ' ' + esc(M.money(t.net, t.currency, { sign: true })) : '') + '</button>' : '') + '<span class="muted">)</span></li>';
    }).join('') + '</ul>';
  }

  // The equity curve, drawn at the chart's real width so its text stays readable on a phone.
  function drawEquity() {
    var box = document.getElementById('equity-chart');
    if (!box) return;
    var res = S.result;
    var list = M.filterTrades(res.closed, { account: S.review.account }).filter(function (t) { return t.netBase !== null; });
    var W = Math.max(300, Math.floor(box.clientWidth - 12) || 900), H = W < 560 ? 220 : 280;
    var padL = W < 560 ? 58 : 76, padR = 12, padT = 14, padB = 30;
    var n = list.length;
    if (!n) { box.innerHTML = '<p class="muted">No closed trades.</p>'; return; }
    var cum = [0], peak = [0], c = 0, p = 0;
    list.forEach(function (t) { c += t.netBase; if (c > p) p = c; cum.push(c); peak.push(p); });
    var lo = Math.min.apply(null, cum), hi = Math.max.apply(null, cum);
    if (hi === lo) { hi += 100; lo -= 100; }
    var span = hi - lo, step = niceStep(span / 4);
    var y0 = Math.floor(lo / step) * step, y1 = Math.ceil(hi / step) * step;
    function X(i) { return padL + i / n * (W - padL - padR); }
    function Y(v) { return padT + (y1 - v) / (y1 - y0) * (H - padT - padB); }
    var out = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" role="img" aria-labelledby="eq-title eq-desc"><title id="eq-title">Closed-trade equity curve</title><desc id="eq-desc">' + esc(summaryLine(M.stats(list, {}), 0)) + '</desc>';
    // Period band.
    var from = box.getAttribute('data-from'), to = box.getAttribute('data-to');
    if (from !== '') {
      var a = -1, b = -1;
      list.forEach(function (t, i) { if (t.closeDay >= +from && t.closeDay <= +to) { if (a < 0) a = i; b = i; } });
      if (a >= 0) out += '<rect x="' + X(a).toFixed(1) + '" y="' + padT + '" width="' + Math.max(3, X(b + 1) - X(a)).toFixed(1) + '" height="' + (H - padT - padB) + '" fill="#f8ea9e" opacity=".75"/>';
    }
    // Grid and y labels.
    for (var v = y0; v <= y1 + step / 2; v += step) {
      out += '<line x1="' + padL + '" x2="' + (W - padR) + '" y1="' + Y(v).toFixed(1) + '" y2="' + Y(v).toFixed(1) + '" stroke="' + (v === 0 ? '#2b2825' : '#b9c8e0') + '" stroke-width="' + (v === 0 ? 1.4 : 1) + '"' + (v === 0 ? '' : ' stroke-dasharray="3 4"') + '/>';
      out += '<text class="axis-text" x="' + (padL - 6) + '" y="' + (Y(v) + 4).toFixed(1) + '" text-anchor="end">' + esc(compactMoney(v)) + '</text>';
    }
    // Week ticks along the bottom.
    var lastX = -999, lastWeek = null;
    list.forEach(function (t, i) {
      var w = M.weekStart(t.closeDay);
      if (w === lastWeek) return;
      lastWeek = w;
      var x = X(i);
      out += '<line x1="' + x.toFixed(1) + '" x2="' + x.toFixed(1) + '" y1="' + (H - padB) + '" y2="' + (H - padB + 5) + '" stroke="#5c564e"/>';
      if (x - lastX > (W < 560 ? 64 : 70) && x < W - 30) { out += '<text class="axis-text" x="' + x.toFixed(1) + '" y="' + (H - 9) + '" text-anchor="middle">' + esc(M.fmtShort(w)) + '</text>'; lastX = x; }
    });
    // Drawdown area between the running high and the curve.
    var dd = 'M' + X(0).toFixed(1) + ' ' + Y(peak[0]).toFixed(1);
    for (var i = 1; i <= n; i++) dd += ' L' + X(i).toFixed(1) + ' ' + Y(peak[i]).toFixed(1);
    for (var j = n; j >= 0; j--) dd += ' L' + X(j).toFixed(1) + ' ' + Y(cum[j]).toFixed(1);
    out += '<path d="' + dd + ' Z" fill="#b3301d" opacity=".22"/>';
    var pk = '', ln = '';
    for (var k = 0; k <= n; k++) { pk += (k ? ' L' : 'M') + X(k).toFixed(1) + ' ' + Y(peak[k]).toFixed(1); ln += (k ? ' L' : 'M') + X(k).toFixed(1) + ' ' + Y(cum[k]).toFixed(1); }
    out += '<path d="' + pk + '" fill="none" stroke="#b5862c" stroke-width="1.5" stroke-dasharray="5 4"/>';
    out += '<path d="' + ln + '" fill="none" stroke="#26307a" stroke-width="2.4" stroke-linejoin="round"/>';
    out += '<circle cx="' + X(n).toFixed(1) + '" cy="' + Y(cum[n]).toFixed(1) + '" r="4" fill="#26307a"/>';
    out += '</svg>';
    box.innerHTML = out;
  }
  function niceStep(x) {
    if (!(x > 0)) return 100;
    var p = Math.pow(10, Math.floor(Math.log(x) / Math.LN10));
    var f = x / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
  }
  function compactMoney(cents, sign, bare) {
    var v = cents / 100, a = Math.abs(v), sym = bare ? '' : M.money(0, base()).replace(/[0-9.,\s]/g, '') || '';
    var txt = a >= 1000000 ? (a / 1000000).toFixed(1).replace(/\.0$/, '') + 'm' : a >= 10000 ? Math.round(a / 1000) + 'k' : a >= 1000 ? (a / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(Math.round(a));
    return (v < 0 ? '-' : sign && v > 0 ? '+' : '') + sym + txt;
  }

  /* ---------- view 4: days ---------- */

  function renderDays(panel) {
    var res = S.result, d = S.days;
    if (d.account && res.accounts.indexOf(d.account) < 0) d.account = '';
    var ledger = M.dayLedger(res, { account: d.account });
    var html = '<div class="review-controls"><label class="field"><span>Account</span><select id="days-account">' + accountOptions(d.account) + '</select></label>' +
      '<div class="btn-row"><button type="button" class="btn btn-line btn-small" data-action="days-csv">Download days CSV</button></div></div>';
    if (!ledger.length) { panel.innerHTML = html + '<p class="empty">No trading days yet.</p>'; return; }
    var byDay = {};
    ledger.forEach(function (x) { byDay[x.day] = x; });
    if (d.day === null || !byDay[d.day]) d.day = ledger[ledger.length - 1].day;
    var hits = ledger.filter(function (x) { return x.limitHit; }).length;
    var up = ledger.filter(function (x) { return x.realised > 0; }).length;
    html += '<section class="sheet plain cal-sheet"><span class="eyebrow">The calendar</span><h2>Every trading day, after fees</h2>' +
      '<p class="intro">Profit realised each day in ' + esc(base()) + ', after every fee, including partial closes of positions still open. ' + up + ' of ' + ledger.length + ' days ended up' + (hits ? '; the daily loss limit was hit on ' + M.plural(hits, 'day') : '') + '. Pick a day to replay it.</p>' +
      '<ul class="cal-key"><li><span class="side-tag side-long">BLUE</span> up on the day</li><li><span class="side-tag side-short">RED</span> down on the day</li><li>Red corner: a rule broken</li><li>LIMIT: daily loss limit hit</li></ul>';
    var first = ledger[0].day, last = ledger[ledger.length - 1].day;
    var c0 = M.civil(first), c1 = M.civil(last);
    for (var y = c0[0], mo = c0[1]; y < c1[0] || (y === c1[0] && mo <= c1[1]); mo === 12 ? (y++, mo = 1) : mo++) {
      html += monthHtml(y, mo, byDay);
    }
    html += '</section>';
    html += '<div id="day-ticket">' + dayTicketHtml(M.dayDetail(res, d.day, { account: d.account }), byDay[d.day]) + '</div>';
    panel.innerHTML = html;
    drawDayChart();
  }

  var MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  function monthHtml(y, mo, byDay) {
    var start = M.daysFromCivil(y, mo, 1);
    var nextStart = mo === 12 ? M.daysFromCivil(y + 1, 1, 1) : M.daysFromCivil(y, mo + 1, 1);
    var html = '<div class="cal-month"><h3>' + MONTHS_LONG[mo - 1] + ' ' + y + '</h3><div class="cal-grid">';
    M.DAY_NAMES.forEach(function (n) { html += '<div class="cal-head" aria-hidden="true">' + n + '</div>'; });
    html += '<div class="cal-head" aria-hidden="true">Week</div>';
    for (var w = M.weekStart(start); w < nextStart; w += 7) {
      var weekSum = 0, weekAny = false;
      for (var k = 0; k < 7; k++) {
        var day = w + k;
        if (day < start || day >= nextStart) { html += '<div class="cal-cell empty"></div>'; continue; }
        var x = byDay[day];
        if (!x) { html += '<div class="cal-cell off"><span class="d">' + M.civil(day)[2] + '</span></div>'; continue; }
        weekSum += x.realised; weekAny = true;
        var label = M.fmtDate(day) + ': ' + m(x.realised, { sign: true }) + ' after fees, ' + M.plural(x.closed, 'trade') + ' closed' + (x.breaches ? ', ' + M.plural(x.breaches, 'rule breach', 'rule breaches') : '') + (x.limitHit ? ', daily loss limit hit' : '');
        html += '<button type="button" class="cal-cell ' + (x.realised > 0 ? 'pos' : x.realised < 0 ? 'neg' : '') + '" data-day="' + day + '" aria-pressed="' + (day === S.days.day ? 'true' : 'false') + '" aria-label="' + esc(label) + '">' +
          '<span class="d">' + M.civil(day)[2] + '</span><span class="v wide ' + cls(x.realised) + '">' + esc(compactMoney(x.realised, true)) + '</span><span class="v narrow ' + cls(x.realised) + '">' + esc(compactMoney(x.realised, true, true)) + '</span><span class="n">' + x.closed + ' closed</span>' +
          (x.breaches ? '<span class="flagged"></span>' : '') + (x.limitHit ? '<span class="limit">LIMIT</span>' : '') + '</button>';
      }
      html += '<div class="cal-week">' + (weekAny ? '<span class="v wide ' + cls(weekSum) + '">' + esc(compactMoney(weekSum, true)) + '</span><span class="v narrow ' + cls(weekSum) + '">' + esc(compactMoney(weekSum, true, true)) + '</span>' : '') + '</div>';
    }
    return html + '</div></div>';
  }

  function dayTicketHtml(dd, x) {
    var html = '<article class="ticket"><div class="ticket-head"><h2>' + esc(M.fmtDate(dd.day)) + '</h2><span class="mono">' + esc(S.days.account || 'all accounts') + ' &middot; replayed fill by fill</span></div>';
    html += '<dl class="figs">' +
      fig('Realised after fees', m(dd.total, { sign: true }), cls(dd.total)) + fig('Before fees', m(x.pnl, { sign: true })) + fig('Fees', m(x.fees)) +
      fig('Trades opened, closed', x.opened + ', ' + x.closed) + fig('Won, lost', x.wins + ', ' + x.losses) + fig('Rule breaches', String(x.breaches), x.breaches ? 'loss' : '') +
      fig('Best point of the day', m(dd.high, { sign: true })) + fig('Worst point', m(dd.low, { sign: true }), cls(dd.low)) + fig('Largest drop in the day', m(dd.drop)) +
      '</dl>';
    html += '<div class="chart chart-paper" id="day-chart"></div><ul class="chart-legend"><li><i style="background:var(--ink)"></i>Running total after fees through the day</li></ul>';
    if (dd.breaches.length) html += '<h3>Rules broken that day</h3>' + breachListHtml(dd.breaches);
    html += '<h3>Fill by fill</h3><div class="table-wrap"><table class="ledger"><thead><tr><th>Time</th><th>Symbol</th><th class="hide-sm">Account</th><th class="num">Realised</th><th class="num hide-sm">Fees</th><th class="num">Running total</th><th class="hide-sm">Trade</th></tr></thead><tbody>' +
      dd.rows.map(function (r) {
        return '<tr><td class="mono" style="font-size:.74rem">' + esc(M.fmtTimeLong(r.sec)) + '</td><td><strong>' + esc(r.symbol) + '</strong><span class="show-sm">' + dayLinks(r) + '</span></td><td class="hide-sm" style="font-size:.8rem">' + esc(r.account) + '</td>' +
          '<td class="num ' + cls(r.pnl) + '">' + (r.pnl ? esc(m(r.pnl, { sign: true })) : '') + '</td><td class="num hide-sm">' + esc(m(r.fees)) + '</td><td class="num ' + cls(r.total) + '">' + esc(m(r.total, { sign: true })) + '</td>' +
          '<td class="hide-sm">' + dayLinks(r) + '</td></tr>';
      }).join('') + '</tbody></table></div>';
    return html + '</article>';
  }

  function dayLinks(r) {
    return r.trades.map(function (id) { var t = tradeById(id); return t ? '<button type="button" class="linkish" data-trade="' + esc(id) + '">' + esc(sideWord(t).toLowerCase()) + '</button>' : ''; }).join(' ');
  }

  function drawDayChart() {
    var box = document.getElementById('day-chart');
    if (!box) return;
    var dd = M.dayDetail(S.result, S.days.day, { account: S.days.account });
    if (!dd.rows.length) { box.innerHTML = ''; return; }
    var W = Math.max(300, Math.floor(box.clientWidth - 12) || 900), H = 180, padL = W < 560 ? 58 : 76, padR = 12, padT = 12, padB = 26;
    var t0 = dd.rows[0].t, t1 = dd.rows[dd.rows.length - 1].t;
    if (t1 === t0) t1 = t0 + 60;
    var lo = Math.min(0, dd.low), hi = Math.max(0, dd.high);
    if (hi === lo) { hi += 100; lo -= 100; }
    var step = niceStep((hi - lo) / 3), y0 = Math.floor(lo / step) * step, y1 = Math.ceil(hi / step) * step;
    function X(t) { return padL + (t - t0) / (t1 - t0) * (W - padL - padR); }
    function Y(v) { return padT + (y1 - v) / (y1 - y0) * (H - padT - padB); }
    var out = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" role="img" aria-label="' + esc('Running total through ' + M.fmtDate(dd.day) + ': ending ' + m(dd.total, { sign: true }) + ', best ' + m(dd.high, { sign: true }) + ', worst ' + m(dd.low, { sign: true })) + '">';
    for (var v = y0; v <= y1 + step / 2; v += step) {
      out += '<line x1="' + padL + '" x2="' + (W - padR) + '" y1="' + Y(v).toFixed(1) + '" y2="' + Y(v).toFixed(1) + '" stroke="' + (v === 0 ? '#2b2825' : '#b9c8e0') + '"' + (v === 0 ? '' : ' stroke-dasharray="3 4"') + '/>';
      out += '<text class="axis-text" x="' + (padL - 6) + '" y="' + (Y(v) + 4).toFixed(1) + '" text-anchor="end">' + esc(compactMoney(v)) + '</text>';
    }
    var hours = Math.max(1, Math.ceil((t1 - t0) / 3600));
    var every = W < 560 ? Math.max(1, Math.ceil(hours / 4)) : Math.max(1, Math.ceil(hours / 8));
    for (var h = Math.ceil(t0 / 3600) * 3600; h <= t1; h += 3600 * every) {
      out += '<text class="axis-text" x="' + X(h).toFixed(1) + '" y="' + (H - 7) + '" text-anchor="middle">' + esc(M.fmtTime(h % 86400)) + '</text>';
    }
    var path = 'M' + X(t0).toFixed(1) + ' ' + Y(0).toFixed(1), prev = 0;
    dd.rows.forEach(function (r) { path += ' L' + X(r.t).toFixed(1) + ' ' + Y(prev).toFixed(1) + ' L' + X(r.t).toFixed(1) + ' ' + Y(r.total).toFixed(1); prev = r.total; });
    out += '<path d="' + path + '" fill="none" stroke="#26307a" stroke-width="2.2"/>';
    dd.rows.forEach(function (r) { if (r.pnl) out += '<circle cx="' + X(r.t).toFixed(1) + '" cy="' + Y(r.total).toFixed(1) + '" r="3" fill="' + (r.pnl > 0 ? '#26307a' : '#b3301d') + '"/>'; });
    box.innerHTML = out + '</svg>';
  }

  /* ---------- view 5: rules and sizing ---------- */

  var RULE_TEXT = {
    maxRiskPct: 'The most a trade may lose at its stop, as a percentage of the account when it opened (the starting balance plus closed trades). Uses the stop or planned risk from the journal.',
    maxDailyLoss: 'Realised loss in a day, after fees, including partial closes and fees not tied to a trade. Trades opened after the limit was hit are listed too.',
    maxTradesPerDay: 'Counts trades opened each day in each account.',
    maxDrawdown: 'How far the closed-trade balance may fall below its highest point, as challenge and funded accounts often limit it. Flagged at the trade that takes it past the limit.',
    tradingWindow: 'No new trades outside these hours, for example to keep out of the first minutes after the open. Written like 09:35-15:45, in the times your export uses.',
    coolOff: 'Stop for the day after this many losing trades in a row. Trades opened after the run are listed.',
    noAddingToLoser: 'Adding to a position at a worse price than its average entry (buying below it when long, shorting above it when short). Partial fills of one order do not count as adding.',
    maxLossR: 'A loss bigger than this many times the planned risk usually means the stop was moved or ignored.',
    needPlannedRisk: 'Every closed trade should have a stop or planned risk in the journal, or the risk rules cannot be checked.'
  };

  function renderRules(panel) {
    var res = S.result, set = S.base.settings, rules = set.rules;
    var html = '<div class="grid-2">';
    html += '<section class="ticket"><div class="ticket-head"><h2>House rules</h2><span class="mono">checked on every trade</span></div><ul class="rule-list">';
    res.ruleSummary.forEach(function (x) {
      var rule = rules[x.id] || { on: false };
      var ctrl = '<label class="check"><input type="checkbox" id="rule-on-' + x.id + '" data-role="rule-on" data-rule="' + x.id + '"' + (rule.on ? ' checked' : '') + '> On</label>';
      if (x.id === 'maxRiskPct') ctrl += '<label class="sr" for="rule-v-' + x.id + '">Maximum risk per trade, percent</label><input type="text" inputmode="decimal" class="inline-input" id="rule-v-' + x.id + '" data-role="rule-value" data-rule="' + x.id + '" value="' + esc(rule.value || '') + '"> <span>% of account</span>';
      if (x.id === 'maxDailyLoss') ctrl += '<label class="sr" for="rule-v-' + x.id + '">Maximum daily loss</label><input type="text" inputmode="decimal" class="inline-input" id="rule-v-' + x.id + '" data-role="rule-value" data-rule="' + x.id + '" value="' + esc(rule.value || '') + '"><label class="sr" for="rule-u-' + x.id + '">Daily loss unit</label><select class="inline-select" id="rule-u-' + x.id + '" data-role="rule-unit" data-rule="' + x.id + '"><option value="pct"' + (rule.unit !== 'money' ? ' selected' : '') + '>% of starting balance</option><option value="money"' + (rule.unit === 'money' ? ' selected' : '') + '>in money</option></select>';
      if (x.id === 'maxDrawdown') ctrl += '<label class="sr" for="rule-v-' + x.id + '">Maximum drawdown</label><input type="text" inputmode="decimal" class="inline-input" id="rule-v-' + x.id + '" data-role="rule-value" data-rule="' + x.id + '" value="' + esc(rule.value || '') + '"><label class="sr" for="rule-u-' + x.id + '">Drawdown unit</label><select class="inline-select" id="rule-u-' + x.id + '" data-role="rule-unit" data-rule="' + x.id + '"><option value="pct"' + (rule.unit !== 'money' ? ' selected' : '') + '>% of starting balance</option><option value="money"' + (rule.unit === 'money' ? ' selected' : '') + '>in money</option></select>';
      if (x.id === 'tradingWindow') ctrl += '<label class="sr" for="rule-v-' + x.id + '">Trading hours</label><input type="text" class="inline-input" style="width:10.5em" id="rule-v-' + x.id + '" data-role="rule-value" data-rule="' + x.id + '" value="' + esc(rule.value || '') + '" placeholder="09:35-15:45">' + (rule.on && !M.tradingWindow(rule.value) ? ' <span class="flag-breach">Write it like 09:35-15:45</span>' : '');
      if (x.id === 'coolOff') ctrl += '<label class="sr" for="rule-v-' + x.id + '">Losing trades in a row before stopping</label><input type="text" inputmode="numeric" class="inline-input" id="rule-v-' + x.id + '" data-role="rule-value" data-rule="' + x.id + '" value="' + esc(rule.value || '') + '"> <span>losses in a row</span>';
      if (x.id === 'maxTradesPerDay') ctrl += '<label class="sr" for="rule-v-' + x.id + '">Maximum trades per day</label><input type="text" inputmode="numeric" class="inline-input" id="rule-v-' + x.id + '" data-role="rule-value" data-rule="' + x.id + '" value="' + esc(rule.value || '') + '"> <span>trades</span>';
      if (x.id === 'maxLossR') ctrl += '<label class="sr" for="rule-v-' + x.id + '">Largest loss in R</label><input type="text" inputmode="decimal" class="inline-input" id="rule-v-' + x.id + '" data-role="rule-value" data-rule="' + x.id + '" value="' + esc(rule.value || '') + '"> <span>R</span>';
      var days = x.breaches - x.trades;
      var said = x.id === 'maxDailyLoss' ? M.plural(days, 'day') + ' over the limit, ' + M.plural(x.trades, 'trade') + ' opened after it was hit' :
        x.id === 'maxDrawdown' ? M.plural(x.breaches, 'time') + ' past the limit' : x.breaches + (x.breaches === 1 ? ' breach' : ' breaches') + (x.breaches !== x.trades ? ' on ' + M.plural(x.trades, 'trade') : '');
      var count = rule.on ? (x.breaches ? '<span class="flag-breach">' + esc(said) + '</span>' : '<span class="gain">No breaches.</span>') + (x.unchecked ? ' <span class="muted">' + x.unchecked + ' not checked (' + (x.id === 'maxDailyLoss' ? 'days with no starting balance' : x.id === 'maxDrawdown' ? 'accounts with no starting balance' : x.id === 'tradingWindow' ? 'no time of day in the export' : 'no stop, planned risk or starting balance') + ').</span>' : '') : '<span class="muted">Off.</span>';
      html += '<li class="rule-item"><span class="rule-name">' + esc(x.label) + '</span><span class="rule-ctrl">' + ctrl + '</span><span class="rule-desc">' + esc(RULE_TEXT[x.id]) + '</span><span class="rule-count">' + count + '</span></li>';
    });
    html += '</ul></section>';
    // Position size.
    var sz = S.size || (S.size = sizeDefaults());
    var acc = sz.account ? M.accountSettings(set, sz.account) : null;
    var startC = acc && acc.start ? M.parseCents(acc.start) : null;
    var eq = startC;
    if (eq !== null) res.closed.forEach(function (t) { if (t.account === sz.account) eq += t.net; });
    var mult = sz.symbol ? M.multiplierFor(set, sz.symbol.toUpperCase(), null) : 1;
    var cur = sz.account ? (acc.currency || currencyOf(sz.account)) : base();
    var out = M.positionSize({ equity: eq === null ? sz.equity || '' : M.plainMoney(eq), riskPct: sz.riskPct, entry: sz.entry, stop: sz.stop, mult: String(mult), fee: sz.fee, step: sz.step, allowance: sz.allowance, currency: cur });
    html += '<section class="ticket"><div class="ticket-head"><h2>Position size</h2><span class="mono">before you place the order</span></div>' +
      '<p class="intro">How big a position keeps a stop-out within your risk per trade. The account size is its starting balance plus every closed trade.</p>' +
      '<div class="form-grid">' +
      '<label class="field"><span>Account</span><select id="sz-account" data-role="size" data-key="account">' + res.accounts.map(function (a) { return '<option' + (a === sz.account ? ' selected' : '') + '>' + esc(a) + '</option>'; }).join('') + '<option value=""' + (!sz.account ? ' selected' : '') + '>Another account</option></select></label>' +
      (eq === null ? '<label class="field"><span>Account size</span><input type="text" inputmode="decimal" id="sz-equity" data-role="size" data-key="equity" value="' + esc(sz.equity || '') + '" placeholder="e.g. 100000"><small>' + (sz.account ? 'No starting balance set for this account below.' : '') + '</small></label>' : '<div class="field"><span>Account size now</span><strong class="mono">' + esc(M.money(eq, cur)) + '</strong></div>') +
      '<label class="field"><span>Risk per trade (%)</span><input type="text" inputmode="decimal" id="sz-risk" data-role="size" data-key="riskPct" value="' + esc(sz.riskPct) + '"></label>' +
      '<label class="field"><span>Symbol (for its multiplier)</span><input type="text" id="sz-symbol" data-role="size" data-key="symbol" value="' + esc(sz.symbol) + '" list="symbol-list" placeholder="e.g. LKFZ6"><small>Multiplier ' + esc(String(mult)) + '</small></label>' +
      '<datalist id="symbol-list">' + res.symbols.map(function (s) { return '<option value="' + esc(s.symbol) + '">'; }).join('') + '</datalist>' +
      '<label class="field"><span>Entry price</span><input type="text" inputmode="decimal" id="sz-entry" data-role="size" data-key="entry" value="' + esc(sz.entry) + '" placeholder="41.20"></label>' +
      '<label class="field"><span>Stop price</span><input type="text" inputmode="decimal" id="sz-stop" data-role="size" data-key="stop" value="' + esc(sz.stop) + '" placeholder="40.85"></label>' +
      '<label class="field"><span>Fees per share or contract, round trip</span><input type="text" inputmode="decimal" id="sz-fee" data-role="size" data-key="fee" value="' + esc(sz.fee) + '" placeholder="0.01"></label>' +
      '<label class="field"><span>Size in steps of</span><input type="text" inputmode="decimal" id="sz-step" data-role="size" data-key="step" value="' + esc(sz.step) + '"></label>' +
      '<label class="field"><span>Loss allowed for the rest of today (optional)</span><input type="text" inputmode="decimal" id="sz-allow" data-role="size" data-key="allowance" value="' + esc(sz.allowance) + '" placeholder="e.g. 850"></label>' +
      '</div><div id="size-out">' + sizeOutHtml(out, cur) + '</div></section>';
    html += '</div>';
    // Accounts and currencies.
    var currencies = {};
    res.trades.forEach(function (t) { currencies[t.currency] = true; });
    html += '<div class="grid-2"><section class="sheet"><span class="eyebrow">Accounts</span><h2>Starting balances</h2><p class="intro">The % rules, the drawdown percentage and the Sharpe ratio need each account\'s starting balance, in its own currency.</p>';
    if (res.accounts.length) {
      html += '<div class="table-wrap"><table class="ledger acct-table"><thead><tr><th>Account</th><th class="hide-sm">Currency</th><th>Starting balance</th><th>Long only</th></tr></thead><tbody>' + res.accounts.map(function (a, i) {
        var s = M.accountSettings(set, a);
        return '<tr><td><strong>' + esc(a) + '</strong><span class="show-sm muted">' + esc(s.currency || currencyOf(a)) + '</span></td><td class="hide-sm">' + esc(s.currency || currencyOf(a)) + '</td><td><label class="sr" for="acct-start-' + i + '">Starting balance for ' + esc(a) + '</label><input type="text" inputmode="decimal" class="inline-input" id="acct-start-' + i + '" data-role="acct-start" data-account="' + esc(a) + '" value="' + esc(s.start || '') + '" placeholder="e.g. 100000"></td>' +
          '<td><label class="check"><input type="checkbox" id="acct-long-' + i + '" data-role="acct-long" data-account="' + esc(a) + '"' + (s.longOnly ? ' checked' : '') + '><span class="sr">Long only for ' + esc(a) + '</span></label></td></tr>';
      }).join('') + '</tbody></table></div><p class="hint">Long only: a sale with nothing held closes shares bought before the exports start, instead of opening a short.</p>';
    } else html += '<p class="muted">Accounts appear here once fills are loaded.</p>';
    html += '<h3>Currency</h3><div class="row-fields"><label class="field"><span>Report in</span><select id="base-cur">' + ['USD', 'GBP', 'EUR'].concat(Object.keys(currencies)).filter(function (c, i, a) { return a.indexOf(c) === i; }).map(function (c) { return '<option' + (c === set.base ? ' selected' : '') + '>' + esc(c) + '</option>'; }).join('') + '</select></label>';
    Object.keys(currencies).sort(M.cmp).forEach(function (c, i) {
      if (c === set.base) return;
      var e = (set.fx || []).filter(function (x) { return x.currency === c; })[0];
      html += '<label class="field"><span>1 ' + esc(c) + ' in ' + esc(set.base) + '</span><input type="text" inputmode="decimal" class="inline-input" id="fx-' + i + '" data-role="fx" data-currency="' + esc(c) + '" value="' + esc(e ? e.rate : '') + '" placeholder="rate"></label>';
    });
    html += '</div><p class="hint">One fixed rate per currency, used for totals across accounts. Each trade keeps its own currency on its ticket.</p></section>';
    html += '<section class="sheet"><span class="eyebrow">Tags</span><h2>Setups and mistakes</h2><p class="intro">One per line. Setups are offered as you type on a trade; mistakes appear as tick boxes.</p>' +
      '<div class="grid-2" style="gap:0 14px"><label class="field"><span>Setups</span><textarea id="tags-setups" rows="7">' + esc((set.setups || []).join('\n')) + '</textarea></label>' +
      '<label class="field"><span>Mistakes</span><textarea id="tags-mistakes" rows="7">' + esc((set.mistakes || []).join('\n')) + '</textarea></label></div></section></div>';
    panel.innerHTML = html;
  }
  // Start the calculator from the latest trade with a stop, so it shows a worked answer straight away.
  function sizeDefaults() {
    var res = S.result, rules = S.base.settings.rules;
    var counts = {}, best = '', bestN = -1;
    res.trades.forEach(function (t) { counts[t.account] = (counts[t.account] || 0) + 1; });
    res.accounts.forEach(function (a) { if (counts[a] > bestN) { best = a; bestN = counts[a]; } });
    var last = null;
    res.closed.forEach(function (t) { if (t.stop !== null && t.account === best) last = t; });
    var fee = last && last.qtyIn ? M.plainMoney(M.rnd(last.fees / (last.qtyIn / M.QTY_SCALE))) : '';
    return {
      account: best, riskPct: (rules.maxRiskPct && rules.maxRiskPct.value) || '1', symbol: last ? last.symbol : '',
      entry: last ? M.fmtPrice(last.avgEntry) : '', stop: last ? M.fmtPrice(last.stop) : '', fee: fee === '0.00' ? '' : fee, step: '1', allowance: '', equity: ''
    };
  }
  function currencyOf(account) {
    for (var i = 0; i < S.result.trades.length; i++) if (S.result.trades[i].account === account) return S.result.trades[i].currency;
    return base();
  }
  function sizeOutHtml(out, cur) {
    if (!out.ok) return '<div class="size-out warn" role="status"><p style="margin:0">' + esc(out.msg) + '</p></div>';
    var unit = out.units === 1 ? 'share or contract' : 'shares or contracts';
    return '<div class="size-out" role="status"><div class="big">' + (out.direction === 'long' ? 'Buy ' : 'Sell short ') + esc(M.fmtUnits(out.units)) + '</div><span>' + unit + '</span><ul>' +
      '<li>Loss at the stop, with fees: <strong>' + esc(M.money(out.risk, cur)) + '</strong> (' + esc(M.fmtNum(out.riskPct, 2)) + '% of the account)' + (out.limitedBy === 'allowance' ? ', capped by what is left of today\'s loss limit' : '') + '</li>' +
      '<li>Position value: ' + esc(M.money(out.value, cur)) + ' (' + esc(M.fmtNum(out.valuePct, 1)) + '% of the account)' + (out.valuePct > 100 ? ': more than the account, so it needs leverage' : '') + '</li>' +
      '<li>Targets: ' + out.targets.map(function (x) { return x.r + 'R at ' + esc(M.fmtPrice(x.price, true)); }).join(', ') + '</li></ul></div>';
  }

  /* ---------- view 5: how it works ---------- */

  function renderHow(panel) {
    panel.innerHTML = '<div class="grid-2"><section class="sheet"><span class="eyebrow">What goes in</span><h2>Your fills, as your broker exports them</h2><div class="prose">' +
      '<p>Any CSV, TSV or semicolon-separated export with a header row that names a date (with or without a time), a symbol, a side (Buy, Sell, Sell Short, Buy to Cover, B or S, or a signed quantity), a quantity and a price. Fee, commission, stamp duty and exchange fee columns are added together; currency, account, order ID, fill ID, status, multiplier and open or close columns are used when they are there.</p>' +
      '<ul><li>Dates in ISO, UK or US order (worked out from days over 12, or set by you), with times in 24-hour or AM/PM form.</li><li>Prices with currency signs, thousands separators, brackets for negatives, and prices in pence (a <code>Price (p)</code> column or GBX currency).</li>' +
      '<li>Cancelled, rejected and expired orders, repeated headers, total rows, dividends and transfers are set aside with the reason. Fee rows of their own are attached to the fill from the same order, or the same symbol that day.</li>' +
      '<li>Exports listed newest first are read oldest first.</li></ul>' +
      '<p>The template shows the simplest layout. A saved journal file reopens everything, and adding next week\'s export to it skips fills it already holds (matched by fill ID, or by account, symbol, time, side, quantity and price).</p></div></section>' +
      '<section class="sheet"><span class="eyebrow">How fills become trades</span><h2>Flat to flat, first in, first out</h2><div class="prose">' +
      '<p>A round trip starts when a symbol\'s position in an account leaves zero and ends when it returns there. Adding to the position (scaling in) and partial sales (scaling out) stay inside the same trade. A fill that takes the position through zero closes the trade and opens a new one the other way.</p>' +
      '<p>Inside a trade, each closing fill is matched to the oldest open lot first. That gives the profit of each piece, its holding time and the profit realised on each day, which the daily loss rule uses.</p>' +
      '<div class="diagram" aria-label="Example: buy 300 at 41.27, buy 200 at 41.10, sell 250 at 41.90, sell 250 at 41.60. The first sale is matched to 250 of the first lot; the second sale to the last 50 of the first lot and all 200 of the second.">' + fifoSvg() + '</div>' +
      '</div></section></div>' +
      '<div class="grid-2"><section class="sheet"><span class="eyebrow">The figures</span><h2>What each number means</h2><div class="prose"><dl>' +
      '<dt>Net after fees</dt><dd>Price change times quantity times the contract multiplier, less every fee on the trade\'s fills.</dd>' +
      '<dt>Win rate</dt><dd>Winning closed trades over all closed trades. A trade that nets exactly zero is flat.</dd>' +
      '<dt>Expectancy</dt><dd>Net after fees divided by closed trades: what an average trade has made.</dd>' +
      '<dt>Profit factor</dt><dd>Money made by winners divided by money lost by losers. Above 1 the trades made money.</dd>' +
      '<dt>R multiple</dt><dd>A trade\'s net over its planned risk: the loss at the stop when the first order filled, or the planned risk you type in.</dd>' +
      '<dt>Most at risk</dt><dd>The largest loss the open lots faced at the stop at any point, which grows when you add.</dd>' +
      '<dt>Largest drop</dt><dd>The deepest fall of the closed-trade running total below its previous high.</dd>' +
      '<dt>Daily Sharpe</dt><dd>The mean of daily net (on days a trade closed) over its standard deviation, as returns on the starting balance, times the square root of 252. Sortino uses only the losing days. Treat both with care over a few weeks.</dd></dl></div></section>' +
      '<section class="sheet"><span class="eyebrow">Limits</span><h2>What it does not do</h2><div class="prose"><ul>' +
      '<li>It describes trades already made. It is not financial advice and does not tell you what to trade.</li>' +
      '<li>Profit is only counted when a position closes; open positions are listed but not valued, as the export has no current price.</li>' +
      '<li>Positions opened before the first export cannot be matched. Their closing fills are listed and left out.</li>' +
      '<li>One fixed exchange rate per currency is used for totals.</li>' +
      '<li>Options are treated like any contract with a multiplier; exercise, assignment and expiry rows are not modelled.</li>' +
      '<li>Times are read as written in the export, with no time zone conversion.</li></ul>' +
      '<p>Everything happens in this page. Files are read by your browser and never leave it; a copy of your journal is kept in this browser\'s storage so you can pick up where you left off, and the journal file you save is yours.</p></div></section></div>';
  }
  function fifoSvg() {
    return '<svg viewBox="0 0 520 232" role="presentation">' +
      '<rect x="10" y="20" width="180" height="34" rx="3" fill="#d8e7f2" stroke="#26307a"/><text x="20" y="42">Buy 300 at 41.27</text>' +
      '<rect x="10" y="66" width="180" height="34" rx="3" fill="#d8e7f2" stroke="#26307a"/><text x="20" y="88">Buy 200 at 41.10</text>' +
      '<rect x="330" y="20" width="180" height="34" rx="3" fill="#f6d3cd" stroke="#b3301d"/><text x="340" y="42">Sell 250 at 41.90</text>' +
      '<rect x="330" y="66" width="180" height="34" rx="3" fill="#f6d3cd" stroke="#b3301d"/><text x="340" y="88">Sell 250 at 41.60</text>' +
      '<path d="M190 34 L330 34" stroke="#26307a" stroke-width="2" marker-end="url(#arr)"/><text x="204" y="27" style="font-size:11px">250 x 0.63: +157.50</text>' +
      '<path d="M190 46 C250 50 280 72 330 76" fill="none" stroke="#26307a" stroke-width="2" marker-end="url(#arr)"/><text x="196" y="63" style="font-size:11px">50 x 0.33: +16.50</text>' +
      '<path d="M190 88 L330 88" stroke="#26307a" stroke-width="2" marker-end="url(#arr)"/><text x="204" y="104" style="font-size:11px">200 x 0.50: +100.00</text>' +
      '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 Z" fill="#26307a"/></marker></defs>' +
      '<line x1="10" y1="132" x2="510" y2="132" stroke="#b9c8e0"/>' +
      '<text x="10" y="156">One trade: flat, long 300, long 500, long 250, flat.</text>' +
      '<text x="10" y="178">Before fees +274.00. Two entries, two exits.</text>' +
      '<text x="10" y="200">Buying more at 41.10, below the 41.27 average,</text><text x="10" y="222">counts as adding to a loser.</text>' +
      '</svg>';
  }

  /* ---------- events ---------- */

  function onClick(e) {
    var el = e.target.closest('button, [data-go]');
    if (!el) return;
    if (el.hasAttribute('data-go')) { show(el.getAttribute('data-go')); if (el.getAttribute('data-go') === 'fills') { var tray = document.getElementById('intray'); if (tray) tray.scrollIntoView({ behavior: 'smooth', block: 'start' }); } return; }
    if (el.hasAttribute('data-trade')) { openTrade(el.getAttribute('data-trade')); return; }
    if (el.hasAttribute('data-select')) {
      var picked = el.getAttribute('data-select');
      S.trades.selected = S.trades.selected === picked && isNarrow() ? null : picked;
      S.dirty.trades = true;
      renderView('trades');
      var row = document.querySelector('[data-select="' + (window.CSS && CSS.escape ? CSS.escape(picked) : picked) + '"]');
      if (row && isNarrow()) row.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    if (el.hasAttribute('data-week')) { S.review.week = +el.getAttribute('data-week'); S.review.all = false; reanalyseLight(); return; }
    if (el.hasAttribute('data-day')) { S.days.day = +el.getAttribute('data-day'); S.dirty.days = true; renderView('days'); var dt = document.getElementById('day-ticket'); if (dt) dt.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
    if (el.hasAttribute('data-breakdown')) { S.breakdown = el.getAttribute('data-breakdown'); S.dirty.review = true; renderView('review'); return; }
    var action = el.getAttribute('data-action');
    if (!action) return;
    var list;
    switch (action) {
      case 'pick': document.getElementById('file-exports').click(); break;
      case 'open': document.getElementById('file-journal').click(); break;
      case 'save': download('round-trips-journal-' + todayIso() + '.json', M.projectFile(S.state, todayIso()), 'application/json'); break;
      case 'template': download('round-trips-template.csv', M.templateCsv()); break;
      case 'trades-csv': download('round-trips-' + todayIso() + '.csv', M.tradesCsv(S.result)); break;
      case 'breaches-csv': download('rule-breaches-' + todayIso() + '.csv', M.breachesCsv(S.result)); break;
      case 'fills-csv': download('fills-matched-' + todayIso() + '.csv', M.fillsCsv(S.result)); break;
      case 'days-csv': download('days-' + todayIso() + '.csv', M.daysCsv(S.result, S.days.account)); break;
      case 'fills-more': S.fills.limit += 200; S.dirty.fills = true; renderView('fills'); break;
      case 'trades-more': S.trades.limit += 120; S.dirty.trades = true; renderView('trades'); break;
      case 'paste':
        var text = document.getElementById('paste-text').value;
        if (!text.trim()) { toast('Paste the exported text first'); break; }
        addFiles([{ name: 'Pasted text ' + (S.files.length + 1), text: text, account: document.getElementById('paste-account').value.trim() || 'Pasted' }]);
        break;
      case 'remove-file':
        S.files.splice(+el.getAttribute('data-file'), 1);
        reimport();
        toast('Removed the export');
        break;
      case 'sample': S.opened = null; loadSample(); show('review'); toast('Showing the invented sample again'); break;
      case 'clear':
        if (!S.sample && el.getAttribute('data-armed') !== '1') {
          el.setAttribute('data-armed', '1');
          var was = el.textContent;
          el.textContent = 'Click again to clear everything';
          toast('This clears the journal and the copy in this browser. Save the journal file first if you want to keep it.');
          setTimeout(function () { el.removeAttribute('data-armed'); el.textContent = was; }, 5000);
          break;
        }
        startFresh(); storeDel(STORE_KEY); reimport(); show('fills'); toast('Cleared: add your fills export to start'); break;
      case 'resume': var saved = S.resume; S.resume = null; openJournal(saved.journal, 'your saved journal'); break;
      case 'forget': S.resume = null; storeDel(STORE_KEY); renderNotice(); break;
      case 'carry-add':
        var ci = +el.getAttribute('data-index');
        var made = M.makeCarry(S.result.unmatched[ci], document.getElementById('carry-date-' + ci).value, document.getElementById('carry-price-' + ci).value);
        if (!made.ok) { toast(made.msg); break; }
        S.base.carry = (S.base.carry || []).concat([made.carry]);
        reimport();
        toast('Added the opening: the close now counts as a trade');
        break;
      case 'carry-remove':
        S.base.carry = S.base.carry.filter(function (c, k) { return k !== +el.getAttribute('data-index'); });
        reimport();
        break;
      case 'mult-add':
        var key = document.getElementById('mult-new-key').value.trim().toUpperCase(), val = document.getElementById('mult-new-value').value.trim();
        if (!key || !(M.parseFloatText(val) > 0)) { toast('Enter a root or symbol and a multiplier above zero'); break; }
        setMultiplier(key, val);
        break;
      case 'prev-trade': case 'next-trade':
        list = tradeFilter();
        var i = list.map(function (t) { return t.id; }).indexOf(S.trades.selected);
        var j = action === 'prev-trade' ? i - 1 : i + 1;
        if (j >= 0 && j < list.length) { S.trades.selected = list[j].id; S.dirty.trades = true; renderView('trades'); focusTicket(); }
        break;
      case 'next-needs':
        list = tradeFilter().filter(function (t) { return t.status === 'closed' && (!t.setup || t.plannedRisk === null); });
        if (!list.length) list = S.result.trades.filter(function (t) { return t.status === 'closed' && (!t.setup || t.plannedRisk === null); }).sort(function (a, b) { return b.openT - a.openT; });
        var nxt = list.filter(function (t) { return t.id !== S.trades.selected; })[0];
        if (nxt) { S.trades.selected = nxt.id; S.dirty.trades = true; renderView('trades'); focusTicket(); } else toast('Every closed trade has a setup and a stop or planned risk');
        break;
      case 'write-new':
        S.trades.account = ''; S.trades.week = ''; S.trades.setup = ''; S.trades.outcome = ''; S.trades.q = ''; S.trades.needs = true; S.trades.fresh = true; S.trades.selected = null;
        S.dirty.trades = true;
        show('trades');
        break;
      case 'review-latest':
        S.review.all = false; S.review.week = null;
        reanalyse();
        show('review');
        break;
      case 'chat-short': case 'chat-full':
        S.chat = action === 'chat-short' ? 'short' : 'full';
        S.dirty.review = true;
        renderView('review');
        break;
      case 'copy-review': copyText(document.getElementById('review-text').value, document.getElementById('review-text')); break;
      case 'review-txt': download('weekly-review-' + M.toIso(S.review.week) + '.txt', document.getElementById('review-text').value, 'text/plain;charset=utf-8'); break;
      case 'print-review':
        document.body.classList.add('print-review');
        window.print();
        setTimeout(function () { document.body.classList.remove('print-review'); }, 500);
        break;
    }
  }
  function focusTicket() { var el = document.getElementById('j-setup'); if (el) el.focus({ preventScroll: false }); }

  function openTrade(id) {
    var t = tradeById(id);
    if (!t) return;
    S.trades.selected = id;
    // Make sure the filters let the trade show.
    var f = S.trades;
    if ((f.account && f.account !== t.account) || f.week || f.setup || f.outcome || f.needs || f.fresh || f.q) { f.account = ''; f.week = ''; f.setup = ''; f.outcome = ''; f.needs = false; f.fresh = false; f.q = ''; }
    S.dirty.trades = true;
    show('trades');
    var row = document.querySelector('[data-select="' + (window.CSS && CSS.escape ? CSS.escape(id) : id) + '"]');
    if (row) row.scrollIntoView({ block: 'nearest' });
    var tk = document.getElementById('trade-ticket');
    if (tk) tk.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function reanalyseLight() { VIEWS.forEach(function (v) { S.dirty[v] = true; }); renderAll(); }

  function setMultiplier(key, value) {
    var list = (S.base.settings.multipliers || []).filter(function (e) { return e.symbol !== key; });
    if (String(value).trim()) list.push({ symbol: key, value: String(value).trim() });
    list.sort(function (a, b) { return M.cmp(a.symbol, b.symbol); });
    S.base.settings.multipliers = list;
    reanalyse();
  }
  function setAccount(name, field, value) {
    var list = (S.base.settings.accounts || []).slice();
    var e = null;
    list.forEach(function (a) { if (a.name === name) e = a; });
    if (!e) { e = { name: name, start: '', currency: currencyOf(name), longOnly: false }; list.push(e); }
    e[field] = value;
    S.base.settings.accounts = list;
  }

  function onChange(e) {
    var el = e.target;
    var role = el.getAttribute('data-role');
    var id = el.id;
    if (id === 'file-exports') { readFiles(el.files); el.value = ''; return; }
    if (id === 'file-journal') {
      var file = el.files && el.files[0];
      if (file) { var reader = new FileReader(); reader.onload = function () { openJournal(String(reader.result), file.name); }; reader.readAsText(file); }
      el.value = '';
      return;
    }
    if (id === 'date-order') { S.base.settings.dateOrder = el.value; reimport(); toast('Re-read the exports'); return; }
    if (role === 'file-account') {
      var named = S.files[+el.getAttribute('data-file')];
      named.account = el.value.trim();
      // Remember the name for this kind of file, so next week's export joins the same account.
      var from = M.cleanAccountName(named.name);
      var renames = (S.base.settings.renames || []).filter(function (x) { return x.from !== from; });
      if (named.account && named.account !== from) renames.push({ from: from, to: named.account });
      S.base.settings.renames = renames;
      reimport();
      return;
    }
    if (role === 'file-column') {
      var target = S.files[+el.getAttribute('data-file')];
      var cols = {};
      Object.keys(target.columns || {}).forEach(function (k) { cols[k] = target.columns[k]; });
      if (el.value === '__auto') delete cols[el.getAttribute('data-field')]; else cols[el.getAttribute('data-field')] = el.value;
      target.columns = cols;
      reimport();
      return;
    }
    if (role === 'mult') { setMultiplier(el.getAttribute('data-key'), el.value); return; }
    if (id === 'days-account') { S.days.account = el.value; S.days.day = null; S.dirty.days = true; renderView('days'); return; }
    if (id === 'fills-account') { S.fills.account = el.value; S.fills.symbol = ''; S.dirty.fills = true; renderView('fills'); return; }
    if (id === 'fills-symbol') { S.fills.symbol = el.value; S.dirty.fills = true; renderView('fills'); return; }
    if (id === 'tr-account' || id === 'tr-week' || id === 'tr-setup' || id === 'tr-outcome' || id === 'tr-needs' || id === 'tr-fresh') {
      var key = id.slice(3);
      S.trades[key] = el.type === 'checkbox' ? el.checked : el.value;
      S.trades.selected = null;
      S.trades.limit = 80;
      S.dirty.trades = true;
      renderView('trades');
      return;
    }
    if (role === 'journal' || role === 'journal-mistake') { saveJournalFromTicket(true); return; }
    if (role === 'journal-notes') { saveJournalFromTicket(true); return; }
    if (id === 'rv-week') {
      if (el.value === 'all') S.review.all = true; else { S.review.all = false; S.review.week = +el.value; }
      reanalyseLight();
      return;
    }
    if (id === 'rv-account') { S.review.account = el.value; var w = closedWeeks(); if (w.indexOf(S.review.week) < 0) S.review.week = w.length ? w[w.length - 1] : null; reanalyseLight(); return; }
    if (role === 'rule-on' || role === 'rule-value' || role === 'rule-unit') {
      var rid = el.getAttribute('data-rule');
      var rules = S.base.settings.rules;
      rules[rid] = rules[rid] || { on: false };
      if (role === 'rule-on') rules[rid].on = el.checked;
      if (role === 'rule-value') rules[rid].value = el.value.trim();
      if (role === 'rule-unit') rules[rid].unit = el.value;
      reanalyse();
      return;
    }
    if (role === 'acct-start') { setAccount(el.getAttribute('data-account'), 'start', el.value.trim()); reanalyse(); return; }
    if (role === 'acct-long') { setAccount(el.getAttribute('data-account'), 'longOnly', el.checked); reanalyse(); return; }
    if (id === 'base-cur') { S.base.settings.base = el.value; reanalyse(); return; }
    if (role === 'fx') {
      var c = el.getAttribute('data-currency');
      var fx = (S.base.settings.fx || []).filter(function (x) { return x.currency !== c; });
      if (el.value.trim()) fx.push({ currency: c, rate: el.value.trim() });
      S.base.settings.fx = fx;
      reanalyse();
      return;
    }
    if (id === 'tags-setups' || id === 'tags-mistakes') {
      var lines = el.value.split(/\r?\n/).map(function (x) { return x.trim(); }).filter(function (x, i, a) { return x && a.indexOf(x) === i; });
      S.base.settings[id === 'tags-setups' ? 'setups' : 'mistakes'] = lines;
      S.dirty.trades = true;
      autosave();
      return;
    }
    if (role === 'size') { sizeInput(el); return; }
  }

  function sizeInput(el) {
    S.size[el.getAttribute('data-key')] = el.value;
    if (el.getAttribute('data-key') === 'account') { S.dirty.rules = true; renderView('rules'); return; }
    S.dirty.rules = true;
    renderView('rules');
  }

  var inputTimer = null;
  function onInput(e) {
    var el = e.target;
    if (el.id === 'tr-q') {
      clearTimeout(inputTimer);
      inputTimer = setTimeout(function () { S.trades.q = el.value; S.trades.selected = null; S.dirty.trades = true; renderView('trades'); }, 250);
      return;
    }
    if (el.getAttribute('data-role') === 'journal-notes') {
      clearTimeout(inputTimer);
      inputTimer = setTimeout(function () { saveJournalFromTicket(false); }, 500);
      return;
    }
    if (el.getAttribute('data-role') === 'size' && el.tagName === 'INPUT') {
      clearTimeout(inputTimer);
      inputTimer = setTimeout(function () {
        S.size[el.getAttribute('data-key')] = el.value;
        var res = S.result, set = S.base.settings, sz = S.size;
        var acc = sz.account ? M.accountSettings(set, sz.account) : null;
        var eq = acc && acc.start ? M.parseCents(acc.start) : null;
        if (eq !== null) res.closed.forEach(function (t) { if (t.account === sz.account) eq += t.net; });
        var mult = sz.symbol ? M.multiplierFor(set, sz.symbol.toUpperCase(), null) : 1;
        var cur = sz.account ? (acc.currency || currencyOf(sz.account)) : base();
        var out = M.positionSize({ equity: eq === null ? sz.equity || '' : M.plainMoney(eq), riskPct: sz.riskPct, entry: sz.entry, stop: sz.stop, mult: String(mult), fee: sz.fee, step: sz.step, allowance: sz.allowance, currency: cur });
        document.getElementById('size-out').innerHTML = sizeOutHtml(out, cur);
      }, 200);
    }
  }

  function onTabKey(e) {
    var tab = e.target.closest('[role="tab"]');
    if (!tab) return;
    var i = VIEWS.indexOf(tab.id.slice(4)), j = -1;
    if (e.key === 'ArrowRight') j = (i + 1) % VIEWS.length;
    else if (e.key === 'ArrowLeft') j = (i + VIEWS.length - 1) % VIEWS.length;
    else if (e.key === 'Home') j = 0;
    else if (e.key === 'End') j = VIEWS.length - 1;
    if (j >= 0) { e.preventDefault(); show(VIEWS[j], true); }
  }

  function initDrop() {
    var depth = 0;
    document.addEventListener('dragenter', function (e) { if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') < 0) return; depth++; var t = document.getElementById('intray'); if (t) t.classList.add('drag'); });
    document.addEventListener('dragleave', function () { depth = Math.max(0, depth - 1); if (!depth) { var t = document.getElementById('intray'); if (t) t.classList.remove('drag'); } });
    document.addEventListener('dragover', function (e) { if (e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') >= 0) e.preventDefault(); });
    document.addEventListener('drop', function (e) {
      if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
      e.preventDefault();
      depth = 0;
      var t = document.getElementById('intray');
      if (t) t.classList.remove('drag');
      var files = Array.prototype.slice.call(e.dataTransfer.files);
      var journal = files.filter(function (f) { return /\.json$/i.test(f.name); })[0];
      if (journal) {
        var reader = new FileReader();
        reader.onload = function () { if (openJournal(String(reader.result), journal.name)) readFiles(files.filter(function (f) { return f !== journal; })); };
        reader.readAsText(journal);
      } else readFiles(files);
    });
  }

  function init() {
    document.addEventListener('click', onClick);
    document.addEventListener('change', onChange);
    document.addEventListener('input', onInput);
    $('.tabs').addEventListener('keydown', onTabKey);
    $$('[role="tab"]').forEach(function (tab) { tab.addEventListener('click', function () { show(tab.id.slice(4)); }); });
    document.getElementById('hero-open').addEventListener('click', function () { document.getElementById('file-journal').click(); });
    initDrop();
    var resizeTimer = null;
    window.addEventListener('resize', function () { clearTimeout(resizeTimer); resizeTimer = setTimeout(function () {
        if (S.view === 'review') drawEquity();
        if (S.view === 'days') drawDayChart();
        var narrow = isNarrow();
        if (narrow !== S.narrow) { S.narrow = narrow; S.dirty.trades = true; if (S.view === 'trades') renderView('trades'); }
      }, 150); });
    window.addEventListener('afterprint', function () { document.body.classList.remove('print-review'); });
    var saved = storeGet(STORE_KEY);
    if (saved) { try { S.resume = JSON.parse(saved); if (!S.resume || !S.resume.journal) S.resume = null; } catch (e) { S.resume = null; } }
    S.narrow = isNarrow();
    loadSample();
    show('review');
  }

  init();
})();
