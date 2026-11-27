"""Self-contained HTML reports with inline SVG charts, and the number formats and plain-English summaries the
command line shares with them. Nothing here fetches anything: the pages use system fonts and no links.
"""
import html
import math

from . import model

CLARET, GOLD, CREAM = '#6b1d33', '#e3a33b', '#faf5ea'
INK, INK_SOFT, INK_FAINT, RULE = '#241a1c', '#5c4a4d', '#8a7a72', '#cdb994'
FLAG_COLOURS = {'coupled': '#9b7b5b', 'uncoupled': '#c9a77e', 'ewma': '#26395a', 'model': '#b97812',
                'oracle': '#3d5a3a'}
POLICY_COLOURS = {'none': INK, 'rest': CLARET, 'modify': '#b97812', 'rotate': '#26395a', 'readiness': '#3d5a3a'}
FLAG_SHORT = {'coupled': 'Rolling ratio (coupled)', 'uncoupled': 'Rolling ratio (uncoupled)', 'ewma': 'EWMA ratio',
              'model': 'Risk model (the AI)', 'oracle': 'Perfect knowledge'}
FLAG_PHRASE = {'coupled': 'rolling ratio (coupled)', 'uncoupled': 'rolling ratio (uncoupled)', 'ewma': 'EWMA ratio',
               'model': 'risk model (the AI)', 'oracle': 'perfect-knowledge oracle'}
POLICY_SHORT = {'none': 'Ignore the light', 'rest': 'Rest anyone flagged', 'modify': 'Cut training when flagged',
                'rotate': 'Planned rotation', 'readiness': 'Pick on readiness'}
METRIC_LABELS = {'injuriesTotal': 'Injuries', 'nc': 'Soft-tissue injuries', 'contact': 'Contact injuries',
                 'daysLost': 'Days lost', 'points': 'League points', 'position': 'League position',
                 'finalBestXV': 'First-choice XV in final', 'meanRating': 'Team rating',
                 'rests': 'Matches sat out', 'finalWon': 'Cup final won (share)'}


# ---------- numbers as text ----------
def finite(x):
    """Whether x is a number that is neither NaN nor infinite."""
    return isinstance(x, (int, float)) and math.isfinite(x)


