"""Tests of the Python companion: reading, matching and the jobs only it does (team review, weekly job, reports, command line)."""

import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import helpers as h

rt = h.rt
CLI = os.path.join(h.ROOT, 'companion', 'round_trips.py')


def run_cli(*args):
    proc = subprocess.run([sys.executable, CLI] + list(args), capture_output=True, text=True, encoding='utf-8')
    return proc.returncode, proc.stdout + proc.stderr


def sample_result():
    st = rt.read_project(h.sample_text('sample-journal.json'))['state']
    return rt.analyse(rt.import_files(st, h.sample_files())['state'])


class ReadingTest(unittest.TestCase):
    def test_the_three_sample_layouts(self):
        reps = [rt.read_export(f['name'], f['text']) for f in h.sample_files()]
        self.assertEqual([r['ok'] for r in reps], [True, True, True])
        eq, fut, uk = reps
        self.assertEqual(eq['counts']['fills'], 524)
        self.assertEqual(eq['columns']['side'], 'Action')
        self.assertEqual(fut['dateOrder'], 'MDY')
        self.assertEqual(fut['counts']['fees'], 58)
        self.assertEqual(uk['account'], 'Dealing account')
        self.assertEqual(uk['fills'][0]['price'], 4180000)

    def test_unreadable_rows_are_explained(self):
        text = 'Date,Symbol,Side,Qty,Price\n2026-11-23,QX,Buy,10,1\n2026-13-45,QX,Buy,10,1\n2026-11-23,,Buy,10,1\n2026-11-23,QX,Buy,0,1\n2026-11-23,QX,Buy,10,\n'
        rep = rt.read_export('x.csv', text)
        self.assertEqual([s['reason'] for s in rep['skipped']], ['date not recognised: 2026-13-45', 'no symbol', 'quantity is zero, nothing filled', 'no price'])
        self.assertEqual([s['line'] for s in rep['skipped']], [3, 4, 5, 6])

    def test_a_byte_order_mark_extra_columns_and_reordered_columns(self):
        text = '\ufeffNotes,Price,Qty,Ticker,Side,Exec Time,Venue\n"bought, early",10.00,5,QX,Buy,2026-11-23 09:30:00,X\nok,10.50,5,QX,Sell,2026-11-23 09:35:00,X\n'
        res = rt.analyse(rt.import_files(rt.empty_state(), [{'name': 'x.csv', 'text': text}])['state'])
        self.assertEqual(len(res['closed']), 1)
        self.assertEqual(res['closed'][0]['gross'], 250)


class AnalysisTest(unittest.TestCase):
    def test_the_sample_figures(self):
        res = sample_result()
        s = rt.stats(res['closed'], rt.start_balance(res, res['accounts']))
        self.assertEqual((s['n'], s['net'], s['fees']), (237, 712174, 474692))
        self.assertEqual(len(res['open']), 1)
        self.assertEqual(res['open'][0]['symbol'], 'GLBM')
        rv = rt.week_review(res, rt.from_iso('2026-11-23'))
        self.assertEqual(rv['stats']['net'], 159571)
        self.assertIn('Not financial advice.', rt.review_text(rv, res))

    def test_a_reopened_journal_merges_next_weeks_export_without_double_counting(self):
        one = rt.import_files(rt.empty_state(), [{'name': 'a.csv', 'text': h.sample_text('weekly/export-2026-11-20.csv')}])['state']
        saved = rt.project_file(one, '2026-11-20')
        reopened = rt.read_project(saved)['state']
        two = rt.import_files(reopened, [{'name': 'b.csv', 'text': h.sample_text('weekly/export-2026-11-27.csv')}])
        full = rt.import_files(rt.empty_state(), [{'name': 'c.csv', 'text': h.sample_text('challenge-equities.csv')}])['state']
        self.assertEqual(len(two['state']['fills']), len(full['fills']))
        self.assertEqual(two['reports'][0]['duplicates'], 62)
        self.assertEqual(rt.stats(rt.analyse(two['state'])['closed'])['net'], rt.stats(rt.analyse(full)['closed'])['net'])

    def test_position_size(self):
        p = rt.position_size({'equity': '100000', 'riskPct': '1', 'entry': '41.20', 'stop': '40.85', 'fee': '0.01'})
        self.assertEqual(p['units'], 2777)
        self.assertEqual([rt.fmt_price(t['price']) for t in p['targets']], ['41.55', '41.90', '42.25'])


