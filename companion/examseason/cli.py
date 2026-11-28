"""Command line for Exam season.

  plan    build a plan from your files (or a folder of them) and write the plan
          file, a calendar, a CSV and an HTML report
  today   the morning job: re-plan from today if anything was missed, then
          write today's sessions as text and .ics (run it from cron or a
          scheduled task)
  tick    tick sessions off (or untick them) in a plan file
  status  are you on track for each exam?
  report  an HTML report of a plan file
  retro   how you kept to the plan, by weekday and module, with suggestions
  group   shared sessions for a study group, from each member's plan file
  check   show how each input file is read, without planning

Dates are written YYYY-MM-DD. "Today" is the real date unless --date is given.
"""

import argparse
import datetime
import json
import os
import sys

from . import group as grp
from . import model as m
from . import report as rep
from .samples import calendar_horizon, import_files, read

KINDS = ('exams', 'topics', 'availability', 'calendar')


def real_today():
    d = datetime.date.today()
    return m.day_from_ymd(d.year, d.month, d.day)


def parse_day(text, what='date'):
    d = m.from_iso(text) if text else None
    if d is None:
        raise SystemExit('Could not read the %s "%s": write it as YYYY-MM-DD.' % (what, text))
    return d


def write_text(path, text):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(text)


def load_project(path, today):
    try:
        text = read(path)
    except OSError as exc:
        raise SystemExit('Could not open %s: %s' % (path, exc.strerror))
    r = m.read_project(text, today)
    if r['project'] is None:
        raise SystemExit('%s: %s' % (path, r['messages'][0]['text']))
    for msg in r['messages']:
        print('Note: ' + msg['text'], file=sys.stderr)
    return r['project']


def detect(path):
    """Which kind of input a file is: exams, topics, availability or calendar (or None)."""
    try:
        text = read(path)
    except OSError:
        return None, None
    low = text[:4000].lower()
    if m.is_html_table(text):
        if m.read_exams(text)['exams']:
            return 'exams', text
        if m.read_topics(text)['topics']:
            return 'topics', text
        return None, text
    if 'begin:vcalendar' in low:
        cal = m.parse_ics(text)
        exams = sum(1 for e in cal['events'] if m.EXAMISH.search(e['summary'] + ' ' + e['description'] + ' ' + e['categories']))
        return ('exams' if exams and exams * 2 >= len(cal['events']) else 'calendar'), text
    if path.lower().endswith('.json'):
        return None, text
    table = m.read_table(text)
    for row in table['rows'][:20]:
        if m.exam_header_score(m.map_columns(row['cells'], m.EXAM_SYNONYMS, m.EXAM_KEYWORDS)) >= 2:
            return 'exams', text
        tm = m.map_columns(row['cells'], m.TOPIC_SYNONYMS, [])
        if 'name' in tm and ('conf' in tm or 'size' in tm):
            return 'topics', text
        bm = m.map_columns(row['cells'], m.BUSY_SYNONYMS, [])
        am = m.map_columns(row['cells'], m.AVAIL_SYNONYMS, [])
        rota = 'date' in bm and 'start' in bm and ('end' in bm or 'duration' in bm)
        if rota or ('day' in am and ('hours' in am or 'from' in am or 'to' in am)):
            # A weekly template names weekdays; a rota lists dates.
            col = bm['date'] if rota else am['day']
            body = [m.trim(r['cells'][col]) for r in table['rows'][table['rows'].index(row) + 1:] if col < len(r['cells']) and m.trim(r['cells'][col])][:20]
            dated = sum(1 for c in body if m.parse_date(c) is not None)
            if rota and dated and dated * 2 > len(body):
                return 'calendar', text
            return 'availability', text
    ex = m.read_exams(text)
    if ex['exams'] and any(e['day'] is not None for e in ex['exams']):
        return 'exams', text
    tp = m.read_topics(text)
    if tp['topics']:
        return 'topics', text
    return None, text


def gather(args):
    """Input files by kind, from the named options and from --folder."""
    files = {k: [] for k in KINDS}
    for k in KINDS:
        for p in getattr(args, k) or []:
            files[k].append(p)
    if args.folder:
        if not os.path.isdir(args.folder):
            raise SystemExit('%s is not a folder.' % args.folder)
        for name in sorted(os.listdir(args.folder)):
            path = os.path.join(args.folder, name)
            if not os.path.isfile(path) or name.startswith('.'):
                continue
            if 'template' in name.lower():
                print('Skipped %s: a blank template.' % name)
                continue
            kind, _text = detect(path)
            if kind is None:
                print('Skipped %s: not an exam timetable, topic list, availability file or calendar.' % name)
                continue
            if kind == 'availability' and files['availability']:
                print('Skipped %s: only one availability file is used (%s).' % (name, os.path.basename(files['availability'][0])))
                continue
            print('%-28s read as %s' % (name, kind))
            files[kind].append(path)
    return files


