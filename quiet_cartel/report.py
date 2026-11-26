"""One self-contained HTML report from saved results.

The page uses inline CSS and inline SVG only: no scripts, no web fonts and no
links to anything outside the file, so it works offline, can be emailed, and
follows the reader's light or dark setting (``prefers-color-scheme``). Every
piece of text that comes from data is escaped. Each section appears only when
its results are given:

* remedies (from ``remedies --json``): bar chart of the mean realised profit
  gain with 90% intervals, and a table with the paired comparisons;
* sweep (from ``sweep --json``): heat map of the mean realised profit gain;
* screening (from ``screen --json``): how well each screen ranks the real
  cases, the false discovery rate flag, and the flagged markets;
* calibration (part of ``screen --json`` when the file has sales): fitted
  against true loyalty, and the fitted price benchmarks.
"""

import datetime
import html
import math

from . import model

__all__ = ['build_report', 'SECTION_TITLES']

SECTION_TITLES = {
    'remedies': 'Remedies: what brings prices down',
    'sweep': 'Sweep: where prices settle',
    'screening': 'Screening: could a regulator spot it?',
    'calibration': 'Calibration: demand fitted to sales',
}
GROUP_LABEL = {'baseline': 'Baseline', 'remedy': 'Possible remedy', 'design': 'Design choice', 'risk': 'Possible risk'}
MINUS = '−'

CSS = """
:root {
  --bg: #f5f6f8; --card: #ffffff; --ink: #1b2130; --muted: #5a6275; --line: #dde1e8; --soft: #eef0f4;
  --accent: #3b4fd8; --good: #1f7a4d; --bad: #b3261e; --warn: #8a5a00; --warn-soft: #fdf1d8;
  --g-baseline: #5a6275; --g-remedy: #1f8f5f; --g-design: #8a7f3c; --g-risk: #c2412d;
  --heat-lo: #f3f0ff; --heat-hi: #3b2a8f; --heat-ink: #ffffff; --point: #3b4fd8;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #12151c; --card: #1b2029; --ink: #e8ebf2; --muted: #a2aabb; --line: #2e3542; --soft: #232935;
    --accent: #8d9bff; --good: #5fd39a; --bad: #ff7b72; --warn: #f0c060; --warn-soft: #3a2f14;
    --g-baseline: #a2aabb; --g-remedy: #4fd19a; --g-design: #d4c46a; --g-risk: #ff8a70;
    --heat-lo: #232935; --heat-hi: #b9b0ff; --heat-ink: #10131a; --point: #8d9bff;
    color-scheme: dark;
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
.wrap { max-width: 960px; margin: 0 auto; padding: 20px 16px 40px; }
h1 { font-size: 1.6rem; line-height: 1.2; margin: 0 0 .4rem; letter-spacing: -.01em; }
h2 { font-size: 1.2rem; margin: 0 0 .6rem; }
h3 { font-size: 1rem; margin: 1.1rem 0 .4rem; }
p { margin: 0 0 .7rem; }
.lead { color: var(--muted); max-width: 760px; }
.notice { background: var(--warn-soft); color: var(--warn); border-radius: 8px; padding: 8px 12px; font-size: .9rem; }
nav { display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 12px 0 4px; font-size: .9rem; }
nav a { color: var(--accent); }
section, .card { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 16px; margin: 16px 0;
  min-width: 0; }
.muted { color: var(--muted); }
.small { font-size: .85rem; }
.caption { color: var(--muted); font-size: .85rem; margin: 6px 0 0; }
.tablewrap { overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 8px 0; }
table { border-collapse: collapse; width: 100%; font-size: .86rem; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: .8rem; }
td.num { text-align: right; white-space: nowrap; }
th.num { text-align: right; }
table.wide { min-width: 860px; }
td.label { min-width: 11rem; }
tr.base td { background: var(--soft); }
.swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: baseline; }
.swatch.heat { position: relative; overflow: hidden; background: var(--heat-lo); outline: 1px solid var(--line); }
.swatch.heat i { position: absolute; inset: 0; background: var(--heat-hi); }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: .84rem; color: var(--muted); margin: 6px 0; }
.chart svg { display: block; width: 100%; height: auto; }
.chart text { fill: var(--muted); font-size: 13px; font-family: inherit; }
.chart .ink { fill: var(--ink); font-weight: 600; }
.chart .axis { stroke: var(--line); }
.chart .grid { stroke: var(--soft); }
.chart .zero { stroke: var(--muted); }
.chart .whisker { stroke: var(--ink); stroke-width: 1.5; }
.chart .heat-lo { fill: var(--heat-lo); }
.chart .heat-hi { fill: var(--heat-hi); }
.chart text.on-hi { fill: var(--heat-ink); }
.chart .diag { stroke: var(--muted); stroke-dasharray: 4 4; }
.chart .pt { fill: var(--point); stroke: var(--card); stroke-width: 1; }
.chart .pt-ci { stroke: var(--point); stroke-width: 1.2; opacity: .6; }
.g-baseline { fill: var(--g-baseline); background: var(--g-baseline); }
.g-remedy { fill: var(--g-remedy); background: var(--g-remedy); }
.g-design { fill: var(--g-design); background: var(--g-design); }
.g-risk { fill: var(--g-risk); background: var(--g-risk); }
.pill { display: inline-block; padding: 0 7px; border-radius: 10px; font-size: .78rem; font-weight: 600;
  border: 1px solid currentColor; }
.pill.bad { color: var(--bad); } .pill.good { color: var(--good); }
dl.settings { display: grid; grid-template-columns: minmax(0, 11rem) minmax(0, 1fr); gap: 4px 12px; font-size: .85rem;
  margin: 6px 0 12px; }
dl.settings dt { color: var(--muted); }
dl.settings dd { margin: 0; overflow-wrap: anywhere; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .84rem; overflow-wrap: anywhere; }
details summary { cursor: pointer; font-weight: 600; }
footer { color: var(--muted); font-size: .8rem; margin-top: 24px; }
@media (max-width: 560px) {
  section, .card { padding: 12px; }
  .chart text { font-size: 15px; }
  dl.settings { grid-template-columns: minmax(0, 1fr); }
  dl.settings dd { margin-bottom: 6px; }
  h1 { font-size: 1.35rem; }
}
"""


