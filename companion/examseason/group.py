"""Study-group mode: shared sessions where everyone taking the same module is free.

Each member brings their own plan file (from the app or the command line).
For every module that two or more members are sitting, one group session a
week is found, up to two days before the exam: the earliest time in the week
when every member taking it is inside their revision window, not busy, not
sitting an exam and not on a day they have kept for another exam. If nobody
can make every member's time, the slot that suits the most members (at least
two) is used and the others are named. A member never gets two group
sessions at once. Each session focuses on the topics the group as a whole
feels least sure about, so every session covers different ground.

The sessions can be written back into each member's plan as busy times, so
their personal plans re-plan around them.
"""

import json
import os

from . import model as m


def member_name(project, path=''):
    """A short name: the first word of the student field, or the file name."""
    if project.get('student'):
        first = project['student'].split(',')[0].split(' (')[0].strip()
        if first:
            return first.split(' ')[0]
    base = os.path.splitext(os.path.basename(path))[0] if path else 'Member'
    return base.replace('-', ' ').replace('_', ' ').strip().title() or 'Member'


def free_time(project, day):
    """A member's free intervals and hours on a day; nothing on a day they sit an exam."""
    s = project['settings']
    exams_by_day = {}
    for e in project['exams']:
        if e['day'] is not None:
            exams_by_day.setdefault(e['day'], []).append(e)
    if day in exams_by_day:
        return [], 0
    busy_by_day = {}
    for b in project['busy']:
        busy_by_day.setdefault(b['day'], []).append(b)
    f = m.day_free(project, day, exams_by_day, busy_by_day, s)
    return f['intervals'], f['cap']


def intersect(a, b):
    out = []
    i = j = 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if hi > lo:
            out.append([lo, hi])
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def kept_days(project):
    """Days a member keeps for an exam (the day before each one), from their own plan."""
    plan = m.build_plan(project)
    out = {}
    for e in plan['exams']:
        if e['finalDay'] is not None:
            out[e['finalDay']] = e['code']
    return out


def plan_group(members, today, length=90, per_week=1):
    """members: [{'name', 'project'}]. Returns {'modules', 'sessions', 'notes'}."""
    notes = []
    exam_of = {}
    for mem in members:
        mem['kept'] = kept_days(mem['project'])
        mem['taken'] = {}
        for e in mem['project']['exams']:
            if e['day'] is None or e['day'] < today:
                continue
            cur = exam_of.setdefault(e['code'], {'code': e['code'], 'name': e['name'], 'day': e['day'], 'members': []})
            if mem['name'] not in cur['members']:
                cur['members'].append(mem['name'])
            if e['day'] < cur['day']:
                cur['day'] = e['day']
    shared = m.sort_by([x for x in exam_of.values() if len(x['members']) >= 2], lambda a, b: m.cmp(a['day'], b['day']) or m.cmp(a['code'], b['code']))
    for x in m.sort_by([x for x in exam_of.values() if len(x['members']) < 2], lambda a, b: m.cmp(a['code'], b['code'])):
        notes.append('%s is only taken by %s, so it has no group sessions.' % (x['code'], x['members'][0]))
    by_name = {mem['name']: mem for mem in members}
    sessions = []
    for mod in shared:
        weak = weakest_topics(mod['code'], [by_name[n] for n in mod['members']])
        mod['topics'] = weak
        covered = 0
        week = today - m.weekday(today)
        last_day = mod['day'] - 2
        count = 0
        while week <= last_day:
            for _k in range(per_week):
                mems = [by_name[n] for n in mod['members']]
                slot = best_slot(mod, mems, max(week, today), min(week + 6, last_day), length, True)
                if slot is None:
                    slot = best_slot(mod, mems, max(week, today), min(week + 6, last_day), length, False)
                if slot is None:
                    break
                focus = [t['name'] for t in weak[covered:covered + 3]] if weak else []
                covered = covered + 3 if covered + 3 < len(weak) else 0
                final_week = week + 7 > last_day
                count += 1
                se = {
                    'id': 'group:%s:%d' % (m.slugify(mod['code']), count), 'code': mod['code'], 'name': mod['name'], 'day': slot['day'],
                    'start': slot['start'], 'end': slot['start'] + length, 'members': slot['members'], 'missing': slot['missing'],
                    'focus': focus, 'kind': 'Past paper debrief' if final_week else 'Group review', 'examDay': mod['day'],
                }
                sessions.append(se)
                for n in slot['members']:
                    by_name[n]['taken'].setdefault(slot['day'], []).append([slot['start'], slot['start'] + length])
            week += 7
        if count == 0:
            notes.append('No time could be found for a %s group session before %s.' % (mod['code'], m.fmt_short(mod['day'])))
    sessions = m.sort_by(sessions, lambda a, b: m.cmp(a['day'], b['day']) or m.cmp(a['start'], b['start']) or m.cmp(a['code'], b['code']))
    return {'modules': shared, 'sessions': sessions, 'notes': notes, 'length': length, 'today': today}