def build_project(files, start, name, modules=None):
    p = m.new_project(start)
    p['name'] = name
    if not files['exams']:
        raise SystemExit('No exam timetable given: use --exams FILE (or put it in --folder).')
    p = import_files(p, exams_path=files['exams'][0], today=start)
    for extra in files['exams'][1:]:
        res = m.read_exams(read(extra), ref=start)
        seen = {(e['code'], e['day'], e['start']) for e in p['exams']}
        added = [e for e in res['exams'] if (e['code'], e['day'], e['start']) not in seen]
        if len(added) < len(res['exams']):
            print('%s: %s already in %s, so counted once.' % (os.path.basename(extra), m.plural(len(res['exams']) - len(added), 'exam'), os.path.basename(files['exams'][0])))
        p['exams'].extend(added)
        p['sources'].append({'kind': 'exams', 'name': os.path.basename(extra), 'summary': m.import_summary('exams', res)})
    for path in files['topics']:
        res = m.read_topics(read(path), exams=p['exams'])
        seen = {(t['code'], t['name'].lower()) for t in p['topics']}
        for t in res['topics']:
            if (t['code'], t['name'].lower()) not in seen:
                p['topics'].append(t)
        m.assign_topic_ids(p['topics'])
        p['sources'].append({'kind': 'topics', 'name': os.path.basename(path), 'summary': m.import_summary('topics', res)})
    for path in files['availability'][:1]:
        p = import_files(p, availability_path=path, today=start)
    for path in files['calendar']:
        frm, to = calendar_horizon(p, start)
        res = m.read_busy(read(path), frm, to)
        p['busy'].extend(res['busy'])
        p['allDay'].extend(res['allDay'])
        p['sources'].append({'kind': 'calendar', 'name': os.path.basename(path), 'summary': m.import_summary('calendar', res)})
    if modules:
        codes = m.parse_code_list(modules)
        before = len(p['exams'])
        p['exams'] = m.keep_modules(p['exams'], codes)
        print('Kept %d of the %d exams: the ones for %s.' % (len(p['exams']), before, ', '.join(codes)))
    elif len(p['exams']) > 40:
        print('Note: %d exams were read, far more than one student sits. Add --modules CODE,CODE to keep only yours.' % len(p['exams']))
    return m.clean_project(json.loads(m.project_file(p)), start)


def print_checks(project, plan, today, out=None):
    out = out or sys.stdout
    checks = m.check_inputs(project, plan, today)
    for c in checks:
        print('Check [%s]: %s' % (c['level'], c['text']), file=out)
    return checks


def print_status(project, plan, today, out=None):
    out = out or sys.stdout
    st = m.status(project, plan, today)
    print('On track? (as at %s)' % m.fmt_day(today), file=out)
    for r in st['exams']:
        print('  %-8s %-34s %-11s %-16s needed %7s  done %7s  planned %7s' % (
            r['code'], r['name'][:34], m.fmt_short(r['day']), r['headline'], m.fmt_hours(r['need']), m.fmt_hours(r['done']), m.fmt_hours(r['ahead'])), file=out)
        for reason in r['reasons']:
            print('           - ' + reason, file=out)
        if r['quick']:
            names = [t['name'] for t in project['topics'] if t['id'] in r['quick']]
            print('           To free time: switch %s to a quick look (saves about %s),' % (', '.join(names), m.fmt_hours(r['quickSaves'])), file=out)
            print('           or find room for %s more before %s.' % (m.plural(r['extraSessions'], '%d-minute session' % project['settings']['learnMin']), m.fmt_short(plan['byExam'][r['id']]['learnBy'])), file=out)
    return st