# ------------------------------------------------------------ small helpers

def e(x):
    """Escape any value for HTML text or attributes."""
    return html.escape('' if x is None else str(x), quote=True)


def _ok(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def pct(x, d=0):
    if not _ok(x):
        return 'n/a'
    s = '%.*f%%' % (d, x * 100)
    if s.startswith('-') and not s.strip('-0.%'):
        return s[1:]                    # no "-0%"
    return MINUS + s[1:] if s.startswith('-') else s


def pts(x):
    return 'n/a' if not _ok(x) else _signed(x) + ' pts'


def num(x, d=3):
    if not _ok(x):
        return 'n/a'
    s = '%.*f' % (d, x)
    return MINUS + s[1:] if s.startswith('-') else s


def money(x):
    return 'n/a' if not _ok(x) else (MINUS if x < 0 else '') + '£%.2f' % abs(x)


def _signed(x):
    """A difference in percentage points without the unit, for intervals, such as +12 or −3."""
    if not _ok(x):
        return 'n/a'
    s = '%+.0f' % (x * 100)
    if s in ('+0', '-0'):
        return '0'
    return MINUS + s[1:] if s.startswith('-') else s


def pval(p):
    return 'n/a' if not _ok(p) else '&lt;0.001' if p < 0.001 else '%.3f' % p


def _f(x):
    """Coordinates with one decimal place, so the SVG stays small."""
    return ('%.1f' % x).rstrip('0').rstrip('.')


def _nice_ticks(lo, hi, count=5):
    if not hi > lo:
        return [lo]
    raw = (hi - lo) / max(1, count)
    mag = 10 ** math.floor(math.log10(raw))
    r = raw / mag
    step = (1 if r < 1.5 else 2 if r < 3 else 5 if r < 7 else 10) * mag
    v = math.ceil(lo / step - 1e-9) * step
    out = []
    while v <= hi + 1e-9 * step:
        out.append(0.0 if abs(v) < step * 1e-9 else v)
        v += step
    return out


def _table(headers, rows, num_cols=(), row_class=None, wide=False, label_cols=()):
    """``headers`` and ``rows`` hold HTML already escaped; ``num_cols`` are right-aligned.

    A ``wide`` table keeps a minimum width and scrolls sideways inside its box on a
    narrow screen, rather than squeezing its text into one word per line;
    ``label_cols`` (default: the first column of a wide table) keep a readable width.
    """
    num_cols = set(num_cols)
    labels = set(label_cols) if label_cols else ({0} if wide else set())

    def cls(k):
        names = (['num'] if k in num_cols else []) + (['label'] if k in labels else [])
        return ' class="%s"' % ' '.join(names) if names else ''

    head = ''.join('<th%s>%s</th>' % (' class="num"' if k in num_cols else '', h) for k, h in enumerate(headers))
    body = []
    for n, r in enumerate(rows):
        rc = row_class(n) if row_class else ''
        body.append('<tr%s>%s</tr>' % (' class="%s"' % rc if rc else '', ''.join(
            '<td%s>%s</td>' % (cls(k), c) for k, c in enumerate(r))))
    return '<div class="tablewrap"><table%s><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (
        ' class="wide"' if wide else '', head, ''.join(body))


