"""Tests of the Python companion: the model on its own, the command line, the
morning job, the study-group planner and the HTML reports."""

import contextlib
import html.parser
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from helpers import COMPANION, DATA, FROM, ROOT, TODAY, es, load, m, sample_text

from examseason import cli, group, report


def run_cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(list(args))
    return code, out.getvalue()


class HtmlCheck(html.parser.HTMLParser):
    """Counts tags and checks every tag that should close does."""
    VOID = {'meta', 'br', 'img', 'input', 'link', 'hr'}

    def __init__(self):
        super().__init__()
        self.stack, self.tags, self.errors = [], {}, []

    def handle_starttag(self, tag, attrs):
        self.tags[tag] = self.tags.get(tag, 0) + 1
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append('unexpected </%s>' % tag)
        else:
            self.stack.pop()


def check_html(text):
    p = HtmlCheck()
    p.feed(text)
    p.close()
    return p


class ModelTest(unittest.TestCase):
    def test_sample_status_tells_the_story(self):
        p = load('sample-project.json')
        plan = m.build_plan(p)
        st = m.status(p, plan, TODAY)
        self.assertEqual([r['verdict'] for r in st['exams']], ['behind', 'behind', 'behind', 'tight', 'tight'])
        self.assertEqual(len(st['missed']), 8)
        m.replan(p, plan, TODAY, 0)
        plan = m.build_plan(p)
        st = m.status(p, plan, TODAY)
        self.assertEqual(st['exams'][4]['verdict'], 'short')
        self.assertTrue(st['exams'][4]['quick'])

    def test_every_session_fits_the_day(self):
        p = load('group/alex.json', FROM)
        plan = m.build_plan(p)
        for se in plan['sessions']:
            w = m.day_window(p, se['day'])
            self.assertFalse(w['blocked'])
            self.assertGreaterEqual(se['start'], w['from'])
            self.assertLessEqual(se['end'], w['to'])
        for d in plan['days']:
            self.assertLessEqual(d['used'], d['cap'])

    def test_project_round_trip_and_damaged_files(self):
        p = load('sample-project.json')
        text = m.project_file(p)
        self.assertEqual(m.project_file(m.read_project(text, TODAY)['project']), text)
        self.assertIsNone(m.read_project('{"x": 1}', TODAY)['project'])
        self.assertIsNone(m.read_project('not json', TODAY)['project'])
        self.assertEqual(text, sample_text('sample-project.json'), 'the bundled sample is current')

    def test_no_em_dash_anywhere_in_outputs(self):
        p = load('sample-project.json')
        plan = m.build_plan(p)
        st = m.status(p, plan, TODAY)
        for text in [m.sessions_csv(p, plan), m.sessions_ics(p, plan), m.day_text(p, plan, TODAY), m.status_csv(st), report.plan_report(p, TODAY)]:
            self.assertNotIn(chr(0x2014), text)


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def test_plan_from_a_folder_writes_every_file(self):
        code, out = run_cli('plan', '--folder', os.path.join(DATA, 'alex'), '--start', '2026-11-30', '--name', 'Alex',
                            '--out', self.path('plan.json'), '--ics', self.path('plan.ics'), '--csv', self.path('plan.csv'), '--report', self.path('plan.html'))
        self.assertEqual(code, 0)
        self.assertIn('topics.csv                   read as topics', out)
        self.assertIn('302 sessions on 48 days', out)
        p = m.read_project(open(self.path('plan.json'), encoding='utf-8').read(), FROM)['project']
        self.assertEqual(len(p['exams']), 5)
        self.assertEqual(len(p['topics']), 40)
        ics = open(self.path('plan.ics'), encoding='utf-8', newline='').read()
        self.assertTrue(ics.startswith('BEGIN:VCALENDAR\r\n'))
        self.assertEqual(ics.count('BEGIN:VEVENT'), 302 + 5)
        rows = open(self.path('plan.csv'), encoding='utf-8-sig').read().splitlines()
        self.assertEqual(len(rows), 303)
        page = open(self.path('plan.html'), encoding='utf-8').read()
        self.assertEqual(check_html(page).errors, [])
        self.assertIn('On track for each exam?', page)

    def test_plan_from_named_files_merges_duplicate_exams(self):
        code, out = run_cli('plan', '--exams', os.path.join(DATA, 'alex', 'exam-timetable.csv'), '--exams', os.path.join(DATA, 'exam-timetable.ics'),
                            '--topics', os.path.join(DATA, 'topics-pasted.txt'), '--start', '2026-11-30', '--out', self.path('p.json'))
        self.assertEqual(code, 0)
        self.assertIn('5 exams already in exam-timetable.csv, so counted once', out)
        p = json.loads(open(self.path('p.json'), encoding='utf-8').read())
        self.assertEqual(len(p['exams']), 5)
        self.assertEqual(len(p['topics']), 9)

    def test_the_morning_job_replans_and_writes_today(self):
        shutil.copy(os.path.join(DATA, 'sample-project.json'), self.path('s.json'))
        code, out = run_cli('today', self.path('s.json'), '--date', '2026-12-10', '--out-dir', self.path('today'))
        self.assertEqual(code, 0)
        self.assertIn('Re-planned from Thu 10 Dec: 8 sessions filed as missed', out)
        txt = open(self.path('today', 'revision-2026-12-10.txt'), encoding='utf-8').read()
        self.assertIn('Thursday 10 December 2026', txt)
        ics = open(self.path('today', 'revision-2026-12-10.ics'), encoding='utf-8', newline='').read()
        self.assertGreaterEqual(ics.count('BEGIN:VEVENT'), 3)
        p = m.read_project(open(self.path('s.json'), encoding='utf-8').read(), TODAY)['project']
        self.assertEqual(p['planFrom'], TODAY)
        self.assertEqual(len(p['missed']), 8)
        # A second run the same morning has nothing new to re-plan.
        code, out = run_cli('today', self.path('s.json'), '--date', '2026-12-10')
        self.assertNotIn('Re-planned', out)

    def test_tick_status_and_report(self):
        shutil.copy(os.path.join(DATA, 'sample-project.json'), self.path('s.json'))
        code, out = run_cli('tick', self.path('s.json'), '--all-today', '--date', '2026-12-10')
        self.assertIn('Ticked 4 sessions', out)
        code, out = run_cli('tick', self.path('s.json'), 'nonsense:id', '--date', '2026-12-10')
        self.assertIn('Ticked 0 sessions', out)
        code, out = run_cli('status', self.path('s.json'), '--date', '2026-12-10', '--csv', self.path('status.csv'))
        self.assertEqual(code, 2, 'exit code 2 when an exam is behind or short')
        self.assertIn('Behind', out)
        self.assertTrue(open(self.path('status.csv'), encoding='utf-8-sig').read().startswith('Module,Title,Exam date'))
        code, out = run_cli('report', self.path('s.json'), '--date', '2026-12-10', '--out', self.path('r.html'))
        page = open(self.path('r.html'), encoding='utf-8').read()
        self.assertEqual(check_html(page).errors, [])
        self.assertIn('The next fourteen days', page)

    def test_check_explains_each_file(self):
        code, out = run_cli('check', os.path.join(DATA, 'messy-timetable.txt'), os.path.join(DATA, 'alex', 'availability.csv'),
                            os.path.join(DATA, 'alex', 'busy-calendar.ics'), os.path.join(DATA, 'topics-pasted.txt'), '--date', '2026-11-30')
        self.assertEqual(code, 0)
        self.assertIn('MKT2210', out)
        self.assertIn('repeats the header row', out)
        self.assertIn('Shift at Wren Lane Coffee', out)
        self.assertIn('Dynamic capabilities', out)
        bad = self.path('statement.pdf')
        with open(bad, 'w', encoding='utf-8') as fh:
            fh.write('%PDF-1.7 not a timetable')
        code, out = run_cli('check', bad)
        self.assertEqual(code, 1)
        self.assertIn('This is a PDF file', out)

    def test_bad_arguments_give_plain_messages(self):
        with self.assertRaises(SystemExit) as ctx:
            run_cli('today', os.path.join(DATA, 'sample-project.json'), '--date', '10/12/2026')
        self.assertIn('YYYY-MM-DD', str(ctx.exception))
        with self.assertRaises(SystemExit) as ctx:
            run_cli('plan', '--topics', os.path.join(DATA, 'alex', 'topics.csv'), '--out', self.path('x.json'))
        self.assertIn('No exam timetable', str(ctx.exception))
        with self.assertRaises(SystemExit) as ctx:
            run_cli('status', self.path('missing.json'))
        self.assertIn('Could not open', str(ctx.exception))

    def test_script_runs_as_a_program(self):
        proc = subprocess.run([sys.executable, os.path.join(COMPANION, 'exam_season.py'), '--help'], capture_output=True, encoding='utf-8')
        self.assertEqual(proc.returncode, 0)
        self.assertIn('group', proc.stdout)


