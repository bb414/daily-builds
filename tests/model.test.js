/* Tests of the browser model, run with: node --test tests/ */
'use strict';

var test = require('node:test');
var assert = require('node:assert');
var fs = require('fs');
var path = require('path');

var ROOT = path.resolve(__dirname, '..');
function loadModel() {
  var html = fs.readFileSync(path.join(ROOT, 'app', 'index.html'), 'utf8');
  var start = html.indexOf('/* MODEL START */'), end = html.indexOf('/* MODEL END */');
  var mod = { exports: {} };
  new Function('module', 'exports', html.slice(start, end))(mod, mod.exports);
  return mod.exports;
}
var M = loadModel();
var AS_OF = M.daysFromCivil(2026, 11, 28);
function sample(name) { return fs.readFileSync(path.join(ROOT, 'data', name), 'utf8'); }
function sampleInput(extra) {
  return Object.assign({ draft: sample('ai-draft.md'), final: sample('final-version.md'), notes: sample('notes.md'), prompt: sample('prompt.txt'), asOf: AS_OF }, extra || {});
}
var truth = JSON.parse(sample('sample-truth.json'));
function claimWith(a, phrase) { return a.claims.filter(function (c) { return c.text.indexOf(phrase) >= 0; })[0]; }

test('the model block in the built page is the same as src/model.js', function () {
  var html = fs.readFileSync(path.join(ROOT, 'app', 'index.html'), 'utf8');
  assert.ok(html.indexOf(fs.readFileSync(path.join(ROOT, 'src', 'model.js'), 'utf8').trim()) >= 0);
});

test('dates: day numbers round-trip and UK dates are read day first', function () {
  for (var d = -800; d < 30000; d += 97) assert.strictEqual(M.daysFromCivil.apply(null, M.civilFromDays(d)), d);
  assert.strictEqual(M.isoDay(M.parseDate('05/11/2026').day), '2026-11-05');
  assert.strictEqual(M.isoDay(M.parseDate('5 Nov 2026').day), '2026-11-05');
  assert.strictEqual(M.isoDay(M.parseDate('Thursday, 5th November 2026').day), '2026-11-05');
  assert.deepStrictEqual(M.parseDate('11/25/2026'), { day: M.daysFromCivil(2026, 11, 25), note: 'read as month first' });
  assert.strictEqual(M.parseDate('31/13/2026').day, null);
  assert.strictEqual(M.parseDate('29/02/2027').day, null);
  assert.strictEqual(M.longDay(AS_OF), '28 November 2026');
});

test('CSV: quotes, delimiters, a byte order mark and spreadsheet formulas', function () {
  var r = M.parseCsv('\ufeffa;b\r\n"x; y";"he said ""hi"""\r\n');
  assert.strictEqual(r.delimiter, ';');
  assert.deepStrictEqual(r.rows, [['a', 'b'], ['x; y', 'he said "hi"']]);
  var out = M.csvText(['A', 'B'], [['=SUM(1)', 'plain'], ['-x', '-5']]);
  assert.ok(out.indexOf("'=SUM(1)") > 0 && out.indexOf("'-x") > 0 && out.indexOf(',-5') > 0);
  assert.strictEqual(out.charCodeAt(0), 0xfeff);
});

test('cleaning a messy paste counts what it tidied and keeps the words', function () {
  var doc = M.readDocument(sample('messy-paste.txt'));
  assert.ok(doc.cleaning.quotes >= 8 && doc.cleaning.markdown >= 8 && doc.cleaning.footnotes >= 2 && doc.cleaning.invisible >= 1);
  assert.strictEqual(doc.refHeading, 'References');
  assert.strictEqual(doc.footnotes.length, 1);
  var text = doc.blocks.map(function (b) { return b.text; }).join(' ');
  assert.ok(text.indexOf('**') < 0 && text.indexOf('\u2019') < 0 && text.indexOf('\u00a0') < 0);
  assert.ok(text.indexOf('in 2023[1]') >= 0, 'footnote markers become [1]');
});

test('ordinary email phrasing is not mistaken for chat leftovers', function () {
  ['Let me know if you have any questions.', 'Would you like me to send the slides?', 'Feel free to call me.'].forEach(function (t) {
    assert.ok(!M.scanSentence(t).kinds.leftover, t);
  });
  ["Let me know if you'd like a shorter version.", 'Would you like me to expand on section 2?', 'As an AI, I cannot browse.'].forEach(function (t) {
    assert.ok(M.scanSentence(t).kinds.leftover, t);
  });
});

