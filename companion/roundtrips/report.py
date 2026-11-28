"""Printable HTML reports: the weekly review and the team review.

Each report is one self-contained HTML file with its own styles (the same desk,
ledger and carbon-ticket look as the app), an equity curve drawn as SVG and no
outside requests, so it can be emailed, attached to a team chat or printed.
"""

import html
import math

from .common import fmt_day_month_year, fmt_duration, fmt_num, fmt_pct, fmt_price, fmt_qty, fmt_r, fmt_short, fmt_time, money, plural, rnd, week_start
from .review import trade_name
from .stats import usable

STYLE = """
:root{--ink:#26307a;--loss:#b3301d;--paper:#fbf8ef;--ledger:#f8f3e4;--rule:#c9d5e7;--canary:#f8ea9e;--pink:#f6d3cd;--sky:#d8e7f2;--graphite:#2b2825;--muted:#6e675e;--brass:#b5862c}
*{box-sizing:border-box}
body{margin:0;font-family:'Manrope','Segoe UI',system-ui,sans-serif;color:var(--graphite);background:#3a2416;line-height:1.5}
.wrap{max-width:1100px;margin:0 auto;padding:28px 18px 40px}
header{color:#f6ead3;margin-bottom:20px}
header .kicker{font-family:ui-monospace,'Cascadia Mono',monospace;font-size:.75rem;letter-spacing:.14em;text-transform:uppercase;color:#e9d7b4}
header h1{font-family:'Unbounded','Arial Black',sans-serif;font-size:2.4rem;line-height:1;margin:.2em 0;color:#fbf3e1}
header p{margin:.3em 0;color:#f1e4c9}
.stamp{display:inline-block;border:3px double #e0614c;color:#ffd9cf;padding:3px 8px;font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;transform:rotate(-2deg);margin-top:6px}
.tickets{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:0 0 20px}
.t{background:var(--paper);padding:12px 14px;border-radius:3px;box-shadow:0 8px 18px -12px #000}
.t:nth-child(2){background:var(--canary)}.t:nth-child(3){background:var(--pink)}.t:nth-child(4){background:var(--sky)}
.t h2{margin:0;font-size:.66rem;letter-spacing:.14em;text-transform:uppercase;color:var(--ink)}
.t .big{font-family:ui-monospace,'Cascadia Mono',monospace;font-size:1.6rem;font-weight:700}
.t p{margin:4px 0 0;font-size:.84rem}
.sheet{background:var(--ledger);border-radius:2px;padding:18px 20px 20px 34px;margin:0 0 18px;box-shadow:0 8px 18px -12px #000;
 background-image:linear-gradient(90deg,transparent 18px,rgba(217,119,106,.55) 18px 19px,transparent 19px 22px,rgba(217,119,106,.55) 22px 23px,transparent 23px)}
.sheet h2{margin:0 0 8px;font-family:'Unbounded','Arial Black',sans-serif;font-weight:500;font-size:1.1rem;color:var(--ink)}
table{width:100%;border-collapse:collapse;font-size:.86rem}
th{text-align:left;font-size:.66rem;letter-spacing:.08em;text-transform:uppercase;color:var(--ink);border-bottom:2px solid var(--ink);padding:6px}
td{padding:6px;border-bottom:1px solid var(--rule);vertical-align:top}
td.n,th.n{text-align:right;font-family:ui-monospace,'Cascadia Mono',monospace;white-space:nowrap}
.gain{color:var(--ink)}.loss{color:var(--loss)}.muted{color:var(--muted)}
ol.notes{padding-left:22px}ol.notes li{padding:3px 0}
.bar{display:grid;grid-template-columns:12em 1fr 7em;gap:8px;align-items:center;font-size:.86rem;margin:3px 0}
.track{position:relative;height:14px;background:rgba(38,48,122,.06)}
.fill{position:absolute;top:2px;bottom:2px}.fill.p{background:var(--ink)}.fill.q{background:var(--loss)}
.zero{position:absolute;top:-2px;bottom:-2px;left:50%;width:2px;background:#555}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;border-top:1px solid var(--rule);border-left:1px solid var(--rule)}
.grid div{padding:8px 10px;border-right:1px solid var(--rule);border-bottom:1px solid var(--rule)}
.grid dt{font-size:.66rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:700}
.grid dd{margin:0;font-family:ui-monospace,'Cascadia Mono',monospace;font-weight:700}
pre{white-space:pre-wrap;font-size:.78rem;background:#fffdf6;border:1px solid #c7c0ae;padding:10px}
svg text{font-family:ui-monospace,'Cascadia Mono',monospace;font-size:11px;fill:#5c564e}
footer{color:#e7d6b6;font-size:.82rem}
@media (max-width:700px){.tickets,.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.bar{grid-template-columns:7em 1fr 5.5em}}
@media print{body{background:#fff}header,footer{color:#000}header h1,header p,header .kicker{color:#000}.sheet,.t{box-shadow:none;border:1px solid #999}}
"""