def fmt(x, digits=1):
    """A number with thousands separators; n/a for NaN or None."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 'n/a'
    if isinstance(x, float) and math.isinf(x):
        return 'never' if x > 0 else '-inf'
    return f'{x:,.{digits}f}'


def signed(x, digits=1):
    """A number with its sign (+1.2, -0.4, 0.0)."""
    if not finite(x):
        return fmt(x, digits)
    if round(x, digits) == 0:
        return f'{0:.{digits}f}'
    return f'{x:+,.{digits}f}'


def pct(x, digits=0):
    """A share as a percentage."""
    return fmt(x if not finite(x) else 100 * x, digits) + ('%' if finite(x) else '')


def interval(lo, hi, digits=1):
    """A 95% interval as text."""
    return f'{signed(lo, digits)} to {signed(hi, digits)}'


def ordinal(n):
    """1st, 2nd, 3rd, 4th, ... 11th, 12th, 13th, ..."""
    suffix = 'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f'{n}{suffix}'


def plural(n, word, words=None):
    """'1 injury', '3 injuries'."""
    return f"{fmt(n, 0)} {word if n == 1 else (words or word + 's')}"


# ---------- settings ----------
def describe_settings(S):
    """The settings that shape a simulation, as (name, value, meaning) rows."""
    return [
        ('policy', S['policy'], model.POLICY_LABELS[S['policy']]),
        ('flag', S['flag'], model.FLAG_LABELS[S['flag']]),
        ('threshold', fmt(S['threshold'], 2), 'ratio flags fire at this workload ratio'),
        ('budget', f"{fmt(S['budget'], 0)}%", 'model and oracle flags fire on the riskiest share of player-weeks'),
        ('preseason', S['preseason'], 'how pre-season training builds up'),
        ('intensity', fmt(S['intensity'], 2), 'multiplies the effort of every training session'),
        ('gradedReturn', 'on' if S['gradedReturn'] else 'off', 'ten days of modified training after an injury'),
        ('spike', fmt(S['spike'], 2), 'truth: how strongly a load spike raises soft-tissue risk'),
        ('contactScale', fmt(S['contactScale'], 2), 'truth: multiplies the contact injury rate'),
        ('squadSeed', str(S['squadSeed']), 'which invented squad'),
        ('historySeasons', str(S['historySeasons']), 'past seasons the risk model learns from'),
    ]


def settings_line(S):
    """The settings in one line of text."""
    return (f"policy {S['policy']}, flag {S['flag']}, threshold {fmt(S['threshold'], 2)}, "
            f"budget {fmt(S['budget'], 0)}%, {S['preseason']} pre-season, intensity {fmt(S['intensity'], 2)}, "
            f"graded return {'on' if S['gradedReturn'] else 'off'}, spike {fmt(S['spike'], 2)}, "
            f"contact scale {fmt(S['contactScale'], 2)}, squad seed {S['squadSeed']}, "
            f"{plural(S['historySeasons'], 'history season')}")


# ---------- plain-English summaries ----------
def flags_summary(ev, S):
    """What the scorecard of warning lights says, in a few sentences."""
    by = {f['id']: f for f in ev['flags']}
    real = sorted((f for f in ev['flags'] if f['id'] != 'oracle'), key=lambda f: -f['auc'])
    best, chosen = real[0], by[S['flag']]
    per100 = 100 * chosen['atRule']['precision']
    return (f"Across {fmt(ev['rows'], 0)} player-weeks, {pct(ev['baseRate'], 1)} ended in a soft-tissue injury "
            f"within seven days. The best real light, the {FLAG_PHRASE[best['id']]}, scores {fmt(best['auc'], 2)} "
            f"(0.5 is a coin toss, 1 is perfect); perfect knowledge of the hidden truth reaches "
            f"{fmt(by['oracle']['auc'], 2)}. At its rule, the {FLAG_PHRASE[S['flag']]} flags "
            f"{pct(chosen['atRule']['share'], 1)} of player-weeks and catches {pct(chosen['atRule']['recall'])} of "
            f"those injuries, but only {fmt(per100, 1)} of every 100 flags are followed by one. A single season can "
            f"score it anywhere from {fmt(chosen['seasonAuc']['lo'], 2)} to {fmt(chosen['seasonAuc']['hi'], 2)} on "
            f"luck alone, and {pct(ev['contactShare'])} of injuries come from contact, which no load figure "
            f"foresees.")


def compare_summary(cp):
    """What playing every policy on the same luck shows, in a few sentences."""
    ref = cp['reference']
    parts = []
    for row in cp['table']:
        if row['policy'] == ref:
            continue
        m = row['metrics']
        parts.append(f"{POLICY_SHORT[row['policy']].lower()} changed injuries by {signed(m['injuriesTotal']['diff'])} "
                     f"({interval(m['injuriesTotal']['lo'], m['injuriesTotal']['hi'])}), days lost by "
                     f"{signed(m['daysLost']['diff'], 0)} and league points by {signed(m['points']['diff'])}")
    fewest = min(cp['table'], key=lambda r: r['metrics']['daysLost']['mean'])
    most = max(cp['table'], key=lambda r: r['metrics']['points']['mean'])
    return (f"Over {plural(len(cp['seeds']), 'season')} with the same luck, against picking the best and ignoring the "
            f"light: " + '; '.join(parts) + f". {POLICY_SHORT[fewest['policy']]} lost the fewest days and "
            f"{POLICY_SHORT[most['policy']].lower()} won the most points.")


def pilot_summary(ps):
    """What a one-season pilot can and cannot tell, in a few sentences."""
    needed = 'more seasons than any club has' if not finite(ps['seasonsNeeded']) else fmt(ps['seasonsNeeded'], 0)
    text = (f"With the luck held fixed, {POLICY_SHORT[ps['policy']].lower()} changes injuries by "
            f"{signed(ps['trueEffect'])} a season ({signed(ps['trueNC'])} soft-tissue). But one season of injuries "
            f"varies by about {fmt(ps['seasonSd'])} either way, so a before-and-after pilot swings by "
            f"{fmt(ps['measuredSd'])}: it shows fewer injuries {pct(ps['looksBetter'])} of the time and more "
            f"{pct(ps['looksWorse'])} of the time. Detecting the true effect four times in five needs {needed} "
            f"seasons in each arm. League points change by {signed(ps['pointsEffect'])} a season.")
    if finite(ps['quietShare']):
        per = ps['actionsPerInjuryPrevented']
        text += (f" {pct(ps['quietShare'])} of acted-on flags are followed by a quiet fortnight, which looks like "
                 f"success to a coach; in truth it took about {fmt(per, 0) if finite(per) else 'an endless number of'}"
                 f" acted-on flags to prevent one injury.")
    return text


# ---------- SVG ----------
def esc(text):
    """Text made safe for HTML and SVG."""
    return html.escape(str(text), quote=True)


def _n(v):
    """A coordinate with at most two decimals."""
    return f'{v:.2f}'.rstrip('0').rstrip('.')


def svg_plot(label, x, y, series, refs=(), width=400, height=280):
    """A chart as inline SVG.

    x and y are axes: {'min', 'max', 'ticks', 'label', 'format'} (format turns a tick into text). series is a
    list of {'kind': 'line' | 'points' | 'bars', 'data', 'colour', ...}: lines take [x, y] points and
    optional 'width' and 'dash'; points take [x, y] or [x, y, colour] and optional 'r' and 'opacity'; bars
    take [x, height] with a 'barWidth' in x units. refs are reference lines {'axis', 'value', 'colour',
    'label', 'dash', 'anchor', 'row'}. Values outside the axes are clipped to them; NaN values are left out.
    """
    ml, mr, mt, mb = 58, 20, 14, 46
    pw, ph = width - ml - mr, height - mt - mb

    def sx(v):
        return ml + (min(max(v, x['min']), x['max']) - x['min']) / (x['max'] - x['min']) * pw

    def sy(v):
        return mt + ph - (min(max(v, y['min']), y['max']) - y['min']) / (y['max'] - y['min']) * ph

    xf, yf = x.get('format', lambda v: fmt(v, 0)), y.get('format', lambda v: fmt(v, 0))
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(label)}">',
           f'<title>{esc(label)}</title>']
    for t in y['ticks']:
        out.append(f'<line x1="{ml}" x2="{ml + pw}" y1="{_n(sy(t))}" y2="{_n(sy(t))}" stroke="{RULE}" '
                   'stroke-width="0.8"/>')
        out.append(f'<text x="{ml - 6}" y="{_n(sy(t) + 4)}" text-anchor="end">{esc(yf(t))}</text>')
    for t in x['ticks']:
        out.append(f'<line x1="{_n(sx(t))}" x2="{_n(sx(t))}" y1="{mt + ph}" y2="{mt + ph + 4}" stroke="{INK}"/>')
        out.append(f'<text x="{_n(sx(t))}" y="{mt + ph + 17}" text-anchor="middle">{esc(xf(t))}</text>')
    out.append(f'<line x1="{ml}" x2="{ml + pw}" y1="{mt + ph}" y2="{mt + ph}" stroke="{INK}"/>')
    out.append(f'<line x1="{ml}" x2="{ml}" y1="{mt}" y2="{mt + ph}" stroke="{INK}"/>')
    if x.get('label'):
        out.append(f'<text x="{ml + pw / 2}" y="{height - 6}" text-anchor="middle" class="axis">'
                   f'{esc(x["label"])}</text>')
    if y.get('label'):
        out.append(f'<text transform="translate(12 {mt + ph / 2}) rotate(-90)" text-anchor="middle" '
                   f'class="axis">{esc(y["label"])}</text>')
    for s in series:
        colour = s.get('colour', CLARET)
        if s['kind'] == 'bars':
            half = s.get('barWidth', 0.8) / 2
            for bx, bh in s['data']:
                top, base = sy(bh), sy(max(y['min'], 0))
                out.append(f'<rect x="{_n(sx(bx - half))}" y="{_n(top)}" width="{_n(sx(bx + half) - sx(bx - half))}"'
                           f' height="{_n(base - top)}" fill="{colour}"/>')
        elif s['kind'] == 'line':
            pts = ' '.join(f'{_n(sx(px))},{_n(sy(py))}' for px, py in s['data'] if finite(px) and finite(py))
            dash = f' stroke-dasharray="{s["dash"]}"' if s.get('dash') else ''
            out.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="{s.get("width", 2)}" '
                       f'stroke-linejoin="round"{dash}/>')
        else:
            r, opacity = s.get('r', 3.5), s.get('opacity', 1)
            stroke = f' stroke="{s["stroke"]}" stroke-width="1.5"' if s.get('stroke') else ''
            for p in s['data']:
                if finite(p[0]) and finite(p[1]):
                    out.append(f'<circle cx="{_n(sx(p[0]))}" cy="{_n(sy(p[1]))}" r="{r}" '
                               f'fill="{p[2] if len(p) > 2 else colour}" fill-opacity="{opacity}"{stroke}/>')
    for ref in refs:
        colour, dash = ref.get('colour', CLARET), ref.get('dash', '5 4')
        if ref['axis'] == 'x':
            px = _n(sx(ref['value']))
            out.append(f'<line x1="{px}" x2="{px}" y1="{mt}" y2="{mt + ph}" stroke="{colour}" stroke-width="2" '
                       f'stroke-dasharray="{dash}"/>')
            if ref.get('label'):
                anchor = ref.get('anchor') or ('end' if sx(ref['value']) > ml + pw * 0.6 else 'start')
                shift = -5 if anchor == 'end' else 5
                out.append(f'<text x="{_n(sx(ref["value"]) + shift)}" y="{mt + 12 + 14 * ref.get("row", 0)}" '
                           f'text-anchor="{anchor}" fill="{colour}" class="ref">{esc(ref["label"])}</text>')
        else:
            py = _n(sy(ref['value']))
            out.append(f'<line x1="{ml}" x2="{ml + pw}" y1="{py}" y2="{py}" stroke="{colour}" stroke-width="2" '
                       f'stroke-dasharray="{dash}"/>')
            if ref.get('label'):
                start = ref.get('anchor') == 'start'
                out.append(f'<text x="{ml + 4 if start else ml + pw - 4}" y="{_n(sy(ref["value"]) - 5)}" '
                           f'text-anchor="{"start" if start else "end"}" fill="{colour}" class="ref">'
                           f'{esc(ref["label"])}</text>')
    out.append('</svg>')
    return '\n'.join(out)


def nice_ticks(lo, hi, count=5):
    """About count round tick values covering lo to hi, and the axis range they span."""
    if not hi > lo:
        hi = lo + 1
    raw = (hi - lo) / count
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
    start, end = math.floor(lo / step) * step, math.ceil(hi / step) * step
    ticks = [start + k * step for k in range(int(round((end - start) / step)) + 1)]
    return ticks, start, end


# ---------- HTML ----------
STYLE = f"""
:root {{ --claret: {CLARET}; --gold: {GOLD}; --cream: {CREAM}; --ink: {INK}; --soft: {INK_SOFT};
  --rule: {RULE}; --card: #fffdf7; --head: #f3e9d3; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--cream); color: var(--ink);
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }}
header {{ background: var(--claret); color: var(--cream); padding: 26px 16px 20px;
  border-bottom: 4px solid var(--gold); }}