def print_topics(project, plan, today, out=None):
    out = out or sys.stdout
    rows = m.topic_status(project, plan, today)
    code = None
    for r in rows:
        if r['code'] != code:
            code = r['code']
            print('\n%s' % code, file=out)
        marks = ''.join('-' if k == 1 else '+' if k == 3 else 'o' for k in r['ratings'])
        nxt = '%s %s %s' % (m.fmt_short(r['next']['day']), m.fmt_time(r['next']['start']), m.KIND_WORD[r['next']['kind']].lower()) if r['next'] else 'nothing planned'
        print('  %-38s conf %d  learnt %d/%d  reviews %-6s %-12s next %s' % (r['name'][:38], r['conf'], r['learnDone'], r['learnTotal'], marks or '.', r['state'], nxt), file=out)
    print('\nReviews: - shaky, o OK, + solid.', file=out)


def cmd_plan(args):
    start = parse_day(args.start, 'start date') if args.start else real_today()
    files = gather(args)
    p = build_project(files, start, args.name, args.modules)
    for src in p['sources']:
        print('%-13s %-24s %s' % (src['kind'], src['name'], src['summary']))
    plan = m.build_plan(p)
    for n in plan['notes']:
        print('Note: ' + n['text'])
    sm = m.summary(p, plan, m.status(p, plan, start))
    print_checks(p, plan, start)
    print('\n%d sessions on %d days from %s to %s: %s learning, %s reviews, %s past papers, %s final reviews.\n' % (
        sm['sessions'], sm['studyDays'], m.fmt_short(plan['from']), m.fmt_short(plan['last']), m.fmt_hours(sm['learnMin']),
        m.fmt_hours(sm['reviewMin']), m.fmt_hours(sm['paperMin']), m.fmt_hours(sm['finalMin'])))
    print_status(p, plan, start)
    write_text(args.out, m.project_file(p))
    print('\nWrote the plan file %s (open it in the app, or use it with "today" each morning).' % args.out)
    if args.ics:
        write_text(args.ics, m.sessions_ics(p, plan, name=p['name'], alarm=args.alarm))
        print('Wrote %s' % args.ics)
    if args.markdown:
        write_text(args.markdown, m.checklist_markdown(p, plan))
        print('Wrote %s' % args.markdown)
    if args.csv:
        write_text(args.csv, m.sessions_csv(p, plan))
        print('Wrote %s' % args.csv)
    if args.report:
        write_text(args.report, rep.plan_report(p, start))
        print('Wrote %s' % args.report)
    return 0


def now_minutes(text):
    if not text:
        n = datetime.datetime.now()
        return n.hour * 60 + n.minute
    t = m.parse_clock(text)
    if t is None:
        raise SystemExit('Could not read the time "%s": write it as HH:MM.' % text)
    return t


def cmd_today(args):
    today = parse_day(args.date) if args.date else real_today()
    p = load_project(args.project, today)
    plan = m.build_plan(p)
    st = m.status(p, plan, today)
    missed = st['missed']
    replanned = False
    shaky = st['shakyNew']
    if args.replan == 'always' or (args.replan == 'auto' and (missed or shaky)):
        # Re-plan from the start of the day unless a time is given (or it is
        # really today, when sessions already past are not planned again).
        start_min = now_minutes(args.now) if args.now else (0 if args.date else now_minutes(''))
        m.replan(p, plan, today, start_min)
        plan = m.build_plan(p)
        replanned = True
    text = m.day_text(p, plan, today)
    head = []
    if replanned:
        head.append('Re-planned from %s: %s filed as missed, every tick kept%s.' % (
            m.fmt_short(today), m.plural(len(missed), 'session'), ', %s back sooner after a shaky review' % m.plural(shaky, 'topic') if shaky else ''))
    elif missed:
        head.append('%s before today %s not ticked off (not re-planned: --replan never).' % (m.plural(len(missed), 'session'), 'is' if len(missed) == 1 else 'are'))
    out_text = ('\n'.join(head) + '\n\n' if head else '') + text
    sys.stdout.write(out_text)
    folder = args.out_dir
    if folder:
        stem = 'revision-' + m.iso_day(today)
        write_text(os.path.join(folder, stem + '.txt'), out_text)
        write_text(os.path.join(folder, stem + '.ics'), m.sessions_ics(p, plan, from_day=today, to_day=today, exams=True, skip_done=True, name='Revision today', alarm=args.alarm))
        write_text(os.path.join(folder, stem + '.md'), m.checklist_markdown(p, plan, today, today + 6))
        print('\nWrote %s.txt, %s.ics and %s.md (the next seven days) in %s' % (stem, stem, stem, folder))
    if replanned:
        if args.dry_run:
            print('(Dry run: the plan file was not changed.)')
        else:
            write_text(args.project, m.project_file(p))
            print('Updated %s' % args.project)
    return 0


