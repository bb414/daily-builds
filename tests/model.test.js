'use strict';
/* Tests of the browser model, run with: node --test tests/ */

var test = require('node:test');
var assert = require('node:assert/strict');
var fs = require('fs');
var path = require('path');

var ROOT = path.resolve(__dirname, '..');
var M = require(path.join(ROOT, 'src', 'model.js'));

function data(name) { return fs.readFileSync(path.join(ROOT, 'data', name), 'utf8'); }
function run(files, tweak) {
  var st = M.emptyState();
  if (tweak) tweak(st);
  var imp = M.importFiles(st, files);
  return { state: imp.state, reports: imp.reports, result: M.analyse(imp.state) };
}
function csv(lines) { return lines.join('\n') + '\n'; }
var HEAD = 'Date,Time,Account,Symbol,Side,Quantity,Price,Commission,Order ID';

test('delimited text: quotes, doubled quotes, line breaks in quotes, a byte order mark and CRLF', function () {
  var p = M.parseDelimited('\ufeffa,"b, c","say ""hi"""\r\n1,"two\nlines",3\r\n', ',');
  assert.deepEqual(p.rows, [['a', 'b, c', 'say "hi"'], ['1', 'two\nlines', '3']]);
  assert.deepEqual(p.lines, [1, 2]);
  assert.equal(M.sniffDelimiter('a;b;c\n1;2;3\n'), ';');
  assert.equal(M.sniffDelimiter('a\tb\tc\n1\t2\t3\n'), '\t');
  assert.equal(M.sniffDelimiter('a,"x;y",c\n1,2,3\n'), ',');
});

test('numbers: currency signs, separators, brackets, trailing minus and pence', function () {
  assert.equal(M.parseCents('$1,234.50'), 123450);
  assert.equal(M.parseCents('-$2.04'), -204);
  assert.equal(M.parseCents('$-2.04'), -204);
  assert.equal(M.parseCents('(12.345)'), -1235);
  assert.equal(M.parseCents('12.34-'), -1234);
  assert.equal(M.parseCents('GBP 5.95'), 595);
  assert.equal(M.parseCents('5.95 GBP'), 595);
  assert.equal(M.parseCents('1 234,5'), 123450);
  assert.equal(M.parseCents('abc'), null);
  assert.equal(M.parseMicro('5,112.25'), 5112250000);
  assert.equal(M.readNumber('412.5p').pence, true);
  assert.equal(M.readNumber('1.234,56', true).int, '1234');
  assert.equal(M.parseFloatText('2.5'), 2.5);
});

test('dates and times in ISO, UK, US, compact and named-month forms', function () {
  var d = M.fromIso('2026-10-07');
  assert.deepEqual(M.parseDateTime('2026-10-07', 'DMY'), { day: d, sec: null });
  assert.deepEqual(M.parseDateTime('07/10/2026 09:31', 'DMY'), { day: d, sec: 9 * 3600 + 31 * 60 });
  assert.deepEqual(M.parseDateTime('10/07/2026 9:31:04 PM', 'MDY'), { day: d, sec: 21 * 3600 + 31 * 60 + 4 });
  assert.deepEqual(M.parseDateTime('2026-10-07, 14:05:00', 'DMY'), { day: d, sec: 14 * 3600 + 5 * 60 });
  assert.deepEqual(M.parseDateTime('20261007;140500', 'DMY'), { day: d, sec: 14 * 3600 + 5 * 60 });
  assert.deepEqual(M.parseDateTime('Wed 7 Oct 2026 12:00 AM', 'DMY'), { day: d, sec: 0 });
  assert.deepEqual(M.parseDateTime('Oct 7, 2026', 'DMY'), { day: d, sec: null });
  assert.deepEqual(M.parseDateTime('2026-10-07T14:05:00.250Z', 'DMY'), { day: d, sec: 14 * 3600 + 5 * 60 });
  assert.equal(M.parseDateTime('31/02/2026', 'DMY'), null);
  assert.equal(M.parseDateTime('07/10/2026 25:00', 'DMY'), null);
  assert.equal(M.detectDateOrder(['07/10/2026', '19/10/2026']), 'DMY');
  assert.equal(M.detectDateOrder(['10/07/2026', '10/19/2026']), 'MDY');
  assert.equal(M.detectDateOrder(['01/02/2026']), '');
  assert.equal(M.detectDateOrder(['13/01/2026', '01/13/2026']), 'MIXED');
  assert.equal(M.weekday(M.fromIso('2026-11-23')), 0);
  assert.equal(M.toIso(M.weekStart(M.fromIso('2026-11-29'))), '2026-11-23');
});

