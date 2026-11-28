"""The browser model (run in Node) and the Python companion must give identical answers.

Each test sends the same inputs to both and compares everything they return:
parsed timetables, topics and calendars, every session of every plan, the
on-track verdicts, and the exact text of every exported file (CSV, .ics, day
text, project file). Skipped when Node is not installed.
"""

import random
import unittest

from helpers import (DATA, FROM, NODE, TODAY, first_difference, m, plain, py_project_job, run_bridge, sample_text)  # noqa: F401


def random_project(seed):
    """A made-up but plausible project: odd exam clashes, every setting, busy times and dated changes."""
    rng = random.Random(seed)
    start = FROM + rng.randint(-20, 20)
    p = m.new_project(start)
    p['name'] = 'Random %d' % seed
    p['planFromMin'] = rng.choice([0, 0, 0, 600, 845])
    codes = ['RND%d' % (1000 + i) for i in range(rng.randint(1, 7))]
    day = start + rng.randint(3, 25)
    for i, code in enumerate(codes):
        p['exams'].append({'id': '', 'code': code, 'name': 'Module %d' % i, 'day': day, 'start': rng.choice([540, 570, 840, 600]),
                           'duration': rng.choice([60, 90, 120, 150, 180, 1440]), 'room': 'Room %d' % i, 'seat': '', 'type': '', 'resit': False, 'note': ''})
        day += rng.choice([0, 1, 1, 2, 3, 5, 9])
    if rng.random() < 0.3:
        p['exams'].append({'id': '', 'code': 'TBC9999', 'name': 'No date', 'day': None, 'start': 570, 'duration': 120, 'room': '', 'seat': '', 'type': '', 'resit': True, 'note': ''})
    if rng.random() < 0.3:
        p['exams'].append({'id': '', 'code': codes[0], 'name': 'Second paper', 'day': day + 2, 'start': 570, 'duration': 90, 'room': '', 'seat': '', 'type': '', 'resit': False, 'note': ''})
    if rng.random() < 0.3:
        p['exams'].append({'id': '', 'code': 'OLD1000', 'name': 'Already sat', 'day': start - 4, 'start': 570, 'duration': 90, 'room': '', 'seat': '', 'type': '', 'resit': False, 'note': ''})
    for code in codes + (['ORPH100'] if rng.random() < 0.3 else []):
        for k in range(rng.randint(0, 12)):
            p['topics'].append({'id': '', 'code': code, 'name': 'Topic %s %d' % (code, k), 'conf': rng.randint(1, 5),
                                'size': rng.choice([60, 120, 180, 300, 420, 75, 600]), 'mode': rng.choice(['full'] * 6 + ['quick', 'drop']), 'note': ''})
    p['week'] = []
    for _ in range(7):
        a = rng.choice([480, 540, 600, 660])
        b = rng.choice([1080, 1200, 1260, 1440])
        p['week'].append({'from': a, 'to': b, 'minutes': rng.choice([0, 120, 180, 240, 300, 360, 600])})
    for _ in range(rng.randint(0, 8)):
        d = start + rng.randint(0, 50)
        ov = {'day': d, 'minutes': rng.choice([0, 0, 60, 120, 240]), 'label': 'Change'}
        if rng.random() < 0.4:
            ov['from'], ov['to'] = 600, 960
        p['overrides'].append(ov)
    for _ in range(rng.randint(0, 60)):
        d = start + rng.randint(-3, 60)
        s = rng.randint(6, 20) * 60 + rng.choice([0, 15, 30, 50])
        p['busy'].append({'day': d, 'start': s, 'end': min(1440, s + rng.choice([45, 60, 120, 240])), 'label': rng.choice(['Lecture', 'Shift', 'Match'])})
    st = p['settings']
    st['learnMin'] = rng.choice([30, 45, 50, 60, 90])
    st['reviewMin'] = rng.choice([15, 20, 25, 30])
    st['breakMin'] = rng.choice([0, 5, 10, 15])
    st['taperDays'] = rng.choice([1, 2, 3, 4, 6])
    st['papers'] = rng.choice([0, 1, 2, 3])
    st['maxShare'] = rng.choice([25, 40, 50, 70, 100])
    st['reviewShare'] = rng.choice([20, 40, 60, 100])
    st['busyGap'] = rng.choice([0, 15, 30])
    st['examGap'] = rng.choice([0, 30, 45, 90])
    st['examDay'] = rng.choice(['after', 'off', 'normal'])
    p = m.clean_project(plain(p), start)
    return m.project_file(p), start


