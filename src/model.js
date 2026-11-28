/* MODEL START */
/*
 * Round trips: the model. Reads fills exports, matches them into round-trip
 * trades first in, first out, applies the journal, checks the rules and works
 * out the statistics and the weekly review. Everything here is plain
 * JavaScript with no access to the page, so Node can run it for the tests and
 * the Python companion can be checked against it.
 *
 * Units: money is held as whole cents (or pence) of the trade's currency,
 * prices as whole millionths of a currency unit, quantities as whole
 * millionths of a share or contract, dates as day numbers (days since
 * 1970-01-01) and times as seconds into the day.
 */
(function (root) {
  'use strict';

  var M = {};
  var PRICE_SCALE = 1000000;
  var QTY_SCALE = 1000000;
  var DAY = 86400;
  M.PRICE_SCALE = PRICE_SCALE;
  M.QTY_SCALE = QTY_SCALE;
  M.VERSION = 1;

  /* ---------- small helpers ---------- */

  function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
  // Round half away from zero to a whole number.
  function rnd(x) { return x < 0 ? -Math.floor(-x + 0.5) : Math.floor(x + 0.5); }
  function str(v) { return v === null || v === undefined ? '' : String(v); }
  function trim(v) { return str(v).replace(/^[\s\u00a0\ufeff]+|[\s\u00a0]+$/g, ''); }
  function pad2(n) { return n < 10 ? '0' + n : String(n); }
  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  M.cmp = cmp;
  M.rnd = rnd;

  /* ---------- dates ---------- */

  function daysFromCivil(y, m, d) {
    y -= m <= 2 ? 1 : 0;
    var era = Math.floor(y / 400);
    var yoe = y - era * 400;
    var mp = (m + 9) % 12;
    var doy = Math.floor((153 * mp + 2) / 5) + d - 1;
    var doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
    return era * 146097 + doe - 719468;
  }
  function civil(z) {
    z += 719468;
    var era = Math.floor(z / 146097);
    var doe = z - era * 146097;
    var yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
    var y = yoe + era * 400;
    var doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
    var mp = Math.floor((5 * doy + 2) / 153);
    var d = doy - Math.floor((153 * mp + 2) / 5) + 1;
    var m = mp < 10 ? mp + 3 : mp - 9;
    return [m <= 2 ? y + 1 : y, m, d];
  }
  function daysInMonth(y, m) {
    if (m === 2) return (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0 ? 29 : 28;
    return [4, 6, 9, 11].indexOf(m) >= 0 ? 30 : 31;
  }
  function makeDay(y, m, d) {
    if (!(y >= 1900 && y <= 2200 && m >= 1 && m <= 12 && d >= 1 && d <= daysInMonth(y, m))) return null;
    return daysFromCivil(y, m, d);
  }
  function toIso(day) { var c = civil(day); return c[0] + '-' + pad2(c[1]) + '-' + pad2(c[2]); }
  function fromIso(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(trim(s));
    return m ? makeDay(+m[1], +m[2], +m[3]) : null;
  }
  // 0 is Monday.
  function weekday(day) { return ((day + 3) % 7 + 7) % 7; }
  function weekStart(day) { return day - weekday(day); }
  M.daysFromCivil = daysFromCivil;
  M.civil = civil;
  M.toIso = toIso;
  M.fromIso = fromIso;
  M.weekday = weekday;
  M.weekStart = weekStart;

  var MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
  var MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  var DAY_LONG = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  M.DAY_NAMES = DAY_NAMES;

  function monthIndex(word) {
    var w = word.toLowerCase();
    if (w === 'sept') w = 'sep';
    if (w.length < 3) return -1;
    for (var i = 0; i < 12; i++) {
      var full = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'][i];
      if (w === MONTHS[i] || w === full) return i + 1;
    }
    return -1;
  }
  function fullYear(y) {
    var n = +y;
    if (y.length === 2) return n < 70 ? 2000 + n : 1900 + n;
    return n;
  }

  // Seconds into the day, or null. Accepts 9:31, 09:31:04, 9:31:04.250 AM, 0931 (only when compact is set).
  function parseTime(text) {
    var s = trim(text).toUpperCase();
    if (!s) return null;
    var m = /^(\d{1,2})[:.](\d{2})(?:[:.](\d{2})(?:[.,]\d+)?)?\s*(AM|PM|A\.M\.|P\.M\.)?\s*(?:Z|UTC|GMT|BST|ET|EST|EDT|CT|CST|CDT|[+-]\d{2}:?\d{2})?$/.exec(s);
    if (!m) {
      m = /^(\d{2})(\d{2})(\d{2})?$/.exec(s);
      if (!m) return null;
    }
    var h = +m[1], mi = +m[2], se = m[3] ? +m[3] : 0;
    var ap = m[4] ? m[4].charAt(0) : '';
    if (ap) {
      if (h < 1 || h > 12) return null;
      if (ap === 'P' && h < 12) h += 12;
      if (ap === 'A' && h === 12) h = 0;
    }
    if (h > 23 || mi > 59 || se > 59) return null;
    return h * 3600 + mi * 60 + se;
  }
  M.parseTime = parseTime;

  // The two leading numbers of a numeric date such as 07/10/2026, used to tell day-first from month-first.
  function dateShape(text) {
    var m = /^(\d{1,2})[\/.\-](\d{1,2})[\/.\-](\d{2}|\d{4})(?![\d])/.exec(trim(text));
    return m ? [+m[1], +m[2]] : null;
  }
  M.dateShape = dateShape;

  // Which order the numeric dates in a column use: 'DMY', 'MDY' or '' when nothing decides it.
  function detectDateOrder(values) {
    var dmy = false, mdy = false;
    for (var i = 0; i < values.length; i++) {
      var s = dateShape(values[i]);
      if (!s) continue;
      if (s[0] > 12 && s[1] <= 12) dmy = true;
      if (s[1] > 12 && s[0] <= 12) mdy = true;
    }
    if (dmy && !mdy) return 'DMY';
    if (mdy && !dmy) return 'MDY';
    return dmy && mdy ? 'MIXED' : '';
  }
  M.detectDateOrder = detectDateOrder;

  // A date with an optional time. Returns {day, sec} (sec null when no time is given) or null.
  function parseDateTime(text, order) {
    var s = trim(text).replace(/^(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+/i, '');
    if (!s) return null;
    var m, day = null, rest = '';
    if ((m = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T\s,;]+(.*))?$/.exec(s))) {
      day = makeDay(+m[1], +m[2], +m[3]); rest = m[4] || '';
    } else if ((m = /^(\d{4})(\d{2})(\d{2})(?:[T\s,;]+(.*))?$/.exec(s))) {
      day = makeDay(+m[1], +m[2], +m[3]); rest = m[4] || '';
    } else if ((m = /^(\d{4})[\/.](\d{1,2})[\/.](\d{1,2})(?:[T\s,;]+(.*))?$/.exec(s))) {
      day = makeDay(+m[1], +m[2], +m[3]); rest = m[4] || '';
    } else if ((m = /^(\d{1,2})[\/.\-](\d{1,2})[\/.\-](\d{2}|\d{4})(?:[T\s,;]+(.*))?$/.exec(s))) {
      var a = +m[1], b = +m[2], y = fullYear(m[3]);
      if (order === 'MDY') day = makeDay(y, a, b);
      else day = makeDay(y, b, a);
      rest = m[4] || '';
    } else if ((m = /^(\d{1,2})(?:st|nd|rd|th)?[\s\-]+([A-Za-z]{3,9})\.?[\s\-,]+(\d{4}|\d{2})(?:[T\s,;]+(.*))?$/.exec(s))) {
      var mi = monthIndex(m[2]);
      day = mi > 0 ? makeDay(fullYear(m[3]), mi, +m[1]) : null; rest = m[4] || '';
    } else if ((m = /^([A-Za-z]{3,9})\.?[\s\-]+(\d{1,2})(?:st|nd|rd|th)?,?[\s\-]+(\d{4}|\d{2})(?:[T\s,;]+(.*))?$/.exec(s))) {
      var mj = monthIndex(m[1]);
      day = mj > 0 ? makeDay(fullYear(m[3]), mj, +m[2]) : null; rest = m[4] || '';
    }
    if (day === null) return null;
    rest = trim(rest);
    if (!rest) return { day: day, sec: null };
    var sec = parseTime(rest);
    if (sec === null) return null;
    return { day: day, sec: sec };
  }
  M.parseDateTime = parseDateTime;

  /* ---------- numbers ---------- */

  // A number as text, cleaned of currency signs, thousands separators and brackets.
  // Returns {neg, int, frac, cur, pence} or null when it is not a number.
  function readNumber(text, decimalComma) {
    var s = trim(text);
    if (!s) return null;
    var neg = false, cur = '', pence = false;
    if (/^\(.*\)$/.test(s)) { neg = true; s = trim(s.slice(1, -1)); }
    var codes = /^(USD|GBP|EUR|GBX|CHF|JPY|CAD|AUD|HKD|SGD)\s*/i;
    var mm = codes.exec(s);
    if (mm) { cur = mm[1].toUpperCase(); s = s.slice(mm[0].length); }
    mm = /\s*(USD|GBP|EUR|GBX|CHF|JPY|CAD|AUD|HKD|SGD)$/i.exec(s);
    if (mm) { cur = mm[1].toUpperCase(); s = s.slice(0, s.length - mm[0].length); }
    s = trim(s);
    for (var pass = 0; pass < 2; pass++) {
      var c = s.charAt(0);
      if (c === '-' || c === '\u2212') { neg = !neg; s = trim(s.slice(1)); } else if (c === '+') { s = trim(s.slice(1)); }
      c = s.charAt(0);
      if (c === '$') { cur = cur || 'USD'; s = trim(s.slice(1)); } else if (c === '£') { cur = cur || 'GBP'; s = trim(s.slice(1)); } else if (c === '€') { cur = cur || 'EUR'; s = trim(s.slice(1)); }
    }
    if (/-$/.test(s)) { neg = !neg; s = trim(s.slice(0, -1)); }
    if (/^[\d.,\s']+p$/i.test(s)) { pence = true; s = trim(s.slice(0, -1)); }
    s = s.replace(/[\s\u00a0\u202f']/g, '');
    if (decimalComma) {
      s = s.replace(/\./g, '').replace(',', '.');
    } else if (s.indexOf(',') >= 0) {
      if (s.indexOf('.') >= 0) s = s.replace(/,/g, '');
      else if (/^\d{1,3}(,\d{3})+$/.test(s)) s = s.replace(/,/g, '');
      else if (/^\d+,\d{1,2}$/.test(s)) s = s.replace(',', '.');
      else return null;
    }
    var m = /^(\d*)(?:\.(\d*))?$/.exec(s);
    if (!m || (m[1] === '' && (m[2] === undefined || m[2] === ''))) return null;
    return { neg: neg, int: m[1].replace(/^0+(?=\d)/, ''), frac: m[2] || '', cur: cur, pence: pence };
  }
  M.readNumber = readNumber;

  // A read number as a whole number of 10^-dp units, rounded half away from zero.
  function scaled(n, dp) {
    if (!n) return null;
    var frac = n.frac + '000000000000';
    var whole = Number(n.int || '0') * Math.pow(10, dp) + Number(frac.slice(0, dp) || '0');
    if (+frac.charAt(dp) >= 5) whole += 1;
    return n.neg && whole !== 0 ? -whole : whole;
  }
  function toFloat(n) {
    if (!n) return null;
    var v = Number((n.int || '0') + '.' + (n.frac || '0'));
    return n.neg ? -v : v;
  }
  function parseCents(text, decimalComma) { return scaled(readNumber(text, decimalComma), 2); }
  function parseMicro(text, decimalComma) { return scaled(readNumber(text, decimalComma), 6); }
  function parseFloatText(text) { return toFloat(readNumber(text, false)); }
  M.scaled = scaled;
  M.parseCents = parseCents;
  M.parseMicro = parseMicro;
  M.parseFloatText = parseFloatText;

  /* ---------- delimited text ---------- */

  function sniffDelimiter(text) {
    var lines = str(text).replace(/^\ufeff/, '').split(/\r\n|\n|\r/).filter(function (l) { return trim(l) !== ''; }).slice(0, 25);
    var best = ',', bestScore = -1;
    [',', ';', '\t', '|'].forEach(function (d) {
      var linesWith = 0, total = 0;
      lines.forEach(function (line) {
        var n = 0, q = false;
        for (var i = 0; i < line.length; i++) {
          var c = line.charAt(i);
          if (c === '"') q = !q;
          else if (c === d && !q) n++;
        }
        if (n > 0) linesWith++;
        total += n;
      });
      var score = linesWith * 100000 + total;
      if (score > bestScore) { best = d; bestScore = score; }
    });
    return best;
  }
  M.sniffDelimiter = sniffDelimiter;

  // Rows of cells, with the line each row starts on. Handles quotes, doubled quotes and line breaks inside quotes.
  function parseDelimited(text, delim) {
    var s = str(text);
    if (s.charCodeAt(0) === 0xfeff) s = s.slice(1);
    var rows = [], lines = [], row = [], cell = '', inQ = false, line = 1, rowLine = 1, i = 0, n = s.length, quotedCell = false;
    while (i < n) {
      var c = s.charAt(i);
      if (inQ) {
        if (c === '"') {
          if (s.charAt(i + 1) === '"') { cell += '"'; i += 2; continue; }
          inQ = false; i++; continue;
        }
        if (c === '\r' || c === '\n') { line++; if (c === '\r' && s.charAt(i + 1) === '\n') { cell += '\n'; i += 2; continue; } }
        cell += c; i++; continue;
      }
      if (c === '"' && cell === '' && !quotedCell) { inQ = true; quotedCell = true; i++; continue; }
      if (c === delim) { row.push(cell); cell = ''; quotedCell = false; i++; continue; }
      if (c === '\r' || c === '\n') {
        row.push(cell); rows.push(row); lines.push(rowLine);
        row = []; cell = ''; quotedCell = false;
        if (c === '\r' && s.charAt(i + 1) === '\n') i++;
        i++; line++; rowLine = line; continue;
      }
      cell += c; i++;
    }
    if (cell !== '' || row.length || quotedCell) { row.push(cell); rows.push(row); lines.push(rowLine); }
    return { rows: rows, lines: lines };
  }
  M.parseDelimited = parseDelimited;

  /* ---------- reading an export ---------- */

  function normHeader(text) {
    return trim(text).toLowerCase().replace(/\([^)]*\)/g, ' ').replace(/[^a-z0-9]+/g, ' ').replace(/^ +| +$/g, '');
  }
  M.normHeader = normHeader;

  // Header names for each field, best first.
  var FIELDS = [
    ['date', ['date time', 'datetime', 'date and time', 'trade date time', 'execution date time', 'fill date time', 'timestamp', 'trade date', 'execution date', 'fill date', 'transaction date', 'deal date', 'order date', 'date', 'trade time', 'execution time', 'exec time', 'fill time', 'filled time', 'time']],
    ['time', ['time', 'trade time', 'execution time', 'exec time', 'fill time', 'filled time', 'time of trade', 'deal time']],
    ['symbol', ['symbol', 'ticker', 'instrument', 'contract', 'instrument code', 'ticker symbol', 'stock', 'security', 'epic', 'product', 'underlying', 'stock code', 'security code', 'name']],
    ['qty', ['filled qty', 'filled quantity', 'fill qty', 'fill quantity', 'exec qty', 'executed qty', 'executed quantity', 'quantity filled', 'qty filled', 'filled', 'quantity', 'qty', 'shares', 'no of shares', 'number of shares', 'contracts', 'lots', 'units', 'size', 'volume', 'amount of shares']],
    ['price', ['avg fill price', 'average fill price', 'fill price', 'filled price', 'execution price', 'exec price', 'trade price', 't price', 'deal price', 'avg price', 'average price', 'price', 'share price', 'unit price', 'price per share', 'price share', 'price per unit', 'avg fill', 'execution px', 'px', 'rate']],
    ['side', ['side', 'action', 'buy sell', 'b s', 'bs', 'buy or sell', 'buy sell indicator', 'direction', 'order side', 'trade side', 'transaction type', 'trade type', 'deal type', 'order action', 'type', 'activity', 'operation', 'transaction']],
    ['fees', ['total fees', 'total costs', 'total charges', 'commission', 'commissions', 'comm', 'comm fee', 'comm fees', 'commission fee', 'fee', 'fees', 'charges', 'charge', 'costs', 'brokerage', 'stamp duty', 'ptm levy', 'sec fee', 'taf fee', 'finra fee', 'exchange fee', 'exchange fees', 'reg fee', 'regulatory fee', 'regulatory fees', 'clearing fee', 'clearing fees', 'nfa fee', 'transaction fee', 'transaction fees', 'fx fee', 'other fees', 'platform fee', 'ib commission', 'ecn fee', 'routing fee',
      'currency conversion fee', 'stamp duty reserve tax', 'french transaction tax', 'financial transaction tax', 'transaction tax', 'finra trading activity fee']],
    ['currency', ['currency', 'ccy', 'curr', 'currency code', 'trade currency', 'settlement currency', 'price currency']],
    ['account', ['account', 'account id', 'account number', 'account no', 'account name', 'acct', 'acct id', 'account code', 'portfolio', 'sub account', 'trader', 'book']],
    ['mult', ['multiplier', 'mult', 'contract multiplier', 'point value', 'value per point', 'contract size']],
    ['status', ['status', 'order status', 'fill status', 'state', 'order state']],
    ['orderId', ['order id', 'order', 'order number', 'order no', 'order ref', 'order reference', 'orderid', 'parent order id']],
    ['execId', ['exec id', 'execution id', 'fill id', 'trade id', 'transaction id', 'deal id', 'deal reference', 'trade ref', 'trade reference', 'ticket', 'trade number', 'trade no', 'contract note', 'contract note number', 'reference', 'ref']],
    ['openClose', ['open close', 'o c', 'oc', 'position effect', 'effect', 'opening closing', 'open or close']],
    ['asset', ['asset category', 'asset class', 'security type', 'sec type', 'instrument type', 'asset type', 'product type']],
    ['recordType', ['record type', 'type', 'transaction type', 'activity', 'activity type', 'entry type', 'category', 'transaction']],
    ['amount', ['proceeds', 'net amount', 'net proceeds', 'consideration', 'amount', 'value', 'net value', 'total', 'net', 'cash']],
    ['description', ['description', 'security name', 'instrument name', 'name', 'details']]
  ];
  var FEE_TOTALS = ['total fees', 'total costs', 'total charges'];
  // The fields a person can point at a column by hand.
  var COLUMN_FIELDS = ['date', 'time', 'symbol', 'side', 'qty', 'price', 'fees', 'account', 'currency', 'orderId'];
  M.COLUMN_FIELDS = COLUMN_FIELDS;

  // Candidate columns for each field from a header row: {field: [column indexes, best first]}.
  function headerCandidates(cells) {
    var norm = cells.map(normHeader);
    var out = {};
    FIELDS.forEach(function (f) {
      var list = [];
      f[1].forEach(function (name) {
        norm.forEach(function (h, i) { if (h === name && list.indexOf(i) < 0) list.push(i); });
      });
      out[f[0]] = list;
    });
    return { norm: norm, cand: out };
  }

  function classifySide(text) {
    var s = ' ' + trim(text).toLowerCase().replace(/[^a-z]+/g, ' ') + ' ';
    if (!trim(s)) return null;
    if (/ (sell short|short sell|sell to open|sto|ss|short|sell open|open short|short open) /.test(s)) return { side: 'S', intent: 'open' };
    if (/ (buy to cover|buy cover|cover|btc|buy to close|close short|buy close) /.test(s)) return { side: 'B', intent: 'close' };
    if (/ (sell to close|stc|close long|sell close) /.test(s)) return { side: 'S', intent: 'close' };
    if (/ (buy to open|bto|open long|buy open) /.test(s)) return { side: 'B', intent: 'open' };
    if (/ (buy|bought|bot|b|long|purchase|purchased) /.test(s)) return { side: 'B', intent: '' };
    if (/ (sell|sold|sld|s|sale) /.test(s)) return { side: 'S', intent: '' };
    return null;
  }
  M.classifySide = classifySide;

  var FEE_TYPE = /\b(fee|fees|commission|commissions|charge|charges|levy|stamp|exchange|regulatory|clearing|platform|data|nfa|sec|finra|ptm)\b/;
  var NON_TRADE = /\b(dividend|dividends|interest|deposit|deposits|withdrawal|withdrawals|transfer|transfers|funding|adjustment|journal|rebate|split|corporate|coupon|tax|withholding|conversion|fx)\b/;
  var TRADE_TYPE = /\b(trade|trades|fill|fills|execution|executions|order|buy|sell|bought|sold)\b/;

  function statusReason(text) {
    var s = trim(text).toLowerCase();
    if (!s) return '';
    if (/fill|execut|done|complete|match|\bok\b|settled/.test(s)) return '';
    if (/cancel/.test(s)) return 'order cancelled, nothing filled';
    if (/reject/.test(s)) return 'order rejected, nothing filled';
    if (/expire/.test(s)) return 'order expired, nothing filled';
    if (/pending|working|open|active|submitted|placed|new/.test(s)) return 'order still working, nothing filled yet';
    if (/delete|void|inactive|unfilled|not filled/.test(s)) return 'order not filled';
    return '';
  }

  function isTotalRow(cells) {
    for (var i = 0; i < cells.length && i < 4; i++) {
      var c = trim(cells[i]).toLowerCase();
      if (!c) continue;
      return /^(grand\s+)?(sub\s*)?totals?\b|^sum\b|^net total\b/.test(c);
    }
    return false;
  }

  function cleanAccountName(name) {
    var s = trim(name).replace(/\.[A-Za-z0-9]{1,5}$/, '');
    s = s.replace(/\d{4}[-_.]?\d{2}[-_.]?\d{2}/g, ' ').replace(/\b(wk|week)\s*\d+\b/gi, ' ').replace(/[_\-.]+/g, ' ');
    s = s.replace(/\b\d+\b/g, ' ').replace(/\s+/g, ' ');
    s = trim(s);
    if (!s) return 'Main account';
    return s.charAt(0).toUpperCase() + s.slice(1);
  }
  M.cleanAccountName = cleanAccountName;

  // A futures-style symbol: a root of 1 to 4 letters, a month code and a one or two digit year (LKFZ6, LKF Z26).
  function symbolRoot(symbol) {
    var s = trim(symbol).toUpperCase();
    var m = /^([A-Z0-9]{1,4}?)\s?([FGHJKMNQUVXZ])(\d{1,2})$/.exec(s);
    if (m && /[A-Z]/.test(m[1])) return m[1];
    m = /^([A-Z0-9]{1,4})\s+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}$/.exec(s);
    if (m) return m[1];
    return '';
  }
  M.symbolRoot = symbolRoot;

  function cell(cells, i) { return i === undefined || i === null || i < 0 ? '' : trim(cells[i]); }

  /*
   * Read one export. opts: {dateOrder: 'auto'|'DMY'|'MDY', account: name for files without an account column,
   * base: default currency}. Returns the fills, the separate fee rows, the rows set aside with reasons and notes.
   */
  function readExport(name, text, opts) {
    opts = opts || {};
    var out = {
      name: str(name), ok: false, error: '', delimiter: '', headerLine: 0, columns: {}, dateOrder: '', dateNote: '',
      account: '', fills: [], fees: [], skipped: [], notes: [], headerCells: [], counts: { rows: 0, blank: 0, fills: 0, fees: 0, skipped: 0 }
    };
    var src = str(text);
    if (!trim(src)) { out.error = 'The file is empty.'; return out; }
    if (/^\s*[{\[]/.test(src) && /"(fills|journal|app)"/.test(src.slice(0, 400))) { out.error = 'This looks like a saved journal file: use Open journal file instead.'; return out; }
    if (/^%PDF|^PK\u0003\u0004/.test(src.slice(0, 8))) { out.error = 'This is not a text export (it looks like a PDF or a spreadsheet). Save it as CSV first.'; return out; }
    var delim = sniffDelimiter(src);
    out.delimiter = delim;
    var parsed = parseDelimited(src, delim);
    var rows = parsed.rows, lines = parsed.lines;
    // Sectioned statements put a section name and Header/Data in the first two cells.
    var sectioned = rows.filter(function (r) { return /^(header|data)$/i.test(trim(r[1])); }).length > rows.length / 2;
    if (sectioned) {
      var keepRows = [], keepLines = [];
      rows.forEach(function (r, i) {
        if (/^trades?$/i.test(trim(r[0])) && /^(header|data|subtotal|total)$/i.test(trim(r[1]))) {
          keepRows.push(/^data$/i.test(trim(r[1])) || /^header$/i.test(trim(r[1])) ? r.slice(2) : ['Total'].concat(r.slice(3)));
          keepLines.push(lines[i]);
        }
      });
      rows = keepRows; lines = keepLines;
      out.notes.push('Read the Trades section of a sectioned statement.');
    }
    // Find the header row: the first with the columns you chose, or else with date, symbol, quantity and price columns.
    var chosen = {}, anyChosen = false;
    Object.keys(opts.columns || {}).forEach(function (f) {
      if (COLUMN_FIELDS.indexOf(f) >= 0 && typeof opts.columns[f] === 'string') { chosen[f] = trim(opts.columns[f]); anyChosen = true; }
    });
    var named = Object.keys(chosen).filter(function (f) { return chosen[f] !== ''; }).map(function (f) { return chosen[f]; });
    var hi = -1, hc = null;
    for (var r = 0; r < rows.length && r < 40; r++) {
      var c = headerCandidates(rows[r]);
      if (anyChosen && named.length) {
        var cellsHere = rows[r].map(trim);
        if (named.every(function (n) { return cellsHere.indexOf(n) >= 0; })) { hi = r; hc = c; break; }
        continue;
      }
      var hasDate = c.cand.date.length > 0 || c.cand.time.length > 0;
      if (hasDate && c.cand.symbol.length && c.cand.qty.length && c.cand.price.length) { hi = r; hc = c; break; }
    }
    if (hi < 0) {
      // Offer the cells of the fullest early row (most likely the header) to choose from.
      var most = 0;
      for (var fr = 0; fr < rows.length && fr < 40; fr++) {
        var filled = rows[fr].filter(function (x) { return trim(x) !== ''; }).length;
        if (filled > most) { most = filled; out.headerCells = rows[fr].map(trim); }
      }
      var first = out.headerCells.filter(function (x) { return x !== ''; }).slice(0, 8).join(', ');
      out.error = anyChosen && named.length ? 'None of the first 40 rows has all the columns you chose (' + named.join(', ') + ').'
        : 'Could not find a header row with date, symbol, quantity and price columns' + (first ? ' (the first row reads: ' + first + ')' : '') + '. Choose the columns yourself below.';
      return out;
    }
    out.headerCells = rows[hi].map(trim);
    out.headerLine = lines[hi];
    if (hi > 0) out.notes.push(hi + (hi === 1 ? ' line' : ' lines') + ' above the header were ignored.');
    var header = rows[hi];
    var body = [], bodyLines = [];
    for (var b = hi + 1; b < rows.length; b++) { body.push(rows[b]); bodyLines.push(lines[b]); }

    // Choose a column for each field. A column is used once.
    var used = {}, col = {};
    // Columns chosen by hand come first; an empty choice means the file has no such column.
    Object.keys(chosen).forEach(function (f) {
      if (f === 'fees' || chosen[f] === '') return;
      var at = out.headerCells.indexOf(chosen[f]);
      if (at >= 0 && !used[at]) { used[at] = true; col[f] = at; }
    });
    function take(field, list) {
      if (has(chosen, field)) return -1;
      for (var i = 0; i < list.length; i++) if (!used[list[i]]) { used[list[i]] = true; col[field] = list[i]; return list[i]; }
      return -1;
    }
    var cand = hc.cand;
    // Values in a column, for choosing between candidates.
    function values(i) { var v = []; for (var k = 0; k < body.length && v.length < 200; k++) { var x = cell(body[k], i); if (x) v.push(x); } return v; }
    function looksLikeDates(i) { var v = values(i); var ok = v.filter(function (x) { return parseDateTime(x, 'DMY') || parseDateTime(x, 'MDY'); }).length; return v.length > 0 && ok >= v.length * 0.5; }
    var dateList = cand.date.filter(looksLikeDates);
    if (!dateList.length) dateList = cand.date.slice(0, 1);
    take('date', dateList);
    take('time', cand.time.filter(function (i) { var v = values(i); return v.length && v.filter(function (x) { return parseTime(x) !== null; }).length >= v.length * 0.5; }));
    take('symbol', cand.symbol);
    // Prefer a filled quantity over an order quantity.
    take('qty', cand.qty);
    take('price', cand.price);
    var sideList = cand.side.filter(function (i) {
      var v = values(i);
      return v.length && v.filter(function (x) { return classifySide(x); }).length >= v.length * 0.5;
    });
    take('side', sideList);
    var feeTotal = cand.fees.filter(function (i) { return FEE_TOTALS.indexOf(hc.norm[i]) >= 0; });
    var feeCols = [];
    if (has(chosen, 'fees')) {
      var fat = chosen.fees === '' ? -1 : out.headerCells.indexOf(chosen.fees);
      if (fat >= 0 && !used[fat]) { used[fat] = true; feeCols.push(fat); }
    } else (feeTotal.length ? feeTotal.slice(0, 1) : cand.fees).forEach(function (i) { if (!used[i]) { used[i] = true; feeCols.push(i); } });
    ['currency', 'account', 'mult', 'status', 'orderId', 'execId', 'openClose', 'asset', 'recordType', 'amount', 'description'].forEach(function (f) { take(f, cand[f]); });
    if (col.symbol === undefined && col.description !== undefined) { col.symbol = col.description; }
    Object.keys(col).forEach(function (f) { out.columns[f] = trim(header[col[f]]); });
    if (feeCols.length) out.columns.fees = feeCols.map(function (i) { return trim(header[i]); }).join(' + ');

    // Hints from the header: prices in pence, the currency of money columns.
    var penceCol = col.price !== undefined && /\(\s*(p|pence|gbx)\s*\)|\bpence\b|\bgbx\b/i.test(header[col.price]);
    var headerCur = '';
    header.forEach(function (h) {
      if (/£|\bgbp\b/i.test(h)) headerCur = headerCur || 'GBP';
      else if (/\$|\busd\b/i.test(h)) headerCur = headerCur || 'USD';
      else if (/€|\beur\b/i.test(h)) headerCur = headerCur || 'EUR';
    });
    var decimalComma = delim === ';';

    // Dates: which order the numeric dates use.
    var dateVals = values(col.date);
    var detected = detectDateOrder(dateVals);
    var wanted = opts.dateOrder === 'DMY' || opts.dateOrder === 'MDY' ? opts.dateOrder : 'auto';
    var order;
    if (wanted !== 'auto') { order = wanted; out.dateNote = 'Dates read ' + (order === 'DMY' ? 'day first' : 'month first') + ', as set.'; }
    else if (detected === 'DMY' || detected === 'MDY') { order = detected; out.dateNote = 'Dates read ' + (order === 'DMY' ? 'day first (UK style)' : 'month first (US style)') + ': some days are over 12.'; }
    else {
      order = 'DMY';
      var numeric = dateVals.some(function (v) { return dateShape(v); });
      if (detected === 'MIXED') out.dateNote = 'Dates are written both ways in this file; read day first. Check the dates.';
      else if (numeric) out.dateNote = 'Dates could be day first or month first (no day is over 12); read day first (UK style). Change this if they are US dates.';
    }
    out.dateOrder = order;

    // Fee columns: mostly negative numbers mean costs are shown as negatives.
    var feeSign = feeCols.map(function (i) {
      var neg = 0, pos = 0;
      values(i).forEach(function (x) { var n = readNumber(x, decimalComma); if (n && (n.int !== '0' || /[1-9]/.test(n.frac))) { if (n.neg) neg++; else pos++; } });
      return neg > pos ? -1 : 1;
    });
    // Signed quantities: any negative quantity means the sign carries the side.
    var signedQty = values(col.qty).some(function (x) { var n = readNumber(x, decimalComma); return n && n.neg; });

    var defaultAccount = trim(opts.account) || cleanAccountName(name);
    var headerNorm = header.map(normHeader).join('|');
    var accounts = {};
    var skip = function (k, reason) {
      out.skipped.push({ line: bodyLines[k], reason: reason, text: body[k].map(trim).filter(function (x) { return x !== ''; }).join(', ').slice(0, 140) });
    };

    for (var k = 0; k < body.length; k++) {
      var cells = body[k];
      if (!cells.some(function (x) { return trim(x) !== ''; })) { out.counts.blank++; continue; }
      out.counts.rows++;
      if (cells.map(normHeader).join('|') === headerNorm) { skip(k, 'repeated header row'); continue; }
      if (isTotalRow(cells)) { skip(k, 'total row, not a fill'); continue; }
      var sr = statusReason(cell(cells, col.status));
      if (sr) { skip(k, sr); continue; }
      var account = col.account !== undefined && cell(cells, col.account) ? cell(cells, col.account) : defaultAccount;
      var symbol = cell(cells, col.symbol).toUpperCase();
      var sideText = cell(cells, col.side);
      var typeText = cell(cells, col.recordType).toLowerCase();
      var side = sideText ? classifySide(sideText) : null;
      var qtyNum = readNumber(cell(cells, col.qty), decimalComma);
      var qtyZero = !qtyNum || scaled(qtyNum, 6) === 0;
      var priceText = cell(cells, col.price);
      // Fee rows and other rows that are not fills.
      var kind = '';
      if (typeText && !TRADE_TYPE.test(typeText)) {
        if (FEE_TYPE.test(typeText) && !NON_TRADE.test(typeText)) kind = 'fee';
        else if (NON_TRADE.test(typeText)) kind = 'other';
      } else if (!typeText && sideText && !side) {
        var st = sideText.toLowerCase();
        if (FEE_TYPE.test(st) && !NON_TRADE.test(st)) kind = 'fee';
        else if (NON_TRADE.test(st)) kind = 'other';
        else { skip(k, 'buy or sell not recognised: ' + sideText); continue; }
      }
      if (kind === 'fee' && qtyZero && !priceText) {
        var feeAmt = 0, anyFee = false;
        feeCols.forEach(function (i, j) { var v = parseCents(cell(cells, i), decimalComma); if (v !== null) { feeAmt += v * feeSign[j]; anyFee = true; } });
        if (!anyFee && col.amount !== undefined) { var av = parseCents(cell(cells, col.amount), decimalComma); if (av !== null) { feeAmt = av < 0 ? -av : av; anyFee = true; } }
        if (!anyFee || feeAmt === 0) { skip(k, 'fee row without an amount'); continue; }
        var fdt = parseDateTime(cell(cells, col.date), order);
        if (fdt && fdt.sec === null && col.time !== undefined) fdt.sec = parseTime(cell(cells, col.time));
        out.fees.push({
          account: account, symbol: symbol, day: fdt ? fdt.day : null, sec: fdt ? fdt.sec : null, amount: feeAmt,
          orderId: cell(cells, col.orderId), label: trim(typeText || sideText).toLowerCase() || 'fee', line: bodyLines[k]
        });
        accounts[account] = true;
        out.counts.fees++;
        continue;
      }
      if (kind) { skip(k, 'not a trade (' + trim(typeText || sideText) + ')'); continue; }
      if (!symbol) { skip(k, 'no symbol'); continue; }
      var dt = parseDateTime(cell(cells, col.date), order);
      if (!dt) { skip(k, cell(cells, col.date) ? 'date not recognised: ' + cell(cells, col.date) : 'no date'); continue; }
      if (dt.sec === null && col.time !== undefined && cell(cells, col.time)) {
        var tm = parseTime(cell(cells, col.time));
        if (tm === null) { skip(k, 'time not recognised: ' + cell(cells, col.time)); continue; }
        dt.sec = tm;
      }
      if (!qtyNum) { skip(k, cell(cells, col.qty) ? 'quantity not recognised: ' + cell(cells, col.qty) : 'no quantity'); continue; }
      var q = scaled(qtyNum, 6);
      if (q === 0) { skip(k, 'quantity is zero, nothing filled'); continue; }
      var intent = '';
      if (side) { intent = side.intent; } else if (sideText) { skip(k, 'buy or sell not recognised: ' + sideText); continue; }
      else if (q < 0 || signedQty) { side = { side: q < 0 ? 'S' : 'B', intent: '' }; }
      else if (col.amount !== undefined && readNumber(cell(cells, col.amount), decimalComma)) {
        var amt = readNumber(cell(cells, col.amount), decimalComma);
        side = { side: amt.neg ? 'B' : 'S', intent: '' };
      } else { skip(k, 'cannot tell a buy from a sell (no side column and the quantity has no sign)'); continue; }
      if (q < 0) q = -q;
      var oc = cell(cells, col.openClose).toLowerCase();
      if (/^(o|open|opening|to open)\b/.test(oc)) intent = 'open';
      else if (/^(c|close|closing|to close)\b/.test(oc)) intent = 'close';
      var pn = readNumber(priceText, decimalComma);
      if (!pn) { skip(k, priceText ? 'price not recognised: ' + priceText : 'no price'); continue; }
      if (pn.neg) { skip(k, 'negative price: ' + priceText); continue; }
      var currency = cell(cells, col.currency).toUpperCase() || pn.cur || headerCur || '';
      var price = scaled(pn, 6);
      if (penceCol || pn.pence || currency === 'GBX' || cell(cells, col.currency) === 'GBp') { price = rnd(price / 100); currency = 'GBP'; }
      var fee = 0;
      for (var fj = 0; fj < feeCols.length; fj++) {
        var fv = parseCents(cell(cells, feeCols[fj]), decimalComma);
        if (fv !== null) fee += fv * feeSign[fj];
        if (!currency) { var fn = readNumber(cell(cells, feeCols[fj]), decimalComma); if (fn && fn.cur) currency = fn.cur; }
      }
      var multText = cell(cells, col.mult);
      var mult = multText ? parseFloatText(multText) : null;
      if (mult !== null && !(mult > 0)) mult = null;
      var assetText = cell(cells, col.asset).toLowerCase();
      out.fills.push({
        key: '', account: account, symbol: symbol, day: dt.day, sec: dt.sec, side: side.side, intent: intent,
        q: q, price: price, fee: fee, currency: currency || trim(opts.base) || 'USD', mult: mult,
        orderId: cell(cells, col.orderId), execId: cell(cells, col.execId), asset: /fut/.test(assetText) ? 'future' : (/opt/.test(assetText) ? 'option' : ''),
        file: out.name, line: bodyLines[k]
      });
      accounts[account] = true;
      out.counts.fills++;
    }
    out.counts.skipped = out.skipped.length;
    // Files listed newest first are read oldest first, so fills without times keep their real order.
    var up = 0, down = 0;
    for (var z = 1; z < out.fills.length; z++) {
      var ta = out.fills[z - 1].day * DAY + (out.fills[z - 1].sec || 0), tb = out.fills[z].day * DAY + (out.fills[z].sec || 0);
      if (tb > ta) up++; else if (tb < ta) down++;
    }
    if (down > up) { out.fills.reverse(); out.notes.push('Rows were listed newest first; read oldest first.'); }
    // In a file that marks short sales and covers, a plain sell closes a long position.
    var markers = out.fills.some(function (f) { return (f.side === 'S' && f.intent === 'open') || (f.side === 'B' && f.intent === 'close'); });
    if (markers) out.fills.forEach(function (f) { if (f.side === 'S' && f.intent === '') f.intent = 'close'; });
    // Keys that let the same fill be recognised in next week's export.
    var seen = {};
    out.fills.forEach(function (f) {
      if (f.execId) { f.key = 'x|' + f.account + '|' + f.symbol + '|' + f.execId; return; }
      var base = ['f', f.account, f.symbol, f.day, f.sec === null ? '' : f.sec, f.side, f.q, f.price].join('|');
      seen[base] = (seen[base] || 0) + 1;
      f.key = base + '#' + seen[base];
    });
    var seenFee = {};
    out.fees.forEach(function (e) {
      var base = ['e', e.account, e.symbol, e.day === null ? '' : e.day, e.sec === null ? '' : e.sec, e.amount, e.orderId, e.label].join('|');
      seenFee[base] = (seenFee[base] || 0) + 1;
      e.key = base + '#' + seenFee[base];
    });
    // Exec IDs repeated within the file are not unique, so fall back to the content key.
    var execCount = {};
    out.fills.forEach(function (f) { if (f.key.charAt(0) === 'x') execCount[f.key] = (execCount[f.key] || 0) + 1; });
    var dupExec = Object.keys(execCount).some(function (key) { return execCount[key] > 1; });
    if (dupExec) {
      seen = {};
      out.fills.forEach(function (f) {
        var base = ['f', f.account, f.symbol, f.day, f.sec === null ? '' : f.sec, f.side, f.q, f.price].join('|');
        seen[base] = (seen[base] || 0) + 1;
        f.key = base + '#' + seen[base];
      });
    }
    out.account = Object.keys(accounts).sort(cmp).join(', ');
    if (!out.fills.length && !out.fees.length) { out.error = 'No fills could be read from this file.'; return out; }
    if (out.fills.some(function (f) { return f.sec === null; })) out.notes.push('Some fills have no time of day, so holding times for them are in whole days.');
    out.ok = true;
    return out;
  }
  M.readExport = readExport;

  /* ---------- settings and the journal state ---------- */

  function defaultRules() {
    return {
      maxRiskPct: { on: true, value: '1' },
      maxDailyLoss: { on: true, value: '2', unit: 'pct' },
      maxTradesPerDay: { on: true, value: '6' },
      noAddingToLoser: { on: true },
      maxLossR: { on: true, value: '1.5' },
      needPlannedRisk: { on: true }
    };
  }
  function defaultSettings() {
    return {
      base: 'USD',
      dateOrder: 'auto',
      fx: [],
      multipliers: [],
      accounts: [],
      rules: defaultRules(),
      setups: ['Opening range break', 'Pullback', 'Breakout', 'Reversal', 'News'],
      mistakes: ['Chased entry', 'Moved stop', 'Added to a loser', 'Oversized', 'Early exit', 'Revenge trade', 'No plan']
    };
  }
  M.defaultSettings = defaultSettings;
  M.defaultRules = defaultRules;

  function emptyState() {
    return { settings: defaultSettings(), sources: [], fills: [], feeRows: [], journal: [], carry: [], seq: 0 };
  }
  M.emptyState = emptyState;

  function lookup(list, key, field) {
    for (var i = 0; i < list.length; i++) if (list[i][field] === key) return list[i];
    return null;
  }

  // Add exports to the journal, skipping fills that are already in it.
  function importFiles(state, files) {
    var next = {
      settings: state.settings, sources: state.sources.slice(), fills: state.fills.slice(), feeRows: state.feeRows.slice(),
      journal: state.journal, carry: state.carry || [], seq: state.seq
    };
    var have = {}, haveFee = {};
    next.fills.forEach(function (f) { have[f.key] = true; });
    next.feeRows.forEach(function (e) { haveFee[e.key] = true; });
    var reports = [];
    files.forEach(function (file) {
      var rep = readExport(file.name, file.text, { dateOrder: file.dateOrder || state.settings.dateOrder, account: file.account, base: state.settings.base, columns: file.columns });
      var id = 1;
      next.sources.forEach(function (s) { if (s.id >= id) id = s.id + 1; });
      var added = 0, dupes = 0, feesAdded = 0;
      rep.fills.forEach(function (f) {
        if (have[f.key]) { dupes++; return; }
        have[f.key] = true;
        next.seq += 1;
        var g = {};
        Object.keys(f).forEach(function (k) { g[k] = f[k]; });
        g.src = id; g.seq = next.seq;
        next.fills.push(g);
        added++;
      });
      rep.fees.forEach(function (e) {
        if (haveFee[e.key]) return;
        haveFee[e.key] = true;
        next.seq += 1;
        var g = {};
        Object.keys(e).forEach(function (k) { g[k] = e[k]; });
        g.src = id; g.seq = next.seq; g.file = rep.name;
        next.feeRows.push(g);
        feesAdded++;
      });
      var source = {
        id: id, name: rep.name, ok: rep.ok, error: rep.error, account: rep.account, columns: rep.columns, dateOrder: rep.dateOrder,
        dateNote: rep.dateNote, notes: rep.notes, counts: rep.counts, added: added, duplicates: dupes, feesAdded: feesAdded,
        skipped: rep.skipped.slice(0, 300), first: null, last: null, headerCells: rep.headerCells
      };
      rep.fills.forEach(function (f) {
        if (source.first === null || f.day < source.first) source.first = f.day;
        if (source.last === null || f.day > source.last) source.last = f.day;
      });
      if (rep.ok || rep.error) next.sources.push(source);
      reports.push(source);
    });
    return { state: next, reports: reports };
  }
  M.importFiles = importFiles;

  /* ---------- matching fills into round trips ---------- */

  function multiplierFor(settings, symbol, fileMult) {
    var e = lookup(settings.multipliers || [], symbol, 'symbol');
    if (!e) { var r = symbolRoot(symbol); if (r) e = lookup(settings.multipliers || [], r, 'symbol'); }
    if (e) { var v = parseFloatText(e.value); if (v > 0) return v; }
    if (fileMult) return fileMult;
    return 1;
  }
  M.multiplierFor = multiplierFor;

  function accountSettings(settings, account) {
    return lookup(settings.accounts || [], account, 'name') || { name: account, start: '', longOnly: false };
  }
  M.accountSettings = accountSettings;

  function fxRate(settings, currency) {
    if (currency === settings.base) return 1;
    var e = lookup(settings.fx || [], currency, 'currency');
    var v = e ? parseFloatText(e.rate) : null;
    return v > 0 ? v : null;
  }
  M.fxRate = fxRate;

  function fillT(f) { return f.day * DAY + (f.sec === null ? 0 : f.sec); }
  function byTime(a, b) { return (fillT(a) - fillT(b)) || (a.seq - b.seq); }
  M.fillT = fillT;

  // Profit on a matched piece, in cents: (exit - entry) x direction x quantity x multiplier.
  function piecePnl(entry, exit, dir, q, mult) {
    return rnd((exit - entry) * dir * q * mult / 10000000000);
  }
  M.piecePnl = piecePnl;

  function sameOrder(a, b) {
    if (a.orderId && b.orderId) return a.orderId === b.orderId;
    if (a.sec === null || b.sec === null) return false;
    return a.day === b.day && fillT(b) - fillT(a) <= 5;
  }

  function isoStamp(day, sec) {
    return toIso(day) + (sec === null ? '' : 'T' + pad2(Math.floor(sec / 3600)) + ':' + pad2(Math.floor(sec / 60) % 60) + ':' + pad2(sec % 60));
  }
  M.isoStamp = isoStamp;

  /*
   * Match fills into round trips: a trade runs from flat to flat in one symbol in one account.
   * Inside a trade, closing quantities are matched to opening lots first in, first out.
   */
  // Opening positions typed in for closes whose opening fill is older than the exports, as fills.
  function carryFills(state) {
    return (state.carry || []).map(function (c, i) {
      return {
        key: carryKey(c), account: c.account, symbol: c.symbol, day: c.day, sec: null, side: c.side, intent: 'open', q: c.q, price: c.price, fee: c.fee || 0,
        currency: c.currency, mult: null, orderId: '', execId: '', asset: '', file: 'Opening position', line: 0, src: 0, seq: -(state.carry.length - i)
      };
    });
  }
  function carryKey(c) { return ['c', c.account, c.symbol, c.day, c.side, c.q, c.price].join('|'); }
  M.carryKey = carryKey;

  // An opening position for a close with no opening fill: the date (YYYY-MM-DD) and price it was opened at.
  function makeCarry(u, dateText, priceText) {
    var day = fromIso(dateText);
    if (day === null) return { ok: false, msg: 'Enter the date the position was opened.' };
    if (day > u.day) return { ok: false, msg: 'The opening date must be on or before ' + fmtDate(u.day) + ', when it was closed.' };
    var price = parseMicro(priceText);
    if (price === null || !(price > 0)) return { ok: false, msg: 'Enter the price it was opened at.' };
    return { ok: true, carry: { account: u.account, symbol: u.symbol, side: u.side === 'S' ? 'B' : 'S', q: u.q, price: price, day: day, fee: 0, currency: u.currency || '' } };
  }
  M.makeCarry = makeCarry;

  function matchTrades(state) {
    var settings = state.settings;
    var fills = state.fills.concat(carryFills(state)).sort(byTime);
    var feeOf = {};
    fills.forEach(function (f) { feeOf[f.key] = f.fee; });
    // Attach fee rows to fills: the same order, else the same symbol that day, else they stay with the account.
    var byOrder = {}, byDay = {};
    fills.forEach(function (f) {
      if (f.orderId) { var ko = f.account + '\u0000' + f.orderId; if (!byOrder[ko]) byOrder[ko] = f; }
      var kd = f.account + '\u0000' + f.symbol + '\u0000' + f.day;
      (byDay[kd] = byDay[kd] || []).push(f);
    });
    var unattached = [];
    var feeRows = state.feeRows.slice().sort(function (a, b) { return ((a.day === null ? 0 : a.day) - (b.day === null ? 0 : b.day)) || ((a.sec === null ? 0 : a.sec) - (b.sec === null ? 0 : b.sec)) || (a.seq - b.seq); });
    feeRows.forEach(function (e) {
      var target = null;
      if (e.orderId) target = byOrder[e.account + '\u0000' + e.orderId] || null;
      if (!target && e.symbol && e.day !== null) {
        var same = byDay[e.account + '\u0000' + e.symbol + '\u0000' + e.day] || [];
        var before = null, after = null, et = e.day * DAY + (e.sec === null ? DAY - 1 : e.sec);
        same.forEach(function (f) { if (fillT(f) <= et) before = f; else if (!after) after = f; });
        target = before || after;
      }
      if (target) feeOf[target.key] += e.amount;
      else unattached.push({ key: e.key, account: e.account, symbol: e.symbol, day: e.day, sec: e.sec, amount: e.amount, label: e.label, file: e.file, seq: e.seq });
    });

    var groups = {}, order = [];
    fills.forEach(function (f) {
      var g = f.account + '\u0000' + f.symbol;
      if (!groups[g]) { groups[g] = []; order.push(g); }
      groups[g].push(f);
    });
    order.sort(cmp);
    var trades = [], unmatched = [], legsByFill = {}, events = [];
    var idCount = {};
    order.forEach(function (g) {
      var list = groups[g];
      var acc = accountSettings(settings, list[0].account);
      var pos = 0, lots = [], trade = null, group = null;
      function event(f, cents, kind, id) {
        events.push({ account: f.account, symbol: f.symbol, day: f.day, sec: f.sec, t: fillT(f), seq: f.seq, cents: cents, trade: id, kind: kind });
      }
      function noTrade(f, q, fee) {
        unmatched.push({ key: f.key, account: f.account, symbol: f.symbol, side: f.side, q: q, price: f.price, day: f.day, sec: f.sec, fee: fee, file: f.file, line: f.line, currency: f.currency });
        event(f, -fee, 'fee', '');
      }
      function openTrade(f, q, fee) {
        var mult = multiplierFor(settings, f.symbol, f.mult);
        var base = f.account + '|' + f.symbol + '|' + isoStamp(f.day, f.sec);
        idCount[base] = (idCount[base] || 0) + 1;
        trade = {
          id: idCount[base] > 1 ? base + '|' + idCount[base] : base,
          account: f.account, symbol: f.symbol, root: symbolRoot(f.symbol), currency: f.currency, mult: mult,
          dir: f.side === 'B' ? 1 : -1, openDay: f.day, openSec: f.sec, closeDay: null, closeSec: null,
          legs: [], matches: [], qtyIn: 0, qtyOut: 0, maxPos: q, gross: 0, fees: 0, status: 'open', reversal: false,
          entryValue: 0, exitValue: 0, timeKnown: true, entryOrders: 0, exitOrders: 0, adds: []
        };
        trades.push(trade);
        group = null;
        addLeg(f, q, 'open', fee);
        lots = [{ q: q, price: f.price, key: f.key, day: f.day, sec: f.sec }];
        pos = (f.side === 'B' ? 1 : -1) * q;
      }
      function addLeg(f, q, role, fee) {
        var prev = trade.legs.length ? trade.legs[trade.legs.length - 1] : null;
        if (f.sec === null) trade.timeKnown = false;
        if (role === 'open' || role === 'add') {
          var newOrder = !prev || !(prev.role === 'open' || prev.role === 'add') || !sameOrder(prev, f);
          if (newOrder) {
            trade.entryOrders += 1;
            group = null;
            if (role === 'add') {
              var lq = 0, lv = 0;
              lots.forEach(function (l) { lq += l.q; lv += l.price * l.q; });
              group = { day: f.day, sec: f.sec, q: 0, value: 0, avgBefore: lq ? lv / lq : 0, worse: false };
              trade.adds.push(group);
            }
          }
          if (role === 'add' && group) { group.q += q; group.value += f.price * q; }
          trade.qtyIn += q;
          trade.entryValue += f.price * q;
        } else {
          group = null;
          if (!prev || prev.role === 'open' || prev.role === 'add' || !sameOrder(prev, f)) trade.exitOrders += 1;
          trade.qtyOut += q;
          trade.exitValue += f.price * q;
        }
        trade.fees += fee;
        trade.legs.push({ key: f.key, role: role, side: f.side, q: q, price: f.price, day: f.day, sec: f.sec, fee: fee, orderId: f.orderId });
        (legsByFill[f.key] = legsByFill[f.key] || []).push({ trade: trade.id, role: role, q: q });
        event(f, -fee, 'fee', trade.id);
      }
      list.forEach(function (f) {
        var fee = feeOf[f.key];
        var dir = f.side === 'B' ? 1 : -1;
        var q = f.q;
        if (pos === 0) {
          if (f.intent === 'close' || (acc.longOnly && f.side === 'S')) { noTrade(f, q, fee); return; }
          openTrade(f, q, fee);
          return;
        }
        if ((pos > 0 && dir > 0) || (pos < 0 && dir < 0)) {
          var last = trade.legs[trade.legs.length - 1];
          addLeg(f, q, last.role === 'open' && sameOrder(last, f) ? 'open' : 'add', fee);
          lots.push({ q: q, price: f.price, key: f.key, day: f.day, sec: f.sec });
          pos += dir * q;
          if (Math.abs(pos) > trade.maxPos) trade.maxPos = Math.abs(pos);
          if (group && group.q) group.worse = trade.dir * (group.value / group.q - group.avgBefore) < 0;
          return;
        }
        // Closing, and perhaps reversing.
        var open = Math.abs(pos);
        var closeQ = q < open ? q : open;
        var extra = q - closeQ;
        var closeFee = extra > 0 ? rnd(fee * closeQ / q) : fee;
        addLeg(f, closeQ, closeQ === open ? 'close' : 'reduce', closeFee);
        var left = closeQ;
        while (left > 0 && lots.length) {
          var lot = lots[0];
          var take = lot.q < left ? lot.q : left;
          var pnl = piecePnl(lot.price, f.price, trade.dir, take, trade.mult);
          trade.matches.push({ open: lot.key, close: f.key, q: take, entry: lot.price, exit: f.price, pnl: pnl, holdSec: fillT(f) - (lot.day * DAY + (lot.sec === null ? 0 : lot.sec)) });
          trade.gross += pnl;
          event(f, pnl, 'pnl', trade.id);
          lot.q -= take;
          left -= take;
          if (lot.q === 0) lots.shift();
        }
        pos += dir * closeQ;
        if (pos === 0) {
          trade.status = 'closed';
          trade.closeDay = f.day;
          trade.closeSec = f.sec;
          trade = null;
          group = null;
          lots = [];
        }
        if (extra > 0) {
          var restFee = fee - closeFee;
          if (f.intent !== 'close' && !(acc.longOnly && f.side === 'S')) {
            openTrade(f, extra, restFee);
            trade.reversal = true;
          } else {
            noTrade(f, extra, restFee);
          }
        }
      });
      if (trade) trade.openLots = lots.map(function (l) { return { q: l.q, price: l.price, day: l.day, sec: l.sec }; });
    });
    unattached.forEach(function (e) {
      events.push({ account: e.account, symbol: e.symbol, day: e.day === null ? 0 : e.day, sec: e.sec, t: e.day === null ? 0 : e.day * DAY + (e.sec === null ? 0 : e.sec), seq: e.seq, cents: -e.amount, trade: '', kind: 'fee' });
    });
    events.sort(function (a, b) { return cmp(a.account, b.account) || (a.t - b.t) || (a.seq - b.seq) || cmp(a.kind, b.kind); });
    trades.forEach(function (t) {
      t.net = t.gross - t.fees;
      t.openT = t.openDay * DAY + (t.openSec === null ? 0 : t.openSec);
      t.closeT = t.closeDay === null ? null : t.closeDay * DAY + (t.closeSec === null ? 0 : t.closeSec);
      t.holdSec = t.closeT === null ? null : t.closeT - t.openT;
      t.avgEntry = t.qtyIn ? t.entryValue / t.qtyIn : 0;
      t.avgExit = t.qtyOut ? t.exitValue / t.qtyOut : 0;
      var hq = 0, hv = 0;
      t.matches.forEach(function (m) { hq += m.q; hv += m.holdSec * m.q; });
      t.fifoHoldSec = hq ? rnd(hv / hq) : null;
      if (!t.openLots) t.openLots = [];
      t.openQty = 0;
      t.openLots.forEach(function (l) { t.openQty += l.q; });
      t.adds = t.adds.map(function (a) {
        return { day: a.day, sec: a.sec, q: a.q, price: a.q ? a.value / a.q : 0, avgBefore: a.avgBefore, worse: a.worse };
      });
    });
    return { fills: fills, feeOf: feeOf, trades: trades, unmatched: unmatched, unattached: unattached, legsByFill: legsByFill, events: events };
  }

  M.matchTrades = matchTrades;

  /* ---------- the journal ---------- */

  function journalEntry(state, id) {
    return lookup(state.journal || [], id, 'id');
  }
  M.journalEntry = journalEntry;

  // Store one trade's journal fields, returning a new journal list (sorted by trade id).
  function setJournal(journal, id, fields) {
    var out = [], found = false;
    (journal || []).forEach(function (e) {
      if (e.id === id) { found = true; out.push(cleanEntry(id, fields)); } else out.push(e);
    });
    if (!found) out.push(cleanEntry(id, fields));
    return out.filter(function (e) { return e.setup || e.stop || e.risk || e.notes || e.mistakes.length || e.target; })
      .sort(function (a, b) { return cmp(a.id, b.id); });
  }
  function cleanEntry(id, f) {
    var mistakes = [];
    (f.mistakes || []).forEach(function (m) { m = trim(m); if (m && mistakes.indexOf(m) < 0) mistakes.push(m); });
    return { id: id, setup: trim(f.setup), stop: trim(f.stop), risk: trim(f.risk), target: trim(f.target), mistakes: mistakes, notes: str(f.notes).replace(/\r\n?/g, '\n').replace(/\s+$/, '') };
  }
  M.setJournal = setJournal;

  // Open risk on a trade given a stop price: the most the open lots could lose at the stop, after each fill.
  function tradeRisk(trade, stop) {
    if (stop === null) return null;
    var lots = [], initial = null, max = 0;
    for (var i = 0; i < trade.legs.length; i++) {
      var leg = trade.legs[i];
      if (leg.role === 'open' || leg.role === 'add') {
        lots.push({ q: leg.q, price: leg.price });
      } else {
        var left = leg.q;
        while (left > 0 && lots.length) {
          var take = lots[0].q < left ? lots[0].q : left;
          lots[0].q -= take;
          left -= take;
          if (lots[0].q === 0) lots.shift();
        }
      }
      var risk = 0;
      for (var j = 0; j < lots.length; j++) {
        var per = trade.dir * (lots[j].price - stop);
        if (per > 0) risk += per * lots[j].q;
      }
      var cents = rnd(risk * trade.mult / 10000000000);
      if (cents > max) max = cents;
      var next = trade.legs[i + 1];
      if (initial === null && leg.role === 'open' && !(next && next.role === 'open')) initial = cents;
    }
    return { initial: initial === null ? 0 : initial, max: max };
  }

  M.tradeRisk = tradeRisk;

  /* ---------- the whole analysis ---------- */

  function analyse(state) {
    var settings = state.settings;
    var m = matchTrades(state);
    var journal = {};
    (state.journal || []).forEach(function (e) { journal[e.id] = e; });
    var warnings = [];
    // Enrich each trade with its journal fields, risk and base-currency figures.
    m.trades.forEach(function (t) {
      var j = journal[t.id] || { setup: '', stop: '', risk: '', target: '', mistakes: [], notes: '' };
      t.setup = j.setup || '';
      t.mistakes = (j.mistakes || []).slice();
      t.notes = j.notes || '';
      t.stopText = j.stop || '';
      t.riskText = j.risk || '';
      t.targetText = j.target || '';
      var stop = j.stop ? parseMicro(j.stop) : null;
      if (stop !== null && /p$/i.test(trim(j.stop)) && t.currency === 'GBP') stop = rnd(stop / 100);
      t.stop = stop;
      var risk = tradeRisk(t, stop);
      var planned = j.risk ? parseCents(j.risk) : null;
      if (planned !== null && planned <= 0) planned = null;
      t.initialRisk = risk ? risk.initial : null;
      t.maxRisk = risk ? risk.max : (planned !== null ? planned : null);
      t.plannedRisk = planned !== null ? planned : (risk && risk.initial > 0 ? risk.initial : null);
      t.r = t.status === 'closed' && t.plannedRisk ? t.net / t.plannedRisk : null;
      var rate = fxRate(settings, t.currency);
      t.rate = rate;
      t.netBase = rate === null ? null : rnd(t.net * rate);
      t.feesBase = rate === null ? null : rnd(t.fees * rate);
      t.grossBase = rate === null ? null : t.netBase + t.feesBase;
      t.target = j.target ? parseMicro(j.target) : null;
      t.breaches = [];
    });
    var missingFx = {};
    m.trades.forEach(function (t) { if (t.rate === null) missingFx[t.currency] = (missingFx[t.currency] || 0) + 1; });
    Object.keys(missingFx).sort(cmp).forEach(function (c) {
      var n = missingFx[c];
      warnings.push({ kind: 'fx', text: plural(n, 'trade') + (n === 1 ? ' is' : ' are') + ' in ' + c + ' but there is no ' + c + ' to ' + settings.base + ' rate, so ' + (n === 1 ? 'it is' : 'they are') + ' left out of the totals. Add a rate under Rules and settings.' });
    });
    // Symbols that look like futures but have no multiplier.
    var symbols = {};
    m.fills.forEach(function (f) {
      var s = symbols[f.account + '|' + f.symbol];
      if (!s) {
        s = symbols[f.account + '|' + f.symbol] = { account: f.account, symbol: f.symbol, root: symbolRoot(f.symbol), currency: f.currency, fills: 0, fileMult: f.mult, asset: f.asset };
      }
      s.fills += 1;
      if (f.asset) s.asset = f.asset;
    });
    var symbolList = Object.keys(symbols).sort(cmp).map(function (k) {
      var s = symbols[k];
      s.mult = multiplierFor(settings, s.symbol, s.fileMult);
      s.multSet = !!(lookup(settings.multipliers || [], s.symbol, 'symbol') || (s.root && lookup(settings.multipliers || [], s.root, 'symbol')));
      s.looksFuture = !!s.root || s.asset === 'future';
      return s;
    });
    var noMult = symbolList.filter(function (s) { return s.looksFuture && !s.multSet && !s.fileMult; });
    if (noMult.length) {
      warnings.push({ kind: 'mult', text: noMult.map(function (s) { return s.symbol; }).join(', ') + (noMult.length === 1 ? ' looks' : ' look') + ' like a futures contract but has no contract multiplier, so each point counts as 1. Set the multiplier under Fills.' });
    }
    if (m.unmatched.length) {
      warnings.push({ kind: 'unmatched', text: m.unmatched.length + (m.unmatched.length === 1 ? ' fill closes' : ' fills close') + ' a position with no opening fill in these exports (probably opened before the first export), so ' + (m.unmatched.length === 1 ? 'it is' : 'they are') + ' not counted as a trade. See Fills.' });
    }
    var closed = m.trades.filter(function (t) { return t.status === 'closed'; }).sort(tradeOrder);
    var open = m.trades.filter(function (t) { return t.status === 'open'; }).sort(function (a, b) { return (a.openT - b.openT) || cmp(a.id, b.id); });
    var all = closed.concat(open);
    var rules = checkRules(closed, open, m.events, settings);
    var accounts = {};
    m.fills.forEach(function (f) { accounts[f.account] = true; });
    m.unattached.forEach(function (e) { accounts[e.account] = true; });
    var weeks = {};
    closed.forEach(function (t) { weeks[weekStart(t.closeDay)] = true; });
    m.fills.forEach(function (f) { weeks[weekStart(f.day)] = true; });
    return {
      settings: settings, fills: m.fills, feeOf: m.feeOf, legsByFill: m.legsByFill, trades: all, closed: closed, open: open,
      unmatched: m.unmatched, unattached: m.unattached, events: m.events, breaches: rules.breaches, ruleSummary: rules.summary,
      warnings: warnings, symbols: symbolList, accounts: Object.keys(accounts).sort(cmp),
      weeks: Object.keys(weeks).map(Number).sort(function (a, b) { return a - b; })
    };
  }
  M.analyse = analyse;

  function tradeOrder(a, b) { return (a.closeT - b.closeT) || (a.openT - b.openT) || cmp(a.id, b.id); }

  /* ---------- rules ---------- */

  // Each rule, with how a breach of it reads in a summary.
  var RULES = [
    { id: 'maxRiskPct', label: 'Maximum risk per trade', broken: 'risk over the limit' },
    { id: 'maxDailyLoss', label: 'Maximum daily loss', broken: 'daily loss limit' },
    { id: 'maxTradesPerDay', label: 'Maximum trades per day', broken: 'too many trades in a day' },
    { id: 'noAddingToLoser', label: 'No adding to a loser', broken: 'added to a loser' },
    { id: 'maxLossR', label: 'Loss no bigger than planned', broken: 'loss bigger than planned' },
    { id: 'needPlannedRisk', label: 'Stop or planned risk recorded', broken: 'no stop or planned risk' }
  ];
  M.RULES = RULES;

  function ruleValue(rule) { var v = rule ? parseFloatText(rule.value) : null; return v === null || !(v > 0) ? null : v; }

  function checkRules(closed, open, events, settings) {
    var rules = settings.rules || defaultRules();
    var breaches = [];
    var unchecked = { maxRiskPct: 0, maxDailyLoss: 0, maxLossR: 0 };
    function add(ruleId, t, day, sec, detail, account) {
      breaches.push({ rule: ruleId, label: ruleLabel(ruleId), account: t ? t.account : account, symbol: t ? t.symbol : '', trade: t ? t.id : '', day: day, sec: sec, detail: detail });
      if (t) t.breaches.push(ruleId);
    }
    var all = closed.concat(open).sort(function (a, b) { return (a.openT - b.openT) || cmp(a.id, b.id); });
    // Account equity when each trade opened: the starting balance plus every trade closed before it.
    var startOf = {};
    function startCents(account) {
      if (has(startOf, account)) return startOf[account];
      var a = accountSettings(settings, account);
      var v = a.start ? parseCents(a.start) : null;
      startOf[account] = v !== null && v > 0 ? v : null;
      return startOf[account];
    }
    // Running totals of closed trades per account, for the equity when a trade opened.
    var runs = {};
    closed.forEach(function (c) {
      var list = runs[c.account] = runs[c.account] || [];
      list.push({ t: c.closeT, cum: (list.length ? list[list.length - 1].cum : 0) + c.net });
    });
    function equityAt(account, t) {
      var s = startCents(account);
      if (s === null) return null;
      var list = runs[account] || [], lo = 0, hi = list.length;
      while (lo < hi) { var mid = Math.floor((lo + hi) / 2); if (list[mid].t <= t) lo = mid + 1; else hi = mid; }
      return lo ? s + list[lo - 1].cum : s;
    }
    var r;
    if ((r = rules.maxRiskPct) && r.on && ruleValue(r) !== null) {
      var pct = ruleValue(r);
      all.forEach(function (t) {
        var risk = t.maxRisk;
        var eq = equityAt(t.account, t.openT);
        if (risk === null || eq === null) { unchecked.maxRiskPct++; return; }
        var limit = rnd(eq * pct / 100);
        if (risk > limit) add('maxRiskPct', t, t.openDay, t.openSec, 'Risked ' + money(risk, t.currency) + ' (' + fmtNum(risk * 100 / eq, 2) + '% of ' + money(eq, t.currency) + '), over the ' + fmtNum(pct, 2) + '% limit of ' + money(limit, t.currency));
      });
    }
    if ((r = rules.maxTradesPerDay) && r.on && ruleValue(r) !== null) {
      var maxN = Math.floor(ruleValue(r));
      var count = {};
      all.forEach(function (t) {
        var k = t.account + '|' + t.openDay;
        count[k] = (count[k] || 0) + 1;
        if (count[k] > maxN) add('maxTradesPerDay', t, t.openDay, t.openSec, 'Trade ' + count[k] + ' of the day; the limit is ' + maxN);
      });
    }
    if ((r = rules.noAddingToLoser) && r.on) {
      all.forEach(function (t) {
        t.adds.forEach(function (a) {
          if (a.worse) add('noAddingToLoser', t, a.day, a.sec, 'Added ' + fmtQty(a.q) + ' at ' + fmtPrice(a.price) + ' while the position was losing (average entry ' + fmtPrice(a.avgBefore) + ')');
        });
      });
    }
    if ((r = rules.maxLossR) && r.on && ruleValue(r) !== null) {
      var maxR = ruleValue(r);
      closed.forEach(function (t) {
        if (t.r === null) { unchecked.maxLossR++; return; }
        if (t.r < -maxR) add('maxLossR', t, t.closeDay, t.closeSec, 'Lost ' + fmtR(t.r) + ', more than the ' + fmtNum(maxR, 2) + 'R allowed: the stop was not respected');
      });
    }
    if ((r = rules.needPlannedRisk) && r.on) {
      closed.forEach(function (t) {
        if (t.plannedRisk === null) add('needPlannedRisk', t, t.openDay, t.openSec, 'No stop or planned risk recorded in the journal');
      });
    }
    if ((r = rules.maxDailyLoss) && r.on && ruleValue(r) !== null) {
      var v = ruleValue(r);
      var byDay = {}, keys = [];
      events.forEach(function (e) {
        var k = e.account + '|' + e.day;
        if (!byDay[k]) { byDay[k] = []; keys.push(k); }
        byDay[k].push(e);
      });
      var tradesByDay = {};
      all.forEach(function (t) { var k = t.account + '|' + t.openDay; (tradesByDay[k] = tradesByDay[k] || []).push(t); });
      keys.forEach(function (k) {
        var list = byDay[k];
        var account = list[0].account, day = list[0].day;
        var limit;
        if (r.unit === 'money') limit = rnd(v * 100);
        else { var s = startCents(account); if (s === null) { unchecked.maxDailyLoss++; return; } limit = rnd(s * v / 100); }
        var run = 0, hitAt = null, total = 0;
        list.forEach(function (e) {
          total += e.cents;
          run += e.cents;
          if (hitAt === null && run <= -limit) hitAt = e.t;
        });
        var cur = currencyOfAccount(all, account, settings.base);
        if (total < -limit) add('maxDailyLoss', null, day, null, account + ' lost ' + money(-total, cur) + ' on ' + fmtDate(day) + ', over the daily limit of ' + money(limit, cur), account);
        if (hitAt !== null) {
          (tradesByDay[k] || []).forEach(function (t) {
            if (t.openT > hitAt) add('maxDailyLoss', t, t.openDay, t.openSec, 'Opened after the daily loss limit of ' + money(limit, cur) + ' had been hit');
          });
        }
      });
    }
    var orderOf = {};
    RULES.forEach(function (x, i) { orderOf[x.id] = i; });
    breaches.sort(function (a, b) {
      return (a.day - b.day) || ((a.sec === null ? -1 : a.sec) - (b.sec === null ? -1 : b.sec)) || (orderOf[a.rule] - orderOf[b.rule]) || cmp(a.trade, b.trade) || cmp(a.account, b.account);
    });
    var summary = RULES.map(function (x) {
      var rule = rules[x.id] || {};
      var n = 0, ids = {};
      breaches.forEach(function (b) { if (b.rule === x.id) { n++; if (b.trade) ids[b.trade] = true; } });
      return { id: x.id, label: x.label, broken: x.broken, on: !!rule.on, breaches: n, trades: Object.keys(ids).length, unchecked: unchecked[x.id] || 0 };
    });
    return { breaches: breaches, summary: summary };
  }
  M.checkRules = checkRules;

  function ruleLabel(id) { for (var i = 0; i < RULES.length; i++) if (RULES[i].id === id) return RULES[i].label; return id; }
  M.ruleLabel = ruleLabel;
  function currencyOfAccount(trades, account, base) {
    for (var i = 0; i < trades.length; i++) if (trades[i].account === account) return trades[i].currency;
    return base;
  }

  /* ---------- statistics ---------- */

  // Trades with a base-currency figure, in the order they closed.
  function usable(trades) { return trades.filter(function (t) { return t.status === 'closed' && t.netBase !== null; }); }

  function stats(trades, opts) {
    opts = opts || {};
    var list = usable(trades);
    var s = {
      n: list.length, wins: 0, losses: 0, flat: 0, net: 0, gross: 0, fees: 0, grossWin: 0, grossLoss: 0, winRate: null,
      avgWin: null, avgLoss: null, payoff: null, expectancy: null, profitFactor: null, best: null, worst: null,
      maxWinStreak: 0, maxLossStreak: 0, avgHoldWin: null, avgHoldLoss: null, avgHold: null,
      rCount: 0, rSum: 0, avgR: null, rWins: 0, maxDD: 0, maxDDPct: null, ddFrom: null, ddTo: null, recovery: null,
      curve: [], days: [], sharpe: null, sortino: null, longN: 0, shortN: 0, longNet: 0, shortNet: 0
    };
    var streakW = 0, streakL = 0, holdW = 0, holdL = 0, holdN = 0, holdAll = 0, nW = 0, nL = 0;
    var start = opts.start || 0;
    var cum = 0, peak = start, peakT = null, dayNet = {}, dayList = [];
    list.forEach(function (t) {
      var v = t.netBase;
      s.net += v; s.fees += t.feesBase; s.gross += t.grossBase;
      if (t.dir > 0) { s.longN++; s.longNet += v; } else { s.shortN++; s.shortNet += v; }
      if (t.net > 0) { s.wins++; s.grossWin += v; streakW++; streakL = 0; if (t.holdSec !== null) { holdW += t.holdSec; nW++; } }
      else if (t.net < 0) { s.losses++; s.grossLoss -= v; streakL++; streakW = 0; if (t.holdSec !== null) { holdL += t.holdSec; nL++; } }
      else { s.flat++; streakW = 0; streakL = 0; }
      if (streakW > s.maxWinStreak) s.maxWinStreak = streakW;
      if (streakL > s.maxLossStreak) s.maxLossStreak = streakL;
      if (t.holdSec !== null) { holdAll += t.holdSec; holdN++; }
      if (s.best === null || v > s.best.net) s.best = { id: t.id, net: v };
      if (s.worst === null || v < s.worst.net) s.worst = { id: t.id, net: v };
      if (t.r !== null) { s.rCount++; s.rSum += t.r; if (t.r > 0) s.rWins++; }
      cum += v;
      var eq = start + cum;
      if (eq > peak) { peak = eq; peakT = t.closeT; }
      var dd = peak - eq;
      if (dd > s.maxDD) { s.maxDD = dd; s.ddFrom = peakT; s.ddTo = t.closeT; s.maxDDPct = peak > 0 && start > 0 ? dd * 100 / peak : null; }
      s.curve.push({ t: t.closeT, id: t.id, cum: cum });
      if (!has(dayNet, t.closeDay)) { dayNet[t.closeDay] = 0; dayList.push(t.closeDay); }
      dayNet[t.closeDay] += v;
    });
    if (s.n) {
      s.winRate = s.wins / s.n;
      s.expectancy = s.net / s.n;
    }
    if (s.wins) s.avgWin = s.grossWin / s.wins;
    if (s.losses) s.avgLoss = s.grossLoss / s.losses;
    if (s.avgWin !== null && s.avgLoss) s.payoff = s.avgWin / s.avgLoss;
    if (s.grossLoss > 0) s.profitFactor = s.grossWin / s.grossLoss;
    if (nW) s.avgHoldWin = rnd(holdW / nW);
    if (nL) s.avgHoldLoss = rnd(holdL / nL);
    if (holdN) s.avgHold = rnd(holdAll / holdN);
    if (s.rCount) s.avgR = s.rSum / s.rCount;
    if (s.maxDD > 0) s.recovery = s.net / s.maxDD;
    s.days = dayList.map(function (d) { return { day: d, net: dayNet[d] }; });
    // Daily Sharpe and Sortino ratios on days with closed trades, as returns on the starting balance, times the square root of 252.
    if (start > 0 && s.days.length >= 2) {
      var sum = 0, n = s.days.length;
      s.days.forEach(function (d) { sum += d.net / start; });
      var mean = sum / n, ss = 0, down = 0;
      s.days.forEach(function (d) { var x = d.net / start - mean; ss += x * x; var y = d.net / start; if (y < 0) down += y * y; });
      var sd = Math.sqrt(ss / (n - 1));
      if (sd > 0) s.sharpe = mean / sd * Math.sqrt(252);
      var dsd = Math.sqrt(down / n);
      if (dsd > 0) s.sortino = mean / dsd * Math.sqrt(252);
    }
    return s;
  }
  M.stats = stats;

  var HOLD_BUCKETS = [
    { key: 'h1', label: 'Under 5 min' },
    { key: 'h2', label: '5 to 30 min' },
    { key: 'h3', label: '30 min to 2 h' },
    { key: 'h4', label: '2 h or more, same day' },
    { key: 'h5', label: 'Same day, no times' },
    { key: 'h6', label: '1 to 4 nights' },
    { key: 'h7', label: '5 nights or more' }
  ];
  function holdBucket(t) {
    var nights = t.closeDay - t.openDay;
    if (nights >= 5) return 'h7';
    if (nights >= 1) return 'h6';
    if (!t.timeKnown) return 'h5';
    if (t.holdSec < 300) return 'h1';
    if (t.holdSec < 1800) return 'h2';
    if (t.holdSec < 7200) return 'h3';
    return 'h4';
  }
  M.holdBucket = holdBucket;

  var BREAKDOWNS = [
    { id: 'setup', label: 'Setup' },
    { id: 'symbol', label: 'Symbol' },
    { id: 'side', label: 'Long or short' },
    { id: 'weekday', label: 'Day of the week' },
    { id: 'hour', label: 'Hour opened' },
    { id: 'hold', label: 'Holding time' },
    { id: 'mistake', label: 'Mistake tag' },
    { id: 'account', label: 'Account' }
  ];
  M.BREAKDOWNS = BREAKDOWNS;

  function groupKeys(t, by) {
    if (by === 'setup') return [t.setup || '(no setup)'];
    if (by === 'symbol') return [t.symbol];
    if (by === 'side') return [t.dir > 0 ? 'Long' : 'Short'];
    if (by === 'weekday') return [String(weekday(t.openDay))];
    if (by === 'hour') return [t.openSec === null || !t.timeKnown ? '99' : pad2(Math.floor(t.openSec / 3600))];
    if (by === 'hold') return [holdBucket(t)];
    if (by === 'mistake') return t.mistakes.length ? t.mistakes.slice() : ['(none tagged)'];
    if (by === 'account') return [t.account];
    return [''];
  }
  function groupLabel(key, by) {
    if (by === 'weekday') return DAY_LONG[+key];
    if (by === 'hour') return key === '99' ? 'Time not given' : key + ':00 to ' + key + ':59';
    if (by === 'hold') { for (var i = 0; i < HOLD_BUCKETS.length; i++) if (HOLD_BUCKETS[i].key === key) return HOLD_BUCKETS[i].label; }
    return key;
  }
  var NATURAL = { weekday: true, hour: true, hold: true };

  function breakdown(trades, by) {
    var list = usable(trades);
    var groups = {}, keys = [];
    list.forEach(function (t) {
      groupKeys(t, by).forEach(function (k) {
        if (!groups[k]) { groups[k] = []; keys.push(k); }
        groups[k].push(t);
      });
    });
    var rows = keys.map(function (k) {
      var g = groups[k];
      var net = 0, wins = 0, losses = 0, gw = 0, gl = 0, rN = 0, rS = 0, fees = 0;
      g.forEach(function (t) {
        net += t.netBase; fees += t.feesBase;
        if (t.net > 0) { wins++; gw += t.netBase; } else if (t.net < 0) { losses++; gl -= t.netBase; }
        if (t.r !== null) { rN++; rS += t.r; }
      });
      return {
        key: k, label: groupLabel(k, by), n: g.length, wins: wins, losses: losses, winRate: wins / g.length, net: net, fees: fees,
        avg: net / g.length, profitFactor: gl > 0 ? gw / gl : null, avgR: rN ? rS / rN : null, rCount: rN
      };
    });
    if (NATURAL[by]) rows.sort(function (a, b) { return cmp(a.key, b.key); });
    else rows.sort(function (a, b) { return (b.net - a.net) || (b.n - a.n) || cmp(a.label, b.label); });
    return rows;
  }
  M.breakdown = breakdown;

  // Net profit of every week (Monday start) in a span of weeks, for the weekly bars.
  function weekly(trades) {
    var list = usable(trades), byWeek = {}, keys = [];
    list.forEach(function (t) {
      var w = weekStart(t.closeDay);
      if (!byWeek[w]) { byWeek[w] = { week: w, n: 0, net: 0, wins: 0 }; keys.push(w); }
      byWeek[w].n++; byWeek[w].net += t.netBase; if (t.net > 0) byWeek[w].wins++;
    });
    keys.sort(function (a, b) { return a - b; });
    return keys.map(function (k) { return byWeek[k]; });
  }
  M.weekly = weekly;

  // R multiples in buckets of half an R from -3 to +4 (outside goes in the end buckets).
  function rHistogram(trades) {
    var edges = [];
    for (var e = -3; e < 4; e += 0.5) edges.push(e);
    var counts = edges.map(function () { return 0; });
    usable(trades).forEach(function (t) {
      if (t.r === null) return;
      var i = Math.floor((t.r + 3) / 0.5);
      if (i < 0) i = 0;
      if (i >= counts.length) i = counts.length - 1;
      counts[i]++;
    });
    return edges.map(function (e, i) { return { from: e, to: e + 0.5, n: counts[i] }; });
  }
  M.rHistogram = rHistogram;

  /* ---------- filters and periods ---------- */

  // Trades for a period and account. period: {from: day, to: day} on the closing day (open trades use their opening day).
  function filterTrades(trades, f) {
    f = f || {};
    return trades.filter(function (t) {
      if (f.account && t.account !== f.account) return false;
      var d = t.status === 'closed' ? t.closeDay : t.openDay;
      if (f.from !== undefined && f.from !== null && d < f.from) return false;
      if (f.to !== undefined && f.to !== null && d > f.to) return false;
      return true;
    });
  }
  M.filterTrades = filterTrades;

  // The starting balances of some accounts, in the base currency (0 when none is set).
  function startBalance(result, accounts) {
    var settings = result.settings;
    var total = 0, any = false;
    accounts.forEach(function (a) {
      var s = accountSettings(settings, a);
      var v = s.start ? parseCents(s.start) : null;
      if (v !== null && v > 0) {
        var cur = s.currency || currencyOfAccount(result.trades, a, settings.base);
        var rate = fxRate(settings, cur);
        if (rate !== null) { total += rnd(v * rate); any = true; }
      }
    });
    return any ? total : 0;
  }
  M.startBalance = startBalance;

  /* ---------- days ---------- */

  // A converter from each account's currency to the base currency (null when there is no rate).
  function toBase(result) {
    var rates = {};
    return function (account, cents) {
      if (!has(rates, account)) rates[account] = fxRate(result.settings, currencyOfAccount(result.trades, account, result.settings.base));
      return rates[account] === null ? null : rnd(cents * rates[account]);
    };
  }

  // Every trading day: profit realised after fees (partial closes and loose fees included), trades opened and closed, breaches.
  function dayLedger(result, opts) {
    var account = (opts && opts.account) || '';
    var conv = toBase(result), map = {}, keys = [];
    function at(day) {
      if (!has(map, day)) { map[day] = { day: day, realised: 0, pnl: 0, fees: 0, opened: 0, closed: 0, wins: 0, losses: 0, closedNet: 0, breaches: 0, limitHit: false }; keys.push(day); }
      return map[day];
    }
    result.events.forEach(function (e) {
      if ((account && e.account !== account) || e.day < 1) return;
      var v = conv(e.account, e.cents);
      if (v === null) return;
      var d = at(e.day);
      d.realised += v;
      if (e.kind === 'pnl') d.pnl += v; else d.fees -= v;
    });
    result.trades.forEach(function (t) {
      if (account && t.account !== account) return;
      at(t.openDay).opened++;
      if (t.status === 'closed' && t.netBase !== null) {
        var d = at(t.closeDay);
        d.closed++;
        d.closedNet += t.netBase;
        if (t.net > 0) d.wins++; else if (t.net < 0) d.losses++;
      }
    });
    result.breaches.forEach(function (b) {
      if (account && b.account !== account) return;
      var d = at(b.day);
      d.breaches++;
      if (b.rule === 'maxDailyLoss' && !b.trade) d.limitHit = true;
    });
    keys.sort(function (a, b) { return a - b; });
    return keys.map(function (k) { return map[k]; });
  }
  M.dayLedger = dayLedger;

  // One day replayed fill by fill: the running total of realised profit after fees, its high, low and largest drop.
  function dayDetail(result, day, opts) {
    var account = (opts && opts.account) || '';
    var conv = toBase(result);
    var list = result.events.filter(function (e) { return e.day === day && (!account || e.account === account); })
      .sort(function (a, b) { return (a.t - b.t) || cmp(a.account, b.account) || (a.seq - b.seq) || cmp(a.kind, b.kind); });
    var rows = [], run = 0, high = 0, low = 0, drop = 0;
    list.forEach(function (e) {
      var v = conv(e.account, e.cents);
      if (v === null) return;
      var last = rows.length ? rows[rows.length - 1] : null;
      var row = last && last.t === e.t && last.account === e.account && last.seq === e.seq ? last : null;
      if (!row) {
        row = { t: e.t, sec: e.sec, account: e.account, symbol: e.symbol, seq: e.seq, trades: [], pnl: 0, fees: 0, total: 0 };
        rows.push(row);
      }
      if (e.trade && row.trades.indexOf(e.trade) < 0) row.trades.push(e.trade);
      if (e.kind === 'pnl') row.pnl += v; else row.fees -= v;
      run += v;
      row.total = run;
      if (run > high) high = run;
      if (run < low) low = run;
      if (high - run > drop) drop = high - run;
    });
    var breaches = result.breaches.filter(function (b) { return b.day === day && (!account || b.account === account); });
    var opened = result.trades.filter(function (t) { return t.openDay === day && (!account || t.account === account); }).map(function (t) { return t.id; });
    return { day: day, account: account, rows: rows, total: run, high: high, low: low, drop: drop, breaches: breaches, opened: opened };
  }
  M.dayDetail = dayDetail;

  /* ---------- formatting (shared by the page, the review text and the files) ---------- */

  var SYMBOLS = { USD: '$', GBP: '£', EUR: '€' };
  function group3(digits) {
    var out = '';
    for (var i = 0; i < digits.length; i++) {
      if (i > 0 && (digits.length - i) % 3 === 0) out += ',';
      out += digits.charAt(i);
    }
    return out;
  }
  // Cents as money: -$1,234.56. opts.sign adds a plus to positives, opts.whole drops the pennies.
  function money(cents, currency, opts) {
    opts = opts || {};
    if (cents === null || cents === undefined) return '';
    var neg = cents < 0, v = neg ? -cents : cents;
    if (opts.whole) v = rnd(v / 100) * 100;
    var units = String(Math.floor(v / 100)), pence = pad2(v % 100);
    var sym = SYMBOLS[currency];
    var body = group3(units) + (opts.whole ? '' : '.' + pence);
    var text = sym ? sym + body : (currency ? currency + ' ' : '') + body;
    if (neg && v !== 0) return '-' + text;
    if (opts.sign && v !== 0) return '+' + text;
    return text;
  }
  M.money = money;

  // A number with a fixed number of decimals, half away from zero, without toFixed.
  function fmtNum(x, dp) {
    if (x === null || x === undefined) return '';
    var f = Math.pow(10, dp);
    var v = rnd(x * f);
    var neg = v < 0;
    if (neg) v = -v;
    var whole = String(Math.floor(v / f));
    var frac = dp ? String(v % f) : '';
    while (frac.length < dp) frac = '0' + frac;
    return (neg ? '-' : '') + group3(whole) + (dp ? '.' + frac : '');
  }
  M.fmtNum = fmtNum;
  function fmtPct(x, dp) { return x === null || x === undefined ? '' : fmtNum(x * 100, dp === undefined ? 0 : dp) + '%'; }
  M.fmtPct = fmtPct;
  function fmtR(r) { return r === null || r === undefined ? '' : (r > 0 && rnd(r * 100) !== 0 ? '+' : '') + fmtNum(r, 2) + 'R'; }
  M.fmtR = fmtR;

  // A price in millionths, with at least two decimals and no trailing zeros beyond that.
  function fmtPrice(micro, grouping) {
    if (micro === null || micro === undefined) return '';
    var v = rnd(micro);
    var neg = v < 0;
    if (neg) v = -v;
    var whole = String(Math.floor(v / PRICE_SCALE));
    var frac = String(v % PRICE_SCALE);
    while (frac.length < 6) frac = '0' + frac;
    frac = frac.replace(/0+$/, '');
    while (frac.length < 2) frac += '0';
    return (neg ? '-' : '') + (grouping ? group3(whole) : whole) + '.' + frac;
  }
  M.fmtPrice = fmtPrice;
  function fmtQty(q) {
    if (q === null || q === undefined) return '';
    var v = rnd(q);
    var neg = v < 0;
    if (neg) v = -v;
    var whole = String(Math.floor(v / QTY_SCALE));
    var frac = String(v % QTY_SCALE);
    while (frac.length < 6) frac = '0' + frac;
    frac = frac.replace(/0+$/, '');
    return (neg ? '-' : '') + group3(whole) + (frac ? '.' + frac : '');
  }
  M.fmtQty = fmtQty;
  function fmtDate(day) { var c = civil(day); return DAY_NAMES[weekday(day)] + ' ' + c[2] + ' ' + MONTH_NAMES[c[1] - 1] + ' ' + c[0]; }
  function fmtShort(day) { var c = civil(day); return c[2] + ' ' + MONTH_NAMES[c[1] - 1]; }
  function fmtDayMonthYear(day) { var c = civil(day); return c[2] + ' ' + MONTH_NAMES[c[1] - 1] + ' ' + c[0]; }
  function fmtTime(sec) { return sec === null || sec === undefined ? '' : pad2(Math.floor(sec / 3600)) + ':' + pad2(Math.floor(sec / 60) % 60); }
  function fmtTimeLong(sec) { return sec === null || sec === undefined ? '' : fmtTime(sec) + ':' + pad2(sec % 60); }
  M.fmtDate = fmtDate;
  M.fmtShort = fmtShort;
  M.fmtDayMonthYear = fmtDayMonthYear;
  M.fmtTime = fmtTime;
  M.fmtTimeLong = fmtTimeLong;
  function fmtDuration(sec, timeKnown) {
    if (sec === null || sec === undefined) return '';
    if (timeKnown === false) { var d0 = Math.floor(sec / DAY); return d0 === 0 ? 'same day' : d0 + (d0 === 1 ? ' day' : ' days'); }
    if (sec < 60) return sec + ' s';
    var mins = Math.floor(sec / 60);
    if (mins < 60) return mins + ' min';
    var h = Math.floor(mins / 60), m = mins % 60;
    if (h < 24) return h + ' h ' + pad2(m) + ' min';
    var d = Math.floor(h / 24);
    return d + (d === 1 ? ' day ' : ' days ') + (h % 24) + ' h';
  }
  M.fmtDuration = fmtDuration;
  function weekLabel(week) { return 'w/c ' + fmtDayMonthYear(week); }
  M.weekLabel = weekLabel;
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
  M.plural = plural;

  /* ---------- the weekly review ---------- */

  function weekReview(result, opts) {
    opts = opts || {};
    var week = opts.week;
    var account = opts.account || '';
    var base = result.settings.base;
    var accounts = account ? [account] : result.accounts;
    var start = startBalance(result, accounts);
    var inWeek = filterTrades(result.closed, { account: account, from: week, to: week + 6 });
    var before = filterTrades(result.closed, { account: account, to: week - 1 });
    var startOfWeek = start;
    usable(before).forEach(function (t) { startOfWeek += t.netBase; });
    var s = stats(inWeek, { start: startOfWeek });
    var prevWeeks = [];
    for (var w = 1; w <= 4; w++) {
      var ws = week - 7 * w;
      var tr = filterTrades(result.closed, { account: account, from: ws, to: ws + 6 });
      if (usable(tr).length) prevWeeks.push(stats(tr, {}));
    }
    var prev = null;
    if (prevWeeks.length) {
      var pn = 0, pnet = 0, pw = 0;
      prevWeeks.forEach(function (p) { pn += p.n; pnet += p.net; pw += p.wins; });
      prev = { weeks: prevWeeks.length, n: pn, net: pnet, perWeek: pnet / prevWeeks.length, expectancy: pn ? pnet / pn : null, winRate: pn ? pw / pn : null };
    }
    var breaches = result.breaches.filter(function (b) { return (!account || b.account === account) && b.day >= week && b.day <= week + 6; });
    var breachCount = {};
    breaches.forEach(function (b) { breachCount[b.rule] = (breachCount[b.rule] || 0) + 1; });
    var broke = { n: 0, net: 0 }, kept = { n: 0, net: 0 };
    usable(inWeek).forEach(function (t) {
      var x = t.breaches.length > 0 ? broke : kept;
      x.n++; x.net += t.netBase;
    });
    // Positions still open at the end of the week.
    var endT = (week + 7) * DAY;
    var openAtEnd = [];
    result.trades.forEach(function (t) {
      if (account && t.account !== account) return;
      if (t.openT >= endT) return;
      if (t.status === 'closed' && t.closeT < endT) return;
      var q = 0;
      t.legs.forEach(function (l) {
        if (l.day * DAY + (l.sec === null ? 0 : l.sec) >= endT) return;
        q += (l.role === 'open' || l.role === 'add') ? l.q : -l.q;
      });
      if (q > 0) openAtEnd.push({ id: t.id, account: t.account, symbol: t.symbol, dir: t.dir, q: q, avgEntry: t.avgEntry, openDay: t.openDay, currency: t.currency });
    });
    var fees = 0;
    result.unattached.forEach(function (e) {
      if ((!account || e.account === account) && e.day !== null && e.day >= week && e.day <= week + 6) {
        var rate = fxRate(result.settings, currencyOfAccount(result.trades, e.account, base));
        if (rate !== null) fees += rnd(e.amount * rate);
      }
    });
    var untagged = 0, noRisk = 0;
    usable(inWeek).forEach(function (t) { if (!t.setup) untagged++; if (t.plannedRisk === null) noRisk++; });
    var review = {
      week: week, account: account, base: base, label: weekLabel(week), start: startOfWeek, stats: s, prev: prev,
      bySetup: breakdown(inWeek, 'setup'), bySymbol: breakdown(inWeek, 'symbol'), byMistake: breakdown(inWeek, 'mistake').filter(function (r) { return r.key !== '(none tagged)'; }),
      byHour: breakdown(inWeek, 'hour'), byHold: breakdown(inWeek, 'hold'),
      breaches: breaches, breachCount: breachCount, broke: broke, kept: kept, openAtEnd: openAtEnd, unattachedFees: fees,
      untagged: untagged, noRisk: noRisk, trades: usable(inWeek).map(function (t) { return t.id; })
    };
    review.notes = reviewNotes(review, result);
    return review;
  }
  M.weekReview = weekReview;

  function reviewNotes(rv, result) {
    var s = rv.stats, base = rv.base, notes = [];
    if (!s.n) { notes.push('No trades closed this week.'); return notes; }
    if (s.gross > 0 && s.net <= 0) notes.push('Before fees the week made ' + money(s.gross, base) + '; fees of ' + money(s.fees, base) + ' turned it into ' + money(s.net, base, { sign: true }) + '.');
    else if (s.gross > 0 && s.fees * 4 >= s.gross) notes.push('Fees took ' + fmtPct(s.fees / s.gross) + ' of the profit before fees (' + money(s.fees, base) + ' of ' + money(s.gross, base) + ').');
    var setups = rv.bySetup.filter(function (r) { return r.key !== '(no setup)' && r.n >= 2; });
    if (setups.length >= 2) {
      var top = setups[0], bottom = setups[setups.length - 1];
      if (top.net > 0) notes.push(top.label + ' made the most: ' + money(top.net, base, { sign: true }) + ' over ' + plural(top.n, 'trade') + ' (' + top.wins + ' won).');
      if (bottom.net < 0) notes.push(bottom.label + ' cost the most: ' + money(bottom.net, base, { sign: true }) + ' over ' + plural(bottom.n, 'trade') + ' (' + bottom.wins + ' won).');
    }
    if (rv.broke.n && rv.kept.n) {
      notes.push(plural(rv.broke.n, 'trade') + ' broke at least one rule and made ' + money(rv.broke.net, base, { sign: true }) + '; the ' + plural(rv.kept.n, 'trade') + ' that kept to every rule made ' + money(rv.kept.net, base, { sign: true }) + '.');
    } else if (rv.broke.n) {
      notes.push((rv.broke.n === 1 ? 'The only trade' : 'All ' + rv.broke.n + ' trades') + ' broke at least one rule, and made ' + money(rv.broke.net, base, { sign: true }) + ' between them.');
    } else {
      notes.push('Every trade kept to the rules this week.');
    }
    if (s.avgHoldWin !== null && s.avgHoldLoss !== null && s.avgHoldLoss >= s.avgHoldWin * 1.5 && s.avgHoldLoss >= 120) {
      notes.push('Losing trades were held ' + fmtNum(s.avgHoldLoss / s.avgHoldWin, 1) + ' times as long as winners (' + fmtDuration(s.avgHoldLoss) + ' against ' + fmtDuration(s.avgHoldWin) + ').');
    }
    var hours = rv.byHour.filter(function (r) { return r.n >= 3 && r.key !== '99'; }).sort(function (a, b) { return (a.net - b.net) || cmp(a.key, b.key); });
    if (hours.length >= 2 && hours[0].net < 0) notes.push('Trades opened ' + hours[0].label + ' were the weakest hour: ' + money(hours[0].net, base, { sign: true }) + ' over ' + plural(hours[0].n, 'trade') + '.');
    if (rv.prev && rv.prev.expectancy !== null && s.expectancy !== null) {
      notes.push('Expectancy ' + money(rnd(s.expectancy), base, { sign: true }) + ' a trade, against ' + money(rnd(rv.prev.expectancy), base, { sign: true }) + ' over the previous ' + plural(rv.prev.weeks, 'week') + ' with trades.');
    }
    if (rv.untagged || rv.noRisk) {
      var parts = [];
      if (rv.untagged) parts.push(plural(rv.untagged, 'trade') + ' with no setup');
      if (rv.noRisk) parts.push(plural(rv.noRisk, 'trade') + ' with no stop or planned risk');
      notes.push('Journal gaps: ' + parts.join(' and ') + '. Fill them in so the setup and R figures cover the whole week.');
    }
    return notes;
  }

  function tradeName(t) {
    return t.symbol + ' ' + (t.dir > 0 ? 'long' : 'short') + ' ' + fmtShort(t.openDay);
  }
  M.tradeName = tradeName;

  // The review as plain text for a team chat.
  function reviewText(rv, result) {
    var s = rv.stats, base = rv.base, L = [];
    var byId = {};
    result.trades.forEach(function (t) { byId[t.id] = t; });
    L.push('WEEKLY TRADE REVIEW: ' + rv.label + ' to ' + fmtDayMonthYear(rv.week + 6) + (rv.account ? ' (' + rv.account + ')' : ' (all accounts)'));
    if (!s.n) {
      L.push('No trades closed this week.');
    } else {
      L.push('Net after fees: ' + money(s.net, base, { sign: true }) + ' from ' + plural(s.n, 'closed trade') + ' (fees ' + money(s.fees, base) + ', before fees ' + money(s.gross, base, { sign: true }) + ')');
      L.push('Win rate ' + fmtPct(s.winRate) + ' (' + s.wins + ' won, ' + s.losses + ' lost' + (s.flat ? ', ' + s.flat + ' flat' : '') + '), expectancy ' + money(rnd(s.expectancy), base, { sign: true }) + ' a trade, profit factor ' + (s.profitFactor === null ? 'n/a (no losses)' : fmtNum(s.profitFactor, 2)));
      L.push('Average win ' + (s.avgWin === null ? 'n/a' : money(rnd(s.avgWin), base)) + ', average loss ' + (s.avgLoss === null ? 'n/a' : money(rnd(s.avgLoss), base)) + (s.rCount ? '; average ' + fmtR(s.avgR) + ' on ' + plural(s.rCount, 'trade') + ' with planned risk' : ''));
      var best = byId[s.best.id], worst = byId[s.worst.id];
      L.push('Best: ' + tradeName(best) + ' ' + money(s.best.net, base, { sign: true }) + (best.setup ? ' (' + best.setup + ')' : '') + '. Worst: ' + tradeName(worst) + ' ' + money(s.worst.net, base, { sign: true }) + (worst.setup ? ' (' + worst.setup + ')' : ''));
      L.push('Largest drop from a high this week: ' + money(s.maxDD, base) + '; longest losing run: ' + plural(s.maxLossStreak, 'trade'));
      var setups = rv.bySetup.slice(0, 6).map(function (r) { return r.label + ' ' + money(r.net, base, { sign: true }) + ' (' + r.n + ')'; });
      if (setups.length) L.push('Setups: ' + setups.join('; '));
    }
    if (rv.breaches.length) {
      var parts = RULES.filter(function (x) { return rv.breachCount[x.id]; }).map(function (x) { return x.broken + ' x' + rv.breachCount[x.id]; });
      L.push('Rule breaches: ' + rv.breaches.length + ' (' + parts.join(', ') + ')');
    } else {
      L.push('Rule breaches: none');
    }
    if (rv.byMistake.length) L.push('Mistakes tagged: ' + rv.byMistake.map(function (r) { return r.label + ' x' + r.n + ' (' + money(r.net, base, { sign: true }) + ')'; }).join('; '));
    if (rv.openAtEnd.length) L.push('Open at the end of the week: ' + rv.openAtEnd.map(function (o) { return o.symbol + ' ' + (o.dir > 0 ? 'long ' : 'short ') + fmtQty(o.q) + ' at ' + fmtPrice(rnd(o.avgEntry / 100) * 100); }).join('; '));
    if (rv.unattachedFees) L.push('Fees not tied to a trade: ' + money(rv.unattachedFees, base));
    if (rv.notes.length) {
      L.push('');
      L.push('Notes:');
      rv.notes.forEach(function (n) { L.push('- ' + n); });
    }
    L.push('');
    L.push('Built from our own fills exports. Not financial advice.');
    return L.join('\n') + '\n';
  }
  M.reviewText = reviewText;

  /* ---------- position size ---------- */

  // How many shares or contracts to trade so a stop-out loses no more than the chosen risk.
  function positionSize(inp) {
    var equity = parseCents(inp.equity);
    var pct = parseFloatText(inp.riskPct);
    var entry = parseMicro(inp.entry);
    var stop = parseMicro(inp.stop);
    var mult = parseFloatText(inp.mult);
    var fee = inp.fee ? parseCents(inp.fee) : 0;
    var step = inp.step ? parseFloatText(inp.step) : 1;
    var allowance = inp.allowance ? parseCents(inp.allowance) : null;
    if (equity === null || !(equity > 0)) return { ok: false, msg: 'Enter the account size.' };
    if (pct === null || !(pct > 0)) return { ok: false, msg: 'Enter the risk per trade as a percentage of the account.' };
    if (entry === null || !(entry > 0)) return { ok: false, msg: 'Enter the entry price.' };
    if (stop === null || !(stop > 0)) return { ok: false, msg: 'Enter the stop price.' };
    if (stop === entry) return { ok: false, msg: 'The stop must be away from the entry.' };
    if (mult === null || !(mult > 0)) mult = 1;
    if (fee === null || fee < 0) fee = 0;
    if (step === null || !(step > 0)) step = 1;
    var dir = stop < entry ? 1 : -1;
    var perUnit = (entry - stop) * dir * mult / 10000 + fee;
    var budget = equity * pct / 100;
    var limitedBy = 'risk';
    if (allowance !== null && allowance >= 0 && allowance < budget) { budget = allowance; limitedBy = 'allowance'; }
    var units = Math.floor(budget / perUnit / step + 1e-9) * step;
    units = rnd(units * 1000000) / 1000000;
    var risk = rnd(units * perUnit);
    var value = rnd(units * entry * mult / 10000);
    var targets = [1, 2, 3].map(function (k) { return { r: k, price: entry + k * (entry - stop) }; });
    return {
      ok: units > 0, msg: units > 0 ? '' : 'The stop is too far away for this risk: even one ' + (step < 1 ? 'step' : 'unit') + ' would risk more than ' + money(rnd(budget), inp.currency || '') + '.',
      direction: dir > 0 ? 'long' : 'short', units: units, perUnit: rnd(perUnit), budget: rnd(budget), risk: risk, riskPct: risk * 100 / equity,
      value: value, valuePct: value * 100 / equity, limitedBy: limitedBy, targets: targets
    };
  }
  M.positionSize = positionSize;

  /* ---------- files ---------- */

  function csvCell(v) {
    var s = str(v);
    if (/[",\r\n]/.test(s) || /^\s|\s$/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
  }
  function csvLines(rows) { return '\ufeff' + rows.map(function (r) { return r.map(csvCell).join(','); }).join('\r\n') + '\r\n'; }
  M.csvCell = csvCell;

  function plainMoney(cents) {
    if (cents === null || cents === undefined) return '';
    var neg = cents < 0, v = neg ? -cents : cents;
    return (neg ? '-' : '') + Math.floor(v / 100) + '.' + pad2(v % 100);
  }
  M.plainMoney = plainMoney;

  function tradesCsv(result, trades) {
    var list = trades || result.trades;
    var base = result.settings.base;
    var rows = [['Trade ID', 'Account', 'Symbol', 'Direction', 'Status', 'Opened', 'Closed', 'Holding (minutes)', 'Max position', 'Entry orders', 'Exit orders', 'Average entry', 'Average exit',
      'Multiplier', 'Currency', 'Gross P&L', 'Fees', 'Net P&L', 'Net P&L (' + base + ')', 'Stop', 'Planned risk', 'Max risk', 'R multiple', 'Setup', 'Mistakes', 'Rule breaches', 'Notes']];
    list.forEach(function (t) {
      rows.push([
        t.id, t.account, t.symbol, t.dir > 0 ? 'Long' : 'Short', t.status === 'closed' ? 'Closed' : 'Open',
        isoStamp(t.openDay, t.openSec).replace('T', ' '), t.closeDay === null ? '' : isoStamp(t.closeDay, t.closeSec).replace('T', ' '),
        t.holdSec === null ? '' : fmtNum(t.holdSec / 60, 1).replace(/,/g, ''), fmtQty(t.maxPos).replace(/,/g, ''), t.entryOrders, t.exitOrders,
        fmtPrice(t.avgEntry), t.qtyOut ? fmtPrice(t.avgExit) : '', fmtNum(t.mult, 4).replace(/,/g, '').replace(/\.?0+$/, ''), t.currency,
        plainMoney(t.gross), plainMoney(t.fees), plainMoney(t.net), t.netBase === null ? '' : plainMoney(t.netBase),
        t.stop === null ? '' : fmtPrice(t.stop), t.plannedRisk === null ? '' : plainMoney(t.plannedRisk), t.maxRisk === null ? '' : plainMoney(t.maxRisk),
        t.r === null ? '' : fmtNum(t.r, 2), t.setup, t.mistakes.join('; '), t.breaches.map(ruleLabel).filter(function (x, i, a) { return a.indexOf(x) === i; }).join('; '), t.notes
      ]);
    });
    return csvLines(rows);
  }
  M.tradesCsv = tradesCsv;

  function daysCsv(result, account) {
    var base = result.settings.base;
    var rows = [['Date', 'Weekday', 'Realised after fees (' + base + ')', 'Before fees', 'Fees', 'Trades opened', 'Trades closed', 'Won', 'Lost', 'Closed trades net', 'Rule breaches', 'Daily limit hit']];
    dayLedger(result, { account: account }).forEach(function (d) {
      rows.push([toIso(d.day), DAY_LONG[weekday(d.day)], plainMoney(d.realised), plainMoney(d.pnl), plainMoney(d.fees), d.opened, d.closed, d.wins, d.losses, plainMoney(d.closedNet), d.breaches, d.limitHit ? 'Yes' : '']);
    });
    return csvLines(rows);
  }
  M.daysCsv = daysCsv;

  function breachesCsv(result, breaches) {
    var byId = {};
    result.trades.forEach(function (t) { byId[t.id] = t; });
    var rows = [['Date', 'Time', 'Account', 'Symbol', 'Rule', 'What happened', 'Trade ID', 'Trade net P&L']];
    (breaches || result.breaches).forEach(function (b) {
      var t = b.trade ? byId[b.trade] : null;
      rows.push([toIso(b.day), fmtTime(b.sec), b.account, b.symbol, b.label, b.detail, b.trade, t && t.status === 'closed' ? plainMoney(t.net) : '']);
    });
    return csvLines(rows);
  }
  M.breachesCsv = breachesCsv;

  function fillsCsv(result) {
    var rows = [['Date', 'Time', 'Account', 'Symbol', 'Side', 'Quantity', 'Price', 'Fees', 'Currency', 'Order ID', 'Trade ID', 'Role', 'File', 'Line']];
    result.fills.forEach(function (f) {
      var legs = result.legsByFill[f.key] || [];
      rows.push([toIso(f.day), fmtTimeLong(f.sec), f.account, f.symbol, f.side === 'B' ? 'Buy' : 'Sell', fmtQty(f.q).replace(/,/g, ''), fmtPrice(f.price), plainMoney(result.feeOf[f.key]), f.currency, f.orderId,
        legs.map(function (l) { return l.trade; }).join('; '), legs.length ? legs.map(function (l) { return l.role; }).join('; ') : 'unmatched', f.file, f.line]);
    });
    return csvLines(rows);
  }
  M.fillsCsv = fillsCsv;

  function templateCsv() {
    return csvLines([
      ['Date', 'Time', 'Account', 'Symbol', 'Side', 'Quantity', 'Price', 'Commission', 'Currency', 'Order ID'],
      ['2026-11-23', '09:41:05', 'Challenge', 'HGRB', 'Buy', '300', '41.27', '1.50', 'USD', 'A-1001'],
      ['2026-11-23', '09:41:06', 'Challenge', 'HGRB', 'Buy', '200', '41.28', '1.00', 'USD', 'A-1001'],
      ['2026-11-23', '10:12:44', 'Challenge', 'HGRB', 'Sell', '500', '41.90', '2.50', 'USD', 'A-1002'],
      ['2026-11-23', '11:02:10', 'Challenge', 'PLMB', 'Sell Short', '400', '18.62', '2.00', 'USD', 'A-1003'],
      ['2026-11-23', '11:40:31', 'Challenge', 'PLMB', 'Buy to Cover', '400', '18.31', '2.00', 'USD', 'A-1004'],
      ['2026-11-24', '14:30:00', 'Futures', 'LKFZ6', 'Buy', '2', '5112.25', '4.10', 'USD', 'F-2001'],
      ['2026-11-24', '14:55:12', 'Futures', 'LKFZ6', 'Sell', '2', '5120.50', '4.10', 'USD', 'F-2002']
    ]);
  }
  M.templateCsv = templateCsv;

  /* ---------- the journal file ---------- */

  var FILL_FIELDS = ['key', 'account', 'symbol', 'day', 'sec', 'side', 'intent', 'q', 'price', 'fee', 'currency', 'mult', 'orderId', 'execId', 'asset', 'file', 'line', 'src', 'seq'];
  var FEE_FIELDS = ['key', 'account', 'symbol', 'day', 'sec', 'amount', 'orderId', 'label', 'file', 'line', 'src', 'seq'];
  var SOURCE_FIELDS = ['id', 'name', 'account', 'first', 'last', 'added', 'duplicates', 'feesAdded'];
  var CARRY_FIELDS = ['account', 'symbol', 'side', 'q', 'price', 'day', 'fee', 'currency'];

  function pick(o, fields) { var out = {}; fields.forEach(function (f) { out[f] = o[f] === undefined ? null : o[f]; }); return out; }

  function projectFile(state, savedOn) {
    var s = state.settings;
    var out = {
      app: 'round-trips', version: M.VERSION, saved: savedOn || '',
      settings: {
        base: s.base, dateOrder: s.dateOrder,
        fx: (s.fx || []).map(function (e) { return { currency: e.currency, rate: str(e.rate) }; }),
        multipliers: (s.multipliers || []).map(function (e) { return { symbol: e.symbol, value: str(e.value) }; }),
        accounts: (s.accounts || []).map(function (a) { return { name: a.name, start: str(a.start), currency: str(a.currency), longOnly: !!a.longOnly }; }),
        rules: (function () { var r = {}; RULES.forEach(function (x) { var v = (s.rules || {})[x.id] || {}; r[x.id] = { on: !!v.on, value: str(v.value), unit: str(v.unit) }; }); return r; })(),
        setups: (s.setups || []).slice(), mistakes: (s.mistakes || []).slice()
      },
      sources: state.sources.filter(function (x) { return !x.error; }).map(function (x) { return pick(x, SOURCE_FIELDS); }),
      journal: (state.journal || []).map(function (e) { return { id: e.id, setup: e.setup, stop: e.stop, risk: e.risk, target: e.target || '', mistakes: e.mistakes.slice(), notes: e.notes }; }),
      fills: state.fills.map(function (f) { return pick(f, FILL_FIELDS); }),
      feeRows: state.feeRows.map(function (e) { return pick(e, FEE_FIELDS); }),
      carry: (state.carry || []).map(function (c) { return pick(c, CARRY_FIELDS); }),
      seq: state.seq
    };
    return JSON.stringify(out, null, 1) + '\n';
  }
  M.projectFile = projectFile;

  // Read a saved journal file back. Returns {ok, error, state}.
  function readProject(text) {
    var data;
    try { data = JSON.parse(str(text).replace(/^\ufeff/, '')); } catch (e) { return { ok: false, error: 'This is not a journal file (it is not valid JSON).' }; }
    if (!data || data.app !== 'round-trips' || !Array.isArray(data.fills)) return { ok: false, error: 'This is not a Round trips journal file.' };
    if (data.version > M.VERSION) return { ok: false, error: 'This journal was saved by a newer version of Round trips.' };
    var st = emptyState();
    var s = data.settings || {};
    var d = st.settings;
    if (typeof s.base === 'string' && /^[A-Z]{3}$/.test(s.base)) d.base = s.base;
    if (s.dateOrder === 'DMY' || s.dateOrder === 'MDY' || s.dateOrder === 'auto') d.dateOrder = s.dateOrder;
    if (Array.isArray(s.fx)) d.fx = s.fx.filter(function (e) { return e && e.currency; }).map(function (e) { return { currency: str(e.currency), rate: str(e.rate) }; });
    if (Array.isArray(s.multipliers)) d.multipliers = s.multipliers.filter(function (e) { return e && e.symbol; }).map(function (e) { return { symbol: str(e.symbol), value: str(e.value) }; });
    if (Array.isArray(s.accounts)) d.accounts = s.accounts.filter(function (e) { return e && e.name; }).map(function (e) { return { name: str(e.name), start: str(e.start), currency: str(e.currency), longOnly: !!e.longOnly }; });
    if (s.rules) RULES.forEach(function (x) { var v = s.rules[x.id]; if (v) d.rules[x.id] = { on: !!v.on, value: str(v.value), unit: str(v.unit) }; });
    RULES.forEach(function (x) { var v = d.rules[x.id]; if (!v.value) delete v.value; if (!v.unit) delete v.unit; });
    if (Array.isArray(s.setups)) d.setups = s.setups.map(str);
    if (Array.isArray(s.mistakes)) d.mistakes = s.mistakes.map(str);
    st.sources = (data.sources || []).map(function (x) { var o = pick(x, SOURCE_FIELDS); o.ok = true; o.error = ''; o.columns = {}; o.notes = []; o.skipped = []; o.counts = null; o.dateNote = ''; o.saved = true; return o; });
    var bad = 0;
    st.fills = data.fills.filter(function (f) {
      var ok = f && typeof f.key === 'string' && typeof f.day === 'number' && (f.side === 'B' || f.side === 'S') && typeof f.q === 'number' && f.q > 0 && typeof f.price === 'number';
      if (!ok) bad++;
      return ok;
    }).map(function (f) { var g = pick(f, FILL_FIELDS); if (g.fee === null) g.fee = 0; if (g.intent === null) g.intent = ''; ['orderId', 'execId', 'asset', 'file', 'currency'].forEach(function (k) { if (g[k] === null) g[k] = ''; }); return g; });
    st.feeRows = (data.feeRows || []).filter(function (e) { return e && typeof e.key === 'string' && typeof e.amount === 'number'; }).map(function (e) { var g = pick(e, FEE_FIELDS); ['orderId', 'label', 'file', 'symbol'].forEach(function (k) { if (g[k] === null) g[k] = ''; }); return g; });
    st.carry = (data.carry || []).filter(function (c) {
      return c && typeof c.account === 'string' && typeof c.symbol === 'string' && (c.side === 'B' || c.side === 'S') && typeof c.q === 'number' && c.q > 0 && typeof c.price === 'number' && typeof c.day === 'number';
    }).map(function (c) { var g = pick(c, CARRY_FIELDS); if (g.fee === null) g.fee = 0; if (g.currency === null) g.currency = ''; return g; });
    st.journal = (data.journal || []).filter(function (e) { return e && typeof e.id === 'string'; }).map(function (e) { return cleanEntry(e.id, e); }).sort(function (a, b) { return cmp(a.id, b.id); });
    var maxSeq = 0;
    st.fills.forEach(function (f) { if (f.seq > maxSeq) maxSeq = f.seq; });
    st.feeRows.forEach(function (f) { if (f.seq > maxSeq) maxSeq = f.seq; });
    st.seq = typeof data.seq === 'number' && data.seq >= maxSeq ? data.seq : maxSeq;
    return { ok: true, error: bad ? bad + ' damaged fills in the file were skipped.' : '', state: st, saved: str(data.saved) };
  }
  M.readProject = readProject;

  if (typeof module !== 'undefined' && module.exports) module.exports = M;
  else root.RoundTrips = M;
})(this);
/* MODEL END */