test('sides from words, codes and markers', function () {
  assert.deepEqual(M.classifySide('Buy'), { side: 'B', intent: '' });
  assert.deepEqual(M.classifySide('SLD'), { side: 'S', intent: '' });
  assert.deepEqual(M.classifySide('Sell Short'), { side: 'S', intent: 'open' });
  assert.deepEqual(M.classifySide('Buy to Cover'), { side: 'B', intent: 'close' });
  assert.deepEqual(M.classifySide('Bought'), { side: 'B', intent: '' });
  assert.deepEqual(M.classifySide('Market sell'), { side: 'S', intent: '' });
  assert.equal(M.classifySide('Dividend'), null);
  assert.equal(M.symbolRoot('LKFZ6'), 'LKF');
  assert.equal(M.symbolRoot('LKF DEC26'), 'LKF');
  assert.equal(M.symbolRoot('HGRB'), '');
  assert.equal(M.cleanAccountName('trade-history-2026-11-27.csv'), 'Trade history');
  assert.equal(M.cleanAccountName('2026-11-27.csv'), 'Main account');
});

test('the messy futures export: partial fills, fee rows, cancelled orders, a repeated header and a total row', function () {
  var rep = M.readExport('futures-messy.csv', data('futures-messy.csv'), {});
  assert.equal(rep.ok, true);
  assert.equal(rep.dateOrder, 'MDY');
  assert.equal(rep.counts.fills, 135);
  assert.equal(rep.counts.fees, 58);
  var reasons = rep.skipped.map(function (s) { return s.reason; });
  assert.ok(reasons.indexOf('repeated header row') >= 0);
  assert.ok(reasons.indexOf('total row, not a fill') >= 0);
  assert.ok(reasons.indexOf('order cancelled, nothing filled') >= 0);
  assert.equal(rep.columns.price, 'Avg Fill Price');
  assert.ok(rep.fills.every(function (f) { return f.currency === 'USD' && f.fee > 0; }));
  assert.equal(rep.fills[0].price, 5093500000);
});

test('the UK dealing account: prices in pence, two fee columns, newest-first rows and no account column', function () {
  var rep = M.readExport('dealing-account.csv', data('dealing-account.csv'), {});
  assert.equal(rep.account, 'Dealing account');
  assert.ok(rep.notes.some(function (n) { return /newest first/.test(n); }));
  var first = rep.fills[0];
  assert.equal(M.toIso(first.day), '2026-09-23');
  assert.equal(first.price, 4180000);          // 418.0p is GBP 4.18
  assert.equal(first.currency, 'GBP');
  assert.equal(first.fee, 595);
  var bought = rep.fills.filter(function (f) { return f.side === 'B'; })[0];
  assert.ok(bought.fee > 595, 'stamp duty is added to the commission on purchases');
});

test('files that cannot be read get a plain reason', function () {
  assert.match(M.readExport('a.csv', '', {}).error, /empty/);
  assert.match(M.readExport('a.json', '{"app":"round-trips","fills":[]}', {}).error, /journal file/);
  assert.match(M.readExport('a.csv', 'Name,Score\nA,1\n', {}).error, /header row/);
  var rep = M.readExport('a.csv', csv([HEAD, '2026-11-23,10:00:00,A,HGRB,Hold,10,1.00,0,1', '2026-11-23,10:00:00,A,HGRB,Buy,ten,1.00,0,1']), {});
  assert.deepEqual(rep.skipped.map(function (s) { return s.reason; }), ['buy or sell not recognised: Hold', 'quantity not recognised: ten']);
});

