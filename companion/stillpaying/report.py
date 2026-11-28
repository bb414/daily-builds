"""A self-contained, print-friendly HTML report of a review.

The page makes no requests of its own (system fonts, inline styles) and uses
the app's palette: duck-egg tiles, deep ink green, copper, enamel cream, and
signal red, amber and green for the checks. All text taken from statements is
escaped.
"""

from html import escape

from .common import money
from .dates import long_date
from .detect import CADENCE_BY_ID
from .payees import CATEGORIES
from .planning import suggest
from .present import cadence_label, decision_label, flag_label, headline, status_label, upcoming

STYLE = """
:root {
  --tile: #dfe9e4; --ink: #13312d; --copper: #b4643a; --cream: #fbf7ee;
  --red: #c23b2a; --amber: #d99a1e; --green: #2f7a4f;
  --muted: #4d6460; --rule: #d6cdb8;
}
* { box-sizing: border-box; }
body {
  margin: 0; color: var(--ink); background-color: var(--tile);
  background-image: linear-gradient(rgba(19, 49, 45, .07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(19, 49, 45, .07) 1px, transparent 1px);
  background-size: 26px 26px;
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
.sheet {
  max-width: 1040px; margin: 28px auto; padding: 28px 32px 36px; background: var(--cream);
  border: 1px solid var(--rule); border-top: 6px solid var(--copper); border-radius: 10px;
  box-shadow: 0 10px 30px rgba(19, 49, 45, .12);
}
.eyebrow {
  margin: 0; color: var(--copper); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; font-size: 13px;
}
h1 { margin: 2px 0 4px; font-size: 30px; line-height: 1.15; }
h2 { margin: 34px 0 10px; font-size: 20px; border-bottom: 2px solid var(--copper); padding-bottom: 4px; }
h3 { margin: 22px 0 6px; font-size: 16px; display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
h3 .sub { font-weight: 400; color: var(--muted); }
.meta { margin: 0; color: var(--muted); }
.figures { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin-top: 22px; }
.figure { background: #fff; border: 1px solid var(--rule); border-radius: 8px; padding: 12px 14px; }
.figure .label { display: block; font-size: 13px; color: var(--muted); }
.figure strong { display: block; font-size: 24px; margin: 2px 0; font-variant-numeric: tabular-nums; }
.figure .sub { display: block; font-size: 13px; color: var(--muted); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
table.fixed { table-layout: fixed; min-width: 760px; }
th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--rule); vertical-align: top; }
th { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); font-weight: 600; }
td.num, th.num { text-align: right; white-space: nowrap; }
td.when { white-space: nowrap; }
.name { font-weight: 600; }
.why { display: block; margin-top: 2px; font-size: 13px; color: var(--muted); }
.checks { display: block; margin-top: 4px; font-size: 13px; color: var(--muted); padding-left: 16px; }
.chip {
  display: inline-block; margin: 0 4px 4px 0; padding: 1px 8px; border-radius: 999px;
  font-size: 12px; font-weight: 600; white-space: nowrap;
}
.chip.alert { background: var(--red); color: #fff; }
.chip.warn { background: var(--amber); color: var(--ink); }
.chip.info { background: transparent; color: var(--green); border: 1px solid var(--green); }
.status { font-weight: 600; }
.status.active { color: var(--green); }
.status.late { color: #8a5a00; }
.status.stopped { color: var(--muted); }
.cancel { color: var(--red); font-weight: 600; }
.note { padding: 10px 14px; background: #fff; border-left: 4px solid var(--copper); border-radius: 4px; }
.alert-box { border-left-color: var(--red); }
ul.plain { margin: 6px 0 0; padding-left: 20px; }
.muted { color: var(--muted); }
.file { margin: 12px 0; padding: 10px 14px; background: #fff; border: 1px solid var(--rule); border-radius: 8px; }
.file h4 { margin: 0 0 4px; font-size: 15px; }
.file .problem { color: var(--red); font-weight: 600; }
footer { margin-top: 34px; font-size: 13px; color: var(--muted); }
@media (max-width: 640px) {
  .sheet { margin: 0; padding: 18px 16px 24px; border-radius: 0; }
  h1 { font-size: 24px; }
}
@media print {
  @page { margin: 14mm; }
  body { background: #fff; font-size: 11pt; }
  .sheet { max-width: none; margin: 0; padding: 0; border: 0; box-shadow: none; background: #fff; }
  h2, h3 { break-after: avoid; }
  .group, tr, .figure, .file, .note { break-inside: avoid; }
  .figures { grid-template-columns: repeat(4, 1fr); }
  table, table.fixed { min-width: 0; font-size: 8.5pt; }
  th { font-size: 7pt; }
  .why, .checks, .chip { font-size: 7.5pt; }
  .table-wrap { overflow: visible; }
  .chip, .status, .figure { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
"""


