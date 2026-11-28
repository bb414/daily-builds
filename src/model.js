/* MODEL START */
/*
 * Exam season: the planning model.
 *
 * Reads exam timetables (CSV, pasted tables, loose lines, .ics), topic lists
 * and calendars of busy times; builds a deterministic day-by-day revision
 * plan; tracks what has been done; and writes CSV, .ics, text and project
 * files. It runs in the browser and in Node.js (module.exports), and it is
 * mirrored function by function in companion/examseason/ so the tests can
 * prove both give identical plans.
 *
 * Conventions that keep the two versions in step: dates are whole day
 * numbers (days since 1 January 1970), times are whole minutes after
 * midnight, every sum is an integer, ratios are compared by
 * cross-multiplying, and every sort has an explicit tie-break.
 */
var ExamSeason = (function () {
  'use strict';

  var M = {};
  M.VERSION = 1;

  // ------------------------------------------------------------------
  // Small helpers
  // ------------------------------------------------------------------

  var SPACE_CHARS = ' \t\r\n\f\v\u00a0\ufeff';

  function trim(s) {
    s = s === null || s === undefined ? '' : String(s);
    var a = 0, b = s.length;
    while (a < b && SPACE_CHARS.indexOf(s.charAt(a)) >= 0) a++;
    while (b > a && SPACE_CHARS.indexOf(s.charAt(b - 1)) >= 0) b--;
    return s.slice(a, b);
  }

  function squash(s) {
    return trim(String(s).replace(/\u00a0/g, ' ').replace(/[ \t]+/g, ' '));
  }

  function lower(s) { return String(s).toLowerCase(); }

  function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0; }

  function floorDiv(a, b) { return Math.floor(a / b); }

  function ceilDiv(a, b) { return Math.floor((a + b - 1) / b); }

  function clamp(x, lo, hi) { return x < lo ? lo : x > hi ? hi : x; }

  // Parse a plain decimal such as "2.5" and multiply it by an integer factor,
  // rounding half up, using integers only (so both versions agree exactly).
  function scaleDecimal(text, factor) {
    var m = /^([0-9]+)(?:\.([0-9]{1,4}))?$/.exec(text);
    if (!m) return null;
    var frac = m[2] || '';
    var den = Math.pow(10, frac.length);
    var num = parseInt(m[1], 10) * den + (frac ? parseInt(frac, 10) : 0);
    return floorDiv(num * factor * 2 + den, 2 * den);
  }

  function slugify(s) {
    var out = lower(s).replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    out = out.slice(0, 48).replace(/-+$/g, '');
    return out || 'item';
  }

  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }

  M.trim = trim;
  M.slugify = slugify;
  M.scaleDecimal = scaleDecimal;

  // ------------------------------------------------------------------
  // Dates and times
  // ------------------------------------------------------------------

  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  var MON3 = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
  var WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  var WD3 = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  function dayFromYmd(y, m, d) {
    y -= m <= 2 ? 1 : 0;
    var era = floorDiv(y, 400);
    var yoe = y - era * 400;
    var mp = (m + 9) % 12;
    var doy = floorDiv(153 * mp + 2, 5) + d - 1;
    var doe = yoe * 365 + floorDiv(yoe, 4) - floorDiv(yoe, 100) + doy;
    return era * 146097 + doe - 719468;
  }

  function ymdFromDay(z) {
    z += 719468;
    var era = floorDiv(z, 146097);
    var doe = z - era * 146097;
    var yoe = floorDiv(doe - floorDiv(doe, 1460) + floorDiv(doe, 36524) - floorDiv(doe, 146096), 365);
    var y = yoe + era * 400;
    var doy = doe - (365 * yoe + floorDiv(yoe, 4) - floorDiv(yoe, 100));
    var mp = floorDiv(5 * doy + 2, 153);
    var d = doy - floorDiv(153 * mp + 2, 5) + 1;
    var m = mp < 10 ? mp + 3 : mp - 9;
    return [m <= 2 ? y + 1 : y, m, d];
  }

  function daysInMonth(y, m) {
    return dayFromYmd(m === 12 ? y + 1 : y, m === 12 ? 1 : m + 1, 1) - dayFromYmd(y, m, 1);
  }

  // 0 = Monday ... 6 = Sunday (1 January 1970 was a Thursday).
  function weekday(day) { return ((day % 7) + 7 + 3) % 7; }

  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  function isoDay(day) {
    var t = ymdFromDay(day);
    return t[0] + '-' + pad2(t[1]) + '-' + pad2(t[2]);
  }

  function fromIso(s) {
    var m = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/.exec(trim(s));
    if (!m) return null;
    return makeDay(parseInt(m[1], 10), parseInt(m[2], 10), parseInt(m[3], 10));
  }

  function makeDay(y, m, d) {
    if (m < 1 || m > 12 || d < 1 || y < 1900 || y > 2200) return null;
    if (d > daysInMonth(y, m)) return null;
    return dayFromYmd(y, m, d);
  }

  function fmtDay(day) {
    var t = ymdFromDay(day);
    return WD3[weekday(day)] + ' ' + t[2] + ' ' + MONTHS[t[1] - 1].slice(0, 3) + ' ' + t[0];
  }

  function fmtShort(day) {
    var t = ymdFromDay(day);
    return WD3[weekday(day)] + ' ' + t[2] + ' ' + MONTHS[t[1] - 1].slice(0, 3);
  }

  function fmtLong(day) {
    var t = ymdFromDay(day);
    return WEEKDAYS[weekday(day)] + ' ' + t[2] + ' ' + MONTHS[t[1] - 1] + ' ' + t[0];
  }

  function fmtTime(min) { return pad2(floorDiv(min, 60)) + ':' + pad2(min % 60); }

  function fmtDur(min) {
    if (min < 60) return min + ' min';
    var h = floorDiv(min, 60), r = min % 60;
    return h + ' h' + (r ? ' ' + r + ' min' : '');
  }

  // Minutes as hours to one decimal place, rounded half up ("12.5 h").
  function fmtHours(min) {
    var neg = min < 0;
    var tenths = floorDiv(Math.abs(min) * 10 + 30, 60);
    var txt = floorDiv(tenths, 10) + (tenths % 10 ? '.' + (tenths % 10) : '');
    return (neg ? '-' : '') + txt + ' h';
  }

  M.dayFromYmd = dayFromYmd;
  M.ymdFromDay = ymdFromDay;
  M.daysInMonth = daysInMonth;
  M.weekday = weekday;
  M.isoDay = isoDay;
  M.fromIso = fromIso;
  M.fmtDay = fmtDay;
  M.fmtShort = fmtShort;
  M.fmtLong = fmtLong;
  M.fmtTime = fmtTime;
  M.fmtDur = fmtDur;
  M.fmtHours = fmtHours;
  M.MONTHS = MONTHS;
  M.WEEKDAYS = WEEKDAYS;
  M.WD3 = WD3;

  var MONTH_RE = '(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\\.?';
  var WEEKDAY_RE = /^(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?[ ]+/;

  function fullYear(text) {
    var y = parseInt(text, 10);
    return text.length <= 2 ? 2000 + y : y;
  }

  // The year that puts day/month nearest after (ref - 60 days).
  function guessYear(m, d, ref) {
    var y0 = ymdFromDay(ref)[0];
    for (var y = y0 - 1; y <= y0 + 1; y++) {
      var day = makeDay(y, m, d);
      if (day !== null && day >= ref - 60) return day;
    }
    return makeDay(y0 + 1, m, d);
  }

  // Read a date written in any of the usual ways. Numeric dates are read
  // day first (UK order) unless order is 'MDY'. ref is the day used to
  // guess a missing year.
  function parseDate(text, order, ref) {
    var s = lower(squash(text)).replace(/,/g, ' ').replace(/[ ]+/g, ' ');
    s = trim(s);
    if (!s) return null;
    s = s.replace(WEEKDAY_RE, '');
    s = s.replace(/([0-9])(st|nd|rd|th)(?![a-z])/g, '$1');
    var m = /^([0-9]{4})[\-\/.]([0-9]{1,2})[\-\/.]([0-9]{1,2})(?:[t ].*)?$/.exec(s);
    if (m) return makeDay(parseInt(m[1], 10), parseInt(m[2], 10), parseInt(m[3], 10));
    m = /^([0-9]{4})([0-9]{2})([0-9]{2})(?:t[0-9]{4,6}z?)?$/.exec(s);
    if (m) return makeDay(parseInt(m[1], 10), parseInt(m[2], 10), parseInt(m[3], 10));
    m = /^([0-9]{1,2})[\/.\-]([0-9]{1,2})[\/.\-]([0-9]{4}|[0-9]{2})(?: .*)?$/.exec(s);
    if (m) {
      var a = parseInt(m[1], 10), b = parseInt(m[2], 10), y = fullYear(m[3]);
      return order === 'MDY' ? makeDay(y, a, b) : makeDay(y, b, a);
    }
    m = new RegExp('^([0-9]{1,2})[ \\-./]?' + MONTH_RE + '(?:[ \\-./]?([0-9]{4}|[0-9]{2}))?(?: .*)?$').exec(s);
    if (m) {
      var mon = MON3.indexOf(m[2]) + 1, dd = parseInt(m[1], 10);
      if (m[3] !== undefined && m[3] !== '') return makeDay(fullYear(m[3]), mon, dd);
      if (dd < 1 || dd > 31) return null;
      return guessYear(mon, dd, ref === undefined || ref === null ? dayFromYmd(2026, 9, 1) : ref);
    }
    m = new RegExp('^' + MONTH_RE + ' ([0-9]{1,2})(?: ([0-9]{4}))?(?: .*)?$').exec(s);
    if (m) {
      var mon2 = MON3.indexOf(m[1]) + 1, d2 = parseInt(m[2], 10);
      if (m[3] !== undefined && m[3] !== '') return makeDay(parseInt(m[3], 10), mon2, d2);
      if (d2 < 1 || d2 > 31) return null;
      return guessYear(mon2, d2, ref === undefined || ref === null ? dayFromYmd(2026, 9, 1) : ref);
    }
    return null;
  }

  // Find the first date inside a longer piece of text. Returns
  // {day, index, length} or null.
  var DATE_FINDERS = [
    /(^|[^0-9])([0-9]{4}-[0-9]{1,2}-[0-9]{1,2})(?![0-9])/,
    /(^|[^0-9])([0-9]{1,2}[\/.\-][0-9]{1,2}[\/.\-](?:[0-9]{4}|[0-9]{2}))(?![0-9])/,
    new RegExp('(^|[^a-z0-9])((?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\\.?,? )?[0-9]{1,2}(?:st|nd|rd|th)?[ \\-]' + MONTH_RE + '(?:,?[ \\-](?:[0-9]{4}|[0-9]{2}))?)(?![0-9a-z])'),
    new RegExp('(^|[^a-z0-9])((?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\\.?,? )?' + MONTH_RE + ' [0-9]{1,2}(?:st|nd|rd|th)?(?:,? [0-9]{4})?)(?![0-9a-z])')
  ];

  function findDate(text, order, ref) {
    var s = lower(text);
    var best = null;
    for (var i = 0; i < DATE_FINDERS.length; i++) {
      var m = DATE_FINDERS[i].exec(s);
      if (!m) continue;
      var day = parseDate(m[2], order, ref);
      if (day === null) continue;
      var idx = m.index + m[1].length;
      if (best === null || idx < best.index) best = { day: day, index: idx, length: m[2].length };
    }
    return best;
  }

  // Read a clock time: "09:30", "9.30", "9:30am", "2pm", "1400", "noon".
  // Hours from 1 to 7 without am or pm are taken as afternoon (nobody sits
  // an exam at 2 in the morning).
  function parseTime(text) {
    var s = lower(trim(text)).replace(/[ \t]+/g, '').replace(/\./g, function (c, i, all) {
      return i > 0 && /[0-9]/.test(all.charAt(i - 1)) && /[0-9]/.test(all.charAt(i + 1)) ? ':' : '';
    });
    if (!s) return null;
    if (s === 'noon' || s === 'midday' || s === '12noon') return 720;
    var m = /^([0-9]{1,2})(?:[:h]([0-9]{2}))?(?::00)?(am|pm)?$/.exec(s);
    var h, mi;
    if (m) {
      h = parseInt(m[1], 10);
      mi = m[2] ? parseInt(m[2], 10) : 0;
      if (!m[2] && !m[3]) return null;
      if (m[3]) {
        if (h < 1 || h > 12) return null;
        if (m[3] === 'pm' && h < 12) h += 12;
        if (m[3] === 'am' && h === 12) h = 0;
      } else if (h >= 1 && h <= 7) {
        h += 12;
      }
    } else {
      m = /^([0-9]{2})([0-9]{2})$/.exec(s);
      if (!m) return null;
      h = parseInt(m[1], 10);
      mi = parseInt(m[2], 10);
    }
    if (h > 23 || mi > 59) return null;
    return h * 60 + mi;
  }

  var TIME_FINDER = /(^|[^0-9:.])([0-9]{1,2}(?:[:.][0-9]{2})(?: ?[ap]\.?m\.?)?|[0-9]{1,2} ?[ap]\.?m\.?)(?![0-9a-z])/g;

  // All clock times inside a piece of text, in order: [{min, index, length}].
  function findTimes(text) {
    var s = lower(text), out = [], m;
    TIME_FINDER.lastIndex = 0;
    while ((m = TIME_FINDER.exec(s)) !== null) {
      var t = parseTime(m[2].replace(/\./g, function (c, i, all) {
        return /[0-9]/.test(all.charAt(i - 1)) && /[0-9]/.test(all.charAt(i + 1)) ? ':' : '';
      }));
      if (t !== null) out.push({ min: t, index: m.index + m[1].length, length: m[2].length });
    }
    return out;
  }

  // Read a length of time as minutes: "2 hours", "2h", "120", "1h 30m",
  // "1:30", "90 mins", "2.5 hrs". A bare number is hours when it is 12 or
  // less (unless the column says minutes), otherwise minutes.
  function parseDuration(text, unit) {
    var s = lower(trim(text)).replace(/^\(|\)$/g, '');
    s = trim(s);
    if (!s) return null;
    var m = /^([0-9]{1,2}):([0-9]{2})(?::00)?$/.exec(s);
    if (m) return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
    m = /^([0-9]+(?:\.[0-9]+)?) ?(?:h|hr|hrs|hour|hours)\.?(?:,? ?(?:and )?([0-9]+) ?(?:m|min|mins|minute|minutes)?\.?)?$/.exec(s);
    if (m) return scaleDecimal(m[1], 60) + (m[2] ? parseInt(m[2], 10) : 0);
    m = /^([0-9]+) ?(?:m|min|mins|minute|minutes)\.?$/.exec(s);
    if (m) return parseInt(m[1], 10);
    m = /^([0-9]+(?:\.[0-9]+)?)$/.exec(s);
    if (m) {
      if (unit === 'min') return scaleDecimal(m[1], 1);
      if (unit === 'hour') return scaleDecimal(m[1], 60);
      var asMin = scaleDecimal(m[1], 1);
      return asMin <= 12 ? scaleDecimal(m[1], 60) : asMin;
    }
    return null;
  }

  M.parseDate = parseDate;
  M.findDate = findDate;
  M.parseTime = parseTime;
  M.findTimes = findTimes;
  M.parseDuration = parseDuration;

  // UK clock changes: British Summer Time runs from 01:00 UTC on the last
  // Sunday of March to 01:00 UTC on the last Sunday of October.
  function lastSunday(y, m) {
    var last = dayFromYmd(y, m, daysInMonth(y, m));
    return last - ((weekday(last) + 1) % 7);
  }

  function utcToLondon(day, min) {
    var y = ymdFromDay(day)[0];
    var t = day * 1440 + min;
    var start = lastSunday(y, 3) * 1440 + 60, end = lastSunday(y, 10) * 1440 + 60;
    if (t >= start && t < end) t += 60;
    return [floorDiv(t, 1440), t - floorDiv(t, 1440) * 1440];
  }

  function londonToUtc(day, min) {
    var y = ymdFromDay(day)[0];
    var t = day * 1440 + min;
    var start = lastSunday(y, 3) * 1440 + 60, end = lastSunday(y, 10) * 1440 + 120;
    if (t >= start + 60 && t < end) t -= 60;
    return [floorDiv(t, 1440), t - floorDiv(t, 1440) * 1440];
  }

  M.utcToLondon = utcToLondon;
  M.londonToUtc = londonToUtc;

  // ------------------------------------------------------------------
  // Delimited text
  // ------------------------------------------------------------------

  function stripBom(text) {
    text = String(text);
    return text.charAt(0) === '\ufeff' ? text.slice(1) : text;
  }

  function splitLines(text) { return stripBom(text).split(/\r\n|\n|\r/); }

  function countOutsideQuotes(line, ch) {
    var n = 0, q = false;
    for (var i = 0; i < line.length; i++) {
      var c = line.charAt(i);
      if (c === '"') q = !q;
      else if (c === ch && !q) n++;
    }
    return n;
  }

  // Pick the delimiter used by most lines: tab, comma, semicolon or pipe.
  // Returns '' when no line has any of them.
  function sniffDelimiter(text) {
    var lines = splitLines(text).filter(function (l) { return trim(l) !== ''; }).slice(0, 40);
    var cands = ['\t', ',', ';', '|'];
    var best = '', bestScore = 0;
    for (var i = 0; i < cands.length; i++) {
      var score = 0;
      for (var j = 0; j < lines.length; j++) if (countOutsideQuotes(lines[j], cands[i]) > 0) score++;
      if (score > bestScore) { best = cands[i]; bestScore = score; }
    }
    return best;
  }

  // Split delimited text into rows of cells, honouring quotes (with doubled
  // quotes and line breaks inside them). Each row keeps its first line number.
  function parseDelimited(text, delim) {
    text = stripBom(text);
    var rows = [], cells = [], cell = '', q = false, line = 1, rowLine = 1;
    var i = 0, n = text.length;
    function endRow() {
      cells.push(cell);
      rows.push({ cells: cells, line: rowLine });
      cells = [];
      cell = '';
    }
    while (i < n) {
      var c = text.charAt(i);
      if (q) {
        if (c === '"') {
          if (text.charAt(i + 1) === '"') { cell += '"'; i += 2; continue; }
          q = false; i++; continue;
        }
        if (c === '\n') line++;
        cell += c; i++; continue;
      }
      if (c === '"' && trim(cell) === '') { cell = ''; q = true; i++; continue; }
      if (delim && c === delim) { cells.push(cell); cell = ''; i++; continue; }
      if (c === '\r' || c === '\n') {
        endRow();
        if (c === '\r' && text.charAt(i + 1) === '\n') i++;
        i++; line++; rowLine = line;
        continue;
      }
      cell += c; i++;
    }
    if (cell !== '' || cells.length) endRow();
    return rows;
  }

  // Rows for any pasted table: a sniffed delimiter, or runs of two or more
  // spaces (text copied out of a PDF or a web page), or one cell per line.
  function readTable(text) {
    var delim = sniffDelimiter(text);
    if (delim) return { delim: delim, rows: parseDelimited(text, delim) };
    var lines = splitLines(text), rows = [], spaced = 0, nonblank = 0;
    for (var i = 0; i < lines.length; i++) {
      if (trim(lines[i]) === '') continue;
      nonblank++;
      if (/[^ \t] {2,}[^ \t]/.test(trim(lines[i]))) spaced++;
    }
    var useSpaces = nonblank > 0 && spaced * 2 >= nonblank;
    for (var k = 0; k < lines.length; k++) {
      var l = lines[k];
      rows.push({ cells: useSpaces ? trim(l).split(/ {2,}/) : [l], line: k + 1 });
    }
    return { delim: useSpaces ? '  ' : '', rows: rows };
  }

  // Tables saved from a web page ("Save page as") or copied as HTML: each
  // <tr> becomes a row and each <td> or <th> a cell, tags removed.
  var ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', ndash: '-', mdash: '-', hellip: '...', rsquo: "'", lsquo: "'", ldquo: '"', rdquo: '"', pound: '£' };

  function decodeEntities(s) {
    return s.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|[a-zA-Z]+);/g, function (m, e) {
      var k = e.toLowerCase();
      if (k.charAt(0) === '#') {
        var n = k.charAt(1) === 'x' ? parseInt(k.slice(2), 16) : parseInt(k.slice(1), 10);
        return n > 0 && n < 0x110000 && (n < 0xd800 || n > 0xdfff) ? String.fromCodePoint(n) : '';
      }
      return ENTITIES[k] !== undefined ? ENTITIES[k] : m;
    });
  }

  function htmlCellText(s) {
    s = s.replace(/<br\s*\/?>/gi, ' ').replace(/<[^>]*>/g, ' ');
    return squash(decodeEntities(s).replace(/[\t\r\n]+/g, ' '));
  }

  function isHtmlTable(text) { return /<tr[\s>]/i.test(text) && /<t[dh][\s>]/i.test(text); }

  function htmlRows(text) {
    var src = String(text).replace(/<!--[\s\S]*?-->/g, function (c) { return c.replace(/[^\n]/g, ' '); });
    var re = /<tr(?:\s[^>]*)?>/gi, m, starts = [];
    while ((m = re.exec(src)) !== null) starts.push([m.index, m.index + m[0].length]);
    var rows = [], pos = 0, line = 1;
    for (var i = 0; i < starts.length; i++) {
      for (; pos < starts[i][0]; pos++) if (src.charAt(pos) === '\n') line++;
      var endAt = i + 1 < starts.length ? starts[i + 1][0] : src.length;
      var chunk = src.slice(starts[i][1], endAt);
      var close = chunk.search(/<\/tr\s*>/i);
      if (close >= 0) chunk = chunk.slice(0, close);
      var cells = [], cre = /<t[dh](?:\s[^>]*)?>([\s\S]*?)(?:<\/t[dh]\s*>|(?=<t[dh][\s>])|$)/gi, cm;
      while ((cm = cre.exec(chunk)) !== null) cells.push(htmlCellText(cm[1]));
      rows.push({ cells: cells, line: line });
    }
    return rows;
  }
  M.htmlRows = htmlRows;

  // Which way round numeric dates are written in a column: a day over 12 in
  // the first place means day first, in the second place month first.
  function dateOrderOf(texts) {
    var dmy = 0, mdy = 0, either = 0;
    texts.forEach(function (s) {
      var m = /(^|[^0-9])([0-9]{1,2})[\/.\-]([0-9]{1,2})[\/.\-]([0-9]{4}|[0-9]{2})(?![0-9])/.exec(String(s));
      if (!m) return;
      var a = parseInt(m[2], 10), b = parseInt(m[3], 10);
      if (a > 12 && b <= 12) dmy++;
      else if (b > 12 && a <= 12) mdy++;
      else either++;
    });
    return { order: mdy > 0 && dmy === 0 ? 'MDY' : 'DMY', dmy: dmy, mdy: mdy, either: either };
  }
  M.dateOrderOf = dateOrderOf;

  function dateOrderMessages(info, out) {
    if (info.order === 'MDY') out.messages.push({ level: 'info', text: 'Dates such as 01/13 show this file puts the month first, so every date was read that way.' });
    else if (info.either > 0 && info.dmy === 0) out.messages.push({ level: 'info', text: 'Every date could be read either way round, so day first (UK order) was assumed. Check the dates below.' });
  }

  function csvCell(v) {
    var s = v === null || v === undefined ? '' : String(v);
    if (/[",\r\n]/.test(s) || /^[ ]|[ ]$/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
  }

  function csvText(rows) {
    return '\ufeff' + rows.map(function (r) { return r.map(csvCell).join(','); }).join('\r\n') + '\r\n';
  }

  M.sniffDelimiter = sniffDelimiter;
  M.parseDelimited = parseDelimited;
  M.readTable = readTable;
  M.csvText = csvText;

  function normHeader(s) {
    return trim(lower(String(s)).replace(/[^a-z0-9]+/g, ' '));
  }

  function isBlankRow(cells) {
    for (var i = 0; i < cells.length; i++) if (trim(cells[i]) !== '') return false;
    return true;
  }

  // Map header cells to roles using exact names first, then key words.
  function mapColumns(cells, synonyms, keywords) {
    var map = {}, used = {};
    var roles = Object.keys(synonyms);
    for (var i = 0; i < cells.length; i++) {
      var h = normHeader(cells[i]);
      if (!h) continue;
      for (var r = 0; r < roles.length; r++) {
        if (map[roles[r]] === undefined && synonyms[roles[r]].indexOf(h) >= 0) { map[roles[r]] = i; used[i] = true; break; }
      }
    }
    for (var j = 0; j < cells.length; j++) {
      if (used[j]) continue;
      var h2 = ' ' + normHeader(cells[j]) + ' ';
      if (h2 === '  ') continue;
      for (var k = 0; k < keywords.length; k++) {
        var role = keywords[k][0];
        if (map[role] !== undefined) continue;
        if (h2.indexOf(' ' + keywords[k][1] + ' ') >= 0) { map[role] = j; used[j] = true; break; }
      }
    }
    return map;
  }

  function cell(cells, idx) { return idx === undefined || idx >= cells.length ? '' : trim(cells[idx]); }

  // ------------------------------------------------------------------
  // Module codes
  // ------------------------------------------------------------------

  var CODE_RE = /(^|[^A-Za-z0-9])([A-Z]{2,5})[ \-]?([0-9]{3,5}[A-Z]?)(?=[^A-Za-z0-9]|$)/;

  // The first module code in a piece of text: {code, index, length} or null.
  function findCode(text) {
    var m = CODE_RE.exec(String(text));
    if (!m) return null;
    return { code: m[2] + m[3], index: m.index + m[1].length, length: m[0].length - m[1].length };
  }

  function normCode(text) {
    var f = findCode(String(text).toUpperCase());
    if (f) return f.code;
    return String(text).toUpperCase().replace(/[^A-Z0-9]+/g, '');
  }

  // Remove a module code (and the separator after it) from a title.
  function stripCode(name, code) {
    var f = findCode(name);
    if (!f || f.code !== code) return squash(name);
    var out = name.slice(0, f.index) + ' ' + name.slice(f.index + f.length);
    return trim(squash(out).replace(/^[\-:,|.\u2013 ]+|[\-:,|\u2013 ]+$/g, ''));
  }

  M.findCode = findCode;
  M.normCode = normCode;

  // ------------------------------------------------------------------
  // Exam timetables
  // ------------------------------------------------------------------

  var EXAM_SYNONYMS = {
    code: ['module code', 'module', 'course code', 'unit code', 'code', 'paper code', 'subject code', 'module id', 'exam code', 'component code', 'assessment code', 'module ref', 'module no'],
    name: ['module title', 'module name', 'title', 'course title', 'course name', 'course', 'unit title', 'unit name', 'unit', 'paper', 'paper title', 'exam title', 'subject', 'module description', 'assessment title', 'examination', 'exam', 'exam name'],
    date: ['date', 'exam date', 'day date', 'date of exam', 'examination date', 'day', 'exam day', 'date and time', 'date time', 'start date', 'when'],
    start: ['start', 'start time', 'time', 'begins', 'from', 'exam start', 'starts', 'start at'],
    end: ['end', 'end time', 'finish', 'finish time', 'to', 'until', 'ends', 'exam end'],
    duration: ['duration', 'length', 'duration mins', 'duration minutes', 'duration hrs', 'duration hours', 'exam duration', 'mins', 'minutes', 'hours', 'hrs', 'length mins', 'length hours'],
    room: ['venue', 'room', 'location', 'building', 'hall', 'exam venue', 'exam room', 'place', 'centre', 'campus'],
    seat: ['seat', 'seat no', 'seat number', 'desk', 'desk number', 'desk no'],
    type: ['type', 'assessment type', 'exam type', 'component', 'sitting', 'attempt', 'kind', 'format', 'mode', 'assessment', 'period'],
    notes: ['notes', 'note', 'comments', 'comment', 'information', 'info', 'details', 'additional information', 'remarks']
  };

  var EXAM_KEYWORDS = [
    ['code', 'code'], ['name', 'title'], ['name', 'name'], ['date', 'date'], ['start', 'start'],
    ['end', 'finish'], ['end', 'end'], ['duration', 'duration'], ['duration', 'length'],
    ['room', 'venue'], ['room', 'room'], ['room', 'location'], ['seat', 'seat'], ['type', 'type'], ['notes', 'notes']
  ];

  var TBC_RE = /^(tbc|tba|tbd|tbc\.|to be (confirmed|arranged|announced|decided|scheduled)|not yet (scheduled|published|known|confirmed|timetabled)|pending|unscheduled|awaiting confirmation|date tbc|n\/a|na|\?+|-+)$/;

  function examHeaderScore(map) {
    var hasWho = map.code !== undefined || map.name !== undefined;
    var hasWhen = map.date !== undefined;
    if (!hasWho || !hasWhen) return 0;
    return Object.keys(map).length;
  }

  function durationUnit(header) {
    var h = ' ' + normHeader(header) + ' ';
    if (/ (min|mins|minutes) /.test(h)) return 'min';
    if (/ (hr|hrs|hour|hours) /.test(h)) return 'hour';
    return '';
  }

  function isExamHeaderRow(cells) {
    var map = mapColumns(cells, EXAM_SYNONYMS, []);
    return Object.keys(map).length >= 3;
  }

  // Read an exam timetable from text: a portal CSV or TSV export, a table
  // pasted from a web page, loose lines, or an .ics calendar.
  // Returns {exams, messages, format, rows}.
  function readExams(text, opts) {
    opts = opts || {};
    var ref = opts.ref === undefined || opts.ref === null ? dayFromYmd(2026, 9, 1) : opts.ref;
    text = String(text === null || text === undefined ? '' : text);
    var out = { exams: [], messages: [], format: '', rows: 0, skipped: 0 };
    if (/^\s*%PDF/.test(text)) {
      out.format = 'pdf';
      out.messages.push({ level: 'error', text: 'This is a PDF file. Open it, select the timetable table, copy it and paste it here, or download the CSV or calendar (.ics) version from your student portal.' });
      return out;
    }
    if (/^\s*PK/.test(text) && text.indexOf('[Content_Types]') >= 0) {
      out.format = 'xlsx';
      out.messages.push({ level: 'error', text: 'This looks like an Excel workbook. Save it as CSV (File, Save as, CSV) and load that, or copy the rows and paste them here.' });
      return out;
    }
    if (/BEGIN:VCALENDAR/i.test(text)) return readExamsIcs(text, out, opts);
    if (trim(text) === '') {
      out.messages.push({ level: 'error', text: 'There was nothing to read.' });
      return out;
    }
    var table = isHtmlTable(text) ? { delim: 'html', rows: htmlRows(text) } : readTable(text);
    var rows = table.rows;
    var headerAt = -1, map = null;
    for (var i = 0; i < rows.length && i < 30; i++) {
      var mp = mapColumns(rows[i].cells, EXAM_SYNONYMS, EXAM_KEYWORDS);
      if (examHeaderScore(mp) >= 2) { headerAt = i; map = mp; break; }
    }
    if (headerAt < 0) {
      if (table.delim === 'html') {
        out.format = 'html';
        out.messages.push({ level: 'error', text: 'This web page has a table, but no header row with a module and a date was found in it.' });
        return out;
      }
      return readExamLines(text, out, ref);
    }
    out.format = table.delim === 'html' ? 'html' : table.delim === '\t' ? 'table' : table.delim === '  ' ? 'spaced' : 'csv';
    var header = rows[headerAt].cells;
    var unit = map.duration !== undefined ? durationUnit(header[map.duration]) : '';
    var orderInfo = dateOrderOf(rows.slice(headerAt + 1).map(function (r) { return cell(r.cells, map.date); }));
    var order = orderInfo.order;
    var seen = {}, blank = 0;
    for (var r = headerAt + 1; r < rows.length; r++) {
      var cells = rows[r].cells, line = rows[r].line;
      if (isBlankRow(cells)) { blank++; continue; }
      out.rows++;
      if (isExamHeaderRow(cells)) {
        out.skipped++;
        out.messages.push({ level: 'info', line: line, text: 'Line ' + line + ' repeats the header row, so it was skipped.' });
        continue;
      }
      var ex = examFromCells(cells, map, unit, ref, line, out.messages, order);
      if (!ex) { out.skipped++; continue; }
      var key = ex.code + '|' + (ex.day === null ? 'tbc' : ex.day) + '|' + ex.start;
      if (seen[key]) {
        out.skipped++;
        out.messages.push({ level: 'info', line: line, text: 'Line ' + line + ' repeats ' + ex.code + (ex.day === null ? '' : ' on ' + fmtShort(ex.day)) + ', so it was skipped.' });
        continue;
      }
      seen[key] = true;
      out.exams.push(ex);
    }
    // Trailing blank lines at the end of a file are not worth mentioning.
    var trailing = 0;
    for (var t = rows.length - 1; t > headerAt && isBlankRow(rows[t].cells); t--) trailing++;
    blank -= trailing;
    if (blank > 0) out.messages.push({ level: 'info', text: plural(blank, 'blank row') + ' skipped.' });
    if (headerAt > 0) out.messages.push({ level: 'info', text: 'The table starts at line ' + rows[headerAt].line + '; the ' + plural(headerAt, 'line') + ' above it were read as a title, not exams.' });
    dateOrderMessages(orderInfo, out);
    finishExams(out);
    return out;
  }

  function examFromCells(cells, map, unit, ref, line, messages, order) {
    var codeCell = cell(cells, map.code), nameCell = cell(cells, map.name);
    var code = '', name = '';
    if (codeCell) {
      var f = findCode(codeCell.toUpperCase());
      code = f ? f.code : codeCell.toUpperCase().replace(/[^A-Z0-9]+/g, '');
      if (f && !nameCell) name = stripCode(codeCell, f.code);
    }
    if (nameCell) {
      var f2 = findCode(nameCell);
      if (!code && f2) code = f2.code;
      name = code ? stripCode(nameCell, code) : squash(nameCell);
    }
    if (!code && !name) {
      messages.push({ level: 'warn', line: line, text: 'Line ' + line + ' has no module code or title, so it was skipped.' });
      return null;
    }
    if (!code) code = slugify(name).toUpperCase().replace(/-/g, '').slice(0, 10);
    var dateCell = cell(cells, map.date);
    var day = null, tbc = false;
    var lowDate = lower(squash(dateCell));
    var startFromDate = null, endFromDate = null;
    if (dateCell === '' || TBC_RE.test(lowDate) || /\b(tbc|tba|tbd|to be confirmed)\b/.test(lowDate)) {
      tbc = true;
      messages.push({ level: 'warn', line: line, text: 'Line ' + line + ': ' + code + ' has no date yet (' + (dateCell || 'blank') + '). It is listed but not planned until you add a date.' });
    } else {
      day = parseDate(dateCell, order, ref);
      if (day === null) {
        var found = findDate(dateCell, order, ref);
        if (found) day = found.day;
      }
      if (day === null) {
        tbc = true;
        messages.push({ level: 'warn', line: line, text: 'Line ' + line + ': could not read the date "' + dateCell + '" for ' + code + '. It is listed without a date; type the date in to plan for it.' });
      } else {
        var tms = findTimes(dateCell.replace(/^[0-9]{4}-[0-9]{2}-[0-9]{2}t/i, ''));
        if (tms.length) startFromDate = tms[0].min;
        if (tms.length > 1) endFromDate = tms[1].min;
      }
    }
    var startCell = cell(cells, map.start), endCell = cell(cells, map.end);
    var start = null, end = null;
    if (startCell) {
      start = parseTime(startCell);
      if (start === null) {
        var ts = findTimes(startCell);
        if (ts.length) { start = ts[0].min; if (ts.length > 1 && !endCell) end = ts[1].min; }
      }
    }
    if (start === null) { start = startFromDate; if (end === null) end = endFromDate; }
    if (endCell) {
      end = parseTime(endCell);
      if (end === null) { var te = findTimes(endCell); if (te.length) end = te[0].min; }
    }
    var duration = null;
    var durCell = cell(cells, map.duration);
    if (durCell) {
      duration = parseDuration(durCell, unit);
      if (duration === null) messages.push({ level: 'info', line: line, text: 'Line ' + line + ': could not read the duration "' + durCell + '" for ' + code + '.' });
    }
    if (duration === null && start !== null && end !== null && end > start) duration = end - start;
    if (!tbc && start === null) {
      start = 570;
      messages.push({ level: 'info', line: line, text: 'Line ' + line + ': no start time for ' + code + ', so 09:30 is assumed.' });
    }
    if (start === null) start = 570;
    if (duration === null || duration <= 0) {
      duration = 120;
      if (!tbc) messages.push({ level: 'info', line: line, text: 'Line ' + line + ': no length given for ' + code + ', so 2 hours is assumed.' });
    }
    duration = clamp(duration, 15, 1440);
    var type = cell(cells, map.type), notes = cell(cells, map.notes);
    var resit = /\b(resit|re-sit|referral|reassessment|re-assessment|deferred|supplementary)\b/i.test(type + ' ' + notes + ' ' + nameCell);
    return {
      id: '', code: code, name: name || code, day: day, start: start, duration: duration,
      room: squash(cell(cells, map.room)), seat: squash(cell(cells, map.seat)), type: squash(type),
      resit: resit, tbc: tbc, note: squash(notes), line: line
    };
  }

  // Lines with no header row: look for a module code, a date and times.
  function readExamLines(text, out, ref) {
    out.format = 'lines';
    var lines = splitLines(text);
    var seen = {};
    for (var i = 0; i < lines.length; i++) {
      var raw = squash(lines[i]), line = i + 1;
      if (!raw) continue;
      var code = findCode(raw);
      var date = findDate(raw, 'DMY', ref);
      if (!code && !date) {
        if (out.exams.length === 0) continue;
        out.messages.push({ level: 'info', line: line, text: 'Line ' + line + ' was not read: no module code or date in "' + raw.slice(0, 60) + '".' });
        continue;
      }
      out.rows++;
      if (!code) {
        out.skipped++;
        out.messages.push({ level: 'warn', line: line, text: 'Line ' + line + ' has a date but no module code, so it was skipped.' });
        continue;
      }
      var rest = raw.slice(0, code.index) + ' ' + raw.slice(code.index + code.length);
      var tbc = false, day = null;
      if (date) {
        day = date.day;
        var di = rest.toLowerCase().indexOf(raw.toLowerCase().slice(date.index, date.index + date.length));
        if (di >= 0) rest = rest.slice(0, di) + ' ' + rest.slice(di + date.length);
      } else {
        tbc = true;
        out.messages.push({ level: 'warn', line: line, text: 'Line ' + line + ': ' + code.code + ' has no date yet. It is listed but not planned until you add a date.' });
      }
      var times = findTimes(rest);
      var start = times.length ? times[0].min : 570;
      var end = times.length > 1 ? times[1].min : null;
      for (var k = times.length - 1; k >= 0 && k >= times.length - 2; k--) {
        rest = rest.slice(0, times[k].index) + ' ' + rest.slice(times[k].index + times[k].length);
      }
      var duration = null;
      var dm = /(?:^|[^0-9a-z])(\(?[0-9]+(?:\.[0-9]+)? ?(?:h|hr|hrs|hours?)\.?(?: ?[0-9]+ ?(?:m|min|mins|minutes?))?\)?|\(?[0-9]+ ?(?:min|mins|minutes)\)?)(?![a-z])/i.exec(rest);
      if (dm) {
        duration = parseDuration(dm[1].replace(/[()]/g, ''), '');
        rest = rest.replace(dm[1], ' ');
      }
      if (duration === null && end !== null && end > start) duration = end - start;
      if (duration === null) duration = 120;
      var name = trim(squash(rest.replace(/\b(tbc|tba|to be confirmed)\b/ig, ' ').replace(/[\-\u2013|,;:]+( |$)/g, ' ').replace(/[()]/g, ' ')));
      var resit = /\b(resit|re-sit|referral|reassessment)\b/i.test(raw);
      var ex = { id: '', code: code.code, name: name || code.code, day: day, start: start, duration: clamp(duration, 15, 1440), room: '', seat: '', type: resit ? 'Resit' : '', resit: resit, tbc: tbc, note: '', line: line };
      var key = ex.code + '|' + (day === null ? 'tbc' : day) + '|' + start;
      if (seen[key]) { out.skipped++; continue; }
      seen[key] = true;
      out.exams.push(ex);
    }
    if (!out.exams.length) {
      out.messages.push({ level: 'error', text: 'No exams found. Paste the timetable with its header row (module, date, time), or use the template.' });
    } else {
      out.messages.push({ level: 'info', text: 'No header row was found, so each line was read by looking for a module code, a date and times.' });
    }
    finishExams(out);
    return out;
  }

  function readExamsIcs(text, out, opts) {
    out.format = 'ics';
    var cal = parseIcs(text);
    var evs = [];
    var examish = /\b(exam|examination|test|paper|assessment|quiz|viva|in-class|mcq)\b/i;
    var anyExam = cal.events.some(function (e) { return examish.test(e.summary + ' ' + e.description + ' ' + e.categories); });
    var dropped = 0;
    cal.events.forEach(function (e) {
      if (e.status === 'CANCELLED' || !e.start) return;
      if (anyExam && !examish.test(e.summary + ' ' + e.description + ' ' + e.categories)) { dropped++; return; }
      evs.push(e);
    });
    if (dropped) out.messages.push({ level: 'info', text: plural(dropped, 'event') + ' that did not mention an exam (lectures, seminars and so on) were left out. Load them under Your time instead.' });
    evs.forEach(function (e) {
      out.rows++;
      var f = findCode(e.summary) || findCode(e.description);
      var code = f ? f.code : slugify(e.summary).toUpperCase().replace(/-/g, '').slice(0, 10);
      var name = f && findCode(e.summary) ? stripCode(e.summary, code) : squash(e.summary);
      name = trim(name.replace(/\b(examination|exam)\b\s*$/i, '').replace(/[\-:\u2013 ]+$/, '')) || code;
      var dur = 120;
      if (e.end) dur = (e.end.day - e.start.day) * 1440 + e.end.min - e.start.min;
      else if (e.durationMin !== null) dur = e.durationMin;
      if (e.start.allDay) {
        out.messages.push({ level: 'info', text: code + ' on ' + fmtShort(e.start.day) + ' is an all-day entry, so 09:30 is assumed for the start.' });
      }
      var resit = /\b(resit|re-sit|referral|reassessment)\b/i.test(e.summary + ' ' + e.description);
      out.exams.push({
        id: '', code: code, name: name, day: e.start.day, start: e.start.allDay ? 570 : e.start.min,
        duration: clamp(e.start.allDay ? 120 : dur, 15, 1440), room: squash(e.location), seat: '', type: resit ? 'Resit' : '',
        resit: resit, tbc: false, note: '', line: e.line
      });
    });
    cal.messages.forEach(function (m) { out.messages.push(m); });
    if (!out.exams.length) out.messages.push({ level: 'error', text: 'The calendar had no events that could be read as exams.' });
    finishExams(out);
    return out;
  }

  function finishExams(out) {
    out.exams.sort(examOrder);
    assignExamIds(out.exams);
  }

  function examOrder(a, b) {
    var ad = a.day === null ? 1e9 : a.day, bd = b.day === null ? 1e9 : b.day;
    return cmp(ad, bd) || cmp(a.start, b.start) || cmp(a.code, b.code) || cmp(a.name, b.name);
  }

  function assignExamIds(exams) {
    var used = {};
    exams.forEach(function (e) {
      if (e.id && !used[e.id]) { used[e.id] = true; return; }
      var base = slugify(e.code), id = base, k = 2;
      while (used[id]) { id = base + '-' + k; k++; }
      used[id] = true;
      e.id = id;
    });
  }

  M.readExams = readExams;
  M.examOrder = examOrder;
  M.assignExamIds = assignExamIds;

  // ------------------------------------------------------------------
  // Topics
  // ------------------------------------------------------------------

  var SIZES = { xs: 60, s: 120, m: 180, l: 300, xl: 420 };
  var SIZE_WORDS = {
    xs: 'xs', 'x-small': 'xs', tiny: 'xs', s: 's', sm: 's', small: 's', short: 's', light: 's',
    m: 'm', med: 'm', medium: 'm', mid: 'm', average: 'm', normal: 'm',
    l: 'l', lg: 'l', large: 'l', big: 'l', long: 'l', heavy: 'l',
    xl: 'xl', 'x-large': 'xl', huge: 'xl', massive: 'xl', 'very large': 'xl'
  };
  var CONF_WORDS = {
    red: 1, 'very weak': 1, 'no idea': 1, 'not started': 1, weak: 2, shaky: 2, amber: 3, ok: 3, okay: 3, 'so-so': 3,
    fine: 3, good: 4, strong: 4, green: 5, 'very good': 5, 'very strong': 5, solid: 5, confident: 5
  };

  M.SIZES = SIZES;

  function sizeLabel(min) {
    var keys = ['xs', 's', 'm', 'l', 'xl'];
    for (var i = 0; i < keys.length; i++) if (SIZES[keys[i]] === min) return keys[i].toUpperCase();
    return fmtDur(min);
  }
  M.sizeLabel = sizeLabel;

  // A confidence token: 1 to 5, "2/5", "conf 2", stars, red/amber/green,
  // or a percentage. Returns 1..5 or null.
  function parseConfidence(text) {
    var s = lower(trim(text)).replace(/^(confidence|conf|rating|rag)[ :=]*/, '');
    s = trim(s);
    if (!s) return null;
    var m = /^([1-5])(?:\.0)?(?: ?\/ ?5| out of 5| of 5)?$/.exec(s);
    if (m) return parseInt(m[1], 10);
    if (/^[\u2605*]{1,5}[\u2606]*$/.test(s)) return s.replace(/\u2606/g, '').length;
    m = /^([0-9]{1,3}) ?%$/.exec(s);
    if (m) {
      var p = clamp(parseInt(m[1], 10), 0, 100);
      return p <= 20 ? 1 : p <= 40 ? 2 : p <= 60 ? 3 : p <= 80 ? 4 : 5;
    }
    if (CONF_WORDS[s] !== undefined) return CONF_WORDS[s];
    return null;
  }

  // A size token: S/M/L, small/medium/large, "3h", "90 min", or a bare
  // number of hours. Returns minutes of first learning or null.
  function parseSize(text, bareIsHours) {
    var s = lower(trim(text)).replace(/^(size|effort|workload|hours|time)[ :=]*/, '');
    s = trim(s);
    if (!s) return null;
    if (SIZE_WORDS[s] !== undefined) return SIZES[SIZE_WORDS[s]];
    var m = /^([0-9]+(?:\.[0-9]+)?) ?(?:h|hr|hrs|hour|hours)$/.exec(s);
    if (m) return clamp(scaleDecimal(m[1], 60), 15, 6000);
    m = /^([0-9]+) ?(?:m|min|mins|minutes)$/.exec(s);
    if (m) return clamp(parseInt(m[1], 10), 15, 6000);
    m = /^([0-9]+(?:\.[0-9]+)?)$/.exec(s);
    if (m && bareIsHours) return clamp(scaleDecimal(m[1], 60), 15, 6000);
    return null;
  }

  M.parseConfidence = parseConfidence;
  M.parseSize = parseSize;

  // Pull confidence and size off the end of a topic line, from brackets
  // "(2, L)" "[2/5] [3h]" or trailing separators "- conf 2 - large".
  // A trailing word with no bracket or separator before it only counts when
  // it cannot be part of a title: "3h", "90 min", "2/5", stars or "40%".
  var STRICT_ATTR = /^([0-9]+(?:\.[0-9]+)? ?(?:h|hr|hrs|hours|m|min|mins)|[1-5] ?\/ ?5|[\u2605*]{1,5}[\u2606]*|[0-9]{1,3}%)$/;

  function splitTopicAttrs(text) {
    var s = trim(text), conf = null, size = null, changed = true;
    function tryAttrs(seg) {
      var joined = trim(seg);
      if (!joined) return null;
      var whole = parseConfidence(joined);
      if (whole !== null && conf === null) return { conf: whole, size: null };
      var wsize = parseSize(joined, false);
      if (wsize !== null && size === null) return { conf: null, size: wsize };
      var parts = joined.split(/[,;\/|]+| (?=[^ ])/);
      var c = null, z = null, ok = 0;
      for (var i = 0; i < parts.length; i++) {
        var p = trim(parts[i]);
        if (!p) continue;
        var pc = parseConfidence(p), ps = parseSize(p, false);
        if (pc !== null && c === null && conf === null) { c = pc; ok++; continue; }
        if (ps !== null && z === null && size === null) { z = ps; ok++; continue; }
        return null;
      }
      return ok ? { conf: c, size: z } : null;
    }
    while (changed && s) {
      changed = false;
      var m = /\(([^()]*)\)$/.exec(s) || /\[([^\[\]]*)\]$/.exec(s) || /\{([^{}]*)\}$/.exec(s);
      var seg = null, cut = -1;
      if (m) { seg = m[1]; cut = m.index; }
      else {
        var m2 = /(?:^|[ ])(?:[\-\u2013|,;:]|--) *([^\-\u2013|,;:]*)$/.exec(s);
        if (m2) { seg = m2[1]; cut = m2.index; }
        else {
          var m3 = / ([^ ]+)$/.exec(s);
          if (m3 && STRICT_ATTR.test(lower(m3[1]))) { seg = m3[1]; cut = m3.index; }
        }
      }
      if (seg === null) break;
      var got = tryAttrs(seg);
      if (!got) break;
      if (got.conf !== null) conf = got.conf;
      if (got.size !== null) size = got.size;
      s = trim(s.slice(0, cut));
      changed = true;
    }
    s = trim(s.replace(/[\-\u2013|,;:]+$/, ''));
    return { name: s, conf: conf, size: size };
  }
  M.splitTopicAttrs = splitTopicAttrs;

  var TOPIC_SYNONYMS = {
    code: ['module code', 'module', 'code', 'course', 'course code', 'unit', 'unit code', 'subject', 'paper', 'exam', 'module title', 'module name'],
    name: ['topic', 'topics', 'topic name', 'title', 'name', 'area', 'chapter', 'lecture', 'week', 'content', 'subtopic', 'sub topic', 'theme', 'section', 'item', 'what'],
    conf: ['confidence', 'conf', 'how confident', 'rating', 'confidence 1 5', 'confidence 1 to 5', 'rag', 'feel', 'feeling', 'score', 'self rating', 'how well i know it', 'knowledge'],
    size: ['size', 'hours', 'effort', 'weight', 'estimate', 'length', 'time needed', 'workload', 'how big', 'hours needed', 'time', 'study hours', 'est hours'],
    mode: ['plan', 'mode', 'status', 'include'],
    notes: ['notes', 'note', 'comments', 'comment']
  };
  var TOPIC_KEYWORDS = [['code', 'module'], ['code', 'code'], ['name', 'topic'], ['conf', 'confidence'], ['conf', 'confident'], ['size', 'size'], ['size', 'hours'], ['notes', 'notes']];

  function stripBullet(s) {
    return trim(s.replace(/^[ \t]*(?:[\-*\u2022\u00b7\u25aa\u25e6>+]|[0-9]{1,2}[.)]|[a-z][.)]|\[[ x]?\]|\u2610|\u2611)[ \t]+/i, ''));
  }

  // Match a heading or a module word to a known exam: by code, or by the
  // exam's title appearing in the text (or the text in the title).
  function matchModule(text, exams) {
    var f = findCode(text) || findCode(String(text).toUpperCase());
    if (f) return f.code;
    var t = normHeader(text);
    if (!t) return null;
    var best = null;
    for (var i = 0; i < exams.length; i++) {
      var n = normHeader(exams[i].name);
      if (!n) continue;
      if (t === n || (' ' + t + ' ').indexOf(' ' + n + ' ') >= 0 || (t.length >= 6 && (' ' + n + ' ').indexOf(' ' + t + ' ') >= 0)) {
        if (best === null) best = exams[i].code;
      }
    }
    return best;
  }

  // Read topics from a CSV with a header row, or from a pasted list with
  // module headings and bullet points. exams helps match module names.
  function readTopics(text, opts) {
    opts = opts || {};
    var exams = opts.exams || [];
    text = String(text === null || text === undefined ? '' : text);
    var out = { topics: [], messages: [], format: '', rows: 0, skipped: 0 };
    if (/^\s*%PDF/.test(text)) {
      out.messages.push({ level: 'error', text: 'This is a PDF file. Copy the list of topics out of it and paste it here instead.' });
      return out;
    }
    if (trim(text) === '') {
      out.messages.push({ level: 'error', text: 'There was nothing to read.' });
      return out;
    }
    var table = isHtmlTable(text) ? { delim: 'html', rows: htmlRows(text) } : readTable(text);
    var headerAt = -1, map = null;
    if (table.delim && table.delim !== '  ') {
      for (var i = 0; i < table.rows.length && i < 20; i++) {
        var mp = mapColumns(table.rows[i].cells, TOPIC_SYNONYMS, TOPIC_KEYWORDS);
        if (mp.name !== undefined && Object.keys(mp).length >= 2) { headerAt = i; map = mp; break; }
      }
    }
    var noConf = 0, noSize = 0;
    var add = function (code, name, conf, size, mode, line, note) {
      out.rows++;
      if (!name) { out.skipped++; out.messages.push({ level: 'warn', line: line, text: 'Line ' + line + ' has no topic name, so it was skipped.' }); return; }
      if (!code) { out.skipped++; out.messages.push({ level: 'warn', line: line, text: 'Line ' + line + ' ("' + name.slice(0, 40) + '") is not under a module, so it was skipped. Put the module code before it or on a heading line.' }); return; }
      if (conf === null) { noConf++; conf = 3; }
      if (size === null) { noSize++; size = SIZES.m; }
      out.topics.push({ id: '', code: code, name: name, conf: conf, size: size, mode: mode || 'full', note: note || '', line: line });
    };
    if (headerAt >= 0) {
      out.format = table.delim === 'html' ? 'html' : 'csv';
      for (var r = headerAt + 1; r < table.rows.length; r++) {
        var cells = table.rows[r].cells, line = table.rows[r].line;
        if (isBlankRow(cells)) continue;
        var hm = mapColumns(cells, TOPIC_SYNONYMS, []);
        if (hm.name !== undefined && Object.keys(hm).length >= 2) {
          out.messages.push({ level: 'info', line: line, text: 'Line ' + line + ' repeats the header row, so it was skipped.' });
          continue;
        }
        var codeTxt = cell(cells, map.code);
        var code = codeTxt ? (matchModule(codeTxt, exams) || normCode(codeTxt)) : (opts.code || '');
        var rawName = cell(cells, map.name);
        var confTxt = cell(cells, map.conf), sizeTxt = cell(cells, map.size);
        var conf = confTxt ? parseConfidence(confTxt) : null;
        var size = sizeTxt ? parseSize(sizeTxt, true) : null;
        if (confTxt && conf === null) out.messages.push({ level: 'warn', line: line, text: 'Line ' + line + ': could not read the confidence "' + confTxt + '", so 3 is used. Use 1 (weak) to 5 (strong).' });
        if (sizeTxt && size === null) out.messages.push({ level: 'warn', line: line, text: 'Line ' + line + ': could not read the size "' + sizeTxt + '", so M is used. Use S, M, L or hours such as 3h.' });
        var name = rawName;
        if (conf === null && size === null && rawName) {
          var sp = splitTopicAttrs(rawName);
          if (sp.conf !== null || sp.size !== null) { name = sp.name; conf = sp.conf; size = sp.size; }
        }
        var modeTxt = lower(cell(cells, map.mode));
        var mode = /^(drop|dropped|skip|no|exclude|excluded)$/.test(modeTxt) ? 'drop' : /^(quick|skim|light|review only)$/.test(modeTxt) ? 'quick' : 'full';
        add(code, squash(name), conf, size, mode, line, squash(cell(cells, map.notes)));
      }
    } else {
      out.format = 'list';
      var lines = splitLines(text), current = opts.code || '';
      for (var k = 0; k < lines.length; k++) {
        var raw = squash(lines[k]), ln = k + 1;
        if (!raw) continue;
        var bullet = stripBullet(raw) !== raw;
        var body = stripBullet(raw);
        var isHeading = false;
        if (!bullet) {
          if (/^#+ /.test(body) || /:$/.test(body)) isHeading = true;
          else if (!/[,;\t]/.test(lines[k])) {
            var sp2 = splitTopicAttrs(body);
            if (sp2.conf === null && sp2.size === null) {
              var cf = findCode(body);
              var nextBullet = false;
              for (var nb = k + 1; nb < lines.length; nb++) {
                var nl = squash(lines[nb]);
                if (!nl) continue;
                nextBullet = stripBullet(nl) !== nl;
                break;
              }
              if (cf && cf.index === 0) {
                var rest = trim(stripCode(body, cf.code));
                var ex = null;
                for (var e = 0; e < exams.length; e++) if (exams[e].code === cf.code) { ex = exams[e]; break; }
                isHeading = !rest || (ex !== null && normHeader(rest) === normHeader(ex.name)) || nextBullet;
              } else if (!cf) {
                var exact = false;
                for (var e2 = 0; e2 < exams.length; e2++) if (normHeader(exams[e2].name) === normHeader(body)) exact = true;
                isHeading = exact || nextBullet;
              }
            }
          }
        }
        if (isHeading) {
          var htxt = trim(body.replace(/^#+ /, '').replace(/:$/, ''));
          var hc = findCode(htxt);
          current = matchModule(htxt, exams) || (hc ? hc.code : normCode(htxt));
          if (!matchModule(htxt, exams) && !hc) {
            out.messages.push({ level: 'warn', line: ln, text: 'Line ' + ln + ': the heading "' + htxt.slice(0, 40) + '" has no module code and does not match an exam title, so its topics are filed under ' + current + '.' });
          }
          continue;
        }
        var code2 = current;
        var cells2 = /[,;\t]/.test(body) ? parseDelimited(body, sniffDelimiter(body))[0].cells : null;
        var name2, conf2 = null, size2 = null;
        if (cells2 && cells2.length >= 2) {
          var first = trim(cells2[0]);
          var fc = findCode(first);
          var idx = 0;
          if (fc && trim(stripCode(first, fc.code)) === '') { code2 = fc.code; idx = 1; }
          name2 = trim(cells2[idx] || '');
          var extras = [];
          for (var q = idx + 1; q < cells2.length; q++) {
            var tok = trim(cells2[q]);
            if (!tok) continue;
            var pc = parseConfidence(tok), ps = parseSize(tok, conf2 !== null);
            if (pc !== null && conf2 === null) conf2 = pc;
            else if (ps !== null && size2 === null) size2 = ps;
            else extras.push(tok);
          }
          if (extras.length && conf2 === null && size2 === null) name2 = trim(cells2.slice(idx).join(', '));
          if (conf2 === null && size2 === null) {
            var sp3 = splitTopicAttrs(name2);
            name2 = sp3.name; conf2 = sp3.conf; size2 = sp3.size;
          }
        } else {
          var fc2 = findCode(body);
          var b2 = body;
          if (fc2 && fc2.index === 0) {
            code2 = fc2.code;
            b2 = trim(body.slice(fc2.length).replace(/^[ \t]*[\-:\u2013|.]+[ \t]*/, ''));
          }
          var sp4 = splitTopicAttrs(b2);
          name2 = sp4.name; conf2 = sp4.conf; size2 = sp4.size;
        }
        add(code2, squash(name2), conf2, size2, 'full', ln, '');
      }
    }
    // Duplicates within the list.
    var seen = {}, kept = [];
    out.topics.forEach(function (t) {
      var key = t.code + '|' + lower(t.name);
      if (seen[key]) {
        out.skipped++;
        out.messages.push({ level: 'info', line: t.line, text: 'Line ' + t.line + ' repeats "' + t.name + '" for ' + t.code + ', so it was skipped.' });
        return;
      }
      seen[key] = true;
      kept.push(t);
    });
    out.topics = kept;
    if (noConf) out.messages.push({ level: 'info', text: plural(noConf, 'topic') + ' had no confidence rating, so 3 (so-so) was used. Change it in the table.' });
    if (noSize) out.messages.push({ level: 'info', text: plural(noSize, 'topic') + ' had no size, so M (3 hours of first learning at confidence 3) was used.' });
    if (exams.length) {
      var known = {}, orphan = {};
      exams.forEach(function (e) { known[e.code] = true; });
      out.topics.forEach(function (t) { if (!known[t.code]) orphan[t.code] = (orphan[t.code] || 0) + 1; });
      Object.keys(orphan).sort(cmp).forEach(function (c) {
        out.messages.push({ level: 'warn', text: plural(orphan[c], 'topic') + ' for ' + c + ', which is not in your exam timetable: kept, but not planned until an exam for ' + c + ' is added.' });
      });
    }
    if (!out.topics.length && !out.messages.some(function (m) { return m.level === 'error'; })) {
      out.messages.push({ level: 'error', text: 'No topics found. Use one line per topic under a module heading, or the CSV template (Module, Topic, Confidence, Size).' });
    }
    return out;
  }

  function assignTopicIds(topics) {
    var used = {};
    topics.forEach(function (t) {
      if (t.id && !used[t.id]) { used[t.id] = true; return; }
      var base = slugify(t.code + '-' + t.name), id = base, k = 2;
      while (used[id]) { id = base + '-' + k; k++; }
      used[id] = true;
      t.id = id;
    });
  }

  M.readTopics = readTopics;
  M.assignTopicIds = assignTopicIds;

  // ------------------------------------------------------------------
  // Calendars (.ics)
  // ------------------------------------------------------------------

  function icsUnescape(s) {
    return String(s).replace(/\\([nN,;\\])/g, function (m, c) { return c === 'n' || c === 'N' ? '\n' : c; });
  }

  function parseIcsLine(line) {
    var q = false, colon = -1;
    for (var i = 0; i < line.length; i++) {
      var c = line.charAt(i);
      if (c === '"') q = !q;
      else if (c === ':' && !q) { colon = i; break; }
    }
    if (colon < 0) return null;
    var head = line.slice(0, colon), value = line.slice(colon + 1);
    var parts = head.split(';');
    var params = {};
    for (var j = 1; j < parts.length; j++) {
      var eq = parts[j].indexOf('=');
      if (eq > 0) params[parts[j].slice(0, eq).toUpperCase()] = parts[j].slice(eq + 1).replace(/^"|"$/g, '');
    }
    return { name: parts[0].toUpperCase(), params: params, value: value };
  }

  var LONDONISH = ['europe/london', 'gmt standard time', 'gmt', 'europe/belfast', 'gb', 'europe/guernsey', 'europe/jersey', 'europe/isle_of_man', 'greenwich standard time'];

  // A DTSTART-style value as {day, min, allDay} in UK local time.
  function icsTime(value, params, zones) {
    var v = trim(value);
    var m = /^([0-9]{4})([0-9]{2})([0-9]{2})$/.exec(v);
    if (m || (params.VALUE && params.VALUE.toUpperCase() === 'DATE')) {
      if (!m) m = /^([0-9]{4})([0-9]{2})([0-9]{2})/.exec(v);
      if (!m) return null;
      var dd = makeDay(parseInt(m[1], 10), parseInt(m[2], 10), parseInt(m[3], 10));
      return dd === null ? null : { day: dd, min: 0, allDay: true };
    }
    m = /^([0-9]{4})([0-9]{2})([0-9]{2})T([0-9]{2})([0-9]{2})([0-9]{2})?(Z?)$/i.exec(v);
    if (!m) return null;
    var day = makeDay(parseInt(m[1], 10), parseInt(m[2], 10), parseInt(m[3], 10));
    if (day === null) return null;
    var min = parseInt(m[4], 10) * 60 + parseInt(m[5], 10);
    var tz = params.TZID ? lower(params.TZID) : '';
    if (m[7] || tz === 'utc' || tz === 'etc/utc' || tz === 'z') {
      var t = utcToLondon(day, min);
      return { day: t[0], min: t[1], allDay: false };
    }
    if (tz && LONDONISH.indexOf(tz) < 0 && zones) zones[params.TZID] = true;
    return { day: day, min: min, allDay: false };
  }

  function icsDuration(value) {
    var m = /^([+\-])?P(?:([0-9]+)W)?(?:([0-9]+)D)?(?:T(?:([0-9]+)H)?(?:([0-9]+)M)?(?:([0-9]+)S)?)?$/i.exec(trim(value));
    if (!m) return null;
    var mins = (m[2] ? parseInt(m[2], 10) * 7 * 1440 : 0) + (m[3] ? parseInt(m[3], 10) * 1440 : 0) +
      (m[4] ? parseInt(m[4], 10) * 60 : 0) + (m[5] ? parseInt(m[5], 10) : 0);
    return m[1] === '-' ? -mins : mins;
  }

  // Parse a calendar into events with local times. Recurrences are kept as
  // rules and expanded later by expandEvents.
  function parseIcs(text) {
    var out = { events: [], messages: [] };
    var raw = stripBom(String(text)).replace(/\r\n[ \t]/g, '').replace(/\n[ \t]/g, '').replace(/\r[ \t]/g, '');
    var lines = raw.split(/\r\n|\n|\r/);
    var ev = null, depth = 0, zones = {}, bad = 0;
    for (var i = 0; i < lines.length; i++) {
      var l = lines[i];
      if (!trim(l)) continue;
      var up = l.toUpperCase();
      if (up === 'BEGIN:VEVENT') {
        ev = { summary: '', description: '', location: '', categories: '', status: '', transp: '', uid: '', start: null, end: null, durationMin: null, rrule: null, exdates: [], recurrenceId: null, line: i + 1 };
        depth = 0;
        continue;
      }
      if (!ev) continue;
      if (up.indexOf('BEGIN:') === 0) { depth++; continue; }
      if (up.indexOf('END:') === 0 && up !== 'END:VEVENT') { depth--; continue; }
      if (up === 'END:VEVENT') {
        if (ev.start) out.events.push(ev); else bad++;
        ev = null;
        continue;
      }
      if (depth > 0) continue;
      var p = parseIcsLine(l);
      if (!p) continue;
      if (p.name === 'SUMMARY') ev.summary = squash(icsUnescape(p.value));
      else if (p.name === 'DESCRIPTION') ev.description = icsUnescape(p.value);
      else if (p.name === 'LOCATION') ev.location = squash(icsUnescape(p.value));
      else if (p.name === 'CATEGORIES') ev.categories = icsUnescape(p.value);
      else if (p.name === 'STATUS') ev.status = trim(p.value).toUpperCase();
      else if (p.name === 'TRANSP') ev.transp = trim(p.value).toUpperCase();
      else if (p.name === 'UID') ev.uid = trim(p.value);
      else if (p.name === 'DTSTART') ev.start = icsTime(p.value, p.params, zones);
      else if (p.name === 'DTEND') ev.end = icsTime(p.value, p.params, zones);
      else if (p.name === 'DURATION') ev.durationMin = icsDuration(p.value);
      else if (p.name === 'RRULE') ev.rrule = parseRrule(p.value, zones);
      else if (p.name === 'EXDATE') {
        p.value.split(',').forEach(function (v) { var t = icsTime(v, p.params, zones); if (t) ev.exdates.push(t); });
      } else if (p.name === 'RECURRENCE-ID') ev.recurrenceId = icsTime(p.value, p.params, zones);
    }
    if (bad) out.messages.push({ level: 'warn', text: plural(bad, 'event') + ' had no readable start time and were skipped.' });
    var zn = Object.keys(zones).sort(cmp);
    if (zn.length) out.messages.push({ level: 'info', text: 'Times in ' + zn.join(', ') + ' were read as UK clock times.' });
    return out;
  }

  function parseRrule(value, zones) {
    var r = { freq: '', interval: 1, count: null, until: null, byday: [], bymonthday: null };
    value.split(';').forEach(function (part) {
      var eq = part.indexOf('=');
      if (eq < 0) return;
      var k = part.slice(0, eq).toUpperCase(), v = part.slice(eq + 1);
      if (k === 'FREQ') r.freq = v.toUpperCase();
      else if (k === 'INTERVAL') r.interval = Math.max(1, parseInt(v, 10) || 1);
      else if (k === 'COUNT') r.count = Math.max(0, parseInt(v, 10) || 0);
      else if (k === 'UNTIL') r.until = icsTime(v, {}, zones);
      else if (k === 'BYDAY') {
        v.split(',').forEach(function (d) {
          var mm = /([+\-]?[0-9]*)(MO|TU|WE|TH|FR|SA|SU)$/i.exec(trim(d));
          if (mm) r.byday.push(['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'].indexOf(mm[2].toUpperCase()));
        });
      } else if (k === 'BYMONTHDAY') r.bymonthday = parseInt(v, 10) || null;
    });
    r.byday.sort(function (a, b) { return a - b; });
    return r;
  }

  // The start days of a recurring event's occurrences, up to lastDay.
  function occurrenceDays(ev, lastDay, messages) {
    var r = ev.rrule, start = ev.start.day, out = [];
    if (!r || !r.freq) return [start];
    var untilDay = r.until ? r.until.day : null;
    var limit = 3000, n = 0;
    function take(d) {
      if (untilDay !== null && d > untilDay) return false;
      if (r.count !== null && n >= r.count) return false;
      n++;
      if (d <= lastDay) out.push(d);
      return d <= lastDay;
    }
    if (r.freq === 'DAILY') {
      for (var k = 0; k < limit; k++) if (!take(start + k * r.interval)) break;
    } else if (r.freq === 'WEEKLY') {
      var days = r.byday.length ? r.byday : [weekday(start)];
      var weekStart = start - weekday(start);
      var go = true;
      for (var w = 0; w < limit && go; w++) {
        for (var j = 0; j < days.length; j++) {
          var d = weekStart + w * 7 * r.interval + days[j];
          if (d < start) continue;
          if (!take(d)) { go = false; break; }
        }
      }
    } else if (r.freq === 'MONTHLY') {
      var t = ymdFromDay(start), dom = r.bymonthday || t[2];
      for (var mo = 0; mo < limit; mo++) {
        var total = t[1] - 1 + mo * r.interval;
        var y = t[0] + floorDiv(total, 12), mth = total % 12 + 1;
        var dd = makeDay(y, mth, dom);
        if (dd === null) continue;
        if (dd < start) continue;
        if (!take(dd)) break;
      }
    } else if (r.freq === 'YEARLY') {
      var ty = ymdFromDay(start);
      for (var yy = 0; yy < 200; yy++) {
        var d3 = makeDay(ty[0] + yy * r.interval, ty[1], ty[2]);
        if (d3 === null) continue;
        if (!take(d3)) break;
      }
    } else {
      messages.push({ level: 'info', text: '"' + (ev.summary || 'An event') + '" repeats in a way this tool does not follow (' + r.freq + '), so only its first time was used.' });
      return [start];
    }
    return out;
  }

  // Busy times from a calendar between two days, as one-day pieces.
  // Returns {busy: [{day, start, end, label}], allDay: [{day, label}],
  // messages, events}.
  function readCalendar(text, fromDay, toDay) {
    var cal = parseIcs(text);
    var out = { busy: [], allDay: [], messages: cal.messages.slice(), events: 0, skipped: 0 };
    if (!/BEGIN:VCALENDAR/i.test(String(text))) {
      out.messages.unshift({ level: 'error', text: 'This is not a calendar (.ics) file. Export your timetable or calendar as .ics (iCalendar) and load that.' });
      return out;
    }
    var moved = {};
    cal.events.forEach(function (e) {
      if (e.recurrenceId && e.uid) moved[e.uid + '|' + e.recurrenceId.day + '|' + (e.recurrenceId.allDay ? 0 : e.recurrenceId.min)] = true;
    });
    var cancelled = 0, free = 0, allDayEvents = [];
    cal.events.forEach(function (e) {
      if (e.status === 'CANCELLED') { cancelled++; return; }
      if (e.transp === 'TRANSPARENT') { free++; return; }
      out.events++;
      var label = e.summary || 'Busy';
      var len;
      if (e.end) len = (e.end.day - e.start.day) * 1440 + (e.end.min - e.start.min);
      else if (e.durationMin !== null) len = e.durationMin;
      else len = e.start.allDay ? 1440 : 60;
      if (len <= 0) len = e.start.allDay ? 1440 : 60;
      var days = e.recurrenceId ? [e.start.day] : occurrenceDays(e, toDay, out.messages);
      days.forEach(function (d) {
        if (!e.recurrenceId && e.uid && moved[e.uid + '|' + d + '|' + (e.start.allDay ? 0 : e.start.min)]) return;
        for (var x = 0; x < e.exdates.length; x++) {
          var xd = e.exdates[x];
          if (xd.day === d && (xd.allDay || e.start.allDay || xd.min === e.start.min)) return;
        }
        if (e.start.allDay) {
          if (allDayEvents.indexOf(label) < 0) allDayEvents.push(label);
          var n = Math.max(1, floorDiv(len + 1439, 1440));
          for (var k = 0; k < n; k++) {
            if (d + k >= fromDay && d + k <= toDay) out.allDay.push({ day: d + k, label: label });
          }
          return;
        }
        var t0 = d * 1440 + e.start.min, t1 = t0 + len;
        while (t0 < t1) {
          var dd = floorDiv(t0, 1440), dayEnd = (dd + 1) * 1440;
          var piece = Math.min(t1, dayEnd);
          if (dd >= fromDay && dd <= toDay) out.busy.push({ day: dd, start: t0 - dd * 1440, end: piece - dd * 1440, label: label });
          t0 = piece;
        }
      });
    });
    out.busy.sort(function (a, b) { return cmp(a.day, b.day) || cmp(a.start, b.start) || cmp(a.end, b.end) || cmp(a.label, b.label); });
    out.allDay.sort(function (a, b) { return cmp(a.day, b.day) || cmp(a.label, b.label); });
    if (cancelled) out.messages.push({ level: 'info', text: plural(cancelled, 'cancelled event') + ' left out.' });
    if (free) out.messages.push({ level: 'info', text: plural(free, 'event') + ' marked as free (not busy) left out.' });
    if (out.allDay.length) out.messages.push({ level: 'info', text: plural(allDayEvents.length, 'all-day entry', 'all-day entries') + ' (' + allDayEvents.slice(0, 3).join(', ') + (allDayEvents.length > 3 ? ' and others' : '') + ') ' + (allDayEvents.length === 1 ? 'was' : 'were') + ' not counted as busy. Block a day by hand if one means you cannot revise.' });
    if (!out.events && !cal.messages.length) out.messages.push({ level: 'warn', text: 'The calendar had no events.' });
    return out;
  }

  M.parseIcs = parseIcs;
  M.readCalendar = readCalendar;

  // Summarise busy pieces by label for display: [{label, count, minutes}].
  function busySummary(busy) {
    var by = {}, order = [];
    busy.forEach(function (b) {
      if (!by[b.label]) { by[b.label] = { label: b.label, count: 0, minutes: 0, first: b.day, last: b.day }; order.push(b.label); }
      var s = by[b.label];
      s.count++;
      s.minutes += b.end - b.start;
      if (b.day > s.last) s.last = b.day;
    });
    return order.map(function (k) { return by[k]; }).sort(function (a, b) { return cmp(b.minutes, a.minutes) || cmp(a.label, b.label); });
  }
  M.busySummary = busySummary;

  // Busy times from a rota or a spreadsheet: a date, a start and an end (or
  // a length) on each row, and what it is. Shifts past midnight carry on into
  // the next day.
  var BUSY_SYNONYMS = {
    date: ['date', 'day', 'shift date', 'when', 'start date', 'date of shift', 'work date'],
    start: ['start', 'start time', 'from', 'begins', 'time in', 'clock in', 'shift start', 'starts', 'time'],
    end: ['end', 'end time', 'to', 'finish', 'finish time', 'until', 'time out', 'clock out', 'shift end', 'ends'],
    duration: ['hours', 'duration', 'length', 'shift length', 'mins', 'minutes'],
    label: ['role', 'shift', 'what', 'event', 'activity', 'description', 'title', 'subject', 'type', 'summary', 'location', 'site', 'job', 'name']
  };

  function readBusyTable(text, fromDay, toDay) {
    var out = { busy: [], allDay: [], messages: [], events: 0, skipped: 0 };
    text = String(text === null || text === undefined ? '' : text);
    var table = isHtmlTable(text) ? { delim: 'html', rows: htmlRows(text) } : readTable(text);
    var headerAt = -1, map = null;
    for (var i = 0; i < table.rows.length && i < 20; i++) {
      var mp = mapColumns(table.rows[i].cells, BUSY_SYNONYMS, []);
      if (mp.date !== undefined && mp.start !== undefined && (mp.end !== undefined || mp.duration !== undefined)) { headerAt = i; map = mp; break; }
    }
    if (headerAt < 0) {
      out.messages.push({ level: 'error', text: 'No header row with a date, a start and an end (or a length) was found. Export your rota with those columns, or load a calendar (.ics) instead.' });
      return out;
    }
    var unit = map.duration !== undefined ? durationUnit(table.rows[headerAt].cells[map.duration]) : '';
    var orderInfo = dateOrderOf(table.rows.slice(headerAt + 1).map(function (r) { return cell(r.cells, map.date); }));
    for (var r = headerAt + 1; r < table.rows.length; r++) {
      var cells = table.rows[r].cells, line = table.rows[r].line;
      if (isBlankRow(cells)) continue;
      var dateTxt = cell(cells, map.date), startTxt = cell(cells, map.start), endTxt = cell(cells, map.end), durTxt = cell(cells, map.duration);
      var hm = mapColumns(cells, BUSY_SYNONYMS, []);
      if (hm.date !== undefined && hm.start !== undefined) continue;
      var day = parseDate(dateTxt, orderInfo.order, fromDay);
      if (day === null) { out.skipped++; out.messages.push({ level: 'warn', line: line, text: 'Line ' + line + ': could not read the date "' + dateTxt + '", so the row was skipped.' }); continue; }
      var start = parseClock(startTxt);
      if (start === null) {
        out.skipped++;
        out.messages.push({ level: 'warn', line: line, text: 'Line ' + line + ': no start time ("' + startTxt + '"), so the row was skipped.' });
        continue;
      }
      var len = null;
      if (endTxt) { var end = parseClock(endTxt); if (end !== null) len = end > start ? end - start : end + 1440 - start; }
      if (len === null && durTxt) len = parseDuration(durTxt, unit);
      if (len === null || len <= 0) {
        out.skipped++;
        out.messages.push({ level: 'warn', line: line, text: 'Line ' + line + ': no end time or length, so the row was skipped.' });
        continue;
      }
      out.events++;
      var label = squash(cell(cells, map.label)) || 'Busy';
      var t0 = day * 1440 + start, t1 = t0 + Math.min(len, 2880);
      while (t0 < t1) {
        var dd = floorDiv(t0, 1440), piece = Math.min(t1, (dd + 1) * 1440);
        if (dd >= fromDay && dd <= toDay) out.busy.push({ day: dd, start: t0 - dd * 1440, end: piece - dd * 1440, label: label });
        t0 = piece;
      }
    }
    out.busy.sort(function (a, b) { return cmp(a.day, b.day) || cmp(a.start, b.start) || cmp(a.end, b.end) || cmp(a.label, b.label); });
    dateOrderMessages(orderInfo, out);
    if (!out.events) out.messages.push({ level: 'error', text: 'No busy times could be read from this file.' });
    return out;
  }
  M.readBusyTable = readBusyTable;

  // Busy times from either a calendar file or a rota table.
  function readBusy(text, fromDay, toDay) {
    return /BEGIN:VCALENDAR/i.test(String(text)) ? readCalendar(text, fromDay, toDay) : readBusyTable(text, fromDay, toDay);
  }
  M.readBusy = readBusy;

  // One line describing what an import read, kept with the project.
  function importSummary(kind, res) {
    if (kind === 'exams') {
      var dated = res.exams.filter(function (e) { return e.day !== null; }).length;
      return plural(res.exams.length, 'exam') + (res.exams.length > dated ? ' (' + (res.exams.length - dated) + ' without a date)' : '') + (res.skipped ? ', ' + plural(res.skipped, 'row') + ' skipped' : '');
    }
    if (kind === 'topics') {
      var mods = {};
      res.topics.forEach(function (t) { mods[t.code] = true; });
      return plural(res.topics.length, 'topic') + ' in ' + plural(Object.keys(mods).length, 'module') + (res.skipped ? ', ' + plural(res.skipped, 'line') + ' skipped' : '');
    }
    if (kind === 'calendar') {
      return plural(res.busy.length, 'busy time') + ' from ' + plural(res.events, 'event') + (res.allDay.length ? ', all-day entries on ' + plural(res.allDay.length, 'day') + ' not counted' : '');
    }
    if (kind === 'availability') {
      return plural(res.weekRows, 'weekday row') + ' and ' + plural(res.overrides.length, 'dated change');
    }
    return '';
  }
  M.importSummary = importSummary;

  // ------------------------------------------------------------------
  // Projects: settings, availability and defaults
  // ------------------------------------------------------------------

  var DEFAULT_SETTINGS = {
    learnMin: 50, reviewMin: 25, breakMin: 10, taperDays: 3, papers: 2, maxShare: 50,
    reviewShare: 40, busyGap: 15, examGap: 45, examDay: 'after', paperMax: 180
  };
  var REVIEW_GAPS = [1, 3, 7, 14, 28];
  var CONF_PCT = [150, 125, 100, 75, 50];
  M.DEFAULT_SETTINGS = DEFAULT_SETTINGS;
  M.REVIEW_GAPS = REVIEW_GAPS;
  M.CONF_PCT = CONF_PCT;

  function defaultWeek() {
    var w = [];
    for (var i = 0; i < 7; i++) {
      if (i < 5) w.push({ from: 540, to: 1200, minutes: 300 });
      else if (i === 5) w.push({ from: 600, to: 1080, minutes: 240 });
      else w.push({ from: 660, to: 1080, minutes: 240 });
    }
    return w;
  }
  M.defaultWeek = defaultWeek;

  function newProject(today) {
    return {
      app: 'exam-season', version: M.VERSION, name: 'My revision plan', student: '',
      settings: copySettings(DEFAULT_SETTINGS), exams: [], topics: [], week: defaultWeek(),
      overrides: [], busy: [], allDay: [], sources: [],
      planFrom: today, planFromMin: 0, asOf: null, done: [], settled: [], missed: []
    };
  }
  M.newProject = newProject;

  function copySettings(s) {
    var o = {};
    Object.keys(DEFAULT_SETTINGS).forEach(function (k) { o[k] = s[k] === undefined ? DEFAULT_SETTINGS[k] : s[k]; });
    return o;
  }

  function intOr(v, d) {
    if (typeof v === 'number' && isFinite(v)) return Math.floor(v);
    if (typeof v === 'string' && /^-?[0-9]+$/.test(trim(v))) return parseInt(trim(v), 10);
    return d;
  }

  function strOr(v, d) { return typeof v === 'string' ? v : d; }

  function dayOr(v, d) {
    if (typeof v === 'number' && isFinite(v)) return Math.floor(v);
    if (typeof v === 'string') { var x = fromIso(v); if (x !== null) return x; }
    return d;
  }

  function cleanSettings(s) {
    s = s && typeof s === 'object' ? s : {};
    var o = copySettings({});
    o.learnMin = clamp(intOr(s.learnMin, o.learnMin), 15, 180);
    o.reviewMin = clamp(intOr(s.reviewMin, o.reviewMin), 10, o.learnMin);
    o.breakMin = clamp(intOr(s.breakMin, o.breakMin), 0, 60);
    o.taperDays = clamp(intOr(s.taperDays, o.taperDays), 1, 10);
    o.papers = clamp(intOr(s.papers, o.papers), 0, 6);
    o.maxShare = clamp(intOr(s.maxShare, o.maxShare), 25, 100);
    o.reviewShare = clamp(intOr(s.reviewShare, o.reviewShare), 10, 100);
    o.busyGap = clamp(intOr(s.busyGap, o.busyGap), 0, 120);
    o.examGap = clamp(intOr(s.examGap, o.examGap), 0, 180);
    o.examDay = ['after', 'off', 'normal'].indexOf(s.examDay) >= 0 ? s.examDay : o.examDay;
    o.paperMax = clamp(intOr(s.paperMax, o.paperMax), 30, 300);
    return o;
  }
  M.cleanSettings = cleanSettings;

  // Tidy a project read from a file (or built by the app), filling in
  // anything missing and dropping anything unreadable.
  function cleanProject(p, today) {
    p = p && typeof p === 'object' ? p : {};
    var base = newProject(today);
    var o = {
      app: 'exam-season', version: M.VERSION,
      name: strOr(p.name, base.name), student: strOr(p.student, ''),
      settings: cleanSettings(p.settings),
      exams: [], topics: [], week: [], overrides: [], busy: [], allDay: [], sources: [],
      planFrom: dayOr(p.planFrom, today), planFromMin: clamp(intOr(p.planFromMin, 0), 0, 1439),
      asOf: p.asOf === null || p.asOf === undefined ? null : dayOr(p.asOf, null),
      done: [], settled: [], missed: []
    };
    (Array.isArray(p.exams) ? p.exams : []).forEach(function (e) {
      if (!e || typeof e !== 'object') return;
      var code = normCode(strOr(e.code, ''));
      if (!code) return;
      var day = e.day === null || e.day === undefined ? null : dayOr(e.day, null);
      o.exams.push({
        id: strOr(e.id, ''), code: code, name: squash(strOr(e.name, code)) || code, day: day,
        start: clamp(intOr(e.start, 570), 0, 1439), duration: clamp(intOr(e.duration, 120), 15, 1440),
        room: squash(strOr(e.room, '')), seat: squash(strOr(e.seat, '')), type: squash(strOr(e.type, '')),
        resit: e.resit === true, tbc: day === null, note: squash(strOr(e.note, ''))
      });
    });
    o.exams.sort(examOrder);
    assignExamIds(o.exams);
    (Array.isArray(p.topics) ? p.topics : []).forEach(function (t) {
      if (!t || typeof t !== 'object') return;
      var name = squash(strOr(t.name, ''));
      var code = normCode(strOr(t.code, ''));
      if (!name || !code) return;
      o.topics.push({
        id: strOr(t.id, ''), code: code, name: name, conf: clamp(intOr(t.conf, 3), 1, 5),
        size: clamp(intOr(t.size, 180), 15, 6000), mode: ['full', 'quick', 'drop'].indexOf(t.mode) >= 0 ? t.mode : 'full',
        note: squash(strOr(t.note, ''))
      });
    });
    assignTopicIds(o.topics);
    var wk = Array.isArray(p.week) && p.week.length === 7 ? p.week : base.week;
    for (var i = 0; i < 7; i++) {
      var w = wk[i] && typeof wk[i] === 'object' ? wk[i] : base.week[i];
      var from = clamp(intOr(w.from, base.week[i].from), 0, 1440), to = clamp(intOr(w.to, base.week[i].to), 0, 1440);
      if (to < from) to = from;
      o.week.push({ from: from, to: to, minutes: clamp(intOr(w.minutes, 0), 0, to - from) });
    }
    (Array.isArray(p.overrides) ? p.overrides : []).forEach(function (v) {
      if (!v || typeof v !== 'object') return;
      var day = dayOr(v.day, null);
      if (day === null) return;
      var ov = { day: day, minutes: clamp(intOr(v.minutes, 0), 0, 1440), label: squash(strOr(v.label, '')) };
      if (v.from !== undefined && v.from !== null) ov.from = clamp(intOr(v.from, 0), 0, 1440);
      if (v.to !== undefined && v.to !== null) ov.to = clamp(intOr(v.to, 1440), 0, 1440);
      o.overrides.push(ov);
    });
    o.overrides.sort(function (a, b) { return cmp(a.day, b.day); });
    var dedup = [];
    o.overrides.forEach(function (v) { if (dedup.length && dedup[dedup.length - 1].day === v.day) dedup[dedup.length - 1] = v; else dedup.push(v); });
    o.overrides = dedup;
    (Array.isArray(p.busy) ? p.busy : []).forEach(function (b) {
      if (!b || typeof b !== 'object') return;
      var day = dayOr(b.day, null);
      if (day === null) return;
      var s = clamp(intOr(b.start, 0), 0, 1440), e = clamp(intOr(b.end, 0), 0, 1440);
      if (e <= s) return;
      o.busy.push({ day: day, start: s, end: e, label: squash(strOr(b.label, 'Busy')) || 'Busy' });
    });
    o.busy.sort(function (a, b) { return cmp(a.day, b.day) || cmp(a.start, b.start) || cmp(a.end, b.end) || cmp(a.label, b.label); });
    (Array.isArray(p.allDay) ? p.allDay : []).forEach(function (b) {
      if (!b || typeof b !== 'object') return;
      var day = dayOr(b.day, null);
      if (day !== null) o.allDay.push({ day: day, label: squash(strOr(b.label, '')) });
    });
    (Array.isArray(p.sources) ? p.sources : []).forEach(function (s) {
      if (!s || typeof s !== 'object') return;
      o.sources.push({ kind: strOr(s.kind, ''), name: strOr(s.name, ''), summary: strOr(s.summary, '') });
    });
    var seenDone = {};
    (Array.isArray(p.done) ? p.done : []).forEach(function (d) {
      if (!d || typeof d !== 'object' || typeof d.id !== 'string' || seenDone[d.id]) return;
      var day = dayOr(d.day, null);
      if (day === null) return;
      seenDone[d.id] = true;
      o.done.push({ id: d.id, day: day, min: clamp(intOr(d.min, 0), 0, 1440), exam: strOr(d.exam, ''), code: strOr(d.code, ''), title: strOr(d.title, ''), rating: clamp(intOr(d.rating, 0), 0, 3) });
    });
    o.done.sort(function (a, b) { return cmp(a.day, b.day) || cmp(a.id, b.id); });
    (Array.isArray(p.settled) ? p.settled : []).forEach(function (id) { if (typeof id === 'string' && seenDone[id] && o.settled.indexOf(id) < 0) o.settled.push(id); });
    o.settled.sort(cmp);
    (Array.isArray(p.missed) ? p.missed : []).forEach(function (d) {
      if (!d || typeof d !== 'object' || typeof d.id !== 'string') return;
      var day = dayOr(d.day, null);
      if (day === null) return;
      o.missed.push({ id: d.id, day: day, min: clamp(intOr(d.min, 0), 0, 1440), exam: strOr(d.exam, ''), code: strOr(d.code, ''), title: strOr(d.title, '') });
    });
    o.missed.sort(function (a, b) { return cmp(a.day, b.day) || cmp(a.id, b.id); });
    return o;
  }
  M.cleanProject = cleanProject;

  // ------------------------------------------------------------------
  // Availability files: a weekly template plus dated changes
  // ------------------------------------------------------------------

  var DAY_WORDS = {
    mo: [0], mon: [0], monday: [0], mondays: [0], tu: [1], tue: [1], tues: [1], tuesday: [1], tuesdays: [1],
    we: [2], wed: [2], weds: [2], wednesday: [2], wednesdays: [2], th: [3], thu: [3], thur: [3], thurs: [3], thursday: [3], thursdays: [3],
    fr: [4], fri: [4], friday: [4], fridays: [4], sa: [5], sat: [5], saturday: [5], saturdays: [5], su: [6], sun: [6], sunday: [6], sundays: [6],
    weekdays: [0, 1, 2, 3, 4], weekday: [0, 1, 2, 3, 4], 'mon-fri': [0, 1, 2, 3, 4], weekends: [5, 6], weekend: [5, 6], 'sat-sun': [5, 6],
    daily: [0, 1, 2, 3, 4, 5, 6], 'every day': [0, 1, 2, 3, 4, 5, 6], everyday: [0, 1, 2, 3, 4, 5, 6], all: [0, 1, 2, 3, 4, 5, 6]
  };

  // A clock time where a bare hour is allowed ("9" is 09:00) and 24:00 is the end of the day.
  function parseClock(text) {
    var s = lower(trim(text));
    if (!s) return null;
    if (s === '24:00' || s === 'midnight') return 1440;
    var m = /^([0-9]{1,2})$/.exec(s);
    if (m) { var h = parseInt(m[1], 10); return h <= 24 ? h * 60 : null; }
    var m2 = /^([0-9]{1,2})[:.]([0-9]{2})$/.exec(s);
    if (m2) {
      var hh = parseInt(m2[1], 10), mm = parseInt(m2[2], 10);
      return hh <= 23 && mm <= 59 ? hh * 60 + mm : null;
    }
    var t = parseTime(s);
    return t;
  }
  M.parseClock = parseClock;

  function parseHours(text) {
    var s = lower(trim(text));
    if (!s) return null;
    if (/^(off|none|no|blocked|busy|away|holiday|x|-+)$/.test(s)) return 0;
    var m = /^([0-9]+(?:\.[0-9]+)?) ?(?:h|hr|hrs|hour|hours)?$/.exec(s);
    if (m) return scaleDecimal(m[1], 60);
    m = /^([0-9]+) ?(?:m|min|mins|minutes)$/.exec(s);
    if (m) return parseInt(m[1], 10);
    m = /^([0-9]{1,2}):([0-9]{2})$/.exec(s);
    if (m) return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
    return null;
  }

  var AVAIL_SYNONYMS = {
    day: ['day', 'date', 'days', 'when', 'weekday', 'day or date'],
    from: ['from', 'start', 'start time', 'earliest', 'begin', 'available from'],
    to: ['to', 'end', 'end time', 'latest', 'until', 'finish', 'available until'],
    hours: ['hours', 'hours to revise', 'revision hours', 'max hours', 'study hours', 'hrs', 'time', 'minutes'],
    note: ['note', 'notes', 'why', 'reason', 'label', 'comment']
  };

  // Read a weekly template and dated changes. Rows name a weekday (or
  // "weekdays", "weekends") or a date or date range, with the window and
  // the hours you can revise that day ("off" or 0 blocks the day).
  function readAvailability(text, base) {
    var out = { week: (base || defaultWeek()).map(function (w) { return { from: w.from, to: w.to, minutes: w.minutes }; }), overrides: [], messages: [], rows: 0, weekRows: 0 };
    var table = readTable(text);
    var headerAt = -1, map = null;
    for (var i = 0; i < table.rows.length && i < 10; i++) {
      var mp = mapColumns(table.rows[i].cells, AVAIL_SYNONYMS, []);
      if (mp.day !== undefined && Object.keys(mp).length >= 2) { headerAt = i; map = mp; break; }
    }
    if (headerAt < 0) {
      out.messages.push({ level: 'error', text: 'No header row found. Use the columns Day, From, To, Hours (and Note): one row per weekday, plus a row for each date that is different.' });
      return out;
    }
    var hoursAreMin = /min/.test(normHeader(table.rows[headerAt].cells[map.hours] || ''));
    for (var r = headerAt + 1; r < table.rows.length; r++) {
      var cells = table.rows[r].cells, line = table.rows[r].line;
      if (isBlankRow(cells)) continue;
      out.rows++;
      var dayTxt = cell(cells, map.day), fromTxt = cell(cells, map.from), toTxt = cell(cells, map.to);
      var hoursTxt = cell(cells, map.hours), note = squash(cell(cells, map.note));
      var from = fromTxt ? parseClock(fromTxt) : null, to = toTxt ? parseClock(toTxt) : null;
      if (fromTxt && from === null) out.messages.push({ level: 'warn', line: line, text: 'Line ' + line + ': could not read the time "' + fromTxt + '".' });
      if (toTxt && to === null) out.messages.push({ level: 'warn', line: line, text: 'Line ' + line + ': could not read the time "' + toTxt + '".' });
      var minutes = hoursTxt ? (hoursAreMin && /^[0-9]+$/.test(trim(hoursTxt)) ? parseInt(trim(hoursTxt), 10) : parseHours(hoursTxt)) : null;
      if (hoursTxt && minutes === null) {
        out.messages.push({ level: 'warn', line: line, text: 'Line ' + line + ': could not read the hours "' + hoursTxt + '", so the row was skipped.' });
        continue;
      }
      var key = lower(squash(dayTxt));
      if (DAY_WORDS[key] !== undefined) {
        out.weekRows++;
        DAY_WORDS[key].forEach(function (wd) {
          var w = out.week[wd];
          if (from !== null) w.from = Math.min(from, 1440);
          if (to !== null) w.to = Math.min(to, 1440);
          if (w.to < w.from) w.to = w.from;
          if (minutes !== null) w.minutes = minutes;
          else if (from !== null || to !== null) w.minutes = w.to - w.from;
          if (w.minutes > w.to - w.from) w.minutes = w.to - w.from;
        });
        continue;
      }
      var range = dayTxt.split(/ +(?:-|–|to|until) +|–/);
      var d1 = parseDate(range[0], 'DMY', null), d2 = range.length > 1 ? parseDate(range[1], 'DMY', null) : d1;
      if (d1 === null || d2 === null) {
        out.messages.push({ level: 'warn', line: line, text: 'Line ' + line + ': "' + dayTxt + '" is not a weekday or a date, so the row was skipped.' });
        continue;
      }
      if (d2 < d1) { var tmp = d1; d1 = d2; d2 = tmp; }
      if (d2 - d1 > 366) { out.messages.push({ level: 'warn', line: line, text: 'Line ' + line + ': the date range is longer than a year, so it was skipped.' }); continue; }
      if (minutes === null) minutes = from !== null && to !== null ? Math.max(0, to - from) : 0;
      for (var d = d1; d <= d2; d++) {
        var ov = { day: d, minutes: minutes, label: note };
        if (from !== null) ov.from = from;
        if (to !== null) ov.to = to;
        out.overrides.push(ov);
      }
    }
    out.overrides.sort(function (a, b) { return cmp(a.day, b.day); });
    return out;
  }
  M.readAvailability = readAvailability;

  function availabilityCsv(project) {
    var rows = [['Day', 'From', 'To', 'Hours', 'Note']];
    project.week.forEach(function (w, i) { rows.push([WD3[i], fmtTime(w.from), fmtTime(w.to), tenths(w.minutes), '']); });
    project.overrides.forEach(function (v) {
      var t = ymdFromDay(v.day);
      rows.push([pad2(t[2]) + '/' + pad2(t[1]) + '/' + t[0], v.from === undefined ? '' : fmtTime(v.from), v.to === undefined ? '' : fmtTime(v.to), tenths(v.minutes), v.label]);
    });
    return csvText(rows);
  }
  M.availabilityCsv = availabilityCsv;

  // The study window for one day: {from, to, cap, blocked, label}.
  function dayWindow(project, day) {
    var w = project.week[weekday(day)];
    var o = { from: w.from, to: w.to, cap: w.minutes, blocked: w.minutes <= 0, label: '' };
    for (var i = 0; i < project.overrides.length; i++) {
      var v = project.overrides[i];
      if (v.day !== day) continue;
      if (v.from !== undefined) o.from = v.from;
      if (v.to !== undefined) o.to = v.to;
      o.cap = v.minutes;
      o.blocked = v.minutes <= 0;
      o.label = v.label;
    }
    if (o.to < o.from) o.to = o.from;
    return o;
  }
  M.dayWindow = dayWindow;

  // Remove [a, b) from a sorted list of free intervals.
  function cut(ivs, a, b) {
    var out = [];
    for (var i = 0; i < ivs.length; i++) {
      var x = ivs[i];
      if (b <= x[0] || a >= x[1]) { out.push([x[0], x[1]]); continue; }
      if (a > x[0]) out.push([x[0], a]);
      if (b < x[1]) out.push([b, x[1]]);
    }
    return out;
  }

  function roundUp5(m) { return Math.floor((m + 4) / 5) * 5; }

  // Free intervals and capacity for a day, after busy times and exams.
  function dayFree(project, day, examsByDay, busyByDay, s) {
    var w = dayWindow(project, day);
    var ivs = w.blocked ? [] : [[w.from, w.to]];
    var cap = w.blocked ? 0 : w.cap;
    (busyByDay[day] || []).forEach(function (b) { ivs = cut(ivs, b.start - s.busyGap, b.end + s.busyGap); });
    var exs = examsByDay[day] || [];
    if (exs.length) {
      var firstStart = 1440, lastEnd = 0;
      exs.forEach(function (e) {
        ivs = cut(ivs, e.start - s.examGap, e.start + e.duration + s.examGap);
        if (e.start < firstStart) firstStart = e.start;
        if (e.start + e.duration > lastEnd) lastEnd = e.start + e.duration;
      });
      if (s.examDay === 'off') { ivs = []; cap = 0; }
      else if (s.examDay === 'after') { ivs = cut(ivs, 0, lastEnd + s.examGap); cap = floorDiv(cap, 2); }
    }
    var clean = [], total = 0;
    ivs.forEach(function (iv) {
      var a = roundUp5(iv[0]), b = iv[1];
      if (b - a >= 10) { clean.push([a, b]); total += b - a; }
    });
    return { window: w, intervals: clean, cap: Math.min(cap, total), blocked: w.blocked, label: w.label };
  }

  // ------------------------------------------------------------------
  // The planner
  // ------------------------------------------------------------------

  function learnSessions(t, s) {
    if (t.mode === 'quick') return 1;
    var pct = CONF_PCT[clamp(t.conf, 1, 5) - 1];
    return Math.max(1, ceilDiv(t.size * pct, 100 * s.learnMin));
  }

  function learnLength(t, s) { return t.mode === 'quick' ? s.reviewMin : s.learnMin; }

  function reviewMax(t) { return t.mode === 'quick' ? 1 : REVIEW_GAPS.length; }

  // Minutes the rules ask for on one topic: first learning, three spaced
  // reviews (one for a quick topic) and the final review.
  function topicNeed(t, s) {
    return learnSessions(t, s) * learnLength(t, s) + Math.min(reviewMax(t), 3) * s.reviewMin + s.reviewMin;
  }

  M.learnSessions = learnSessions;
  M.learnLength = learnLength;
  M.topicNeed = topicNeed;

  function paperLength(e, s) { return clamp(e.duration, 30, s.paperMax); }
  M.paperLength = paperLength;

  function topicPriority(a, b) {
    return cmp(a.t.conf, b.t.conf) || cmp(b.t.size, a.t.size) || cmp(a.order, b.order);
  }

  function parseId(id) {
    var parts = String(id).split(':');
    return { kind: parts[0], a: parts[1] || '', b: parts[2] || '' };
  }
  M.parseId = parseId;

  // Build the plan. The schedule depends only on the project's inputs, the
  // day and time it was planned from, and the sessions that were already
  // done ("settled") when it was planned, so ticking sessions off never
  // moves anything; re-planning does.
  function buildPlan(project) {
    var s = project.settings;
    var from = project.planFrom;
    var notes = [];
    var settledSet = {};
    project.settled.forEach(function (id) { settledSet[id] = true; });
    var history = project.done.filter(function (d) { return settledSet[d.id]; });

    var dated = project.exams.filter(function (e) { return e.day !== null; });
    var upcoming = dated.filter(function (e) { return e.day >= from; });
    project.exams.forEach(function (e) {
      if (e.day === null) notes.push({ level: 'warn', exam: e.id, text: e.code + ' ' + e.name + ': date to be confirmed, so it is not planned yet. Add the date when it is published.' });
    });
    dated.forEach(function (e) {
      if (e.day < from) notes.push({ level: 'info', exam: e.id, text: e.code + ' ' + e.name + ' was on ' + fmtShort(e.day) + ', before this plan starts, so it is not planned.' });
    });
    var plan = {
      from: from, fromMin: project.planFromMin, last: from, settings: s, exams: [], days: [], sessions: [], notes: notes,
      topics: [], byExam: {}, byId: {}
    };
    if (!upcoming.length) {
      if (!project.exams.length) notes.push({ level: 'info', text: 'No exams yet: load your exam timetable to make a plan.' });
      else notes.push({ level: 'warn', text: 'None of your exams has a date on or after ' + fmtShort(from) + ', so there is nothing to plan.' });
      return plan;
    }
    var last = upcoming[upcoming.length - 1].day;
    plan.last = last;
    var nDays = last - from + 1;

    // Exams, their deadlines and the topic each module's work aims at.
    var target = {};
    var examsByDay = {};
    upcoming.forEach(function (e, i) {
      var info = {
        id: e.id, code: e.code, name: e.name, day: e.day, start: e.start, duration: e.duration, room: e.room, seat: e.seat,
        resit: e.resit, colour: i % 6, learnBy: e.day - s.taperDays - 1, aimBy: e.day - s.taperDays - 8, taperFrom: e.day - s.taperDays, finalDay: null,
        topicIds: [], paperLen: paperLength(e, s), second: false
      };
      if (target[e.code]) info.second = true; else target[e.code] = info;
      plan.exams.push(info);
      plan.byExam[e.id] = info;
      (examsByDay[e.day] = examsByDay[e.day] || []).push(e);
    });
    var dupes = {};
    upcoming.forEach(function (e) { dupes[e.code] = (dupes[e.code] || 0) + 1; });
    Object.keys(dupes).sort(cmp).forEach(function (c) {
      if (dupes[c] > 1) notes.push({ level: 'info', text: c + ' has ' + dupes[c] + ' exams. Its topics are learnt for the first one; the later ones get past papers and a final review.' });
    });
    for (var di = 1; di < upcoming.length; di++) {
      if (upcoming[di].day === upcoming[di - 1].day) notes.push({ level: 'info', text: 'Two exams on ' + fmtShort(upcoming[di].day) + ' (' + upcoming[di - 1].code + ' and ' + upcoming[di].code + '): the day before is shared between them.' });
    }

    // Topics with their state from what was already done.
    var orphan = {};
    var states = [], stById = {}, order = 0;
    project.topics.forEach(function (t) {
      if (t.mode === 'drop') return;
      var ex = target[t.code];
      if (!ex) { orphan[t.code] = (orphan[t.code] || 0) + 1; return; }
      var st = {
        t: t, exam: ex, order: order++, len: learnLength(t, s), count: learnSessions(t, s), done: 0, nextK: 1,
        learnedDay: null, reviews: 0, step: 0, shaky: 0, nextR: 1, lastReview: null, due: null, rmax: reviewMax(t), lastDay: null,
        planned: 0, plannedReviews: 0
      };
      states.push(st);
      stById[t.id] = st;
      ex.topicIds.push(t.id);
    });
    Object.keys(orphan).sort(cmp).forEach(function (c) {
      notes.push({ level: 'warn', text: plural(orphan[c], 'topic') + ' for ' + c + (orphan[c] === 1 ? ' is' : ' are') + ' not planned: there is no upcoming exam for ' + c + '.' });
    });
    plan.exams.forEach(function (e) {
      if (e.second) e.topicIds = target[e.code].topicIds.slice();
      if (!e.topicIds.length && !e.second) notes.push({ level: 'warn', exam: e.id, text: e.code + ' ' + e.name + ' has no topics yet, so it only gets past papers and a final review day. Add its topics to plan the revision.' });
    });

    var lastLearn = {}, usedToday = 0, papersDone = {}, finalsDone = {};
    history.slice().sort(function (a, b) { return cmp(a.day, b.day) || cmp(a.id, b.id); }).forEach(function (h) {
      var p = parseId(h.id);
      if (h.day === from) usedToday += h.min;
      if (p.kind === 'learn' && stById[p.a]) {
        var st = stById[p.a];
        st.done++;
        st.nextK = Math.max(st.nextK, (parseInt(p.b, 10) || 0) + 1);
        lastLearn[p.a] = Math.max(lastLearn[p.a] === undefined ? h.day : lastLearn[p.a], h.day);
        if (h.day >= from) st.lastDay = h.day;
      } else if (p.kind === 'review' && stById[p.a]) {
        var sr = stById[p.a];
        sr.reviews++;
        // How the review went moves the topic along its ladder of gaps:
        // shaky starts it again, OK moves one step, solid moves two.
        if (h.rating === 1) { sr.step = 0; sr.shaky++; } else sr.step += h.rating === 3 ? 2 : 1;
        sr.nextR = Math.max(sr.nextR, (parseInt(p.b, 10) || 0) + 1);
        sr.lastReview = sr.lastReview === null ? h.day : Math.max(sr.lastReview, h.day);
        if (h.day >= from) sr.lastDay = h.day;
      } else if (p.kind === 'paper') {
        papersDone[p.a] = papersDone[p.a] || { n: 0, next: 1 };
        papersDone[p.a].n++;
        papersDone[p.a].next = Math.max(papersDone[p.a].next, (parseInt(p.b, 10) || 0) + 1);
      } else if (p.kind === 'final') {
        finalsDone[p.a + ':' + p.b] = true;
      }
    });
    states.forEach(function (st) {
      if (st.done >= st.count) {
        st.learnedDay = lastLearn[st.t.id] === undefined ? from - 1 : lastLearn[st.t.id];
        var prev = st.reviews === 0 ? st.learnedDay : Math.max(st.lastReview, st.learnedDay);
        if (st.step < st.rmax) st.due = prev + REVIEW_GAPS[Math.min(st.step, REVIEW_GAPS.length - 1)];
      }
    });

    // Days: windows, busy times and exams.
    var busyByDay = {};
    project.busy.forEach(function (b) { (busyByDay[b.day] = busyByDay[b.day] || []).push(b); });
    var days = [];
    for (var i = 0; i < nDays; i++) {
      var d = from + i;
      var f = dayFree(project, d, examsByDay, busyByDay, s);
      if (i === 0 && project.planFromMin > 0) {
        f.intervals = cut(f.intervals, 0, roundUp5(project.planFromMin));
        var tot = 0;
        f.intervals.forEach(function (iv) { tot += iv[1] - iv[0]; });
        f.cap = Math.min(f.cap, tot);
      }
      if (i === 0) f.cap = Math.max(0, f.cap - usedToday);
      days.push({
        day: d, cap: f.cap, fullCap: f.cap, intervals: f.intervals, blocked: f.blocked, label: f.label,
        examIds: (examsByDay[d] || []).map(function (e) { return e.id; }), reserved: [], sessions: [], used: 0, paper: false
      });
    }

    // The day before each exam is kept for it (or the nearest earlier free day).
    plan.exams.forEach(function (e) {
      for (var back = 1; back <= 3; back++) {
        var d = e.day - back;
        if (d < from) break;
        var dd = days[d - from];
        if (dd.cap <= 0) continue;
        var clash = dd.reserved.some(function (rid) { return plan.byExam[rid].day !== e.day; });
        if (clash) continue;
        dd.reserved.push(e.id);
        e.finalDay = d;
        break;
      }
      if (e.finalDay === null && e.day > from) notes.push({ level: 'warn', exam: e.id, text: 'No free day in the three days before ' + e.code + ' (' + fmtShort(e.day) + ') to keep for a final review.' });
    });

    // Past papers: booked first, as late as possible in the taper.
    var sessions = [];
    function addSession(se, dayObj) {
      sessions.push(se);
      dayObj.sessions.push(se);
      dayObj.used += se.min;
      plan.byId[se.id] = se;
    }
    plan.exams.forEach(function (e) {
      var pd = papersDone[e.id] || { n: 0, next: 1 };
      var k = pd.next;
      var len = e.paperLen;
      for (var n = pd.n; n < s.papers; n++) {
        var booked = false;
        for (var d = e.day - 2; d >= Math.max(from, e.day - 15); d--) {
          var dd = days[d - from];
          if (dd.reserved.length || dd.examIds.length || dd.paper) continue;
          if (dd.cap - dd.used < len) continue;
          for (var v = 0; v < dd.intervals.length; v++) {
            var iv = dd.intervals[v];
            if (iv[1] - iv[0] >= len) {
              var se = {
                id: 'paper:' + e.id + ':' + k, kind: 'paper', day: d, start: iv[0], end: iv[0] + len, min: len,
                exam: e.id, code: e.code, topic: '', title: 'Past paper ' + k, detail: 'Timed, ' + fmtDur(len) + ', then mark it'
              };
              dd.intervals = cut(dd.intervals, iv[0], iv[0] + len + s.breakMin);
              dd.paper = true;
              addSession(se, dd);
              booked = true;
              break;
            }
          }
          if (booked) break;
        }
        if (!booked) break;
        k++;
      }
      e.papersPlanned = k - pd.next;
      e.papersDone = pd.n;
    });

    // Learning capacity left on each day, for the slack of each module.
    var prefix = [0];
    for (var pi = 0; pi < nDays; pi++) {
      var dp = days[pi];
      prefix.push(prefix[pi] + (dp.reserved.length ? 0 : Math.max(0, dp.cap - dp.used)));
    }
    function capBetween(a, b) { // days a..b inclusive (indices)
      if (b < a) return 0;
      return prefix[b + 1] - prefix[a];
    }

    var remaining = {};
    plan.exams.forEach(function (e) { remaining[e.id] = 0; });
    states.forEach(function (st) { if (st.done < st.count) remaining[st.exam.id] += (st.count - st.done) * st.len; });

    // Fill each day in time order.
    for (var x = 0; x < nDays; x++) {
      fillDay(days[x], x);
    }

    function fillDay(dd, x) {
      var d = dd.day;
      if (dd.cap - dd.used < s.reviewMin && !dd.reserved.length) return;
      var modMin = {}, reviewUsed = 0, lastCode = null;
      dd.sessions.forEach(function (se) { modMin[se.code] = (modMin[se.code] || 0) + se.min; });
      var modCap = Math.max(s.learnMin, floorDiv(dd.cap * s.maxShare, 100));
      var revCap = Math.max(s.reviewMin, floorDiv(dd.cap * s.reviewShare, 100));
      var reservedExams = dd.reserved.map(function (id) { return plan.byExam[id]; });
      var finalQueues = reservedExams.map(function (e) {
        var list = e.topicIds.map(function (id) { return stById[id]; }).filter(function (st) { return !finalsDone[e.id + ':' + st.t.id]; });
        list.sort(topicPriority);
        return { exam: e, list: list, pos: 0 };
      });
      var finalTurn = 0;

      function candidates() {
        var out = [];
        if (dd.reserved.length) {
          for (var q = 0; q < finalQueues.length; q++) {
            var fq = finalQueues[(finalTurn + q) % finalQueues.length];
            if (fq.pos < fq.list.length) {
              var st = fq.list[fq.pos];
              out.push({ kind: 'final', st: st, exam: fq.exam, code: fq.exam.code, len: s.reviewMin, rank: q, queue: fq });
            }
          }
          return out;
        }
        var anyLearn = false;
        for (var i = 0; i < states.length; i++) {
          var st2 = states[i];
          var e = st2.exam;
          if (st2.done < st2.count) {
            if (d <= e.learnBy) {
              anyLearn = true;
              out.push({ kind: 'learn', st: st2, exam: e, code: e.code, len: st2.len, today: st2.lastDay === d });
            }
          } else if (st2.due !== null && st2.due <= d && d <= e.day - 2) {
            out.push({ kind: 'review', st: st2, exam: e, code: e.code, len: s.reviewMin, today: st2.lastDay === d });
          }
        }
        if (anyLearn) {
          out = out.filter(function (c) { return c.kind !== 'review' || reviewUsed + c.len <= revCap; });
        }
        return out;
      }

      // The first three reviews of a topic come before new learning; later
      // top-up reviews only fill time that learning cannot use. In the last
      // three days before new topics stop for an exam, its unfinished
      // learning comes first of all.
      function kindRank(c) {
        if (c.kind === 'review') return c.st.step < 3 ? 1 : 3;
        return d >= c.exam.learnBy - 2 ? 0 : 2;
      }

      function better(a, b, cx) {
        // true when a should be placed before b
        var ra = kindRank(a), rb = kindRank(b);
        if (ra !== rb) return ra < rb;
        if (a.kind === 'final') return a.rank < b.rank || (a.rank === b.rank && topicPriority(a.st, b.st) < 0);
        if (a.kind === 'review' && b.kind === 'review') {
          var c = cmp(a.st.due, b.st.due) || cmp(a.exam.day, b.exam.day) || cmp(a.st.t.conf, b.st.t.conf) || cmp(a.st.order, b.st.order);
          return c < 0;
        }
        if (a.exam !== b.exam) {
          // Least slack first: time left before the module's target day
          // minus the first learning it still needs.
          var sa = cx(a.exam) - remaining[a.exam.id], sb = cx(b.exam) - remaining[b.exam.id];
          if (sa !== sb) return sa < sb;
          var c2 = cmp(a.exam.day, b.exam.day) || cmp(a.code, b.code);
          if (c2) return c2 < 0;
        }
        return topicPriority(a.st, b.st) < 0;
      }

      var capCache = {};
      function capFor(e) {
        if (capCache[e.id] !== undefined) return capCache[e.id];
        var end = e.aimBy - from;
        var today = d <= e.aimBy ? Math.max(0, dd.cap - dd.used) : 0;
        var c = today + capBetween(x + 1, Math.min(end, nDays - 1));
        capCache[e.id] = c;
        return c;
      }

      function choose(room) {
        var cands = candidates();
        if (!cands.length) return null;
        capCache = {};
        for (var level = 0; level < 4; level++) {
          var best = null;
          for (var i = 0; i < cands.length; i++) {
            var c = cands[i];
            if (c.len > room) continue;
            if (level < 1 && c.code === lastCode) continue;
            if (c.kind !== 'final') {
              if (level < 3 && c.today) continue;
              if (level < 2 && (modMin[c.code] || 0) + c.len > modCap) continue;
            }
            if (best === null || better(c, best, capFor)) best = c;
          }
          if (best) return best;
        }
        return null;
      }

      function place(c, start) {
        var st = c.st, e = c.exam, se;
        if (c.kind === 'learn') {
          var k = st.nextK;
          se = {
            id: 'learn:' + st.t.id + ':' + k, kind: 'learn', day: d, start: start, end: start + c.len, min: c.len,
            exam: e.id, code: e.code, topic: st.t.id, title: st.t.name,
            detail: st.t.mode === 'quick' ? 'Quick look' : st.count > 1 ? 'Learn, part ' + (st.done + 1) + ' of ' + st.count : 'Learn'
          };
          st.nextK++;
          st.done++;
          st.planned++;
          remaining[e.id] -= c.len;
          if (st.done >= st.count) {
            st.learnedDay = d;
            st.due = st.step < st.rmax ? d + REVIEW_GAPS[Math.min(st.step, REVIEW_GAPS.length - 1)] : null;
          }
        } else if (c.kind === 'review') {
          var n = st.nextR;
          se = {
            id: 'review:' + st.t.id + ':' + n, kind: 'review', day: d, start: start, end: start + c.len, min: c.len,
            exam: e.id, code: e.code, topic: st.t.id, title: st.t.name, detail: 'Review ' + (st.reviews + 1) + ': test yourself, then fill the gaps'
          };
          st.nextR++;
          st.reviews++;
          st.step++;
          st.plannedReviews++;
          st.lastReview = d;
          st.due = st.step < st.rmax ? d + REVIEW_GAPS[Math.min(st.step, REVIEW_GAPS.length - 1)] : null;
          reviewUsed += c.len;
        } else {
          se = {
            id: 'final:' + e.id + ':' + st.t.id, kind: 'final', day: d, start: start, end: start + c.len, min: c.len,
            exam: e.id, code: e.code, topic: st.t.id, title: st.t.name, detail: 'Final review before the exam'
          };
          c.queue.pos++;
          finalTurn = (finalTurn + 1) % finalQueues.length;
        }
        st.lastDay = d;
        modMin[c.code] = (modMin[c.code] || 0) + c.len;
        lastCode = c.code;
        addSession(se, dd);
      }

      for (var v = 0; v < dd.intervals.length; v++) {
        var cur = dd.intervals[v][0];
        while (true) {
          cur = roundUp5(cur);
          var room = Math.min(dd.intervals[v][1] - cur, dd.cap - dd.used);
          if (room < Math.min(s.reviewMin, s.learnMin)) break;
          var pick = choose(room);
          if (!pick) break;
          place(pick, cur);
          cur += pick.len + s.breakMin;
        }
        if (dd.cap - dd.used < s.reviewMin) break;
      }
      dd.sessions.sort(function (a, b) { return cmp(a.start, b.start) || cmp(a.id, b.id); });
    }

    sessions.sort(function (a, b) { return cmp(a.day, b.day) || cmp(a.start, b.start) || cmp(a.id, b.id); });
    plan.sessions = sessions;
    plan.days = days.map(function (dd) {
      return {
        day: dd.day, cap: dd.fullCap, used: dd.used, spare: Math.max(0, dd.cap - dd.used), blocked: dd.blocked, label: dd.label,
        examIds: dd.examIds, reserved: dd.reserved, sessionIds: dd.sessions.map(function (se) { return se.id; })
      };
    });

    // What did not fit, exam by exam.
    plan.exams.forEach(function (e) {
      var sts = e.topicIds.map(function (id) { return stById[id]; });
      var shortTopics = [], shortMin = 0, thin = [], finalsPlanned = 0;
      var need = 0;
      if (!e.second) {
        sts.forEach(function (st) {
          need += topicNeed(st.t, s);
          if (st.done < st.count) { shortTopics.push(st.t.id); shortMin += (st.count - st.done) * st.len; }
          else if (st.reviews < Math.min(2, st.rmax)) thin.push(st.t.id);
        });
      } else {
        need += sts.length * s.reviewMin;
      }
      sts.forEach(function (st) { if (plan.byId['final:' + e.id + ':' + st.t.id] || finalsDone[e.id + ':' + st.t.id]) finalsPlanned++; });
      need += s.papers * e.paperLen;
      e.need = need;
      e.shortTopics = shortTopics;
      e.shortMin = shortMin;
      e.thinTopics = thin;
      e.finalsPlanned = finalsPlanned;
      e.finalsMissing = sts.length - finalsPlanned;
      e.papersMissing = Math.max(0, s.papers - e.papersDone - e.papersPlanned);
    });

    plan.topics = states.map(function (st) {
      return {
        id: st.t.id, code: st.t.code, exam: st.exam.id, name: st.t.name, conf: st.t.conf, size: st.t.size, mode: st.t.mode,
        sessions: st.count, length: st.len, learnt: st.done >= st.count, learnedDay: st.learnedDay, reviews: st.reviews, step: st.step, shaky: st.shaky
      };
    });
    return plan;
  }
  M.buildPlan = buildPlan;

  // ------------------------------------------------------------------
  // Progress: what is done, what was missed, and are you on track?
  // ------------------------------------------------------------------

  function doneMap(project) {
    var m = {};
    project.done.forEach(function (d) { m[d.id] = d; });
    return m;
  }
  M.doneMap = doneMap;

  // Status of every exam on a given day: hours needed, done, still planned,
  // missed, and a verdict with reasons and suggestions.
  function status(project, plan, today) {
    var s = project.settings;
    var done = doneMap(project);
    var out = { today: today, exams: [], todaySessions: [], missed: [], doneMin: 0, aheadMin: 0, missedMin: 0, needMin: 0, verdict: 'ok', shakyNew: 0 };
    var settledSet = {};
    project.settled.forEach(function (id) { settledSet[id] = true; });
    project.done.forEach(function (d) { if (d.rating === 1 && !settledSet[d.id]) out.shakyNew++; });
    var byExamDone = {}, byExamAhead = {}, byExamMissed = {}, byExamMissedN = {};
    project.done.forEach(function (d) {
      byExamDone[d.exam] = (byExamDone[d.exam] || 0) + d.min;
    });
    plan.sessions.forEach(function (se) {
      if (done[se.id]) return;
      if (se.day >= today) byExamAhead[se.exam] = (byExamAhead[se.exam] || 0) + se.min;
      else {
        byExamMissed[se.exam] = (byExamMissed[se.exam] || 0) + se.min;
        byExamMissedN[se.exam] = (byExamMissedN[se.exam] || 0) + 1;
        out.missed.push(se);
      }
      if (se.day === today) out.todaySessions.push(se);
    });
    plan.sessions.forEach(function (se) { if (done[se.id] && se.day === today) out.todaySessions.push(se); });
    out.todaySessions.sort(function (a, b) { return cmp(a.start, b.start) || cmp(a.id, b.id); });
    var topicsById = {};
    project.topics.forEach(function (t) { topicsById[t.id] = t; });
    plan.exams.forEach(function (e) {
      var r = {
        id: e.id, code: e.code, name: e.name, day: e.day, start: e.start, colour: e.colour, daysLeft: e.day - today,
        need: e.need, done: byExamDone[e.id] || 0, ahead: byExamAhead[e.id] || 0, missed: byExamMissed[e.id] || 0,
        missedCount: byExamMissedN[e.id] || 0, short: 0, verdict: 'ok', headline: '', reasons: [], quick: [], quickSaves: 0,
        extraSessions: 0, extraDays: 0, topics: e.topicIds.length
      };
      if (e.day < today) {
        r.verdict = 'sat';
        r.headline = 'Exam done';
        out.exams.push(r);
        return;
      }
      if (e.day === today) {
        r.verdict = 'today';
        r.headline = 'Exam today';
        r.reasons.push('Exam at ' + fmtTime(e.start) + (e.room ? ', ' + e.room : '') + '. Good luck.');
        out.exams.push(r);
        return;
      }
      r.short = Math.max(0, r.need - r.done - r.ahead);
      if (e.shortMin > 0) {
        r.verdict = 'short';
        r.headline = 'Not enough time';
        r.reasons.push(fmtHours(e.shortMin) + ' of first learning (' + plural(e.shortTopics.length, 'topic') + ') does not fit before ' + fmtShort(e.learnBy) + ', when new topics stop for this exam.');
        // Suggest the strongest, smallest topics as quick reviews instead.
        var cands = e.topicIds.map(function (id) { return topicsById[id]; }).filter(function (t) { return t && t.mode === 'full'; });
        cands.sort(function (a, b) { return cmp(b.conf, a.conf) || cmp(a.size, b.size) || cmp(a.name, b.name); });
        var saved = 0;
        for (var i = 0; i < cands.length && saved < e.shortMin; i++) {
          var t = cands[i];
          var save = learnSessions(t, s) * s.learnMin - s.reviewMin;
          if (save <= 0) continue;
          r.quick.push(t.id);
          saved += save;
        }
        r.quickSaves = saved;
        var free = 0;
        for (var d = Math.max(today, plan.from); d <= e.learnBy; d++) {
          var dd = plan.days[d - plan.from];
          if (dd && !dd.blocked && !dd.reserved.length && !dd.examIds.length) free++;
        }
        r.extraDays = free;
        r.extraSessions = ceilDiv(e.shortMin, s.learnMin);
      }
      if (r.missedCount > 0) {
        if (r.verdict === 'ok') { r.verdict = 'behind'; r.headline = 'Behind'; }
        r.reasons.push(plural(r.missedCount, 'session') + ' (' + fmtHours(r.missed) + ') planned before today ' + (r.missedCount === 1 ? 'was' : 'were') + ' not ticked off. Re-plan from today to fit ' + (r.missedCount === 1 ? 'it' : 'them') + ' back in.');
      }
      if (e.papersMissing > 0) {
        if (r.verdict === 'ok') { r.verdict = 'tight'; r.headline = 'Tight'; }
        r.reasons.push(plural(e.papersMissing, 'past paper') + ' could not be fitted in the two weeks before the exam (no free stretch of ' + fmtDur(e.paperLen) + ').');
      }
      if (e.finalDay === null && e.day > today) {
        if (r.verdict === 'ok') { r.verdict = 'tight'; r.headline = 'Tight'; }
        r.reasons.push('There is no free day just before it for a final review.');
      } else if (e.finalDay !== null && e.finalsMissing > 0 && e.topicIds.length) {
        if (r.verdict === 'ok') { r.verdict = 'tight'; r.headline = 'Tight'; }
        r.reasons.push(plural(e.finalsMissing, 'topic') + (e.finalsMissing === 1 ? ' misses' : ' miss') + ' a final review on ' + fmtShort(e.finalDay) + ' (not enough time that day).');
      }
      if (e.thinTopics.length) {
        if (r.verdict === 'ok') { r.verdict = 'tight'; r.headline = 'Tight'; }
        r.reasons.push(plural(e.thinTopics.length, 'topic') + (e.thinTopics.length === 1 ? ' gets' : ' get') + ' fewer than two spaced reviews before the exam, because ' + (e.thinTopics.length === 1 ? 'it is' : 'they are') + ' learnt late.');
      }
      if (r.verdict === 'ok') {
        r.headline = 'On track';
        if (!e.topicIds.length) r.reasons.push('No topics listed: only past papers and a final review are planned.');
        else r.reasons.push('Every topic is learnt by ' + fmtShort(e.learnBy) + ', with spaced reviews, ' + plural(s.papers, 'past paper') + ' and a final review on ' + (e.finalDay === null ? 'the day before' : fmtShort(e.finalDay)) + '.');
      }
      out.exams.push(r);
    });
    var rank = { short: 4, behind: 3, tight: 2, ok: 1, today: 0, sat: 0 };
    out.exams.forEach(function (r) {
      if (r.verdict === 'sat') return;
      out.needMin += r.need;
      out.doneMin += r.done;
      out.aheadMin += r.ahead;
      out.missedMin += r.missed;
      if (rank[r.verdict] > rank[out.verdict]) out.verdict = r.verdict;
    });
    return out;
  }
  M.status = status;

  // Tick a session off (or untick it). A session ticked before its day is
  // recorded as done today.
  function tick(project, plan, id, today, on) {
    var idx = -1;
    for (var i = 0; i < project.done.length; i++) if (project.done[i].id === id) { idx = i; break; }
    if (on === false) {
      if (idx >= 0) {
        project.done.splice(idx, 1);
        var si = project.settled.indexOf(id);
        if (si >= 0) project.settled.splice(si, 1);
      }
      return project;
    }
    if (idx >= 0) return project;
    var se = plan.byId[id];
    if (!se) return project;
    project.done.push({ id: id, day: Math.min(se.day, today), min: se.min, exam: se.exam, code: se.code, title: sessionTitle(se), rating: 0 });
    project.done.sort(function (a, b) { return cmp(a.day, b.day) || cmp(a.id, b.id); });
    return project;
  }
  M.tick = tick;

  // Say how a review went: 1 shaky, 2 OK, 3 solid (0 clears it). Ticks the
  // session off first if it was not already.
  function rate(project, plan, id, today, rating) {
    var entry = null;
    project.done.forEach(function (d) { if (d.id === id) entry = d; });
    if (!entry) {
      tick(project, plan, id, today, true);
      project.done.forEach(function (d) { if (d.id === id) entry = d; });
    }
    if (entry) entry.rating = clamp(rating, 0, 3);
    return project;
  }
  M.rate = rate;

  var RATING_WORD = ['', 'shaky', 'OK', 'solid'];
  M.RATING_WORD = RATING_WORD;

  // Where each topic stands today: learning parts done and still planned,
  // reviews done (with how they went) and planned, the next session, and a
  // one-word state.
  function topicStatus(project, plan, today) {
    var done = doneMap(project);
    var byTopic = {};
    project.done.forEach(function (d) {
      var p = parseId(d.id);
      var tid = p.kind === 'final' ? p.b : p.a;
      if (p.kind === 'paper') return;
      var x = byTopic[tid] = byTopic[tid] || { learn: 0, reviews: [], finals: 0, last: null };
      if (p.kind === 'learn') x.learn++;
      else if (p.kind === 'review') x.reviews.push(d.rating || 0);
      else x.finals++;
      if (x.last === null || d.day > x.last) x.last = d.day;
    });
    var ahead = {};
    plan.sessions.forEach(function (se) {
      if (!se.topic || done[se.id]) return;
      var a = ahead[se.topic] = ahead[se.topic] || { learn: 0, reviews: 0, finals: 0, next: null, missed: 0, learnMissed: 0 };
      if (se.day < today) { a.missed++; if (se.kind === 'learn') a.learnMissed++; return; }
      if (se.kind === 'learn') a.learn++;
      else if (se.kind === 'review') a.reviews++;
      else if (se.kind === 'final') a.finals++;
      if (a.next === null || se.day < a.next.day || (se.day === a.next.day && se.start < a.next.start)) a.next = { day: se.day, start: se.start, kind: se.kind, id: se.id };
    });
    var planTopic = {};
    plan.topics.forEach(function (t) { planTopic[t.id] = t; });
    var out = [];
    project.topics.forEach(function (t) {
      var x = byTopic[t.id] || { learn: 0, reviews: [], finals: 0, last: null };
      var a = ahead[t.id] || { learn: 0, reviews: 0, finals: 0, next: null, missed: 0, learnMissed: 0 };
      var total = t.mode === 'drop' ? 0 : learnSessions(t, project.settings);
      var shaky = x.reviews.filter(function (r) { return r === 1; }).length;
      var state;
      if (t.mode === 'drop') state = 'dropped';
      else if (!planTopic[t.id]) state = 'not planned';
      else if (x.finals > 0) state = 'ready';
      else if (x.learn === 0) state = 'not started';
      else if (x.learn < total) state = 'learning';
      else if (x.reviews.length === 0) state = 'learnt';
      else state = 'reviewing';
      out.push({
        id: t.id, code: t.code, name: t.name, conf: t.conf, mode: t.mode, learnDone: Math.min(x.learn, total), learnTotal: total,
        learnAhead: a.learn, learnMissed: a.learnMissed, reviewsDone: x.reviews.length, ratings: x.reviews, reviewsAhead: a.reviews, finalAhead: a.finals,
        finalDone: x.finals > 0, missed: a.missed, last: x.last, next: a.next, shaky: shaky, state: state
      });
    });
    return out;
  }
  M.topicStatus = topicStatus;

  // Re-plan from a day (and time): sessions planned before it that were not
  // done are kept as "missed", everything done so far is settled, and the
  // plan is rebuilt from there.
  function replan(project, plan, today, nowMin) {
    var done = doneMap(project);
    plan.sessions.forEach(function (se) {
      if (se.day < today && !done[se.id]) {
        project.missed.push({ id: se.id, day: se.day, min: se.min, exam: se.exam, code: se.code, title: sessionTitle(se) });
      }
    });
    project.missed.sort(function (a, b) { return cmp(a.day, b.day) || cmp(a.id, b.id); });
    project.settled = project.done.map(function (d) { return d.id; }).sort(cmp);
    project.planFrom = today;
    project.planFromMin = nowMin || 0;
    return project;
  }
  M.replan = replan;

  // Block a day (or set its hours) and note why.
  function setOverride(project, day, minutes, label, from, to) {
    project.overrides = project.overrides.filter(function (v) { return v.day !== day; });
    var ov = { day: day, minutes: minutes, label: label || '' };
    if (from !== undefined && from !== null) ov.from = from;
    if (to !== undefined && to !== null) ov.to = to;
    project.overrides.push(ov);
    project.overrides.sort(function (a, b) { return cmp(a.day, b.day); });
    return project;
  }
  M.setOverride = setOverride;

  // ------------------------------------------------------------------
  // Checks that catch slips before they become a bad plan
  // ------------------------------------------------------------------

  function checkInputs(project, plan, today) {
    var out = [];
    var s = project.settings;
    var dated = project.exams.filter(function (e) { return e.day !== null; });
    dated.forEach(function (e) {
      var what = e.code + ' ' + e.name;
      if (e.day > today + 240) out.push({ level: 'warn', text: what + ' is on ' + fmtDay(e.day) + ', more than eight months away. Check the year.' });
      if (e.start < 420 || e.start >= 1260) out.push({ level: 'warn', text: what + ' starts at ' + fmtTime(e.start) + '. Check it is not meant to be ' + fmtTime((e.start + 720) % 1440) + ' (am and pm are easy to mix up).' });
      if (e.duration > 300 && e.duration < 1440) out.push({ level: 'warn', text: what + ' lasts ' + fmtDur(e.duration) + ', which is long for an exam. Check the length.' });
      if (e.duration < 30) out.push({ level: 'warn', text: what + ' lasts only ' + fmtDur(e.duration) + ', which is short for an exam. Check the length (the timetable may give it in hours).' });
    });
    for (var i = 0; i < dated.length; i++) {
      for (var j = i + 1; j < dated.length; j++) {
        var a = dated[i], b = dated[j];
        if (a.day !== b.day) continue;
        if (a.start < b.start + b.duration && b.start < a.start + a.duration) {
          out.push({ level: 'error', text: a.code + ' and ' + b.code + ' overlap on ' + fmtShort(a.day) + '. Ask your exams office about a clash arrangement, then set the times you are given.' });
        }
      }
    }
    var codes = {};
    project.topics.forEach(function (t) { (codes[t.code] = codes[t.code] || []).push(t); });
    var examCodes = {};
    plan.exams.forEach(function (e) {
      if (e.second || examCodes[e.code]) return;
      examCodes[e.code] = true;
      var ts = codes[e.code] || [];
      if (!ts.length) out.push({ level: 'warn', text: e.code + ' ' + e.name + ' has no topics, so only past papers and a final review are planned for it.' });
      else if (ts.length >= 5 && ts.every(function (t) { return t.conf === 3; })) out.push({ level: 'info', text: 'Every ' + e.code + ' topic is rated 3. Rating the weak ones lower and the strong ones higher puts the time where you need it.' });
    });
    project.topics.forEach(function (t) {
      if (t.mode !== 'drop' && t.size > 1200) out.push({ level: 'warn', text: '"' + t.name + '" (' + t.code + ') is sized at ' + fmtHours(t.size) + ' of first learning. If that is a typo, pick S, M or L.' });
    });
    var week = 0;
    project.week.forEach(function (w) { week += w.minutes; });
    project.week.forEach(function (w, k) {
      if (w.minutes > 600) out.push({ level: 'warn', text: WEEKDAYS[k] + 's are set to ' + fmtHours(w.minutes) + ' of revision. More than about ten hours a day rarely sticks.' });
    });
    if (week < 300 && plan.exams.length) out.push({ level: 'warn', text: 'Your normal week has only ' + fmtHours(week) + ' of revision. Check the hours under Your time.' });
    if (plan.exams.length) {
      var need = 0, cap = 0;
      plan.exams.forEach(function (e) { need += e.need; });
      plan.days.forEach(function (d) { if (d.day >= today) cap += d.cap; });
      var doneMin = 0;
      project.done.forEach(function (d) { doneMin += d.min; });
      if (need - doneMin > cap) out.push({ level: 'error', text: 'The time is not there: the rules ask for ' + fmtHours(Math.max(0, need - doneMin)) + ' more, and your week has ' + fmtHours(cap) + ' between now and the last exam. See On track for what to drop or shorten.' });
    }
    var rank = { error: 0, warn: 1, info: 2 };
    return out.map(function (c, k) { return [c, k]; }).sort(function (x, y) { return cmp(rank[x[0].level], rank[y[0].level]) || cmp(x[1], y[1]); }).map(function (x) { return x[0]; });
  }
  M.checkInputs = checkInputs;

  // How much of the planned time you actually do, by weekday, from your
  // ticks and the sessions filed as missed. Days before today only.
  function adherence(project, plan, today) {
    var done = doneMap(project);
    var byDay = {};
    function add(day, min, isDone) {
      if (day >= today) return;
      var x = byDay[day] = byDay[day] || { planned: 0, done: 0 };
      x.planned += min;
      if (isDone) x.done += min;
    }
    project.done.forEach(function (d) { add(d.day, d.min, true); });
    project.missed.forEach(function (d) { add(d.day, d.min, false); });
    plan.sessions.forEach(function (se) { if (!done[se.id]) add(se.day, se.min, false); });
    var wd = [];
    for (var k = 0; k < 7; k++) wd.push({ weekday: k, days: 0, planned: 0, done: 0, pct: null, suggest: null });
    Object.keys(byDay).map(Number).sort(function (a, b) { return a - b; }).forEach(function (d) {
      var x = byDay[d], w = wd[weekday(d)];
      w.days++;
      w.planned += x.planned;
      w.done += x.done;
    });
    var totalPlanned = 0, totalDone = 0;
    wd.forEach(function (w) {
      totalPlanned += w.planned;
      totalDone += w.done;
      if (w.planned) w.pct = floorDiv(w.done * 100 + floorDiv(w.planned, 2), w.planned);
      var tmpl = project.week[w.weekday].minutes;
      if (w.days >= 2 && w.pct !== null && w.pct < 70 && tmpl > 0) {
        var perDay = floorDiv(w.done, w.days);
        var to = floorDiv(perDay, 30) * 30;
        if (to < tmpl) w.suggest = to;
      }
    });
    return {
      weekdays: wd, planned: totalPlanned, done: totalDone,
      pct: totalPlanned ? floorDiv(totalDone * 100 + floorDiv(totalPlanned, 2), totalPlanned) : null,
      days: Object.keys(byDay).length
    };
  }
  M.adherence = adherence;

  // ------------------------------------------------------------------
  // Outputs
  // ------------------------------------------------------------------

  var KIND_WORD = { learn: 'Learn', review: 'Review', paper: 'Past paper', final: 'Final review' };
  M.KIND_WORD = KIND_WORD;

  function sessionTitle(se) {
    if (se.kind === 'paper') return se.code + ' ' + se.title;
    return se.code + ' ' + se.title + ' (' + (se.kind === 'learn' ? se.detail.toLowerCase() : KIND_WORD[se.kind].toLowerCase()) + ')';
  }
  M.sessionTitle = sessionTitle;

  function sessionsCsv(project, plan) {
    var done = doneMap(project);
    var rows = [['Date', 'Day', 'Start', 'End', 'Minutes', 'Module', 'Module title', 'Exam date', 'Kind', 'Topic', 'What to do', 'Done', 'Session id']];
    plan.sessions.forEach(function (se) {
      var e = plan.byExam[se.exam];
      rows.push([isoDay(se.day), WD3[weekday(se.day)], fmtTime(se.start), fmtTime(se.end), se.min, se.code, e.name, isoDay(e.day),
        KIND_WORD[se.kind], se.kind === 'paper' ? '' : se.title, se.detail, done[se.id] ? 'yes' : '', se.id]);
    });
    return csvText(rows);
  }
  M.sessionsCsv = sessionsCsv;

  function statusCsv(st) {
    var rows = [['Module', 'Title', 'Exam date', 'Days left', 'Hours needed', 'Hours done', 'Hours still planned', 'Hours missed', 'Verdict', 'Reasons']];
    st.exams.forEach(function (r) {
      rows.push([r.code, r.name, isoDay(r.day), r.daysLeft, tenths(r.need), tenths(r.done), tenths(r.ahead), tenths(r.missed), r.headline, r.reasons.join(' ')]);
    });
    return csvText(rows);
  }
  M.statusCsv = statusCsv;

  function tenths(min) {
    var t = floorDiv(min * 10 + 30, 60);
    return floorDiv(t, 10) + '.' + (t % 10);
  }
  M.tenths = tenths;

  function utf8Len(ch) {
    var c = ch.codePointAt(0);
    return c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4;
  }

  // Fold a content line at 75 octets, never inside a character.
  function icsFold(line) {
    var out = '', len = 0;
    var chars = Array.from(line);
    for (var i = 0; i < chars.length; i++) {
      var n = utf8Len(chars[i]);
      if (len + n > 75) { out += '\r\n '; len = 1; }
      out += chars[i];
      len += n;
    }
    return out;
  }
  M.icsFold = icsFold;

  function icsEscape(s) {
    return String(s).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r\n|\n|\r/g, '\\n');
  }

  function icsStamp(day, min) {
    var t = ymdFromDay(day);
    return t[0] + pad2(t[1]) + pad2(t[2]) + 'T' + pad2(floorDiv(min, 60)) + pad2(min % 60) + '00';
  }

  var VTIMEZONE = [
    'BEGIN:VTIMEZONE', 'TZID:Europe/London',
    'BEGIN:DAYLIGHT', 'TZOFFSETFROM:+0000', 'TZOFFSETTO:+0100', 'TZNAME:BST', 'DTSTART:19810329T010000', 'RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU', 'END:DAYLIGHT',
    'BEGIN:STANDARD', 'TZOFFSETFROM:+0100', 'TZOFFSETTO:+0000', 'TZNAME:GMT', 'DTSTART:19961027T020000', 'RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU', 'END:STANDARD',
    'END:VTIMEZONE'
  ];

  // A calendar of sessions (from a day onwards) and, optionally, the exams.
  function sessionsIcs(project, plan, opts) {
    opts = opts || {};
    var fromDay = opts.fromDay === undefined ? plan.from : opts.fromDay;
    var toDay = opts.toDay === undefined ? plan.last : opts.toDay;
    var done = doneMap(project);
    var stamp = icsStamp(project.planFrom, 0) + 'Z';
    var lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Exam season//Revision plan//EN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
      'X-WR-CALNAME:' + icsEscape(opts.name || 'Revision plan'), 'X-WR-TIMEZONE:Europe/London'];
    VTIMEZONE.forEach(function (l) { lines.push(l); });
    plan.sessions.forEach(function (se) {
      if (se.day < fromDay || se.day > toDay) return;
      if (opts.skipDone && done[se.id]) return;
      var e = plan.byExam[se.exam];
      lines.push('BEGIN:VEVENT');
      lines.push('UID:' + se.id.replace(/:/g, '-') + '@exam-season');
      lines.push('DTSTAMP:' + stamp);
      lines.push('DTSTART;TZID=Europe/London:' + icsStamp(se.day, se.start));
      lines.push('DTEND;TZID=Europe/London:' + icsStamp(se.day, se.end));
      lines.push('SUMMARY:' + icsEscape(sessionTitle(se)));
      lines.push('DESCRIPTION:' + icsEscape(se.detail + '. ' + e.code + ' ' + e.name + ' exam: ' + fmtDay(e.day) + ' at ' + fmtTime(e.start) + '.'));
      lines.push('CATEGORIES:Revision,' + icsEscape(e.code));
      lines.push('TRANSP:OPAQUE');
      if (opts.alarm) {
        lines.push('BEGIN:VALARM');
        lines.push('ACTION:DISPLAY');
        lines.push('DESCRIPTION:' + icsEscape(sessionTitle(se)));
        lines.push('TRIGGER:-PT' + opts.alarm + 'M');
        lines.push('END:VALARM');
      }
      lines.push('END:VEVENT');
    });
    if (opts.exams !== false) {
      plan.exams.forEach(function (e) {
        if (e.day < fromDay || e.day > toDay) return;
        lines.push('BEGIN:VEVENT');
        lines.push('UID:exam-' + e.id + '@exam-season');
        lines.push('DTSTAMP:' + stamp);
        lines.push('DTSTART;TZID=Europe/London:' + icsStamp(e.day, e.start));
        var endT = e.start + e.duration;
        lines.push('DTEND;TZID=Europe/London:' + icsStamp(e.day + floorDiv(endT, 1440), endT % 1440));
        lines.push('SUMMARY:' + icsEscape('EXAM ' + e.code + ' ' + e.name));
        if (e.room) lines.push('LOCATION:' + icsEscape(e.room));
        lines.push('DESCRIPTION:' + icsEscape((e.seat ? 'Seat ' + e.seat + '. ' : '') + 'Bring your student card. Arrive 30 minutes early.'));
        lines.push('CATEGORIES:Exam');
        lines.push('BEGIN:VALARM');
        lines.push('ACTION:DISPLAY');
        lines.push('DESCRIPTION:' + icsEscape('Exam tomorrow: ' + e.code + ' ' + e.name));
        lines.push('TRIGGER:-PT18H');
        lines.push('END:VALARM');
        lines.push('END:VEVENT');
      });
    }
    lines.push('END:VCALENDAR');
    return lines.map(icsFold).join('\r\n') + '\r\n';
  }
  M.sessionsIcs = sessionsIcs;

  // One day's sessions as text to copy or print.
  function dayText(project, plan, day) {
    var done = doneMap(project);
    var lines = [fmtLong(day)];
    var dd = plan.days[day - plan.from];
    var list = plan.sessions.filter(function (se) { return se.day === day; });
    plan.exams.forEach(function (e) { if (e.day === day) lines.push('  EXAM ' + fmtTime(e.start) + ' ' + e.code + ' ' + e.name + (e.room ? ', ' + e.room : '')); });
    if (dd && dd.reserved.length) lines.push('  Kept for ' + dd.reserved.map(function (id) { return plan.byExam[id].code; }).join(' and ') + ': final review only.');
    if (!list.length) lines.push(dd && dd.blocked ? '  No revision (' + (dd.label || 'day off') + ').' : '  Nothing planned.');
    list.forEach(function (se) {
      lines.push('  [' + (done[se.id] ? 'x' : ' ') + '] ' + fmtTime(se.start) + '-' + fmtTime(se.end) + '  ' + sessionTitle(se) + (se.kind === 'review' || se.kind === 'paper' ? ': ' + se.detail : ''));
    });
    var mins = 0;
    list.forEach(function (se) { mins += se.min; });
    if (list.length) lines.push('  ' + plural(list.length, 'session') + ', ' + fmtDur(mins) + ' of revision.');
    plan.exams.forEach(function (e) {
      if (e.day > day) lines.push('  ' + e.code + ' in ' + plural(e.day - day, 'day') + ' (' + fmtShort(e.day) + ')');
    });
    return lines.join('\n') + '\n';
  }
  M.dayText = dayText;

  // The plan as a Markdown checklist, for notes apps that tick boxes.
  function checklistMarkdown(project, plan, fromDay, toDay) {
    var done = doneMap(project);
    fromDay = fromDay === undefined || fromDay === null ? plan.from : fromDay;
    toDay = toDay === undefined || toDay === null ? plan.last : toDay;
    var lines = ['# ' + project.name, '', 'Revision plan from ' + fmtDay(Math.max(fromDay, plan.from)) + ' to ' + fmtDay(Math.min(toDay, plan.last)) + '.'];
    for (var d = Math.max(fromDay, plan.from); d <= Math.min(toDay, plan.last); d++) {
      var list = plan.sessions.filter(function (se) { return se.day === d; });
      var exams = plan.exams.filter(function (e) { return e.day === d; });
      if (!list.length && !exams.length) continue;
      lines.push('', '## ' + fmtLong(d), '');
      exams.forEach(function (e) { lines.push('- **Exam** ' + fmtTime(e.start) + ' ' + e.code + ' ' + e.name + (e.room ? ', ' + e.room : '')); });
      list.forEach(function (se) {
        lines.push('- [' + (done[se.id] ? 'x' : ' ') + '] ' + fmtTime(se.start) + '-' + fmtTime(se.end) + ' ' + sessionTitle(se) + (se.kind === 'review' || se.kind === 'paper' ? ': ' + se.detail : ''));
      });
    }
    return lines.join('\n') + '\n';
  }
  M.checklistMarkdown = checklistMarkdown;

  function projectFile(project) {
    var p = project;
    var o = {
      app: 'exam-season', version: M.VERSION, name: p.name, student: p.student,
      planFrom: isoDay(p.planFrom), planFromMin: p.planFromMin, asOf: p.asOf === null ? null : isoDay(p.asOf),
      settings: p.settings,
      exams: p.exams.map(function (e) {
        return { id: e.id, code: e.code, name: e.name, day: e.day === null ? null : isoDay(e.day), start: e.start, duration: e.duration, room: e.room, seat: e.seat, type: e.type, resit: e.resit, note: e.note };
      }),
      topics: p.topics.map(function (t) { return { id: t.id, code: t.code, name: t.name, conf: t.conf, size: t.size, mode: t.mode, note: t.note }; }),
      week: p.week.map(function (w) { return { from: w.from, to: w.to, minutes: w.minutes }; }),
      overrides: p.overrides.map(function (v) {
        var o2 = { day: isoDay(v.day), minutes: v.minutes, label: v.label };
        if (v.from !== undefined) o2.from = v.from;
        if (v.to !== undefined) o2.to = v.to;
        return o2;
      }),
      busy: p.busy.map(function (b) { return { day: isoDay(b.day), start: b.start, end: b.end, label: b.label }; }),
      allDay: p.allDay.map(function (b) { return { day: isoDay(b.day), label: b.label }; }),
      sources: p.sources,
      done: p.done.map(function (d) { return { id: d.id, day: isoDay(d.day), min: d.min, exam: d.exam, code: d.code, title: d.title, rating: d.rating || 0 }; }),
      settled: p.settled,
      missed: p.missed.map(function (d) { return { id: d.id, day: isoDay(d.day), min: d.min, exam: d.exam, code: d.code, title: d.title }; })
    };
    return JSON.stringify(o, null, 1) + '\n';
  }
  M.projectFile = projectFile;

  // Read a saved project file. Returns {project, messages}.
  function readProject(text, today) {
    var obj;
    try { obj = JSON.parse(stripBom(String(text))); } catch (err) {
      return { project: null, messages: [{ level: 'error', text: 'This is not a project file (it is not valid JSON). Choose a file saved from Exam season.' }] };
    }
    if (!obj || typeof obj !== 'object' || Array.isArray(obj) || (obj.app !== 'exam-season' && !Array.isArray(obj.exams))) {
      return { project: null, messages: [{ level: 'error', text: 'This JSON file is not an Exam season project.' }] };
    }
    var p = cleanProject(obj, today);
    var msgs = [];
    if (typeof obj.version === 'number' && obj.version > M.VERSION) msgs.push({ level: 'warn', text: 'This project was saved by a newer version; anything this version does not know about was left out.' });
    return { project: p, messages: msgs };
  }
  M.readProject = readProject;

  // ------------------------------------------------------------------
  // Templates
  // ------------------------------------------------------------------

  function examTemplate() {
    return csvText([
      ['Module code', 'Module title', 'Date', 'Start time', 'Duration', 'Venue', 'Seat', 'Type'],
      ['ABC1234', 'Example module', '11/01/2027', '09:30', '2 hours', 'Main Hall', '101', 'Unseen exam'],
      ['ABC5678', 'Another module', '2027-01-14', '14:00', '90 min', 'Room 2.04', '', 'Resit'],
      ['ABC9012', 'Third module', 'TBC', '', '', '', '', '']
    ]);
  }

  function topicTemplate() {
    return csvText([
      ['Module', 'Topic', 'Confidence', 'Size'],
      ['ABC1234', 'First topic', '2', 'L'],
      ['ABC1234', 'Second topic', '4', 'S'],
      ['ABC5678', 'Another topic', '3', '3h']
    ]);
  }
  M.examTemplate = examTemplate;
  M.topicTemplate = topicTemplate;

  // ------------------------------------------------------------------
  // Summary numbers for the headline figures
  // ------------------------------------------------------------------

  function summary(project, plan, st) {
    var next = null;
    plan.exams.forEach(function (e) { if (e.day >= st.today && next === null) next = e; });
    var todayMin = 0, todayDone = 0;
    var done = doneMap(project);
    st.todaySessions.forEach(function (se) { todayMin += se.min; if (done[se.id]) todayDone += se.min; });
    var plannedMin = 0, learnMin = 0, reviewMin = 0, paperMin = 0, finalMin = 0;
    plan.sessions.forEach(function (se) {
      plannedMin += se.min;
      if (se.kind === 'learn') learnMin += se.min;
      else if (se.kind === 'review') reviewMin += se.min;
      else if (se.kind === 'paper') paperMin += se.min;
      else finalMin += se.min;
    });
    var capMin = 0;
    plan.days.forEach(function (d) { capMin += d.cap; });
    return {
      next: next ? { id: next.id, code: next.code, name: next.name, day: next.day, daysLeft: next.day - st.today } : null,
      exams: plan.exams.length, topics: plan.topics.length, sessions: plan.sessions.length,
      plannedMin: plannedMin, learnMin: learnMin, reviewMin: reviewMin, paperMin: paperMin, finalMin: finalMin, capMin: capMin,
      todayMin: todayMin, todayDone: todayDone, todayCount: st.todaySessions.length,
      doneMin: st.doneMin, needMin: st.needMin, missedMin: st.missedMin, verdict: st.verdict,
      days: plan.days.length, studyDays: plan.days.filter(function (d) { return d.used > 0; }).length
    };
  }
  M.summary = summary;

  return M;
})();
if (typeof module !== 'undefined' && module.exports) module.exports = ExamSeason;
/* MODEL END */
