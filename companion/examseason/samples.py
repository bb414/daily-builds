"""Build the sample project the app opens with, from the files in data/."""

import os

from . import model as m

PLAN_FROM = m.day_from_ymd(2026, 11, 30)
AS_OF = m.day_from_ymd(2026, 12, 10)


def read(path):
    with open(path, encoding='utf-8', newline='') as fh:
        return fh.read()


def import_files(project, exams_path=None, topics_path=None, availability_path=None, calendar_path=None, today=None):
    """Load input files into a project the way the app does, recording each source."""
    today = project['planFrom'] if today is None else today
    if exams_path:
        res = m.read_exams(read(exams_path), ref=today)
        project['exams'] = res['exams']
        project['sources'].append({'kind': 'exams', 'name': os.path.basename(exams_path), 'summary': m.import_summary('exams', res)})
    if topics_path:
        res = m.read_topics(read(topics_path), exams=project['exams'])
        m.assign_topic_ids(res['topics'])
        project['topics'] = res['topics']
        project['sources'].append({'kind': 'topics', 'name': os.path.basename(topics_path), 'summary': m.import_summary('topics', res)})
    if availability_path:
        res = m.read_availability(read(availability_path), project['week'])
        project['week'] = res['week']
        project['overrides'] = res['overrides']
        project['sources'].append({'kind': 'availability', 'name': os.path.basename(availability_path), 'summary': m.import_summary('availability', res)})
    if calendar_path:
        frm, to = calendar_horizon(project, today)
        res = m.read_calendar(read(calendar_path), frm, to)
        project['busy'] = res['busy']
        project['allDay'] = res['allDay']
        project['sources'].append({'kind': 'calendar', 'name': os.path.basename(calendar_path), 'summary': m.import_summary('calendar', res)})
    return m.clean_project(project, today)


def calendar_horizon(project, today):
    """The days a calendar is read for: a week before the plan to a week after the last exam (or a year ahead)."""
    days = [e['day'] for e in project['exams'] if e['day'] is not None]
    frm = min(project['planFrom'], today) - 7
    to = max(days) + 7 if days else today + 365
    return frm, max(to, today + 60)


def member_project(folder, name=None, student=None):
    """A plan file from one student's folder of files, planned from Mon 30 Nov 2026."""
    p = m.new_project(PLAN_FROM)
    p['name'] = name or "Alex's January exams"
    p['student'] = student or 'Alex Marlow (invented), final year, Brackenmoor University (invented)'
    p = import_files(p, os.path.join(folder, 'exam-timetable.csv'), os.path.join(folder, 'topics.csv'),
                     os.path.join(folder, 'availability.csv'), os.path.join(folder, 'busy-calendar.ics'), PLAN_FROM)
    return m.project_file(p)


def sample_project(data_dir):
    """The sample: Alex's January exams planned from Mon 30 Nov 2026, with ten days ticked off."""
    p = m.read_project(member_project(os.path.join(data_dir, 'alex')), PLAN_FROM)['project']
    plan = m.build_plan(p)
    # Ten days of progress: everything done except Sat 5 Dec (a long away
    # fixture), the evening sessions on Tue 1 Dec and one review on Mon 7 Dec.
    skip_day = m.day_from_ymd(2026, 12, 5)
    for se in plan['sessions']:
        if se['day'] >= AS_OF or se['day'] == skip_day:
            continue
        if se['day'] == m.day_from_ymd(2026, 12, 1) and se['start'] >= 16 * 60:
            continue
        if se['day'] == m.day_from_ymd(2026, 12, 7) and se['kind'] == 'review':
            continue
        m.tick(p, plan, se['id'], se['day'], True)
    p['asOf'] = AS_OF
    return m.project_file(p)