def _e(text):
    return escape(str(text), quote=True)


def _about(s):
    return 'about ' if s['amounts']['kind'] == 'variable' else ''


def _chips(flags):
    return ''.join('<span class="chip %s" title="%s">%s</span>' % (_e(f['tone']), _e(f['text']), _e(flag_label(f)))
                   for f in flags)


def _table(headers, rows, numeric=(), widths=None):
    head = ''.join('<th%s>%s</th>' % (' class="num"' if i in numeric else '', _e(h)) for i, h in enumerate(headers))
    body = ''.join('<tr>' + ''.join(cells) + '</tr>' for cells in rows)
    cols = ''
    if widths:
        cols = '<colgroup>%s</colgroup>' % ''.join('<col style="width:%d%%">' % w for w in widths)
    return ('<div class="table-wrap"><table%s>%s<thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
            % (' class="fixed"' if widths else '', cols, head, body))


def _header(result, generated_for):
    start, end = result['dataStart'], result['dataEnd']
    if start is None:
        covered = 'No statements'
    else:
        covered = 'Statements from %s to %s' % (long_date(start), long_date(end))
    return ('<header><p class="eyebrow">Still paying?</p><h1>%s</h1><p class="meta">%s. Reviewed on %s.</p></header>'
            % (_e(generated_for), _e(covered), _e(long_date(result['asOf']))))


def _figures(result, decisions):
    h = headline(result, decisions)
    payday = h['payday']
    cards = [
        ('Committed each month', money(h['monthly']),
         money(h['annual']) + ' a year, not counting savings or money moved between your own accounts'),
        ('Regular payments', str(h['regulars']), '%d of them count as spending' % h['costs']),
        ('Checks to look at', str(h['checks']), 'regular payments with something worth a second look'),
        ('Next payday', long_date(payday['next']) if payday else 'Not known',
         ('%s, about %s' % (payday['name'], money(payday['typical']))) if payday else 'No regular income found'),
    ]
    return '<section class="figures">' + ''.join(
        '<div class="figure"><span class="label">%s</span><strong>%s</strong><span class="sub">%s</span></div>'
        % (_e(a), _e(b), _e(c)) for a, b, c in cards) + '</section>'


def _since(result, since, previous_file):
    out = ['<h2>Since your last review</h2>']
    if since is None:
        out.append('<p class="note">This is your first review, so there is nothing to compare with yet. '
                   'Next month this section will show what has changed.</p>')
        return ''.join(out)
    out.append('<p class="meta">Compared with the review on %s%s.</p>'
               % (_e(long_date(since['reviewedOn'])), (' (' + _e(previous_file) + ')') if previous_file else ''))
    if since['stillCharging']:
        items = ''.join('<li><span class="name">%s</span>: %s after you decided to cancel on %s.</li>'
                        % (_e(c['name']), _e(', '.join(money(p['amount']) + ' on ' + long_date(p['day'])
                                                       for p in c['payments'])), _e(long_date(c['decidedOn'])))
                        for c in since['stillCharging'])
        out.append('<div class="note alert-box"><strong>Still being charged after you decided to cancel</strong>'
                   '<ul class="plain">%s</ul></div>' % items)
    groups = [
        ('New regular payments', ['%s: %s %s, first taken on %s' % (
            n['name'], money(n['amount']), CADENCE_BY_ID[n['cadence']]['label'].lower(), long_date(n['first']))
            for n in since['newSince']]),
        ('Price changes', ['%s: %s to %s' % (p['name'], money(p['from']), money(p['to']))
                           for p in since['priceChanges']]),
        ('Stopped', ['%s: last paid on %s' % (s['name'], long_date(s['last'])) for s in since['stoppedSince']]),
    ]
    for title, items in groups:
        body = ''.join('<li>%s</li>' % _e(i) for i in items) if items else '<li class="muted">None.</li>'
        out.append('<h3>%s</h3><ul class="plain">%s</ul>' % (_e(title), body))
    return ''.join(out)


