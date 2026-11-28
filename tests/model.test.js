/* Tests of the browser app's model, loaded from the built app/index.html. Run: node --test tests/ */
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'app', 'index.html'), 'utf8');
const block = html.slice(html.indexOf('/* MODEL START */'), html.indexOf('/* MODEL END */') + '/* MODEL END */'.length);
const M = (function () { const module = { exports: {} }; new Function('module', 'window', block)(module, undefined); return module.exports; })();

const data = (name) => fs.readFileSync(path.join(ROOT, 'data', name), 'utf8');
const SAMPLES = ['current-account.csv', 'credit-card.csv', 'spending-app.csv', 'messy-export.csv'];
const truth = JSON.parse(data('sample-truth.json'));
const all = () => M.analyse({ files: SAMPLES.map((n) => ({ name: n, text: data(n) })) });
const d = (s) => M.fromIso(s);

test('the model in app/index.html is the one in src/model.js', () => {
  const src = fs.readFileSync(path.join(ROOT, 'src', 'model.js'), 'utf8');
  assert.equal(block.trim(), src.trim());
});

test('amounts are read in whole pence from the ways banks write them', () => {
  const cases = {
    '-12.99': -1299, '£1,234.56': 123456, '(24.99)': -2499, '18.30 DR': -1830, '5.00 CR': 500, 'CR 5.00': 500,
    '£18.00-': -1800, '-£24.99': -2499, '12,50': 1250, '1.234,56': 123456, '+412.50': 41250, 'GBP 9.99': 999,
    '.5': 50, '10.995': 1100, '−7.50': -750, ' 3 ': 300, 'n/a': null, '': null, 'abc': null, '1-2': null, '--5': null
  };
  for (const [text, want] of Object.entries(cases)) assert.equal(M.parseAmount(text), want, text);
});

test('dates in UK, ISO, written and US forms', () => {
  assert.equal(M.iso(M.parseDate('03/10/2026', 'DMY')), '2026-10-03');
  assert.equal(M.iso(M.parseDate('03/10/2026', 'MDY')), '2026-03-10');
  assert.equal(M.iso(M.parseDate('3 Oct 26')), '2026-10-03');
  assert.equal(M.iso(M.parseDate('Thu 12 Mar 2026')), '2026-03-12');
  assert.equal(M.iso(M.parseDate('March 12, 2026')), '2026-03-12');
  assert.equal(M.iso(M.parseDate('2026-03-12T10:22:00Z')), '2026-03-12');
  assert.equal(M.iso(M.parseDate('20260312')), '2026-03-12');
  assert.equal(M.parseDate('32/10/2026', 'DMY'), null);
  assert.equal(M.parseDate('29/02/2026', 'DMY'), null);
  assert.equal(M.parseDate('TBC'), null);
  assert.equal(M.detectDateOrder(['01/02/2026', '13/02/2026']).order, 'DMY');
  assert.equal(M.detectDateOrder(['02/13/2026', '02/01/2026']).order, 'MDY');
  const amb = M.detectDateOrder(['01/02/2026', '03/04/2026']);
  assert.equal(amb.order, 'DMY');
  assert.equal(amb.ambiguous, true);
});

test('England and Wales bank holidays, including Christmas substitutes', () => {
  assert.deepEqual(M.bankHolidays(2026).map(M.iso), ['2026-01-01', '2026-04-03', '2026-04-06', '2026-05-04', '2026-05-25', '2026-08-31', '2026-12-25', '2026-12-28']);
  assert.deepEqual(M.bankHolidays(2027).map(M.iso), ['2027-01-01', '2027-03-26', '2027-03-29', '2027-05-03', '2027-05-31', '2027-08-30', '2027-12-27', '2027-12-28']);
  assert.ok(M.bankHolidays(2022).map(M.iso).includes('2022-09-19'));
  assert.equal(M.iso(M.nextWorkingDay(d('2026-12-25'))), '2026-12-29');
  assert.equal(M.iso(M.nominalInMonth(2026, 12, 'L5')), '2026-12-24');
  assert.equal(M.iso(M.nominalInMonth(2026, 2, 31)), '2026-02-28');
  assert.equal(M.iso(M.nominalInMonth(2026, 5, 'LW')), '2026-05-29');
});