test('scaling in and out, matched first in, first out, with adding to a loser caught', function () {
  var r = run([{ name: 'a.csv', text: csv([HEAD,
    '2026-11-23,09:41:05,A,HGRB,Buy,300,41.27,1.50,1',
    '2026-11-23,09:50:00,A,HGRB,Buy,200,41.10,1.00,2',
    '2026-11-23,10:12:44,A,HGRB,Sell,250,41.90,1.25,3',
    '2026-11-23,10:40:00,A,HGRB,Sell,250,41.60,1.25,4']) }]).result;
  assert.equal(r.closed.length, 1);
  var t = r.closed[0];
  assert.equal(t.gross, 27400);
  assert.equal(t.fees, 500);
  assert.equal(t.net, 26900);
  assert.equal(t.maxPos, 500 * M.QTY_SCALE);
  assert.equal(t.entryOrders, 2);
  assert.equal(t.exitOrders, 2);
  assert.deepEqual(t.matches.map(function (m) { return m.pnl; }), [15750, 1650, 10000]);
  assert.equal(t.holdSec, 59 * 60 - 5);
  assert.equal(t.adds.length, 1);
  assert.equal(t.adds[0].worse, true);
  assert.ok(r.breaches.some(function (b) { return b.rule === 'noAddingToLoser'; }));
});

test('partial fills of one order are one entry, not an add', function () {
  var r = run([{ name: 'a.csv', text: csv([HEAD,
    '2026-11-23,09:41:05,A,HGRB,Buy,300,41.27,1.50,7',
    '2026-11-23,09:41:06,A,HGRB,Buy,200,41.20,1.00,7',
    '2026-11-23,10:12:44,A,HGRB,Sell,500,41.90,2.50,8']) }]).result;
  var t = r.closed[0];
  assert.equal(t.entryOrders, 1);
  assert.equal(t.adds.length, 0);
  assert.deepEqual(t.legs.map(function (l) { return l.role; }), ['open', 'open', 'close']);
});

test('shorts, a reversal through zero, and covers with nothing to cover', function () {
  var r = run([{ name: 'a.csv', text: csv([HEAD,
    '2026-11-23,11:02:10,A,PLMB,Sell Short,400,18.62,2.00,1',
    '2026-11-23,11:40:31,A,PLMB,Buy to Cover,400,18.31,2.00,2',
    '2026-11-23,12:00:00,A,PLMB,Buy to Cover,100,18.00,1.00,3']) }]).result;
  assert.equal(r.closed.length, 1);
  assert.equal(r.closed[0].dir, -1);
  assert.equal(r.closed[0].gross, 12400);
  assert.equal(r.unmatched.length, 1);
  var rev = run([{ name: 'b.csv', text: csv(['Date,Symbol,Quantity,Price', '2026-11-23,QX,10,5', '2026-11-23,QX,-15,6', '2026-11-24,QX,5,4']) }]).result;
  assert.equal(rev.closed.length, 2);
  assert.equal(rev.closed[0].gross, 1000);
  assert.equal(rev.closed[1].dir, -1);
  assert.equal(rev.closed[1].reversal, true);
  assert.equal(rev.closed[1].gross, 1000);
});

test('a long-only account treats a sale from nothing as shares bought before the export', function () {
  var text = csv(['Date,Symbol,Side,Quantity,Price', '2026-11-23,WMRU,Sell,100,4.10', '2026-11-24,WMRU,Buy,100,4.00', '2026-11-25,WMRU,Sell,100,4.20']);
  var plain = run([{ name: 'uk.csv', text: text }]).result;
  assert.equal(plain.closed.length, 1);
  assert.equal(plain.open.length, 1, 'without long-only the first sale opens a short');
  var r = run([{ name: 'uk.csv', text: text }], function (st) { st.settings.accounts = [{ name: 'Uk', start: '', longOnly: true }]; }).result;
  assert.equal(r.unmatched.length, 1);
  assert.equal(r.closed.length, 1);
  assert.equal(r.closed[0].gross, 2000);
});