def _regulars(result, decisions):
    out = ['<h2>Regular payments by category</h2>']
    if not result['series']:
        out.append('<p class="muted">No regular payments were found.</p>')
    by_cat = {}
    for s in result['series']:
        by_cat.setdefault(s['category'], []).append(s)
    for cat in CATEGORIES:
        series = by_cat.get(cat['id'])
        if not series:
            continue
        monthly = sum(s['monthly'] for s in series if s['status'] == 'active')
        rows = []
        for s in series:
            texts = ''.join('<li>%s</li>' % _e(f['text']) for f in s['flags'])
            decision = decision_label(decisions, s['id'])
            hint = 'Suggested: ' + suggest(s)['text'] if not decision else ''
            paid_by = s['account'] + ('' if s['method'] == 'unknown' else ', ' + s['method'])
            rows.append([
                '<td><span class="name">%s</span><span class="why">%s</span>%s</td>'
                % (_e(s['name']), _e(paid_by), ('<ul class="checks">%s</ul>' % texts) if texts else ''),
                '<td>%s</td>' % _e(cadence_label(s)),
                '<td class="num">%s%s</td>' % (_e(money(s['typical'])), '<span class="why">varies</span>'
                                               if s['amounts']['kind'] == 'variable' else ''),
                '<td class="num">%s</td>' % _e(money(s['monthly'])),
                '<td class="num">%s</td>' % _e(money(s['annual'])),
                '<td class="when">%s</td>' % _e(long_date(s['nextDue']) if s['nextDue'] is not None else ''),
                '<td><span class="status %s">%s</span></td>' % (_e(status_label(s).lower()), _e(status_label(s))),
                '<td>%s%s</td>' % (('<span class="cancel">%s</span>' if decision == 'Cancel' else '%s') % _e(decision),
                                   ('<span class="why">%s</span>' % _e(hint)) if hint else ''),
                '<td>%s</td>' % _chips(s['flags']),
            ])
        out.append('<div class="group"><h3>%s <span class="sub">%s a month</span></h3>%s</div>' % (
            _e(cat['label']), _e(money(monthly)),
            _table(['Name', 'How often', 'Typical', 'Monthly', 'Yearly', 'Next due', 'Status', 'Decision', 'Checks'],
                   rows, numeric=(2, 3, 4), widths=(21, 9, 9, 8, 9, 11, 8, 14, 11))))
    return ''.join(out)


def _next_days(result, decisions):
    rows = upcoming(result, decisions, 31)
    out = ['<h2>The next 31 days</h2>']
    if not rows:
        out.append('<p class="muted">Nothing is due in the next 31 days.</p>')
        return ''.join(out)
    cells = []
    for r in rows:
        note = ' <span class="cancel">(you plan to cancel)</span>' if r['cancelling'] else (
            ' <span class="muted">(due, not in your statement yet)</span>' if r['late'] else '')
        cells.append(['<td class="when">%s</td>' % _e(long_date(r['day'])),
                      '<td><span class="name">%s</span>%s</td>' % (_e(r['name']), note),
                      '<td class="num">%s</td>' % _e(('about ' if r['about'] else '') + money(r['amount'])),
                      '<td class="num">%s</td>' % _e(money(r['running']))])
    out.append(_table(['Date', 'Payment', 'Amount', 'Running total'], cells, numeric=(2, 3)))
    return ''.join(out)