def e(v):
    return html.escape('' if v is None else str(v))


def cls(v):
    return 'gain' if v > 0 else ('loss' if v < 0 else '')


def page(title, body):
    return ('<!doctype html>\n<html lang="en-GB">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<title>' + e(title) + '</title>\n<style>' + STYLE + '</style>\n</head>\n<body>\n<div class="wrap">\n' + body
            + '<footer><p>Made by Round trips from fills exports. A record of trades already made: not financial advice.</p></footer>\n</div>\n</body>\n</html>\n')


def equity_svg(trades, base, highlight=None, width=1000, height=260):
    """A closed-trade equity curve with the drop from each high shaded and an optional span of days highlighted."""
    lst = usable(trades)
    if not lst:
        return '<p class="muted">No closed trades.</p>'
    pad_l, pad_r, pad_t, pad_b = 76, 12, 12, 28
    cum, peak, c, p = [0], [0], 0, 0
    for t in lst:
        c += t['netBase']
        p = max(p, c)
        cum.append(c)
        peak.append(p)
    lo, hi = min(cum), max(cum)
    if hi == lo:
        hi, lo = hi + 100, lo - 100
    raw = (hi - lo) / 4
    mag = 10 ** math.floor(math.log10(raw))
    f = raw / mag
    step = (1 if f <= 1 else 2 if f <= 2 else 5 if f <= 5 else 10) * mag
    y0, y1 = math.floor(lo / step) * step, math.ceil(hi / step) * step
    n = len(lst)

    def x(i):
        return pad_l + i / n * (width - pad_l - pad_r)

    def y(v):
        return pad_t + (y1 - v) / (y1 - y0) * (height - pad_t - pad_b)

    out = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="Closed-trade equity curve">' % (width, height)]
    if highlight:
        idx = [i for i, t in enumerate(lst) if highlight[0] <= t['closeDay'] <= highlight[1]]
        if idx:
            out.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" fill="#f8ea9e" opacity=".75"/>' % (x(idx[0]), pad_t, max(3, x(idx[-1] + 1) - x(idx[0])), height - pad_t - pad_b))
    v = y0
    while v <= y1 + step / 2:
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="%s"/>' % (pad_l, width - pad_r, y(v), y(v), '#2b2825' if v == 0 else '#c9d5e7'))
        out.append('<text x="%d" y="%.1f" text-anchor="end">%s</text>' % (pad_l - 6, y(v) + 4, e(money(rnd(v), base, whole=True))))
        v += step
    last_x, last_w = -999, None
    for i, t in enumerate(lst):
        w = week_start(t['closeDay'])
        if w == last_w:
            continue
        last_w = w
        if x(i) - last_x > 70 and x(i) < width - 30:
            out.append('<text x="%.1f" y="%d" text-anchor="middle">%s</text>' % (x(i), height - 8, e(fmt_short(w))))
            last_x = x(i)
    dd = ['M%.1f %.1f' % (x(0), y(peak[0]))] + ['L%.1f %.1f' % (x(i), y(peak[i])) for i in range(1, n + 1)]
    dd += ['L%.1f %.1f' % (x(i), y(cum[i])) for i in range(n, -1, -1)]
    out.append('<path d="%s Z" fill="#b3301d" opacity=".22"/>' % ' '.join(dd))
    out.append('<path d="%s" fill="none" stroke="#b5862c" stroke-width="1.5" stroke-dasharray="5 4"/>' % ' '.join(('M' if i == 0 else 'L') + '%.1f %.1f' % (x(i), y(peak[i])) for i in range(n + 1)))
    out.append('<path d="%s" fill="none" stroke="#26307a" stroke-width="2.4"/>' % ' '.join(('M' if i == 0 else 'L') + '%.1f %.1f' % (x(i), y(cum[i])) for i in range(n + 1)))
    out.append('</svg>')
    return ''.join(out)