test('fee rows attach to their order, multipliers apply by contract root, and the stop gives risk and R', function () {
  var text = csv(['Order,Time,Instrument,B/S,Type,Qty,Price,Fees',
    'F1,10/19/2026 9:31:04 AM,LKFZ6,Buy,Trade,2,"5,112.25",$4.08',
    'F1,10/19/2026 9:31:05 AM,LKFZ6,,Exchange fee,,,$2.40',
    'F2,10/19/2026 9:45:00 AM,LKFZ6,Buy,Trade,1,"5,108.00",$2.04',
    'F3,10/19/2026 10:02:00 AM,LKFZ6,Sell,Trade,3,"5,120.00",$6.12']);
  var r = run([{ name: 'f.csv', text: text }], function (st) {
    st.settings.multipliers = [{ symbol: 'LKF', value: '20' }];
    st.journal = M.setJournal([], 'F|LKFZ6|2026-10-19T09:31:04', { stop: '5104.25', mistakes: ['Added to a loser'] });
    st.settings.accounts = [{ name: 'F', start: '50000', longOnly: false }];
  }).result;
  var t = r.closed[0];
  assert.equal(t.id, 'F|LKFZ6|2026-10-19T09:31:04');
  assert.equal(t.mult, 20);
  assert.equal(t.fees, 408 + 240 + 204 + 612);
  assert.equal(t.gross, (7.75 * 2 + 12 * 1) * 20 * 100);
  assert.equal(t.initialRisk, 8 * 2 * 20 * 100);
  assert.equal(t.maxRisk, (8 * 2 + 3.75) * 20 * 100);
  assert.equal(t.plannedRisk, 32000);
  assert.equal(Math.round(t.r * 1000) / 1000, Math.round(t.net / 32000 * 1000) / 1000);
  assert.deepEqual(r.warnings, []);
  var warn = run([{ name: 'f.csv', text: text }]).result.warnings;
  assert.ok(warn.some(function (w) { return w.kind === 'mult'; }));
});

test('statistics: win rate, expectancy, profit factor, streaks and drawdown', function () {
  var lines = [HEAD];
  var pnl = [100, -50, -50, 200, -300, 50];
  pnl.forEach(function (p, i) {
    var day = '2026-11-' + (23 + Math.floor(i / 2));
    lines.push(day + ',1' + i + ':00:00,A,QX,Buy,1,100,0,o' + i);
    lines.push(day + ',1' + i + ':30:00,A,QX,Sell,1,' + (100 + p / 100).toFixed(2) + ',0,c' + i);
  });
  var r = run([{ name: 'a.csv', text: csv(lines) }], function (st) { st.settings.accounts = [{ name: 'A', start: '1000', longOnly: false }]; }).result;
  var s = M.stats(r.closed, { start: 100000 });
  assert.equal(s.n, 6);
  assert.equal(s.wins, 3);
  assert.equal(s.net, -50);
  assert.equal(s.grossWin, 350);
  assert.equal(s.grossLoss, 400);
  assert.equal(s.profitFactor, 350 / 400);
  assert.equal(s.expectancy, -50 / 6);
  assert.equal(s.maxLossStreak, 2);
  assert.equal(s.maxDD, 300);       // from +200 down to -100
  assert.equal(s.curve.length, 6);
  var rows = M.breakdown(r.closed, 'weekday');
  assert.deepEqual(rows.map(function (x) { return x.label; }), ['Monday', 'Tuesday', 'Wednesday']);
  assert.equal(M.weekly(r.closed).length, 1);
  var h = M.rHistogram(r.closed);
  assert.equal(h.length, 14);
});

test('rules: trades per day and a daily loss limit in money', function () {
  var lines = [HEAD];
  for (var i = 0; i < 4; i++) {
    lines.push('2026-11-23,1' + i + ':00:00,A,QX,Buy,10,100,1.00,o' + i);
    lines.push('2026-11-23,1' + i + ':10:00,A,QX,Sell,10,98,1.00,c' + i);
  }
  var r = run([{ name: 'a.csv', text: csv(lines) }], function (st) {
    st.settings.rules.maxTradesPerDay.value = '3';
    st.settings.rules.maxDailyLoss = { on: true, value: '50', unit: 'money' };
  }).result;
  var byRule = {};
  r.breaches.forEach(function (b) { byRule[b.rule] = (byRule[b.rule] || 0) + 1; });
  assert.equal(byRule.maxTradesPerDay, 1);
  assert.equal(byRule.maxDailyLoss, 2, 'the day itself, and the trade opened after the limit was hit');
  assert.equal(byRule.needPlannedRisk, 4);
  var sum = r.ruleSummary.filter(function (x) { return x.id === 'maxRiskPct'; })[0];
  assert.equal(sum.unchecked, 4);
});