def _svg(w, h, label, inner, max_width=None):
    """An inline SVG chart that scales with the page, up to ``max_width`` pixels (default 1.3 times its own width)."""
    return ('<div class="chart"><svg viewBox="0 0 %s %s" role="img" aria-label="%s" style="max-width:%dpx">%s</svg>'
            '</div>' % (_f(w), _f(h), e(label), round(max_width or w * 1.3), ''.join(inner)))


def _text(x, y, s, cls='', anchor='start', extra=''):
    return '<text x="%s" y="%s"%s%s%s>%s</text>' % (
        _f(x), _f(y), ' class="%s"' % cls if cls else '', ' text-anchor="%s"' % anchor if anchor != 'start' else '',
        ' ' + extra if extra else '', s)


def _settings_list(part):
    """The command and settings that produced a saved result."""
    items = [('Command', '<code>%s</code>' % e(part.get('command', 'unknown')))]
    settings = part.get('settings') or {}
    for k, v in settings.items():
        if k == 'base':
            continue
        if isinstance(v, list):
            v = ', '.join(str(x) for x in v) or 'none'
        items.append((e(k), e(v)))
    base = settings.get('base')
    if base:
        n = base.get('nFirms', 2)
        cfg = ', '.join('%s %s' % (k, v[:n] if isinstance(v, list) else v) for k, v in base.items() if k != 'seed')
        items.append(('Model settings', '<code>%s</code>' % e(cfg)))
    if _ok(part.get('seconds')):
        items.append(('Run time', '%.1f s' % part['seconds']))
    return '<dl class="settings">%s</dl>' % ''.join('<dt>%s</dt><dd>%s</dd>' % kv for kv in items)


# ------------------------------------------------------------ remedies

def _remedies_chart(summary):
    rows = [summary['scenarios'][sid] for sid in summary['order']]
    rows.sort(key=lambda s: -(s['agg']['gain']['mean'] if _ok(s['agg']['gain']['mean']) else -9))
    W, rowH, top, left, right = 440, 40, 6, 16, 46
    H = top + rowH * len(rows) + 26
    lows = [s['agg']['gain']['lo'] for s in rows if _ok(s['agg']['gain']['lo'])]
    highs = [s['agg']['gain']['hi'] for s in rows if _ok(s['agg']['gain']['hi'])]
    lo, hi = min([0.0] + lows), max([1.0] + highs)

    def X(v):
        return left + (v - lo) / (hi - lo) * (W - left - right)

    inner = []
    tick_values = _nice_ticks(lo, hi, 5)
    for v in tick_values:
        inner.append(_text(X(v), H - 6, pct(v), anchor='middle'))
    for k in range(len(rows)):
        # Grid lines run only across each row's bar band, so they never cross the labels above the bars.
        y = top + k * rowH
        for v in tick_values:
            inner.append('<line class="grid" x1="%s" x2="%s" y1="%s" y2="%s"/>' % (
                _f(X(v)), _f(X(v)), _f(y + 16), _f(y + 36 if k < len(rows) - 1 else H - 22)))
        inner.append('<line class="zero" x1="%s" x2="%s" y1="%s" y2="%s"/>' % (_f(X(0)), _f(X(0)), _f(y + 16),
                                                                               _f(y + 36)))
    for k, s in enumerate(rows):
        y = top + k * rowH
        g = s['agg']['gain']
        inner.append(_text(4, y + 13, e(s['label']), cls='ink' if s['id'] == 'baseline' else ''))
        if not _ok(g['mean']):
            continue
        x0, x1 = X(min(0, g['mean'])), X(max(0, g['mean']))
        title = '%s: %s' % (s['label'], pct(g['mean']))
        if _ok(g['lo']) and _ok(g['hi']):
            title += ' (90%% interval %s to %s)' % (pct(g['lo']), pct(g['hi']))
        inner.append('<rect class="g-%s" x="%s" y="%s" width="%s" height="13" rx="3"><title>%s</title></rect>' % (
            e(s['group']), _f(x0), _f(y + 19), _f(max(1, x1 - x0)), e(title)))
        end = max(0.0, g['mean'])          # the label goes right of the bar, its whisker and zero
        if _ok(g['lo']) and _ok(g['hi']):
            end = max(end, g['hi'])
            for a, b, c, d in ((X(g['lo']), X(g['hi']), y + 25.5, y + 25.5), (X(g['lo']), X(g['lo']), y + 20, y + 31),
                               (X(g['hi']), X(g['hi']), y + 20, y + 31)):
                inner.append('<line class="whisker" x1="%s" x2="%s" y1="%s" y2="%s"/>' % (_f(a), _f(b), _f(c), _f(d)))
        inner.append(_text(min(W - 2, X(end) + 6), y + 30, pct(g['mean']), cls='ink'))
    return _svg(W, H, 'Bar chart of the mean realised profit gain for %d options, with 90%% intervals' % len(rows),
                inner)