def bars(rows, base, label=lambda r: r['label'], sub=None):
    if not rows:
        return '<p class="muted">Nothing to show.</p>'
    mx = max(1, max(abs(r['net']) for r in rows))
    out = []
    for r in rows:
        w = abs(r['net']) / mx * 50
        left = 50 if r['net'] >= 0 else 50 - w
        out.append('<div class="bar"><span>%s</span><span class="track"><span class="zero"></span><span class="fill %s" style="left:%.2f%%;width:%.2f%%"></span></span>'
                   '<span class="n %s" style="text-align:right">%s</span></div>' % (e(label(r)), 'p' if r['net'] >= 0 else 'q', left, max(w, .6), cls(r['net']),
                                                                                  e(money(r['net'], base, sign=True, whole=True))))
        if sub:
            out.append('<div class="muted" style="font-size:.78rem;margin:-2px 0 4px">%s</div>' % e(sub(r)))
    return ''.join(out)


def stat_grid(s, base):
    def cell(label, value):
        return '<div><dt>%s</dt><dd>%s</dd></div>' % (e(label), e(value))
    if not s['n']:
        return '<p class="muted">No trades closed.</p>'
    return '<dl class="grid">' + ''.join([
        cell('Net after fees', money(s['net'], base, sign=True)), cell('Closed trades', '%d (%d won, %d lost)' % (s['n'], s['wins'], s['losses'])),
        cell('Win rate', fmt_pct(s['winRate'])), cell('Expectancy', money(rnd(s['expectancy']), base, sign=True)),
        cell('Average win', 'n/a' if s['avgWin'] is None else money(rnd(s['avgWin']), base)),
        cell('Average loss', 'n/a' if s['avgLoss'] is None else money(rnd(s['avgLoss']), base)),
        cell('Profit factor', 'no losses' if s['profitFactor'] is None else fmt_num(s['profitFactor'], 2)),
        cell('Average R', 'n/a' if s['avgR'] is None else fmt_r(s['avgR']) + ' (%d trades)' % s['rCount']),
        cell('Fees', money(s['fees'], base)), cell('Largest drop', money(s['maxDD'], base)),
        cell('Held: winners, losers', '%s, %s' % (fmt_duration(s['avgHoldWin']) or 'n/a', fmt_duration(s['avgHoldLoss']) or 'n/a')),
        cell('Longest losing run', plural(s['maxLossStreak'], 'trade')),
    ]) + '</dl>'