test('adding next week\'s export skips the fills already in the journal', function () {
  var a = data('weekly/export-2026-11-20.csv'), b = data('weekly/export-2026-11-27.csv');
  var one = M.importFiles(M.emptyState(), [{ name: 'a.csv', text: a }]);
  var two = M.importFiles(one.state, [{ name: 'b.csv', text: b }]);
  var again = M.importFiles(two.state, [{ name: 'b-again.csv', text: b }]);
  var full = M.importFiles(M.emptyState(), [{ name: 'full.csv', text: data('challenge-equities.csv') }]);
  assert.ok(two.reports[0].duplicates > 0);
  assert.equal(two.state.fills.length, full.state.fills.length);
  assert.equal(again.reports[0].added, 0);
  var x = M.analyse(two.state), y = M.analyse(full.state);
  assert.equal(M.stats(x.closed).net, M.stats(y.closed).net);
});

test('the journal file reopens exactly, keeps the notes and refuses other files', function () {
  var pr = M.readProject(data('sample-journal.json'));
  assert.equal(pr.ok, true);
  var st = M.importFiles(pr.state, [{ name: 'challenge-equities.csv', text: data('challenge-equities.csv') }]).state;
  var text = M.projectFile(st, '2026-11-28');
  var back = M.readProject(text);
  assert.equal(M.projectFile(back.state, '2026-11-28'), text);
  assert.equal(back.state.journal.length, pr.state.journal.length);
  assert.equal(M.readProject('not json').ok, false);
  assert.equal(M.readProject('{"app":"other"}').ok, false);
  var damaged = JSON.parse(text);
  damaged.fills[0].side = 'X';
  assert.match(M.readProject(JSON.stringify(damaged)).error, /1 damaged/);
});

test('the sample opens with the figures the README quotes', function () {
  var pr = M.readProject(data('sample-journal.json'));
  var imp = M.importFiles(pr.state, ['challenge-equities.csv', 'futures-messy.csv', 'dealing-account.csv'].map(function (n) { return { name: n, text: data(n) }; }));
  var r = M.analyse(imp.state);
  assert.equal(r.closed.length, 237);
  assert.equal(r.open.length, 1);
  assert.equal(r.unmatched.length, 1);
  var s = M.stats(r.closed, { start: M.startBalance(r, r.accounts) });
  assert.equal(s.net, 712174);
  var rv = M.weekReview(r, { week: M.fromIso('2026-11-23') });
  assert.equal(rv.stats.n, 21);
  assert.equal(rv.stats.net, 159571);
  var text = M.reviewText(rv, r);
  assert.match(text, /^WEEKLY TRADE REVIEW: w\/c 23 Nov 2026/);
  assert.match(text, /Not financial advice\.\n$/);
});

test('position size: risk budget, fees, steps, a short and the day\'s allowance', function () {
  var p = M.positionSize({ equity: '100000', riskPct: '1', entry: '41.20', stop: '40.85', fee: '0.01' });
  assert.equal(p.ok, true);
  assert.equal(p.direction, 'long');
  assert.equal(p.units, 2777);
  assert.ok(p.risk <= 100000);
  assert.deepEqual(p.targets.map(function (t) { return M.fmtPrice(t.price); }), ['41.55', '41.90', '42.25']);
  var f = M.positionSize({ equity: '50000', riskPct: '1', entry: '5112.25', stop: '5120.25', mult: '20', allowance: '250' });
  assert.equal(f.direction, 'short');
  assert.equal(f.units, 1);
  assert.equal(f.limitedBy, 'allowance');
  assert.equal(M.positionSize({ equity: '1000', riskPct: '1', entry: '100', stop: '50' }).ok, false);
  assert.equal(M.positionSize({ equity: '', riskPct: '1', entry: '1', stop: '2' }).msg, 'Enter the account size.');
});