test('every sample file is read, and the messy one explains each row it skips', () => {
  const out = all();
  const [cur, card, app, messy] = out.statements;
  assert.equal(cur.ok && card.ok && app.ok && messy.ok, true);
  assert.equal(cur.skipped.length + card.skipped.length + app.skipped.length, 0);
  assert.equal(card.layout.headerRow, 4, 'the header comes after four lines of account details');
  assert.equal(app.layout.mapping.out, 4);
  const reasons = messy.skipped.map((k) => k.reason);
  assert.deepEqual(reasons, ['Could not read the date "TBC"', 'Could not read the amount "n/a"', 'Could not read the date "32/10/2026"', 'A repeated header row', 'A total or balance line, not a payment']);
  assert.equal(out.merged.linked.length, 1, 'the messy re-export is recognised as the current account');
  assert.equal(messy.account, 'Current account');
  assert.equal(out.merged.duplicates, messy.transactions.length, 'every payment in the overlap is counted once');
});

test('awkward layouts: no header, semicolons with comma decimals, credit card signs, status column', () => {
  const headerless = M.parseCsv('12/01/2026,COFFEE,-3.20,100.00\n13/01/2026,RENT,-500.00,-400.00\n14/01/2026,PAY,900.00,500.00\n', 'x.csv');
  assert.equal(headerless.transactions.length, 3);
  assert.equal(headerless.transactions[1].amount, -50000);
  assert.ok(headerless.warnings[0].includes('No header row'));
  const semi = M.parseCsv('Datum;Omschrijving;Bedrag\n01-02-2026;Huur;-500,00\n02-02-2026;Koffie;-2,50\n', 'semi.csv');
  assert.equal(semi.layout.delimiter, ';');
  assert.deepEqual(semi.transactions.map((t) => t.amount), [-50000, -250]);
  const cc = M.parseCsv('Date,Description,Amount\n' + [1, 2, 3, 4, 5, 6].map((i) => '0' + i + '/03/2026,SHOP ' + i + ',' + (i * 3) + '.00').join('\n') + '\n07/03/2026,PAYMENT RECEIVED,-50.00\n', 'card.csv');
  assert.equal(cc.layout.signConvention, 'positive-out');
  assert.equal(cc.transactions.filter((t) => t.amount < 0).length, 6);
  const st = M.parseCsv('Completed Date,Description,Amount,State\n2026-03-01,A,-1.00,COMPLETED\n2026-03-02,B,-2.00,REVERTED\n2026-03-03,C,-3.00,PENDING\n', 's.csv');
  assert.equal(st.transactions.length, 1);
  assert.match(st.skipped[0].reason, /reverted/);
  assert.match(st.skipped[1].reason, /pending/);
  const quoted = M.parseCsv('Date,Description,Amount\n01/03/2026,"LINE ONE\nLINE TWO",-1.00\n02/03/2026,"SAYS ""HI""",-2.00\n', 'q.csv');
  assert.equal(quoted.transactions[0].desc, 'LINE ONE LINE TWO');
  assert.equal(quoted.transactions[1].desc, 'SAYS "HI"');
});

test('an export of mostly money in is not mistaken for a credit card', () => {
  const savings = 'Date,Description,Amount\n' + [1, 2, 3, 4, 5, 6].map((m) => '28/0' + m + '/2026,FROM CURRENT ACCOUNT,100.00').join('\n') + '\n15/06/2026,CASH OUT,-20.00\n';
  const st = M.parseCsv(savings, 'easy-saver.csv');
  assert.equal(st.layout.signConvention, 'negative-out');
  assert.equal(st.transactions.filter((t) => t.amount > 0).length, 6);
  assert.match(st.warnings[0], /read as money coming in/);
  const named = M.parseCsv(savings, 'credit-card.csv');
  assert.equal(named.layout.signConvention, 'positive-out', 'a card in the file name is enough to flip');
  assert.match(M.parseCsv('Date,Description,Amount\n', 'h.csv').error, /header row but no payments/);
});

test('files that are not statements get a plain message, not a crash', () => {
  assert.match(M.parseCsv('', 'e.csv').error, /empty/);
  assert.match(M.parseCsv('%PDF-1.7 ...', 'a.pdf').error, /PDF/);
  assert.match(M.parseCsv('{"a":1}', 'x.json').error, /JSON/);
  assert.match(M.parseCsv('PK\u0003\u0004binary', 'x.xlsx').error, /spreadsheet/);
  const nonsense = M.parseCsv('hello,world\nfoo,bar\n', 'n.csv');
  assert.equal(nonsense.ok, false);
  assert.match(nonsense.error, /date column/);
});