def _remedies_section(part):
    summary = part['summary']
    groups = []
    for sid in summary['order']:
        g = summary['scenarios'][sid]['group']
        if g not in groups:
            groups.append(g)
    legend = '<div class="legend">%s</div>' % ''.join(
        '<span><i class="swatch g-%s"></i>%s</span>' % (e(g), e(GROUP_LABEL.get(g, g))) for g in groups)
    runs = summary['scenarios']['baseline']['agg']['runs']
    rows = []
    for sid in summary['order']:
        s = summary['scenarios'][sid]
        a, vs = s['agg'], s['vsBaseline']
        gd, hd = (vs['realisedGain'], vs['harm']) if vs else (None, None)
        rows.append([
            '<i class="swatch g-%s"></i>%s' % (e(s['group']), e(s['label'])),
            '%s<br><span class="small muted">%s to %s</span>' % (pct(a['gain']['mean']), pct(a['gain']['lo']),
                                                                 pct(a['gain']['hi'])),
            '%s<br><span class="small muted">%s to %s</span>' % (pts(gd['diff']), _signed(gd['lo']), _signed(gd['hi']))
            if gd else '<span class="muted">baseline</span>',
            pval(gd['pHolm']) if gd else '',
            '%s<br><span class="small muted">%s to %s</span>' % (pct(a['harm']['mean']), pct(a['harm']['lo']),
                                                                 pct(a['harm']['hi'])),
            '%s<br><span class="small muted">Holm p %s</span>' % (pts(hd['diff']), pval(hd['pHolm'])) if hd else '',
            pct(a['punishedShare']), pct(a['convergedShare']),
            pct(s.get('replyGain'), 1) if s.get('replyGain') is not None else 'n/a',
        ])
    table = _table(['Option', 'Profit gain<br>(90% interval)', 'Change vs baseline<br>(paired 90% interval)', 'Holm p',
                    'Shoppers’ loss<br>(90% interval)', 'Change in loss', 'Punished', 'Settled', 'Gain from best reply'],
                   rows, num_cols=range(1, 9), row_class=lambda n: 'base' if summary['order'][n] == 'baseline' else '',
                   wide=True)
    notes = '<details><summary>What each option means</summary><dl class="settings">%s</dl></details>' % ''.join(
        '<dt>%s</dt><dd>%s</dd>' % (e(summary['scenarios'][sid]['label']), e(summary['scenarios'][sid].get('note', '')))
        for sid in summary['order'])
    return ''.join([
        '<section id="remedies"><h2>%s</h2>' % e(SECTION_TITLES['remedies']),
        '<p class="lead">Each option was trained %s (seeds %s), and each run is compared with the baseline run '
        'that has the same seed. Profit gain is 0%% at competitive prices and 100%% at monopoly prices, measured over '
        'the last 100,000 rounds of training.</p>' % ({1: 'once', 2: 'twice'}.get(runs, '%d times' % runs),
                                                      e(_seed_range(summary['seeds']))),
        _remedies_chart(summary), legend,
        '<p class="caption">Bars show the mean realised profit gain; whiskers its 90% bootstrap interval (the same '
        'interval the browser app shows for the same runs).</p>',
        table,
        '<p class="caption">Change is the mean difference from the paired baseline run, with a 90% bootstrap interval '
        'over the pairs. The p-value is a two-sided sign-flip permutation test (exact for 16 pairs or fewer), adjusted '
        'with Holm’s method across all the options shown. Shoppers’ loss is the share of the gap between '
        'competitive and monopoly consumer surplus that shoppers lose. Punished is the share of runs in which a '
        'one-day price cut is answered and loses money overall; settled is the share whose strategies stopped '
        'changing. Gain from best reply is how much more a learning seller would earn over time, from where play '
        'settled, by switching to its exact best reply to the others\u2019 learned strategies, from the model\u2019s '
        'best-response check (two sellers only). Zero would mean the learned strategies form an equilibrium.</p>',
        notes,
        '<details><summary>Command and settings</summary>%s</details></section>' % _settings_list(part),
    ])