test('sentences do not break at et al., initials, page numbers or titles', function () {
  var s = M.splitSentences('Hartwell et al. (2019) found it (p. 14). Dr. A. B. Smith agreed. Then e.g. this. Repair caf\u00e9s. According to them.');
  assert.deepStrictEqual(s, ['Hartwell et al. (2019) found it (p. 14).', 'Dr. A. B. Smith agreed.', 'Then e.g. this.', 'Repair caf\u00e9s.', 'According to them.']);
});

test('citations: parenthetical, narrative and numbered', function () {
  var c = M.findCitations('As shown (Smith & Jones, 2020a; Brown et al., 2018, p. 4), Lindqvist (2020) and [2, 4-6] agree (in 2019).');
  assert.deepStrictEqual(c.map(function (x) { return x.kind + ':' + (x.authors || x.labels.join('/')) + ':' + x.year; }),
    ['author-year:Smith & Jones:2020a', 'author-year:Brown et al.:2018', 'author-year:Lindqvist:2020', 'numeric:2/4/5/6:']);
});

test('the sample: every planted problem is found in the AI draft', function () {
  var a = M.analyse(sampleInput({ final: '' }));
  assert.strictEqual(a.checked, 'draft');
  var conflicts = a.claims.filter(function (c) { return c.notes.status === 'conflict'; }).map(function (c) { return c.text; }).join(' | ');
  ['tonnes', 'survey_pct', 'saving', 'first_year'].forEach(function (k) {
    assert.ok(conflicts.indexOf(truth.aiValues[k]) >= 0, k + ' (' + truth.aiValues[k] + ') should conflict with the notes');
  });
  assert.ok(conflicts.indexOf(truth.aiValues.quote) >= 0, 'the misquote is caught');
  var left = claimWith(a, 'As of my last update');
  assert.ok(left.kinds.indexOf('leftover') >= 0 && left.level === 'high');
  assert.strictEqual(claimWith(a, 'Soldering fumes').kinds.indexOf('medical') >= 0, true);
  assert.strictEqual(claimWith(a, 'Studies show').kinds.indexOf('vague') >= 0, true);
  assert.strictEqual(claimWith(a, 'legally liable').kinds.indexOf('legal') >= 0, true);
  assert.strictEqual(claimWith(a, 'Footfall').notes.status, 'match');
});

test('the sample: claims are checked in the final version, with where each came from', function () {
  var a = M.analyse(sampleInput());
  assert.strictEqual(a.checked, 'final');
  assert.strictEqual(claimWith(a, 'tonnes of electrical').notes.status, 'match', 'the student fixed the tonnes');
  assert.strictEqual(claimWith(a, 'households found that').notes.status, 'conflict', 'but not the survey figure');
  assert.strictEqual(claimWith(a, 'When I visited').origin, 'yours');
  assert.strictEqual(claimWith(a, 'Households save').origin, 'kept');
  assert.ok(!claimWith(a, 'Soldering'), 'the cut sentence is no longer a claim');
  var order = a.ranked.map(function (q) { return a.claims[q - 1].score; });
  for (var i = 1; i < order.length; i++) assert.ok(order[i - 1] >= order[i]);
  a.claims.forEach(function (c) {
    var sum = c.reasons.reduce(function (t, r) { return t + r.points; }, 0);
    assert.strictEqual(sum, c.score);
    assert.strictEqual(c.level, M.levelOf(c.score));
    assert.ok(/^q[0-9a-f]{8}$/.test(c.key));
  });
});

test('reference checks find each planted problem and never claim to verify', function () {
  var a = M.analyse(sampleInput({ final: '' }));
  var byText = function (s) { return a.refs.entries.filter(function (r) { return r.entry.text.indexOf(s) === 0; }); };
  var codes = function (r) { return r.issues.map(function (x) { return x.code; }); };
  assert.ok(codes(byText('Brinmouth')[0]).indexOf('url-space') >= 0);
  assert.ok(codes(byText('Eastmoor')[0]).indexOf('doi-space') >= 0);
  assert.ok(codes(byText('Hartwell')[1]).indexOf('duplicate') >= 0);
  assert.ok(codes(byText('Kestleford')[0]).indexOf('url-scheme') >= 0);
  assert.strictEqual(byText('Morrow')[0].verdict, 'suspect');
  assert.ok(codes(byText('Pemberton')[0]).indexOf('future-year') >= 0);
  assert.ok(codes(byText('Quinlan')[0]).indexOf('doi-form') >= 0);
  assert.deepStrictEqual(a.refs.missing.map(function (m) { return m.text; }), ['Lindqvist (2020)']);
  var all = JSON.stringify(a.refs);
  assert.ok(!/verified|exists online|confirmed/i.test(all));
});

