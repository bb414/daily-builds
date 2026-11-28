"""HTML reports: one student's plan and progress, and a study group's sessions.

Both are single self-contained pages (no fonts, scripts or images to fetch)
that print cleanly, styled like the app: highlighter colours on a printed
planner sheet.
"""

import html

from . import model as m

HL = ['#ffe74a', '#ff86bd', '#82e297', '#72d0f3', '#ffad55', '#bba2ff']
VERDICT_COLOUR = {'ok': '#1b7f45', 'tight': '#b35f00', 'behind': '#c92b70', 'short': '#d2352b', 'sat': '#555a73', 'today': '#1d2141'}

CSS = """
*{box-sizing:border-box}body{margin:0;background:#b9b0d8;color:#1d2141;font:15px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif}
.sheet{max-width:1040px;margin:24px auto;background:#fffdf6;padding:28px 32px;border-radius:3px;box-shadow:0 20px 40px -18px rgba(42,34,82,.6);
background-image:linear-gradient(rgba(27,143,176,.10) 1px,transparent 1px),linear-gradient(90deg,rgba(27,143,176,.10) 1px,transparent 1px);background-size:26px 26px}
h1{font-size:34px;margin:0 0 4px;line-height:1.1}h1 span{background:linear-gradient(transparent 55%,#ffe74a 55%,#ffe74a 92%,transparent 92%)}
h2{font-size:21px;margin:28px 0 8px;border-bottom:2px solid #1b8fb0;padding-bottom:4px}
.meta{color:#555a73;margin:0 0 14px}.mono{font-family:ui-monospace,Menlo,Consolas,monospace}
table{width:100%;border-collapse:collapse;font-size:14px;background:#fff}th{text-align:left;font:600 11px/1.3 ui-monospace,Menlo,monospace;letter-spacing:.08em;text-transform:uppercase;color:#555a73;border-bottom:2px solid #1b8fb0;padding:6px 8px}
td{padding:6px 8px;border-bottom:1px dotted #c9d4e0;vertical-align:top}tr.day td{background:#e7f4f9;font-weight:700}
.chip{display:inline-block;padding:0 7px;border-radius:3px 7px 3px 6px;font:700 12px/1.6 ui-monospace,Menlo,monospace}
.v{display:inline-block;font-weight:800;border:2px solid currentColor;border-radius:999px;padding:0 10px;white-space:nowrap}
.bar{display:flex;height:16px;border:1.5px solid #1d2141;border-radius:4px;overflow:hidden;background:#fff;min-width:160px}.bar span{height:100%}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}.card{background:#fff;border-radius:3px;padding:12px 14px;box-shadow:0 2px 8px rgba(0,0,0,.12)}
.card h3{margin:0 0 4px;font-size:16px}.small{font-size:13px;color:#555a73}ul{margin:6px 0 0;padding-left:18px}
.done{text-decoration:line-through;color:#555a73}.foot{color:#555a73;font-size:12.5px;margin-top:26px}
@media print{body{background:#fff}.sheet{box-shadow:none;margin:0;padding:0;background:#fff}tr,.card{break-inside:avoid}}
"""


def esc(s):
    return html.escape(str(s), quote=True)


def page(title, body):
    return ('<!doctype html>\n<html lang="en-GB">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<title>%s</title>\n<style>%s</style>\n</head>\n<body>\n<div class="sheet">\n%s\n</div>\n</body>\n</html>\n') % (esc(title), CSS, body)