def _seed_range(seeds):
    if not seeds:
        return 'none'
    if seeds == list(range(seeds[0], seeds[0] + len(seeds))):
        return '%s to %s' % (seeds[0], seeds[-1]) if len(seeds) > 1 else str(seeds[0])
    return ', '.join(str(s) for s in seeds)


# ------------------------------------------------------------ sweep

def _heat_map(sw, key='gain'):
    xs, ys = sw['x']['values'], sw['y']['values']
    cw = max(46, min(84, 400 / max(1, len(xs))))
    ch, left, top, bottom = 34, 78, 8, 44
    W, H = left + cw * len(xs) + 8, top + ch * len(ys) + bottom
    inner = []
    for iy, (y, line) in enumerate(zip(ys, sw['cells'])):
        # The largest y value goes at the top, like an ordinary chart axis.
        r = len(ys) - 1 - iy
        yy = top + r * ch
        inner.append(_text(left - 8, yy + ch / 2 + 4, e(_short(y)), anchor='end'))
        for ix, cell in enumerate(line):
            v = cell.get(key)
            t = min(1.0, max(0.0, v)) if _ok(v) else 0.0
            x = left + ix * cw
            label = '%s %s, %s %s: %s, punished in %s of runs, settled in %s' % (
                sw['x']['param'], _short(cell['x']), sw['y']['param'], _short(cell['y']), pct(v),
                pct(cell.get('punishedShare')), pct(cell.get('convergedShare')))
            inner.append('<g><title>%s</title><rect class="heat-lo" x="%s" y="%s" width="%s" height="%s" rx="2"/>'
                         '<rect class="heat-hi" x="%s" y="%s" width="%s" height="%s" rx="2" fill-opacity="%.2f"/>%s</g>'
                         % (e(label), _f(x + 1), _f(yy + 1), _f(cw - 2), _f(ch - 2), _f(x + 1), _f(yy + 1),
                            _f(cw - 2), _f(ch - 2), t,
                            _text(x + cw / 2, yy + ch / 2 + 4, pct(v), cls='on-hi' if t > 0.55 else 'ink',
                                  anchor='middle')))
    for ix, x in enumerate(xs):
        inner.append(_text(left + ix * cw + cw / 2, top + ch * len(ys) + 16, e(_short(x)), anchor='middle'))
    inner.append(_text(left + cw * len(xs) / 2, H - 6, e(sw['x']['param']) + ' →', cls='ink', anchor='middle'))
    cy = top + ch * len(ys) / 2
    inner.append(_text(14, cy, e(sw['y']['param']) + ' →', cls='ink', anchor='middle',
                       extra='transform="rotate(-90 14 %s)"' % _f(cy)))
    return _svg(W, H, 'Heat map of mean realised profit gain by %s and %s' % (sw['x']['param'], sw['y']['param']),
                inner)


def _short(v):
    return ('%.6g' % v) if isinstance(v, float) else str(v)