test('a messy reference list is mended: broken lines joined, run-together entries split', function () {
  var a = M.analyse({ draft: sample('messy-paste.txt'), asOf: AS_OF });
  var urls = a.refs.entries.map(function (r) { return r.entry.url; }).filter(Boolean);
  assert.ok(urls.indexOf('https://kestleford-repair-network.org.uk/annual-report-2023') >= 0, 'URL broken over two lines is rejoined');
  assert.strictEqual(a.refs.entries.filter(function (r) { return r.entry.authors === 'Morrow, J'; }).length, 2);
  assert.ok(a.messages.join(' ').indexOf('run together') >= 0);
  assert.strictEqual(a.claims.filter(function (c) { return c.kinds.indexOf('leftover') >= 0; }).length >= 4, true);
});

test('changes: word-for-word share, sentence classes and cut sentences', function () {
  var ch = M.analyse(sampleInput()).changes;
  assert.strictEqual(ch.counts.kept + ch.counts.edited + ch.counts.reworded + ch.counts.yours, ch.finalSentences);
  assert.strictEqual(ch.keptShare, M.pct(ch.keptWords, ch.finalWords));
  assert.ok(ch.dropped.some(function (d) { return d.text.indexOf('Soldering') === 0; }));
  var same = M.analyse({ draft: 'One two three four five six. Seven eight nine ten.', final: 'One two three four five six. Seven eight nine ten.', asOf: AS_OF }).changes;
  assert.strictEqual(same.keptShare, 100);
  assert.strictEqual(same.counts.kept, 2);
  var none = M.analyse({ draft: 'One two three four five six.', final: 'Completely different words written by me today.', asOf: AS_OF }).changes;
  assert.strictEqual(none.keptShare, 0);
  assert.strictEqual(none.counts.yours, 1);
  assert.strictEqual(none.counts.dropped, 1);
});

test('word diff marks what was cut and added inside a sentence', function () {
  var ops = M.lcsOps('Repair caf\u00e9s always reduce waste.'.split(' '), 'Repair caf\u00e9s often reduce waste.'.split(' '));
  assert.deepStrictEqual(ops, [['=', 'Repair caf\u00e9s'], ['-', 'always'], ['+', 'often'], ['=', 'reduce waste.']]);
});

test('statuses, the summary and the sign-off condition', function () {
  var a = M.analyse(sampleInput());
  var checks = {};
  var s0 = M.summarise(a, checks, {});
  assert.strictEqual(s0.unchecked, a.claims.length);
  assert.strictEqual(s0.complete, false);
  a.claims.forEach(function (c) { checks[c.key] = { status: 'verified' }; });
  var s1 = M.summarise(a, checks, {});
  assert.strictEqual(s1.highUnchecked, 0);
  assert.strictEqual(s1.complete, false, 'flagged references still need marks');
  var refs = {};
  a.refs.entries.forEach(function (r) { refs[r.entry.key] = { status: 'checked' }; });
  assert.strictEqual(M.summarise(a, checks, refs).complete, true);
});

test('session logs: aliases, reordered columns and plain messages for bad rows', function () {
  var r = M.parseSessions(sample('session-log.csv'));
  assert.strictEqual(r.sessions.length, 6);
  var msgs = r.messages.join(' ');
  assert.ok(/31\/13\/2026/.test(msgs) && /"ten" is not a number/.test(msgs));
  assert.ok(/no date, tool or purpose/.test(M.parseSessions('Date,Tool,Purpose,Prompt\n,,,just a note\n').messages.join(' ')));
  var dev = M.parseSessions(sample('team/team-log-dev.csv'));
  assert.strictEqual(dev.sessions[0].person, 'Dev Okonedo');
  assert.strictEqual(dev.sessions[0].tool, 'Fernwrite');
  var sam = M.parseSessions(sample('team/team-log-sam.csv'));
  assert.strictEqual(sam.sessions[1].prompt, 'Asked for three ways to open the summary; used none');
  assert.ok(/does not look like a session log/.test(M.parseSessions('Name,Age\nAna,20\n').messages[0]));
});