test('payee keys strip what changes every month', () => {
  const k = M.payeeKey;
  assert.equal(k('CARD PAYMENT TO IRONWORKS GYM ON 03 DEC'), 'IRONWORKS GYM');
  assert.equal(k('PAYPAL *PIXELBOX'), 'PIXELBOX');
  assert.equal(k('PARCELPOINT PRIME*7HG2K'), 'PARCELPOINT PRIME');
  assert.equal(k('STREAMCRATE.TV LONDON GB'), 'STREAMCRATE.TV');
  assert.equal(k('DD BRIGHTSPARK ENERGY REF 88231742'), 'BRIGHTSPARK ENERGY');
  assert.equal(k('SO TO SAVINGS 0412'), 'SAVINGS');
  assert.equal(M.categorise('STREAMCRATE.TV LONDON GB').id, 'tv');
  assert.equal(M.categorise('GADGETGUARD PHONE COVER').id, 'insurance');
  assert.equal(M.paymentMethod('DD', 'X'), 'direct debit');
  assert.equal(M.paymentMethod('', 'X SO'), 'standing order');
});

test('finds every planted regular payment in the sample and nothing else', () => {
  const r = all().result;
  const found = r.series;
  for (const want of truth.series) {
    const s = found.find((x) => x.name.toLowerCase() === want.name.toLowerCase() && (want.typical === undefined || x.typical === want.typical));
    assert.ok(s, 'missing ' + want.name);
    assert.equal(s.cadence, want.cadence, want.name);
    assert.equal(s.amounts.kind, want.kind, want.name);
    assert.equal(s.category, want.category, want.name);
    assert.equal(s.count, want.count, want.name + ' count');
    assert.equal(s.status, want.status || 'active', want.name + ' status');
    for (const f of want.flags || []) assert.ok(s.flags.some((x) => x.id === f), want.name + ' should be flagged ' + f);
  }
  // Card repayments are found too, and recognised as money between your own accounts.
  const card = found.find((s) => s.name === 'Student Card Repayment');
  assert.equal(card.category, 'savings');
  assert.equal(found.length, truth.series.length + 1, 'nothing from everyday spending is mistaken for a regular payment');
  assert.deepEqual(r.candidates.map((c) => c.name).sort(), truth.candidates.map((c) => c.name).sort());
  assert.equal(r.income.length, 1);
  assert.equal(M.iso(r.payday.next), '2026-12-24', 'the last Friday of December is Christmas Day, so pay comes on the 24th');
});

test('forecasts roll direct debits and standing orders past weekends and bank holidays', () => {
  const r = all().result;
  const byName = (n) => r.series.find((s) => s.name === n);
  assert.equal(M.iso(byName('Savings Transfer').nextDue), '2026-11-30', '28 Nov 2026 is a Saturday');
  const fc = M.forecast(r, 70);
  const rentJan = fc.find((it) => it.name === 'Harbour Lettings Rent' && M.iso(it.day).startsWith('2027-01'));
  assert.equal(M.iso(rentJan.day), '2027-01-04', '1 Jan is a bank holiday and 2 to 3 Jan a weekend');
  const gymJan = fc.find((it) => it.name === 'Ironworks Gym' && M.iso(it.day).startsWith('2027-01'));
  assert.equal(M.iso(gymJan.day), '2027-01-03', 'card payments are not rolled');
  const energyDec = fc.find((it) => it.name === 'Brightspark Energy' && M.iso(it.day).startsWith('2026-12'));
  assert.equal(energyDec.amount, byName('Brightspark Energy').payments[0].amount, 'a variable bill uses last December\'s amount');
});

test('weekly costs are converted to months through the year, not times four', () => {
  assert.equal(M.monthlyCost(1550, 'weekly'), 6717);
  assert.equal(M.monthlyCost(900, 'four-weekly'), 975);
  assert.equal(M.annualCost(899, 'monthly'), 10788);
});

test('the plan totals what cancelling saves and sets cancel-by dates before the next payment', () => {
  const r = all().result;
  const id = (n) => r.series.find((s) => s.name === n).id;
  const decisions = { [id('Ironworks Gym')]: { decision: 'cancel' }, [id('Harbour Lettings Rent')]: { decision: 'keep' }, [id('Savings Transfer')]: { decision: 'ignore' } };
  const p = M.plan(r, decisions);
  assert.equal(p.totals.cancelMonthly, 2499);
  assert.equal(p.totals.cancelAnnual, 29988);
  assert.equal(p.totals.cancelNext12, 2499 * 12);
  assert.equal(p.actions.length, 1);
  assert.equal(M.iso(p.actions[0].cancelBy), '2026-12-01', 'two days before the card payment on 3 Dec');
  assert.match(p.actions[0].message, /Please cancel my Ironworks Gym membership/);
  const noSavings = M.plan(r, {}).totals;
  assert.equal(noSavings.monthly - p.totals.monthly, 0, 'savings were never counted as a cost');
});