header .inner, main {{ max-width: 880px; margin: 0 auto; }}
main {{ padding: 4px 16px 40px; }}
.kicker {{ margin: 0 0 4px; color: var(--gold); font-size: 12px; font-weight: 700; letter-spacing: .14em;
  text-transform: uppercase; }}
h1 {{ margin: 0 0 6px; font-size: clamp(26px, 6vw, 38px); line-height: 1.1; }}
header p {{ margin: 0; max-width: 60ch; }}
h2 {{ margin: 34px 0 10px; padding-bottom: 4px; color: var(--claret); font-size: 22px;
  border-bottom: 2px solid var(--gold); }}
h3 {{ margin: 0 0 6px; font-size: 16px; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 170px), 1fr)); gap: 10px;
  margin: 18px 0 6px; }}
.tile {{ background: var(--card); border: 1px solid var(--rule); border-top: 4px solid var(--claret);
  padding: 10px 12px; }}
.tile b {{ display: block; color: var(--claret); font-size: 26px; line-height: 1.2; }}
.tile span {{ color: var(--soft); font-size: 13px; }}
.note {{ margin: 12px 0; padding: 10px 14px; background: var(--card); border-left: 4px solid var(--gold); }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr)); gap: 14px; }}
figure {{ margin: 0; padding: 12px; background: var(--card); border: 1px solid var(--rule); }}
figcaption {{ color: var(--soft); font-size: 14px; }}
svg.chart {{ display: block; width: 100%; max-width: 460px; height: auto; margin: 6px auto 0; font-size: 13px;
  fill: var(--ink); }}