def _sweep_section(part):
    sw = part['sweep']
    settings = part.get('settings') or {}
    rows = []
    for line in sw['cells']:
        for c in line:
            rows.append([e(_short(c['x'])), e(_short(c['y'])), str(c.get('runs', '')), pct(c.get('gain')),
                         pct(c.get('harm')), pct(c.get('punishedShare')), pct(c.get('convergedShare'))])
    key = ''.join('<span><i class="swatch heat"><i style="opacity:%.2f"></i></i>%s</span>' % (t, pct(t))
                  for t in (0.0, 0.25, 0.5, 0.75, 1.0))
    return ''.join([
        '<section id="sweep"><h2>%s</h2>' % e(SECTION_TITLES['sweep']),
        '<p class="lead">Mean realised profit gain for every combination of %s and %s, under “%s”, with %s '
        'run%s per cell.</p>' % (e(sw['x']['param']), e(sw['y']['param']),
                                 e(settings.get('scenarioLabel', sw.get('scenario', ''))),
                                 len(sw.get('seeds', [])), '' if len(sw.get('seeds', [])) == 1 else 's'),
        _heat_map(sw), '<div class="legend">%s</div>' % key,
        '<p class="caption">Darker cells settle closer to monopoly prices (gains below 0% are shaded as 0%). Hover '
        'over a cell for the share of runs in which a cut is punished.</p>',
        '<details><summary>Every cell</summary>%s</details>' % _table(
            [e(sw['x']['param']), e(sw['y']['param']), 'Runs', 'Profit gain', 'Shoppers’ loss', 'Punished',
             'Settled'], rows, num_cols=range(0, 7)),
        '<details><summary>Command and settings</summary>%s</details></section>' % _settings_list(part),
    ])


# ------------------------------------------------------------ screening

def _screening_section(part):
    res = part['results']
    settings = part.get('settings') or {}
    ev = res.get('evaluation')
    markets = res['markets']
    flagged = [r for r in markets if r.get('flag')]
    out = ['<section id="screening"><h2>%s</h2>' % e(SECTION_TITLES['screening']),
           '<p class="lead">%d markets were screened from daily prices%s. Each market’s retaliation screen was '
           'tested with %s circular shifts of the rival’s prices, the p-values were turned into '
           'Benjamini-Hochberg q-values across markets, and a market is flagged when q is below %s and rivals hit '
           'back more often after an unprovoked cut than on an ordinary day.</p>' % (
               len(markets), ' and sales' if settings.get('sales') else '', e(settings.get('reps', '?')),
               e(settings.get('flagQ', 0.1)))]
    if ev:
        tg = ev['targets']
        rows = []
        for k, s in enumerate(tg[0]['screens']):
            rows.append(['<strong>%s</strong><br><span class="small muted">%s</span>' % (e(s['label']), e(s['note']))]
                        + [num(t['screens'][k]['auc'], 2) for t in tg])
        out.append('<h3>How well each screen ranks the real cases</h3>')
        out.append(_table(['Screen'] + ['%s<br><span class="small">%d of %d markets</span>' % (
            e(t['label']), t['positives'], t['positives'] + t['negatives']) for t in tg], rows, num_cols=range(1, 3),
            label_cols=[0]))
        out.append('<p class="caption">ROC AUC: the chance that a randomly chosen real case scores higher than a '
                   'randomly chosen innocent market (0.5 is no better than a coin, 1 is perfect). %s</p>' % ' '.join(
                       '“%s”: %s' % (e(t['label']), e(t['note'])) for t in tg))
        if tg[0]['flag'] is not None:
            rows = []
            for t in tg:
                c = t['flag']
                rows.append([e(t['label']), str(c['caught']), str(c['falseAlarms']), str(c['missed']),
                             str(c['cleared']), pct(c['precision']), pct(c['recall'])])
            out.append('<h3>The flag against each definition</h3>')
            out.append(_table(['Definition', 'Caught', 'False alarms', 'Missed', 'Cleared', 'Precision', 'Recall'],
                              rows, num_cols=range(1, 7)))
    out.append('<h3>Flagged markets (%d)</h3>' % len(flagged))
    truth_cols = any(r.get('truth') for r in markets)
    if flagged:
        out.append(_market_table(flagged, truth_cols))
    else:
        out.append('<p>No market was flagged.</p>')
    out.append('<details><summary>Every market</summary>%s</details>' % _market_table(markets, truth_cols))
    out.append('<details><summary>Command and settings</summary>%s</details></section>' % _settings_list(part))
    return ''.join(out)