test('reopening a review spots payments still taken after you cancelled', () => {
  const r = all().result;
  const id = r.series.find((s) => s.name === 'Gadgetguard Phone Cover').id;
  const since = M.sinceLastReview(r, { reviewedOn: '2026-10-20', known: { [id]: { typical: 499, status: 'active', kind: 'fixed' } }, decisions: { [id]: { decision: 'cancel', decidedOn: '2026-10-20' } } });
  assert.equal(since.stillCharging.length, 1);
  assert.equal(M.iso(since.stillCharging[0].payments[0].day), '2026-11-08');
  assert.ok(since.newSince.length > 0);
});

test('the register, budget and calendar files are well formed', () => {
  const r = all().result;
  const reg = M.registerCsv(r, {});
  assert.ok(reg.startsWith('﻿Name,Category,Paid by'));
  assert.equal(reg.trim().split('\r\n').length, r.series.length + 1);
  const budget = M.budgetCsv(r, {}, 12).trim().split('\r\n');
  assert.equal(budget[0].split(',').length, 14);
  assert.ok(budget[budget.length - 1].startsWith('Total,'));
  const ics = M.buildIcs(r, {}, { days: 92 });
  const lines = ics.text.split('\r\n');
  assert.equal(lines[0], 'BEGIN:VCALENDAR');
  assert.equal(lines.filter((l) => l === 'BEGIN:VEVENT').length, ics.events);
  assert.equal(lines.filter((l) => l === 'BEGIN:VEVENT').length, lines.filter((l) => l === 'END:VEVENT').length);
  for (const l of lines) assert.ok(Buffer.byteLength(l, 'utf8') <= 75, 'line too long: ' + l);
  assert.ok(ics.text.includes('DTSTART;VALUE=DATE:20261201'));
});

test('a saved review reopens with the same payments and decisions', () => {
  const out = all();
  const decisions = { [out.result.series[0].id]: { decision: 'keep', note: 'Fine, for now', decidedOn: d('2026-11-28') } };
  const text = M.projectFile({ transactions: out.merged.transactions, result: out.result, decisions, accounts: out.merged.accounts });
  const back = M.readProject(text);
  assert.equal(back.transactions.length, out.merged.transactions.length);
  assert.equal(back.decisions[out.result.series[0].id].note, 'Fine, for now');
  const again = M.analyse({ files: [], extra: back.transactions });
  assert.deepEqual(M.summary(again.result), M.summary(out.result));
  assert.match(M.readProject('not json').error, /not valid JSON/);
  assert.match(M.readProject('{"format":"other"}').error, /not a Still paying review/);
});

test('your own transfers between accounts are not counted as spending', () => {
  const a = 'Date,Description,Amount\n' + ['01', '02', '03'].map((m) => '05/' + m + '/2026,TO MY SAVINGS,-100.00').join('\n') + '\n';
  const b = 'Date,Description,Amount\n' + ['01', '02', '03'].map((m) => '05/' + m + '/2026,FROM CURRENT,100.00').join('\n') + '\n';
  const out = M.analyse({ files: [{ name: 'a.csv', text: a, account: 'Current' }, { name: 'b.csv', text: b, account: 'Saver' }] });
  assert.equal(out.result.transferCount, 6);
  assert.equal(out.result.series[0].category, 'savings');
  assert.equal(out.result.income.length, 0);
});

test('a large export stays quick', () => {
  const rows = ['Date,Description,Amount'];
  let day = d('2023-01-01');
  for (let i = 0; i < 30000; i++) {
    const p = M.ymd(day + Math.floor(i / 25));
    rows.push(p.d + '/' + p.m + '/' + p.y + ',SHOP ' + (i % 400) + ',-' + (1 + (i % 50)) + '.' + String(i % 100).padStart(2, '0'));
  }
  const t0 = Date.now();
  const out = M.analyse({ files: [{ name: 'big.csv', text: rows.join('\n') }] });
  assert.equal(out.statements[0].transactions.length, 30000);
  assert.ok(Date.now() - t0 < 8000, 'took ' + (Date.now() - t0) + ' ms');
});