def weekly_report(result, rv, text):
    """The weekly review as a printable HTML page."""
    base = rv['base']
    s = rv['stats']
    by_id = {t['id']: t for t in result['trades']}
    body = ['<header><div class="kicker">Round trips &middot; weekly trade review</div><h1>%s</h1><p>%s to %s, %s</p><span class="stamp">Not financial advice</span></header>'
            % (e(rv['label']), e(fmt_day_month_year(rv['week'])), e(fmt_day_month_year(rv['week'] + 6)), e(rv['account'] or 'all accounts'))]
    body.append('<section class="tickets">')
    body.append('<div class="t"><h2>Net after fees</h2><div class="big %s">%s</div><p>Before fees %s; fees %s</p></div>'
                % (cls(s['net']), e(money(s['net'], base, sign=True)), e(money(s['gross'], base, sign=True)), e(money(s['fees'], base))))
    body.append('<div class="t"><h2>Win rate</h2><div class="big">%s</div><p>%d won, %d lost</p></div>' % (e(fmt_pct(s['winRate']) if s['n'] else 'n/a'), s['wins'], s['losses']))
    body.append('<div class="t"><h2>Expectancy</h2><div class="big">%s</div><p>%s</p></div>'
                % (e(money(rnd(s['expectancy']), base, sign=True) if s['n'] else 'n/a'), e('Average ' + fmt_r(s['avgR']) if s['avgR'] is not None else 'No R: add stops')))
    body.append('<div class="t"><h2>Rule breaches</h2><div class="big %s">%d</div><p>%d trades broke a rule: %s</p></div>'
                % ('loss' if rv['breaches'] else '', len(rv['breaches']), rv['broke']['n'], e(money(rv['broke']['net'], base, sign=True))))
    body.append('</section>')
    body.append('<section class="sheet"><h2>What the week says</h2><ol class="notes">%s</ol>%s</section>'
                % (''.join('<li>%s</li>' % e(n) for n in rv['notes']), stat_grid(s, base)))
    body.append('<section class="sheet"><h2>Running total after fees</h2>%s<p class="muted">Every closed trade; the yellow band is this week.</p></section>'
                % equity_svg([t for t in result['closed'] if not rv['account'] or t['account'] == rv['account']], base, (rv['week'], rv['week'] + 6)))
    body.append('<section class="sheet"><h2>By setup</h2>%s</section>' % bars(rv['bySetup'], base, sub=lambda r: '%s, %d won%s' % (
        plural(r['n'], 'trade'), r['wins'], ', average ' + fmt_r(r['avgR']) if r['avgR'] is not None else '')))
    rows = []
    for tid in rv['trades']:
        t = by_id[tid]
        rows.append('<tr><td>%s %s</td><td>%s</td><td>%s</td><td class="n">%s</td><td class="n">%s</td><td class="n %s">%s</td><td class="n">%s</td><td>%s</td><td>%s</td></tr>' % (
            e(fmt_short(t['openDay'])), e(fmt_time(t['openSec'])), e(t['symbol'] + (' long' if t['dir'] > 0 else ' short')), e(t['account']), e(fmt_qty(t['maxPos'])),
            e(fmt_duration(t['holdSec'], t['timeKnown'])), cls(t['net']), e(money(t['net'], t['currency'], sign=True)), e(fmt_r(t['r'])), e(t['setup']), e('; '.join(t['mistakes']))))
    body.append('<section class="sheet"><h2>Trades closed this week</h2><table><thead><tr><th>Opened</th><th>Trade</th><th>Account</th><th class="n">Size</th><th class="n">Held</th>'
                '<th class="n">Net</th><th class="n">R</th><th>Setup</th><th>Mistakes</th></tr></thead><tbody>%s</tbody></table></section>' % ''.join(rows))
    if rv['breaches']:
        body.append('<section class="sheet"><h2>Rule breaches</h2><table><thead><tr><th>When</th><th>Rule</th><th>What happened</th><th>Trade</th></tr></thead><tbody>%s</tbody></table></section>' % ''.join(
            '<tr><td>%s %s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (e(fmt_short(b['day'])), e(fmt_time(b['sec'])), e(b['label']), e(b['detail']),
                                                                          e(trade_name(by_id[b['trade']]) if b['trade'] else b['account'])) for b in rv['breaches']))
    if rv['openAtEnd']:
        body.append('<section class="sheet"><h2>Open at the end of the week</h2><p>%s</p></section>' % e('; '.join(
            '%s %s %s at %s' % (o['symbol'], 'long' if o['dir'] > 0 else 'short', fmt_qty(o['q']), fmt_price(rnd(o['avgEntry'] / 100) * 100)) for o in rv['openAtEnd'])))
    body.append('<section class="sheet"><h2>For the team chat</h2><pre>%s</pre></section>' % e(text))
    return page('Weekly trade review, ' + rv['label'], ''.join(body))


MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']


def calendar_html(ledger, base, start, end):
    """Month grids of each trading day's realised result after fees, with week totals."""
    from .common import civil, days_from_civil, weekday as wd
    by_day = {d['day']: d for d in ledger}
    out = []
    c0, c1 = civil(start), civil(end)
    y, mo = c0[0], c0[1]
    while (y, mo) <= (c1[0], c1[1]):
        first = days_from_civil(y, mo, 1)
        nxt = days_from_civil(y + 1, 1, 1) if mo == 12 else days_from_civil(y, mo + 1, 1)
        rows = []
        w = first - wd(first)
        while w < nxt:
            cells, total, any_day = [], 0, False
            for k in range(7):
                day = w + k
                x = by_day.get(day)
                if day < first or day >= nxt:
                    cells.append('<td></td>')
                elif not x:
                    cells.append('<td class="muted">%d</td>' % civil(day)[2])
                else:
                    total += x['realised']
                    any_day = True
                    cells.append('<td style="background:%s"><span class="muted">%d</span><br><strong class="%s">%s</strong>%s</td>' % (
                        'rgba(38,48,122,.1)' if x['realised'] > 0 else ('rgba(179,48,29,.1)' if x['realised'] < 0 else 'transparent'), civil(day)[2], cls(x['realised']),
                        e(money(x['realised'], base, sign=True, whole=True)), '<br><span class="loss">LIMIT</span>' if x['limitHit'] else ''))
            cells.append('<td class="n %s">%s</td>' % (cls(total), e(money(total, base, sign=True, whole=True)) if any_day else ''))
            rows.append('<tr>%s</tr>' % ''.join(cells))
            w += 7
        out.append('<h3>%s %d</h3><table><thead><tr>%s<th class="n">Week</th></tr></thead><tbody>%s</tbody></table>' % (
            MONTHS[mo - 1], y, ''.join('<th>%s</th>' % d for d in ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')), ''.join(rows)))
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    return ''.join(out)


def period_report(result, start, end, account=''):
    """A report for any span of days (a month, a term, a whole challenge): weeks, days, setups, rules and what keeping to them would have changed."""
    from .common import to_iso
    from .days import day_ledger
    from .stats import breakdown, filter_trades, stats, start_balance, weekly, what_if
    base = result['settings']['base']
    trades = filter_trades(result['closed'], account, start, end)
    before = filter_trades(result['closed'], account, None, start - 1)
    start_bal = start_balance(result, [account] if account else result['accounts']) + sum(t['netBase'] for t in usable(before))
    s = stats(trades, start_bal)
    breaches = [b for b in result['breaches'] if (not account or b['account'] == account) and start <= b['day'] <= end]
    wi = what_if(result, account, start, end)
    title = '%s to %s' % (fmt_day_month_year(start), fmt_day_month_year(end))
    body = ['<header><div class="kicker">Round trips &middot; period report</div><h1>%s</h1><p>%s, %s closed. All figures after fees, in %s.</p><span class="stamp">Not financial advice</span></header>'
            % (e(title), e(account or 'all accounts'), e(plural(s['n'], 'trade')), e(base))]
    body.append('<section class="sheet"><h2>The period</h2>%s</section>' % stat_grid(s, base))
    wk = weekly(trades)
    wrows = ''.join('<tr><td>%s</td><td class="n">%d</td><td class="n %s">%s</td><td class="n">%s</td><td class="n">%d</td></tr>' % (
        e(fmt_day_month_year(w['week'])), w['n'], cls(w['net']), e(money(w['net'], base, sign=True)), e(fmt_pct(w['wins'] / w['n'])),
        len([b for b in breaches if w['week'] <= b['day'] <= w['week'] + 6])) for w in wk)
    body.append('<section class="sheet"><h2>Week by week</h2><table><thead><tr><th>Week of</th><th class="n">Trades</th><th class="n">Net</th><th class="n">Won</th><th class="n">Breaches</th></tr></thead><tbody>%s</tbody></table></section>' % wrows)
    body.append('<section class="sheet"><h2>Running total after fees</h2>%s</section>' % equity_svg([t for t in result['closed'] if not account or t['account'] == account], base, (start, end)))
    ledger = [d for d in day_ledger(result, account) if start <= d['day'] <= end]
    if ledger:
        body.append('<section class="sheet"><h2>Day by day</h2>%s<p class="muted">%d of %d trading days ended up; the daily loss limit was hit on %d.</p></section>' % (
            calendar_html(ledger, base, ledger[0]['day'], ledger[-1]['day']), len([d for d in ledger if d['realised'] > 0]), len(ledger), len([d for d in ledger if d['limitHit']])))
    body.append('<section class="sheet"><h2>By setup</h2>%s<h2 style="margin-top:16px">By symbol</h2>%s</section>' % (
        bars(breakdown(trades, 'setup'), base, sub=lambda r: '%s, %s won%s' % (plural(r['n'], 'trade'), fmt_pct(r['winRate']), ', average ' + fmt_r(r['avgR']) if r['avgR'] is not None else '')),
        bars(breakdown(trades, 'symbol'), base)))
    counts = {}
    for b in breaches:
        counts[b['rule']] = counts.get(b['rule'], 0) + 1
    from .matching import RULES
    body.append('<section class="sheet"><h2>Rules</h2><table><tbody>%s</tbody></table>'
                '<p>If every rule had been kept: about <strong class="%s">%s</strong> instead of <strong class="%s">%s</strong> (skipping %s the rules ruled out %s, sizing %s within the limit %s, taking %s as planned %s). An estimate: other trades are left as they were.</p></section>' % (
                    ''.join('<tr><td>%s</td><td class="n">%d</td></tr>' % (e(x['label']), counts.get(x['id'], 0)) for x in RULES),
                    cls(wi['combined']), e(money(wi['combined'], base, sign=True)), cls(wi['actual']), e(money(wi['actual'], base, sign=True)),
                    e(plural(wi['skip']['n'], 'trade')), e(money(wi['skip']['change'], base, sign=True)), e(plural(wi['size']['n'], 'trade')), e(money(wi['size']['change'], base, sign=True)),
                    e(plural(wi['cap']['n'], 'stop')), e(money(wi['cap']['change'], base, sign=True))))
    mistakes = [r for r in breakdown(trades, 'mistake') if r['key'] != '(none tagged)']
    if mistakes:
        body.append('<section class="sheet"><h2>What the mistakes cost</h2>%s</section>' % bars(mistakes, base, sub=lambda r: plural(r['n'], 'trade')))
    return page('Trade report, ' + title, ''.join(body))


def team_report(team, base, week):
    """The team review: one row per member with risk-adjusted figures and rule breaches."""
    body = ['<header><div class="kicker">Round trips &middot; team review</div><h1>Team review</h1><p>%s %s. All figures after fees, in %s.</p><span class="stamp">Not financial advice</span></header>'
            % (e(plural(len(team['members']), 'member')), e('with ' + fmt_day_month_year(week) + ' as the week' if week is not None else ''), e(base))]
    head = ('<tr><th>Member</th><th class="n">Trades</th><th class="n">Net</th><th class="n">Win rate</th><th class="n">Expectancy</th><th class="n">Profit factor</th>'
            '<th class="n">Avg R</th><th class="n">Largest drop</th><th class="n">Net / drop</th><th class="n">Sharpe</th><th class="n">Breaches</th></tr>')
    rows = []
    for mbr in team['members']:
        s = mbr['stats']
        rows.append('<tr><td><strong>%s</strong><br><span class="muted">%s</span></td><td class="n">%d</td><td class="n %s">%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td>'
                    '<td class="n">%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%d</td></tr>' % (
                        e(mbr['name']), e(', '.join(mbr['accounts'])), s['n'], cls(s['net']), e(money(s['net'], base, sign=True)), e(fmt_pct(s['winRate'])),
                        e('' if s['expectancy'] is None else money(rnd(s['expectancy']), base, sign=True)), e('' if s['profitFactor'] is None else fmt_num(s['profitFactor'], 2)),
                        e(fmt_r(s['avgR'])), e(money(s['maxDD'], base) + ('' if s['maxDDPct'] is None else ' (%s%%)' % fmt_num(s['maxDDPct'], 1))),
                        e('' if s['recovery'] is None else fmt_num(s['recovery'], 2)), e('' if s['sharpe'] is None else fmt_num(s['sharpe'], 2)), mbr['breachTotal']))
    body.append('<section class="sheet"><h2>Everyone, all weeks</h2><div style="overflow-x:auto"><table><thead>%s</thead><tbody>%s</tbody></table></div>'
                '<p class="muted">Net / drop is net profit divided by the largest drop from a high. Sharpe uses daily net on days a trade closed, as a return on the starting balance, times the square root of 252.</p></section>'
                % (head, ''.join(rows)))
    if week is not None:
        wrows = []
        for mbr in team['members']:
            s = mbr['week']
            wrows.append('<tr><td><strong>%s</strong></td><td class="n">%d</td><td class="n %s">%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%d</td><td>%s</td></tr>' % (
                e(mbr['name']), s['n'], cls(s['net']), e(money(s['net'], base, sign=True)), e(fmt_pct(s['winRate'])), e(fmt_r(s['avgR'])), mbr['weekBreaches'],
                e(' '.join(mbr['weekNotes'][:2]))))
        body.append('<section class="sheet"><h2>%s</h2><table><thead><tr><th>Member</th><th class="n">Trades</th><th class="n">Net</th><th class="n">Win rate</th><th class="n">Avg R</th>'
                    '<th class="n">Breaches</th><th>Notes</th></tr></thead><tbody>%s</tbody></table></section>' % (e('Week of ' + fmt_day_month_year(week)), ''.join(wrows)))
    rule_ids = team['rules']
    brows = ''.join('<tr><td><strong>%s</strong></td>%s</tr>' % (e(mbr['name']), ''.join('<td class="n">%d</td>' % mbr['breachByRule'].get(r['id'], 0) for r in rule_ids))
                    for mbr in team['members'])
    body.append('<section class="sheet"><h2>Rule breaches, all weeks</h2><div style="overflow-x:auto"><table><thead><tr><th>Member</th>%s</tr></thead><tbody>%s</tbody></table></div></section>'
                % (''.join('<th class="n">%s</th>' % e(r['label']) for r in rule_ids), brows))
    body.append('<section class="sheet"><h2>Running totals</h2>%s</section>' % ''.join(
        '<h3>%s</h3>%s' % (e(mbr['name']), equity_svg(mbr['closed'], base, None, 1000, 200)) for mbr in team['members']))
    if team['problems']:
        body.append('<section class="sheet"><h2>Files that need a look</h2><ul>%s</ul></section>' % ''.join('<li>%s</li>' % e(p) for p in team['problems']))
    return page('Team trade review', ''.join(body))
