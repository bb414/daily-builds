/* MODEL START */
/*
 * Checked by me: the model. Everything that reads, checks and writes lives
 * here, with no access to the page, so Node can test it and the Python
 * companion can be proved to give the same answers.
 *
 * Rules kept so both versions agree exactly: dates are whole day numbers,
 * shares are worked out with Math.floor(x + 0.5), strings are compared by
 * code point (never localeCompare), regular expressions use only ASCII
 * classes (written out, never \w or \d on text that matters) and every
 * piece of text is cleaned first so only plain spaces and newlines remain.
 */
(function (root) {
  'use strict';

  var M = {};
  M.VERSION = 1;
  M.FORMAT = 'checked-by-me project';
  M.MIN_RUN = 4;               // words in a row that count as "kept word for word"
  M.KEPT_SHARE = 85;           // a final sentence is "kept" when this % of its words are kept
  M.EDITED_SHARE = 30;         // ... "edited" from this %, otherwise reworded or your own
  M.PAIR_DICE = 30;            // closest AI sentence must share this % of words to be shown
  M.REWORD_DICE = 50;          // a sentence of your own counts as "reworded" above this
  M.NOTE_COMPARE = 2;          // shared words before a note's figure is compared at all
  M.NOTE_CONFLICT = 3;         // shared words before a different figure counts as a conflict
  M.HIGH = 6;                  // risk score for High
  M.MEDIUM = 3;                // risk score for Medium

  // ---------------------------------------------------------------- basics

  function cmp(a, b) { return a < b ? -1 : (a > b ? 1 : 0); }
  M.cmp = cmp;

  function hasOwn(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }

  // Maps keyed by words from the text have no prototype, so a word like "constructor" is just a word.
  function dict() { return Object.create(null); }

  function utf8(s) {
    var out = [];
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      if (c < 0x80) out.push(c);
      else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
      else out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    }
    return out;
  }

  // FNV-1a over the UTF-8 bytes: a short, stable key for a sentence or a reference.
  function fnv(s) {
    var h = 0x811c9dc5, bytes = utf8(s);
    for (var i = 0; i < bytes.length; i++) {
      h ^= bytes[i];
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    var hex = h.toString(16);
    while (hex.length < 8) hex = '0' + hex;
    return hex;
  }
  M.fnv = fnv;

  function pct(part, whole) { return whole > 0 ? Math.floor(part * 100 / whole + 0.5) : 0; }
  M.pct = pct;

  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
  M.plural = plural;

  function listAnd(items) {
    if (items.length === 0) return '';
    if (items.length === 1) return items[0];
    return items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1];
  }
  M.listAnd = listAnd;

  function trim(s) { return s.replace(/^ +| +$/g, ''); }

  function collapse(s) { return trim(s.replace(/ {2,}/g, ' ')); }

  // ---------------------------------------------------------------- dates (whole day numbers since 1970-01-01)

  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
    'October', 'November', 'December'];
  var MONTH_KEYS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };

  function daysFromCivil(y, m, d) {
    y -= m <= 2 ? 1 : 0;
    var era = Math.floor(y / 400);
    var yoe = y - era * 400;
    var doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1;
    var doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
    return era * 146097 + doe - 719468;
  }
  M.daysFromCivil = daysFromCivil;

  function civilFromDays(z) {
    z += 719468;
    var era = Math.floor(z / 146097);
    var doe = z - era * 146097;
    var yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
    var y = yoe + era * 400;
    var doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
    var mp = Math.floor((5 * doy + 2) / 153);
    var d = doy - Math.floor((153 * mp + 2) / 5) + 1;
    var m = mp + (mp < 10 ? 3 : -9);
    return [y + (m <= 2 ? 1 : 0), m, d];
  }
  M.civilFromDays = civilFromDays;

  function pad(n, w) { var s = String(n); while (s.length < w) s = '0' + s; return s; }

  function isoDay(day) {
    var c = civilFromDays(day);
    return pad(c[0], 4) + '-' + pad(c[1], 2) + '-' + pad(c[2], 2);
  }
  M.isoDay = isoDay;

  function longDay(day) {
    var c = civilFromDays(day);
    return c[2] + ' ' + MONTHS[c[1] - 1] + ' ' + c[0];
  }
  M.longDay = longDay;

  function validDay(y, m, d) {
    if (m < 1 || m > 12 || d < 1 || y < 1000 || y > 2999) return null;
    var dim = [31, (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0 ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if (d > dim[m - 1]) return null;
    return daysFromCivil(y, m, d);
  }

  function monthFrom(word) {
    var w = word.toLowerCase();
    if (w.length < 3) return 0;
    var key = w.slice(0, 3);
    if (!hasOwn(MONTH_KEYS, key)) return 0;
    var full = MONTHS[MONTH_KEYS[key] - 1].toLowerCase();
    if (w !== key && w !== 'sept' && full.indexOf(w) !== 0) return 0;
    return MONTH_KEYS[key];
  }

  // Reads the dates people type: ISO, UK day-first (with / . or -), and written months.
  // Returns {day, note}; day is null when the text is not a date.
  function parseDate(text) {
    var s = trim(String(text || '').replace(/[\n\r\t]/g, ' ').replace(/,/g, ', ').replace(/ {2,}/g, ' '));
    if (s === '') return { day: null, note: null };
    var m = /^([0-9]{4})[-/.]([0-9]{1,2})[-/.]([0-9]{1,2})(?:[T ].*)?$/.exec(s);
    if (m) {
      var d0 = validDay(+m[1], +m[2], +m[3]);
      return d0 === null ? { day: null, note: 'no such date' } : { day: d0, note: null };
    }
    m = /^([0-9]{1,2})[/.-]([0-9]{1,2})[/.-]([0-9]{4}|[0-9]{2})(?:[T ,].*)?$/.exec(s);
    if (m) {
      var a = +m[1], b = +m[2], y = +m[3], note = null;
      if (m[3].length === 2) y = y >= 70 ? 1900 + y : 2000 + y;
      if (b > 12 && a <= 12) { var t = a; a = b; b = t; note = 'read as month first'; }
      var d1 = validDay(y, b, a);
      return d1 === null ? { day: null, note: 'no such date' } : { day: d1, note: note };
    }
    m = /^(?:[A-Za-z]+,? )?([0-9]{1,2})(?:st|nd|rd|th)? ([A-Za-z]+)\.?,? ([0-9]{4})$/.exec(s);
    if (m && monthFrom(m[2])) {
      var d2 = validDay(+m[3], monthFrom(m[2]), +m[1]);
      return d2 === null ? { day: null, note: 'no such date' } : { day: d2, note: null };
    }
    m = /^(?:[A-Za-z]+,? )?([A-Za-z]+)\.? ([0-9]{1,2})(?:st|nd|rd|th)?,? ([0-9]{4})$/.exec(s);
    if (m && monthFrom(m[1])) {
      var d3 = validDay(+m[3], monthFrom(m[1]), +m[2]);
      return d3 === null ? { day: null, note: 'no such date' } : { day: d3, note: null };
    }
    return { day: null, note: 'not a date I can read' };
  }
  M.parseDate = parseDate;

  // ---------------------------------------------------------------- CSV

  function sniffDelimiter(text) {
    var line = '';
    var lines = text.split('\n');
    for (var i = 0; i < lines.length; i++) { if (trim(lines[i]) !== '') { line = lines[i]; break; } }
    var counts = { ',': 0, ';': 0, '\t': 0 }, quoted = false;
    for (var j = 0; j < line.length; j++) {
      var ch = line[j];
      if (ch === '"') quoted = !quoted;
      else if (!quoted && hasOwn(counts, ch)) counts[ch]++;
    }
    var best = ',';
    if (counts[';'] > counts[best]) best = ';';
    if (counts['\t'] > counts[best]) best = '\t';
    return best;
  }

  // RFC 4180 reader: quoted fields, doubled quotes, commas and newlines inside quotes, a byte
  // order mark, CRLF or LF line ends, and comma, semicolon or tab delimiters (sniffed).
  function parseCsv(text) {
    var s = String(text || '');
    if (s.charCodeAt(0) === 0xfeff) s = s.slice(1);
    s = s.replace(/\r\n?/g, '\n');
    var delim = sniffDelimiter(s);
    var rows = [], row = [], cell = '', quoted = false, i = 0, n = s.length;
    while (i < n) {
      var ch = s[i];
      if (quoted) {
        if (ch === '"') {
          if (s[i + 1] === '"') { cell += '"'; i += 2; continue; }
          quoted = false; i++; continue;
        }
        cell += ch; i++; continue;
      }
      if (ch === '"' && trim(cell) === '') { cell = ''; quoted = true; i++; continue; }
      if (ch === delim) { row.push(cell); cell = ''; i++; continue; }
      if (ch === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; i++; continue; }
      cell += ch; i++;
    }
    if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
    return { rows: rows, delimiter: delim };
  }
  M.parseCsv = parseCsv;

  function csvCell(v) {
    var s = v === null || v === undefined ? '' : String(v);
    if (/^[=+@]/.test(s) || /^-[^0-9]/.test(s)) s = "'" + s;
    if (/[",\r\n]/.test(s) || s !== trim(s)) s = '"' + s.replace(/"/g, '""') + '"';
    return s;
  }

  function csvText(header, rows) {
    var lines = [header.map(csvCell).join(',')];
    for (var i = 0; i < rows.length; i++) lines.push(rows[i].map(csvCell).join(','));
    return '\ufeff' + lines.join('\r\n') + '\r\n';
  }
  M.csvText = csvText;

  // ---------------------------------------------------------------- cleaning pasted text

  function cleanChars(raw, counts) {
    var s = String(raw === null || raw === undefined ? '' : raw);
    function count(re, key, repl) {
      s = s.replace(re, function () { counts[key] = (counts[key] || 0) + 1; return repl; });
    }
    s = s.replace(/\r\n?/g, '\n').replace(/[\u2028\u2029]/g, '\n');
    count(/[\ud800-\udbff][\udc00-\udfff]|[\ud800-\udfff]/g, 'symbols', '');
    count(/[\u200b\u200c\u200d\u2060\u00ad\ufeff]/g, 'invisible', '');
    count(/[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]/g, 'spaces', ' ');
    s = s.replace(/[\t\u000b\u000c]/g, ' ');
    s = s.replace(/[\u0000-\u0008\u000e-\u001f\u007f-\u009f]/g, '');
    count(/[\u2018\u2019\u201a\u201b\u2032]/g, 'quotes', "'");
    count(/[\u201c\u201d\u201e\u201f\u2033]/g, 'quotes', '"');
    s = s.replace(/\u2026/g, '...').replace(/\u2212/g, '-');
    count(/\ufb01/g, 'ligatures', 'fi');
    count(/\ufb02/g, 'ligatures', 'fl');
    return s;
  }
  M.cleanChars = cleanChars;

  var SUPERSCRIPTS = { '\u00b9': '1', '\u00b2': '2', '\u00b3': '3', '\u2070': '0', '\u2074': '4', '\u2075': '5',
    '\u2076': '6', '\u2077': '7', '\u2078': '8', '\u2079': '9' };

  function htmlToText(s, counts) {
    if (!/<(?:p|div|br|li|h[1-6]|span|em|strong|b|i|ul|ol|table|tr|td|blockquote|a)(?:[ >/])/i.test(s)) return s;
    counts.html = (counts.html || 0) + 1;
    s = s.replace(/<(?:script|style)[^>]*>[\s\S]*?<\/(?:script|style)>/gi, '');
    s = s.replace(/<br *\/?>/gi, '\n');
    s = s.replace(/<\/?(?:p|div|li|h[1-6]|ul|ol|table|tr|blockquote)(?: [^>]*)?>/gi, '\n\n');
    s = s.replace(/<[^>]+>/g, '');
    s = s.replace(/&nbsp;/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
      .replace(/&#39;|&apos;/g, "'").replace(/&amp;/g, '&');
    return s.replace(/\n{3,}/g, '\n\n');
  }

  function inlineClean(text, counts) {
    var s = text;
    function count(re, repl) {
      s = s.replace(re, function () {
        counts.markdown = (counts.markdown || 0) + 1;
        var args = arguments, out = repl;
        return out.replace(/\$([1-3])/g, function (m0, g) { return args[+g] === undefined ? '' : args[+g]; });
      });
    }
    count(/!\[([^\]]*)\]\([^)]*\)/g, '$1');
    count(/\[([^\]^][^\]]*)\]\(([^)\s]+)\)/g, '$1 ($2)');
    s = s.replace(/\[\^([0-9]+)\]/g, function (m0, g) { counts.footnotes = (counts.footnotes || 0) + 1; return '[' + g + ']'; });
    count(/\*\*([^*\n]+)\*\*/g, '$1');
    count(/__([^_\n]+)__/g, '$1');
    count(/(^|[^A-Za-z0-9*])\*([^*\n]+?)\*(?![A-Za-z0-9*])/g, '$1$2');
    count(/(^|[^A-Za-z0-9_])_([^_\n]+?)_(?![A-Za-z0-9_])/g, '$1$2');
    count(/`([^`\n]+)`/g, '$1');
    count(/~~([^~\n]+)~~/g, '$1');
    count(/<\/?[A-Za-z][^>]*>/g, '');
    return collapse(s);
  }

  var REF_HEADINGS = ['references', 'reference list', 'bibliography', 'works cited', 'sources', 'sources cited',
    'citations', 'further reading', 'literature cited', 'endnotes', 'footnotes', 'notes and references'];

  function isRefHeading(text) {
    var t = trim(text.replace(/[*_#:]/g, '').replace(/ {2,}/g, ' ')).toLowerCase();
    return REF_HEADINGS.indexOf(t) >= 0;
  }
  M.isRefHeading = isRefHeading;

  // Reads pasted text or Markdown into blocks (headings, paragraphs, list items), with the
  // reference section and any footnote definitions set aside, and counts what was tidied.
  function readDocument(raw) {
    var counts = {};
    var s = cleanChars(raw, counts);
    s = htmlToText(s, counts);
    s = s.replace(/([A-Za-z]{3}|[.,;:)\]'"%]|\b(?:1[5-9]|20)[0-9]{2})([\u00b9\u00b2\u00b3\u2070\u2074-\u2079]+)/g, function (m0, before, sup) {
      counts.footnotes = (counts.footnotes || 0) + 1;
      var digits = '';
      for (var i = 0; i < sup.length; i++) digits += SUPERSCRIPTS[sup[i]];
      return before + '[' + digits + ']';
    });
    var lines = s.split('\n');
    var blocks = [], refLines = [], footnotes = [], current = null, inRefs = false, refHeading = '';
    function close() { current = null; }
    for (var li = 0; li < lines.length; li++) {
      var line = trim(lines[li]);
      var fm = /^\[\^?([0-9]+)\]: *(.*)$/.exec(line);
      if (fm) { footnotes.push({ label: fm[1], text: fm[2] }); counts.footnotes = (counts.footnotes || 0) + 1; close(); continue; }
      if (inRefs) { refLines.push(line); continue; }
      if (line === '') { close(); continue; }
      var hm = /^(#{1,6}) +(.*?)(?: +#+)? *$/.exec(line);
      var bm = /^(?:\*\*([^*]+)\*\*|__([^_]+)__):?$/.exec(line);
      var headingText = null, level = 0;
      if (hm) { headingText = hm[2]; level = hm[1].length; counts.markdown = (counts.markdown || 0) + 1; }
      else if (bm) { headingText = bm[1] !== undefined ? bm[1] : bm[2]; level = 9; counts.markdown = (counts.markdown || 0) + 1; }
      else if (isRefHeading(line)) { headingText = line; level = 9; }
      if (headingText !== null) {
        if (isRefHeading(headingText)) { inRefs = true; refHeading = trim(headingText.replace(/[*_:]/g, '')); close(); continue; }
        blocks.push({ kind: 'heading', level: level, text: inlineClean(headingText, counts) });
        close();
        continue;
      }
      if (/^([-*_])(?: *\1){2,}$/.test(line)) { counts.markdown = (counts.markdown || 0) + 1; close(); continue; }
      var quoted = false;
      while (/^> ?/.test(line)) { line = line.replace(/^> ?/, ''); quoted = true; }
      if (quoted) counts.markdown = (counts.markdown || 0) + 1;
      if (/^\|? *:?-{3,}/.test(line) && /^[|:\- ]+$/.test(line)) { counts.markdown = (counts.markdown || 0) + 1; continue; }
      if (/^\|.*\|$/.test(line)) {
        line = line.slice(1, -1).split('|').map(trim).filter(function (c) { return c !== ''; }).join('; ');
        counts.markdown = (counts.markdown || 0) + 1;
      }
      var im = /^(?:[-*+\u2022]|[0-9]{1,3}[.)]) +(.*)$/.exec(line);
      if (im) {
        current = { kind: 'item', level: 0, text: im[1] };
        blocks.push(current);
        counts.markdown = (counts.markdown || 0) + 1;
        continue;
      }
      if (trim(line) === '') { close(); continue; }
      if (current) current.text += ' ' + line;
      else { current = { kind: 'para', level: 0, text: line }; blocks.push(current); }
    }
    var out = [];
    for (var b = 0; b < blocks.length; b++) {
      var text = blocks[b].kind === 'heading' ? blocks[b].text : inlineClean(blocks[b].text, counts);
      if (text !== '') out.push({ kind: blocks[b].kind, level: blocks[b].level, text: text });
    }
    return { blocks: out, refLines: refLines, footnotes: footnotes, refHeading: refHeading, cleaning: counts };
  }
  M.readDocument = readDocument;

  // ---------------------------------------------------------------- sentences and words

  var ABBREV = {};
  ('eg ie etc al dr prof mr mrs ms mx st no nos vol vols pp p fig figs cf vs approx ltd inc co jan feb mar apr jun jul ' +
    'aug sep sept oct nov dec ed eds rev op cit ibid ch sec para est dept univ assn bros jr sr mt ave rd ca c ' +
    'viz resp repr trans govt corp intl natl').split(' ').forEach(function (w) { ABBREV[w] = true; });

  var STARTER = /[A-Z\u00c0-\u00d6\u00d8-\u00de0-9"'(\[]/;

  function splitSentences(text) {
    var out = [], start = 0, i = 0, n = text.length;
    function push(a, b) {
      var piece = trim(text.slice(a, b));
      if (piece !== '') out.push(piece);
    }
    while (i < n) {
      var ch = text[i];
      if (ch === '.' || ch === '!' || ch === '?') {
        var j = i;
        while (j < n && '.!?'.indexOf(text[j]) >= 0) j++;
        var k = j;
        while (k < n && '"\')]'.indexOf(text[k]) >= 0) k++;
        if (k < n && text[k] === ' ') {
          var m = k;
          while (m < n && text[m] === ' ') m++;
          if (m < n && STARTER.test(text[m])) {
            var ok = true;
            if (j - i === 1 && ch === '.') {
              var b = i;
              while (b > 0 && /[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u017f.]/.test(text[b - 1])) b--;
              var word = text.slice(b, i).replace(/\./g, '').toLowerCase();
              if (word.length === 1 || hasOwn(ABBREV, word)) ok = false;
            }
            if (ok) { push(start, k); start = m; i = m; continue; }
          }
        }
        i = k > i ? k : i + 1;
        continue;
      }
      i++;
    }
    push(start, n);
    return out;
  }
  M.splitSentences = splitSentences;

  var WORD_RE = /[0-9]+(?:[.,][0-9]+)*|[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u017f]+(?:'[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u017f]+)*/g;

  function words(text) {
    var out = [], m;
    WORD_RE.lastIndex = 0;
    while ((m = WORD_RE.exec(text)) !== null) out.push(m[0].toLowerCase());
    return out;
  }
  M.words = words;

  function stripAccents(s) { return s.normalize('NFD').replace(/[\u0300-\u036f]/g, ''); }

  var STOP = {};
  ('a an the and or but if of to in on at by for with from as is are was were be been being it its this that these ' +
    'those there their they them then than so such not no nor can could would should will shall may might must do ' +
    'does did has have had having which who whom whose what when where why how all any each few more most other some ' +
    'own same too very just also into over under about after before between through during while because until ' +
    'again further once here both only our ours your yours his her hers him she he we you i me my us one per via ' +
    'up down out off above below said says').split(' ').forEach(function (w) { STOP[w] = true; });

  function stem(w) {
    if (w.length > 2 && w.slice(-2) === "'s") w = w.slice(0, -2);
    if (w.length > 4 && w.slice(-3) === 'ies') return w.slice(0, -3) + 'y';
    if (w.length > 4 && (w.slice(-4) === 'ches' || w.slice(-4) === 'shes' || w.slice(-3) === 'ses' || w.slice(-3) === 'xes' || w.slice(-3) === 'zes')) return w.slice(0, -2);
    if (w.length > 3 && w.slice(-1) === 's' && w.slice(-2) !== 'ss' && w.slice(-2) !== 'us' && w.slice(-2) !== 'is') return w.slice(0, -1);
    return w;
  }
  M.stem = stem;

  // Content words: lower case, no accents, no stop words or numbers, lightly stemmed.
  function contentWords(text) {
    var seen = dict(), out = [];
    var ws = words(stripAccents(text));
    for (var i = 0; i < ws.length; i++) {
      var w = ws[i];
      if (/^[0-9]/.test(w) || w.length < 3 || hasOwn(STOP, w)) continue;
      w = stem(w);
      if (!hasOwn(seen, w)) { seen[w] = true; out.push(w); }
    }
    return out;
  }
  M.contentWords = contentWords;

  // ---------------------------------------------------------------- spans: citations, links, figures

  var YEAR = '(?:1[5-9][0-9]{2}|20[0-9]{2})';
  var CAP = 'A-Z\u00c0-\u00d6\u00d8-\u00de';
  var LET = 'A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u00ff';
  var PAREN_RE = /\(([^()]*)\)/g;
  var PIECE_YEAR_RE = new RegExp('(?:^|[ ,])(' + YEAR + '[a-z]?|n\\.d\\.)(?=$|[ ,;:])');
  var NARR_RE = new RegExp('([' + CAP + '][' + LET + "'\\-]+(?: (?:et al\\.?|and [" + CAP + '][' + LET + "'\\-]+|& [" + CAP + '][' + LET + "'\\-]+))?) \\((" + YEAR + '[a-z]?|n\\.d\\.)(?:, (pp?\\. ?[0-9]+(?:[-\u2013][0-9]+)?))?\\)', 'g');
  var NUM_CIT_RE = /\[([0-9]{1,3}(?: *[-\u2013,] *[0-9]{1,3})*)\]/g;
  var PANDOC_RE = /\[(-?@[A-Za-z0-9_][^\]]*)\]/g;
  var LATEX_CITE_RE = /\\(?:cite|citep|citet|parencite|textcite|autocite)\*?(?:\[[^\]]*\]){0,2}\{([^}]+)\}/g;
  var NOT_AUTHOR = { 'in': 1, 'since': 1, 'from': 1, 'by': 1, 'until': 1, 'before': 1, 'after': 1, 'see': 1, 'circa': 1, 'around': 1 };

  function citationPiece(piece) {
    var p = trim(piece.replace(/^(?:see also|see|e\.g\.,?|cf\.|as cited in) +/i, ''));
    var m = PIECE_YEAR_RE.exec(p);
    if (!m) return null;
    var yearStart = m.index + m[0].indexOf(m[1]);
    var authors = trim(p.slice(0, yearStart).replace(/[ ,]+$/, ''));
    var rest = trim(p.slice(yearStart + m[1].length).replace(/^[ ,]+/, ''));
    if (authors === '' || !new RegExp('^[' + CAP + ']').test(authors)) return null;
    if (authors.split(' ').length > 9) return null;
    if (hasOwn(NOT_AUTHOR, authors.split(' ')[0].toLowerCase())) return null;
    var page = /^(?:pp?\.|page|pages) ?[0-9]+(?: ?[-\u2013] ?[0-9]+)?$/.test(rest) ? rest : '';
    return { authors: authors, year: m[1], page: page };
  }

  function findCitations(text) {
    var out = [], m;
    PAREN_RE.lastIndex = 0;
    while ((m = PAREN_RE.exec(text)) !== null) {
      var pieces = m[1].split(';'), found = [];
      for (var i = 0; i < pieces.length; i++) {
        var c = citationPiece(pieces[i]);
        if (c) found.push(c);
      }
      if (found.length) {
        for (var f = 0; f < found.length; f++) {
          out.push({ kind: 'author-year', text: m[0], start: m.index, end: m.index + m[0].length,
            authors: found[f].authors, year: found[f].year, page: found[f].page, labels: [] });
        }
      }
    }
    NARR_RE.lastIndex = 0;
    while ((m = NARR_RE.exec(text)) !== null) {
      var first = m[1].split(' ')[0].toLowerCase();
      if (hasOwn(NOT_AUTHOR, first)) continue;
      var overlaps = false;
      for (var o = 0; o < out.length; o++) {
        if (m.index < out[o].end && m.index + m[0].length > out[o].start) overlaps = true;
      }
      if (!overlaps) {
        out.push({ kind: 'author-year', text: m[0], start: m.index, end: m.index + m[0].length,
          authors: m[1], year: m[2], page: m[3] || '', labels: [] });
      }
    }
    NUM_CIT_RE.lastIndex = 0;
    while ((m = NUM_CIT_RE.exec(text)) !== null) {
      var labels = [], parts = m[1].replace(/ /g, '').split(',');
      for (var p = 0; p < parts.length; p++) {
        var r = /^([0-9]+)[-\u2013]([0-9]+)$/.exec(parts[p]);
        if (r && +r[2] >= +r[1] && +r[2] - +r[1] <= 50) {
          for (var x = +r[1]; x <= +r[2]; x++) labels.push(String(x));
        } else if (/^[0-9]+$/.test(parts[p])) labels.push(String(+parts[p]));
      }
      if (labels.length) out.push({ kind: 'numeric', text: m[0], start: m.index, end: m.index + m[0].length, authors: '', year: '', page: '', labels: labels });
    }
    // citation keys from Pandoc Markdown ([@key; @other, p. 4]) and LaTeX (\cite{key,other})
    var keyRes = [[PANDOC_RE, ';', /^ *-?@([A-Za-z0-9_:.\-]*[A-Za-z0-9_])/], [LATEX_CITE_RE, ',', /^ *([A-Za-z0-9_:.\-]+)/]];
    for (var kr = 0; kr < keyRes.length; kr++) {
      keyRes[kr][0].lastIndex = 0;
      while ((m = keyRes[kr][0].exec(text)) !== null) {
        var keys = [], pieces = m[1].split(keyRes[kr][1]);
        for (var q = 0; q < pieces.length; q++) {
          var km = keyRes[kr][2].exec(pieces[q]);
          if (km && keys.indexOf(km[1]) < 0) keys.push(km[1]);
        }
        if (keys.length) out.push({ kind: 'key', text: m[0], start: m.index, end: m.index + m[0].length, authors: '', year: '', page: '', labels: keys });
      }
    }
    out.sort(function (a, b) { return a.start - b.start || a.end - b.end; });
    return out;
  }
  M.findCitations = findCitations;

  var URL_RE = /\b(?:https?|htps?|hhtps?|http)(?::\/\/|:\/|\/\/)[^ <>"()]+|\bwww\.[^ <>"()]+|\b10\.[0-9]{4,9}\/[^ <>"()]+|\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:com|org|net|gov|edu|ac|io|co|uk|info)(?:\.[a-z]{2})?\/[^ <>"()]*/gi;

  function findUrls(text) {
    var out = [], m;
    URL_RE.lastIndex = 0;
    while ((m = URL_RE.exec(text)) !== null) {
      var t = m[0].replace(/[.,;:!?']+$/, '');
      out.push({ start: m.index, end: m.index + t.length, text: t });
    }
    return out;
  }
  M.findUrls = findUrls;

  function inside(spans, a, b) {
    for (var i = 0; i < spans.length; i++) if (a < spans[i].end && b > spans[i].start) return true;
    return false;
  }

  var MONEY_RE = /([\u00a3$\u20ac]) ?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)(?: ?(k|m|bn|million|billion|thousand)\b)?/g;
  var PCT_RE = /\b([0-9]+(?:\.[0-9]+)?) ?(%|per ?cent\b)/g;
  var YEAR_RE = new RegExp('\\b(' + YEAR + ')\\b(?![%,.]?[0-9])', 'g');
  var NUM_RE = /\b([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\b/g;
  var UNIT_RE = /^[ -]*([A-Za-z\u00c0-\u00ff]+)/;

  function normNumber(v) {
    var s = v.replace(/,/g, '');
    if (s.indexOf('.') >= 0) s = s.replace(/0+$/, '').replace(/\.$/, '');
    return s;
  }

  // Figures in a sentence: amounts of money, percentages, years and other numbers with the
  // word after them as the unit. Spans to skip (citations, links) are passed in.
  function findFacts(text, skip) {
    var taken = skip.slice(), out = [], m;
    function add(cls, start, end, value, unit) {
      if (inside(taken, start, end)) return;
      taken.push({ start: start, end: end });
      out.push({ cls: cls, start: start, end: end, text: text.slice(start, end), value: value, unit: unit });
    }
    MONEY_RE.lastIndex = 0;
    while ((m = MONEY_RE.exec(text)) !== null) {
      add('money', m.index, m.index + m[0].length, m[1] + normNumber(m[2]) + (m[3] ? m[3].toLowerCase() : ''), '');
    }
    PCT_RE.lastIndex = 0;
    while ((m = PCT_RE.exec(text)) !== null) add('pct', m.index, m.index + m[0].length, normNumber(m[1]), '');
    YEAR_RE.lastIndex = 0;
    while ((m = YEAR_RE.exec(text)) !== null) {
      var before = text.slice(Math.max(0, m.index - 1), m.index);
      if (/[\u00a3$\u20ac.,]/.test(before)) continue;
      add('year', m.index, m.index + m[0].length, m[1], '');
    }
    NUM_RE.lastIndex = 0;
    while ((m = NUM_RE.exec(text)) !== null) {
      var prev = text.slice(Math.max(0, m.index - 1), m.index);
      if (/[A-Za-z\u00a3$\u20ac]/.test(prev)) continue;
      var um = UNIT_RE.exec(text.slice(m.index + m[0].length));
      var unit = um ? stem(stripAccents(um[1].toLowerCase())) : '';
      var end = m.index + m[0].length;
      if (hasOwn(STOP, unit)) {
        var rest = text.slice(m.index + m[0].length + um[0].length);
        var um2 = UNIT_RE.exec(rest);
        unit = um2 ? stem(stripAccents(um2[1].toLowerCase())) : '';
      } else if (um) end += um[0].length;
      add('num', m.index, end, normNumber(m[1]), unit);
    }
    out.sort(function (a, b) { return a.start - b.start; });
    return out;
  }
  M.findFacts = findFacts;

  var QUOTE_D_RE = /"([^"\n]{3,}?)"/g;
  var QUOTE_S_RE = /(^|[ (\[])'([^'\n]{3,}?)'(?=$|[ .,;:!?)\]])/g;

  function findQuotes(text) {
    var out = [], m;
    QUOTE_D_RE.lastIndex = 0;
    while ((m = QUOTE_D_RE.exec(text)) !== null) {
      if (trim(m[1]).split(/ +/).length >= 4) out.push({ start: m.index, end: m.index + m[0].length, text: m[1] });
    }
    QUOTE_S_RE.lastIndex = 0;
    while ((m = QUOTE_S_RE.exec(text)) !== null) {
      var s = m.index + m[1].length;
      if (trim(m[2]).split(/ +/).length >= 4 && !inside(out, s, s + m[2].length + 2)) out.push({ start: s, end: s + m[2].length + 2, text: m[2] });
    }
    out.sort(function (a, b) { return a.start - b.start; });
    return out;
  }
  M.findQuotes = findQuotes;

  // ---------------------------------------------------------------- what makes a sentence worth checking

  var LEFTOVER_RES = [
    /\bas an ai\b/gi,
    /\bas a(?:n ai)? language model\b/gi,
    /\bas of my (?:last|latest|most recent) (?:update|training|knowledge)\b/gi,
    /\bknowledge cut-?off\b/gi,
    /\bi (?:hope|trust) (?:this|that) helps\b/gi,
    /\blet me know if you(?:'d| would) like (?:me to|a |an |any |another|more|further)|\blet me know if (?:you need )?any (?:further |other |more )?(?:changes|adjustments|edits|tweaks|revisions)\b/gi,
    /^(?:sure|certainly|of course|absolutely|great question)!/gi,
    /^(?:sure|certainly|absolutely|of course)[,.]? (?:here|i can|i'll|i will|let me|below)\b/gi,
    /\bhere(?:'s| is) (?:a|an|the|your) (?:[a-z-]+ ){0,3}(?:version|draft|rewrite|revision|summary|essay|section|paragraph|outline)\b/gi,
    /\[(?:insert|add|citation needed|source|sources|author|year|reference|ref|todo|tbc|tbd|name|date)\b[^\]]*\]/gi,
    /\((?:author|source),? (?:year|date)\)/gi,
    /\bxx+(?:\.x+)? ?%/gi,
    /\blorem ipsum\b/gi,
    /\bregenerate(?: response)?\b/gi,
    /\bi (?:cannot|can't|am unable to|don't have the ability to) (?:browse|access|search)\b/gi,
    /\bi don't have access to (?:real-time|current|the internet)\b/gi,
    /\b(?:do you want|would you like) me to (?:expand|shorten|rewrite|revise|adjust|add|make|create|draft|write|tailor|format|summari[sz]e|tweak|continue)\b/gi
  ];
  var ABSOLUTE_RE = /\b(?:always|never|every|everyone|everybody|nobody|no one|entirely|completely|totally|undoubtedly|unquestionably|definitely|certainly|clearly|obviously|proven|proves|prove|guarantees?|guaranteed|without exception|universally|unprecedented|beyond doubt|the (?:first|only|single most|most|best|worst|largest|biggest|smallest|highest|lowest|greatest|fastest|leading))\b/gi;
  var VAGUE_RE = /\b(?:studies|research|evidence|data|surveys|experts|scientists|researchers|economists|analysts)(?: (?:have|has))? (?:show|shows|shown|suggest|suggests|suggested|prove|proves|proven|agree|agrees|indicate|indicates|confirm|confirms|say|says|believe|believes|found)\b|\bit is (?:widely|generally|commonly|well) (?:known|accepted|believed|agreed|established)\b|\b(?:many|most|some) (?:studies|experts|researchers|scientists|people) (?:say|believe|agree|argue|suggest|have found)\b|\baccording to (?:experts|research|studies|many|some|scientists)\b/gi;
  var STUDY_NOUN_RE = /\b(?:study|studies|survey|surveys|report|reports|trial|trials|experiment|experiments|meta-analysis|poll|census|paper|research|review|analysis|evaluation)\b/gi;
  var STUDY_VERB_RE = /\b(?:found|finds|find|showed|shows|show|concluded|concludes|reported|reports|revealed|reveals|estimated|estimates|according to|suggests|suggested|predicts|predicted|argues|argued|recorded|records|measured)\b/i;
  var PERSON_TITLE_RE = new RegExp('\\b(?:Dr|Prof|Professor|Sir|Dame|Lord|Lady|Mr|Mrs|Ms|Mx|Baroness|Judge|Justice)\\.? [' + CAP + "][a-z\u00e0-\u00ff'\\-]+(?: [" + CAP + "][a-z\u00e0-\u00ff'\\-]+)?", 'g');
  var PERSON_SAID_RE = new RegExp('\\b([' + CAP + "][a-z\u00e0-\u00ff'\\-]+ [" + CAP + "][a-z\u00e0-\u00ff'\\-]+),? (?:said|says|argued|argues|wrote|writes|claimed|claims|noted|notes|observed|observes|stated|states|told|explained|explains|warned|warns|added|put it)\\b", 'g');
  var CAPRUN_RE = new RegExp('[' + CAP + '][' + LET + "'&\\-]*(?:(?: (?:of|for|and|the|on|&))* [" + CAP + '][' + LET + "'&\\-]*)*", 'g');
  var ORG_WORDS = {};
  ('University Institute Council Agency Department Ministry Office Commission Foundation Trust Society Association ' +
    'Network Group Bank Board Authority Centre Center College School Hospital Committee Federation Union Partnership ' +
    'Corporation Company Ltd plc Inc LLP Organisation Organization Service Services Unit Lab Laboratory Forum Alliance ' +
    'Coalition Press Party Fund Bureau Court Parliament Government Observatory Consortium Collective').split(' ').forEach(function (w) { ORG_WORDS[w] = true; });
  var ACRONYM_RE = /\b[A-Z]{2,6}s?\b/g;
  var ACRONYM_STOP = {};
  ('UK US USA EU AI OK TV PC CEO GB NB AM PM ID HR PR UN IT FAQ PDF CV MSc BSc BA MA PhD GCSE OR AND THE PS ' +
    'LGBT DIY USB UKs').split(' ').forEach(function (w) { ACRONYM_STOP[w] = true; });
  var DATE_RES = [
    /\b(?:1[5-9]|20)[0-9]0s\b/g,
    /\b(?:1[5-9]|2[01])(?:st|nd|rd|th) century\b/gi,
    /\b[0-9]{1,2}(?:st|nd|rd|th)? (?:January|February|March|April|May|June|July|August|September|October|November|December) (?:1[5-9]|20)[0-9]{2}\b/g,
    /\b(?:January|February|March|April|May|June|July|August|September|October|November|December) (?:1[5-9]|20)[0-9]{2}\b/g,
    /\b(?:recently|currently|nowadays|at present|to date|this year|last year|next year|in recent years|as of (?:now|today)|the latest|so far)\b/gi
  ];
  var STAT_WORDS_RE = /\b(?:twice|double|doubled|doubling|triple|tripled|halved|quadrupled|(?:one|two|three|four|five|six|seven|eight|nine|ten) in (?:two|three|four|five|six|seven|eight|nine|ten|[0-9]+)|[0-9]+(?:\.[0-9]+)? ?(?:times|-fold|fold)|the majority|a minority|(?:half|a third|a quarter|two thirds|three quarters) of)\b/gi;
  var LEGAL_RE = /\b(?:law|laws|legal|legally|illegal|illegally|unlawful|lawful|liable|liability|regulations?|statute|statutory|courts?|tribunal|contracts?|contractual|gdpr|copyright|trademarks?|patents?|licen[cs]es?|lawsuits?|sued?|prosecut[a-z]*|criminal|offences?|offenses?|obliged|obligations?|compliance|comply|complies|data controller|data protection|rights|required by law)\b/gi;
  var ACT_RE = /\b[A-Z][a-z]+ Act\b/g;
  var MEDICAL_RE = /\b(?:health|healthy|unhealthy|disease|diseases|illness|symptoms?|diagnos[a-z]*|treatments?|cures?|cured|therapy|therapies|medication|medicines?|medical|doses?|dosage|mg|vaccines?|harmless|toxic|toxins?|carcinogen[a-z]*|side effects?|clinical|patients?|mental health|anxiety|depression|cancer|lungs?|injur[a-z]*|allerg[a-z]*|fumes|poison[a-z]*|infection|safe to (?:eat|drink|use|take|breathe))\b/gi;
  var FINANCE_RE = /\b(?:tax|taxes|vat|interest rates?|apr|investments?|invest|investing|investors?|returns|pensions?|mortgages?|loans?|credit|debts?|inflation|salary|salaries|wages?|income|profits?|revenues?|dividends?|shares|stock market|stocks|savings|insurance|premiums?|fees?|tariffs?|budgets?)\b/gi;
  var HEDGE_RE = /\b(?:may|might|could|possibly|perhaps|suggests?|appears?|likely|around|about|approximately|roughly|estimated|up to|nearly|almost)\b/gi;

  function allMatches(re, text) {
    var out = [], m;
    re.lastIndex = 0;
    while ((m = re.exec(text)) !== null) {
      out.push({ start: m.index, end: m.index + m[0].length, text: m[0] });
      if (m[0].length === 0) re.lastIndex++;
    }
    return out;
  }

  function findOrgs(text) {
    var out = [], m;
    CAPRUN_RE.lastIndex = 0;
    while ((m = CAPRUN_RE.exec(text)) !== null) {
      var toks = m[0].split(' '), offs = [], pos = m.index;
      for (var t = 0; t < toks.length; t++) { offs.push(pos); pos += toks[t].length + 1; }
      for (var k = 0; k < toks.length; k++) {
        if (!hasOwn(ORG_WORDS, toks[k])) continue;
        var a = k;
        while (a > 0 && /^[A-Z\u00c0-\u00de]/.test(toks[a - 1]) && toks[a - 1] !== 'The' && toks[a - 1] !== '&') a--;
        if (a < k && (toks[a] === 'In' || toks[a] === 'As' || toks[a] === 'At' || toks[a] === 'According' || toks[a] === 'By' || toks[a] === 'From')) a++;
        var b = k;
        while (b + 2 < toks.length && (toks[b + 1] === 'of' || toks[b + 1] === 'for') && /^[A-Z\u00c0-\u00de]/.test(toks[b + 2])) {
          b += 2;
          while (b + 1 < toks.length && /^[A-Z\u00c0-\u00de]/.test(toks[b + 1])) b++;
        }
        var start = offs[a], end = offs[b] + toks[b].length;
        if (!inside(out, start, end)) out.push({ start: start, end: end, text: text.slice(start, end) });
        k = b;
      }
    }
    ACRONYM_RE.lastIndex = 0;
    while ((m = ACRONYM_RE.exec(text)) !== null) {
      if (hasOwn(ACRONYM_STOP, m[0]) || inside(out, m.index, m.index + m[0].length)) continue;
      out.push({ start: m.index, end: m.index + m[0].length, text: m[0] });
    }
    out.sort(function (x, y) { return x.start - y.start; });
    return out;
  }
  M.findOrgs = findOrgs;

  function uniqTexts(spans) {
    var seen = dict(), out = [];
    for (var i = 0; i < spans.length; i++) {
      var t = spans[i].text;
      var k = t.toLowerCase();
      if (!hasOwn(seen, k)) { seen[k] = true; out.push(t); }
    }
    return out;
  }

  function quoteList(items, max) {
    var shown = items.slice(0, max || 4).map(function (t) { return '"' + t + '"'; });
    if (items.length > (max || 4)) shown.push('and ' + (items.length - (max || 4)) + ' more');
    return listAnd(shown);
  }

  M.KIND_LABELS = {
    leftover: 'AI leftover', statistic: 'Statistic', date: 'Date', study: 'Study or report', vague: 'Vague source',
    person: 'Person', org: 'Organisation', quote: 'Quotation', citation: 'Citation', url: 'Link or DOI',
    absolute: 'Absolute wording', legal: 'Legal', medical: 'Health', financial: 'Money'
  };
  M.KIND_ORDER = ['leftover', 'statistic', 'quote', 'citation', 'study', 'vague', 'person', 'org', 'date', 'url',
    'absolute', 'legal', 'medical', 'financial'];

  // Everything checkable in one sentence: the spans to mark and the kinds found.
  function scanSentence(text) {
    var citations = findCitations(text);
    var urls = findUrls(text);
    var skip = citations.concat(urls);
    var facts = findFacts(text, skip);
    var spans = [], kinds = {};
    function mark(kind, list) {
      for (var i = 0; i < list.length; i++) spans.push({ start: list[i].start, end: list[i].end, kind: kind, text: list[i].text });
      if (list.length) kinds[kind] = list;
    }
    var leftovers = [];
    for (var l = 0; l < LEFTOVER_RES.length; l++) leftovers = leftovers.concat(allMatches(LEFTOVER_RES[l], text));
    leftovers.sort(function (a, b) { return a.start - b.start || a.end - b.end; });
    mark('leftover', leftovers);
    var stats = facts.filter(function (f) { return f.cls !== 'year'; });
    var statWords = allMatches(STAT_WORDS_RE, text).filter(function (s) { return !inside(skip, s.start, s.end) && !inside(stats, s.start, s.end); });
    mark('statistic', stats.concat(statWords).sort(function (a, b) { return a.start - b.start; }));
    var dates = facts.filter(function (f) { return f.cls === 'year'; });
    for (var d = 0; d < DATE_RES.length; d++) {
      var found = allMatches(DATE_RES[d], text);
      for (var e = 0; e < found.length; e++) {
        if (!inside(skip, found[e].start, found[e].end) && !inside(dates, found[e].start, found[e].end)) dates.push(found[e]);
      }
    }
    mark('date', dates.filter(function (x, i) {
      for (var j = 0; j < dates.length; j++) {
        if (j !== i && dates[j].start <= x.start && dates[j].end >= x.end && (dates[j].end - dates[j].start) > (x.end - x.start)) return false;
      }
      return true;
    }).sort(function (a, b) { return a.start - b.start; }));
    var vague = allMatches(VAGUE_RE, text);
    mark('vague', vague);
    if (!vague.length && STUDY_VERB_RE.test(text)) mark('study', allMatches(STUDY_NOUN_RE, text).filter(function (s) { return !inside(skip, s.start, s.end); }).slice(0, 1));
    var people = allMatches(PERSON_TITLE_RE, text);
    var said = [], m;
    PERSON_SAID_RE.lastIndex = 0;
    while ((m = PERSON_SAID_RE.exec(text)) !== null) {
      if (m[1].split(' ').some(function (w) { return hasOwn(ORG_WORDS, w); })) continue;
      if (!inside(people, m.index, m.index + m[1].length)) said.push({ start: m.index, end: m.index + m[1].length, text: m[1] });
    }
    mark('person', people.concat(said).sort(function (a, b) { return a.start - b.start; }));
    mark('org', findOrgs(text).filter(function (o) { return !inside(skip, o.start, o.end) && !inside(spans.filter(function (s) { return s.kind === 'person'; }), o.start, o.end); }));
    mark('quote', findQuotes(text));
    mark('citation', citations);
    mark('url', urls);
    mark('absolute', allMatches(ABSOLUTE_RE, text).filter(function (s) { return !inside(leftovers, s.start, s.end); }));
    mark('legal', allMatches(LEGAL_RE, text).concat(allMatches(ACT_RE, text)).sort(function (a, b) { return a.start - b.start; }));
    mark('medical', allMatches(MEDICAL_RE, text));
    var money = facts.filter(function (f) { return f.cls === 'money'; });
    var fin = allMatches(FINANCE_RE, text);
    mark('financial', fin.length || money.length ? fin.concat(money.filter(function (x) { return !inside(fin, x.start, x.end); })).sort(function (a, b) { return a.start - b.start; }) : []);
    spans.sort(function (a, b) { return a.start - b.start || b.end - a.end || cmp(a.kind, b.kind); });
    return { spans: spans, kinds: kinds, facts: facts, citations: citations, urls: urls,
      quotes: kinds.quote || [], hedges: allMatches(HEDGE_RE, text) };
  }
  M.scanSentence = scanSentence;

  // ---------------------------------------------------------------- your notes

  function notesIndex(text) {
    var doc = readDocument(text || '');
    var out = [], heading = [];
    for (var b = 0; b < doc.blocks.length; b++) {
      var block = doc.blocks[b];
      if (block.kind === 'heading') heading = contentWords(block.text);
      var parts = block.kind === 'heading' ? [block.text] : splitSentences(block.text);
      for (var p = 0; p < parts.length; p++) {
        var cits = findCitations(parts[p]);
        out.push({ text: parts[p], words: contentWords(parts[p]), heading: block.kind === 'heading' ? [] : heading.slice(),
          facts: findFacts(parts[p], findUrls(parts[p])), quotes: findQuotes(parts[p]), citations: cits });
      }
    }
    return out;
  }
  M.notesIndex = notesIndex;

  function overlap(claimWords, note) {
    var have = dict(), n = 0;
    for (var i = 0; i < note.words.length; i++) have[note.words[i]] = true;
    for (var j = 0; j < note.heading.length; j++) have[note.heading[j]] = true;
    for (var k = 0; k < claimWords.length; k++) if (hasOwn(have, claimWords[k])) n++;
    return n;
  }

  function quoteWords(text) { return words(stripAccents(text)).map(stem); }

  function diceOf(a, b) {
    var counts = dict(), inter = 0;
    for (var i = 0; i < a.length; i++) counts[a[i]] = (counts[a[i]] || 0) + 1;
    for (var j = 0; j < b.length; j++) if (counts[b[j]] > 0) { counts[b[j]]--; inter++; }
    return { inter: inter, total: a.length + b.length };
  }

  // Compares one sentence's figures and quotations with your notes.
  function compareNotes(sentence, scan, notes) {
    var result = { status: 'none', items: [], related: '' };
    if (!notes || !notes.length) return result;
    var cw = contentWords(sentence);
    for (var f = 0; f < scan.facts.length; f++) {
      var fact = scan.facts[f];
      var match = null, matchOv = -1, best = null, bestFact = null, bestOv = -1;
      for (var s = 0; s < notes.length; s++) {
        var note = notes[s];
        for (var g = 0; g < note.facts.length; g++) {
          var nf = note.facts[g];
          if (nf.cls !== fact.cls || (fact.cls === 'num' && nf.unit !== fact.unit)) continue;
          var ov = overlap(cw, note);
          if (ov < M.NOTE_COMPARE) continue;
          if (nf.value === fact.value) { if (ov > matchOv) { match = note; matchOv = ov; } }
          else if (ov > bestOv) { best = note; bestFact = nf; bestOv = ov; }
        }
      }
      if (match) result.items.push({ what: fact.text, result: 'match', note: match.text, noted: '' });
      else if (best && bestOv >= M.NOTE_CONFLICT) result.items.push({ what: fact.text, result: 'conflict', note: best.text, noted: bestFact.text });
      else result.items.push({ what: fact.text, result: 'missing', note: '', noted: '' });
    }
    for (var q = 0; q < scan.quotes.length; q++) {
      var qw = quoteWords(scan.quotes[q].text), same = null, near = null, nearScore = null;
      for (var n = 0; n < notes.length; n++) {
        for (var r = 0; r < notes[n].quotes.length; r++) {
          var nw = quoteWords(notes[n].quotes[r].text);
          if (nw.join(' ') === qw.join(' ')) { if (!same) same = notes[n]; continue; }
          var dc = diceOf(qw, nw);
          if (dc.inter * 2 * 10 >= 4 * dc.total && (!nearScore || dc.inter * nearScore.total > nearScore.inter * dc.total)) {
            near = notes[n].quotes[r]; nearScore = dc;
          }
        }
      }
      if (same) result.items.push({ what: 'the quotation', result: 'match', note: same.text, noted: '' });
      else if (near) result.items.push({ what: 'the quotation', result: 'conflict', note: near.text, noted: '"' + near.text + '"' });
      else result.items.push({ what: 'the quotation', result: 'missing', note: '', noted: '' });
    }
    var counts = { match: 0, conflict: 0, missing: 0 };
    for (var i = 0; i < result.items.length; i++) counts[result.items[i].result]++;
    if (counts.conflict) result.status = 'conflict';
    else if (counts.match && !counts.missing) result.status = 'match';
    else if (counts.match) result.status = 'partial';
    else if (counts.missing) result.status = 'missing';
    if (result.status === 'none' || result.status === 'missing') {
      var bestRel = null, relOv = 2;
      for (var t = 0; t < notes.length; t++) {
        var o = overlap(cw, notes[t]);
        if (o > relOv) { bestRel = notes[t]; relOv = o; }
      }
      if (bestRel) {
        result.related = bestRel.text;
        if (result.status === 'none') result.status = 'related';
      }
    }
    return result;
  }
  M.compareNotes = compareNotes;

  // ---------------------------------------------------------------- the claims checklist

  var PROMPT_SOURCES_RE = /\b(?:references?|citations?|cite|sources?|bibliography|harvard|apa|mla|footnotes?)\b/i;
  var PROMPT_STATS_RE = /\b(?:statistics?|stats|figures|numbers|data|percentages?)\b/i;
  var PROMPT_QUOTES_RE = /\b(?:quotes?|quotations?|quoting)\b/i;

  function readPrompt(text) {
    var doc = readDocument(text || '');
    var all = doc.blocks.map(function (b) { return b.text; }).join(' ');
    var ws = trim(all).split(/ +/).filter(function (w) { return w !== ''; });
    var summary = ws.slice(0, 30).join(' ') + (ws.length > 30 ? ' ...' : '');
    return { given: ws.length > 0, words: ws.length, summary: summary,
      asksSources: PROMPT_SOURCES_RE.test(all), asksStats: PROMPT_STATS_RE.test(all), asksQuotes: PROMPT_QUOTES_RE.test(all) };
  }
  M.readPrompt = readPrompt;

  function sentenceKey(text) { return 'q' + fnv(words(text).join(' ')); }
  M.sentenceKey = sentenceKey;

  function levelOf(score) { return score >= M.HIGH ? 'high' : (score >= M.MEDIUM ? 'medium' : 'low'); }
  M.levelOf = levelOf;

  function checksFor(kinds, scan) {
    var out = [];
    function texts(k) { return uniqTexts(kinds[k] || []); }
    if (kinds.leftover) out.push('Delete or replace ' + quoteList(texts('leftover'), 2) + ': it is the AI tool talking, not part of your work.');
    if (kinds.statistic) out.push('Find where ' + quoteList(texts('statistic')) + (texts('statistic').length === 1 ? ' comes' : ' come') + ' from and check the number, the unit, the year and who it covers.');
    if (kinds.quote) out.push('Find the exact quotation in the original, with its page number.');
    if (kinds.citation) out.push('Open ' + quoteList(texts('citation'), 3) + (texts('citation').length === 1 ? ' and check it really supports' : ' and check they really support') + ' this sentence.');
    if (kinds.study) out.push('Find the study or report itself, not a summary of it, and check it says this.');
    if (kinds.vague) out.push('Name the source behind ' + quoteList(texts('vague'), 2) + ', or cut the appeal to it.');
    if (kinds.person) out.push('Check ' + quoteList(texts('person'), 3) + (texts('person').length === 1 ? ' exists, holds that role and said or wrote this.' : ' exist, hold those roles and said or wrote this.'));
    if (kinds.org) out.push('Check the exact name of ' + quoteList(texts('org'), 3) + '.');
    if (kinds.date) out.push('Check the date' + (texts('date').length > 1 ? 's ' : ' ') + quoteList(texts('date')) + '.');
    if (kinds.url) out.push('Open ' + quoteList(texts('url'), 2) + ' yourself and check it loads and says this.');
    if (kinds.absolute) out.push('Soften ' + quoteList(texts('absolute'), 3) + ' or find a source strong enough to back it.');
    if (kinds.legal) out.push('Check the legal point against an authoritative source for the right country, and take advice where it matters.');
    if (kinds.medical) out.push('Check the health or safety point against an authoritative clinical or safety source.');
    if (kinds.financial) out.push('Check the money figures and rules against an authoritative source for the right year.');
    return out;
  }

  // Points each reason adds to a statement's risk score (High from 6, Medium from 3).
  var W = {
    'leftover': 6,
    'statistic': 3,
    'quote': 3,
    'vague': 3,
    'legal': 3,
    'medical': 3,
    'financial': 3,
    'study': 2,
    'person': 2,
    'url': 2,
    'absolute': 2,
    'org': 1,
    'date': 1,
    'citation': 1,
    'unsourced': 2,
    'missing-ref': 3,
    'prompt-sources': 1,
    'prompt-stats': 1,
    'prompt-quotes': 1,
    'notes-conflict': 4,
    'notes-match': -2,
    'notes-partial': -1,
    'notes-missing': 1,
    'origin-kept': 1,
    'origin-yours': -1,
    'hedge': -1
  };
  M.WEIGHTS = W;

  function scoreClaim(kinds, scan, ctx) {
    var reasons = [];
    function add(code, points, text) { reasons.push({ code: code, points: points, text: text }); }
    function texts(k) { return uniqTexts(kinds[k] || []); }
    if (kinds.leftover) add('leftover', W['leftover'], 'Text from the AI tool itself (' + quoteList(texts('leftover'), 2) + '), not part of your work.');
    if (kinds.statistic) add('statistic', W['statistic'], 'Figures to check: ' + quoteList(texts('statistic')) + '. Numbers are where AI drafts most often go wrong.');
    if (kinds.quote) add('quote', W['quote'], 'Direct quotation: AI tools often reword or invent quotes.');
    if (kinds.vague) add('vague', W['vague'], 'Vague appeal to authority (' + quoteList(texts('vague'), 2) + ') with no named source.');
    if (kinds.legal) add('legal', W['legal'], 'Legal statement (' + quoteList(texts('legal'), 3) + ').');
    if (kinds.medical) add('medical', W['medical'], 'Health or safety statement (' + quoteList(texts('medical'), 3) + ').');
    if (kinds.financial) add('financial', W['financial'], 'Money or financial statement (' + quoteList(texts('financial'), 3) + ').');
    if (kinds.study) add('study', W['study'], 'Refers to a study or report: check the original says this.');
    if (kinds.person) add('person', W['person'], 'Names a person (' + quoteList(texts('person'), 3) + ').');
    if (kinds.url) add('url', W['url'], 'Web address or DOI (' + quoteList(texts('url'), 2) + ').');
    if (kinds.absolute) add('absolute', W['absolute'], 'Absolute or superlative wording (' + quoteList(texts('absolute'), 3) + ').');
    if (kinds.org) add('org', W['org'], 'Names an organisation (' + quoteList(texts('org'), 3) + ').');
    if (kinds.date) add('date', W['date'], 'Dates or times: ' + quoteList(texts('date')) + '.');
    if (kinds.citation) add('citation', W['citation'], 'Cites ' + quoteList(texts('citation'), 3) + ': check the source supports the sentence.');
    if ((kinds.statistic || kinds.quote || kinds.study) && !kinds.citation && !kinds.url) add('unsourced', W['unsourced'], 'No source given in the sentence.');
    if (ctx.missing.length) add('missing-ref', W['missing-ref'], 'Cites ' + quoteList(ctx.missing, 3) + ', which ' + (ctx.missing.length === 1 ? 'is' : 'are') + ' not in your reference list.');
    if (ctx.prompt.asksSources && kinds.citation) add('prompt-sources', W['prompt-sources'], 'You asked the AI for references, and AI tools often invent plausible ones.');
    if (ctx.prompt.asksStats && kinds.statistic) add('prompt-stats', W['prompt-stats'], 'You asked the AI for statistics, and AI tools often invent plausible figures.');
    if (ctx.prompt.asksQuotes && kinds.quote) add('prompt-quotes', W['prompt-quotes'], 'You asked the AI for a quotation, and AI tools often invent them.');
    var nt = ctx.notes;
    if (nt.status === 'conflict') {
      var bits = nt.items.filter(function (it) { return it.result === 'conflict'; }).map(function (it) {
        return it.what === 'the quotation' ? 'your notes give the quotation as ' + it.noted : 'your notes say ' + it.noted + ' where the text says ' + it.what;
      });
      add('notes-conflict', W['notes-conflict'], 'Your notes disagree: ' + listAnd(bits) + '.');
    } else if (nt.status === 'match') add('notes-match', W['notes-match'], 'Your notes give the same ' + (nt.items.length === 1 ? 'figure' : 'figures') + '.');
    else if (nt.status === 'partial') {
      add('notes-partial', W['notes-partial'], 'Your notes back ' + listAnd(nt.items.filter(function (it) { return it.result === 'match'; }).map(function (it) { return '"' + it.what + '"'; })) + ' but not ' + listAnd(nt.items.filter(function (it) { return it.result !== 'match'; }).map(function (it) { return '"' + it.what + '"'; })) + '.');
    } else if (nt.status === 'missing') add('notes-missing', W['notes-missing'], 'Not in your notes, so you have no record of where it came from.');
    if (ctx.origin === 'kept') add('origin-kept', W['origin-kept'], 'Kept word for word from the AI draft.');
    else if (ctx.origin === 'yours') add('origin-yours', W['origin-yours'], 'Written in your own words.');
    if (kinds.statistic && !kinds.leftover && scan.hedges.length) add('hedge', W['hedge'], 'Hedged wording (' + quoteList(uniqTexts(scan.hedges), 2) + ').');
    var score = 0;
    for (var i = 0; i < reasons.length; i++) score += reasons[i].points;
    return { score: score, reasons: reasons };
  }

  // ---------------------------------------------------------------- what changed between the AI draft and your final version

  // Citations are left out of the wording comparison: "(Hartwell et al., 2019)" is the same whoever writes it.
  function withoutCitations(text) {
    var cits = findCitations(text), out = '', at = 0;
    for (var i = 0; i < cits.length; i++) {
      if (cits[i].start < at) continue;
      out += text.slice(at, cits[i].start) + ' ';
      at = cits[i].end;
    }
    return out + text.slice(at);
  }
  M.withoutCitations = withoutCitations;

  function bodySentences(doc) {
    var out = [], para = 0;
    for (var b = 0; b < doc.blocks.length; b++) {
      var block = doc.blocks[b];
      if (block.kind === 'heading') continue;
      var parts = splitSentences(block.text);
      for (var p = 0; p < parts.length; p++) out.push({ text: parts[p], para: para, block: b, toks: words(withoutCitations(parts[p])) });
      para++;
    }
    return out;
  }
  M.bodySentences = bodySentences;

  function gramSet(sents, n) {
    var set = dict(), flat = [];
    for (var s = 0; s < sents.length; s++) for (var t = 0; t < sents[s].toks.length; t++) flat.push(sents[s].toks[t]);
    for (var i = 0; i + n <= flat.length; i++) set[flat.slice(i, i + n).join(' ')] = true;
    var whole = dict();
    for (var w = 0; w < sents.length; w++) if (sents[w].toks.length) whole[sents[w].toks.join(' ')] = true;
    return { grams: set, whole: whole };
  }

  // Marks every word that sits in a run of at least MIN_RUN words found, in order, in the other text.
  function markKept(sents, other, n) {
    var flat = [], owner = [];
    for (var s = 0; s < sents.length; s++) {
      for (var t = 0; t < sents[s].toks.length; t++) { flat.push(sents[s].toks[t]); owner.push(s); }
    }
    var kept = [];
    for (var k = 0; k < flat.length; k++) kept.push(false);
    for (var i = 0; i + n <= flat.length; i++) {
      if (hasOwn(other.grams, flat.slice(i, i + n).join(' '))) for (var j = i; j < i + n; j++) kept[j] = true;
    }
    var perSentence = [], idx = 0;
    for (var a = 0; a < sents.length; a++) {
      var len = sents[a].toks.length, c = 0;
      for (var b = 0; b < len; b++) if (kept[idx + b]) c++;
      if (len > 0 && len < n && hasOwn(other.whole, sents[a].toks.join(' '))) c = len;
      perSentence.push(c);
      idx += len;
    }
    return perSentence;
  }

  function lcsOps(a, b) {
    var ka = a.map(function (t) { return words(t).join(' '); }), kb = b.map(function (t) { return words(t).join(' '); });
    var n = a.length, m = b.length;
    if (n * m > 40000) return null;
    var dp = [];
    for (var i = 0; i <= n; i++) { dp.push(new Array(m + 1)); for (var j = 0; j <= m; j++) dp[i][j] = 0; }
    for (var x = n - 1; x >= 0; x--) {
      for (var y = m - 1; y >= 0; y--) {
        dp[x][y] = ka[x] === kb[y] ? dp[x + 1][y + 1] + 1 : Math.max(dp[x + 1][y], dp[x][y + 1]);
      }
    }
    var ops = [], p = 0, q = 0;
    function push(type, text) {
      if (ops.length && ops[ops.length - 1][0] === type) ops[ops.length - 1][1] += ' ' + text;
      else ops.push([type, text]);
    }
    while (p < n && q < m) {
      if (ka[p] === kb[q]) { push('=', b[q]); p++; q++; }
      else if (dp[p + 1][q] >= dp[p][q + 1]) { push('-', a[p]); p++; }
      else { push('+', b[q]); q++; }
    }
    while (p < n) { push('-', a[p]); p++; }
    while (q < m) { push('+', b[q]); q++; }
    return ops;
  }
  M.lcsOps = lcsOps;

  // The draft sentences sharing most content words with the given tokens (at most CANDIDATES of them,
  // most shared first, then in order), so long texts that repeat themselves stay quick.
  M.CANDIDATES = 25;
  function candidates(index, toks) {
    var count = dict(), out = [], seenTok = dict();
    for (var i = 0; i < toks.length; i++) {
      if (!hasOwn(index, toks[i]) || hasOwn(seenTok, toks[i])) continue;
      seenTok[toks[i]] = true;
      var lst = index[toks[i]];
      for (var j = 0; j < lst.length; j++) {
        if (!hasOwn(count, lst[j])) { count[lst[j]] = 0; out.push(lst[j]); }
        count[lst[j]]++;
      }
    }
    out.sort(function (a, b) { return count[b] - count[a] || a - b; });
    return out.slice(0, M.CANDIDATES).sort(function (a, b) { return a - b; });
  }

  function analyseChanges(draftSents, finalSents) {
    var n = M.MIN_RUN;
    var keptFinal = markKept(finalSents, gramSet(draftSents, n), n);
    var keptDraft = markKept(draftSents, gramSet(finalSents, n), n);
    var counts = { kept: 0, edited: 0, reworded: 0, yours: 0, dropped: 0 };
    var finalWords = 0, keptWords = 0, draftWords = 0, survived = 0;
    var paired = dict(), sentences = [];
    var index = dict();
    for (var di = 0; di < draftSents.length; di++) {
      for (var dt = 0; dt < draftSents[di].toks.length; dt++) {
        var tok = draftSents[di].toks[dt];
        if (hasOwn(STOP, tok) || /^[0-9]/.test(tok)) continue;
        if (!hasOwn(index, tok)) index[tok] = [];
        var lst = index[tok];
        if (lst[lst.length - 1] !== di) lst.push(di);
      }
    }
    for (var f = 0; f < finalSents.length; f++) {
      var fs = finalSents[f], len = fs.toks.length, k = keptFinal[f];
      finalWords += len; keptWords += k;
      var best = -1, bestD = null, cands = candidates(index, fs.toks);
      for (var ci = 0; ci < cands.length; ci++) {
        var d = cands[ci];
        var dc = diceOf(fs.toks, draftSents[d].toks);
        if (dc.total === 0) continue;
        if (bestD === null || dc.inter * bestD.total > bestD.inter * dc.total) { best = d; bestD = dc; }
      }
      var pairOk = bestD !== null && bestD.inter * 2 * 100 >= M.PAIR_DICE * bestD.total;
      var cls;
      if (len > 0 && k * 100 >= M.KEPT_SHARE * len) cls = 'kept';
      else if (len > 0 && k * 100 >= M.EDITED_SHARE * len) cls = 'edited';
      else if (bestD !== null && bestD.inter * 2 * 100 >= M.REWORD_DICE * bestD.total) cls = 'reworded';
      else cls = 'yours';
      counts[cls]++;
      var pair = pairOk && cls !== 'yours' ? best : -1;
      if (pair >= 0) paired[pair] = true;
      var ops = null;
      if (pair >= 0 && cls !== 'kept') {
        ops = lcsOps(draftSents[pair].text.split(' ').filter(function (t) { return t !== ''; }), fs.text.split(' ').filter(function (t) { return t !== ''; }));
      } else if (pair >= 0 && draftSents[pair].toks.join(' ') !== fs.toks.join(' ')) {
        ops = lcsOps(draftSents[pair].text.split(' ').filter(function (t) { return t !== ''; }), fs.text.split(' ').filter(function (t) { return t !== ''; }));
      }
      sentences.push({ text: fs.text, para: fs.para, cls: cls, words: len, kept: k, pair: pair, ops: ops });
    }
    var dropped = [];
    for (var a = 0; a < draftSents.length; a++) {
      var dl = draftSents[a].toks.length;
      draftWords += dl; survived += keptDraft[a];
      if (dl > 0 && keptDraft[a] * 100 < M.EDITED_SHARE * dl && !hasOwn(paired, a)) {
        dropped.push({ index: a, text: draftSents[a].text, words: dl, survived: keptDraft[a] });
      }
    }
    counts.dropped = dropped.length;
    var paras = [];
    for (var s = 0; s < sentences.length; s++) {
      var pi = sentences[s].para;
      while (paras.length <= pi) paras.push({ words: 0, kept: 0, sentences: 0 });
      paras[pi].words += sentences[s].words; paras[pi].kept += sentences[s].kept; paras[pi].sentences++;
    }
    return {
      finalWords: finalWords, keptWords: keptWords, keptShare: pct(keptWords, finalWords),
      draftWords: draftWords, survivedWords: survived, survivedShare: pct(survived, draftWords),
      counts: counts, finalSentences: finalSents.length, draftSentences: draftSents.length,
      sentences: sentences, dropped: dropped, paragraphs: paras
    };
  }
  M.analyseChanges = analyseChanges;

  // ---------------------------------------------------------------- reference lists

  var ENTRY_START_RE = new RegExp('^(?:[' + CAP + "][" + LET + "'\\-]+(?: [" + CAP + '][' + LET + "'\\-]+)*, ?(?:[" + CAP + ']\\.|[' + CAP + '][a-z]+)|[' + CAP + '][^()]{0,120}\\((?:' + YEAR + '[a-z]?|n\\.d\\.)\\)|[' + CAP + '].{0,100}\\b' + YEAR + '\\b)');
  var MERGED_RE = new RegExp('\\. (?=[' + CAP + '][' + LET + "'\\-]+, (?:[" + CAP + ']\\. ?){1,3}(?:(?:,|and|&) [^()]{0,80})?\\((?:' + YEAR + '[a-z]?|n\\.d\\.)\\))', 'g');
  var LABEL_RE = /^(?:\[([0-9]{1,3})\]|([0-9]{1,3})[.)]|[-*+\u2022]) +/;

  // Splits a pasted reference list into entries, joining lines that were broken in the middle
  // and splitting entries that were run together.
  function splitEntries(lines) {
    var entries = [], current = null;
    var anyLabel = false;
    for (var i = 0; i < lines.length; i++) if (LABEL_RE.test(trim(lines[i]))) { anyLabel = true; break; }
    for (var j = 0; j < lines.length; j++) {
      var line = trim(lines[j]);
      if (line === '' || /^([-*_])(?: *\1){2,}$/.test(line)) { if (!anyLabel) current = null; continue; }
      var lm = LABEL_RE.exec(line);
      if (lm) {
        current = { label: lm[1] || lm[2] || '', text: line.slice(lm[0].length) };
        entries.push(current);
        continue;
      }
      var starts = !anyLabel && ENTRY_START_RE.test(line);
      if (current && !starts) {
        var joinTight = /-$/.test(current.text) && /(?:https?:|www\.|doi|\/)[^ ]*-$/.test(current.text);
        current.text += (joinTight ? '' : ' ') + line;
      } else {
        current = { label: '', text: line };
        entries.push(current);
      }
    }
    var out = [];
    for (var e = 0; e < entries.length; e++) {
      var parts = entries[e].text.split(MERGED_RE);
      for (var p = 0; p < parts.length; p++) {
        var t = collapse(parts[p]);
        if (p < parts.length - 1) t += '.';
        if (t !== '') out.push({ label: p === 0 ? entries[e].label : '', text: t, merged: parts.length > 1 });
      }
    }
    return out;
  }
  M.splitEntries = splitEntries;

  var DOI_MARK_RE = /(?:https?:\/\/(?:dx\.)?doi\.org\/|\bdoi:? ?|\bDOI:? ?)/i;
  var BARE_DOI_RE = /\b10\.[0-9]{1,9}\/[^ ]+/;
  var REF_URL_RE = /\b(?:https?|htps?|hhtps?|http)(?::\/\/|:\/|\/\/)[^ ]+|\bwww\.[^ ]+/i;
  var GENERIC_WORDS = {};
  ('journal international research studies study review science sciences advanced global modern contemporary applied ' +
    'academic annals quarterly bulletin of and the in for on new open general current trends perspectives letters ' +
    'reports report proceedings transactions world european american british issues insights frontiers horizons ' +
    'progress innovative innovation multidisciplinary interdisciplinary').split(' ').forEach(function (w) { GENERIC_WORDS[w] = true; });
  var PLACEHOLDER_HOSTS = ['example.com', 'example.org', 'example.net', 'localhost'];

  function stripMarks(s) { return collapse(s.replace(/[*_]/g, '')); }

  function parseEntry(text, label) {
    var e = { label: label || '', text: stripMarks(text), raw: text, authors: '', year: '', title: '', container: '',
      volume: '', issue: '', pages: '', doi: '', doiMarked: false, url: '', urlTail: '', accessed: '', publisher: '', type: 'other', citeKey: '' };
    var s = text;
    var am = /\(?(?:accessed|retrieved|viewed)(?: on)?:? ([^)\]]+)[)\]]?/i.exec(s);
    if (am) { e.accessed = trim(am[1].replace(/[.]$/, '')); s = s.slice(0, am.index) + s.slice(am.index + am[0].length); }
    var dm = DOI_MARK_RE.exec(s);
    if (dm) {
      var after = s.slice(dm.index + dm[0].length);
      var stop = after.search(/ (?:\(|\[|Available|Accessed|Retrieved)/i);
      var doi = trim((stop >= 0 ? after.slice(0, stop) : after)).replace(/[.,;]+$/, '');
      e.doi = doi; e.doiMarked = true;
      s = s.slice(0, dm.index) + (stop >= 0 ? after.slice(stop) : '');
    } else {
      var bm = BARE_DOI_RE.exec(s);
      if (bm) { e.doi = bm[0].replace(/[.,;]+$/, ''); s = s.slice(0, bm.index) + s.slice(bm.index + bm[0].length); }
    }
    var um = REF_URL_RE.exec(s);
    if (um) {
      e.url = um[0].replace(/[.,;]+$/, '');
      var tail = trim(s.slice(um.index + um[0].length));
      tail = trim(tail.replace(/[ .,;]+$/, ''));
      if (tail !== '' && /^[a-z0-9][^ ]*(?: [a-z0-9][^ ]*){0,2}$/.test(tail) && !/^(?:accessed|viewed|retrieved|available)/i.test(tail)) e.urlTail = tail;
      s = s.slice(0, um.index) + (e.urlTail ? '' : s.slice(um.index + um[0].length));
      s = s.replace(/\bAvailable (?:at|from):? *$/i, '').replace(/\bRetrieved from:? *$/i, '');
    }
    var body = trim(s);
    var lm = /^(?:\[([0-9]{1,3})\]|([0-9]{1,3})[.)]) +/.exec(body);
    if (lm) { if (!e.label) e.label = lm[1] || lm[2]; body = body.slice(lm[0].length); }
    var ym = new RegExp('\\((' + YEAR + '[a-z]?|n\\.d\\.|[0-9]{4}[a-z]?)\\)').exec(body);
    var yearEnd = -1;
    if (ym) { e.year = ym[1]; e.authors = trim(body.slice(0, ym.index)).replace(/[,.]$/, ''); yearEnd = ym.index + ym[0].length; }
    else {
      ym = new RegExp('(?:^|[ ,.])(' + YEAR + '[a-z]?|[0-9]{4}[a-z]?|n\\.d\\.)(?=[.,;:]|$| )').exec(body);
      if (ym) {
        e.year = ym[1];
        var ys = ym.index + ym[0].indexOf(ym[1]);
        e.authors = trim(body.slice(0, ys)).replace(/[,.]$/, '');
        yearEnd = ys + ym[1].length;
      }
    }
    e.authors = stripMarks(e.authors);
    var rest = yearEnd >= 0 ? body.slice(yearEnd) : body;
    rest = rest.replace(/^[).,: ]+/, '');
    var tm = /^'([^']+)'|^"([^"]+)"/.exec(rest);
    var after2 = '';
    if (tm) { e.title = tm[1] || tm[2]; after2 = rest.slice(tm[0].length); }
    else {
      var im = /^\*([^*]+)\*/.exec(rest);
      if (im) { e.title = im[1]; after2 = rest.slice(im[0].length); e.container = ''; e.italicTitle = true; }
      else {
        var dot = rest.search(/[.?!] /);
        if (dot >= 0) { e.title = rest.slice(0, dot); after2 = rest.slice(dot + 1); }
        else { e.title = rest; after2 = ''; }
      }
    }
    e.title = trim(stripMarks(e.title).replace(/[.,]$/, ''));
    after2 = after2.replace(/^[.,: ]+/, '');
    var cm = /^(?:[Ii]n:? )?\*([^*]+)\*/.exec(after2);
    if (cm) e.container = trim(cm[1].replace(/[.,]$/, ''));
    else if (tm) {
      var cut = after2.search(/, ?(?:vol|[0-9]|pp?\.)|\. |\.$|$/i);
      e.container = trim(stripMarks(after2.slice(0, cut < 0 ? after2.length : cut)).replace(/[.,]$/, ''));
    }
    var plain = stripMarks(after2);
    var vm = /\b([0-9]{1,4}) ?\(([0-9]{1,4}(?:[-\u2013][0-9]{1,4})?)\)/.exec(plain) || /\bvol(?:ume)?\.? ?([0-9]{1,4})(?:,? (?:no|issue|iss)\.? ?([0-9]{1,4}))?/i.exec(plain);
    if (vm) { e.volume = vm[1]; e.issue = vm[2] || ''; }
    else {
      var vm2 = /, ([0-9]{1,4}),/.exec(plain);
      if (vm2 && e.container) e.volume = vm2[1];
    }
    var pm = /\bpp?\.? ?([0-9]+) ?[-\u2013] ?([0-9]+)/.exec(plain) || /\), ?([0-9]+) ?[-\u2013] ?([0-9]+)/.exec(plain) || /, ([0-9]+) ?[-\u2013] ?([0-9]+)\.?$/.exec(plain);
    if (pm) e.pages = pm[1] + '-' + pm[2];
    else {
      var pm2 = /\b(?:p\.|article|art\.) ?(e?[0-9]+)/i.exec(plain);
      if (pm2) e.pages = pm2[1];
    }
    if (!e.container && !tm && !e.italicTitle && (e.volume || /-/.test(e.pages))) {
      var cut2 = plain.search(/, ?(?:vol|[0-9]|pp?\.)|\. |\.$|$/i);
      e.container = trim(plain.slice(0, cut2 < 0 ? plain.length : cut2).replace(/[.,]$/, ''));
    }
    var pubm = /(?:^|\. )([A-Z][A-Za-z .'\-]{1,40}): ([A-Z][^.:]{1,80})\.?/.exec(plain);
    if (pubm && !e.volume) e.publisher = trim(pubm[2]);
    if (e.volume || (e.pages && e.container && /-/.test(e.pages))) e.type = 'journal';
    else if (tm && e.container && !e.publisher) e.type = 'journal';
    else if (e.publisher || /\b(?:ed\.|edn|edition)\b/i.test(plain)) e.type = 'book';
    else if (e.url) e.type = 'web';
    else if (/\breport\b|working paper/i.test(e.title + ' ' + plain)) e.type = 'report';
    e.key = 'r' + fnv(words(e.text).join(' '));
    return e;
  }
  M.parseEntry = parseEntry;

  // ---------------------------------------------------------------- reference manager exports (RIS and BibTeX)

  function listNames(names) {
    if (names.length <= 1) return names.join('');
    return names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1];
  }

  function firstYear(s) {
    var m = /(?:^|[^0-9])([0-9]{4})(?![0-9])/.exec(s || '');
    return m ? m[1] : '';
  }

  // Builds an entry, in the same shape parseEntry gives, from the fields of a reference manager record.
  function structuredEntry(f, format, raw) {
    var e = { label: '', text: '', raw: raw, authors: listNames(f.authors), year: f.year, title: f.title, container: f.container,
      volume: f.volume, issue: f.issue, pages: f.pages, doi: f.doi, doiMarked: f.doi !== '', url: f.url, urlTail: '', accessed: f.accessed,
      publisher: f.publisher, type: f.type, citeKey: f.citeKey, structured: format };
    var t = (e.authors ? e.authors + ' ' : '') + '(' + (e.year || 'no year') + ') ';
    if (e.type === 'journal') {
      t += "'" + e.title + "', " + e.container + (e.volume ? ', ' + e.volume + (e.issue ? '(' + e.issue + ')' : '') : '') + (e.pages ? ', pp. ' + e.pages : '') + '.';
    } else if (e.type === 'book' || e.type === 'report') {
      t += e.title + '.' + (e.container ? ' In: ' + e.container + '.' : '') + (e.publisher ? ' ' + e.publisher + '.' : '');
    } else t += e.title + '.' + (e.container ? ' ' + e.container + '.' : '');
    if (e.doi) t += ' doi:' + e.doi;
    if (e.url) t += ' Available at: ' + e.url + (e.accessed ? ' (Accessed: ' + e.accessed + ')' : '');
    e.text = collapse(t.replace(/ ,/g, ','));
    e.key = 'r' + fnv(words(e.text).join(' '));
    return e;
  }

  var RIS_TYPES = { JOUR: 'journal', JFULL: 'journal', EJOUR: 'journal', MGZN: 'journal', NEWS: 'journal', BOOK: 'book', EBOOK: 'book', CHAP: 'book',
    ECHAP: 'book', EDBOOK: 'book', ELEC: 'web', WEB: 'web', BLOG: 'web', RPRT: 'report', GOVDOC: 'report', THES: 'report' };

  function looksRis(text) { return /(?:^|\n)TY {1,2}- ?[A-Z]/.test(text); }
  function looksBibtex(text) { return /(?:^|\n) *@[A-Za-z]+ *[{(]/.test(text); }
  M.looksRis = looksRis;
  M.looksBibtex = looksBibtex;

  // Reads a RIS export (Zotero, Mendeley, EndNote, library databases): one record from TY to ER.
  function parseRis(text) {
    var lines = cleanChars(text, {}).split('\n'), recs = [], cur = null, last = '';
    for (var i = 0; i < lines.length; i++) {
      var m = /^([A-Z][A-Z0-9]) {1,2}-(?: (.*))?$/.exec(trim(lines[i]));
      if (m) {
        var tag = m[1], val = trim(m[2] || '');
        if (tag === 'TY') { cur = { type: val, fields: dict(), raw: [trim(lines[i])] }; recs.push(cur); last = ''; continue; }
        if (!cur) continue;
        cur.raw.push(trim(lines[i]));
        if (tag === 'ER') { cur = null; continue; }
        if (!hasOwn(cur.fields, tag)) cur.fields[tag] = [];
        cur.fields[tag].push(val);
        last = tag;
      } else if (cur && last && trim(lines[i]) !== '') {
        var arr = cur.fields[last];
        arr[arr.length - 1] = collapse(arr[arr.length - 1] + ' ' + trim(lines[i]));
        cur.raw.push(trim(lines[i]));
      }
    }
    return recs.map(function (r) {
      var f = r.fields;
      function one() {
        for (var k = 0; k < arguments.length; k++) if (hasOwn(f, arguments[k]) && f[arguments[k]][0] !== '') return f[arguments[k]][0];
        return '';
      }
      var authors = [];
      ['AU', 'A1', 'A2'].forEach(function (t) { if (hasOwn(f, t) && !authors.length) authors = f[t].filter(function (x) { return x !== ''; }); });
      var sp = one('SP'), ep = one('EP');
      return structuredEntry({ authors: authors, year: firstYear(one('PY', 'Y1', 'DA')), title: one('TI', 'T1', 'CT'), container: one('T2', 'JO', 'JF', 'JA', 'BT'),
        volume: one('VL'), issue: one('IS'), pages: sp && ep && ep !== sp ? sp + '-' + ep : sp, doi: one('DO').replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi: ?)/i, ''),
        url: one('UR', 'L2'), accessed: one('Y2'), publisher: one('PB'), type: hasOwn(RIS_TYPES, r.type) ? RIS_TYPES[r.type] : (one('UR') ? 'web' : 'other'),
        citeKey: one('ID') }, 'ris', r.raw.join('\n'));
    });
  }
  M.parseRis = parseRis;

  var TEX_ACCENTS = { "'": '\u0301', '`': '\u0300', '^': '\u0302', '"': '\u0308', '~': '\u0303', '=': '\u0304', '.': '\u0307' };

  // Turns BibTeX's TeX markup into plain text: accents, escaped characters, commands and braces.
  function texText(s) {
    var t = s.replace(/\\([&%$#_])/g, '$1');
    t = t.replace(/\{?\\(['`^"~=.])\{?\\?([A-Za-z])\}?\}?/g, function (m0, acc, ch) { return ch + TEX_ACCENTS[acc]; });
    t = t.replace(/\{?\\c\{?([A-Za-z])\}?\}?/g, function (m0, ch) { return ch + '\u0327'; });
    t = t.replace(/\\(?:ss)\b/g, '\u00df').replace(/\\[A-Za-z]+\*? ?/g, '');
    t = t.replace(/[{}]/g, '').replace(/~/g, ' ').replace(/--/g, '-');
    return collapse(t.normalize('NFC').replace(/\n/g, ' '));
  }
  M.texText = texText;

  function bibName(name) {
    var n = trim(name);
    if (/^\{.*\}$/.test(n)) return texText(n);
    var plain = texText(n);
    if (plain.indexOf(',') >= 0 || plain.indexOf(' ') < 0) return plain;
    var parts = plain.split(' ');
    return parts[parts.length - 1] + ', ' + parts.slice(0, -1).join(' ');
  }

  var BIB_TYPES = { article: 'journal', book: 'book', inbook: 'book', incollection: 'book', booklet: 'book', proceedings: 'book',
    inproceedings: 'book', conference: 'book', techreport: 'report', report: 'report', phdthesis: 'report', mastersthesis: 'report', thesis: 'report',
    online: 'web', electronic: 'web', www: 'web', webpage: 'web' };

  // Reads a BibTeX export: @type{key, field = {value} or "value" or bare, ...}.
  function parseBibtex(text) {
    var s = cleanChars(text, {}), out = [], i = 0, n = s.length;
    function skipBlank() { while (i < n && /[ \n,]/.test(s[i])) i++; }
    while (i < n) {
      var at = s.indexOf('@', i);
      if (at < 0) break;
      var hm = /^@([A-Za-z]+) *([{(])/.exec(s.slice(at, at + 60));
      if (!hm) { i = at + 1; continue; }
      var type = hm[1].toLowerCase(), close = hm[2] === '{' ? '}' : ')';
      i = at + hm[0].length;
      if (type === 'comment' || type === 'string' || type === 'preamble') {
        var depth = 1;
        while (i < n && depth > 0) { if (s[i] === hm[2]) depth++; else if (s[i] === close) depth--; i++; }
        continue;
      }
      var comma = s.indexOf(',', i), shut = s.indexOf(close, i);
      if (comma < 0 || (shut >= 0 && shut < comma)) { i = shut < 0 ? n : shut + 1; continue; }
      var key = trim(s.slice(i, comma).replace(/\n/g, ' '));
      i = comma + 1;
      var fields = dict();
      while (i < n) {
        skipBlank();
        if (i >= n || s[i] === close) { i++; break; }
        var nm = /^([A-Za-z][A-Za-z0-9_\-]*) *= */.exec(s.slice(i, i + 80));
        if (!nm) { while (i < n && s[i] !== ',' && s[i] !== close) i++; continue; }
        i += nm[0].length;
        var value = '';
        if (s[i] === '{') {
          var d2 = 0, st = i;
          while (i < n) { if (s[i] === '{') d2++; else if (s[i] === '}') { d2--; if (d2 === 0) break; } i++; }
          value = s.slice(st + 1, i); i++;
        } else if (s[i] === '"') {
          var st2 = ++i, d3 = 0;
          while (i < n && !(s[i] === '"' && d3 === 0)) { if (s[i] === '{') d3++; else if (s[i] === '}') d3--; i++; }
          value = s.slice(st2, i); i++;
        } else {
          var st3 = i;
          while (i < n && s[i] !== ',' && s[i] !== close && s[i] !== '\n') i++;
          value = trim(s.slice(st3, i));
        }
        fields[nm[1].toLowerCase()] = value;
      }
      var get = function (k) { return hasOwn(fields, k) ? texText(fields[k]) : ''; };
      var authorsRaw = hasOwn(fields, 'author') ? fields.author : (hasOwn(fields, 'editor') ? fields.editor : '');
      var authors = trim(authorsRaw) === '' ? [] : authorsRaw.replace(/\n/g, ' ').split(/ +and +/).map(bibName).filter(function (x) { return x !== ''; });
      var url = get('url'), doi = get('doi').replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi: ?)/i, '');
      var raw = s.slice(at, i);
      out.push(structuredEntry({ authors: authors, year: get('year') ? firstYear(get('year')) || get('year') : firstYear(get('date')), title: get('title'),
        container: get('journal') || get('journaltitle') || get('booktitle'), volume: get('volume'), issue: get('number') || get('issue'),
        pages: get('pages').replace(/ *[-\u2013]+ */g, '-'), doi: doi, url: url, accessed: get('urldate'),
        publisher: get('publisher') || get('institution') || get('organization') || get('school'),
        type: hasOwn(BIB_TYPES, type) ? BIB_TYPES[type] : (url ? 'web' : 'other'), citeKey: key }, 'bibtex', trim(raw)));
    }
    return out;
  }
  M.parseBibtex = parseBibtex;

  function normAuthors(s) { return collapse(stripAccents(s).toLowerCase().replace(/[^a-z0-9 ]/g, ' ')); }

  function firstSurname(authors) {
    var a = normAuthors(authors.replace(/\bet al\.?/g, ''));
    return a.split(' ')[0] || '';
  }

  function checkUrl(url, tail) {
    var issues = [];
    if (/^(?:htps?|hhtps?)[:/]/i.test(url) || /^https?:\/(?!\/)/i.test(url) || /^https?\/\//i.test(url) || /^http\/\//i.test(url)) {
      issues.push({ code: 'url-scheme', severity: 'problem', text: 'The web address starts "' + url.slice(0, url.indexOf('/') + 2) + '": it should start https:// or http://.' });
    }
    if (tail) issues.push({ code: 'url-space', severity: 'problem', text: 'The web address seems to contain a space ("' + url + ' ' + tail + '"), so it will not open as written.' });
    else if (/ /.test(url)) issues.push({ code: 'url-space', severity: 'problem', text: 'The web address contains a space ("' + url + '"), so it will not open as written.' });
    var hm = /^(?:[a-z]+:?\/*)?([^/?#]+)/i.exec(url);
    var host = hm ? hm[1].toLowerCase() : '';
    if (host && (host.indexOf('.') < 0 || /[^a-z0-9.\-:]/.test(host) || /\.\.|^-|-\.|\.-/.test(host))) {
      issues.push({ code: 'url-host', severity: 'problem', text: 'The site name "' + host + '" is not a well-formed address.' });
    }
    var bare = host.replace(/^www\./, '');
    var placeholder = PLACEHOLDER_HOSTS.indexOf(bare) >= 0 || /\.(?:example|invalid|test)$/.test(bare);
    if (placeholder) issues.push({ code: 'url-placeholder', severity: 'problem', text: 'The web address points to a placeholder site (' + bare + '), not a real source.' });
    return issues;
  }

  // Checks each reference on its own: shape, plausibility and signs it may be made up.
  function checkEntry(e, asOfDay) {
    var issues = [], signals = 0;
    var thisYear = civilFromDays(asOfDay)[0];
    if (!e.year) issues.push({ code: 'no-year', severity: 'problem', text: 'No year found.' });
    else if (e.year !== 'n.d.') {
      var y = +e.year.slice(0, 4);
      if (y > thisYear) { issues.push({ code: 'future-year', severity: 'problem', text: 'The year ' + y + ' is after ' + longDay(asOfDay) + '.' }); signals++; }
      else if (y < 1800) issues.push({ code: 'old-year', severity: 'warning', text: 'The year ' + y + ' is unusually early: check it.' });
    } else issues.push({ code: 'no-date', severity: 'note', text: 'No date (n.d.): check whether the source gives one.' });
    if (!e.authors) issues.push({ code: 'no-author', severity: 'warning', text: 'No author found.' });
    else if (/^(?:anon|anonymous|author|unknown|et al)\b/i.test(e.authors)) {
      issues.push({ code: 'placeholder-author', severity: 'warning', text: 'The author looks like a placeholder ("' + e.authors + '").' }); signals++;
    }
    if (e.authors && /\bet al\b/i.test(e.authors)) {
      issues.push({ code: 'et-al', severity: 'warning', text: 'Uses "et al." in the reference list, where Harvard and APA name the authors in full.' }); signals++;
    }
    if (/\[(?:author|year|title|insert|source)[^\]]*\]/i.test(e.raw) || /^title of\b/i.test(e.title)) {
      issues.push({ code: 'placeholder', severity: 'problem', text: 'Contains placeholder text from the AI tool.' }); signals++;
    }
    if (e.doi) {
      var d = e.doi;
      if (/ /.test(d)) issues.push({ code: 'doi-space', severity: 'problem', text: 'The DOI "' + d + '" contains a space.' });
      else if (!/^10\.[0-9]{4,9}\/[^ ]+$/.test(d)) issues.push({ code: 'doi-form', severity: 'problem', text: 'The DOI "' + d + '" does not have the shape 10.NNNN/something.' });
      if (/^10\.(?:1234|0000|9999|xxxx)\b/i.test(d) || /x{3,}/i.test(d)) { issues.push({ code: 'doi-placeholder', severity: 'problem', text: 'The DOI "' + d + '" looks like a placeholder.' }); signals++; }
    }
    if (e.url) issues = issues.concat(checkUrl(e.url, e.urlTail));
    if (e.type === 'web' && !e.accessed) issues.push({ code: 'web-no-date', severity: 'note', text: 'Web source with no date you accessed it.' });
    var looksArticle = e.type === 'journal' || (e.container && /\b(?:journal|review|quarterly|bulletin|annals|letters|proceedings|transactions)\b/i.test(e.container));
    if (looksArticle && !e.volume && !e.pages) {
      issues.push({ code: 'journal-incomplete', severity: 'warning', text: 'Journal article with no volume or page numbers.' }); signals++;
    }
    if (e.container) {
      var cws = normAuthors(e.container).split(' ').filter(function (w) { return w !== ''; });
      var specific = cws.filter(function (w) { return !hasOwn(GENERIC_WORDS, w); });
      if (cws.length >= 2 && specific.length <= 1 && /\b(?:journal|review|annals|bulletin|quarterly)\b/i.test(e.container)) {
        issues.push({ code: 'generic-journal', severity: 'warning', text: 'The journal name "' + e.container + '" is very generic.' }); signals++;
      }
    }
    if (e.pages && /^([0-9]+)-([0-9]+)$/.test(e.pages)) {
      var pr = /^([0-9]+)-([0-9]+)$/.exec(e.pages);
      if (+pr[2] < +pr[1]) issues.push({ code: 'pages-reversed', severity: 'problem', text: 'The page range ' + pr[1] + '-' + pr[2] + ' runs backwards.' });
    }
    if (!e.title || e.title.length < 3) issues.push({ code: 'no-title', severity: 'warning', text: 'No title found.' });
    return { issues: issues, signals: signals };
  }
  M.checkEntry = checkEntry;

  function titleKey(t) { return normAuthors(t).split(' ').filter(function (w) { return w !== '' && !hasOwn(STOP, w); }); }

  function checkReferences(entries, citations, asOfDay) {
    var out = [];
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];
      var c = checkEntry(e, asOfDay);
      out.push({ index: i, number: i + 1, entry: e, issues: c.issues, signals: c.signals, cited: 0, duplicateOf: -1 });
    }
    for (var a = 0; a < out.length; a++) {
      for (var b = 0; b < a; b++) {
        var ea = out[a].entry, eb = out[b].entry, dup = false;
        if (ea.doi && eb.doi && ea.doi.toLowerCase() === eb.doi.toLowerCase()) dup = true;
        if (!dup && firstSurname(ea.authors) && firstSurname(ea.authors) === firstSurname(eb.authors) && ea.year === eb.year) {
          var dc = diceOf(titleKey(ea.title), titleKey(eb.title));
          if (dc.total > 0 && dc.inter * 2 * 10 >= 8 * dc.total) dup = true;
        }
        if (!dup && ea.text.toLowerCase() === eb.text.toLowerCase()) dup = true;
        if (dup) {
          out[a].duplicateOf = b;
          out[a].issues.push({ code: 'duplicate', severity: 'problem', text: 'Looks like a duplicate of entry ' + (b + 1) + '.' });
          break;
        }
      }
    }
    var missing = [], matched = [];
    for (var k = 0; k < citations.length; k++) {
      var cit = citations[k], hits = [];
      if (cit.kind === 'numeric') {
        for (var l = 0; l < cit.labels.length; l++) {
          var found = -1;
          for (var r0 = 0; r0 < out.length; r0++) if (out[r0].entry.footnote && out[r0].entry.label === cit.labels[l]) { found = r0; break; }
          for (var r = 0; r < out.length && found < 0; r++) if (out[r].entry.label === cit.labels[l]) { found = r; break; }
          if (found < 0 && !out.some(function (o) { return o.entry.label; }) && +cit.labels[l] >= 1 && +cit.labels[l] <= out.length) found = +cit.labels[l] - 1;
          if (found >= 0) hits.push(found);
          else missing.push({ text: '[' + cit.labels[l] + ']', sentence: cit.sentence, near: '' });
        }
      } else if (cit.kind === 'key') {
        for (var kk = 0; kk < cit.labels.length; kk++) {
          var fk = -1;
          for (var r2 = 0; r2 < out.length; r2++) {
            if (out[r2].entry.citeKey && out[r2].entry.citeKey.toLowerCase() === cit.labels[kk].toLowerCase()) { fk = r2; break; }
          }
          if (fk >= 0) hits.push(fk);
          else missing.push({ text: '@' + cit.labels[kk], sentence: cit.sentence, near: '' });
        }
      } else {
        var sur = firstSurname(cit.authors), near = '';
        for (var t = 0; t < out.length; t++) {
          var en = out[t].entry;
          var ea2 = normAuthors(en.authors);
          var cAuth = normAuthors(cit.authors.replace(/\bet al\.?/g, ''));
          var nameOk = sur !== '' && (ea2.indexOf(cAuth) === 0 || ea2.split(' ')[0] === sur);
          if (!nameOk) continue;
          var ey = en.year.toLowerCase(), cy = cit.year.toLowerCase();
          if (ey === cy || (ey.slice(0, 4) === cy && /^[0-9]{4}[a-z]$/.test(ey))) hits.push(t);
          else if (!near) near = en.authors + ' (' + en.year + ')';
        }
        if (!hits.length) missing.push({ text: cit.text.charAt(0) === '(' ? cit.authors + ', ' + cit.year : cit.text, sentence: cit.sentence, near: near });
      }
      for (var h = 0; h < hits.length; h++) {
        out[hits[h]].cited++;
        matched.push({ citation: cit.text, entry: hits[h] });
      }
    }
    var uncited = 0, problems = 0, suspect = 0;
    for (var u = 0; u < out.length; u++) {
      var row = out[u];
      if (citations.length && row.cited === 0) {
        row.issues.push({ code: 'uncited', severity: 'warning', text: 'Never cited in the text.' });
        uncited++;
      }
      row.verdict = row.signals >= 2 || (row.signals >= 1 && row.issues.some(function (x) { return x.code === 'journal-incomplete'; })) ? 'suspect'
        : row.issues.some(function (x) { return x.severity === 'problem'; }) ? 'fix'
          : row.issues.some(function (x) { return x.severity === 'warning'; }) ? 'warn' : 'ok';
      if (row.verdict === 'suspect') suspect++;
      if (row.verdict === 'suspect' || row.verdict === 'fix') problems++;
    }
    return { entries: out, missing: missing, matched: matched, uncited: uncited, problems: problems, suspect: suspect,
      flagged: out.filter(function (o) { return o.verdict !== 'ok'; }).length };
  }
  M.checkReferences = checkReferences;

  // ---------------------------------------------------------------- the whole analysis

  function analyse(input) {
    var asOf = typeof input.asOf === 'number' ? input.asOf : daysFromCivil(2026, 11, 28);
    var draftDoc = readDocument(input.draft || '');
    var finalDoc = readDocument(input.final || '');
    var hasFinal = finalDoc.blocks.length > 0;
    var checkedDoc = hasFinal ? finalDoc : draftDoc;
    var prompt = readPrompt(input.prompt || '');
    var notes = notesIndex(input.notes || '');
    var draftSents = bodySentences(draftDoc), finalSents = hasFinal ? bodySentences(finalDoc) : [];
    var sents = hasFinal ? finalSents : draftSents;
    var changes = hasFinal && draftSents.length ? analyseChanges(draftSents, finalSents) : null;
    var messages = [];

    var refSource = 'none', refLines = [], footnotes = checkedDoc.footnotes;
    var refInput = trim(cleanChars(input.references || '', {}).replace(/\n/g, ' '));
    if (refInput !== '') {
      var rd = cleanChars(input.references, {}).split('\n');
      refLines = []; var started = false;
      for (var r = 0; r < rd.length; r++) {
        if (!started && isRefHeading(trim(rd[r]).replace(/^#+ */, ''))) { started = true; continue; }
        if (trim(rd[r]) !== '') started = true;
        refLines.push(rd[r]);
      }
      refSource = 'list';
      if (checkedDoc.refLines.length) messages.push('Your text has its own reference list too; the separate list you gave is the one checked.');
    } else if (checkedDoc.refLines.length || footnotes.length) {
      refLines = checkedDoc.refLines; refSource = hasFinal ? 'final' : 'draft';
    }
    var refFormat = 'text', structured = [];
    if (refSource === 'list' && looksRis(input.references)) { refFormat = 'ris'; structured = parseRis(input.references); refLines = []; }
    else if (refSource === 'list' && looksBibtex(input.references)) { refFormat = 'bibtex'; structured = parseBibtex(input.references); refLines = []; }
    if (refFormat !== 'text' && !structured.length) messages.push('The reference list looks like a ' + (refFormat === 'ris' ? 'RIS' : 'BibTeX') + ' export but no records could be read from it.');
    var split = splitEntries(refLines);
    for (var fn = 0; fn < footnotes.length; fn++) split.push({ label: footnotes[fn].label, text: footnotes[fn].text, merged: false, footnote: true });
    var entries = structured.concat(split.map(function (x) { var e = parseEntry(x.text, x.label); e.footnote = !!x.footnote; return e; }));
    for (var se = 0; se < structured.length; se++) structured[se].footnote = false;
    var mergedCount = split.filter(function (x) { return x.merged; }).length;

    var citations = [];
    var scans = [];
    for (var s = 0; s < sents.length; s++) {
      var scan = scanSentence(sents[s].text);
      scans.push(scan);
      for (var c = 0; c < scan.citations.length; c++) {
        var cc = scan.citations[c];
        citations.push({ kind: cc.kind, text: cc.text, authors: cc.authors, year: cc.year, page: cc.page, labels: cc.labels, sentence: s });
      }
    }
    var refs = checkReferences(entries, citations, asOf);
    refs.source = refSource;
    refs.format = refFormat;
    refs.citations = citations.length;
    refs.mergedSplit = mergedCount;

    var claims = [];
    for (var i = 0; i < sents.length; i++) {
      var sc = scans[i];
      var kindNames = M.KIND_ORDER.filter(function (k) { return hasOwn(sc.kinds, k); });
      if (!kindNames.length) continue;
      var missingHere = entries.length || refSource !== 'none' ? refs.missing.filter(function (mm) { return mm.sentence === i; }).map(function (mm) { return mm.text; }) : [];
      var origin = changes ? changes.sentences[i].cls : '';
      var nt = compareNotes(sents[i].text, sc, notes);
      var scored = scoreClaim(sc.kinds, sc, { missing: missingHere, prompt: prompt, notes: nt, origin: origin });
      claims.push({
        q: claims.length + 1, key: sentenceKey(sents[i].text), sentence: i, para: sents[i].para, text: sents[i].text,
        kinds: kindNames, spans: sc.spans, score: scored.score, level: levelOf(scored.score), reasons: scored.reasons,
        checks: checksFor(sc.kinds, sc), origin: origin, notes: nt
      });
    }
    var ranked = claims.slice().sort(function (a, b) { return b.score - a.score || a.q - b.q; });
    if (!sents.length) messages.push('There is no text to check yet: paste the AI draft (and your final version, if you have one).');
    if (citations.length && !entries.length) messages.push('The text cites sources but no reference list was found, so citations could not be matched. Paste the list or add a "References" heading above it.');
    if (hasFinal && !draftSents.length) messages.push('There is a final version but no AI draft, so nothing can be compared.');
    if (mergedCount) messages.push(plural(mergedCount, 'reference entry was', 'reference entries were') + ' run together with another and have been split.');
    return {
      asOf: asOf, checked: hasFinal ? 'final' : 'draft', hasFinal: hasFinal, hasDraft: draftSents.length > 0,
      sentences: sents.map(function (x) { return { text: x.text, para: x.para }; }),
      headings: checkedDoc.blocks.filter(function (b) { return b.kind === 'heading'; }).map(function (b) { return b.text; }),
      claims: claims, ranked: ranked.map(function (x) { return x.q; }), refs: refs, changes: changes,
      prompt: prompt, notesGiven: notes.length > 0, notesSentences: notes.length,
      cleaning: { draft: draftDoc.cleaning, final: finalDoc.cleaning }, messages: messages,
      words: sents.reduce(function (t, x) { return t + x.toks.length; }, 0)
    };
  }
  M.analyse = analyse;

  // ---------------------------------------------------------------- statuses and the summary

  M.STATUSES = ['unchecked', 'verified', 'corrected', 'removed'];
  M.REF_STATUSES = ['unchecked', 'checked', 'fixed', 'removed'];

  function statusOf(checks, key) {
    var c = checks && hasOwn(checks, key) ? checks[key] : null;
    return c && M.STATUSES.indexOf(c.status) > 0 ? c.status : 'unchecked';
  }
  M.statusOf = statusOf;

  function refStatusOf(refChecks, key) {
    var c = refChecks && hasOwn(refChecks, key) ? refChecks[key] : null;
    return c && M.REF_STATUSES.indexOf(c.status) > 0 ? c.status : 'unchecked';
  }
  M.refStatusOf = refStatusOf;

  function summarise(a, checks, refChecks) {
    var s = { claims: a.claims.length, high: 0, medium: 0, low: 0, verified: 0, corrected: 0, removed: 0, unchecked: 0,
      highUnchecked: 0, leftovers: 0, conflicts: 0, resolved: 0 };
    for (var i = 0; i < a.claims.length; i++) {
      var c = a.claims[i], st = statusOf(checks, c.key);
      s[c.level]++;
      s[st]++;
      if (st === 'unchecked' && c.level === 'high') s.highUnchecked++;
      if (c.kinds.indexOf('leftover') >= 0) s.leftovers++;
      if (c.notes.status === 'conflict') s.conflicts++;
    }
    s.resolved = s.claims - s.unchecked;
    var flagged = a.refs.entries.filter(function (e) { return e.verdict !== 'ok'; });
    s.refs = a.refs.entries.length;
    s.refFlagged = flagged.length;
    s.refProblems = a.refs.problems;
    s.refSuspect = a.refs.suspect;
    s.refMissing = a.refs.missing.length;
    s.refResolved = flagged.filter(function (e) { return refStatusOf(refChecks, e.entry.key) !== 'unchecked'; }).length;
    s.refUnresolved = s.refFlagged - s.refResolved;
    s.complete = s.claims > 0 && s.unchecked === 0 && s.refUnresolved === 0;
    s.ready = s.highUnchecked === 0 && s.leftovers - countResolved(a, checks, 'leftover') === 0;
    return s;
  }
  M.summarise = summarise;

  function countResolved(a, checks, kind) {
    var n = 0;
    for (var i = 0; i < a.claims.length; i++) {
      if (a.claims[i].kinds.indexOf(kind) >= 0 && statusOf(checks, a.claims[i].key) !== 'unchecked') n++;
    }
    return n;
  }

  // ---------------------------------------------------------------- re-checking a new version

  // Compares the claims in the text you are checking now with those in the version you recorded as checked:
  // which are new, which were edited (with the mark the old wording had), which are unchanged (their marks
  // carry over, because a mark belongs to the exact sentence) and which have gone.
  function compareVersions(baselineText, a, checks) {
    var out = { newClaims: [], changed: [], unchanged: [], gone: [] };
    var prev = analyse({ draft: baselineText || '', asOf: a.asOf });
    var cur = dict(), before = dict();
    for (var i = 0; i < a.claims.length; i++) cur[a.claims[i].key] = true;
    for (var j = 0; j < prev.claims.length; j++) before[prev.claims[j].key] = true;
    var loose = prev.claims.filter(function (p) { return !hasOwn(cur, p.key); });
    var used = [];
    for (var u = 0; u < loose.length; u++) used.push(false);
    function noteOf(key) { return checks && hasOwn(checks, key) && typeof checks[key].note === 'string' ? checks[key].note : ''; }
    for (var k = 0; k < a.claims.length; k++) {
      var c = a.claims[k];
      if (hasOwn(before, c.key)) { out.unchanged.push(c.q); continue; }
      var cw = words(c.text), best = -1, bestD = null;
      for (var l = 0; l < loose.length; l++) {
        if (used[l]) continue;
        var d = diceOf(cw, words(loose[l].text));
        if (d.inter * 2 * 100 >= M.REWORD_DICE * d.total && (bestD === null || d.inter * bestD.total > bestD.inter * d.total)) { best = l; bestD = d; }
      }
      if (best >= 0) {
        used[best] = true;
        var p = loose[best];
        out.changed.push({ q: c.q, before: p.text, key: p.key, status: statusOf(checks, p.key), note: noteOf(p.key),
          ops: lcsOps(p.text.split(' ').filter(function (t) { return t !== ''; }), c.text.split(' ').filter(function (t) { return t !== ''; })) });
      } else out.newClaims.push(c.q);
    }
    for (var g = 0; g < loose.length; g++) {
      if (!used[g]) out.gone.push({ text: loose[g].text, key: loose[g].key, status: statusOf(checks, loose[g].key), note: noteOf(loose[g].key) });
    }
    return out;
  }
  M.compareVersions = compareVersions;

  // ---------------------------------------------------------------- the session log

  var SESSION_FIELDS = ['date', 'assignment', 'tool', 'purpose', 'prompt', 'used', 'changed', 'checked', 'minutes', 'person'];
  M.SESSION_FIELDS = SESSION_FIELDS;
  var SESSION_HEADER = ['Date', 'Assignment', 'Tool', 'Purpose', 'Prompt summary', 'What I used', 'What I changed', 'What I checked', 'Minutes', 'Person'];
  M.SESSION_HEADER = SESSION_HEADER;
  var SESSION_ALIASES = {
    date: ['date', 'day', 'when', 'session date', 'timestamp', 'date used', 'on'],
    assignment: ['assignment', 'project', 'module', 'deliverable', 'piece of work', 'document', 'course', 'task name', 'work'],
    tool: ['tool', 'ai tool', 'assistant', 'ai assistant', 'model', 'service', 'ai used', 'app', 'tool used', 'ai'],
    purpose: ['purpose', 'task', 'use', 'what for', 'used for', 'activity', 'reason', 'why'],
    prompt: ['prompt summary', 'prompt', 'prompts', 'what i asked', 'question', 'request', 'asked'],
    used: ['what i used', 'used', 'kept', 'output used', 'what i kept', 'output'],
    changed: ['what i changed', 'changed', 'changes', 'edits', 'my changes', 'what i edited'],
    checked: ['what i checked', 'checked', 'verification', 'verified', 'checks'],
    minutes: ['minutes', 'mins', 'duration', 'time', 'time spent', 'time (min)', 'time (mins)', 'length'],
    person: ['person', 'name', 'author', 'who', 'student', 'contributor', 'team member', 'by']
  };

  function headerKey(h) { return collapse(String(h).toLowerCase().replace(/[^a-z0-9() ]/g, ' ')); }

  function mapSessionHeader(header) {
    var map = dict(), used = dict();
    for (var f = 0; f < SESSION_FIELDS.length; f++) {
      var field = SESSION_FIELDS[f], aliases = SESSION_ALIASES[field];
      for (var a = 0; a < aliases.length && !hasOwn(map, field); a++) {
        for (var i = 0; i < header.length; i++) {
          if (!hasOwn(used, i) && headerKey(header[i]) === aliases[a]) { map[field] = i; used[i] = true; break; }
        }
      }
    }
    return map;
  }
  M.mapSessionHeader = mapSessionHeader;

  // Reads a session log CSV, saying in plain words what it could not read and why.
  function parseSessions(text) {
    var clean = cleanChars(text, {});
    var parsed = parseCsv(clean);
    var rows = parsed.rows, messages = [], sessions = [];
    var h = 0;
    while (h < rows.length && rows[h].every(function (c) { return trim(c) === ''; })) h++;
    if (h >= rows.length) return { sessions: [], messages: ['The file is empty.'], columns: {} };
    var map = mapSessionHeader(rows[h]);
    if (!hasOwn(map, 'date') && !hasOwn(map, 'tool')) {
      return { sessions: [], messages: ['No "Date" or "Tool" column found in the first row, so this does not look like a session log. Download the template to see the columns.'], columns: map };
    }
    var ignored = rows[h].filter(function (c, i) { return trim(c) !== '' && !Object.keys(map).some(function (k) { return map[k] === i; }); });
    if (ignored.length) messages.push('Columns not used: ' + ignored.map(function (c) { return '"' + trim(c) + '"'; }).join(', ') + '.');
    for (var r = h + 1; r < rows.length; r++) {
      var row = rows[r];
      if (row.every(function (c) { return trim(c) === ''; })) continue;
      var get = function (field) { return hasOwn(map, field) && map[field] < row.length ? collapse(row[map[field]].replace(/\n/g, ' ')) : ''; };
      var s = { date: '', day: null, assignment: get('assignment'), tool: get('tool'), purpose: get('purpose'), prompt: get('prompt'),
        used: get('used'), changed: get('changed'), checked: get('checked'), minutes: '', person: get('person') };
      var rawDate = get('date');
      var pd = parseDate(rawDate);
      if (pd.day !== null) {
        s.day = pd.day; s.date = isoDay(pd.day);
        if (pd.note) messages.push('Row ' + (r + 1) + ': the date "' + rawDate + '" was ' + pd.note + '.');
      } else if (rawDate !== '') {
        s.date = rawDate;
        messages.push('Row ' + (r + 1) + ': could not read the date "' + rawDate + '" (' + pd.note + '); kept as typed.');
      }
      var rawMin = get('minutes');
      if (rawMin !== '') {
        var mm = /^([0-9]{1,4})(?: ?(?:min|mins|minutes|m))?$/i.exec(rawMin);
        var hm = /^([0-9]{1,2}):([0-9]{2})$/.exec(rawMin);
        if (mm) s.minutes = String(+mm[1]);
        else if (hm) s.minutes = String(+hm[1] * 60 + +hm[2]);
        else messages.push('Row ' + (r + 1) + ': "' + rawMin + '" is not a number of minutes; left blank.');
      }
      if (!s.tool && !s.purpose && !s.date) { messages.push('Row ' + (r + 1) + ': no date, tool or purpose, so it was skipped.'); continue; }
      if (!s.tool) messages.push('Row ' + (r + 1) + ': no tool named.');
      sessions.push(s);
    }
    return { sessions: sessions, messages: messages, columns: map };
  }
  M.parseSessions = parseSessions;

  function sortSessions(list) {
    return list.slice().sort(function (a, b) {
      var da = a.day === null || a.day === undefined ? 1e9 : a.day, db = b.day === null || b.day === undefined ? 1e9 : b.day;
      return da - db || cmp(a.person || '', b.person || '') || cmp(a.tool || '', b.tool || '') || cmp(a.purpose || '', b.purpose || '');
    });
  }
  M.sortSessions = sortSessions;

  function sessionsFor(sessions, assignment) {
    var a = collapse(String(assignment || '').toLowerCase());
    if (a === '') return sessions.slice();
    var anyNamed = sessions.some(function (s) { return trim(s.assignment || '') !== ''; });
    if (!anyNamed) return sessions.slice();
    return sessions.filter(function (s) {
      var x = collapse(String(s.assignment || '').toLowerCase());
      return x === '' || x === a || x.indexOf(a) >= 0 || a.indexOf(x) >= 0;
    });
  }
  M.sessionsFor = sessionsFor;

  function sessionsCsv(sessions) {
    return csvText(SESSION_HEADER, sortSessions(sessions).map(function (s) {
      return [s.date, s.assignment, s.tool, s.purpose, s.prompt, s.used, s.changed, s.checked, s.minutes, s.person];
    }));
  }
  M.sessionsCsv = sessionsCsv;

  // ---------------------------------------------------------------- the declaration

  M.TEMPLATES = [
    { id: 'statement', name: 'Statement for a university submission' },
    { id: 'appendix', name: 'Full log for an appendix' },
    { id: 'short', name: 'Short statement for a submission box' },
    { id: 'work', name: 'Note for a manager or client' }
  ];
  M.LEVELS = [
    { id: 'none', text: 'I did not use AI tools for this work.' },
    { id: 'planning', text: 'I used AI tools for ideas and planning only; none of the AI\'s wording is in the final text.' },
    { id: 'assisted', text: 'I used AI tools to help draft and edit parts of this work, and I reviewed and changed what they produced.' },
    { id: 'integrated', text: 'AI-generated text forms part of this work, as described below, and I have checked it.' }
  ];

  function levelText(id) {
    for (var i = 0; i < M.LEVELS.length; i++) if (M.LEVELS[i].id === id) return M.LEVELS[i].text;
    return M.LEVELS[2].text;
  }

  function toolsUsed(sessions) {
    var seen = dict(), out = [];
    for (var i = 0; i < sessions.length; i++) {
      var t = trim(sessions[i].tool || '');
      if (t && !hasOwn(seen, t.toLowerCase())) { seen[t.toLowerCase()] = true; out.push(t); }
    }
    return out;
  }
  M.toolsUsed = toolsUsed;

  function sessionDate(s) { return s.day !== null && s.day !== undefined ? longDay(s.day) : (s.date || 'undated'); }

  function sessionLine(s) {
    var bits = [sessionDate(s) + ', ' + (s.tool || 'unnamed tool') + ': ' + (s.purpose || 'no purpose given') + '.'];
    if (s.prompt) bits.push('Prompt in brief: "' + s.prompt.replace(/"/g, "'") + '".');
    if (s.used) bits.push('What I used: ' + s.used.replace(/\.$/, '') + '.');
    if (s.changed) bits.push('What I changed: ' + s.changed.replace(/\.$/, '') + '.');
    if (s.checked) bits.push('What I checked: ' + s.checked.replace(/\.$/, '') + '.');
    return bits.join(' ');
  }

  // "who" is null for the first person, or the name to write in the third person.
  function changeSentence(a, who) {
    var ch = a.changes;
    if (!ch) return '';
    var c = ch.counts, mine = who === null ? 'my' : 'the';
    return 'About ' + ch.keptShare + '% of the words in ' + mine + ' final text appear word for word in the AI draft (in runs of ' +
      M.MIN_RUN + ' or more words). Of ' + mine + ' ' + plural(ch.finalSentences, 'sentence') + ', ' + c.kept + ' ' + (c.kept === 1 ? 'is' : 'are') +
      ' kept from the AI draft, ' + c.edited + ' edited, ' + c.reworded + ' reworded and ' + c.yours + ' written by ' + (who === null ? 'me' : who) + '; ' +
      plural(c.dropped, 'sentence') + ' of the AI draft ' + (c.dropped === 1 ? 'was' : 'were') + ' left out.';
  }

  function checkSentence(sum, who, hasText) {
    if (!hasText) return 'No text has been checked yet.';
    if (!sum.claims) return 'The checker found no statements in the text that needed checking.';
    var parts = [];
    if (sum.verified) parts.push(sum.verified + ' verified against a source');
    if (sum.corrected) parts.push(sum.corrected + ' corrected');
    if (sum.removed) parts.push(sum.removed + ' removed');
    var s = (who === null ? 'I' : who) + ' went through ' + plural(sum.claims, 'statement') + ' flagged for checking (' + sum.high + ' high risk, ' + sum.medium + ' medium, ' + sum.low + ' low)';
    s += parts.length ? ': ' + listAnd(parts) + '.' : '.';
    if (sum.unchecked) s += ' ' + plural(sum.unchecked, 'statement is', 'statements are') + ' not yet marked as checked' + (sum.highUnchecked ? ', including ' + sum.highUnchecked + ' high risk.' : '.');
    else s += ' None is left unchecked.';
    return s;
  }

  // Says only what the marks show: a list with flagged entries is "checked" only once each has been dealt with.
  function refSentence(sum, who) {
    if (!sum.refs) return '';
    var list = who === null ? 'my reference list' : 'the reference list';
    if (!sum.refFlagged) return 'None of the ' + plural(sum.refs, 'entry', 'entries') + ' in ' + list + ' was flagged by the checker.';
    if (sum.refResolved === sum.refFlagged) {
      return (who === null ? 'I' : who) + ' looked up by hand the ' + plural(sum.refFlagged, 'entry', 'entries') + ' in ' + list + ' (of ' + sum.refs + ') flagged for attention.';
    }
    return 'Of the ' + plural(sum.refs, 'entry', 'entries') + ' in ' + list + ', ' + sum.refFlagged + ' ' + (sum.refFlagged === 1 ? 'was' : 'were') +
      ' flagged for attention; ' + (who === null ? 'I have' : who + ' has') + ' dealt with ' + sum.refResolved + ' of them so far.';
  }

  // Builds the declaration as plain lines; Markdown and plain text are both made from these.
  function declaration(a, state) {
    var p = state.project || {};
    var tpl = p.template || 'statement';
    var all = state.sessions || [];
    var sessions = sortSessions(sessionsFor(all, p.assignment));
    var sum = summarise(a, state.checks || {}, state.refChecks || {});
    var asOf = typeof state.asOf === 'number' ? state.asOf : a.asOf;
    var dateText = p.date ? (parseDate(p.date).day !== null ? longDay(parseDate(p.date).day) : p.date) : longDay(asOf);
    var tools = toolsUsed(sessions);
    var name = trim(p.person || '');
    var assignment = trim(p.assignment || '');
    var warnings = [];
    if (!a.sentences.length) warnings.push('There is no text yet: paste the AI draft and your final version on the Your texts page.');
    if (!sessions.length) warnings.push('No sessions in the log for this assignment: add at least the session that produced the AI draft.');
    if (sum.highUnchecked) warnings.push(plural(sum.highUnchecked, 'high-risk statement is', 'high-risk statements are') + ' still unchecked. The declaration says so.');
    if (!name) warnings.push('Add your name so the declaration can be signed.');
    if (p.level === 'none' && sessions.length) warnings.push('You chose "I did not use AI tools", but your log has ' + plural(sessions.length, 'session') + ' for this work.');
    if (a.changes && (p.level === 'none' || p.level === 'planning') && a.changes.keptShare >= 10) {
      warnings.push('You chose "' + (p.level === 'none' ? 'I did not use AI tools' : 'ideas and planning only') + '", but ' + a.changes.keptShare +
        '% of your final text is the AI draft\'s wording, word for word. Choose the description that fits.');
    }
    var blocks = [];
    function para(text) { blocks.push({ type: 'p', text: text }); }
    function heading(text) { blocks.push({ type: 'h', text: text }); }
    function item(text) { blocks.push({ type: 'li', text: text }); }
    function fields(list) { blocks.push({ type: 'fields', items: list.filter(function (x) { return x[1]; }) }); }

    if (tpl === 'work') {
      heading('Note on AI use');
      fields([['Document', trim(p.title || '')], ['Prepared by', name], ['Date', dateText]]);
      para(tools.length ? 'This document was prepared with help from ' + listAnd(tools) + ', used for ' + listAnd(uniqLower(sessions.map(function (s) { return s.purpose; }).filter(Boolean))) + '.' : 'No AI tools were used to prepare this document.');
      if (a.changes) para(changeSentence(a, name || 'the author'));
      para(checkSentence(sum, name || 'The author', a.sentences.length > 0));
      if (sum.refs) para(refSentence(sum, name || 'the author'));
      para('Nothing in this note was checked online by the checking tool; the checks above were done by ' + (name || 'the author') + '.');
    } else if (tpl === 'short') {
      var bits = [levelText(p.level)];
      if (tools.length) bits.push('Tools: ' + listAnd(tools) + ' (' + plural(sessions.length, 'session') + ', ' + (sessions.length ? sessionDate(sessions[0]) + (sessions.length > 1 ? ' to ' + sessionDate(sessions[sessions.length - 1]) : '') : '') + ').');
      if (a.changes) bits.push(a.changes.keptShare + '% of my final wording appears word for word in the AI draft.');
      bits.push(sum.claims ? 'I checked ' + sum.resolved + ' of ' + plural(sum.claims, 'flagged statement') + (sum.unchecked ? ' (' + sum.unchecked + ' not yet checked).' : '.') : '');
      bits.push('I take responsibility for the content.');
      para(bits.filter(Boolean).join(' '));
    } else {
      heading('Declaration of AI use');
      fields([['Title', trim(p.title || '')], ['Assignment', assignment], ['Module or course', trim(p.course || '')], ['Institution', trim(p.institution || '')], ['Name', name], ['Date', dateText]]);
      para(levelText(p.level));
      if (sessions.length) {
        para('I used ' + listAnd(tools.length ? tools : ['AI tools']) + ' in ' + plural(sessions.length, 'session') + ':');
        for (var i = 0; i < sessions.length; i++) item(sessionLine(sessions[i]));
      }
      if (a.changes) { heading('How much of the final text is the AI\'s'); para(changeSentence(a, null)); }
      heading('What I checked');
      para(checkSentence(sum, null, a.sentences.length > 0));
      if (sum.refs) para(refSentence(sum, null));
      if (tpl === 'appendix' && a.claims.length) {
        heading('Checking log');
        var ranked = a.claims.slice().sort(function (x, y) { return y.score - x.score || x.q - y.q; });
        for (var k = 0; k < ranked.length; k++) {
          var c = ranked[k], st = statusOf(state.checks || {}, c.key), note = state.checks && state.checks[c.key] ? trim(state.checks[c.key].note || '') : '';
          item('Q' + c.q + ' (' + c.level + ' risk) "' + clip(c.text, 90) + '": ' + st + (note ? '. ' + note.replace(/\.$/, '') + '.' : '.'));
        }
      }
      para('The checking tool flags statements by simple rules on my own device; it does not check anything online and is not a plagiarism detector. I take full responsibility for the content of this work, including anything produced with AI help.');
      blocks.push({ type: 'sign', text: 'Signed: ' + (name || '____________________') + '    Date: ' + dateText });
    }
    return { template: tpl, blocks: blocks, warnings: warnings, sessions: sessions.length, summary: sum };
  }
  M.declaration = declaration;

  function uniqLower(list) {
    var seen = dict(), out = [];
    for (var i = 0; i < list.length; i++) {
      var k = list[i].toLowerCase();
      if (!hasOwn(seen, k)) { seen[k] = true; out.push(list[i].charAt(0).toLowerCase() + list[i].slice(1)); }
    }
    return out;
  }

  function clip(s, n) { return s.length > n ? trim(s.slice(0, n - 3)) + '...' : s; }
  M.clip = clip;

  function declarationText(d) {
    var out = [];
    for (var i = 0; i < d.blocks.length; i++) {
      var b = d.blocks[i];
      if (b.type === 'h') out.push(b.text.toUpperCase());
      else if (b.type === 'fields') out.push(b.items.map(function (x) { return x[0] + ': ' + x[1]; }).join('\n'));
      else if (b.type === 'li') out.push('- ' + b.text);
      else out.push(b.text);
      var next = d.blocks[i + 1];
      out.push(b.type === 'li' && next && next.type === 'li' ? '\n' : '\n\n');
    }
    return out.join('').replace(/\n+$/, '') + '\n';
  }
  M.declarationText = declarationText;

  function mdEscape(s) { return s.replace(/([\\`*_[\]#|])/g, '\\$1'); }

  function declarationMarkdown(d) {
    var out = [];
    for (var i = 0; i < d.blocks.length; i++) {
      var b = d.blocks[i];
      if (b.type === 'h') out.push((i === 0 ? '# ' : '## ') + mdEscape(b.text));
      else if (b.type === 'fields') out.push(b.items.map(function (x) { return '**' + x[0] + ':** ' + mdEscape(x[1]); }).join('  \n'));
      else if (b.type === 'li') out.push('- ' + mdEscape(b.text));
      else if (b.type === 'sign') out.push('*' + mdEscape(b.text) + '*');
      else out.push(mdEscape(b.text));
      var next = d.blocks[i + 1];
      out.push(b.type === 'li' && next && next.type === 'li' ? '\n' : '\n\n');
    }
    return out.join('').replace(/\n+$/, '') + '\n';
  }
  M.declarationMarkdown = declarationMarkdown;

  // ---------------------------------------------------------------- other files to take away

  function claimsCsv(a, checks) {
    var rows = [];
    var order = a.ranked;
    for (var i = 0; i < order.length; i++) {
      var c = a.claims[order[i] - 1];
      var ck = checks && hasOwn(checks, c.key) ? checks[c.key] : {};
      rows.push(['Q' + c.q, c.level, String(c.score), c.kinds.map(function (k) { return M.KIND_LABELS[k]; }).join('; '), c.text,
        c.checks.join(' '), c.origin, c.notes.status === 'none' ? '' : c.notes.status, statusOf(checks, c.key), ck.note || '']);
    }
    return csvText(['Query', 'Risk', 'Score', 'What it is', 'Sentence', 'What to check', 'Where it came from', 'Against your notes', 'Status', 'Source or note'], rows);
  }
  M.claimsCsv = claimsCsv;

  function refsCsv(a, refChecks) {
    var rows = a.refs.entries.map(function (r) {
      var ck = refChecks && hasOwn(refChecks, r.entry.key) ? refChecks[r.entry.key] : {};
      return [String(r.number), r.entry.text, r.entry.type, r.entry.year, r.verdict, r.issues.map(function (x) { return x.text; }).join(' '),
        String(r.cited), refStatusOf(refChecks, r.entry.key), ck.note || ''];
    });
    for (var m = 0; m < a.refs.missing.length; m++) {
      rows.push(['', a.refs.missing[m].text, 'citation', '', 'missing', 'Cited in the text but not in the reference list.' + (a.refs.missing[m].near ? ' Closest entry: ' + a.refs.missing[m].near + '.' : ''), '', '', '']);
    }
    return csvText(['Entry', 'Reference', 'Type', 'Year', 'Verdict', 'Issues', 'Times cited', 'Status', 'Note'], rows);
  }
  M.refsCsv = refsCsv;

  // The checked text with a query number after every flagged sentence, then the queries in full: a copy
  // to work from away from the page, or to hand to someone checking it with you.
  function annotatedMarkdown(a, checks, refChecks, title, asOf) {
    var byIndex = dict();
    for (var i = 0; i < a.claims.length; i++) byIndex[a.claims[i].sentence] = a.claims[i];
    var out = ['# Proof copy: ' + mdEscape(trim(title || '') || 'your text'), '',
      'Checked by me, ' + longDay(typeof asOf === 'number' ? asOf : a.asOf) + '. Each flagged statement in the ' + (a.hasFinal ? 'final version' : 'draft') +
      ' is followed by its query number; the queries are listed after the text, highest risk first. Nothing was checked online and this is not a plagiarism check.', ''];
    var para = [], cur = -1;
    function flush() { if (para.length) { out.push(para.join(' ')); out.push(''); } para = []; }
    for (var s = 0; s < a.sentences.length; s++) {
      var sent = a.sentences[s];
      if (sent.para !== cur) { flush(); cur = sent.para; }
      var c = hasOwn(byIndex, s) ? byIndex[s] : null;
      var text = mdEscape(sent.text);
      if (c) {
        var st = statusOf(checks, c.key);
        text += ' **[Qy ' + c.q + ': ' + c.level + ', ' + (st === 'unchecked' ? 'open' : st) + ']**';
      }
      para.push(text);
    }
    flush();
    if (a.claims.length) {
      var s0 = summarise(a, checks, refChecks);
      out.push('## Queries');
      out.push('');
      out.push(plural(s0.claims, 'statement') + ' flagged: ' + s0.high + ' high risk, ' + s0.medium + ' medium, ' + s0.low + ' low; ' + s0.unchecked + ' still open.');
      out.push('');
      for (var r = 0; r < a.ranked.length; r++) {
        var q = a.claims[a.ranked[r] - 1], status = statusOf(checks, q.key);
        var note = checks && hasOwn(checks, q.key) && typeof checks[q.key].note === 'string' ? trim(checks[q.key].note) : '';
        out.push('### Qy ' + q.q + ' (' + q.level + ' risk, score ' + q.score + ', ' + (status === 'unchecked' ? 'open' : status) + ')');
        out.push('');
        out.push('> ' + mdEscape(q.text));
        out.push('');
        out.push('- **What it is:** ' + q.kinds.map(function (k) { return M.KIND_LABELS[k]; }).join(', '));
        if (q.origin) out.push('- **Where it came from:** ' + { kept: 'kept word for word from the AI draft', edited: 'edited from the AI draft', reworded: 'reworded from the AI draft', yours: 'your own words' }[q.origin]);
        for (var n = 0; n < q.notes.items.length; n++) {
          var it = q.notes.items[n];
          if (it.result === 'conflict') out.push('- **Your notes disagree:** ' + mdEscape(it.note));
        }
        out.push('- **Why it is flagged:** ' + q.reasons.map(function (x) { return (x.points > 0 ? '+' : '') + x.points + ' ' + mdEscape(x.text); }).join(' '));
        out.push('- **What to check:**');
        for (var t = 0; t < q.checks.length; t++) out.push('  - ' + mdEscape(q.checks[t]));
        out.push('- **Status:** ' + (status === 'unchecked' ? 'open' : status) + (note ? ' (' + mdEscape(note) + ')' : ''));
        out.push('');
      }
    }
    var flagged = a.refs.entries.filter(function (e) { return e.verdict !== 'ok'; });
    if (flagged.length || a.refs.missing.length) {
      out.push('## References to look at');
      out.push('');
      for (var f = 0; f < flagged.length; f++) {
        var e = flagged[f], rs = refStatusOf(refChecks, e.entry.key);
        out.push('- ' + mdEscape(e.entry.text) + ' **(' + { suspect: 'look it up by hand', fix: 'needs fixing', warn: 'worth a look' }[e.verdict] + (rs !== 'unchecked' ? ', ' + rs : '') + ')** ' +
          mdEscape(e.issues.map(function (x) { return x.text; }).join(' ')));
      }
      for (var mm = 0; mm < a.refs.missing.length; mm++) out.push('- Cited in the text but not in the list: ' + mdEscape(a.refs.missing[mm].text));
      out.push('');
    }
    return out.join('\n').replace(/\n+$/, '') + '\n';
  }
  M.annotatedMarkdown = annotatedMarkdown;

  function cleanChecks(checks, allowed) {
    var out = {}, keys = Object.keys(checks || {}).sort(cmp);
    for (var i = 0; i < keys.length; i++) {
      var c = checks[keys[i]];
      if (!c || typeof c !== 'object' || allowed.indexOf(c.status) < 0 || !/^[qr][0-9a-f]{8}$/.test(keys[i])) continue;
      if (c.status === allowed[0] && !(typeof c.note === 'string' && c.note)) continue;
      var e = { status: c.status };
      if (typeof c.note === 'string' && c.note) e.note = c.note;
      if (typeof c.on === 'string' && c.on) e.on = c.on;
      if (typeof c.text === 'string' && c.text) e.text = c.text;
      out[keys[i]] = e;
    }
    return out;
  }

  // Only text and whole numbers are kept from a session; anything else becomes blank.
  function fieldText(v) {
    if (typeof v === 'string') return v;
    if (typeof v === 'number' && Math.floor(v) === v && Math.abs(v) < 1e15) return String(v);
    return '';
  }

  function cleanSession(s) {
    var out = {};
    for (var i = 0; i < SESSION_FIELDS.length; i++) out[SESSION_FIELDS[i]] = s ? fieldText(s[SESSION_FIELDS[i]]) : '';
    var pd = parseDate(out.date);
    out.day = pd.day;
    if (pd.day !== null) out.date = isoDay(pd.day);
    return out;
  }
  M.cleanSession = cleanSession;

  var PROJECT_FIELDS = ['title', 'assignment', 'course', 'institution', 'person', 'date', 'level', 'template'];

  function projectFile(state) {
    var p = state.project || {}, proj = {};
    for (var i = 0; i < PROJECT_FIELDS.length; i++) proj[PROJECT_FIELDS[i]] = String(p[PROJECT_FIELDS[i]] || '');
    var texts = state.texts || {};
    var doc = {
      format: M.FORMAT, version: M.VERSION, saved: isoDay(typeof state.asOf === 'number' ? state.asOf : daysFromCivil(2026, 11, 28)),
      project: proj,
      texts: { draft: String(texts.draft || ''), final: String(texts.final || ''), prompt: String(texts.prompt || ''),
        references: String(texts.references || ''), notes: String(texts.notes || '') },
      sessions: sortSessions((state.sessions || []).map(cleanSession)).map(function (s) {
        var o = {};
        for (var k = 0; k < SESSION_FIELDS.length; k++) o[SESSION_FIELDS[k]] = s[SESSION_FIELDS[k]];
        return o;
      }),
      checks: cleanChecks(state.checks, M.STATUSES),
      refChecks: cleanChecks(state.refChecks, M.REF_STATUSES),
      baseline: { text: state.baseline && typeof state.baseline.text === 'string' ? state.baseline.text : '',
        on: state.baseline && typeof state.baseline.on === 'string' ? state.baseline.on : '' }
    };
    return JSON.stringify(doc, null, 1) + '\n';
  }
  M.projectFile = projectFile;

  function readProject(text) {
    var data;
    try { data = JSON.parse(String(text).replace(/^\ufeff/, '')); } catch (err) {
      return { ok: false, message: 'This is not a project file: it is not valid JSON.' };
    }
    if (!data || typeof data !== 'object' || data.format !== M.FORMAT) {
      return { ok: false, message: 'This JSON file is not a Checked by me project (its "format" is missing or different).' };
    }
    if (typeof data.version !== 'number' || data.version > M.VERSION) {
      return { ok: false, message: 'This project was saved by a newer version (' + data.version + ').' };
    }
    var p = data.project && typeof data.project === 'object' ? data.project : {};
    var project = {};
    for (var i = 0; i < PROJECT_FIELDS.length; i++) project[PROJECT_FIELDS[i]] = typeof p[PROJECT_FIELDS[i]] === 'string' ? p[PROJECT_FIELDS[i]] : '';
    var t = data.texts && typeof data.texts === 'object' ? data.texts : {};
    var texts = {};
    ['draft', 'final', 'prompt', 'references', 'notes'].forEach(function (k) { texts[k] = typeof t[k] === 'string' ? t[k] : ''; });
    var sessions = Array.isArray(data.sessions) ? data.sessions.filter(function (s) { return s && typeof s === 'object' && !Array.isArray(s); }).map(cleanSession) : [];
    var b = data.baseline && typeof data.baseline === 'object' && !Array.isArray(data.baseline) ? data.baseline : null;
    return { ok: true, project: project, texts: texts, sessions: sessions,
      checks: cleanChecks(data.checks && typeof data.checks === 'object' ? data.checks : {}, M.STATUSES),
      refChecks: cleanChecks(data.refChecks && typeof data.refChecks === 'object' ? data.refChecks : {}, M.REF_STATUSES),
      saved: typeof data.saved === 'string' ? data.saved : '',
      baseline: { text: b && typeof b.text === 'string' ? b.text : '', on: b && typeof b.on === 'string' ? b.on : '' } };
  }
  M.readProject = readProject;

  // ---------------------------------------------------------------- Word files

  function xmlDecode(s) {
    return s.replace(/&(lt|gt|amp|quot|apos|#[0-9]{1,7}|#x[0-9a-fA-F]{1,6});/g, function (m0, e) {
      if (e === 'lt') return '<';
      if (e === 'gt') return '>';
      if (e === 'amp') return '&';
      if (e === 'quot') return '"';
      if (e === 'apos') return "'";
      var code = e.charAt(1) === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return code > 0 && code < 0xd800 ? String.fromCharCode(code) : (code >= 0xe000 && code < 0x10000 ? String.fromCharCode(code) : '');
    });
  }

  var DOCX_P_RE = /<w:p(?: [^>]*)?>([\s\S]*?)<\/w:p>/g;
  var DOCX_TOKEN_RE = /<w:t(?: [^>]*)?>([^<]*)<\/w:t>|<w:(?:tab|br|cr)(?: [^>]*)?\/>|<w:footnoteReference [^>]*?w:id="(-?[0-9]+)"[^>]*\/>/g;

  function docxParagraphs(xml) {
    var out = [], m;
    DOCX_P_RE.lastIndex = 0;
    while ((m = DOCX_P_RE.exec(xml)) !== null) {
      var body = m[1], text = '', t;
      DOCX_TOKEN_RE.lastIndex = 0;
      while ((t = DOCX_TOKEN_RE.exec(body)) !== null) {
        if (t[1] !== undefined) text += xmlDecode(t[1]);
        else if (t[2] !== undefined) text += '[^' + t[2] + ']';
        else text += ' ';
      }
      text = collapse(text.replace(/\n/g, ' '));
      if (text === '') { out.push(''); continue; }
      var st = /<w:pStyle w:val="([^"]*)"/.exec(body);
      var style = st ? st[1].toLowerCase().replace(/ /g, '') : '';
      var hm = /^heading([1-6])$/.exec(style);
      if (hm) text = '######'.slice(0, +hm[1]) + ' ' + text;
      else if (style === 'title') text = '# ' + text;
      else if (/<w:numPr>/.test(body) || /^listparagraph|^listbullet|^listnumber/.test(style)) text = '- ' + text;
      out.push(text);
    }
    return out;
  }

  // Turns the XML inside a .docx (the document and, if any, its footnotes) into Markdown-like text.
  function docxText(documentXml, footnotesXml) {
    var paras = docxParagraphs(String(documentXml || '')).filter(function (p) { return p !== ''; });
    var notes = [], m;
    var FN_RE = /<w:footnote (?:[^>]*? )?w:id="(-?[0-9]+)"[^>]*>([\s\S]*?)<\/w:footnote>/g;
    var fx = String(footnotesXml || '');
    while ((m = FN_RE.exec(fx)) !== null) {
      if (+m[1] <= 0) continue;
      var body = docxParagraphs(m[2]).filter(function (p) { return p !== ''; }).join(' ');
      if (body !== '') notes.push('[^' + m[1] + ']: ' + body);
    }
    return paras.join('\n\n') + (notes.length ? '\n\n' + notes.join('\n') : '') + '\n';
  }
  M.docxText = docxText;

  M.SESSION_TEMPLATE = csvText(SESSION_HEADER, [['2026-11-02', 'Module code and assignment', 'The AI tool you used', 'What you used it for',
    'Your prompt in one line', 'What you kept from its answer', 'What you changed', 'What you checked, and against what', '15', 'Your name']]);

  if (typeof module !== 'undefined' && module.exports) module.exports = M;
  else root.CheckedByMe = M;
})(typeof window !== 'undefined' ? window : this);
/* MODEL END */