class ReportTest(unittest.TestCase):
    def test_weekly_report_is_one_page_with_no_outside_requests(self):
        res = sample_result()
        rv = rt.week_review(res, rt.from_iso('2026-11-23'))
        page = rt.weekly_report(res, rv, rt.review_text(rv, res))
        self.assertTrue(page.startswith('<!doctype html>'))
        self.assertIn('w/c 23 Nov 2026', page)
        self.assertIn('<svg', page)
        self.assertNotIn('http://', page.replace('http://www.w3.org', ''))
        self.assertNotIn('https://', page)
        self.assertIn('Not financial advice', page)


class TeamTest(unittest.TestCase):
    def test_team_review_of_the_sample_team(self):
        team = rt.team_review(os.path.join(h.DATA, 'team'))
        names = [m['name'] for m in team['members']]
        self.assertEqual(names, ['kasia', 'priya', 'tom'])
        by = {m['name']: m for m in team['members']}
        self.assertGreater(by['priya']['stats']['net'], 0)
        self.assertLess(by['kasia']['stats']['net'], 0)
        self.assertLess(by['priya']['breachTotal'], by['tom']['breachTotal'])
        self.assertIsNotNone(by['priya']['stats']['sharpe'])
        self.assertEqual(team['week'], rt.from_iso('2026-11-23'))
        rows = list(csv.reader(io.StringIO(rt.team_csv(team).lstrip('\ufeff'))))
        self.assertEqual(rows[0][0], 'Member')
        self.assertEqual(len(rows), 4)

    def test_flat_folder_of_one_export_per_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(os.path.join(h.DATA, 'team', 'tom', 'fills.csv'), os.path.join(tmp, 'tom-fills.csv'))
            with open(os.path.join(tmp, 'broken.csv'), 'w', encoding='utf-8') as fh:
                fh.write('nothing useful\n')
            team = rt.team_review(tmp, default_start='100000')
            self.assertEqual([m['name'] for m in team['members']], ['Broken', 'Tom fills'])
            self.assertTrue(any('broken.csv' in p for p in team['problems']))


class WeeklyJobTest(unittest.TestCase):
    def test_merge_archive_and_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox, out, archive = os.path.join(tmp, 'inbox'), os.path.join(tmp, 'reviews'), os.path.join(tmp, 'archive')
            journal = os.path.join(tmp, 'journal.json')
            os.makedirs(inbox)
            shutil.copy(os.path.join(h.DATA, 'weekly', 'export-2026-11-20.csv'), inbox)
            first = rt.weekly_job(journal, inbox, out, archive=archive, settings_path=os.path.join(h.DATA, 'sample-journal.json'))
            self.assertEqual(first['added'], 489)
            self.assertEqual(rt.to_iso(first['week']), '2026-11-16')
            self.assertEqual(os.listdir(inbox), [])
            shutil.copy(os.path.join(h.DATA, 'weekly', 'export-2026-11-27.csv'), inbox)
            second = rt.weekly_job(journal, inbox, out, archive=archive)
            self.assertEqual(second['added'], 35)
            self.assertEqual(second['newlyClosed'], 11)
            self.assertTrue(os.path.exists(journal + '.bak'))
            dated = os.path.join(out, 'review-2026-11-23')
            self.assertEqual(sorted(os.listdir(dated)), ['breaches-week.csv', 'days.csv', 'fills.csv', 'review.html', 'review.txt', 'round-trips-all.csv', 'round-trips-week.csv'])
            shutil.copy(os.path.join(h.DATA, 'weekly', 'export-2026-11-27.csv'), os.path.join(inbox, 'again.csv'))
            third = rt.weekly_job(journal, inbox, out)
            self.assertEqual(third['added'], 0)
            with open(journal, encoding='utf-8') as fh:
                st = rt.read_project(fh.read())['state']
            self.assertEqual(len(st['fills']), 524)
            self.assertEqual(st['settings']['multipliers'][0]['symbol'], 'LKF')