def weakest_topics(code, mems):
    """The module's topics ordered by the group's average confidence, weakest first."""
    by = {}
    order = []
    for mem in mems:
        for t in mem['project']['topics']:
            if t['code'] != code or t['mode'] == 'drop':
                continue
            key = t['name'].lower()
            if key not in by:
                by[key] = {'name': t['name'], 'total': 0, 'n': 0}
                order.append(key)
            by[key]['total'] += t['conf']
            by[key]['n'] += 1
    items = [by[k] for k in order]
    # Compare averages by cross-multiplying, so no rounding is involved.
    return m.sort_by(items, lambda a, b: m.cmp(a['total'] * b['n'], b['total'] * a['n']) or m.cmp(b['n'], a['n']) or m.cmp(a['name'].lower(), b['name'].lower()))


def best_slot(mod, mems, first_day, last_day, length, spread):
    """The earliest slot in the days given where all members are free, or the one that suits most.

    With spread set, days on which a member already has a group session are
    passed over, so a week's sessions land on different days.
    """
    best = None
    for day in range(first_day, last_day + 1):
        frees = []
        for mem in mems:
            taken = mem['taken'].get(day, [])
            if (day in mem['kept'] and mem['kept'][day] != mod['code']) or (spread and taken):
                frees.append([])
                continue
            ivs, cap = free_time(mem['project'], day)
            if cap - sum(t[1] - t[0] for t in taken) < length:
                frees.append([])
                continue
            for t in taken:
                ivs = m.cut(ivs, t[0] - 15, t[1] + 15)
            frees.append([iv for iv in ivs if iv[1] - iv[0] >= length])
        # Everyone first.
        common = frees[0]
        for f in frees[1:]:
            common = intersect(common, f)
        common = [iv for iv in common if iv[1] - iv[0] >= length]
        if common:
            start = m.round_up5(common[0][0])
            if start + length <= common[0][1]:
                return {'day': day, 'start': start, 'members': [x['name'] for x in mems], 'missing': []}
        # Otherwise the largest group of at least two, earliest first.
        for size in range(len(mems) - 1, 1, -1):
            cand = subset_slot(mems, frees, size, length)
            if cand and (best is None or len(cand['members']) > len(best['members'])):
                cand['day'] = day
                best = cand
                break
    return best


def subset_slot(mems, frees, size, length):
    names = [x['name'] for x in mems]
    idx = list(range(len(mems)))

    def combos(start, k):
        if k == 0:
            yield []
            return
        for i in range(start, len(idx) - k + 1):
            for rest in combos(i + 1, k - 1):
                yield [i] + rest

    for combo in combos(0, size):
        common = frees[combo[0]]
        for c in combo[1:]:
            common = intersect(common, frees[c])
        common = [iv for iv in common if iv[1] - iv[0] >= length]
        if common:
            start = m.round_up5(common[0][0])
            if start + length <= common[0][1]:
                return {'start': start, 'members': [names[c] for c in combo], 'missing': [names[i] for i in idx if i not in combo]}
    return None


def group_csv(result):
    rows = [['Date', 'Day', 'Start', 'End', 'Module', 'Module title', 'Kind', 'Who', 'Cannot make it', 'Focus topics', 'Exam date']]
    for se in result['sessions']:
        rows.append([m.iso_day(se['day']), m.WD3[m.weekday(se['day'])], m.fmt_time(se['start']), m.fmt_time(se['end']), se['code'], se['name'], se['kind'],
                     '; '.join(se['members']), '; '.join(se['missing']), '; '.join(se['focus']), m.iso_day(se['examDay'])])
    return m.csv_text(rows)


def group_ics(result, stamp_day):
    stamp = m.ics_stamp(stamp_day, 0) + 'Z'
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Exam season//Study group//EN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
             'X-WR-CALNAME:Study group sessions', 'X-WR-TIMEZONE:Europe/London']
    lines.extend(m.VTIMEZONE)
    for se in result['sessions']:
        desc = '%s with %s.' % (se['kind'], ', '.join(se['members']))
        if se['focus']:
            desc += ' Focus: ' + ', '.join(se['focus']) + '.'
        if se['missing']:
            desc += ' Cannot make it: ' + ', '.join(se['missing']) + '.'
        lines += ['BEGIN:VEVENT', 'UID:' + se['id'].replace(':', '-') + '@exam-season', 'DTSTAMP:' + stamp,
                  'DTSTART;TZID=Europe/London:' + m.ics_stamp(se['day'], se['start']), 'DTEND;TZID=Europe/London:' + m.ics_stamp(se['day'], se['end']),
                  'SUMMARY:' + m.ics_escape('%s %s: %s' % (se['code'], se['name'], se['kind'].lower())), 'DESCRIPTION:' + m.ics_escape(desc),
                  'CATEGORIES:Study group', 'END:VEVENT']
    lines.append('END:VCALENDAR')
    return '\r\n'.join(m.ics_fold(l) for l in lines) + '\r\n'


def add_to_member(project, name, result):
    """A copy of a member's project with their group sessions added as busy times."""
    p = m.clean_project(json.loads(m.project_file(project)), project['planFrom'])
    for se in result['sessions']:
        if name in se['members']:
            p['busy'].append({'day': se['day'], 'start': se['start'], 'end': se['end'], 'label': 'Study group: %s %s' % (se['code'], se['kind'].lower())})
    p['sources'].append({'kind': 'calendar', 'name': 'study group', 'summary': m.plural(sum(1 for se in result['sessions'] if name in se['members']), 'group session')})
    return m.clean_project(p, project['planFrom'])