def plan_report(project, today):
    """The plan, where you stand on each exam, the next fortnight and the whole timetable."""
    plan = m.build_plan(project)
    st = m.status(project, plan, today)
    sm = m.summary(project, plan, st)
    done = m.done_map(project)
    colour = {e['id']: e['colour'] for e in plan['exams']}
    out = ['<h1><span>%s</span></h1>' % esc(project['name'])]
    out.append('<p class="meta">%s Revision plan made %s, as at %s. %d sessions: %s learning, %s spaced reviews, %s past papers, %s final reviews.</p>' % (
        esc(project['student'] + '.') if project['student'] else '', esc(m.fmt_day(project['planFrom'])), esc(m.fmt_day(today)), sm['sessions'],
        m.fmt_hours(sm['learnMin']), m.fmt_hours(sm['reviewMin']), m.fmt_hours(sm['paperMin']), m.fmt_hours(sm['finalMin'])))
    for n in plan['notes']:
        out.append('<p class="small">%s</p>' % esc(n['text']))
    out.append('<h2>On track for each exam?</h2><div class="cards">')
    for r in st['exams']:
        mx = max(r['need'], r['done'] + r['ahead'] + r['missed'], 1)
        short = max(0, r['need'] - r['done'] - r['ahead']) if r['verdict'] not in ('sat', 'today') else 0
        hl = HL[r['colour']]
        bar = ('<div class="bar" role="img" aria-label="%s done, %s planned, %s needed"><span style="width:%.2f%%;background:%s"></span>'
               '<span style="width:%.2f%%;background:repeating-linear-gradient(135deg,%s 0 5px,#fff 5px 9px)"></span>'
               '<span style="width:%.2f%%;background:repeating-linear-gradient(45deg,#d2352b 0 3px,#ffd9d5 3px 7px)"></span></div>') % (
            m.fmt_hours(r['done']), m.fmt_hours(r['ahead']), m.fmt_hours(r['need']), r['done'] * 100.0 / mx, hl, r['ahead'] * 100.0 / mx, hl, short * 100.0 / mx)
        out.append('<div class="card"><h3><span class="chip" style="background:%s">%s</span> %s</h3><p class="small">%s &middot; %s</p>'
                   '<p><span class="v" style="color:%s">%s</span></p>%s<p class="small mono">needed %s &middot; done %s &middot; still planned %s%s</p><ul class="small">%s</ul></div>' % (
                       hl, esc(r['code']), esc(r['name']), esc(m.fmt_day(r['day'])),
                       'sat' if r['verdict'] == 'sat' else ('today' if r['daysLeft'] == 0 else m.plural(r['daysLeft'], 'day') + ' to go'),
                       VERDICT_COLOUR[r['verdict']], esc(r['headline']), bar, m.fmt_hours(r['need']), m.fmt_hours(r['done']), m.fmt_hours(r['ahead']),
                       (' &middot; missed %s' % m.fmt_hours(r['missed'])) if r['missed'] else '', ''.join('<li>%s</li>' % esc(x) for x in r['reasons'])))
    out.append('</div>')
    out.append('<h2>Where each topic stands</h2>' + topics_table(project, plan, today, colour))
    out.append('<h2>The next fourteen days</h2>')
    out.append(sessions_table(plan, done, colour, today, today + 13))
    out.append('<h2>Hours each week</h2>' + week_table(plan))
    out.append('<h2>The whole plan</h2>')
    out.append(sessions_table(plan, done, colour, plan['from'], plan['last']))
    if project['missed']:
        out.append('<h2>Filed as missed when you re-planned</h2><ul class="small">%s</ul>' % ''.join(
            '<li>%s: %s</li>' % (esc(m.fmt_short(x['day'])), esc(x['title'])) for x in project['missed']))
    out.append('<p class="foot">Made by the Exam season companion. Same inputs, same plan: the browser app gives identical sessions.</p>')
    return page(project['name'] + ': revision plan', '\n'.join(out))


def sessions_table(plan, done, colour, first, last):
    rows = ['<table><thead><tr><th>Time</th><th>Module</th><th>What</th><th>Topic</th></tr></thead><tbody>']
    any_rows = False
    for d in range(max(first, plan['from']), min(last, plan['last']) + 1):
        lst = [se for se in plan['sessions'] if se['day'] == d]
        exams = [e for e in plan['exams'] if e['day'] == d]
        if not lst and not exams:
            continue
        any_rows = True
        rows.append('<tr class="day"><td colspan="4">%s%s</td></tr>' % (esc(m.fmt_long(d)), ''.join(
            ' &middot; <span style="color:#d2352b">EXAM %s at %s</span>' % (esc(e['code']), m.fmt_time(e['start'])) for e in exams)))
        for se in lst:
            cls = ' class="done"' if se['id'] in done else ''
            rows.append('<tr%s><td class="mono">%s&ndash;%s</td><td><span class="chip" style="background:%s">%s</span></td><td>%s<div class="small">%s</div></td><td>%s</td></tr>' % (
                cls, m.fmt_time(se['start']), m.fmt_time(se['end']), HL[colour[se['exam']]], esc(se['code']), esc(m.KIND_WORD[se['kind']]), esc(se['detail']),
                '' if se['kind'] == 'paper' else esc(se['title'])))
    rows.append('</tbody></table>')
    return '\n'.join(rows) if any_rows else '<p class="small">Nothing planned in these days.</p>'


RATING_COLOUR = ['#c9cbd8', '#ff8f80', '#ffe74a', '#82e297']