class CommandLineTest(unittest.TestCase):
    def test_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = [os.path.join(h.DATA, n) for n in h.SAMPLES]
            code, out = run_cli('trades', *files, '--journal', os.path.join(h.DATA, 'sample-journal.json'), '--out', tmp)
            self.assertEqual(code, 0, out)
            self.assertIn('237 trades closed', out)
            with open(os.path.join(tmp, 'round-trips.csv'), encoding='utf-8-sig') as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 238)
            self.assertEqual(rows[0]['Account'], 'KES-EQ-0417')
            html_path = os.path.join(tmp, 'review.html')
            code, out = run_cli('review', *files, '--journal', os.path.join(h.DATA, 'sample-journal.json'), '--week', '2026-11-25', '--html', html_path)
            self.assertEqual(code, 0, out)
            self.assertIn('Net after fees: +$1,595.71 from 21 closed trades', out)
            self.assertTrue(os.path.exists(html_path))
            code, out = run_cli('size', '--equity', '100000', '--risk', '1', '--entry', '41.20', '--stop', '40.85', '--fee', '0.01')
            self.assertIn('Buy 2,777', out)
            code, out = run_cli('check', os.path.join(h.DATA, 'futures-messy.csv'))
            self.assertIn('repeated header row', out)
            code, out = run_cli('template', '--out', os.path.join(tmp, 't.csv'))
            with open(os.path.join(tmp, 't.csv'), encoding='utf-8', newline='') as fh:
                self.assertEqual(fh.read(), rt.template_csv())
            code, out = run_cli('team', os.path.join(h.DATA, 'team'), '--out', os.path.join(tmp, 'team'))
            self.assertEqual(code, 0, out)
            self.assertIn('priya', out)
            period = os.path.join(tmp, 'october.html')
            code, out = run_cli('period', *files, '--journal', os.path.join(h.DATA, 'sample-journal.json'), '--month', '2026-10', '--out', period)
            self.assertEqual(code, 0, out)
            with open(period, encoding='utf-8') as fh:
                page = fh.read()
            self.assertIn('1 Oct 2026 to 31 Oct 2026', page)
            self.assertIn('Week by week', page)
            self.assertIn('If every rule had been kept', page)
            code, out = run_cli('period', *files, '--month', '2026-13')
            self.assertNotEqual(code, 0)
            code, out = run_cli('review', '--week', 'nonsense', *files)
            self.assertNotEqual(code, 0)


class HygieneTest(unittest.TestCase):
    def test_no_em_dashes_in_tracked_files(self):
        proc = subprocess.run(['git', 'ls-files'], cwd=h.ROOT, capture_output=True, text=True)
        if proc.returncode != 0 or not proc.stdout.strip():
            self.skipTest('not a git checkout')
        for name in proc.stdout.split('\n'):
            if not name or name.endswith(('.woff2', '.png')):
                continue
            with open(os.path.join(h.ROOT, name), encoding='utf-8', errors='replace') as fh:
                text = fh.read()
            self.assertNotIn('\u2014', text, name)

    def test_sample_journal_is_valid(self):
        data = json.loads(h.sample_text('sample-journal.json'))
        self.assertEqual(data['app'], 'round-trips')
        self.assertGreater(len(data['journal']), 200)


if __name__ == '__main__':
    unittest.main()