test('the declaration states what is still unchecked and never claims more', function () {
  var p = M.readProject(sample('sample-project.json'));
  var a = M.analyse(Object.assign({}, p.texts, { asOf: AS_OF }));
  var st = { project: p.project, sessions: p.sessions, checks: p.checks, refChecks: p.refChecks, asOf: AS_OF };
  var text = M.declarationText(M.declaration(a, st));
  assert.ok(text.indexOf('7 statements are not yet marked as checked, including 4 high risk.') >= 0, text);
  assert.ok(text.indexOf('4 verified against a source') >= 0);
  assert.ok(text.indexOf('does not check anything online and is not a plagiarism detector') >= 0);
  assert.ok(text.indexOf('MGT2210') < 0, 'sessions for another assignment are left out');
  var md = M.declarationMarkdown(M.declaration(a, Object.assign({}, st, { project: Object.assign({}, p.project, { template: 'appendix' }) })));
  assert.ok(/^# Declaration of AI use/.test(md) && md.indexOf('## Checking log') > 0);
  M.TEMPLATES.forEach(function (t) {
    var d = M.declaration(a, Object.assign({}, st, { project: Object.assign({}, p.project, { template: t.id }) }));
    assert.ok(M.declarationText(d).length > 100);
    assert.ok(M.declarationText(d).indexOf('\u2014') < 0);
  });
});

test('project files round-trip and junk is refused with a reason', function () {
  var text = sample('sample-project.json');
  var p = M.readProject(text);
  assert.ok(p.ok);
  assert.strictEqual(M.projectFile({ project: p.project, texts: p.texts, sessions: p.sessions, checks: p.checks, refChecks: p.refChecks, baseline: p.baseline, asOf: AS_OF }), text);
  assert.ok(/not valid JSON/.test(M.readProject('nope').message));
  assert.ok(/not a Checked by me project/.test(M.readProject('{"a":1}').message));
  assert.ok(/newer version/.test(M.readProject('{"format":"checked-by-me project","version":7}').message));
});

test('reference manager exports: RIS and BibTeX records with citation keys', function () {
  var keyed = sample('final-version.md').split('## References')[0].replace('(Hartwell et al., 2019)', '[@hartwell2019, p. 115]').replace('Lindqvist (2020)', '\\cite{lindqvist2020}');
  ['ris', 'bib'].forEach(function (ext) {
    var a = M.analyse({ draft: sample('ai-draft.md'), final: keyed, references: sample('references.' + ext), asOf: AS_OF });
    assert.strictEqual(a.refs.format, ext === 'ris' ? 'ris' : 'bibtex');
    assert.strictEqual(a.refs.entries.length, 9);
    var byKey = {};
    a.refs.entries.forEach(function (r) { byKey[r.entry.citeKey] = r; });
    assert.ok(byKey.hartwell2019.cited >= 1, 'the [@key] citation finds its record');
    assert.strictEqual(byKey.morrow2021.verdict, 'suspect');
    assert.ok(byKey.brinmouth2022.issues.some(function (x) { return x.code === 'url-space'; }));
    assert.ok(byKey.pemberton2031.issues.some(function (x) { return x.code === 'future-year'; }));
    assert.ok(a.refs.missing.some(function (m) { return m.text === '@lindqvist2020'; }));
  });
  var b = M.parseBibtex('@article{k, author = {Maren Haldane and {Kestleford Repair Network}}, title = {Caf{\\\'e}s}, journal={J}, year=2021, pages={1--9}}')[0];
  assert.strictEqual(b.authors, 'Haldane, Maren and Kestleford Repair Network');
  assert.strictEqual(b.title, 'Caf\u00e9s');
  assert.strictEqual(b.pages, '1-9');
});

test('re-checking: new, edited and gone statements since the recorded version', function () {
  var p = M.readProject(sample('sample-project.json'));
  var a = M.analyse(Object.assign({}, p.texts, { asOf: AS_OF }));
  var v = M.compareVersions(p.baseline.text, a, p.checks);
  assert.strictEqual(p.baseline.on, '2026-11-20');
  assert.deepStrictEqual([v.newClaims.length, v.changed.length, v.gone.length, v.unchanged.length], [1, 1, 1, 9]);
  assert.ok(a.claims[v.newClaims[0] - 1].text.indexOf('Younger respondents') === 0);
  assert.strictEqual(v.changed[0].status, 'corrected');
  assert.ok(v.changed[0].ops.some(function (o) { return o[0] === '-' && o[1] === truth.aiValues.tonnes; }));
  assert.strictEqual(v.gone[0].status, 'removed');
  var same = M.compareVersions(p.texts.final, a, p.checks);
  assert.strictEqual(same.unchanged.length, a.claims.length);
});

test('the proof copy puts a query after every flagged sentence and lists them all', function () {
  var p = M.readProject(sample('sample-project.json'));
  var a = M.analyse(Object.assign({}, p.texts, { asOf: AS_OF }));
  var md = M.annotatedMarkdown(a, p.checks, p.refChecks, p.project.title, AS_OF);
  assert.strictEqual((md.match(/\*\*\[Qy [0-9]+: /g) || []).length, a.claims.length);
  assert.strictEqual((md.match(/^### Qy /gm) || []).length, a.claims.length);
  assert.ok(md.indexOf('11 statements flagged: 5 high risk, 3 medium, 3 low; 7 still open.') > 0);
  assert.ok(md.indexOf('Nothing was checked online') > 0);
});

test('fresh-eyes findings: forms headings, source labels, real journals and honest notes', function () {
  var forms = 'Timestamp,Email address,Your name,Which AI tool did you use?,What did you use it for?,Prompt (in brief),' +
    'What did you keep from its answer?,What did you change?,What did you check?,How long (minutes)?\n' +
    '21/11/2026 09:14:03,a@b.c,Sam Ward,Orrery Chat,Draft the briefing,Asked for a briefing,Two paragraphs,The figures,Turnover,25\n';
  var r = M.parseSessions(forms);
  assert.deepStrictEqual([r.sessions[0].tool, r.sessions[0].purpose, r.sessions[0].used, r.sessions[0].checked, r.sessions[0].minutes, r.sessions[0].person],
    ['Orrery Chat', 'Draft the briefing', 'Two paragraphs', 'Turnover', '25', 'Sam Ward']);
  var notes = 'HR dashboard Q3 2026: desk occupancy 41% average (Leeds 44%, Bristol 38%).';
  var a = M.analyse({ draft: 'Since the move in 2024, desk occupancy has averaged 41% across the Leeds and Bristol offices.', notes: notes, asOf: AS_OF });
  assert.strictEqual(a.claims[0].notes.status, 'partial', 'the dashboard date before the colon is not a fact to compare');
  assert.ok(!a.claims[0].notes.items.some(function (it) { return it.result === 'conflict'; }));
  var real = M.checkEntry(M.parseEntry("Smith, J. (2020) 'Title', Journal of Management Studies, 57(2), pp. 1-20.", ''), AS_OF);
  assert.ok(!real.issues.some(function (x) { return x.code === 'generic-journal'; }));
  var vague = M.checkEntry(M.parseEntry("Smith, J. (2020) 'Title', Journal of Research Studies.", ''), AS_OF);
  assert.ok(vague.issues.some(function (x) { return x.code === 'generic-journal'; }));
  var b = M.analyse({ draft: 'It saved 40% of costs.', asOf: AS_OF });
  var work = function (level, sessions) {
    return M.declarationText(M.declaration(b, { project: { template: 'work', level: level }, sessions: sessions, asOf: AS_OF }));
  };
  assert.ok(work('assisted', []).indexOf('no sessions have been logged yet') > 0);
  assert.ok(work('assisted', [M.cleanSession({ date: '2026-11-21', purpose: 'Draft' })]).indexOf('AI tools (not named in the log) (purposes logged: draft).') > 0);
  assert.ok(work('none', []).indexOf('No AI tools were used') > 0);
  assert.ok(work('assisted', []).indexOf('none has been marked as checked yet') > 0);
});

test('word files become Markdown-like text with headings, lists and footnotes', function () {
  var t = M.docxText('<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Intro</w:t></w:r></w:p><w:p><w:r><w:t>Text &amp; more</w:t></w:r><w:r><w:footnoteReference w:id="1"/></w:r></w:p>',
    '<w:footnote w:id="0"><w:p><w:r><w:t>x</w:t></w:r></w:p></w:footnote><w:footnote w:id="1"><w:p><w:r><w:t>Smith (2020) Title.</w:t></w:r></w:p></w:footnote>');
  assert.strictEqual(t, '## Intro\n\nText & more[^1]\n\n[^1]: Smith (2020) Title.\n');
});

test('nothing in the model can fetch or touch the page', function () {
  var src = fs.readFileSync(path.join(ROOT, 'src', 'model.js'), 'utf8');
  assert.ok(!/fetch\(|XMLHttpRequest|\bdocument\.(?:get|query|body|create|write)|window\.location|localStorage/.test(src));
});

test('a long draft is analysed quickly', function () {
  var para = sample('ai-draft.md').split('## References')[0];
  var big = new Array(40).join(para + '\n\n');
  var t0 = Date.now();
  var a = M.analyse({ draft: big, final: big.replace(/always/g, 'often'), asOf: AS_OF });
  assert.ok(a.claims.length > 400);
  assert.ok(Date.now() - t0 < 8000, 'took ' + (Date.now() - t0) + ' ms');
});
