/* MODEL START */
/*
 * Still paying? model: reads bank exports, finds regular payments, forecasts
 * when they will next leave and builds the files the app hands back.
 * Money is held in whole pence and dates as day numbers (days since
 * 1 January 1970) so the browser app and the Python companion agree exactly.
 */
(function (root) {
  'use strict';

  var VERSION = '1.0';
  var MS_DAY = 86400000;

  /* ------------------------------------------------------------------ */
  /* Dates                                                               */
  /* ------------------------------------------------------------------ */

  function dayFromYMD(y, m, d) { return Math.floor(Date.UTC(y, m - 1, d) / MS_DAY); }
  function ymd(day) {
    var dt = new Date(day * MS_DAY);
    return { y: dt.getUTCFullYear(), m: dt.getUTCMonth() + 1, d: dt.getUTCDate() };
  }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function iso(day) { var p = ymd(day); return p.y + '-' + pad2(p.m) + '-' + pad2(p.d); }
  function fromIso(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s || ''));
    if (!m) return null;
    return validDay(+m[1], +m[2], +m[3]);
  }
  /** 0 = Sunday ... 6 = Saturday */
  function weekday(day) { return ((day + 4) % 7 + 7) % 7; }
  function daysInMonth(y, m) { return new Date(Date.UTC(y, m, 0)).getUTCDate(); }
  function validDay(y, m, d) {
    if (!(y >= 1900 && y <= 2200) || !(m >= 1 && m <= 12) || !(d >= 1 && d <= daysInMonth(y, m))) return null;
    return dayFromYMD(y, m, d);
  }
  /**
   * The nominal due day in a month. An anchor is a day of the month (31 means
   * the last day) or a rule: 'LW' for the last working day, or 'L1' to 'L5'
   * for the last Monday to Friday of the month (moved back a working day if
   * that is a bank holiday), the way many payrolls run.
   */
  function nominalInMonth(y, m, anchor) {
    if (typeof anchor === 'string') {
      var d = dayFromYMD(y, m, daysInMonth(y, m));
      if (anchor === 'LW') { while (!isWorkingDay(d)) d--; return d; }
      var wd = +anchor.slice(1);
      while (weekday(d) !== wd) d--;
      while (!isWorkingDay(d)) d--;
      return d;
    }
    return dayFromYMD(y, m, Math.min(anchor, daysInMonth(y, m)));
  }
  /** Move a day forward by whole months, landing on the nominal day of the month (clamped). */
  function addMonths(day, months, anchor) {
    var p = ymd(day);
    var total = p.y * 12 + (p.m - 1) + months;
    var y = Math.floor(total / 12), m = total % 12 + 1;
    return nominalInMonth(y, m, anchor || p.d);
  }
  var MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
  var MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  var DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  function shortDate(day) { var p = ymd(day); return p.d + ' ' + MONTH_NAMES[p.m - 1].slice(0, 3); }
  function longDate(day) { var p = ymd(day); return p.d + ' ' + MONTH_NAMES[p.m - 1].slice(0, 3) + ' ' + p.y; }
  function ordinal(n) {
    var s = n % 100;
    if (s >= 11 && s <= 13) return n + 'th';
    return n + (['th', 'st', 'nd', 'rd'][n % 10] || 'th');
  }

  /* England and Wales bank holidays, including the one-off changes since 2012. */
  var HOLIDAY_MOVES = {
    2012: { remove: ['2012-05-28'], add: ['2012-06-04', '2012-06-05'] },
    2020: { remove: ['2020-05-04'], add: ['2020-05-08'] },
    2022: { remove: ['2022-05-30'], add: ['2022-06-02', '2022-06-03', '2022-09-19'] },
    2023: { remove: [], add: ['2023-05-08'] }
  };
  function easterSunday(y) {
    var a = y % 19, b = Math.floor(y / 100), c = y % 100, d = Math.floor(b / 4), e = b % 4;
    var f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3);
    var h = (19 * a + b - d - g + 15) % 30, i = Math.floor(c / 4), k = c % 4;
    var l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451);
    var month = Math.floor((h + l - 7 * m + 114) / 31), dd = ((h + l - 7 * m + 114) % 31) + 1;
    return dayFromYMD(y, month, dd);
  }
  function firstMonday(y, m) { var d = dayFromYMD(y, m, 1); while (weekday(d) !== 1) d++; return d; }
  function lastMonday(y, m) { var d = dayFromYMD(y, m, daysInMonth(y, m)); while (weekday(d) !== 1) d--; return d; }
  var holidayCache = {};
  function bankHolidays(y) {
    if (holidayCache[y]) return holidayCache[y];
    var list = [];
    var ny = dayFromYMD(y, 1, 1);
    if (weekday(ny) === 6) ny += 2; else if (weekday(ny) === 0) ny += 1;
    list.push(ny);
    var easter = easterSunday(y);
    list.push(easter - 2, easter + 1);
    list.push(firstMonday(y, 5), lastMonday(y, 5), lastMonday(y, 8));
    var xmas = dayFromYMD(y, 12, 25), wd = weekday(xmas);
    if (wd === 6) list.push(xmas + 2, xmas + 3);
    else if (wd === 0) list.push(xmas + 1, xmas + 2);
    else if (wd === 5) list.push(xmas, xmas + 3);
    else list.push(xmas, xmas + 1);
    var moves = HOLIDAY_MOVES[y];
    if (moves) {
      list = list.filter(function (d) { return moves.remove.indexOf(iso(d)) < 0; });
      moves.add.forEach(function (s) { list.push(fromIso(s)); });
    }
    list.sort(function (a, b) { return a - b; });
    holidayCache[y] = list;
    return list;
  }
  function isWorkingDay(day) {
    var wd = weekday(day);
    if (wd === 0 || wd === 6) return false;
    return bankHolidays(ymd(day).y).indexOf(day) < 0;
  }
  function nextWorkingDay(day) { while (!isWorkingDay(day)) day++; return day; }

  /* ------------------------------------------------------------------ */
  /* Money                                                               */
  /* ------------------------------------------------------------------ */

  function roundHalfUp(x) { return Math.floor(x + 0.5); }
  /** Plain code-point order, so sorting is the same in every browser and in Python. */
  function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
  function money(pence, opts) {
    opts = opts || {};
    var neg = pence < 0, p = Math.abs(pence);
    var pounds = Math.floor(p / 100), rest = p % 100;
    var s = String(pounds).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    var out = '\u00a3' + s + (opts.whole && rest === 0 ? '' : '.' + pad2(rest));
    return (neg ? '-' : '') + out;
  }
  function plainMoney(pence) {
    var neg = pence < 0, p = Math.abs(pence);
    return (neg ? '-' : '') + Math.floor(p / 100) + '.' + pad2(p % 100);
  }

  /**
   * Read an amount as whole pence. Copes with currency symbols, thousands
   * separators, brackets or a trailing minus for money out, DR and CR markers
   * and comma decimals. Returns null when the text is not an amount.
   */
  function parseAmount(raw) {
    if (raw === null || raw === undefined) return null;
    var t = String(raw).trim();
    if (!t) return null;
    var neg = false;
    t = t.replace(/\u2212/g, '-').replace(/\u00a0/g, ' ');
    if (/^\(.*\)$/.test(t)) { neg = true; t = t.slice(1, -1).trim(); }
    var m = /^(.*?)\s*\b(DR|CR|D|C)\.?$/i.exec(t);
    if (m && /\d/.test(m[1])) { if (/^d/i.test(m[2])) neg = !neg; t = m[1].trim(); }
    m = /^(DR|CR)\b\s*(.*)$/i.exec(t);
    if (m && /\d/.test(m[2])) { if (/^d/i.test(m[1])) neg = !neg; t = m[2].trim(); }
    t = t.replace(/(GBP|EUR|USD|\u00a3|\u20ac|\$)/gi, '').replace(/\s+/g, '');
    if (/^-.*-$/.test(t)) return null;
    if (/-$/.test(t)) { neg = !neg; t = t.slice(0, -1); }
    if (/^[+-]/.test(t)) { if (t[0] === '-') neg = !neg; t = t.slice(1); }
    if (/^-?\(.*\)$/.test(t)) { neg = !neg; t = t.replace(/[()]/g, ''); }
    if (!t) return null;
    var intPart, frac;
    if (/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(t) || /^\d+(\.\d+)?$/.test(t)) {
      t = t.replace(/,/g, '');
      var parts = t.split('.');
      intPart = parts[0]; frac = parts[1] || '';
    } else if (/^\d{1,3}(\.\d{3})+,\d{1,2}$/.test(t) || /^\d+,\d{1,2}$/.test(t)) {
      t = t.replace(/\./g, '');
      var p2 = t.split(',');
      intPart = p2[0]; frac = p2[1];
    } else if (/^\.\d+$/.test(t)) {
      intPart = '0'; frac = t.slice(1);
    } else {
      return null;
    }
    var pence = parseInt(intPart, 10) * 100;
    var f = (frac + '000').slice(0, 3);
    pence += parseInt(f.slice(0, 2), 10) + (parseInt(f[2], 10) >= 5 ? 1 : 0);
    if (!isFinite(pence)) return null;
    return neg ? -pence : pence;
  }

  /* ------------------------------------------------------------------ */
  /* Dates in exports                                                    */
  /* ------------------------------------------------------------------ */

  function monthIndex(word) {
    var w = String(word).toLowerCase().slice(0, 3);
    var i = MONTHS.indexOf(w);
    return i < 0 ? 0 : i + 1;
  }
  function fullYear(y) {
    if (y.length === 2) { var n = +y; return n < 70 ? 2000 + n : 1900 + n; }
    return +y;
  }
  /** Classify a date string: returns {kind, a, b, y} or {kind:'ymd'|'text', day} or null. */
  function dateShape(raw) {
    var t = String(raw || '').trim().replace(/^(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+/i, '');
    if (!t) return null;
    var m = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:$|[T\s])/.exec(t);
    if (m) return { kind: 'fixed', day: validDay(+m[1], +m[2], +m[3]) };
    m = /^(\d{4})[\/.](\d{1,2})[\/.](\d{1,2})(?:$|\s)/.exec(t);
    if (m) return { kind: 'fixed', day: validDay(+m[1], +m[2], +m[3]) };
    m = /^(\d{4})(\d{2})(\d{2})(?:\d{6})?(?:\.\d+)?(?:\[.*\])?$/.exec(t);
    if (m) return { kind: 'fixed', day: validDay(+m[1], +m[2], +m[3]) };
    m = /^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2}|\d{4})(?:$|[\sT,])/.exec(t);
    if (m) return { kind: 'pair', a: +m[1], b: +m[2], y: fullYear(m[3]) };
    m = /^(\d{1,2})(?:st|nd|rd|th)?[\s\-\/.]*([A-Za-z]{3,9})\.?[\s\-\/.,]*(\d{2}|\d{4})(?:$|[\sT,])/.exec(t);
    if (m && monthIndex(m[2]) && MONTHS.indexOf(m[2].toLowerCase().slice(0, 3)) >= 0) {
      return { kind: 'fixed', day: validDay(fullYear(m[3]), monthIndex(m[2]), +m[1]) };
    }
    m = /^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?:$|[\sT,])/.exec(t);
    if (m && MONTHS.indexOf(m[1].toLowerCase().slice(0, 3)) >= 0) {
      return { kind: 'fixed', day: validDay(+m[3], monthIndex(m[1]), +m[2]) };
    }
    return null;
  }
  /** Decide whether d/m/y or m/d/y dates are in use. UK order unless the data says otherwise. */
  function detectDateOrder(values) {
    var dmy = 0, mdy = 0, pairs = 0;
    values.forEach(function (v) {
      var s = dateShape(v);
      if (!s || s.kind !== 'pair') return;
      pairs++;
      if (s.a > 12 && s.b <= 12) dmy++;
      else if (s.b > 12 && s.a <= 12) mdy++;
    });
    if (mdy > 0 && dmy === 0) return { order: 'MDY', ambiguous: false, pairs: pairs };
    return { order: 'DMY', ambiguous: pairs > 0 && dmy === 0, conflicting: dmy > 0 && mdy > 0, pairs: pairs };
  }
  function parseDate(raw, order) {
    var s = dateShape(raw);
    if (!s) return null;
    if (s.kind === 'fixed') return s.day;
    if (order === 'MDY') return validDay(s.y, s.a, s.b);
    return validDay(s.y, s.b, s.a);
  }

  /* ------------------------------------------------------------------ */
  /* CSV                                                                 */
  /* ------------------------------------------------------------------ */

  function stripBom(text) { return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text; }

  /** Split delimited text into rows of cells (RFC 4180 quotes, quoted line breaks). */
  function parseDelimited(text, delim) {
    var rows = [], row = [], cell = '', i = 0, inQ = false, n = text.length, lineNo = 1, rowLine = 1;
    var lines = [];
    while (i < n) {
      var ch = text[i];
      if (inQ) {
        if (ch === '"') {
          if (text[i + 1] === '"') { cell += '"'; i += 2; continue; }
          inQ = false; i++; continue;
        }
        if (ch === '\n') lineNo++;
        cell += ch; i++; continue;
      }
      if (ch === '"' && cell.trim() === '') { inQ = true; cell = ''; i++; continue; }
      if (ch === delim) { row.push(cell); cell = ''; i++; continue; }
      if (ch === '\r' || ch === '\n') {
        row.push(cell); rows.push(row); lines.push(rowLine);
        row = []; cell = '';
        if (ch === '\r' && text[i + 1] === '\n') i++;
        i++; lineNo++; rowLine = lineNo; continue;
      }
      cell += ch; i++;
    }
    if (cell !== '' || row.length) { row.push(cell); rows.push(row); lines.push(rowLine); }
    return { rows: rows, lines: lines };
  }
  function sniffDelimiter(text) {
    var sample = text.split(/\r?\n/).filter(function (l) { return l.trim(); }).slice(0, 30);
    var best = ',', bestScore = -1;
    [',', ';', '\t', '|'].forEach(function (d) {
      var counts = sample.map(function (l) {
        var c = 0, q = false;
        for (var i = 0; i < l.length; i++) { if (l[i] === '"') q = !q; else if (!q && l[i] === d) c++; }
        return c;
      }).filter(function (c) { return c > 0; });
      if (!counts.length) return;
      var freq = {};
      counts.forEach(function (c) { freq[c] = (freq[c] || 0) + 1; });
      var mode = 0, modeN = 0;
      Object.keys(freq).forEach(function (k) { if (freq[k] > modeN || (freq[k] === modeN && +k > mode)) { mode = +k; modeN = freq[k]; } });
      var score = modeN * 10 + mode;
      if (score > bestScore) { bestScore = score; best = d; }
    });
    return best;
  }

  /* Column names that banks use, by role. */
  var ROLE_NAMES = {
    date: ['transaction date', 'date', 'posting date', 'posted date', 'completed date', 'started date', 'booking date', 'trans date', 'txn date', 'date of transaction', 'posted', 'transaction time', 'value date', 'created'],
    payee: ['name', 'payee', 'counter party', 'counterparty', 'merchant', 'merchant name', 'description', 'transaction description', 'details', 'transaction details', 'narrative', 'particulars', 'beneficiary', 'party'],
    memo: ['reference', 'memo', 'notes', 'notes and tags', 'note', 'additional details', 'extra details', 'ref'],
    amount: ['amount', 'amount gbp', 'transaction amount', 'value', 'amount in gbp', 'net amount', 'sum', 'billing amount', 'amount gbp gbp'],
    out: ['paid out', 'money out', 'debit', 'debit amount', 'debits', 'withdrawals', 'withdrawal', 'withdrawn', 'payments', 'out', 'spent', 'outgoing', 'outgoings', 'amount out', 'paid out gbp', 'money out gbp'],
    in: ['paid in', 'money in', 'credit', 'credit amount', 'credits', 'deposits', 'deposit', 'receipts', 'in', 'incoming', 'amount in', 'paid in gbp', 'money in gbp'],
    sign: ['debit credit', 'dr cr', 'cr dr', 'credit debit', 'indicator', 'direction', 'transaction direction', 'debit or credit'],
    type: ['type', 'transaction type', 'payment type', 'method', 'tran type', 'payment method', 'transaction code'],
    category: ['category', 'spending category', 'subcategory', 'spending type', 'categories'],
    balance: ['balance', 'running balance', 'balance gbp', 'account balance'],
    currency: ['currency', 'ccy', 'local currency'],
    status: ['state', 'status', 'transaction status']
  };
  var ROLE_LABELS = { date: 'Date', payee: 'Description or payee', memo: 'Reference or notes', amount: 'Amount (signed)', out: 'Money out', in: 'Money in', sign: 'Debit or credit marker', type: 'Payment type', category: 'Category', balance: 'Balance', currency: 'Currency', status: 'Status' };
  function headerKey(h) {
    return String(h || '').toLowerCase().replace(/\u00a3/g, ' gbp ').replace(/#/g, ' ').replace(/[^a-z0-9]+/g, ' ').trim();
  }
  function roleOf(h) {
    var k = headerKey(h);
    if (!k) return null;
    var roles = Object.keys(ROLE_NAMES);
    for (var r = 0; r < roles.length; r++) if (ROLE_NAMES[roles[r]].indexOf(k) >= 0) return roles[r];
    if (/\bdate\b/.test(k) && !/update/.test(k)) return 'date';
    if (/\b(paid out|money out|debit)\b/.test(k)) return 'out';
    if (/\b(paid in|money in|credit)\b/.test(k)) return 'in';
    if (/\bamount\b/.test(k) && !/local|original|foreign/.test(k)) return 'amount';
    if (/\b(description|details|narrative|payee|merchant)\b/.test(k)) return 'payee';
    if (/\b(reference|memo|notes?)\b/.test(k)) return 'memo';
    if (/\bbalance\b/.test(k)) return 'balance';
    if (/\bcategory\b/.test(k)) return 'category';
    if (/\btype\b/.test(k)) return 'type';
    return null;
  }
  /** Map header cells to roles. The earliest synonym in each list wins when two columns compete. */
  function mapHeader(cells) {
    var map = {}, rank = {};
    cells.forEach(function (c, i) {
      var r = roleOf(c);
      if (!r) return;
      var k = headerKey(c), pos = ROLE_NAMES[r].indexOf(k);
      if (pos < 0) pos = 50;
      if (r === 'payee' && map.payee !== undefined) {
        // A second description-like column becomes the memo if there is none.
        if (map.memo === undefined && pos >= rank.payee) { map.memo = i; rank.memo = pos; return; }
      }
      if (map[r] === undefined || pos < rank[r]) {
        if (r === 'payee' && map.payee !== undefined && map.memo === undefined) { map.memo = map.payee; rank.memo = rank.payee; }
        map[r] = i; rank[r] = pos;
      }
    });
    return map;
  }
  function hasAmountRole(map) { return map.amount !== undefined || map.out !== undefined || map.in !== undefined; }

  /** Guess roles for a file with no header row, from what the cells look like. */
  function inferColumns(rows) {
    var sample = rows.filter(function (r) { return r.some(function (c) { return String(c).trim(); }); }).slice(0, 60);
    if (!sample.length) return null;
    var width = 0;
    sample.forEach(function (r) { width = Math.max(width, r.length); });
    var stats = [];
    for (var c = 0; c < width; c++) {
      var dates = 0, nums = 0, filled = 0, textLen = 0, absSum = 0;
      sample.forEach(function (r) {
        var v = String(r[c] === undefined ? '' : r[c]).trim();
        if (!v) return;
        filled++;
        if (dateShape(v)) dates++;
        else {
          var a = parseAmount(v);
          if (a !== null && /\d/.test(v) && !/[a-z]{3,}/i.test(v.replace(/gbp|dr|cr/gi, ''))) { nums++; absSum += Math.abs(a); }
          else textLen += v.length;
        }
      });
      stats.push({ c: c, dates: dates, nums: nums, filled: filled, textLen: textLen, absSum: absSum });
    }
    var map = {};
    var dateCol = stats.filter(function (s) { return s.filled && s.dates / s.filled >= 0.8; })[0];
    if (!dateCol) return null;
    map.date = dateCol.c;
    var numCols = stats.filter(function (s) { return s.c !== map.date && s.filled && s.nums / s.filled >= 0.8; });
    var sparse = stats.filter(function (s) { return s.c !== map.date && s.nums > 0 && s.filled < sample.length * 0.9 && s.nums / Math.max(1, s.filled) >= 0.8; });
    if (sparse.length >= 2) { map.out = sparse[0].c; map['in'] = sparse[1].c; }
    else if (numCols.length >= 1) {
      map.amount = numCols[0].c;
      if (numCols.length >= 2) map.balance = numCols[numCols.length - 1].c;
    } else return null;
    var used = {};
    Object.keys(map).forEach(function (k) { used[map[k]] = 1; });
    var texts = stats.filter(function (s) { return !used[s.c] && s.textLen > 0; }).sort(function (a, b) { return b.textLen - a.textLen || a.c - b.c; });
    if (!texts.length) return null;
    map.payee = texts[0].c;
    return map;
  }

  var TOTAL_LINE = /^(total|totals|sub ?total|opening balance|closing balance|balance brought forward|balance carried forward|brought forward|carried forward|start balance|end balance)\b/i;
  var SKIP_STATUS = /^(declined|reverted|reversed|failed|cancelled|canceled|void|rejected)$/i;

  /**
   * Read one export. Returns the transactions it could read, the rows it
   * skipped with reasons, and a description of the layout it found.
   * options: {account, dateOrder:'DMY'|'MDY', signConvention:'auto'|'negative-out'|'positive-out', mapping:{role:index}}
   */
  function parseCsv(text, name, options) {
    options = options || {};
    text = stripBom(String(text || ''));
    var result = { name: name || 'statement', format: 'csv', account: options.account || defaultAccount(name), transactions: [], skipped: [], warnings: [], layout: null, ok: false, rowCount: 0, blankRows: 0 };
    if (!text.trim()) { result.error = 'The file is empty.'; return result; }
    if (/^\s*[{\[]/.test(text)) { result.error = 'This looks like a JSON file, not a bank statement. To reopen a saved review, use Open a saved review.'; return result; }
    if (/^\s*%PDF/.test(text)) { result.error = 'This is a PDF. Download your statement as CSV from your banking app or website instead.'; return result; }
    if (/^PK/.test(text) || /[\u0000-\u0008]/.test(text.slice(0, 2000))) { result.error = 'This looks like a spreadsheet or other binary file. Save it as CSV first (File, Save as, CSV).'; return result; }
    var delim = options.delimiter || sniffDelimiter(text);
    var parsed = parseDelimited(text, delim);
    var rows = parsed.rows, lines = parsed.lines;
    var headerIdx = -1, map = null;
    if (options.mapping && options.headerRow !== undefined) {
      headerIdx = options.headerRow; map = options.mapping;
    } else {
      for (var i = 0; i < Math.min(rows.length, 40); i++) {
        var m = mapHeader(rows[i]);
        if (m.date !== undefined && hasAmountRole(m) && (m.payee !== undefined || m.memo !== undefined)) { headerIdx = i; map = m; break; }
      }
      if (options.mapping) map = options.mapping;
    }
    var headers = headerIdx >= 0 ? rows[headerIdx].map(function (h) { return String(h).trim(); }) : null;
    if (!map) {
      map = inferColumns(rows);
      if (map) result.warnings.push('No header row was found, so the columns were worked out from what they contain. Check the column choices below.');
    }
    if (!map || map.date === undefined || !hasAmountRole(map)) {
      result.error = 'Could not find a date column and an amount column. Choose the columns by hand, or download the template to see the layout that always works.';
      result.headers = headers || (rows[0] || []).map(function (h, i) { return 'Column ' + (i + 1); });
      result.preview = rows.slice(0, 6);
      result.delimiter = delim;
      return result;
    }
    if (map.payee === undefined && map.memo !== undefined) { map.payee = map.memo; delete map.memo; }
    var body = rows.slice(headerIdx + 1), bodyLines = lines.slice(headerIdx + 1);
    var order = options.dateOrder || null;
    var dateInfo = detectDateOrder(body.map(function (r) { return r[map.date]; }));
    if (!order) order = dateInfo.order;
    var raw = [];
    var currencies = {};
    body.forEach(function (r, k) {
      var line = bodyLines[k];
      var cells = r.map(function (c) { return String(c === undefined ? '' : c); });
      if (!cells.some(function (c) { return c.trim(); })) { result.blankRows++; return; }
      result.rowCount++;
      var get = function (role) { return map[role] === undefined ? '' : String(cells[map[role]] === undefined ? '' : cells[map[role]]).trim(); };
      var rawLine = cells.join(delim === '\t' ? ' | ' : delim).slice(0, 160);
      var desc = get('payee').replace(/\s+/g, ' ');
      var memo = get('memo').replace(/\s+/g, ' ');
      var dateText = get('date');
      if (headers && cells.join('|').trim() === headers.join('|').trim()) { result.skipped.push({ line: line, reason: 'A repeated header row', raw: rawLine }); return; }
      if (!dateText) {
        if (TOTAL_LINE.test(desc) || TOTAL_LINE.test(cells.join(' ').trim())) result.skipped.push({ line: line, reason: 'A total or balance line, not a payment', raw: rawLine });
        else result.skipped.push({ line: line, reason: 'No date in this row', raw: rawLine });
        return;
      }
      var day = parseDate(dateText, order);
      if (day === null) { result.skipped.push({ line: line, reason: 'Could not read the date "' + dateText.slice(0, 30) + '"', raw: rawLine }); return; }
      if (TOTAL_LINE.test(desc)) { result.skipped.push({ line: line, reason: 'A total or balance line, not a payment', raw: rawLine }); return; }
      var status = get('status');
      if (status && SKIP_STATUS.test(status)) { result.skipped.push({ line: line, reason: 'Marked ' + status.toLowerCase() + ', so no money left the account', raw: rawLine }); return; }
      if (status && /^pending$/i.test(status)) { result.skipped.push({ line: line, reason: 'Still pending, so it may change or drop off', raw: rawLine }); return; }
      var amount = null, amountSource = '';
      if (map.amount !== undefined) {
        var at = get('amount');
        amount = parseAmount(at);
        amountSource = at;
        if (amount !== null && map.sign !== undefined) {
          var sg = get('sign').toLowerCase();
          if (/^(d|dr|debit|out|money out|paid out|withdrawal)/.test(sg)) amount = -Math.abs(amount);
          else if (/^(c|cr|credit|in|money in|paid in|deposit)/.test(sg)) amount = Math.abs(amount);
        }
      } else {
        var ot = get('out'), it = get('in');
        var o = parseAmount(ot), n2 = parseAmount(it);
        amountSource = ot || it;
        if (ot && o === null) { result.skipped.push({ line: line, reason: 'Could not read the amount "' + ot.slice(0, 20) + '"', raw: rawLine }); return; }
        if (it && n2 === null) { result.skipped.push({ line: line, reason: 'Could not read the amount "' + it.slice(0, 20) + '"', raw: rawLine }); return; }
        if (o !== null && o !== 0) amount = -Math.abs(o);
        else if (n2 !== null && n2 !== 0) amount = Math.abs(n2);
        else if (o === 0 || n2 === 0) amount = 0;
      }
      if (amount === null) {
        if (amountSource) result.skipped.push({ line: line, reason: 'Could not read the amount "' + amountSource.slice(0, 20) + '"', raw: rawLine });
        else result.skipped.push({ line: line, reason: 'No amount in this row', raw: rawLine });
        return;
      }
      if (amount === 0) { result.skipped.push({ line: line, reason: 'A zero amount, so nothing was paid', raw: rawLine }); return; }
      var cur = get('currency').toUpperCase();
      if (cur) currencies[cur] = (currencies[cur] || 0) + 1;
      if (!desc && !memo) desc = '(no description)';
      raw.push({ day: day, amount: amount, desc: desc || memo, memo: desc ? memo : '', type: get('type'), category: get('category'), line: line });
    });
    var signMode = options.signConvention || 'auto';
    var flipped = false;
    if (map.amount !== undefined && map.sign === undefined && raw.length) {
      var pos = raw.filter(function (t) { return t.amount > 0; }).length;
      if (signMode === 'positive-out' || (signMode === 'auto' && raw.length >= 5 && pos / raw.length > 0.7)) {
        raw.forEach(function (t) { t.amount = -t.amount; });
        flipped = true;
        if (signMode === 'auto') result.warnings.push('Most amounts in this file are positive, so positive amounts were read as money spent (the way credit card exports usually work). Switch this if it is wrong.');
      }
    }
    var curKeys = Object.keys(currencies);
    var nonGbp = curKeys.filter(function (c) { return c !== 'GBP'; });
    if (nonGbp.length) result.warnings.push('Some rows are in ' + nonGbp.join(', ') + '. Amounts are used as they are, so totals mix currencies.');
    if (dateInfo.ambiguous && !options.dateOrder) result.warnings.push('Every date in this file could be read either way, so they were read the UK way (day first). Switch to month first if your bank is not in the UK.');
    if (dateInfo.conflicting) result.warnings.push('Some dates only make sense day first and others only month first. They were read day first; check the rows listed below.');
    var account = result.account;
    result.transactions = raw.map(function (t) {
      return { day: t.day, amount: t.amount, desc: t.desc, memo: t.memo, type: t.type, category: t.category, account: account, source: result.name, line: t.line };
    });
    result.layout = {
      delimiter: delim, headerRow: headerIdx, headers: headers, mapping: map, dateOrder: order,
      signConvention: map.amount === undefined ? 'columns' : (map.sign !== undefined ? 'marker' : (flipped ? 'positive-out' : 'negative-out')),
      description: describeLayout(map, headers, flipped, order)
    };
    result.ok = result.transactions.length > 0;
    if (!result.ok && !result.error) result.error = 'No payments could be read from this file. The rows it skipped are listed with reasons.';
    finishRange(result);
    return result;
  }
  function describeLayout(map, headers, flipped, order) {
    var name = function (role) { return headers && map[role] !== undefined ? '"' + headers[map[role]] + '"' : 'column ' + (map[role] + 1); };
    var parts = ['dates from ' + name('date') + ' (' + (order === 'MDY' ? 'month first' : 'day first') + ')'];
    if (map.amount !== undefined) parts.push('amounts from ' + name('amount') + (map.sign !== undefined ? ' with ' + name('sign') + ' saying which way' : (flipped ? ', positive means money out' : ', negative means money out')));
    else parts.push('money out from ' + (map.out !== undefined ? name('out') : 'nowhere') + ' and money in from ' + (map['in'] !== undefined ? name('in') : 'nowhere'));
    parts.push('payee from ' + name('payee'));
    if (map.type !== undefined) parts.push('payment type from ' + name('type'));
    return parts.join('; ');
  }
  function finishRange(result) {
    if (!result.transactions.length) { result.start = null; result.end = null; return; }
    var s = Infinity, e = -Infinity;
    result.transactions.forEach(function (t) { if (t.day < s) s = t.day; if (t.day > e) e = t.day; });
    result.start = s; result.end = e;
  }
  function defaultAccount(name) {
    var n = String(name || 'Account').replace(/\.[a-z0-9]+$/i, '').replace(/[_]+/g, ' ').trim();
    n = n.replace(/\b(19|20)\d{2}[-_ ]?\d{2}([-_ ]?\d{2})?\b/g, '').replace(/\b(statement|export|transactions|download|csv)\b/gi, '').replace(/[-\s]+/g, ' ').trim();
    if (!n) return 'Account';
    return n.charAt(0).toUpperCase() + n.slice(1);
  }

  /** Read any supported file: delimited text (CSV, TSV, pasted tables). */
  function parseStatement(text, name, options) {
    return parseCsv(text, name, options);
  }

  /* ------------------------------------------------------------------ */
  /* Merging several files                                               */
  /* ------------------------------------------------------------------ */

  function dedupeKey(t) {
    return t.account + '|' + t.day + '|' + t.amount + '|' + String(t.desc).toUpperCase().replace(/[^A-Z0-9]+/g, '');
  }
  /**
   * Combine statements. Where two files cover the same account and the same
   * days, a payment that appears in both is kept once; identical payments on
   * the same day in one file are all kept.
   */
  function mergeStatements(statements) {
    var counts = {}, firstSeen = {}, order = [];
    statements.forEach(function (st, fi) {
      if (!st || !st.transactions) return;
      var local = {};
      st.transactions.forEach(function (t) {
        var k = dedupeKey(t);
        local[k] = (local[k] || []);
        local[k].push(t);
      });
      Object.keys(local).forEach(function (k) {
        var have = counts[k] || 0, now = local[k].length;
        if (!firstSeen[k]) { firstSeen[k] = []; order.push(k); }
        if (now > have) {
          for (var j = have; j < now; j++) firstSeen[k].push(local[k][j]);
          counts[k] = now;
        }
      });
      void fi;
    });
    var out = [], total = 0;
    statements.forEach(function (st) { if (st && st.transactions) total += st.transactions.length; });
    order.forEach(function (k) { firstSeen[k].forEach(function (t) { out.push(t); }); });
    out.sort(function (a, b) { return a.day - b.day || cmp(a.account, b.account) || a.amount - b.amount || cmp(a.desc, b.desc); });
    var accounts = {};
    statements.forEach(function (st) {
      if (!st || !st.transactions || !st.transactions.length) return;
      var a = accounts[st.account] || (accounts[st.account] = { account: st.account, start: st.start, end: st.end, files: [] });
      a.start = Math.min(a.start, st.start); a.end = Math.max(a.end, st.end);
      a.files.push(st.name);
    });
    return { transactions: out, duplicates: total - out.length, accounts: Object.keys(accounts).sort().map(function (k) { return accounts[k]; }) };
  }

  /**
   * Spot two files that are the same account exported twice (for example a
   * re-download with a different layout): if at least 80% of one file's
   * payments in the days both cover also appear in the other, label them as
   * one account so the overlap is only counted once. Files given an account
   * name by the user are left alone.
   */
  function linkSameAccounts(statements) {
    var notes = [];
    for (var j = 0; j < statements.length; j++) {
      var B = statements[j];
      if (!B || !B.transactions || !B.transactions.length || B.accountGiven) continue;
      for (var i = 0; i < statements.length; i++) {
        var A = statements[i];
        if (i === j || !A || !A.transactions || !A.transactions.length || A.account === B.account) continue;
        if (B.transactions.length > A.transactions.length) continue;
        var from = Math.max(A.start, B.start), to = Math.min(A.end, B.end);
        if (to - from < 7) continue;
        var keys = {};
        A.transactions.forEach(function (t) {
          if (t.day < from || t.day > to) return;
          var k = t.day + '|' + t.amount + '|' + String(t.desc).toUpperCase().replace(/[^A-Z0-9]+/g, '');
          keys[k] = (keys[k] || 0) + 1;
        });
        var inWindow = 0, match = 0;
        B.transactions.forEach(function (t) {
          if (t.day < from || t.day > to) return;
          inWindow++;
          var k = t.day + '|' + t.amount + '|' + String(t.desc).toUpperCase().replace(/[^A-Z0-9]+/g, '');
          if (keys[k]) { keys[k]--; match++; }
        });
        if (inWindow >= 8 && match / inWindow >= 0.8) {
          var was = B.account;
          B.account = A.account;
          B.transactions.forEach(function (t) { t.account = A.account; });
          notes.push({ file: B.name, account: A.account, was: was, share: roundHalfUp(match / inWindow * 100), other: A.name });
          break;
        }
      }
    }
    return notes;
  }

  /* ------------------------------------------------------------------ */
  /* Payees and categories                                               */
  /* ------------------------------------------------------------------ */

  var LEAD_WORDS = ['CARD PAYMENT TO', 'CARD PAYMENT', 'CARD PURCHASE', 'DEBIT CARD PAYMENT', 'CONTACTLESS PAYMENT', 'CONTACTLESS', 'DIRECT DEBIT PAYMENT TO', 'DIRECT DEBIT PAYMENT', 'DIRECT DEBIT TO', 'DIRECT DEBIT', 'STANDING ORDER TO', 'STANDING ORDER', 'FASTER PAYMENT TO', 'FASTER PAYMENTS', 'FASTER PAYMENT', 'BILL PAYMENT TO', 'BILL PAYMENT', 'PAYMENT TO', 'RECURRING PAYMENT', 'RECURRING CARD PAYMENT', 'MOBILE PAYMENT', 'ONLINE PAYMENT', 'PURCHASE', 'POS', 'VIS', 'VISA', 'DEB', 'DD', 'DDR', 'SO', 'STO', 'FPO', 'FPI', 'BGC', 'BP', 'TFR', 'CPT', 'TO', 'FROM'];
  var TRAIL_WORDS = ['DD', 'DDR', 'SO', 'STO', 'FPO', 'FPI', 'BGC', 'DEB', 'POS', 'VIS', 'GB', 'GBR', 'UK', 'IE', 'IRL', 'LU', 'LUX', 'NL', 'NLD', 'US', 'USA', 'DE', 'FR', 'LONDON', 'INTERNET', 'ONLINE', 'APPLE PAY', 'GOOGLE PAY', 'VIA APPLE PAY', 'VIA GOOGLE PAY', 'CONTACTLESS', 'DIRECT DEBIT', 'STANDING ORDER', 'GBP'];
  var PROCESSORS = ['PAYPAL', 'PP', 'SQ', 'SUMUP', 'IZ', 'ZETTLE', 'ZTL', 'STRIPE', 'GOOGLE', 'SP', 'CRV', 'WWW', 'TST', 'CKO', 'SMP', 'PADDLE', 'FS', 'DNH', 'WL'];
  var GENERIC = ['THE', 'PAYMENT', 'PAYMENTS', 'TRANSFER', 'CARD', 'BANK', 'ONLINE', 'MOBILE', 'DIRECT', 'DEBIT', 'CREDIT', 'MR', 'MRS', 'MS', 'MISS', 'DR', 'LTD', 'LIMITED', 'PLC', 'AND', 'CO', 'UK'];

  function cleanDescription(desc) {
    var t = String(desc || '').toUpperCase();
    t = t.replace(/\u2019/g, "'").replace(/[\u2013\u2014]/g, ' ');
    // Dates, times, card numbers and references that change every month.
    t = t.replace(/\bON \d{1,2}[ \/\-]?[A-Z]{3}(?:[ \/\-]?\d{2,4})?\b/g, ' ');
    t = t.replace(/\b\d{1,2}[\/\-.]\d{1,2}(?:[\/\-.]\d{2,4})?\b/g, ' ');
    t = t.replace(/\b\d{1,2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{0,4}\b/g, ' ');
    t = t.replace(/\b\d{1,2}:\d{2}(?::\d{2})?\b/g, ' ');
    t = t.replace(/[X*]{2,}\d{2,}/g, ' ').replace(/\bCD \d{3,}\b/g, ' ');
    t = t.replace(/\b(GBP|EUR|USD)\s*\d+(?:\.\d+)?\b/g, ' ').replace(/\b\d+\.\d{2}\b/g, ' ');
    t = t.replace(/\b(REF|REFERENCE|MANDATE|MANDATE NO|MANDATE REF|INV|INVOICE|ORDER|TXN|ID)\b[:.#]?\s*\S*/g, ' ');
    return t;
  }
  function tokens(t) {
    return t.split(/[^A-Z0-9&+'.\/-]+/).map(function (w) { return w.replace(/^[.\/'-]+|[.\/'-]+$/g, ''); }).filter(function (w) {
      if (!w) return false;
      if (/^\d+$/.test(w)) return w.length <= 2;
      var digits = (w.match(/\d/g) || []).length;
      if (digits >= 3) return false;
      if (digits >= 2 && w.length >= 5) return false;
      return true;
    });
  }
  function stripEnds(toks) {
    var changed = true;
    while (changed && toks.length > 1) {
      changed = false;
      for (var i = 0; i < LEAD_WORDS.length; i++) {
        var lw = LEAD_WORDS[i].split(' ');
        if (toks.length > lw.length && toks.slice(0, lw.length).join(' ') === LEAD_WORDS[i]) { toks = toks.slice(lw.length); changed = true; break; }
      }
      if (changed) continue;
      for (var j = 0; j < TRAIL_WORDS.length; j++) {
        var tw = TRAIL_WORDS[j].split(' ');
        if (toks.length > tw.length && toks.slice(toks.length - tw.length).join(' ') === TRAIL_WORDS[j]) { toks = toks.slice(0, toks.length - tw.length); changed = true; break; }
      }
    }
    return toks;
  }
  /** The payee key used to group payments: the first three meaningful words of the description. */
  function payeeKey(desc) {
    var t = cleanDescription(desc);
    var star = t.indexOf('*');
    if (star >= 0) {
      var left = t.slice(0, star).trim(), right = t.slice(star + 1).trim();
      var leftToks = stripEnds(tokens(left));
      if (!leftToks.length || PROCESSORS.indexOf(leftToks[leftToks.length - 1]) >= 0) t = right || left;
      else t = left;
    }
    var toks = stripEnds(tokens(t));
    if (toks.length > 1 && PROCESSORS.indexOf(toks[0]) >= 0 && toks[0] !== 'GOOGLE') toks = toks.slice(1);
    toks = toks.slice(0, 3);
    while (toks.length > 1 && ['&', '-', '+', 'AND'].indexOf(toks[toks.length - 1]) >= 0) toks.pop();
    var key = toks.join(' ').trim();
    return key || String(desc || '').toUpperCase().trim().slice(0, 30) || '(NO DESCRIPTION)';
  }
  function displayName(key) {
    return key.split(' ').map(function (w) {
      if (w.length <= 2 && !/^[A-Z][a-z]?$/.test(w) && /^[A-Z0-9&+]+$/.test(w)) return w;
      return w.charAt(0) + w.slice(1).toLowerCase().replace(/([.\/-])([a-z])/g, function (m, a, b) { return a + b; });
    }).join(' ');
  }
  /** Groups whose key is the first word or words of another key are the same payee. */
  function groupKeys(keys) {
    var sorted = keys.slice().sort(function (a, b) { return a.split(' ').length - b.split(' ').length || cmp(a, b); });
    var parent = {};
    sorted.forEach(function (k) {
      var toks = k.split(' ');
      parent[k] = k;
      for (var n = toks.length - 1; n >= 1; n--) {
        var pre = toks.slice(0, n).join(' ');
        if (parent[pre] === undefined) continue;
        var head = toks[0];
        if (n === 1 && (head.length < 4 || GENERIC.indexOf(head) >= 0)) continue;
        parent[k] = parent[pre];
        break;
      }
    });
    return parent;
  }

  var CATEGORIES = [
    { id: 'savings', label: 'Savings and moving money between your accounts', essential: false, cost: false, words: ['SAVINGS', 'SAVER', 'ISA', 'LISA', 'POT', 'POTS', 'INVEST', 'INVESTMENT', 'TO SAVINGS', 'SAVINGS ACCOUNT', 'MONEYBOX', 'VANGUARD', 'PREMIUM BONDS', 'NS&I', 'OWN ACCOUNT'] },
    { id: 'housing', label: 'Rent and housing', essential: true, words: ['RENT', 'LETTINGS', 'LETTING', 'LANDLORD', 'MORTGAGE', 'HOUSING', 'ACCOMMODATION', 'HALLS', 'RESIDENCE', 'ESTATES', 'PROPERTY', 'SERVICE CHARGE'] },
    { id: 'council', label: 'Council tax', essential: true, words: ['COUNCIL', 'COUNCIL TAX', 'CTAX', 'BOROUGH', 'DISTRICT COUNCIL'] },
    { id: 'energy', label: 'Energy and water', essential: true, words: ['ENERGY', 'ELECTRIC', 'ELECTRICITY', 'GAS', 'WATER', 'POWER', 'UTILITIES', 'UTILITY', 'OCTOPUS', 'EDF', 'EON', 'E.ON', 'OVO', 'BRITISH GAS', 'SCOTTISH POWER', 'SO ENERGY', 'HEATING'] },
    { id: 'finance', label: 'Loans and credit', essential: true, words: ['LOAN', 'LOANS', 'CREDIT CARD', 'KLARNA', 'CLEARPAY', 'LAYBUY', 'PAYPAL CREDIT', 'FINANCE', 'REPAYMENT', 'HIRE PURCHASE', 'BNPL', 'OVERDRAFT'] },
    { id: 'insurance', label: 'Insurance and cover', essential: true, words: ['INSURANCE', 'INS', 'INSURE', 'COVER', 'ASSURANCE', 'MUTUAL', 'WARRANTY', 'PROTECT', 'PROTECTION', 'BREAKDOWN'] },
    { id: 'telecoms', label: 'Phone and broadband', essential: true, words: ['MOBILE', 'BROADBAND', 'FIBRE', 'SIM', 'TELECOM', 'TELECOMS', 'WIFI', 'INTERNET SERVICE', 'VODAFONE', 'O2', 'EE', 'GIFFGAFF', 'VIRGIN MEDIA', 'TALKTALK', 'PLUSNET', 'SMARTY', 'LEBARA', 'TESCO MOBILE', 'VOXI', 'HYPEROPTIC', 'PHONE'] },
    { id: 'tv', label: 'TV and video', essential: false, words: ['TV', 'STREAM', 'STREAMING', 'VIDEO', 'FILMS', 'CINEMA', 'NETFLIX', 'DISNEY', 'DISNEY PLUS', 'PRIME VIDEO', 'NOW TV', 'NOWTV', 'PARAMOUNT', 'BRITBOX', 'DAZN', 'YOUTUBE', 'CRUNCHYROLL', 'APPLE TV', 'TV LICENCE', 'MUBI'] },
    { id: 'music', label: 'Music and audio', essential: false, words: ['MUSIC', 'SPOTIFY', 'TIDAL', 'DEEZER', 'AUDIBLE', 'SOUNDCLOUD', 'PODCAST', 'AUDIOBOOKS', 'RADIO'] },
    { id: 'software', label: 'Apps, software and cloud', essential: false, words: ['CLOUD', 'STORAGE', 'ICLOUD', 'DROPBOX', 'ADOBE', 'MICROSOFT', 'MICROSOFT 365', 'OFFICE', 'CANVA', 'NOTION', 'OPENAI', 'CHATGPT', 'GITHUB', 'GOOGLE ONE', 'GOOGLE STORAGE', 'SOFTWARE', 'HOSTING', 'DOMAIN', 'DOMAINS', 'VPN', 'PASSWORD', 'ANTIVIRUS', 'APPS', 'APP STORE', 'GRAMMARLY', 'ZOOM', 'SLACK', 'FIGMA'] },
    { id: 'news', label: 'News and magazines', essential: false, words: ['NEWS', 'NEWSPAPER', 'MAGAZINE', 'MAGAZINES', 'GAZETTE', 'JOURNAL', 'TIMES', 'HERALD', 'ECONOMIST', 'PRESS', 'LANTERN', 'SUBSTACK', 'PATREON'] },
    { id: 'gym', label: 'Gym and fitness', essential: false, words: ['GYM', 'FITNESS', 'LEISURE', 'SPORTS CENTRE', 'CLIMBING', 'BOULDERING', 'YOGA', 'PILATES', 'SWIM', 'SWIMMING', 'STRAVA', 'PELOTON', 'CROSSFIT', 'ATHLETIC'] },
    { id: 'food', label: 'Food boxes and delivery passes', essential: false, words: ['MEAL', 'MEALS', 'MEAL KIT', 'VEG BOX', 'VEGBOX', 'FOOD BOX', 'HELLOFRESH', 'GOUSTO', 'MINDFUL CHEF', 'MILK', 'MILKMAN', 'DELIVERY PASS', 'DELIVEROO PLUS', 'UBER ONE', 'COFFEE SUBSCRIPTION'] },
    { id: 'learning', label: 'Learning and languages', essential: false, words: ['LANGUAGE', 'LANGUAGES', 'LINGO', 'DUOLINGO', 'BABBEL', 'COURSE', 'COURSES', 'TUTOR', 'TUITION', 'MASTERCLASS', 'COURSERA', 'LEARNING', 'LEARN', 'SCHOOL', 'ACADEMY'] },
    { id: 'gaming', label: 'Games', essential: false, words: ['GAME', 'GAMES', 'GAMING', 'XBOX', 'PLAYSTATION', 'NINTENDO', 'STEAM', 'CHESS', 'TWITCH'] },
    { id: 'charity', label: 'Charity and donations', essential: false, words: ['CHARITY', 'CHARITABLE', 'TRUST', 'FOUNDATION', 'DONATION', 'DONATE', 'RNLI', 'OXFAM', 'UNICEF', 'WWF', 'SHELTER', 'RSPCA', 'NSPCC', 'SAMARITANS', 'APPEAL'] },
    { id: 'transport', label: 'Transport and travel passes', essential: false, words: ['RAILCARD', 'TRAINLINE', 'BUS PASS', 'TRAVELCARD', 'SEASON TICKET', 'PARKING', 'BIKE', 'CYCLE', 'SCOOTER', 'CAR CLUB', 'ZIPCAR', 'TRANSPORT', 'RAIL'] },
    { id: 'household', label: 'Household services', essential: false, words: ['CLEAN', 'CLEANING', 'CLEANER', 'WINDOW', 'GARDEN', 'GARDENING', 'LAUNDRY', 'PEST', 'BINS'] },
    { id: 'personal', label: 'Personal care', essential: false, words: ['BARBER', 'BARBERS', 'HAIR', 'SALON', 'NAILS', 'BEAUTY', 'DENTAL', 'DENTIST', 'OPTICIAN', 'CONTACT LENSES', 'PHARMACY'] },
    { id: 'memberships', label: 'Memberships and clubs', essential: false, words: ['MEMBERSHIP', 'MEMBERS', 'CLUB', 'SOCIETY', 'PRIME', 'PREMIUM', 'SUBSCRIPTION', 'SUBS', 'PLUS'] },
    { id: 'income', label: 'Income', essential: false, cost: false, words: [] },
    { id: 'other', label: 'Other regular payments', essential: false, words: [] }
  ];
  var CATEGORY_BY_ID = {};
  CATEGORIES.forEach(function (c) { CATEGORY_BY_ID[c.id] = c; });
  var DUPLICATE_PRONE = ['tv', 'music', 'software', 'news', 'gym', 'food', 'learning', 'gaming', 'memberships'];
  var BANK_CATEGORY_HINTS = [
    [/saving|transfer|pot/i, 'savings'], [/rent|mortgage|housing/i, 'housing'], [/council/i, 'council'],
    [/utilit|energy|water/i, 'energy'], [/insur/i, 'insurance'], [/phone|mobile|broadband|internet/i, 'telecoms'],
    [/entertain|subscri|stream/i, 'tv'], [/fitness|sport|gym/i, 'gym'], [/charit|donat|gift/i, 'charity'],
    [/transport|travel/i, 'transport'], [/education|learn/i, 'learning']
  ];

  function categorise(text, bankCategory) {
    var words = ' ' + tokens(cleanDescription(text).replace(/[.\/]/g, ' ')).join(' ') + ' ';
    for (var i = 0; i < CATEGORIES.length; i++) {
      var c = CATEGORIES[i];
      for (var j = 0; j < c.words.length; j++) if (words.indexOf(' ' + c.words[j] + ' ') >= 0) return { id: c.id, word: c.words[j] };
    }
    if (bankCategory) {
      for (var k = 0; k < BANK_CATEGORY_HINTS.length; k++) if (BANK_CATEGORY_HINTS[k][0].test(bankCategory)) return { id: BANK_CATEGORY_HINTS[k][1], word: null, bank: bankCategory };
    }
    return { id: 'other', word: null };
  }

  var METHODS = ['direct debit', 'standing order', 'card', 'transfer', 'unknown'];
  /** How a payment was made, from the bank's type column or the description. */
  function paymentMethod(type, desc) {
    var t = (' ' + String(type || '') + ' ').toUpperCase();
    var d = (' ' + String(desc || '') + ' ').toUpperCase();
    if (/DIRECT DEBIT|\bDDR?\b|\bDD\b/.test(t)) return 'direct debit';
    if (/STANDING ORDER|\bSO\b|\bSTO\b/.test(t)) return 'standing order';
    if (/CARD|\bPOS\b|\bVIS\b|\bDEB\b|CONTACTLESS|PURCHASE|APPLE PAY|GOOGLE PAY/.test(t)) return 'card';
    if (/TRANSFER|\bTFR\b|\bFPO\b|\bFPI\b|FASTER|\bBGC\b|BACS|BANK CREDIT|BILL PAYMENT/.test(t)) return 'transfer';
    if (/DIRECT DEBIT|^ DDR? |\sDDR?\s*$/.test(d)) return 'direct debit';
    if (/STANDING ORDER|^ SO |^ STO |\sSO\s*$|\sSTO\s*$/.test(d)) return 'standing order';
    if (/CARD PAYMENT|CARD PURCHASE|^ POS |^ VIS |CONTACTLESS|APPLE PAY|GOOGLE PAY/.test(d)) return 'card';
    if (/FASTER PAYMENT|^ FPO |^ FPI |^ BGC |^ TFR |TRANSFER/.test(d)) return 'transfer';
    return 'unknown';
  }

  /* ------------------------------------------------------------------ */
  /* Finding regular payments                                            */
  /* ------------------------------------------------------------------ */

  var CADENCES = [
    { id: 'weekly', label: 'Weekly', days: 7, tol: 1, min: 4, perYear: 52 },
    { id: 'fortnightly', label: 'Every two weeks', days: 14, tol: 2, min: 3, perYear: 26 },
    { id: 'four-weekly', label: 'Every four weeks', days: 28, tol: 1, min: 3, perYear: 13 },
    { id: 'monthly', label: 'Monthly', months: 1, days: 30.44, tol: 4, min: 3, perYear: 12 },
    { id: 'two-monthly', label: 'Every two months', months: 2, days: 60.88, tol: 5, min: 3, perYear: 6 },
    { id: 'quarterly', label: 'Quarterly', months: 3, days: 91.31, tol: 7, min: 2, perYear: 4 },
    { id: 'six-monthly', label: 'Every six months', months: 6, days: 182.62, tol: 10, min: 2, perYear: 2 },
    { id: 'yearly', label: 'Yearly', months: 12, days: 365.25, tol: 14, min: 2, perYear: 1 }
  ];
  var CADENCE_BY_ID = {};
  CADENCES.forEach(function (c) { CADENCE_BY_ID[c.id] = c; });

  /** The nominal day of the month a monthly payment is due: the most common day, earliest on a tie. */
  function anchorDay(days) {
    var counts = {};
    days.forEach(function (d) {
      var p = ymd(d);
      var dom = p.d >= 28 && p.d === daysInMonth(p.y, p.m) ? 31 : p.d;
      counts[dom] = (counts[dom] || 0) + 1;
    });
    var best = 0, bestN = 0;
    Object.keys(counts).forEach(function (k) { var n = counts[k]; if (n > bestN || (n === bestN && +k < best)) { best = +k; bestN = n; } });
    return best;
  }
  /** A monthly rule that every payment follows exactly, such as the last Friday of the month. */
  function ruleAnchor(days) {
    if (days.length < 3) return null;
    var rules = ['LW', 'L5', 'L1', 'L2', 'L3', 'L4'];
    for (var i = 0; i < rules.length; i++) {
      var r = rules[i];
      var all = days.every(function (d) { var p = ymd(d); return nominalInMonth(p.y, p.m, r) === d; });
      if (!all) continue;
      // Only worth a rule if a plain day of the month would not do.
      var doms = {};
      days.forEach(function (d) { doms[ymd(d).d] = 1; });
      if (Object.keys(doms).length > 1) return r;
    }
    return null;
  }
  /** Next nominal due date after a given payment for a cadence. */
  function stepFrom(day, cad, anchor, k) {
    k = k || 1;
    if (cad.months) return addMonths(day, cad.months * k, anchor);
    return day + cad.days * k;
  }
  /**
   * Test how well a list of payment days fits each cadence. Returns the best
   * fit: how many gaps match one step, how many look like a missed payment
   * (two steps), how many are extra charges close to another, and the
   * average error in days.
   */
  function fitCadence(days) {
    if (days.length < 2) return null;
    var best = null;
    CADENCES.forEach(function (cad) {
      var anchor = cad.months ? (cad.months === 1 ? ruleAnchor(days) || anchorDay(days) : anchorDay(days)) : 0;
      var matched = 0, missed = 0, extras = [], err = 0, bad = 0;
      var prev = days[0];
      for (var i = 1; i < days.length; i++) {
        var d = days[i];
        var gap = d - prev;
        var e1, e2;
        if (cad.months) {
          // Compare with the due date one and two steps on from the previous nominal date.
          var nominalPrev = nearestNominal(prev, anchor);
          e1 = d - stepFrom(nominalPrev, cad, anchor, 1);
          e2 = d - stepFrom(nominalPrev, cad, anchor, 2);
        } else {
          e1 = gap - cad.days; e2 = gap - cad.days * 2;
        }
        var lateTol = cad.tol, earlyTol = cad.months ? Math.min(cad.tol, 3) : cad.tol;
        if (e1 >= -earlyTol && e1 <= lateTol) { matched++; err += Math.abs(e1); prev = d; continue; }
        if (e2 >= -earlyTol && e2 <= lateTol) { missed++; err += Math.abs(e2); prev = d; continue; }
        if (gap <= Math.max(3, cad.days * 0.25)) { extras.push(d); continue; }
        bad++; prev = d;
      }
      var gaps = matched + missed + bad;
      if (!gaps) return;
      var score = (matched + missed) / gaps;
      var mae = err / Math.max(1, matched + missed);
      var fit = { cadence: cad.id, anchor: anchor, matched: matched, missed: missed, bad: bad, extras: extras, mae: mae, score: score };
      var allowedMissed = Math.max(1, Math.floor(gaps * 0.25));
      fit.ok = matched >= 1 && score >= 0.75 && missed <= allowedMissed && extras.length <= Math.max(1, Math.floor(days.length / 6)) && matched >= missed;
      var rank = score - mae * 0.02 - missed * 0.01;
      fit.rank = rank;
      if (!best || (fit.ok && !best.ok) || (fit.ok === best.ok && rank > best.rank + 1e-9)) best = fit;
    });
    return best;
  }
  /** For monthly cadences: the nominal due date nearest to (on or before, allowing rolling) a payment day. */
  function nearestNominal(day, anchor) {
    var p = ymd(day);
    var cand = [];
    for (var dm = -1; dm <= 1; dm++) {
      var total = p.y * 12 + (p.m - 1) + dm;
      var y = Math.floor(total / 12), m = total % 12 + 1;
      cand.push(nominalInMonth(y, m, anchor));
    }
    var best = cand[0];
    cand.forEach(function (c) { if (Math.abs(day - c) < Math.abs(day - best) || (Math.abs(day - c) === Math.abs(day - best) && c < best)) best = c; });
    return best;
  }

  function median(list) {
    var s = list.slice().sort(function (a, b) { return a - b; });
    if (!s.length) return 0;
    var mid = Math.floor(s.length / 2);
    return s.length % 2 ? s[mid] : roundHalfUp((s[mid - 1] + s[mid]) / 2);
  }
  /** Describe how a series' amounts behave: fixed, stepped (price changes) or variable. */
  function amountProfile(payments) {
    var amounts = payments.map(function (p) { return Math.abs(p.amount); });
    var runs = [];
    payments.forEach(function (p, i) {
      var a = amounts[i];
      var last = runs[runs.length - 1];
      if (last && last.amount === a) { last.count++; last.end = p.day; }
      else runs.push({ amount: a, count: 1, start: p.day, end: p.day });
    });
    var distinct = {};
    amounts.forEach(function (a) { distinct[a] = 1; });
    var nDistinct = Object.keys(distinct).length;
    var kind;
    if (nDistinct === 1) kind = 'fixed';
    else if (runs.length <= 4 && (runs.length <= Math.ceil(amounts.length / 2) || runs.length === 2) && runs[runs.length - 1].count >= 1 && runs.filter(function (r) { return r.count === 1; }).length <= 1 + (runs[0].count === 1 ? 1 : 0)) kind = 'stepped';
    else kind = 'variable';
    var typical;
    if (kind === 'fixed') typical = amounts[0];
    else if (kind === 'stepped') typical = runs[runs.length - 1].amount;
    else typical = median(amounts.slice(-3));
    var changes = [];
    if (kind === 'stepped') {
      for (var i = 1; i < runs.length; i++) changes.push({ day: runs[i].start, from: runs[i - 1].amount, to: runs[i].amount });
    }
    var min = Math.min.apply(null, amounts), max = Math.max.apply(null, amounts);
    return { kind: kind, typical: typical, min: min, max: max, changes: changes, runs: runs, last: amounts[amounts.length - 1] };
  }

  /** Split a payee's payments into regular series. */
  function explainGroup(payments, signals) {
    var found = [];
    if (payments.length >= 2) {
      var whole = fitCadence(payments.map(function (p) { return p.day; }));
      if (whole && whole.ok && whole.extras.length === 0 && (amountsCompatible(payments) || (signals && signals.mandate))) {
        return { series: [{ payments: payments, fit: whole }], rest: [] };
      }
    }
    // Same amount, then join runs that follow on from each other (price changes, intro offers).
    var byAmount = {}, keys = [];
    payments.forEach(function (p) {
      var a = Math.abs(p.amount);
      if (!byAmount[a]) { byAmount[a] = []; keys.push(a); }
      byAmount[a].push(p);
    });
    var clusters = keys.map(function (a) { return byAmount[a]; });
    clusters.sort(function (x, y) { return x[0].day - y[0].day || Math.abs(x[0].amount) - Math.abs(y[0].amount); });
    var merged = true;
    while (merged) {
      merged = false;
      var bestPair = null;
      for (var i = 0; i < clusters.length; i++) {
        for (var j = 0; j < clusters.length; j++) {
          if (i === j) continue;
          var A = clusters[i], B = clusters[j];
          if (A[A.length - 1].day >= B[0].day) continue;
          if (A.length < 2 && B.length < 2) continue;
          var ref = fitCadence((A.length >= B.length ? A : B).map(function (p) { return p.day; }));
          if (!ref || !ref.ok) continue;
          var union = A.concat(B);
          var uf = fitCadence(union.map(function (p) { return p.day; }));
          if (!uf || !uf.ok || uf.cadence !== ref.cadence || uf.extras.length) continue;
          var gapErr = joinError(A, B, ref);
          if (gapErr === null) continue;
          var cost = gapErr + (union.length > 0 ? 0 : 1);
          if (!bestPair || cost < bestPair.cost) bestPair = { i: i, j: j, cost: cost };
        }
      }
      if (bestPair) {
        var a2 = clusters[bestPair.i], b2 = clusters[bestPair.j];
        var joined = a2.concat(b2);
        clusters = clusters.filter(function (c, k) { return k !== bestPair.i && k !== bestPair.j; });
        clusters.push(joined);
        clusters.sort(function (x, y) { return x[0].day - y[0].day || Math.abs(x[0].amount) - Math.abs(y[0].amount); });
        merged = true;
      }
    }
    var rest = [];
    clusters.forEach(function (c) {
      if (c.length >= 2) {
        var f = fitCadence(c.map(function (p) { return p.day; }));
        if (f && f.ok) { found.push({ payments: c, fit: f }); return; }
      }
      c.forEach(function (p) { rest.push(p); });
    });
    void signals;
    return { series: found, rest: rest };
  }
  /** Bills vary, but a whole payee group only counts as one series if its amounts stay in a sensible band. */
  function amountsCompatible(payments) {
    var a = payments.map(function (p) { return Math.abs(p.amount); });
    var min = Math.min.apply(null, a), max = Math.max.apply(null, a);
    var distinct = {};
    a.forEach(function (x) { distinct[x] = 1; });
    var n = Object.keys(distinct).length;
    if (n === 1) return true;
    if (max <= min * 3) return true;
    // An intro or trial price at the start, then a steady price.
    var tail = a.slice(1), tmin = Math.min.apply(null, tail), tmax = Math.max.apply(null, tail);
    return a[0] < tmin && tmax <= tmin * 3;
  }
  /** How far the gap between two runs is from one step of the cadence, or null if it is not a follow-on. */
  function joinError(A, B, fit) {
    var cad = CADENCE_BY_ID[fit.cadence];
    var last = A[A.length - 1].day, first = B[0].day;
    var expected = cad.months ? stepFrom(nearestNominal(last, fit.anchor), cad, fit.anchor, 1) : last + cad.days;
    var err = first - expected;
    var earlyTol = cad.months ? Math.min(cad.tol, 3) : cad.tol;
    if (err < -earlyTol || err > cad.tol) return null;
    return Math.abs(err);
  }

  /** Minimum payments needed before a pattern counts, given what else we know. */
  function minimumCount(cad, method, keyword) {
    var n = cad.min;
    if (method === 'direct debit' || method === 'standing order') n = Math.max(2, n - 1);
    else if (keyword && cad.months) n = Math.max(2, n - 1);
    return n;
  }

  function cadenceOf(id) { return CADENCE_BY_ID[id]; }

  /** Expected payment dates from a series, rolled to working days for direct debits and standing orders. */
  function scheduleFrom(series, fromNominal, count, untilDay) {
    var cad = CADENCE_BY_ID[series.cadence];
    var out = [], nominal = fromNominal;
    for (var i = 0; i < count; i++) {
      nominal = stepFrom(nominal, cad, series.anchor, 1);
      if (untilDay !== undefined && nominal > untilDay) break;
      var due = series.rolls ? nextWorkingDay(nominal) : nominal;
      out.push({ nominal: nominal, due: due });
    }
    return out;
  }
  function lastNominal(series) {
    var cad = CADENCE_BY_ID[series.cadence];
    var last = series.payments[series.payments.length - 1].day;
    if (cad.months) return nearestNominal(last, series.anchor);
    return last;
  }

  /** What a payment on a given day is likely to be: last year's for the same month if a bill varies, else the current amount. */
  function expectedAmount(s, day) {
    if (s.amounts.kind !== 'variable' || !s.seasonal) return s.typical;
    var target = day - 365, best = null;
    s.payments.forEach(function (p) {
      var e = Math.abs(p.day - target);
      if (e <= 20 && (!best || e < best.e)) best = { e: e, amount: p.amount };
    });
    return best ? best.amount : s.typical;
  }
  function annualCost(typical, cadenceId) {
    return typical * CADENCE_BY_ID[cadenceId].perYear;
  }
  function monthlyCost(typical, cadenceId) {
    return roundHalfUp(annualCost(typical, cadenceId) / 12);
  }

  function confidenceFor(s) {
    var n = s.payments.length;
    var score = Math.min(40, n * 10);
    score += roundHalfUp(25 * s.fit.score);
    score += s.amounts.kind === 'fixed' ? 15 : s.amounts.kind === 'stepped' ? 12 : 6;
    if (s.method === 'direct debit' || s.method === 'standing order') score += 10;
    else if (s.method === 'card') score += 3;
    if (s.keyword) score += 7;
    score -= s.fit.missed * 5 + s.extras.length * 3;
    score -= roundHalfUp(s.fit.mae);
    return Math.max(5, Math.min(99, score));
  }
  function confidenceLabel(c) { return c >= 75 ? 'Sure' : c >= 50 ? 'Likely' : 'Possible'; }

  /** Words that suggest a single payment is a renewal worth watching. */
  var RENEWAL_WORDS = ['ANNUAL', 'YEARLY', 'RENEWAL', 'RENEW', 'MEMBERSHIP', 'SUBSCRIPTION', 'SUBS', 'PREMIUM', 'LICENCE', 'LICENSE', 'INSURANCE', 'COVER', 'PRO', 'PLUS'];

  /**
   * Find regular payments in merged transactions.
   * options: {asOf, aliases: {key: groupKey}, names: {id: name}, manual: [{key, cadence, account}]}
   */
  function findRegulars(transactions, options) {
    options = options || {};
    var aliases = options.aliases || {};
    var overrides = options.overrides || {};
    var coverage = {};
    transactions.forEach(function (t) {
      var c = coverage[t.account] || (coverage[t.account] = { start: t.day, end: t.day });
      if (t.day < c.start) c.start = t.day;
      if (t.day > c.end) c.end = t.day;
    });
    var dataEnd = -Infinity, dataStart = Infinity;
    Object.keys(coverage).forEach(function (a) { dataEnd = Math.max(dataEnd, coverage[a].end); dataStart = Math.min(dataStart, coverage[a].start); });
    var asOf = options.asOf !== undefined && options.asOf !== null ? options.asOf : (isFinite(dataEnd) ? dataEnd + 1 : dayFromYMD(2026, 1, 1));

    var transfers = matchTransfers(transactions);
    var series = [], candidates = [], income = [];
    ['out', 'in'].forEach(function (direction) {
      var list = transactions.filter(function (t) { return direction === 'out' ? t.amount < 0 : t.amount > 0; });
      var keyOf = {};
      list.forEach(function (t) { var k = payeeKey(t.desc); keyOf[k] = 1; });
      var parents = groupKeys(Object.keys(keyOf));
      var groups = {}, gorder = [];
      list.forEach(function (t) {
        var k = payeeKey(t.desc);
        var g = parents[k] || k;
        if (aliases[g]) g = aliases[g];
        if (!groups[g]) { groups[g] = []; gorder.push(g); }
        groups[g].push({ day: t.day, amount: t.amount, desc: t.desc, memo: t.memo, type: t.type, category: t.category, account: t.account, key: k, transfer: !!transfers[transferId(t)] });
      });
      gorder.sort();
      gorder.forEach(function (g) {
        var pays = groups[g].slice().sort(function (a, b) { return a.day - b.day || Math.abs(a.amount) - Math.abs(b.amount); });
        var mandates = pays.filter(function (p) { var m = paymentMethod(p.type, p.desc); return m === 'direct debit' || m === 'standing order'; }).length;
        var ex = explainGroup(pays, { mandate: mandates * 2 > pays.length });
        var seq = {};
        ex.series.forEach(function (raw) {
          var base = g + '~' + raw.fit.cadence;
          seq[base] = (seq[base] || 0) + 1;
          var id = base + '~' + seq[base];
          var s = buildSeries(g, raw, direction, coverage, asOf, overrides[id]);
          s.id = id;
          var minN = minimumCount(CADENCE_BY_ID[s.cadence], s.method, s.keyword);
          if (s.payments.length < minN) {
            if (direction === 'in') return;
            candidates.push(candidateFrom(s, 'Only ' + s.payments.length + ' payments so far, ' + CADENCE_BY_ID[s.cadence].label.toLowerCase() + ' apart.'));
            return;
          }
          if (direction === 'in') { if (!s.transfer) income.push(s); } else series.push(s);
        });
        if (direction === 'out') {
          ex.rest.forEach(function (p) {
            var words = ' ' + tokens(cleanDescription(p.desc + ' ' + (p.memo || ''))).join(' ') + ' ';
            var hit = null;
            for (var i = 0; i < RENEWAL_WORDS.length; i++) if (words.indexOf(' ' + RENEWAL_WORDS[i] + ' ') >= 0) { hit = RENEWAL_WORDS[i]; break; }
            if (!hit || Math.abs(p.amount) < 1000) return;
            if (asOf - p.day > 400) return;
            var cat = categorise(p.desc + ' ' + (p.memo || ''), p.category);
            candidates.push({
              id: g + '~single~' + iso(p.day), key: g, name: displayName(g), account: p.account, cadence: 'yearly', amount: Math.abs(p.amount),
              lastDay: p.day, payments: [p], method: paymentMethod(p.type, p.desc), category: cat.id,
              reason: 'One payment of ' + money(Math.abs(p.amount)) + ' on ' + longDate(p.day) + ' with "' + hit.toLowerCase() + '" in the description. If it renews yearly, the next one is due about ' + longDate(addMonths(p.day, 12)) + '.'
            });
          });
        }
      });
    });
    // Payments the user has confirmed by hand.
    (options.manual || []).forEach(function (m) {
      var idx = -1;
      candidates.forEach(function (c, i) { if (c.id === m.id) idx = i; });
      if (idx < 0) return;
      var c = candidates[idx];
      candidates.splice(idx, 1);
      var s = buildSeries(c.key, { payments: c.payments, fit: { cadence: m.cadence || c.cadence, anchor: anchorDay(c.payments.map(function (p) { return p.day; })), matched: 0, missed: 0, bad: 0, extras: [], mae: 0, score: 1, ok: true } }, 'out', coverage, asOf, overrides[c.id]);
      s.id = c.id;
      s.manual = true;
      s.confidence = 60;
      s.reasons.unshift('You confirmed this as a regular payment.');
      series.push(s);
    });

    flagDuplicates(series);
    series.sort(function (a, b) { return statusRank(a) - statusRank(b) || b.annual - a.annual || cmp(a.id, b.id); });
    income.sort(function (a, b) { return b.annual - a.annual || cmp(a.id, b.id); });
    candidates.sort(function (a, b) { return b.amount - a.amount || cmp(a.id, b.id); });
    var names = options.names || {};
    series.concat(income).forEach(function (s) { if (names[s.id]) s.name = names[s.id]; });
    return {
      asOf: asOf, dataStart: isFinite(dataStart) ? dataStart : null, dataEnd: isFinite(dataEnd) ? dataEnd : null,
      coverage: coverage, series: series, income: income, candidates: candidates,
      payday: findPayday(income, asOf), transferCount: Object.keys(transfers).length
    };
  }
  function statusRank(s) { return s.status === 'stopped' ? 1 : 0; }

  function transferId(t) { return t.account + '|' + t.day + '|' + t.amount + '|' + t.desc; }
  /** Money moved between two of your own accounts: out of one and into another for the same amount within three days. */
  function matchTransfers(transactions) {
    var accounts = {};
    transactions.forEach(function (t) { accounts[t.account] = 1; });
    if (Object.keys(accounts).length < 2) return {};
    var ins = {}, marked = {};
    transactions.forEach(function (t) {
      if (t.amount > 0) { (ins[t.amount] = ins[t.amount] || []).push(t); }
    });
    transactions.forEach(function (t) {
      if (t.amount >= 0) return;
      var cands = ins[-t.amount] || [];
      for (var i = 0; i < cands.length; i++) {
        var c = cands[i];
        if (c.account === t.account || marked[transferId(c)]) continue;
        if (c.day < t.day || c.day - t.day > 3) continue;
        marked[transferId(c)] = 1; marked[transferId(t)] = 1;
        break;
      }
    });
    return marked;
  }

  function buildSeries(groupKey, raw, direction, coverage, asOf, override) {
    override = override || {};
    var payments = raw.payments.slice().sort(function (a, b) { return a.day - b.day; });
    var fit = raw.fit;
    var cad = CADENCE_BY_ID[fit.cadence];
    var extras = fit.extras || [];
    var methods = {};
    payments.forEach(function (p) { var m = paymentMethod(p.type, p.desc); methods[m] = (methods[m] || 0) + 1; });
    var method = 'unknown', mN = 0;
    Object.keys(methods).sort().forEach(function (m) { if (m !== 'unknown' && methods[m] > mN) { method = m; mN = methods[m]; } });
    if (method === 'unknown' && payments.every(function (p) { return /card|credit/i.test(p.account); })) method = 'card';
    if (override.method && METHODS.indexOf(override.method) >= 0) method = override.method;
    var lastP = payments[payments.length - 1];
    var cat = categorise(payments.map(function (p) { return p.desc + ' ' + (p.memo || ''); }).join(' '), lastP.category);
    var transferShare = payments.filter(function (p) { return p.transfer; }).length / payments.length;
    if (transferShare >= 0.5 && direction === 'out') cat = { id: 'savings', word: null, transfer: true };
    if (direction === 'in') cat = { id: 'income', word: null, transfer: transferShare >= 0.5 };
    else if (override.category && CATEGORY_BY_ID[override.category]) cat = { id: override.category, word: null, user: true };
    var amounts = amountProfile(payments);
    var accounts = {};
    payments.forEach(function (p) { accounts[p.account] = 1; });
    var accList = Object.keys(accounts).sort();
    var covEnd = -Infinity, covStart = Infinity;
    accList.forEach(function (a) { covEnd = Math.max(covEnd, coverage[a].end); covStart = Math.min(covStart, coverage[a].start); });
    var s = {
      id: '', key: groupKey, name: displayName(groupKey), direction: direction,
      account: accList.join(', '), accounts: accList, cadence: cad.id, cadenceLabel: cad.label,
      anchor: fit.anchor, payments: payments.map(function (p) { return { day: p.day, amount: Math.abs(p.amount), desc: p.desc, account: p.account }; }),
      count: payments.length, first: payments[0].day, last: lastP.day,
      method: method, rolls: method === 'direct debit' || method === 'standing order',
      category: cat.id, keyword: cat.word || null, bankCategory: cat.bank || null, transfer: !!cat.transfer,
      amounts: amounts, typical: amounts.typical, fit: fit, extras: extras, flags: [], reasons: []
    };
    s.annual = annualCost(s.typical, s.cadence);
    if (amounts.kind === 'variable' && s.last - s.first >= 300) {
      // A year of a variable bill: what the last twelve months actually cost.
      var recent = s.payments.filter(function (p) { return p.day > s.last - 365; });
      var sum = recent.reduce(function (a, p) { return a + p.amount; }, 0);
      s.annual = roundHalfUp(sum * cad.perYear / recent.length);
      s.seasonal = true;
    }
    s.monthly = roundHalfUp(s.annual / 12);
    // Status: still going, or stopped?
    var ln = lastNominal(s);
    var upcoming = scheduleFrom(s, ln, 60, asOf + 800);
    var grace = Math.max(4, roundHalfUp(cad.days * 0.2));
    var missedAtEnd = upcoming.filter(function (u) { return u.due + grace < covEnd; }).length;
    s.missedAtEnd = missedAtEnd;
    if (missedAtEnd >= 1) {
      s.status = 'stopped';
      s.nextDue = null;
    } else {
      s.status = 'active';
      s.nextDue = upcoming.length ? upcoming[0].due : null;
      if (s.nextDue !== null && s.nextDue < asOf) s.late = true;
      // New if it started within the last three steps, or the last three months for shorter cadences.
      if (cad.days <= 32 && s.first - covStart >= cad.days * 0.8 && s.first >= covEnd - Math.max(3 * cad.days, CADENCE_BY_ID.quarterly.days)) s.isNew = true;
    }
    s.coverageEnd = covEnd;
    s.coverageStart = covStart;
    s.confidence = confidenceFor(s);
    s.confidenceLabel = confidenceLabel(s.confidence);
    describeSeries(s, asOf);
    return s;
  }

  function anchorText(anchor) {
    if (anchor === 'LW') return 'last working day of the month';
    if (typeof anchor === 'string') return 'last ' + DAY_NAMES[+anchor.slice(1)] + ' of the month';
    return ordinal(anchor) + (anchor === 31 ? ' (the last day)' : '');
  }
  /** When a series is due, in words: "on the 14th", "on Thursdays", "on the last Friday of the month". */
  function whenText(s) {
    var cad = CADENCE_BY_ID[s.cadence];
    if (cad.months) return (cad.months === 1 ? 'on the ' : 'around the ') + anchorText(s.anchor);
    return 'on ' + DAY_NAMES[weekday(s.last)] + 's';
  }
  function describeSeries(s, asOf) {
    var cad = CADENCE_BY_ID[s.cadence];
    var r = [];
    var when;
    if (typeof s.anchor === 'string') when = 'monthly, on the ' + anchorText(s.anchor);
    else if (cad.months === 1) when = 'monthly, usually on the ' + ordinal(s.anchor) + (s.anchor === 31 ? ' (the last day)' : '');
    else if (cad.months) when = cad.label.toLowerCase() + ', around the ' + ordinal(s.anchor);
    else when = cad.label.toLowerCase() + ', on ' + DAY_NAMES[weekday(s.last)] + 's';
    r.push(s.count + ' payments, ' + when + (s.fit.missed ? ', with ' + s.fit.missed + ' gap' + (s.fit.missed > 1 ? 's' : '') : '') + '.');
    if (s.amounts.kind === 'fixed') r.push('The same amount every time (' + money(s.typical) + ').');
    else if (s.amounts.kind === 'stepped') r.push('The amount changed ' + s.amounts.changes.length + ' time' + (s.amounts.changes.length > 1 ? 's' : '') + '; it is now ' + money(s.typical) + '.');
    else r.push('The amount varies, from ' + money(s.amounts.min) + ' to ' + money(s.amounts.max) + '; recent typical ' + money(s.typical) + '.');
    if (s.method !== 'unknown') r.push('Paid by ' + s.method + '.');
    if (s.keyword) r.push('The description mentions "' + s.keyword.toLowerCase() + '".');
    s.reasons = r;
    var flags = [];
    if (s.status === 'stopped') {
      flags.push({ id: 'stopped', tone: 'info', text: 'No payment since ' + longDate(s.last) + ' (' + s.missedAtEnd + ' expected payment' + (s.missedAtEnd > 1 ? 's' : '') + ' missing), so it looks stopped.' });
    }
    if (s.direction === 'out') {
      var intro = null;
      if (s.amounts.kind === 'stepped' && s.amounts.runs.length >= 2) {
        var r0 = s.amounts.runs[0], r1 = s.amounts.runs[1];
        if (r0.amount * 2 <= r1.amount && r0.count <= 3) {
          intro = { day: r1.start, from: r0.amount, to: r1.amount };
          flags.push({ id: 'intro', tone: 'warn', text: 'An intro price of ' + money(r0.amount) + ' ended on ' + longDate(r1.start) + '; it is now ' + money(r1.amount) + '.' });
        }
      }
      s.amounts.changes.forEach(function (c) {
        if (intro && c.day === intro.day) return;
        var pct = roundHalfUp((c.to - c.from) / c.from * 1000) / 10;
        if (c.to > c.from) flags.push({ id: 'rise', tone: asOf - c.day <= 190 ? 'warn' : 'info', day: c.day, text: 'Went up from ' + money(c.from) + ' to ' + money(c.to) + ' (+' + pct.toFixed(1) + '%) on ' + longDate(c.day) + '.' });
        else flags.push({ id: 'drop', tone: 'info', day: c.day, text: 'Went down from ' + money(c.from) + ' to ' + money(c.to) + ' on ' + longDate(c.day) + '.' });
      });
      if (s.amounts.kind === 'variable' && s.payments.length >= 6) {
        var a = s.payments.map(function (p) { return p.amount; });
        var early = median(a.slice(0, 3)), late = median(a.slice(-3));
        if (late > early * 1.15) flags.push({ id: 'creep', tone: 'info', text: 'Recent payments (' + money(late) + ' typical) are higher than the first ones (' + money(early) + ').' });
      }
      s.extras.forEach(function (d) {
        var p = s.payments.filter(function (x) { return x.day === d; })[0];
        flags.push({ id: 'double', tone: 'alert', day: d, text: 'Charged twice: an extra ' + money(p ? p.amount : s.typical) + ' on ' + longDate(d) + '. Check it was not taken in error.' });
      });
      if (s.isNew) flags.push({ id: 'new', tone: 'warn', text: 'New: first taken on ' + longDate(s.first) + '.' });
      if (s.late) flags.push({ id: 'late', tone: 'info', text: 'Due on ' + longDate(s.nextDue) + ' but not in your statement yet.' });
    }
    s.flags = flags;
  }

  function candidateFrom(s, reason) {
    return {
      id: s.id, key: s.key, name: s.name, account: s.account, cadence: s.cadence, amount: s.typical, lastDay: s.last,
      payments: s.payments.map(function (p) { return { day: p.day, amount: -p.amount, desc: p.desc, account: p.account, memo: '', type: '', category: '' }; }),
      method: s.method, category: s.category, reason: reason
    };
  }

  function flagDuplicates(series) {
    var byCat = {}, byKey = {};
    series.forEach(function (s) {
      if (s.status !== 'active') return;
      if (DUPLICATE_PRONE.indexOf(s.category) >= 0) (byCat[s.category] = byCat[s.category] || []).push(s);
      (byKey[s.key] = byKey[s.key] || []).push(s);
    });
    Object.keys(byCat).forEach(function (c) {
      var list = byCat[c];
      if (list.length < 2) return;
      var label = CATEGORY_BY_ID[c].label.toLowerCase();
      list.forEach(function (s) {
        var others = list.filter(function (o) { return o !== s; }).map(function (o) { return o.name; });
        s.flags.push({ id: 'overlap', tone: 'warn', text: 'You pay for ' + list.length + ' services in ' + label + ' (also ' + others.join(', ') + ').' });
      });
    });
    Object.keys(byKey).forEach(function (k) {
      var list = byKey[k];
      if (list.length < 2) return;
      list.forEach(function (s) {
        s.flags.push({ id: 'same-payee', tone: 'info', text: 'One of ' + list.length + ' regular payments to ' + s.name + ', at different amounts.' });
      });
    });
  }

  function findPayday(income, asOf) {
    var monthly = income.filter(function (s) { return s.status === 'active' && ['monthly', 'four-weekly', 'fortnightly', 'weekly'].indexOf(s.cadence) >= 0; });
    if (!monthly.length) return null;
    var best = monthly.slice().sort(function (a, b) { return b.monthly - a.monthly || cmp(a.id, b.id); })[0];
    var next = best.nextDue;
    if (next === null) return null;
    // Step on from nominal dates, so a payment rolled into the next month does not skip one.
    var nominal = scheduleFrom(best, lastNominal(best), 1)[0].nominal;
    while (next < asOf) {
      var sched = scheduleFrom(best, nominal, 1);
      nominal = sched[0].nominal;
      next = sched[0].due;
    }
    return { seriesId: best.id, name: best.name, next: next, typical: best.typical, cadence: best.cadence };
  }

  /* ------------------------------------------------------------------ */
  /* Forecast                                                            */
  /* ------------------------------------------------------------------ */

  /** Every expected payment from asOf for a number of days, for active series. */
  function forecast(result, days, decisions) {
    decisions = decisions || {};
    var until = result.asOf + days - 1;
    var items = [];
    result.series.concat(result.income).forEach(function (s) {
      if (s.status !== 'active') return;
      var d = decisions[s.id] || {};
      var ln = lastNominal(s);
      var sched = scheduleFrom(s, ln, 2000, until + 10);
      sched.forEach(function (u, i) {
        var due = u.due;
        var late = false;
        if (due < result.asOf) {
          if (i === 0) { due = result.asOf; late = true; } else return;
        }
        if (due > until) return;
        items.push({ day: due, nominal: u.nominal, id: s.id, name: s.name, amount: expectedAmount(s, u.due), direction: s.direction, category: s.category, decision: d.decision || null, late: late, low: s.amounts.kind === 'variable' ? s.amounts.min : s.typical, high: s.amounts.kind === 'variable' ? s.amounts.max : s.typical });
      });
    });
    items.sort(function (a, b) { return a.day - b.day || cmp(a.direction, b.direction) || b.amount - a.amount || cmp(a.id, b.id); });
    return items;
  }
  /** Total due in each calendar month of the forecast. */
  function monthTotals(items, includeDecisions) {
    var months = {}, order = [];
    items.forEach(function (it) {
      if (it.direction !== 'out') return;
      if (!includeDecisions && (it.decision === 'cancel' || it.decision === 'ignore')) return;
      if (CATEGORY_BY_ID[it.category] && CATEGORY_BY_ID[it.category].cost === false) return;
      var p = ymd(it.day), k = p.y + '-' + pad2(p.m);
      if (!months[k]) { months[k] = { key: k, y: p.y, m: p.m, total: 0, essential: 0, optional: 0, count: 0 }; order.push(k); }
      months[k].total += it.amount;
      months[k].count++;
      if (CATEGORY_BY_ID[it.category] && CATEGORY_BY_ID[it.category].essential) months[k].essential += it.amount;
      else months[k].optional += it.amount;
    });
    return order.sort().map(function (k) { return months[k]; });
  }

  /* ------------------------------------------------------------------ */
  /* Decisions and the plan                                              */
  /* ------------------------------------------------------------------ */

  var DECISIONS = ['keep', 'cancel', 'review', 'ignore'];

  function isCost(s) { return s.direction === 'out' && s.status === 'active' && (!CATEGORY_BY_ID[s.category] || CATEGORY_BY_ID[s.category].cost !== false); }

  /** A suggestion for each series, with the reason, before the user decides. */
  function suggest(s) {
    var cat = CATEGORY_BY_ID[s.category] || CATEGORY_BY_ID.other;
    var ids = s.flags.map(function (f) { return f.id; });
    if (s.status === 'stopped') return { decision: null, text: 'Looks stopped already. Check it does not restart.' };
    if (cat.cost === false) return { decision: 'ignore', text: 'Money to your own savings, not a cost.' };
    if (ids.indexOf('double') >= 0) return { decision: 'review', text: 'Check the double charge with the company.' };
    if (ids.indexOf('intro') >= 0) return { decision: 'review', text: 'The intro price has ended. Still worth the full price?' };
    if (ids.indexOf('overlap') >= 0) return { decision: 'review', text: 'Do you need all of these?' };
    if (ids.indexOf('rise') >= 0 && s.flags.some(function (f) { return f.id === 'rise' && f.tone === 'warn'; })) return { decision: 'review', text: 'The price went up recently. Shop around or ask for a better deal.' };
    if (ids.indexOf('new') >= 0) return { decision: 'review', text: 'New this month. Did you mean to sign up?' };
    if (cat.essential) return { decision: 'keep', text: 'An essential bill. Keep, but check you are on a good deal.' };
    return { decision: 'review', text: 'Optional. Did you use it in the last month?' };
  }

  function noticeDaysFor(s) { return s.method === 'direct debit' || s.method === 'standing order' ? 3 : 2; }

  /** How to stop a payment, by how it is paid. */
  function howToStop(s) {
    switch (s.method) {
      case 'direct debit':
        return ['Cancel the service with ' + s.name + ' first, so you are not left owing anything under the contract.', 'Then cancel the Direct Debit in your banking app, or ask your bank to, at least a couple of working days before it is due.', 'If a Direct Debit is taken in error after that, the Direct Debit Guarantee lets you claim it back from your bank.'];
      case 'standing order':
        return ['You set up standing orders, so only you can stop them: cancel it in your banking app or online banking.', 'Do it at least a working day before it is due.', 'Tell the person or company you pay, so they are not surprised.'];
      case 'card':
        return ['Cancel in your account settings on ' + s.name + "'s website or app (or the app store you subscribed through).", 'Keep the confirmation email or a screenshot.', 'If it charges you again after you cancelled, ask your card provider to stop the recurring payment and dispute the charge.'];
      case 'transfer':
        return ['This is a payment you send yourself. Stop sending it, or cancel any scheduled transfer in your banking app.'];
      default:
        return ['Find how you pay ' + s.name + ' (Direct Debit, card or standing order) and cancel with the company first.', 'Then stop the payment in your banking app if it is a Direct Debit or standing order.'];
    }
  }

  function cancelMessage(s, details) {
    details = details || {};
    var yourName = details.name || '[your name]';
    var ref = details.account || '[your account email or customer number]';
    var last = s.payments[s.payments.length - 1];
    return [
      'Subject: Please cancel my ' + s.name + ' ' + (s.category === 'gym' || s.category === 'memberships' ? 'membership' : 'subscription'),
      '',
      'Hello,',
      '',
      'Please cancel my ' + s.name + ' ' + (s.category === 'gym' || s.category === 'memberships' ? 'membership' : 'subscription') + ' and stop all further payments from today.',
      '',
      'My account: ' + ref,
      'Last payment: ' + money(last.amount) + ' on ' + longDate(last.day),
      '',
      'Please confirm in writing that it is cancelled and that no further payments will be taken. If any payment is taken after today, I will ask for it to be refunded.',
      '',
      'Thank you,',
      yourName
    ].join('\n');
  }

  /** Summarise decisions: committed spending, savings from cancelling, and the action list. */
  function plan(result, decisions, options) {
    decisions = decisions || {};
    options = options || {};
    var asOf = result.asOf;
    var fc = forecast(result, 365, decisions);
    var costs = result.series.filter(isCost);
    var totals = { monthly: 0, annual: 0, essentialMonthly: 0, optionalMonthly: 0, keepMonthly: 0, cancelMonthly: 0, cancelAnnual: 0, cancelNext12: 0, reviewMonthly: 0, undecidedMonthly: 0, count: costs.length };
    var actions = [];
    costs.forEach(function (s) {
      var d = decisions[s.id] || {};
      var decision = d.decision || null;
      var cat = CATEGORY_BY_ID[s.category] || CATEGORY_BY_ID.other;
      if (decision === 'ignore') return;
      totals.monthly += s.monthly; totals.annual += s.annual;
      if (cat.essential) totals.essentialMonthly += s.monthly; else totals.optionalMonthly += s.monthly;
      if (decision === 'keep') totals.keepMonthly += s.monthly;
      else if (decision === 'cancel') {
        totals.cancelMonthly += s.monthly; totals.cancelAnnual += s.annual;
        var next12 = 0;
        fc.forEach(function (it) { if (it.id === s.id) next12 += it.amount; });
        totals.cancelNext12 += next12;
        var notice = d.noticeDays !== undefined && d.noticeDays !== null ? d.noticeDays : noticeDaysFor(s);
        var by = s.nextDue !== null ? s.nextDue - notice : asOf;
        if (by < asOf) by = asOf;
        actions.push({ id: s.id, name: s.name, method: s.method, nextDue: s.nextDue, cancelBy: by, amount: s.typical, cadence: s.cadence, saveNext12: next12, annual: s.annual, steps: howToStop(s), message: cancelMessage(s, options.details), note: d.note || '' });
      } else if (decision === 'review') totals.reviewMonthly += s.monthly;
      else totals.undecidedMonthly += s.monthly;
    });
    actions.sort(function (a, b) { return a.cancelBy - b.cancelBy || b.amount - a.amount || cmp(a.id, b.id); });
    return { totals: totals, actions: actions, forecast: fc };
  }

  /* ------------------------------------------------------------------ */
  /* Since your last review                                              */
  /* ------------------------------------------------------------------ */

  /**
   * Compare the regulars now with a saved review: what is new, what changed
   * price, what stopped, and anything still charging after you decided to
   * cancel it.
   */
  function sinceLastReview(result, saved) {
    if (!saved || !saved.reviewedOn) return null;
    var reviewed = typeof saved.reviewedOn === 'number' ? saved.reviewedOn : fromIso(saved.reviewedOn);
    var known = saved.known || {};
    var decisions = saved.decisions || {};
    var out = { reviewedOn: reviewed, stillCharging: [], newSince: [], priceChanges: [], stoppedSince: [] };
    result.series.forEach(function (s) {
      var d = decisions[s.id];
      if (d && d.decision === 'cancel') {
        var decided = typeof d.decidedOn === 'number' ? d.decidedOn : (fromIso(d.decidedOn) || reviewed);
        var grace = d.noticeDays !== undefined && d.noticeDays !== null ? d.noticeDays : noticeDaysFor(s);
        var after = s.payments.filter(function (p) { return p.day > decided + grace; });
        if (after.length) out.stillCharging.push({ id: s.id, name: s.name, decidedOn: decided, payments: after, total: after.reduce(function (a, p) { return a + p.amount; }, 0), method: s.method });
      }
      if (!known[s.id] && s.status === 'active' && s.last > reviewed) out.newSince.push({ id: s.id, name: s.name, first: s.first, amount: s.typical, cadence: s.cadence });
      if (known[s.id] && known[s.id].typical !== undefined && known[s.id].typical !== s.typical && s.status === 'active' && s.amounts.kind !== 'variable' && known[s.id].kind !== 'variable') out.priceChanges.push({ id: s.id, name: s.name, from: known[s.id].typical, to: s.typical });
      if (known[s.id] && known[s.id].status === 'active' && s.status === 'stopped') out.stoppedSince.push({ id: s.id, name: s.name, last: s.last });
    });
    return out;
  }

  /* ------------------------------------------------------------------ */
  /* Files the app hands back                                            */
  /* ------------------------------------------------------------------ */

  function csvCell(v) {
    var s = v === null || v === undefined ? '' : String(v);
    if (/[",\r\n]/.test(s) || /^\s|\s$/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
  }
  function toCsv(rows) { return '\ufeff' + rows.map(function (r) { return r.map(csvCell).join(','); }).join('\r\n') + '\r\n'; }

  var DECISION_LABELS = { keep: 'Keep', cancel: 'Cancel', review: 'Review', ignore: 'Not a cost' };

  /** The register of regular payments as CSV. */
  function registerCsv(result, decisions) {
    decisions = decisions || {};
    var rows = [['Name', 'Category', 'Paid by', 'How often', 'Typical amount', 'Monthly equivalent', 'Yearly cost', 'Payments seen', 'First seen', 'Last seen', 'Next due', 'Status', 'Confidence', 'Checks', 'Decision', 'Note', 'Accounts']];
    result.series.forEach(function (s) {
      var d = decisions[s.id] || {};
      rows.push([
        s.name, (CATEGORY_BY_ID[s.category] || CATEGORY_BY_ID.other).label, s.method, CADENCE_BY_ID[s.cadence].label,
        plainMoney(s.typical), plainMoney(s.monthly), plainMoney(s.annual), s.count, iso(s.first), iso(s.last),
        s.nextDue !== null ? iso(s.nextDue) : '', s.status, s.confidence, s.flags.map(function (f) { return f.text; }).join(' '),
        d.decision ? DECISION_LABELS[d.decision] : '', d.note || '', s.account
      ]);
    });
    return toCsv(rows);
  }
  /** Committed spending by month for the next twelve months, by category, for a spreadsheet. */
  function budgetCsv(result, decisions, months) {
    months = months || 12;
    decisions = decisions || {};
    var start = ymd(result.asOf);
    var keys = [];
    for (var i = 0; i < months; i++) {
      var total = start.y * 12 + start.m - 1 + i;
      keys.push(Math.floor(total / 12) + '-' + pad2(total % 12 + 1));
    }
    var lastMonth = keys[keys.length - 1].split('-');
    var until = dayFromYMD(+lastMonth[0], +lastMonth[1], daysInMonth(+lastMonth[0], +lastMonth[1]));
    var items = forecast(result, until - result.asOf + 1, decisions);
    var cats = {}, catOrder = [];
    items.forEach(function (it) {
      if (it.direction !== 'out' || it.decision === 'cancel' || it.decision === 'ignore') return;
      var c = CATEGORY_BY_ID[it.category] || CATEGORY_BY_ID.other;
      if (c.cost === false) return;
      if (!cats[c.id]) { cats[c.id] = {}; catOrder.push(c.id); }
      var p = ymd(it.day), k = p.y + '-' + pad2(p.m);
      cats[c.id][k] = (cats[c.id][k] || 0) + it.amount;
    });
    catOrder.sort(function (a, b) { return CATEGORIES.indexOf(CATEGORY_BY_ID[a]) - CATEGORIES.indexOf(CATEGORY_BY_ID[b]); });
    var rows = [['Category'].concat(keys.map(function (k) { var p = k.split('-'); return MONTH_NAMES[+p[1] - 1].slice(0, 3) + ' ' + p[0]; })).concat(['Total'])];
    var colTotals = keys.map(function () { return 0; });
    catOrder.forEach(function (c) {
      var row = [CATEGORY_BY_ID[c].label], sum = 0;
      keys.forEach(function (k, i) { var v = cats[c][k] || 0; sum += v; colTotals[i] += v; row.push(plainMoney(v)); });
      row.push(plainMoney(sum));
      rows.push(row);
    });
    rows.push(['Total'].concat(colTotals.map(plainMoney)).concat([plainMoney(colTotals.reduce(function (a, b) { return a + b; }, 0))]));
    return toCsv(rows);
  }

  function icsEscape(s) { return String(s).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n'); }
  function utf8Length(ch) { var c = ch.codePointAt(0); return c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4; }
  /** Fold a content line at 75 bytes, as the calendar standard asks. */
  function icsFold(line) {
    var out = [], cur = '', bytes = 0, limit = 75;
    Array.from(line).forEach(function (ch) {
      var b = utf8Length(ch);
      if (bytes + b > limit) { out.push(cur); cur = ' '; bytes = 1; limit = 75; }
      cur += ch; bytes += b;
    });
    out.push(cur);
    return out.join('\r\n');
  }
  function icsDate(day) { return iso(day).replace(/-/g, ''); }
  function slug(s) { return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'item'; }

  /**
   * A calendar of upcoming payments (with a reminder the day before) and
   * cancel-by reminders. options: {days, includeIncome, reminderDays}
   */
  function buildIcs(result, decisions, options) {
    options = options || {};
    decisions = decisions || {};
    var days = options.days || 92;
    var stamp = icsDate(result.asOf) + 'T090000Z';
    var lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Still paying//Regular payments//EN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'X-WR-CALNAME:Regular payments'];
    var items = forecast(result, days, decisions);
    var pl = plan(result, decisions, options);
    var cancelIds = {};
    pl.actions.forEach(function (a) { cancelIds[a.id] = 1; });
    var count = 0;
    items.forEach(function (it) {
      if (it.direction === 'in' && !options.includeIncome) return;
      if (it.decision === 'ignore') return;
      var s = findSeries(result, it.id);
      var label = it.direction === 'in' ? 'Expected in: ' : '';
      var amountText = s && s.amounts.kind === 'variable' ? 'about ' + money(it.amount) : money(it.amount);
      var summary = label + amountText + ' ' + it.name + (cancelIds[it.id] ? ' (you plan to cancel)' : '');
      var desc = [(CADENCE_BY_ID[s.cadence].label) + ' payment' + (s.method !== 'unknown' ? ' by ' + s.method : '') + '.', s.amounts.kind === 'variable' ? 'Recent payments ranged from ' + money(s.amounts.min) + ' to ' + money(s.amounts.max) + '.' : '', 'Found by Still paying from your bank export.'].filter(Boolean).join(' ');
      lines.push('BEGIN:VEVENT');
      lines.push('UID:' + slug(it.id) + '-' + icsDate(it.day) + '@still-paying.local');
      lines.push('DTSTAMP:' + stamp);
      lines.push('DTSTART;VALUE=DATE:' + icsDate(it.day));
      lines.push('DTEND;VALUE=DATE:' + icsDate(it.day + 1));
      lines.push('SUMMARY:' + icsEscape(summary));
      lines.push('DESCRIPTION:' + icsEscape(desc));
      lines.push('TRANSP:TRANSPARENT');
      lines.push('CATEGORIES:' + icsEscape((CATEGORY_BY_ID[it.category] || CATEGORY_BY_ID.other).label));
      if (it.direction === 'out' && (options.reminders !== false)) {
        lines.push('BEGIN:VALARM', 'ACTION:DISPLAY', 'DESCRIPTION:' + icsEscape(summary + ' leaves tomorrow'), 'TRIGGER:-PT15H', 'END:VALARM');
      }
      lines.push('END:VEVENT');
      count++;
    });
    pl.actions.forEach(function (a) {
      var summary = 'Cancel ' + a.name + ' before ' + (a.nextDue !== null ? shortDate(a.nextDue) : 'the next payment');
      var desc = a.steps.join(' ') + ' Next payment ' + money(a.amount) + (a.nextDue !== null ? ' on ' + longDate(a.nextDue) : '') + '.';
      lines.push('BEGIN:VEVENT');
      lines.push('UID:cancel-' + slug(a.id) + '-' + icsDate(a.cancelBy) + '@still-paying.local');
      lines.push('DTSTAMP:' + stamp);
      lines.push('DTSTART;VALUE=DATE:' + icsDate(a.cancelBy));
      lines.push('DTEND;VALUE=DATE:' + icsDate(a.cancelBy + 1));
      lines.push('SUMMARY:' + icsEscape(summary));
      lines.push('DESCRIPTION:' + icsEscape(desc));
      lines.push('BEGIN:VALARM', 'ACTION:DISPLAY', 'DESCRIPTION:' + icsEscape(summary), 'TRIGGER:PT9H', 'END:VALARM');
      lines.push('END:VEVENT');
      count++;
    });
    lines.push('END:VCALENDAR');
    return { text: lines.map(icsFold).join('\r\n') + '\r\n', events: count };
  }
  function findSeries(result, id) {
    var all = result.series.concat(result.income);
    for (var i = 0; i < all.length; i++) if (all[i].id === id) return all[i];
    return null;
  }

  /** A template showing the layout that always reads cleanly. */
  function templateCsv() {
    return toCsv([
      ['Date', 'Description', 'Type', 'Amount', 'Balance'],
      ['01/11/2026', 'HARBOUR LETTINGS RENT', 'Standing order', '-525.00', '812.40'],
      ['03/11/2026', 'IRONWORKS GYM', 'Card payment', '-24.99', '787.41'],
      ['12/11/2026', 'BRIGHTSPARK ENERGY', 'Direct debit', '-58.20', '729.21'],
      ['27/11/2026', 'CAMPUS CAFE PAYROLL', 'Bank credit', '412.50', '1141.71']
    ]);
  }

  /* ------------------------------------------------------------------ */
  /* Saving and reopening a review                                       */
  /* ------------------------------------------------------------------ */

  function projectFile(state) {
    var tx = state.transactions.map(function (t) { return [iso(t.day), t.amount, t.desc, t.memo || '', t.type || '', t.category || '', t.account]; });
    var known = {};
    (state.result ? state.result.series : []).forEach(function (s) { known[s.id] = { typical: s.typical, status: s.status, name: s.name, kind: s.amounts.kind }; });
    var decisions = {};
    Object.keys(state.decisions || {}).forEach(function (id) {
      var d = state.decisions[id];
      decisions[id] = { decision: d.decision || null, note: d.note || '', decidedOn: typeof d.decidedOn === 'number' ? iso(d.decidedOn) : (d.decidedOn || null), noticeDays: d.noticeDays === undefined ? null : d.noticeDays };
    });
    return JSON.stringify({
      format: 'still-paying-review', version: 1, reviewedOn: iso(state.reviewedOn !== undefined ? state.reviewedOn : state.result.asOf),
      accounts: (state.accounts || []).map(function (a) { return { account: a.account, files: a.files }; }),
      transactions: tx, decisions: decisions, known: known, aliases: state.aliases || {}, names: state.names || {}, manual: state.manual || [], overrides: state.overrides || {}, details: state.details || {}
    }, null, 1);
  }
  function readProject(text) {
    var data;
    try { data = JSON.parse(stripBom(String(text))); } catch (e) { return { error: 'This file is not a saved review (it is not valid JSON).' }; }
    if (!data || data.format !== 'still-paying-review') return { error: 'This JSON file is not a Still paying review.' };
    if (data.version > 1) return { error: 'This review was saved by a newer version of the tool.' };
    var tx = [], bad = 0;
    (data.transactions || []).forEach(function (r, i) {
      var day = fromIso(r[0]);
      if (day === null || typeof r[1] !== 'number' || !isFinite(r[1])) { bad++; return; }
      tx.push({ day: day, amount: roundHalfUp(r[1]), desc: String(r[2] || ''), memo: String(r[3] || ''), type: String(r[4] || ''), category: String(r[5] || ''), account: String(r[6] || 'Account'), source: 'saved review', line: i + 1 });
    });
    var decisions = {};
    Object.keys(data.decisions || {}).forEach(function (id) {
      var d = data.decisions[id] || {};
      if (d.decision && DECISIONS.indexOf(d.decision) < 0) return;
      decisions[id] = { decision: d.decision || null, note: String(d.note || ''), decidedOn: d.decidedOn ? fromIso(d.decidedOn) : null, noticeDays: typeof d.noticeDays === 'number' ? d.noticeDays : undefined };
    });
    return {
      reviewedOn: fromIso(data.reviewedOn), transactions: tx, decisions: decisions, known: data.known || {},
      aliases: data.aliases || {}, names: data.names || {}, manual: data.manual || [], overrides: data.overrides || {}, details: data.details || {}, accounts: data.accounts || [], badRows: bad
    };
  }

  /* ------------------------------------------------------------------ */
  /* One call for the whole job                                          */
  /* ------------------------------------------------------------------ */

  /**
   * Read every file, merge them, find the regulars and summarise.
   * input: {files: [{name, text, account, options}], extra: [transactions], aliases, names, manual, asOf}
   */
  function analyse(input) {
    var statements = (input.files || []).map(function (f) {
      var opts = Object.assign({}, f.options || {});
      if (f.account) opts.account = f.account;
      var st = parseStatement(f.text, f.name, opts);
      st.accountGiven = !!f.account;
      return st;
    });
    var pseudo = [];
    if (input.extra && input.extra.length) {
      var ex = { name: 'saved review', account: '', transactions: input.extra };
      finishRange(ex);
      // Saved transactions can cover several accounts; split them so coverage stays per account.
      var byAcc = {};
      input.extra.forEach(function (t) { (byAcc[t.account] = byAcc[t.account] || []).push(t); });
      Object.keys(byAcc).sort().forEach(function (a) {
        var st = { name: 'saved review', account: a, transactions: byAcc[a] };
        finishRange(st);
        pseudo.push(st);
      });
    }
    var linked = linkSameAccounts(pseudo.concat(statements));
    var merged = mergeStatements(pseudo.concat(statements));
    merged.linked = linked;
    var result = findRegulars(merged.transactions, { asOf: input.asOf, aliases: input.aliases, names: input.names, manual: input.manual, overrides: input.overrides });
    return { statements: statements, merged: merged, result: result };
  }

  /** A compact, stable summary used to check the Python companion gives the same answers. */
  function summary(result) {
    var pick = function (s) {
      return {
        id: s.id, name: s.name, cadence: s.cadence, count: s.count, first: iso(s.first), last: iso(s.last), typical: s.typical, monthly: s.monthly, annual: s.annual,
        kind: s.amounts.kind, status: s.status, nextDue: s.nextDue === null ? null : iso(s.nextDue), method: s.method, category: s.category, confidence: s.confidence,
        flags: s.flags.map(function (f) { return f.id; })
      };
    };
    return {
      asOf: iso(result.asOf), series: result.series.map(pick), income: result.income.map(pick),
      candidates: result.candidates.map(function (c) { return { id: c.id, cadence: c.cadence, amount: c.amount }; }),
      payday: result.payday ? { id: result.payday.seriesId, next: iso(result.payday.next) } : null
    };
  }

  var api = {
    VERSION: VERSION, CADENCES: CADENCES, CATEGORIES: CATEGORIES, CATEGORY_BY_ID: CATEGORY_BY_ID, CADENCE_BY_ID: CADENCE_BY_ID, ROLE_LABELS: ROLE_LABELS, DECISIONS: DECISIONS, DECISION_LABELS: DECISION_LABELS,
    dayFromYMD: dayFromYMD, ymd: ymd, iso: iso, fromIso: fromIso, weekday: weekday, addMonths: addMonths, daysInMonth: daysInMonth,
    shortDate: shortDate, longDate: longDate, ordinal: ordinal, MONTH_NAMES: MONTH_NAMES, DAY_NAMES: DAY_NAMES,
    easterSunday: easterSunday, bankHolidays: bankHolidays, isWorkingDay: isWorkingDay, nextWorkingDay: nextWorkingDay,
    roundHalfUp: roundHalfUp, money: money, plainMoney: plainMoney, parseAmount: parseAmount,
    dateShape: dateShape, detectDateOrder: detectDateOrder, parseDate: parseDate,
    parseDelimited: parseDelimited, sniffDelimiter: sniffDelimiter, mapHeader: mapHeader, headerKey: headerKey, inferColumns: inferColumns,
    parseCsv: parseCsv, parseStatement: parseStatement, mergeStatements: mergeStatements, linkSameAccounts: linkSameAccounts, METHODS: METHODS, defaultAccount: defaultAccount,
    cleanDescription: cleanDescription, payeeKey: payeeKey, displayName: displayName, groupKeys: groupKeys,
    categorise: categorise, paymentMethod: paymentMethod, fitCadence: fitCadence, anchorDay: anchorDay, amountProfile: amountProfile,
    explainGroup: explainGroup, findRegulars: findRegulars, matchTransfers: matchTransfers, forecast: forecast, monthTotals: monthTotals,
    suggest: suggest, howToStop: howToStop, cancelMessage: cancelMessage, plan: plan, noticeDaysFor: noticeDaysFor, isCost: isCost,
    sinceLastReview: sinceLastReview, registerCsv: registerCsv, budgetCsv: budgetCsv, buildIcs: buildIcs, icsFold: icsFold, icsEscape: icsEscape,
    toCsv: toCsv, templateCsv: templateCsv, projectFile: projectFile, readProject: readProject, analyse: analyse, summary: summary, findSeries: findSeries,
    lastNominal: lastNominal, scheduleFrom: scheduleFrom, whenText: whenText, anchorText: anchorText, expectedAmount: expectedAmount, nominalInMonth: nominalInMonth, monthlyCost: monthlyCost, annualCost: annualCost
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.StillPaying = api;
})(typeof window !== 'undefined' ? window : this);
/* MODEL END */