def ticks_for(text, today, seed):
    """Tick a random share of sessions before 'today' in the plan the text describes."""
    rng = random.Random(seed)
    p = m.read_project(text, today)['project']
    plan = m.build_plan(p)
    out = []
    for se in plan['sessions']:
        if se['day'] < today and rng.random() < 0.7:
            out.append([se['id'], se['day']])
        elif se['day'] == today and rng.random() < 0.5:
            out.append([se['id'], today])
    return out


@unittest.skipIf(NODE is None, 'Node.js is not installed')
class AgreementTest(unittest.TestCase):
    maxDiff = None

    def compare(self, py, js, what):
        diff = first_difference(plain(py), js)
        self.assertIsNone(diff, '%s differs: %s' % (what, diff))

    def run_projects(self, jobs):
        js = run_bridge({'projects': jobs})['projects']
        for i, job in enumerate(jobs):
            py = py_project_job(job)
            for key in py:
                self.compare(py[key], js[i][key], 'project %d, %s' % (i, key))
            # Exported files are compared as exact text too.
            for key in ['csv', 'statusCsv', 'ics', 'icsToday', 'dayText', 'projectFile', 'availabilityCsv', 'markdown', 'markdownWeek', 'icsAlarm']:
                self.assertEqual(py[key], js[i][key], 'project %d, %s' % (i, key))

    def test_sample_plan_progress_and_replan(self):
        text = sample_text('sample-project.json')
        p = m.read_project(text, TODAY)['project']
        plan = m.build_plan(p)
        todays = [se['id'] for se in plan['sessions'] if se['day'] == TODAY]
        later = [se['id'] for se in plan['sessions'] if se['day'] == TODAY + 3]
        jobs = [
            {'project': text, 'today': TODAY},
            {'project': text, 'today': TODAY, 'replan': {'day': TODAY, 'min': 0}},
            {'project': text, 'today': TODAY, 'ticks': [[todays[0], TODAY], [later[0], TODAY], [p['done'][0]['id'], TODAY, False]], 'replan': {'day': TODAY, 'min': 780}},
            {'project': text, 'today': TODAY, 'rates': [[r, TODAY, k] for r, k in zip([se['id'] for se in plan['sessions'] if se['kind'] == 'review' and se['day'] <= TODAY][:9], [1, 3, 2, 0, 1, 1, 3, 3, 2])],
             'replan': {'day': TODAY, 'min': 0}},
            {'project': text, 'today': TODAY + 5, 'replan': {'day': TODAY + 5, 'min': 0}, 'overrides': [{'day': TODAY + 6, 'minutes': 0, 'label': 'Ill'}, {'day': TODAY + 9, 'minutes': 60, 'label': 'Short day'}]},
            {'project': text, 'today': m.day_from_ymd(2027, 1, 14)},
            {'project': text, 'today': m.day_from_ymd(2027, 2, 1)},
        ]
        self.run_projects(jobs)

    def test_group_members_plans(self):
        jobs = []
        for name in ['alex', 'sam', 'priya']:
            text = sample_text('group/%s.json' % name)
            jobs.append({'project': text, 'today': FROM})
            jobs.append({'project': text, 'today': FROM + 9, 'ticks': ticks_for(text, FROM + 9, 7), 'replan': {'day': FROM + 9, 'min': 0}})
        self.run_projects(jobs)

    def test_random_projects(self):
        jobs = []
        for seed in range(40):
            text, start = random_project(seed)
            today = start + (seed % 9)
            job = {'project': text, 'today': today}
            if seed % 3 == 0:
                job['ticks'] = ticks_for(text, today, seed)
                job['rates'] = [[t[0], t[1], (seed + i) % 4] for i, t in enumerate(job['ticks']) if t[0].startswith('review:')]
                job['replan'] = {'day': today, 'min': [0, 615][seed % 2]}
            jobs.append(job)
        self.run_projects(jobs)

    def test_large_project(self):
        p = m.new_project(FROM)
        for i in range(12):
            code = 'BIG%d' % (1000 + i)
            p['exams'].append({'id': '', 'code': code, 'name': 'Module %d' % i, 'day': FROM + 70 + i * 3, 'start': 570, 'duration': 120,
                               'room': '', 'seat': '', 'type': '', 'resit': False, 'note': ''})
            for k in range(40):
                p['topics'].append({'id': '', 'code': code, 'name': 'Topic %d' % k, 'conf': 1 + k % 5, 'size': [60, 120, 180, 300][k % 4], 'mode': 'full', 'note': ''})
        text = m.project_file(m.clean_project(plain(p), FROM))
        self.run_projects([{'project': text, 'today': FROM + 20}])

    def test_readers_on_every_sample_file(self):
        exams = [{'text': sample_text(n), 'ref': TODAY} for n in ['alex/exam-timetable.csv', 'messy-timetable.txt', 'exam-timetable.ics',
                                                                  'group/sam/exam-timetable.csv', 'group/priya/exam-timetable.csv', 'template-exams.csv', 'exam-timetable.html']]
        exam_list = m.read_exams(sample_text('alex/exam-timetable.csv'), ref=TODAY)['exams']
        topics = [{'text': sample_text(n), 'exams': plain(exam_list)} for n in ['alex/topics.csv', 'topics-pasted.txt', 'group/sam/topics.csv', 'template-topics.csv']]
        topics.append({'text': sample_text('topics-pasted.txt'), 'exams': []})
        cals = [{'text': sample_text(n), 'from': FROM - 7, 'to': FROM + 70} for n in ['alex/busy-calendar.ics', 'group/sam/busy-calendar.ics', 'group/priya/busy-calendar.ics', 'exam-timetable.ics']]
        avail = [{'text': sample_text(n)} for n in ['alex/availability.csv', 'group/sam/availability.csv', 'group/priya/availability.csv']]
        busy = [{'text': sample_text(n), 'from': FROM - 7, 'to': FROM + 70} for n in ['group/sam/shift-rota.csv', 'alex/busy-calendar.ics', 'alex/topics.csv']]
        js = run_bridge({'exams': exams, 'topics': topics, 'calendars': cals, 'availability': avail, 'busy': busy})
        for i, x in enumerate(busy):
            self.compare(m.read_busy(x['text'], x['from'], x['to']), js['busy'][i], 'busy %d' % i)
        for i, x in enumerate(exams):
            self.compare(m.read_exams(x['text'], ref=x['ref']), js['exams'][i], 'exams %d' % i)
        for i, x in enumerate(topics):
            r = m.read_topics(x['text'], exams=x['exams'])
            m.assign_topic_ids(r['topics'])
            self.compare(r, js['topics'][i], 'topics %d' % i)
        for i, x in enumerate(cals):
            self.compare(m.read_calendar(x['text'], x['from'], x['to']), js['calendars'][i], 'calendar %d' % i)
        for i, x in enumerate(avail):
            self.compare(m.read_availability(x['text']), js['availability'][i], 'availability %d' % i)
        self.assertEqual(js['templates'], [m.exam_template(), m.topic_template()])

    def test_messy_inputs_and_small_parsers(self):
        dates = ['11/01/2027', '1/2/27', '2027-01-11', 'Mon 11 Jan', '11th January 2027', 'January 11, 2027', 'Jan 11', '31/02/2027', 'TBC', '',
                 '11-Jan-27', 'Friday 22nd January 2027', '20270111T093000Z', '13.01.2027 14:00', 'sometime', '29/02/2028', '1 Sept 2027', '12 June']
        times = ['09:30', '9.30am', '2pm', '2:00', '1400', 'noon', '12am', '24:00', '9', '7 p.m.', '0930', 'half nine', '13:75']
        durations = ['2 hours', '2h', '120', '1h 30m', '1:30', '90 mins', '2.5 hrs', '(3 hours)', '1.25', 'two hours', '2 hrs 15 mins', '15']
        conf = ['2', '2/5', 'conf 4', 'amber', 'GREEN', '★★★☆☆', '45%', 'L', '3h', '90 min', 'xl', 'huge', '7',
                'Prospect theory (2, L)', 'Chapter 3', 'Nash equilibrium - conf 2 - large', 'Elasticity [1/5] [4h]', 'Week 5: markets', 'Supply - big']
        delimited = ['a,b\n"c, d",e\n', '﻿x;y;z\r\n1;2;3', 'one\ttwo\n"q\tq"\tthree', 'col  two  three\nval  2  3', '"unclosed,quote\nnext,line']
        folds = ['x' * 200, 'é' * 80, 'SUMMARY:' + 'café ' * 30, '\U0001F4DA' * 30]
        slugs = ['Porter’s five forces', '  ', 'A/B testing', 'x' * 80, 'Café résumé']
        codes = ['ECO3112 Behavioural', 'eco 3112', 'Room 101', 'BM-3104', 'LT101 lecture', 'nothing here']
        utc = [[m.day_from_ymd(2027, 3, 28), 59], [m.day_from_ymd(2027, 3, 28), 60], [m.day_from_ymd(2027, 10, 31), 59], [m.day_from_ymd(2027, 10, 31), 60], [m.day_from_ymd(2027, 7, 1), 1430]]
        messy_exams = [
            'Module,Title,Date,Time,Length\nABC1001,One,32/01/2027,9am,2h\nABC1002,Two,11/01/2027,,\nABC1002,Two,11/01/2027,,\n,,,,\nABC1003,Three,tbc,,\n',
            'Course\tPaper\tWhen\tStarts\tEnds\nXYZ2001\tPaper 1\t2027-01-12\t09:00\t11:30\n',
            'random words\nno exams here\n', '%PDF-1.4', 'PK\x03\x04[Content_Types].xml',
            'BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART;VALUE=DATE:20270112\nSUMMARY:ABC1234 Exam\nEND:VEVENT\nEND:VCALENDAR',
            'Course,Date,Time,Length\nABC1001,01/13/2027,9:00 AM,2h\nABC1002,01/08/2027,1:30 PM,90\n', 'Module,Date\nABC1001,02/01/2027\n',
            '<html><body><table><tr><th>Code</th><th>Exam date</th><th>Venue</th></tr><tr><td>XYZ1001</td><td>Tue 12 Jan 2027, 9:30&ndash;11:00</td><td>Hall &amp; Annex</td></tr>'
            '<tr><td>XYZ1002<td>14/01/2027 14:00-16:00<td>Hall</tr></table>', '<table><tr><td>nothing</td></tr></table>',
        ]
        messy_topics = ['Topic\nNo module\n', 'ABC1234:\n- One (9)\n- Two (2, M)\n- Two (2, M)\n', '# Heading without code\n- x\n', '', 'Module,Topic,Confidence,Size\nABC1234,One,high,huge\nABC1234,Two,6,3 lectures\n']
        messy_cals = ['BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART;TZID=America/New_York:20261201T090000\nDURATION:PT1H30M\nRRULE:FREQ=DAILY;COUNT=3\nSUMMARY:Call\nEND:VEVENT\n'
                      'BEGIN:VEVENT\nDTSTART:20261203T100000\nRRULE:FREQ=MONTHLY;BYMONTHDAY=3\nSUMMARY:Monthly\nEND:VEVENT\nBEGIN:VEVENT\nSUMMARY:No start\nEND:VEVENT\nEND:VCALENDAR',
                      'nope']
        js = run_bridge({'dates': dates, 'times': times, 'durations': durations, 'confidence': conf, 'delimited': delimited, 'folds': folds,
                         'slugs': slugs, 'codes': codes, 'utc': utc,
                         'exams': [{'text': t, 'ref': TODAY} for t in messy_exams], 'topics': [{'text': t, 'exams': []} for t in messy_topics],
                         'calendars': [{'text': t, 'from': FROM, 'to': FROM + 60} for t in messy_cals]})
        self.compare([[m.parse_date(s, 'DMY', 20788), m.parse_date(s, 'MDY', 20788), m.find_date(s, 'DMY', 20788)] for s in dates], js['dates'], 'dates')
        self.compare([[m.parse_time(s), m.find_times(s), m.parse_clock(s)] for s in times], js['times'], 'times')
        self.compare([[m.parse_duration(s, ''), m.parse_duration(s, 'min'), m.parse_duration(s, 'hour')] for s in durations], js['durations'], 'durations')
        self.compare([[m.parse_confidence(s), m.parse_size(s, True), m.parse_size(s, False), m.split_topic_attrs(s)] for s in conf], js['confidence'], 'confidence')
        self.compare([[m.sniff_delimiter(t), m.parse_delimited(t, m.sniff_delimiter(t)), m.read_table(t)] for t in delimited], js['delimited'], 'delimited')
        self.assertEqual([m.ics_fold(s) for s in folds], js['folds'])
        self.assertEqual([m.slugify(s) for s in slugs], js['slugs'])
        self.compare([[m.find_code(s), m.norm_code(s)] for s in codes], js['codes'], 'codes')
        self.compare([list(m.utc_to_london(a, b)) for a, b in utc], js['utc'], 'utc')
        for i, t in enumerate(messy_exams):
            self.compare(m.read_exams(t, ref=TODAY), js['exams'][i], 'messy exams %d' % i)
        for i, t in enumerate(messy_topics):
            r = m.read_topics(t, exams=[])
            m.assign_topic_ids(r['topics'])
            self.compare(r, js['topics'][i], 'messy topics %d' % i)
        for i, t in enumerate(messy_cals):
            self.compare(m.read_calendar(t, FROM, FROM + 60), js['calendars'][i], 'messy calendar %d' % i)

    def test_damaged_project_files_are_cleaned_the_same_way(self):
        texts = [
            '{"app":"exam-season","exams":[{"code":"abc 1234","day":"2027-01-11","start":"570","duration":-5},{"code":""},7],'
            '"topics":[{"code":"ABC1234","name":"  One  ","conf":9,"size":"x","mode":"weird"},{"name":"no code"}],'
            '"week":[1,2,3],"settings":{"learnMin":1000,"reviewMin":5,"examDay":"maybe","papers":-1},'
            '"done":[{"id":"learn:x:1","day":"2026-12-01","min":50},{"id":"learn:x:1","day":"2026-12-02"},{"day":"2026-12-01"}],'
            '"settled":["learn:x:1","nope",3],"overrides":[{"day":"2026-12-05","minutes":"60"},{"day":"bad"},{"day":"2026-12-05","minutes":0}],'
            '"busy":[{"day":"2026-12-05","start":600,"end":500},{"day":"2026-12-06","start":600,"end":700}],"planFrom":"2026-12-01","asOf":"nonsense"}',
            '{"exams":[]}', '[]', '{"app":"exam-season","version":99}',
        ]
        js = run_bridge({'cleaned': texts})['cleaned']
        for i, t in enumerate(texts):
            r = m.read_project(t, 20788)
            py = m.project_file(r['project']) if r['project'] else r['messages']
            self.compare(py, js[i], 'cleaned %d' % i)


if __name__ == '__main__':
    unittest.main()