class GroupTest(unittest.TestCase):
    def members(self):
        out = []
        for name in ['alex', 'sam', 'priya']:
            p = load('group/%s.json' % name, FROM)
            out.append({'name': group.member_name(p, name), 'project': p})
        return out

    def test_sessions_fit_everyone_who_comes(self):
        mems = self.members()
        result = group.plan_group(mems, FROM, length=90)
        self.assertEqual([x['code'] for x in result['modules']], ['ECO3112', 'FIN3020', 'LAW3207', 'DAT3301'])
        self.assertGreater(len(result['sessions']), 20)
        by = {x['name']: x['project'] for x in mems}
        seen = {}
        for se in result['sessions']:
            self.assertLessEqual(se['day'], se['examDay'] - 2)
            self.assertGreaterEqual(len(se['members']), 2)
            for name in se['members']:
                p = by[name]
                ivs, cap = group.free_time(p, se['day'])
                self.assertTrue(any(iv[0] <= se['start'] and se['end'] <= iv[1] for iv in ivs), '%s is free for %s' % (name, se['id']))
                self.assertFalse(any(e['day'] == se['day'] for e in p['exams']), 'not on an exam day')
                for other in seen.get((name, se['day']), []):
                    self.assertTrue(se['start'] >= other[1] or se['end'] <= other[0], 'no double booking')
                seen.setdefault((name, se['day']), []).append((se['start'], se['end']))
        # Focus topics are the group's weakest first.
        fin = [se for se in result['sessions'] if se['code'] == 'FIN3020'][0]
        self.assertEqual(len(fin['focus']), 3)
        self.assertIn('MGT3104 is only taken by Alex, so it has no group sessions.', result['notes'])

    def test_outputs_and_members_replanned_around_the_group(self):
        mems = self.members()
        result = group.plan_group(mems, FROM, length=90)
        csv = group.group_csv(result)
        self.assertEqual(csv.count('\r\n'), len(result['sessions']) + 1)
        ics = group.group_ics(result, FROM)
        self.assertEqual(ics.count('BEGIN:VEVENT'), len(result['sessions']))
        page = report.group_report(result, mems)
        self.assertEqual(check_html(page).errors, [])
        alex = group.add_to_member(mems[0]['project'], 'Alex', result)
        plan = m.build_plan(alex)
        mine = [se for se in result['sessions'] if 'Alex' in se['members']]
        for gs in mine:
            for se in plan['sessions']:
                if se['day'] == gs['day']:
                    self.assertTrue(se['end'] <= gs['start'] or se['start'] >= gs['end'], 'personal sessions move round the group')

    def test_command_line_group(self):
        tmp = tempfile.mkdtemp()
        try:
            code, out = run_cli('group', *[os.path.join(DATA, 'group', n + '.json') for n in ['alex', 'sam', 'priya']], '--date', '2026-11-30',
                                '--out', tmp, '--update-members')
            self.assertEqual(code, 0)
            self.assertIn('Study group: Alex, Sam, Priya', out)
            for name in ['group-sessions.csv', 'group-sessions.ics', 'group-report.html', 'alex-with-group.json', 'sam-with-group.json', 'priya-with-group.json']:
                self.assertTrue(os.path.exists(os.path.join(tmp, name)), name)
            with self.assertRaises(SystemExit):
                run_cli('group', os.path.join(DATA, 'group', 'alex.json'), '--out', tmp)
        finally:
            shutil.rmtree(tmp)

    def test_icalendar_library_reads_the_files(self):
        try:
            import icalendar
        except ImportError:
            self.skipTest('the icalendar library is not installed')
        p = load('sample-project.json')
        plan = m.build_plan(p)
        cal = icalendar.Calendar.from_ical(m.sessions_ics(p, plan))
        events = [c for c in cal.walk() if c.name == 'VEVENT']
        self.assertEqual(len(events), len(plan['sessions']) + len(plan['exams']))
        first = events[0]
        self.assertEqual(str(first['SUMMARY']), m.session_title(plan['sessions'][0]))
        self.assertEqual(first.decoded('DTSTART').hour, plan['sessions'][0]['start'] // 60)


if __name__ == '__main__':
    unittest.main()