def cmd_tick(args):
    today = parse_day(args.date) if args.date else real_today()
    if args.day and not args.date:
        # Ticking a day's sessions means they were done on that day.
        today = max(today, parse_day(args.day, 'day'))
    p = load_project(args.project, today)
    plan = m.build_plan(p)
    ids = list(args.ids)
    if args.all_today:
        ids += [se['id'] for se in plan['sessions'] if se['day'] == today]
    if args.day:
        d = parse_day(args.day, 'day')
        ids += [se['id'] for se in plan['sessions'] if se['day'] == d]
    if not ids:
        raise SystemExit('Name the sessions to tick (their ids are in the CSV), or use --all-today or --day YYYY-MM-DD.')
    changed = 0
    rating = {'shaky': 1, 'ok': 2, 'solid': 3}.get(args.rate or '', 0)
    for ident in ids:
        if ident not in plan['byId'] and not args.undo:
            print('Not in the plan: %s' % ident, file=sys.stderr)
            continue
        before = len(p['done'])
        m.tick(p, plan, ident, today, not args.undo)
        if len(p['done']) != before:
            changed += 1
        if rating and not args.undo and ident.startswith('review:'):
            m.rate(p, plan, ident, today, rating)
    write_text(args.project, m.project_file(p))
    print('%s %s. Updated %s' % ('Unticked' if args.undo else 'Ticked', m.plural(changed, 'session'), args.project))
    return 0


def cmd_status(args):
    today = parse_day(args.date) if args.date else real_today()
    p = load_project(args.project, today)
    plan = m.build_plan(p)
    print_checks(p, plan, today)
    st = print_status(p, plan, today)
    if args.topics:
        print_topics(p, plan, today)
    if args.csv:
        write_text(args.csv, m.status_csv(st))
        print('Wrote %s' % args.csv)
    return 0 if st['verdict'] in ('ok', 'tight') else 2