def _candidates(result):
    out = ['<h2>Possible regular payments</h2>']
    if not result['candidates']:
        out.append('<p class="muted">None: every repeating payment found so far is in the list above.</p>')
        return ''.join(out)
    rows = [['<td><span class="name">%s</span><span class="why">%s</span></td>' % (_e(c['name']), _e(c['account'])),
             '<td class="num">%s</td>' % _e(money(c['amount'])),
             '<td class="when">%s</td>' % _e(long_date(c['lastDay'])),
             '<td>%s</td>' % _e(c['reason'])] for c in result['candidates']]
    out.append(_table(['Name', 'Amount', 'Last seen', 'Why it might be regular'], rows, numeric=(1,)))
    return ''.join(out)


def _income(result):
    if not result['income']:
        return ''
    rows = [['<td class="name">%s</td>' % _e(s['name']), '<td>%s</td>' % _e(cadence_label(s)),
             '<td class="num">%s</td>' % _e(_about(s) + money(s['typical'])),
             '<td class="when">%s</td>' % _e(long_date(s['nextDue']) if s['nextDue'] is not None else ''),
             '<td><span class="status %s">%s</span></td>' % (_e(status_label(s).lower()), _e(status_label(s)))]
            for s in result['income']]
    return '<h2>Money coming in</h2>' + _table(['From', 'How often', 'Typical', 'Next expected', 'Status'], rows,
                                               numeric=(2,))


def _files(analysis, notes):
    out = ['<h2>Files read</h2>']
    linked = {n['file']: n for n in analysis['merged'].get('linked', [])}
    for st in analysis['statements']:
        parts = ['<div class="file"><h4>%s</h4>' % _e(st['name'])]
        if st.get('error') and not st['ok']:
            parts.append('<p class="problem">%s</p>' % _e(st['error']))
        if st['rowCount'] or st['ok']:
            parts.append('<p>Account: %s. %d rows read, %d payments, %d skipped.</p>'
                         % (_e(st['account']), st['rowCount'], len(st['transactions']), len(st['skipped'])))
        link = linked.get(st['name'])
        if link:
            parts.append('<p class="muted">Read as %s: %d%% of its payments are also in %s, so the overlap is only '
                         'counted once.</p>' % (_e(link['account']), link['share'], _e(link['other'])))
        for w in st['warnings']:
            parts.append('<p class="muted">%s</p>' % _e(w))
        if st['skipped']:
            rows = [['<td class="when">Line %d</td>' % k['line'], '<td>%s</td>' % _e(k['reason']),
                     '<td class="muted">%s</td>' % _e(k['raw'])] for k in st['skipped']]
            parts.append(_table(['Where', 'Why it was skipped', 'The row'], rows))
        parts.append('</div>')
        out.append(''.join(parts))
    for note in notes or []:
        out.append('<p class="muted">%s</p>' % _e(note))
    duplicates = analysis['merged']['duplicates']
    if duplicates:
        out.append('<p class="muted">%d payments appeared in more than one file and were counted once.</p>'
                   % duplicates)
    return ''.join(out)


def render_report(analysis, decisions=None, since=None, show_since=False, previous_file=None, notes=None,
                  title='Your regular payments'):
    """The whole report as an HTML page.

    analysis is what analyse() returns. Pass show_since=True to include the
    "Since your last review" section; since is since_last_review()'s result,
    or None for a first review. notes are extra lines for the files section.
    """
    decisions = decisions or {}
    result = analysis['result']
    body = [_header(result, title), _figures(result, decisions)]
    if show_since:
        body.append(_since(result, since, previous_file))
    body += [_regulars(result, decisions), _next_days(result, decisions), _candidates(result), _income(result),
             _files(analysis, notes)]
    return ('<!doctype html>\n<html lang="en-GB">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<title>Still paying? Review for %s</title>\n<style>%s</style>\n</head>\n<body>\n<main class="sheet">\n%s\n'
            '<footer>Made by the Still paying? companion from your own bank exports, on your own computer. '
            'Amounts are in pounds; "about" marks bills that vary.</footer>\n</main>\n</body>\n</html>\n'
            % (_e(long_date(result['asOf'])), STYLE, '\n'.join(body)))