def _market_table(markets, truth_cols):
    has_excess = any(r.get('excessPrice') is not None for r in markets)
    rows = []
    for r in markets:
        sc = r['screens']
        row = [e(r['market']), str(r['days']), pct(sc.get('margin')), num(sc.get('cv')), str(sc.get('events')),
               pct(sc.get('retaliation')), pval(r.get('pValue')), pval(r.get('qValue')),
               '<span class="pill bad">flag</span>' if r.get('flag') else '']
        if has_excess:
            row.append(num(r.get('excessPrice'), 2))
        if truth_cols:
            t = r.get('truth') or {}
            row += ['<span class="small">%s</span>' % e(t.get('setup_label', '')), _yes(t.get('coordinated')),
                    _yes(t.get('high_price'))]
        rows.append(row)
    headers = ['Market', 'Days', 'Margin', 'cv', 'Cuts', 'Retaliation', 'p', 'q', 'Flag']
    if has_excess:
        headers.append('Excess')
    if truth_cols:
        headers += ['Hidden set-up', 'Threat', 'High prices']
    key = ('<p class="caption">cv is the coefficient of price variation; cuts counts unprovoked one-day price cuts; '
           'retaliation is how much more often a rival cuts the next day than on an ordinary day.%s</p>' % (
               ' Excess is the excess price index from the demand fit.' if has_excess else ''))
    num_cols = list(range(1, 8)) + ([9] if has_excess else [])
    return _table(headers, rows, num_cols=num_cols, wide=True,
                  label_cols=[len(headers) - 3] if truth_cols else []) + key


def _yes(v):
    if v is None:
        return ''
    return '<span class="pill %s">%s</span>' % ('bad' if v else 'good', 'yes' if v else 'no')


# ------------------------------------------------------------ calibration

def _scatter(markets):
    pts_ = [(r['trueMu'], r['fit']['mu'], r['fit'].get('muSe'), r['market']) for r in markets
            if _ok(r.get('trueMu')) and r['fit'].get('usable') and _ok(r['fit'].get('mu'))]
    if not pts_:
        return ''
    top = max([p[0] for p in pts_] + [p[1] + 1.645 * (p[2] or 0) for p in pts_])
    hi = max(0.1, top * 1.1)
    W, H, m, left = 360, 300, 46, 64

    def X(v):
        return left + v / hi * (W - left - 12)

    def Y(v):
        return H - m - v / hi * (H - m - 12)

    inner = []
    for v in _nice_ticks(0, hi, 5):
        inner.append('<line class="grid" x1="%s" x2="%s" y1="%s" y2="%s"/>' % (_f(X(v)), _f(X(v)), _f(Y(0)), _f(Y(hi))))
        inner.append('<line class="grid" x1="%s" x2="%s" y1="%s" y2="%s"/>' % (_f(X(0)), _f(X(hi)), _f(Y(v)), _f(Y(v))))
        inner.append(_text(X(v), H - m + 16, num(v, 2), anchor='middle'))
        inner.append(_text(left - 6, Y(v) + 4, num(v, 2), anchor='end'))
    inner.append('<line class="diag" x1="%s" y1="%s" x2="%s" y2="%s"/>' % (_f(X(0)), _f(Y(0)), _f(X(hi)), _f(Y(hi))))
    # Markets share only a few true values, so points at the same true mu are spread out a little sideways.
    seen = {}
    for t, f, se, mid in pts_:
        k = seen[t] = seen.get(t, -1) + 1
        dx = ((k % 9) - 4) * 1.6
        x, y = X(t) + dx, Y(f)
        if _ok(se):
            inner.append('<line class="pt-ci" x1="%s" x2="%s" y1="%s" y2="%s"/>' % (
                _f(x), _f(x), _f(Y(max(0, f - 1.645 * se))), _f(Y(f + 1.645 * se))))
        inner.append('<circle class="pt" cx="%s" cy="%s" r="3.6"><title>%s</title></circle>' % (
            _f(x), _f(y), e('Market %s: true %s, fitted %s' % (mid, num(t), num(f)))))
    inner.append(_text(X(hi / 2), H - 8, 'True mu (how loyal shoppers are)', anchor='middle'))
    inner.append(_text(14, Y(hi / 2), 'Fitted mu', anchor='middle', extra='transform="rotate(-90 14 %s)"' % _f(Y(hi / 2))))
    return _svg(W, H, 'Scatter of fitted against true mu for %d markets' % len(pts_), inner)