def cmd_retro(args):
    """How the plan went: time done against time planned, by weekday and by module, with suggestions."""
    today = parse_day(args.date) if args.date else real_today()
    p = load_project(args.project, today)
    plan = m.build_plan(p)
    ad = m.adherence(p, plan, today)
    if not ad['days']:
        print('Nothing to look back on yet: no sessions were planned before %s.' % m.fmt_short(today))
        return 0
    print('How you kept to the plan, %s up to %s: %s of %s done (%d%%).' % (m.plural(ad['days'], 'day'), m.fmt_short(today - 1), m.fmt_hours(ad['done']), m.fmt_hours(ad['planned']), ad['pct']))
    print('\nBy weekday')
    for w in ad['weekdays']:
        if not w['planned']:
            continue
        bar = '#' * (w['pct'] // 5)
        print('  %-10s %-20s %3d%%  %s of %s over %s' % (m.WEEKDAYS[w['weekday']], bar, w['pct'], m.fmt_hours(w['done']), m.fmt_hours(w['planned']), m.plural(w['days'], 'day')))
    by_exam = {}
    done = m.done_map(p)
    for d in p['done']:
        if d['day'] < today:
            x = by_exam.setdefault(d['code'], [0, 0])
            x[0] += d['min']
            x[1] += d['min']
    for d in p['missed']:
        if d['day'] < today:
            by_exam.setdefault(d['code'], [0, 0])[1] += d['min']
    for se in plan['sessions']:
        if se['day'] < today and se['id'] not in done:
            by_exam.setdefault(se['code'], [0, 0])[1] += se['min']
    print('\nBy module')
    for code in sorted(by_exam):
        dn, pl = by_exam[code]
        print('  %-10s %3d%%  %s of %s' % (code, (dn * 100 + pl // 2) // pl if pl else 0, m.fmt_hours(dn), m.fmt_hours(pl)))
    tips = [w for w in ad['weekdays'] if w['suggest'] is not None]
    if tips:
        print('\nFor a plan you can keep')
        for w in tips:
            print('  On %ss you did about %s of the %s planned: set %ss to %s under Your time.' % (
                m.WEEKDAYS[w['weekday']], m.fmt_hours(w['done'] // w['days']), m.fmt_hours(p['week'][w['weekday']]['minutes']), m.WEEKDAYS[w['weekday']],
                m.fmt_hours(w['suggest']) if w['suggest'] else 'no revision'))
    return 0


def cmd_report(args):
    today = parse_day(args.date) if args.date else real_today()
    p = load_project(args.project, today)
    write_text(args.out, rep.plan_report(p, today))
    print('Wrote %s' % args.out)
    return 0


def cmd_group(args):
    today = parse_day(args.date) if args.date else real_today()
    members, used = [], set()
    for path in args.projects:
        p = load_project(path, today)
        name = grp.member_name(p, path)
        base, k = name, 2
        while name in used:
            name = '%s %d' % (base, k)
            k += 1
        used.add(name)
        members.append({'name': name, 'project': p, 'path': path})
    if len(members) < 2:
        raise SystemExit('A study group needs at least two plan files.')
    result = grp.plan_group(members, today, length=args.length, per_week=args.per_week)
    print('Study group: %s' % ', '.join(x['name'] for x in members))
    for n in result['notes']:
        print('Note: ' + n)
    for se in result['sessions']:
        print('  %s %s-%s  %-8s %-18s %s%s%s' % (m.fmt_short(se['day']).ljust(10), m.fmt_time(se['start']), m.fmt_time(se['end']), se['code'], se['kind'],
                                               ', '.join(se['members']), (' (not ' + ', '.join(se['missing']) + ')') if se['missing'] else '',
                                               ('  focus: ' + ', '.join(se['focus'])) if se['focus'] else ''))
    os.makedirs(args.out, exist_ok=True)
    write_text(os.path.join(args.out, 'group-sessions.csv'), grp.group_csv(result))
    write_text(os.path.join(args.out, 'group-sessions.ics'), grp.group_ics(result, today))
    write_text(os.path.join(args.out, 'group-report.html'), rep.group_report(result, members))
    written = ['group-sessions.csv', 'group-sessions.ics', 'group-report.html']
    if args.update_members:
        for mem in members:
            p2 = grp.add_to_member(mem['project'], mem['name'], result)
            plan2 = m.build_plan(p2)
            m.replan(p2, plan2, max(today, p2['planFrom']), 0)
            fname = m.slugify(mem['name']) + '-with-group.json'
            write_text(os.path.join(args.out, fname), m.project_file(p2))
            written.append(fname)
    print('Wrote %s in %s' % (', '.join(written), args.out))
    return 0


def cmd_check(args):
    today = parse_day(args.date) if args.date else real_today()
    status = 0
    # Topics are matched to the exams in the same check, as they are in a plan.
    files = [(path,) + tuple(detect(path)) for path in args.files]
    exams = []
    for path, kind, text in files:
        if text is not None and kind == 'exams':
            exams += m.read_exams(text, ref=today)['exams']
    for path, kind, text in files:
        print('== %s: %s' % (path, kind or 'not recognised'))
        if text is None:
            print('   could not be read as text')
            status = 1
            continue
        if kind == 'exams' or kind is None:
            res = m.read_exams(text, ref=today)
            for e in res['exams']:
                print('   %-8s %-36s %s %s %s %s' % (e['code'], e['name'][:36], 'date TBC   ' if e['day'] is None else m.fmt_short(e['day']).ljust(11),
                                                  m.fmt_time(e['start']), m.fmt_dur(e['duration']), e['room']))
        elif kind == 'topics':
            res = m.read_topics(text, exams)
            for t in res['topics']:
                print('   %-8s %-40s confidence %d, %s' % (t['code'], t['name'][:40], t['conf'], m.size_label(t['size'])))
        elif kind == 'availability':
            res = m.read_availability(text, None, today)
            for i, w in enumerate(res['week']):
                print('   %s %s-%s up to %s' % (m.WD3[i], m.fmt_time(w['from']), m.fmt_time(w['to']), m.fmt_hours(w['minutes'])))
            for v in res['overrides']:
                print('   %s %s %s' % (m.fmt_day(v['day']), 'blocked' if not v['minutes'] else m.fmt_hours(v['minutes']), v['label']))
        else:
            res = m.read_busy(text, today - 7, today + 400)
            for b in m.busy_summary(res['busy'])[:20]:
                print('   %-40s %3d times  %s' % (b['label'][:40], b['count'], m.fmt_hours(b['minutes'])))
        for k, msg in enumerate(res['messages']):
            if k == 40:
                print('   and %d more notes like these' % (len(res['messages']) - 40))
            if k >= 40:
                if msg['level'] == 'error':
                    status = 1
                continue
            print('   [%s] %s' % (msg['level'], msg['text']))
            if msg['level'] == 'error':
                status = 1
    return status


def build_parser():
    ap = argparse.ArgumentParser(prog='exam_season', description='Revision plans from your exam timetable, topics and free time.')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('plan', help='build a plan from your files')
    p.add_argument('--exams', action='append', help='exam timetable: CSV, TSV, a saved web page, pasted text or .ics')
    p.add_argument('--topics', action='append', help='topics: CSV or a pasted list')
    p.add_argument('--availability', action='append', help='weekly hours and dated changes (CSV)')
    p.add_argument('--calendar', action='append', help='busy times: a calendar (.ics) or a rota (CSV); repeat for several')
    p.add_argument('--folder', help='a folder of input files; each one is recognised by its contents')
    p.add_argument('--start', help='first day of the plan (default today)')
    p.add_argument('--name', default='My revision plan', help='a name for the plan')
    p.add_argument('--modules', help='keep only these module codes from the timetable, for example "ECO3112,FIN3020"')
    p.add_argument('--out', default='revision-plan.json', help='the plan file to write')
    p.add_argument('--ics', help='also write the sessions as a calendar file')
    p.add_argument('--csv', help='also write the sessions as CSV')
    p.add_argument('--report', help='also write an HTML report')
    p.add_argument('--markdown', help='also write the plan as a Markdown checklist')
    p.add_argument('--alarm', type=int, default=0, choices=[0, 5, 10, 15, 30, 60], help='minutes of warning before each session in the calendar file')
    p.set_defaults(func=cmd_plan)

    t = sub.add_parser('today', help="the morning job: re-plan if needed, then today's sessions as text and .ics")
    t.add_argument('project')
    t.add_argument('--date', help='treat this day as today (YYYY-MM-DD)')
    t.add_argument('--now', help='re-plan from this time of day (HH:MM); default the start of the day when --date is given')
    t.add_argument('--replan', choices=['auto', 'always', 'never'], default='auto', help='auto (default): re-plan when sessions before today were missed')
    t.add_argument('--out-dir', help='write revision-YYYY-MM-DD.txt and .ics here')
    t.add_argument('--dry-run', action='store_true', help='do not save the re-planned project')
    t.add_argument('--alarm', type=int, default=10, choices=[0, 5, 10, 15, 30, 60], help='minutes of warning before each session in the .ics (default 10)')
    t.set_defaults(func=cmd_today)

    k = sub.add_parser('tick', help='tick sessions off in a plan file')
    k.add_argument('project')
    k.add_argument('ids', nargs='*', help='session ids (see the CSV)')
    k.add_argument('--all-today', action='store_true', help="tick every session planned for today")
    k.add_argument('--day', help='tick every session planned for this day')
    k.add_argument('--undo', action='store_true', help='untick instead')
    k.add_argument('--rate', choices=['shaky', 'ok', 'solid'], help='how the review(s) went; a shaky one comes back sooner after the next re-plan')
    k.add_argument('--date', help='treat this day as today')
    k.set_defaults(func=cmd_tick)

    s = sub.add_parser('status', help='are you on track for each exam?')
    s.add_argument('project')
    s.add_argument('--date')
    s.add_argument('--csv', help='write the table as CSV')
    s.add_argument('--topics', action='store_true', help='also list every topic: learning, reviews and what is next')
    s.set_defaults(func=cmd_status)

    rt = sub.add_parser('retro', help='how you kept to the plan: done against planned, by weekday and module')
    rt.add_argument('project')
    rt.add_argument('--date')
    rt.set_defaults(func=cmd_retro)

    r = sub.add_parser('report', help='an HTML report of a plan file')
    r.add_argument('project')
    r.add_argument('--out', default='revision-report.html')
    r.add_argument('--date')
    r.set_defaults(func=cmd_report)

    g = sub.add_parser('group', help='shared sessions for a study group')
    g.add_argument('projects', nargs='+', help="each member's plan file")
    g.add_argument('--out', default='study-group', help='folder for the CSV, .ics and report')
    g.add_argument('--length', type=int, default=90, help='minutes per group session (default 90)')
    g.add_argument('--per-week', type=int, default=1, help='sessions per shared module per week (default 1)')
    g.add_argument('--update-members', action='store_true', help="also write each member's plan with the group sessions as busy times, re-planned")
    g.add_argument('--date')
    g.set_defaults(func=cmd_group)

    c = sub.add_parser('check', help='show how input files are read')
    c.add_argument('files', nargs='+')
    c.add_argument('--date')
    c.set_defaults(func=cmd_check)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)