svg.chart .axis {{ fill: var(--soft); }}
svg.chart .ref {{ font-weight: 700; stroke: #fffdf7; stroke-width: 3px; paint-order: stroke; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 8px 0 0; padding: 0; list-style: none;
  font-size: 13px; }}
.legend i {{ display: inline-block; width: 12px; height: 12px; margin-right: 5px; vertical-align: -1px;
  border-radius: 2px; }}
.table-wrap {{ overflow-x: auto; margin: 10px 0; border: 1px solid var(--rule); }}
table {{ width: 100%; border-collapse: collapse; background: var(--card); font-size: 14px; }}
th, td {{ padding: 6px 9px; border-bottom: 1px solid var(--rule); text-align: left; white-space: nowrap; }}
th {{ background: var(--head); }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
tr.us td {{ background: #f7ead0; font-weight: 700; }}
.warn {{ padding: 8px 12px; background: #f4dca8; border-left: 4px solid var(--claret); }}
footer {{ max-width: 880px; margin: 0 auto; padding: 0 16px 30px; color: var(--soft); font-size: 13px; }}
"""


def tiles(items):
    """A row of headline figures: (value, caption) pairs."""
    return '<div class="tiles">' + ''.join(f'<div class="tile"><b>{esc(v)}</b><span>{esc(c)}</span></div>'
                                           for v, c in items) + '</div>'


def legend(items):
    """A legend under a chart: (label, colour) pairs."""
    return '<ul class="legend">' + ''.join(f'<li><i style="background:{c}"></i>{esc(t)}</li>'
                                           for t, c in items) + '</ul>'


def figure(title, caption, svg, legend_items=None):
    """A chart with its heading, caption and legend."""
    return (f'<figure><h3>{esc(title)}</h3><figcaption>{esc(caption)}</figcaption>{svg}'
            f'{legend(legend_items) if legend_items else ""}</figure>')


def table(headers, rows, numeric=None, highlight=None):
    """An HTML table; numeric holds the indices of right-aligned columns (default all but the first) and
    highlight the indices of rows to pick out."""
    numeric = set(range(1, len(headers))) if numeric is None else set(numeric)
    highlight = set(highlight or ())

    def cell(tag, i, v):
        return f'<{tag}{" class=num" if i in numeric else ""}>{esc(v)}</{tag}>'

    head = ''.join(cell('th', i, h) for i, h in enumerate(headers))
    body = ''.join(f'<tr{" class=us" if k in highlight else ""}>' + ''.join(cell('td', i, v) for i, v in enumerate(r))
                   + '</tr>' for k, r in enumerate(rows))
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def page(title, kicker, intro, body, footer):
    """A whole self-contained HTML page."""
    return ('<!doctype html>\n<html lang="en-GB">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>{esc(title)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n'
            f'<header><div class="inner"><p class="kicker">{esc(kicker)}</p><h1>{esc(title)}</h1>'
            f'<p>{esc(intro)}</p></div></header>\n<main>\n{body}\n</main>\n<footer>{esc(footer)}</footer>\n'
            '</body>\n</html>\n')


def settings_table(S, extra=()):
    """The settings used, as an HTML table; extra adds (name, value, meaning) rows."""
    rows = [[n, v, m] for n, v, m in describe_settings(S)] + [list(r) for r in extra]
    return table(['Setting', 'Value', 'Meaning'], rows, numeric=())


# ---------- the analysis report ----------
def _roc_chart(ev, S):
    shown = [f for f in ev['flags'] if f['id'] != 'uncoupled']
    series = [{'kind': 'line', 'data': [[0, 0], [1, 1]], 'colour': INK_FAINT, 'width': 1.5, 'dash': '4 4'}]
    for f in shown:
        series.append({'kind': 'line', 'data': f['roc'], 'colour': FLAG_COLOURS[f['id']],
                       'width': 3.5 if f['id'] == S['flag'] else 2.2, 'dash': '7 4' if f['id'] == 'oracle' else None})
    axis = {'min': 0, 'max': 1, 'ticks': [0, 0.25, 0.5, 0.75, 1], 'format': lambda v: pct(v)}
    svg = svg_plot('ROC curves for each warning light', dict(axis, label='Fit players flagged'),
                   dict(axis, label='Injuries caught'), series)
    names = [(FLAG_SHORT[f['id']].replace(' (coupled)', ' (either version)') + f" {fmt(f['auc'], 2)}",
              FLAG_COLOURS[f['id']]) for f in shown]
    return figure('Hits against false alarms', 'Each curve traces every possible flag level: up means more '
                  'soft-tissue injuries caught, right means more fit players flagged. The diagonal is guessing.',
                  svg, names)


def _strip_chart(ev):
    ids = ['coupled', 'ewma', 'model', 'oracle']
    names = ['Rolling', 'EWMA', 'AI', 'Perfect']
    pts = [[k + 0.5 + ((j * 37) % 23 - 11) / 40, o[f], FLAG_COLOURS[f]]
           for k, f in enumerate(ids) for j, o in enumerate(ev['perSeason'])]
    svg = svg_plot('Single-season AUC for each light',
                   {'min': 0, 'max': len(ids), 'ticks': [k + 0.5 for k in range(len(ids))],
                    'format': lambda v: names[int(v)]},
                   {'min': 0.3, 'max': 1, 'ticks': [0.3, 0.5, 0.7, 0.9], 'label': 'Score for one season',
                    'format': lambda v: fmt(v, 1)},
                   [{'kind': 'points', 'data': pts, 'r': 4, 'opacity': 0.75}],
                   refs=[{'axis': 'y', 'value': 0.5, 'colour': CLARET, 'label': 'Coin toss'}])
    return figure('One season at a time', f"Each dot is one season's score for that light, over "
                  f"{plural(len(ev['perSeason']), 'season')}. A club judging its light on one season gets one dot.",
                  svg)


def _pilot_histogram(ps):
    counts = {}
    for v in ps['measured']:
        counts[v] = counts.get(v, 0) + 1
    lo = min(min(counts), math.floor(ps['trueEffect'])) - 1
    hi = max(max(counts), math.ceil(ps['trueEffect'])) + 1
    xt, x0, x1 = nice_ticks(lo, hi, 6)
    yt, _, y1 = nice_ticks(0, max(counts.values()), 4)
    svg = svg_plot('Histogram of what one pilot season reports',
                   {'min': x0, 'max': x1, 'ticks': xt, 'label': 'Change in injuries against the season before',
                    'format': lambda v: signed(v, 0)},
                   {'min': 0, 'max': y1, 'ticks': yt, 'label': 'Pilots'},
                   [{'kind': 'bars', 'data': sorted(counts.items()), 'colour': '#a5566a', 'barWidth': 0.8}],
                   refs=[{'axis': 'x', 'value': 0, 'colour': INK_FAINT, 'label': 'No change',
                          'anchor': 'start' if ps['trueEffect'] < 0 else 'end'},
                         {'axis': 'x', 'value': ps['trueEffect'], 'colour': '#b97812',
                          'label': f"True effect {signed(ps['trueEffect'])}", 'row': 1,
                          'anchor': 'end' if ps['trueEffect'] < 0 else 'start'}])
    return figure('What one pilot season reports', f"Each bar counts pilots (of {ps['pairs']}) that reported that "
                  'change against the season before. The true effect is the same in every one.', svg)


def _power_chart(ps):
    needed = ps['seasonsNeeded']
    refs = [{'axis': 'y', 'value': 0.8, 'colour': CLARET, 'label': 'Four times in five', 'anchor': 'start'}]
    if finite(needed) and needed <= 100:
        refs.append({'axis': 'x', 'value': needed, 'colour': '#b97812', 'label': f'{fmt(needed, 0)} seasons',
                     'row': 1})
    svg = svg_plot('Power against seasons in each arm', {'min': 0, 'max': 100, 'ticks': [0, 20, 40, 60, 80, 100],
                                                         'label': 'Seasons in each arm'},
                   {'min': 0, 'max': 1, 'ticks': [0, 0.25, 0.5, 0.75, 1], 'label': 'Chance of detecting it',
                    'format': lambda v: pct(v)},
                   [{'kind': 'line', 'data': [[p['seasons'], p['power']] for p in ps['power']], 'colour': '#26395a',
                     'width': 3}], refs=refs)
    return figure('How many seasons to know?', 'The chance that a fair comparison of this many seasons with the '
                  'light and without it detects the true effect (two-sided, 5% level).', svg)


def _policy_scatter(cp):
    pts, means = [], []
    for row in cp['table']:
        pol = row['policy']
        pts += [[r['daysLost'], r['points'], POLICY_COLOURS[pol]] for r in cp['runs'][pol]]
        means.append([row['metrics']['daysLost']['mean'], row['metrics']['points']['mean'], POLICY_COLOURS[pol]])
    xt, x0, x1 = nice_ticks(min(p[0] for p in pts), max(p[0] for p in pts), 5)
    yt, y0, y1 = nice_ticks(min(p[1] for p in pts), max(p[1] for p in pts), 5)
    svg = svg_plot('Days lost against league points for each policy',
                   {'min': x0, 'max': x1, 'ticks': xt, 'label': 'Days lost to injury in the season'},
                   {'min': y0, 'max': y1, 'ticks': yt, 'label': 'League points'},
                   [{'kind': 'points', 'data': pts, 'r': 3, 'opacity': 0.3},
                    {'kind': 'points', 'data': means, 'r': 7, 'stroke': CREAM}])
    return figure('Fewer days lost, more points?', 'Small dots are single seasons; large dots are each policy\'s '
                  'average. Up and to the left is better.', svg,
                  [(POLICY_SHORT[r['policy']], POLICY_COLOURS[r['policy']]) for r in cp['table']])


def flags_table(ev, S):
    """The warning-light scorecard as table rows (shared by the text and HTML reports)."""
    rows = []
    for f in ev['flags']:
        rows.append([FLAG_SHORT[f['id']], fmt(f['auc'], 3),
                     f"{fmt(f['seasonAuc']['lo'], 2)} to {fmt(f['seasonAuc']['hi'], 2)}",
                     pct(f['atRule']['share'], 1),
                     fmt(100 * f['atRule']['precision'], 1) if f['atRule']['flagged'] else 'n/a',
                     pct(f['atRule']['recall']), pct(f['atBudget']['recall'])])
    headers = ['Light', 'AUC', 'One season', 'Flagged', 'Hits per 100 flags', 'Caught',
               f"Caught at {fmt(S['budget'], 0)}%"]
    return headers, rows


def analysis_report(S, ev, cp, ps):
    """The whole report: warning lights, the pilot and the policies, with charts and the settings used."""
    by = {f['id']: f for f in ev['flags']}
    real = sorted((f for f in ev['flags'] if f['id'] != 'oracle'), key=lambda f: -f['auc'])
    needed = ps['seasonsNeeded']
    body = [tiles([
        (fmt(real[0]['auc'], 2), f"the best real light, the {FLAG_PHRASE[real[0]['id']]}; 0.5 is a coin toss"),
        (fmt(by['oracle']['auc'], 2), 'the ceiling: perfect knowledge of the hidden truth, not of the luck'),
        (signed(ps['trueEffect']), f"injuries a season from {POLICY_SHORT[ps['policy']].lower()}, same luck"),
        (fmt(needed, 0) if finite(needed) else 'never', 'seasons in each arm to detect that four times in five'),
    ])]
    headers, rows = flags_table(ev, S)
    body.append('<h2>How good is each warning light?</h2>')
    body.append(f'<p class="note">{esc(flags_summary(ev, S))}</p>')
    body.append(f'<div class="grid">{_roc_chart(ev, S)}{_strip_chart(ev)}</div>')
    body.append(table(headers, rows, highlight=[k for k, f in enumerate(ev['flags']) if f['id'] == S['flag']]))
    body.append(f"<p>Scored on {plural(len(ev['seeds']), 'silent season')} (seeds {ev['seeds'][0]} to "
                f"{ev['seeds'][-1]}) in which nobody acts on any flag. Ratio lights fire at "
                f"{fmt(S['threshold'], 2)}; the model and the oracle flag the riskiest {fmt(S['budget'], 0)}% on past "
                f"seasons. The risk model learned from {fmt(ev['historyRows'], 0)} player-weeks with "
                f"{plural(ev['historyInjuries'], 'soft-tissue injury', 'soft-tissue injuries')}.</p>")
    body.append('<h2>Could a one-season pilot tell?</h2>')
    body.append(f'<p class="note">{esc(pilot_summary(ps))}</p>')
    body.append(f'<div class="grid">{_pilot_histogram(ps)}{_power_chart(ps)}</div>')
    body.append(table(['Measure', 'A season'], [
        ['Injuries in a normal season', fmt(ps['baseMean'])],
        ['True effect on injuries (95% interval)', f"{signed(ps['trueEffect'])} ({interval(*ps['trueEffectCI'])})"],
        ['True effect on days lost', signed(ps['trueDays'], 0)],
        ['What a pilot reports: mean and spread', f"{signed(ps['measuredMean'])}, sd {fmt(ps['measuredSd'])}"],
        ['League points (95% interval)', f"{signed(ps['pointsEffect'])} ({interval(*ps['pointsCI'])})"],
        ['Matches sat out', fmt(ps['matchesMissed'])],
    ]))
    body.append('<h2>Five ways to manage the squad</h2>')
    body.append(f'<p class="note">{esc(compare_summary(cp))}</p>')
    body.append(_policy_scatter(cp))
    ref = cp['reference']
    rows = []
    for row in cp['table']:
        m = row['metrics']
        rows.append([POLICY_SHORT[row['policy']], fmt(m['injuriesTotal']['mean']), fmt(m['daysLost']['mean'], 0),
                     fmt(m['points']['mean']), fmt(m['position']['mean']), fmt(m['rests']['mean'])] +
                    (['reference'] * 3 if row['policy'] == ref else
                     [f"{signed(m[k]['diff'], d)} ({interval(m[k]['lo'], m[k]['hi'], d)})"
                      for k, d in (('injuriesTotal', 1), ('daysLost', 0), ('points', 1))]))
    body.append(table(['Policy', 'Injuries', 'Days lost', 'Points', 'Position', 'Sat out', 'Injuries vs ignore',
                       'Days lost vs ignore', 'Points vs ignore'], rows))
    body.append(f"<p>Every policy plays the same {plural(len(cp['seeds']), 'season')} (seeds {cp['seeds'][0]} to "
                f"{cp['seeds'][-1]}) with the same luck; intervals are 95% bootstrap intervals of the paired "
                'differences.</p>')
    body.append('<h2>Settings used</h2>')
    body.append(settings_table(S, [('flag seasons', f"{len(ev['seeds'])}", 'silent seasons scoring the lights'),
                                   ('policy seasons', f"{len(cp['seeds'])}", 'seasons each policy plays'),
                                   ('pilot pairs', f"{ps['pairs']}", 'pairs of seasons in the pilot study')]))
    return page('Does the warning light help?', 'Load bearing report',
                'An invented rugby club, a workload warning light, and whether a club could ever prove it works.',
                '\n'.join(body), f'Made with python -m loadbearing report, model version {model.VERSION}. '
                'Every number comes from the simulation; nothing here describes a real club.')


# ---------- the logbook report ----------
def _weekly_series(book, an):
    """Mean load per player each week, [soft-tissue, contact] injuries each week, and the squad's daily median
    EWMA ratio, median rolling ratio and 90th-percentile EWMA ratio on each weekly scoring day (day 28, 35 ...),
    as [week, value] points."""
    weeks = math.ceil(book['span'] / 7)
    load = [0.0] * weeks
    for L in book['loads']:
        for t, v in enumerate(L):
            load[t // 7] += v
    players = max(1, len(book['loads']))
    injuries = [[0, 0] for _ in range(weeks)]
    for x in book['injuries']:
        injuries[x['day'] // 7][0 if x['type'] == 'non-contact' else 1] += 1
    ratios = {'ewma': [], 'coupled': [], 'top': []}
    for t in range(28, book['span'], 7):
        ew = sorted(se['ewma'][t] for se in an['series'] if finite(se['ewma'][t]))
        rolling = sorted(se['coupled'][t] for se in an['series'] if finite(se['coupled'][t]))
        if ew and rolling:
            ratios['ewma'].append([t / 7, model.quantile(ew, 0.5)])
            ratios['coupled'].append([t / 7, model.quantile(rolling, 0.5)])
            ratios['top'].append([t / 7, model.quantile(ew, 0.9)])
    return [v / players for v in load], injuries, ratios


def _logbook_charts(book, an):
    load, injuries, ratios = _weekly_series(book, an)
    weeks = len(load)
    week_axis = {'min': 0, 'max': weeks, 'ticks': list(range(0, weeks + 1, 5 if weeks > 20 else 2)),
                 'label': 'Week of the logbook'}
    lt, _, l1 = nice_ticks(0, max(load + [1]), 4)
    load_svg = svg_plot('Average weekly load per player', week_axis,
                        {'min': 0, 'max': l1, 'ticks': lt, 'label': 'Load (minutes x rpe)'},
                        [{'kind': 'bars', 'data': [[k + 0.5, v] for k, v in enumerate(load)], 'colour': '#a5566a',
                          'barWidth': 0.8}])
    top = max([v for _, v in ratios['top']] + [an['threshold'] + 0.1])
    rt, _, r1 = nice_ticks(0, top, 4)
    ratio_svg = svg_plot('Squad workload ratios through the season', week_axis,
                         {'min': 0, 'max': r1, 'ticks': rt, 'label': 'Workload ratio', 'format': lambda v: fmt(v, 1)},
                         [{'kind': 'line', 'data': ratios['top'], 'colour': '#b97812', 'width': 1.5, 'dash': '4 3'},
                          {'kind': 'line', 'data': ratios['coupled'], 'colour': FLAG_COLOURS['coupled'], 'width': 2},
                          {'kind': 'line', 'data': ratios['ewma'], 'colour': FLAG_COLOURS['ewma'], 'width': 2.5}],
                         refs=[{'axis': 'y', 'value': an['threshold'], 'colour': CLARET,
                                'label': f"Flag at {fmt(an['threshold'], 2)}"}])
    most = max([a + b for a, b in injuries] + [1])
    it, _, i1 = nice_ticks(0, most, min(4, most))
    injury_svg = svg_plot('Injuries each week', week_axis,
                          {'min': 0, 'max': i1, 'ticks': it, 'label': 'Injuries in the week'},
                          [{'kind': 'bars', 'data': [[k + 0.5, a + b] for k, (a, b) in enumerate(injuries)],
                            'colour': INK_FAINT, 'barWidth': 0.7},
                           {'kind': 'bars', 'data': [[k + 0.5, a] for k, (a, _) in enumerate(injuries)],
                            'colour': '#b97812', 'barWidth': 0.7}])
    return ('<div class="grid">' +
            figure('How hard the squad worked', 'Average load per player each week.', load_svg) +
            figure('Workload ratios', 'The squad\'s median ratios on each weekly scoring day, and the EWMA ratio '
                   'that only the top tenth of the squad reached.', ratio_svg,
                   [('Median EWMA ratio', FLAG_COLOURS['ewma']), ('Median rolling ratio', FLAG_COLOURS['coupled']),
                    ('Top tenth, EWMA', '#b97812')]) +
            figure('Injuries', 'Injuries logged each week.', injury_svg,
                   [('Soft-tissue', '#b97812'), ('Contact', INK_FAINT)]) + '</div>')


def logbook_report(name, book, an):
    """A report on a club's own logbook: the squad's load, the scorecard and this week's highest ratios."""
    ew = next(r for r in an['results'] if r['id'] == 'ewma')
    tested = 'p' in ew
    if tested:
        verdict = (f"The EWMA ratio scored {fmt(ew['auc'], 2)} on these injuries"
                   + (', better than chance would explain.' if ew['p'] < 0.05
                      else ', which chance alone could produce.')
                   + f" In {fmt(an['permutations'], 0)} reshuffles that slide each player's injuries round the season, "
                   f"{pct(ew['p'], 1)} scored at least as well. {plural(an['positives'], 'injured week')} is a small "
                   'sample, so treat any single season with care.')
    else:
        verdict = 'Fewer than three injured weeks: too few to test the ratios, though the ratios below still work.'
    body = [tiles([
        (fmt(len(book['names']), 0), f"players, {fmt(book['sessions'], 0)} sessions"),
        (fmt(book['span'] / 7, 0), f"weeks, {model.format_day(book['start'])} to "
                                    f"{model.format_day(book['start'] + book['span'] - 1)}"),
        (fmt(an['meanWeekly'], 0), 'average weekly load per player (minutes x rpe)'),
        (fmt(an['counted'], 0), f"injuries counted ({'all' if an['only'] == 'all' else 'soft-tissue only'}, "
                                f"of {fmt(an['injuries'], 0)} recorded)"),
    ])]
    if book['warnings']:
        body.append(''.join(f'<p class="warn">{esc(w)}</p>' for w in book['warnings']))
    body.append(f'<p class="note">{esc(verdict)}</p>')
    body.append('<h2>The squad\'s season</h2>')
    body.append(_logbook_charts(book, an))
    body.append('<h2>Did the ratios see it coming?</h2>')
    body.append(table(['Ratio', 'AUC', 'Chance by luck', f"Flagged at {fmt(an['threshold'], 2)}", 'Hits per 100 flags',
                       'Injuries caught'], scorecard_rows(an)))
    body.append(f"<p>{fmt(an['rows'], 0)} player-weeks scored, one every seven days from day 28, leaving out a "
                'fortnight after each injury.</p>')
    body.append('<h2>This week\'s list</h2>')
    headers, rows = latest_rows(an)
    body.append(table(headers, rows, highlight=[k for k, r in enumerate(an['latest'][:len(rows)]) if r['flagged']]))
    return page('The logbook', 'Load bearing logbook report', f'Workload ratios and injuries in {name}.',
                '\n'.join(body), 'Made with python -m loadbearing logbook. Ratios use minutes times rpe as the load.')


def scorecard_rows(an):
    """The logbook scorecard as table rows (shared by the text and HTML reports)."""
    rows = []
    for r in an['results']:
        rows.append([FLAG_SHORT[r['id']], fmt(r['auc'], 3), pct(r['p'], 1) if 'p' in r else 'n/a',
                     pct(r['atRule']['share'], 1),
                     fmt(100 * r['atRule']['precision'], 1) if r['atRule']['flagged'] else 'n/a',
                     pct(r['atRule']['recall']) if an['positives'] else 'n/a'])
    return rows


def latest_rows(an, count=12):
    """The highest EWMA ratios on the logbook's last day, as table headers and rows."""
    rows = [[r['name'], fmt(r['ewma'], 2), fmt(r['coupled'], 2), fmt(r['acute'], 0), fmt(r['monotony'], 2),
             fmt(r['strain'], 0), 'flagged' if r['flagged'] else ''] for r in an['latest'][:count]]
    return ['Player', 'EWMA ratio', 'Rolling ratio', 'Last 7 days', 'Monotony', 'Strain', 'Flag'], rows