def _calibration_section(cal, part):
    markets = cal['markets']
    t = cal.get('truth')
    has_truth = any('trueMu' in r for r in markets)
    rows = []
    for r in markets:
        f, b = r['fit'], r['benchmark']
        row = [e(r['market']),
               '%s<br><span class="small muted">SE %s</span>' % (num(f.get('mu')), num(f.get('muSe')))
               if f.get('usable') else '<span class="pill bad">unusable</span>']
        if has_truth:
            row.append(num(r.get('trueMu')))
        row += [num(f.get('r2'), 2), '%s of %s' % (f['days'], f['days'] + f['dropped']),
                money(model.mean(b['competitive'])) if b.get('competitive') else 'n/a',
                money(model.mean(b['monopoly'])) if b.get('monopoly') else 'n/a',
                money(model.mean(f['meanPrice'])), num(b.get('excessPrice'), 2),
                '<span class="small muted">%s</span>' % e(f.get('problem') or f.get('note') or '')]
        rows.append(row)
    headers = ['Market', 'Fitted mu'] + (['True mu'] if has_truth else []) + [
        'R²', 'Days used', 'Fitted competitive price', 'Fitted monopoly price', 'Mean price', 'Excess price', 'Note']
    summary = ''
    if t:
        bits = ['%d of %d fits are usable.' % (cal['usable'], len(markets))]
        if t.get('muMae') is not None:
            bits.append('Fitted mu is off by %s on average (mean error %s).' % (num(t['muMae']), num(t['muBias'])))
        if t.get('competitiveMae') is not None:
            bits.append('The fitted competitive price is off by %s on average.' % money(t['competitiveMae']))
        if t.get('evaluation'):
            bits.append('Ranked by the excess price index, ' + '; '.join(
                '%s has an AUC of %s' % (e(tg['label'].lower()), num(tg['screens'][0]['auc'], 2))
                for tg in t['evaluation']['targets']) + '.')
        summary = '<p>%s</p>' % ' '.join(bits)
    return ''.join([
        '<section id="calibration"><h2>%s</h2>' % e(SECTION_TITLES['calibration']),
        '<p class="lead">With daily sales a regulator can fit the demand model itself: ln(s<sub>i</sub> / '
        's<sub>0</sub>) = a<sub>i</sub> / mu − p<sub>i</sub> / mu, by least squares with one intercept per '
        'seller. The fitted market gives competitive and monopoly prices, and the excess price index says where '
        'observed prices sit between them (0 competitive, 1 monopoly).</p>',
        summary, _scatter(markets),
        '<p class="caption">Each dot is a market; bars are 90% intervals from the delta-method standard error; the '
        'dashed line is a perfect fit.</p>' if has_truth else '',
        _table(headers, rows, num_cols=range(1, 9 if has_truth else 8), wide=True, label_cols=[len(headers) - 1]),
        '</section>',
    ])


# ------------------------------------------------------------ page

def build_report(remedies=None, sweep=None, screen=None, command=''):
    """The whole report as one HTML string. Each argument is a saved JSON result (already loaded) or None."""
    sections, nav = [], []
    if remedies:
        sections.append(_remedies_section(remedies))
        nav.append(('remedies', 'Remedies'))
    if sweep:
        sections.append(_sweep_section(sweep))
        nav.append(('sweep', 'Sweep'))
    if screen:
        res = screen['results']
        sections.append(_screening_section(screen))
        nav.append(('screening', 'Screening'))
        if res.get('calibration'):
            sections.append(_calibration_section(res['calibration'], screen))
            nav.append(('calibration', 'Calibration'))
    made = datetime.datetime.now().strftime('%d %B %Y, %H:%M')
    head = ''.join([
        '<!doctype html>\n<html lang="en-GB">\n<head>\n<meta charset="utf-8">\n',
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n',
        '<title>Quiet cartel: companion report</title>\n<style>%s</style>\n</head>\n<body>\n<div class="wrap">\n' % CSS,
        '<header><h1>Quiet cartel: companion report</h1>',
        '<p class="lead">Can self-learning pricing algorithms learn to keep prices high without being told to, which '
        'remedies stop them, and could a regulator tell from the prices? This report collects results from the '
        'Python companion to the Quiet cartel browser app.</p>',
        '<p class="notice">All markets, sellers and sales here are synthetic, produced by simulated Q-learning '
        'sellers in a textbook logit demand model. The numbers are illustrative only: they are not evidence about '
        'any real business, and nothing here is legal advice.</p>',
        '<nav aria-label="Sections">%s</nav>' % ''.join('<a href="#%s">%s</a>' % (k, e(v)) for k, v in nav),
        '<p class="small muted">Made on %s with <code>%s</code>. The command and settings behind each section are '
        'listed at the end of it.</p></header>\n' % (e(made), e(command or 'python -m quiet_cartel report')),
    ])
    foot = ('<footer>Quiet cartel companion report. Self-contained: no scripts, fonts or links to anything outside '
            'this file.</footer>\n</div>\n</body>\n</html>\n')
    if not sections:
        sections.append('<section><p>No results were given.</p></section>')
    return head + '\n'.join(sections) + foot