def topics_table(project, plan, today, colour):
    rows = m.topic_status(project, plan, today)
    exam_of = {e['code']: e for e in plan['exams']}
    out = ['<table><thead><tr><th>Topic</th><th>Confidence</th><th>Learning</th><th>Reviews</th><th>Next</th><th>State</th></tr></thead><tbody>']
    for r in rows:
        e = exam_of.get(r['code'])
        chip = HL[colour[e['id']]] if e else '#eee'
        dots = ''.join('<span title="%s" style="display:inline-block;width:11px;height:11px;border-radius:50%%;border:1px solid #1d2141;background:%s;margin-right:2px"></span>' % (
            m.RATING_WORD[k] or 'not rated', RATING_COLOUR[k]) for k in r['ratings'])
        nxt = '%s %s, %s' % (m.fmt_short(r['next']['day']), m.fmt_time(r['next']['start']), m.KIND_WORD[r['next']['kind']].lower()) if r['next'] else 'nothing planned'
        out.append('<tr><td><span class="chip" style="background:%s">%s</span> %s</td><td class="mono">%d</td><td class="mono">%d of %d%s</td><td>%s%s</td><td class="small">%s</td><td>%s</td></tr>' % (
            chip, esc(r['code']), esc(r['name']), r['conf'], r['learnDone'], r['learnTotal'], ' (%d missed)' % r['learnMissed'] if r['learnMissed'] else '',
            dots, ' <span class="small">+%d planned</span>' % r['reviewsAhead'] if r['reviewsAhead'] else '', esc(nxt), esc(r['state'])))
    out.append('</tbody></table>')
    return '\n'.join(out)


def week_table(plan):
    rows = ['<table><thead><tr><th>Week of</th><th>Planned</th><th>Available</th><th>By module</th></tr></thead><tbody>']
    start = plan['from'] - m.weekday(plan['from'])
    w = start
    while w <= plan['last']:
        cap = sum(d['cap'] for d in plan['days'] if w <= d['day'] < w + 7)
        by, tot = {}, 0
        for se in plan['sessions']:
            if w <= se['day'] < w + 7:
                by[se['exam']] = by.get(se['exam'], 0) + se['min']
                tot += se['min']
        parts = ' '.join('<span class="chip" style="background:%s">%s %s</span>' % (HL[e['colour']], esc(e['code']), m.fmt_hours(by[e['id']])) for e in plan['exams'] if by.get(e['id']))
        rows.append('<tr><td class="mono">%s</td><td class="mono">%s</td><td class="mono">%s</td><td>%s</td></tr>' % (esc(m.fmt_short(w)), m.fmt_hours(tot), m.fmt_hours(cap), parts))
        w += 7
    rows.append('</tbody></table>')
    return '\n'.join(rows)


def group_report(result, members):
    """The study group's sessions, week by week, with who is coming and what to cover."""
    out = ['<h1><span>Study group sessions</span></h1>']
    out.append('<p class="meta">%s. %s of %s each, from %s.</p>' % (
        esc(', '.join(x['name'] for x in members)), m.plural(len(result['sessions']), 'session'), m.fmt_dur(result['length']), esc(m.fmt_day(result['today']))))
    for n in result['notes']:
        out.append('<p class="small">%s</p>' % esc(n))
    out.append('<h2>Shared modules</h2><div class="cards">')
    for i, mod in enumerate(result['modules']):
        weakest = ', '.join(t['name'] for t in mod.get('topics', [])[:4])
        out.append('<div class="card"><h3><span class="chip" style="background:%s">%s</span> %s</h3><p class="small">Exam %s &middot; %s</p><p class="small">Weakest across the group: %s</p></div>' % (
            HL[i % 6], esc(mod['code']), esc(mod['name']), esc(m.fmt_day(mod['day'])), esc(', '.join(mod['members'])), esc(weakest or 'no topics listed')))
    out.append('</div><h2>Sessions</h2><table><thead><tr><th>When</th><th>Module</th><th>Who</th><th>Focus</th></tr></thead><tbody>')
    colour = {mod['code']: HL[i % 6] for i, mod in enumerate(result['modules'])}
    for se in result['sessions']:
        out.append('<tr><td class="mono">%s<br>%s&ndash;%s</td><td><span class="chip" style="background:%s">%s</span> %s</td><td>%s%s</td><td>%s</td></tr>' % (
            esc(m.fmt_day(se['day'])), m.fmt_time(se['start']), m.fmt_time(se['end']), colour[se['code']], esc(se['code']), esc(se['kind']),
            esc(', '.join(se['members'])), ('<div class="small">Cannot make it: %s</div>' % esc(', '.join(se['missing']))) if se['missing'] else '',
            esc(', '.join(se['focus']) or 'past papers')))
    out.append('</tbody></table><p class="foot">Made by the Exam season companion from each member\'s own plan file.</p>')
    return page('Study group sessions', '\n'.join(out))