test('files: the template reads back, the CSVs quote what they must, and formats are fixed', function () {
  var r = run([{ name: 'template.csv', text: M.templateCsv() }]).result;
  assert.equal(r.closed.length, 3);
  assert.equal(data('template.csv'), M.templateCsv());
  var out = M.tradesCsv(r);
  assert.equal(out.charAt(0), '\ufeff');
  assert.equal(out.split('\r\n').length, 5);
  assert.equal(M.csvCell('a,b'), '"a,b"');
  assert.equal(M.csvCell('say "x"'), '"say ""x"""');
  assert.equal(M.money(-123456, 'USD'), '-$1,234.56');
  assert.equal(M.money(5, 'GBP', { sign: true }), '+£0.05');
  assert.equal(M.money(12345, 'CHF'), 'CHF 123.45');
  assert.equal(M.fmtNum(0.125, 2), '0.13');
  assert.equal(M.fmtNum(-2.5, 0), '-3');
  assert.equal(M.fmtPrice(4512250000), '4512.25');
  assert.equal(M.fmtQty(2500000), '2.5');
  assert.equal(M.fmtDuration(7385), '2 h 03 min');
  assert.equal(M.fmtR(1.2345), '+1.23R');
});

test('columns chosen by hand: an unknown layout, and overriding a wrong guess', function () {
  var text = csv(['Exported by desk', 'When,Code,Way,Lots,At,Charge', '23/11/2026 09:00,QX,B,2,10.00,0.50', '23/11/2026 10:00,QX,S,2,10.40,0.50']);
  var auto = M.readExport('odd.csv', text, {});
  assert.equal(auto.ok, false);
  assert.deepEqual(auto.headerCells, ['When', 'Code', 'Way', 'Lots', 'At', 'Charge']);
  var cols = { date: 'When', symbol: 'Code', side: 'Way', qty: 'Lots', price: 'At', fees: 'Charge' };
  var rep = M.readExport('odd.csv', text, { columns: cols });
  assert.equal(rep.ok, true);
  assert.equal(rep.headerLine, 2);
  assert.equal(rep.fills.length, 2);
  assert.equal(rep.fills[0].fee, 50);
  var r = run([{ name: 'odd.csv', text: text, columns: cols }]).result;
  assert.equal(r.closed[0].net, 80 - 100);
  var none = M.readExport('odd.csv', text, { columns: { date: 'When', symbol: 'Code', side: 'Way', qty: 'Lots', price: 'At', fees: '' } });
  assert.equal(none.fills[0].fee, 0);
  assert.match(M.readExport('odd.csv', text, { columns: { date: 'Nope' } }).error, /columns you chose/);
});

test('an opening position typed in for a close with no opening fill', function () {
  var text = csv(['Date,Symbol,Side,Quantity,Price', '2026-11-23,WMRU,Sell,100,4.10']);
  var st = M.emptyState();
  st.settings.accounts = [{ name: 'Uk', start: '', longOnly: true }];
  var r = run([{ name: 'uk.csv', text: text }], function (s) { s.settings = st.settings; }).result;
  assert.equal(r.unmatched.length, 1);
  assert.equal(M.makeCarry(r.unmatched[0], '2026-11-24', '4.00').ok, false);
  assert.equal(M.makeCarry(r.unmatched[0], '2026-11-01', '').ok, false);
  var made = M.makeCarry(r.unmatched[0], '2026-11-02', '4.00');
  assert.equal(made.ok, true);
  assert.equal(made.carry.side, 'B');
  var r2 = run([{ name: 'uk.csv', text: text }], function (s) { s.settings = st.settings; s.carry = [made.carry]; }).result;
  assert.equal(r2.unmatched.length, 0);
  assert.equal(r2.closed.length, 1);
  assert.equal(r2.closed[0].gross, 1000);
  assert.equal(r2.closed[0].openDay, M.fromIso('2026-11-02'));
  var saved = M.projectFile(M.importFiles((function () { var s = M.emptyState(); s.carry = [made.carry]; return s; })(), [{ name: 'uk.csv', text: text }]).state, '2026-11-28');
  assert.equal(M.readProject(saved).state.carry.length, 1);
});

test('no em dashes in the model or the text it writes', function () {
  var src = fs.readFileSync(path.join(ROOT, 'src', 'model.js'), 'utf8');
  assert.equal(src.indexOf('\u2014'), -1);
});
