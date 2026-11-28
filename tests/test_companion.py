"""Unit tests of the Python companion on its own: dates, amounts, parsing, detection and the command line."""

import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from helpers import COMPANION, DATA, NODE, ROOT, SAMPLES, run_bridge, sample_files, sample_text, sp, truncate

EVERYDAY = ['BEAN AND BARLEY', 'GREENGATE SUPERMARKET', 'CITYLINK BUSES', 'NOODLE NOOK TAKEAWAY', 'CASH WITHDRAWAL',
            'RAILWAY TICKETS ONLINE', 'TO SPENDING APP', 'PARCELPOINT MKTPLACE', 'NORTHLINE RAIL', 'PAGEFOLD BOOKS',
            'THREADWORK CLOTHING', 'SKYLARK HOSTELS', 'CORNER DELI', 'THE RUSTY KETTLE', 'CAMPUS UNION SHOP',
            'FOLD & PRESS PRINTING', 'TOP UP FROM CURRENT ACCOUNT', 'MAINTENANCE LOAN INSTALMENT',
            'PAYMENT RECEIVED - THANK YOU']


def days(*isos):
    """Day numbers for YYYY-MM-DD dates."""
    return [sp.from_iso(d) for d in isos]


class DatesTest(unittest.TestCase):
    """Day numbers, month arithmetic and bank holidays."""

    def test_day_numbers(self):
        self.assertEqual(sp.day_from_ymd(1970, 1, 1), 0)
        self.assertEqual(sp.iso(20785), '2026-11-28')
        self.assertEqual(sp.from_iso('2026-11-28'), 20785)
        self.assertIsNone(sp.from_iso('2026-02-29'))
        self.assertIsNone(sp.from_iso('28/11/2026'))
        self.assertEqual(sp.long_date(20785), '28 Nov 2026')
        self.assertEqual(sp.short_date(20785), '28 Nov')

    def test_bank_holidays_2026(self):
        self.assertEqual(sp.bank_holidays(2026), days('2026-01-01', '2026-04-03', '2026-04-06', '2026-05-04',
                                                      '2026-05-25', '2026-08-31', '2026-12-25', '2026-12-28'))

    def test_bank_holidays_2027_with_christmas_substitutes(self):
        # Christmas Day 2027 is a Saturday, so both holidays move to the Monday and Tuesday.
        self.assertEqual(sp.bank_holidays(2027), days('2027-01-01', '2027-03-26', '2027-03-29', '2027-05-03',
                                                      '2027-05-31', '2027-08-30', '2027-12-27', '2027-12-28'))

    def test_one_off_changes(self):
        self.assertIn(sp.from_iso('2022-09-19'), sp.bank_holidays(2022))
        self.assertNotIn(sp.from_iso('2022-05-30'), sp.bank_holidays(2022))
        self.assertIn(sp.from_iso('2023-05-08'), sp.bank_holidays(2023))

    def test_working_days(self):
        self.assertFalse(sp.is_working_day(sp.from_iso('2026-12-28')))
        self.assertEqual(sp.next_working_day(sp.from_iso('2026-12-25')), sp.from_iso('2026-12-29'))
        self.assertEqual(sp.next_working_day(sp.from_iso('2026-11-27')), sp.from_iso('2026-11-27'))

    def test_nominal_in_month(self):
        self.assertEqual(sp.iso(sp.nominal_in_month(2026, 2, 31)), '2026-02-28')
        self.assertEqual(sp.iso(sp.nominal_in_month(2028, 2, 31)), '2028-02-29')
        # The last working day of August 2026 is Friday 28th: Monday 31st is a bank holiday.
        self.assertEqual(sp.iso(sp.nominal_in_month(2026, 8, 'LW')), '2026-08-28')
        # The last Friday of December 2026 is Christmas Day, so payroll moves back to the Thursday.
        self.assertEqual(sp.iso(sp.nominal_in_month(2026, 12, 'L5')), '2026-12-24')

    def test_add_months(self):
        jan31 = sp.from_iso('2026-01-31')
        self.assertEqual(sp.iso(sp.add_months(jan31, 1)), '2026-02-28')
        self.assertEqual(sp.iso(sp.add_months(sp.add_months(jan31, 1), 1, 31)), '2026-03-31')
        self.assertEqual(sp.iso(sp.add_months(sp.from_iso('2026-11-15'), 3)), '2027-02-15')
        self.assertEqual(sp.iso(sp.add_months(sp.from_iso('2026-11-15'), -12)), '2025-11-15')


class MoneyTest(unittest.TestCase):
    """Reading and writing amounts."""

    CASES = {
        '-525.00': -52500, '(525.00)': -52500, '18.30 DR': -1830, '18.30 CR': 1830, '\N{POUND SIGN}18.00-': -1800,
        '-\N{POUND SIGN}24.99': -2499, '+18.30': 1830, '1,234.56': 123456, '1.234,56': 123456, '12,5': 1250,
        '.5': 50, '0.005': 1, '0.004': 0, '1,234': 123400, 'DR 5.00': -500, '5 C': 500, 'GBP 12.00': 1200,
        '\N{MINUS SIGN}12.00': -1200, '(-5.00)': 500, 'abc': None, '': None, 'n/a': None, '--5': None, '-5-': None,
        '12,345,67': None, '1.2.3': None, '12.345': 1235, '\N{EURO SIGN}9.99': 999, '-0.00': 0,
    }

    def test_parse_amount(self):
        for raw, pence in self.CASES.items():
            with self.subTest(raw=raw):
                self.assertEqual(sp.parse_amount(raw), pence)

    def test_money_text(self):
        self.assertEqual(sp.money(123456), '\N{POUND SIGN}1,234.56')
        self.assertEqual(sp.money(-5), '-\N{POUND SIGN}0.05')
        self.assertEqual(sp.money(1200, whole=True), '\N{POUND SIGN}12')
        self.assertEqual(sp.plain_money(-320), '-3.20')

    def test_rounding_halves_up(self):
        self.assertEqual(sp.round_half_up(2.5), 3)
        self.assertEqual(sp.round_half_up(-2.5), -2)
        self.assertEqual(sp.round_half_up(0.5), 1)


class ParsingTest(unittest.TestCase):
    """Reading each sample export."""

    def read(self, name):
        """A sample export, parsed."""
        return sp.parse_csv(sample_text(name), name)

    def test_current_account(self):
        st = self.read('current-account.csv')
        self.assertTrue(st['ok'])
        self.assertEqual((st['rowCount'], len(st['transactions']), len(st['skipped'])), (570, 570, 0))
        self.assertEqual(st['account'], 'Current account')
        self.assertEqual(st['layout']['signConvention'], 'negative-out')

    def test_credit_card_with_details_above_the_header(self):
        st = self.read('credit-card.csv')
        self.assertEqual((st['rowCount'], len(st['transactions']), len(st['skipped'])), (33, 33, 0))
        self.assertEqual(st['layout']['headerRow'], 4)
        self.assertEqual(st['layout']['signConvention'], 'columns')
        self.assertEqual(st['transactions'][0]['amount'], -5628)

    def test_spending_app(self):
        st = self.read('spending-app.csv')
        self.assertEqual((st['rowCount'], len(st['transactions']), len(st['skipped'])), (49, 49, 0))
        self.assertEqual(st['account'], 'Spending app')

    def test_messy_export_skips_rows_with_reasons(self):
        st = self.read('messy-export.csv')
        self.assertEqual((st['rowCount'], len(st['transactions']), st['blankRows']), (102, 97, 2))
        self.assertEqual([(k['line'], k['reason']) for k in st['skipped']], [
            (10, 'Could not read the date "TBC"'),
            (21, 'Could not read the amount "n/a"'),
            (26, 'Could not read the date "32/10/2026"'),
            (41, 'A repeated header row'),
            (113, 'A total or balance line, not a payment'),
        ])
        # A quoted line break is folded into the description, and the line numbers still count it.
        by_line = {t['line']: t['desc'] for t in st['transactions']}
        self.assertEqual((by_line[27], by_line[28], by_line[30]), ('BRIGHTSPARK ENERGY', 'BEAN AND BARLEY',
                                                                   'BEAN AND BARLEY'))
        self.assertNotIn(29, by_line)

    def test_file_problems(self):
        self.assertEqual(sp.parse_csv('', 'empty.csv')['error'], 'The file is empty.')
        self.assertTrue(sp.parse_csv('{"a": 1}', 'x.csv')['error'].startswith('This looks like a JSON file'))
        self.assertTrue(sp.parse_csv('%PDF-1.4', 'x.csv')['error'].startswith('This is a PDF'))

    def test_account_names_from_file_names(self):
        self.assertEqual(sp.default_account('messy-export.csv'), 'Messy')
        self.assertEqual(sp.default_account('current-account-2026-11.csv'), 'Current account')
        self.assertEqual(sp.default_account('statement.csv'), 'Account')


class DetectionTest(unittest.TestCase):
    """Detection against the planted payments in data/sample-truth.json."""

    @classmethod
    def setUpClass(cls):
        """Analyse the four samples together once."""
        with open(os.path.join(DATA, 'sample-truth.json'), encoding='utf-8') as fh:
            cls.truth = json.load(fh)
        cls.analysis = sp.analyse(sample_files())
        cls.result = cls.analysis['result']

    def find(self, planted):
        """The one series that matches a planted payment."""
        found = [s for s in self.result['series'] if s['name'] == planted['name']
                 and ('typical' not in planted or s['typical'] == planted['typical'])]
        self.assertEqual(len(found), 1, 'expected one series for %s' % planted)
        return found[0]

    def test_every_planted_series_is_found(self):
        for planted in self.truth['series']:
            with self.subTest(planted['name'], typical=planted.get('typical')):
                s = self.find(planted)
                self.assertEqual(s['cadence'], planted['cadence'])
                self.assertEqual(s['amounts']['kind'], planted['kind'])
                self.assertEqual(s['category'], planted['category'])
                self.assertEqual(s['count'], planted['count'])
                self.assertEqual(s['account'], planted['account'])
                self.assertEqual({f['id'] for f in s['flags']} - {'stopped'}, set(planted.get('flags', [])))
                self.assertEqual(s['status'], planted.get('status', 'active'))

    def test_every_planted_candidate_is_found(self):
        for planted in self.truth['candidates']:
            with self.subTest(planted['name']):
                found = [c for c in self.result['candidates'] if c['name'] == planted['name']]
                self.assertEqual(len(found), 1)
                self.assertEqual((found[0]['amount'], found[0]['cadence']), (planted['amount'], planted['cadence']))

    def test_income_is_found(self):
        for planted in self.truth['income']:
            found = [s for s in self.result['income'] if s['name'] == planted['name']]
            self.assertEqual([s['cadence'] for s in found], [planted['cadence']])
        self.assertEqual(sp.iso(self.result['payday']['next']), '2026-12-24')

    def test_nothing_found_among_everyday_spending(self):
        keys = [s['key'] for s in self.result['series']] + [c['key'] for c in self.result['candidates']]
        for key in keys:
            self.assertFalse(any(key.startswith(word) or word.startswith(key) for word in EVERYDAY), key)
        extra = [s['name'] for s in self.result['series']
                 if not any(s['name'] == p['name'] for p in self.truth['series'])]
        self.assertEqual(extra, ['Student Card Repayment'])

    def test_re_export_is_linked_and_counted_once(self):
        linked = self.analysis['merged']['linked']
        self.assertEqual([(n['file'], n['account'], n['share']) for n in linked],
                         [('messy-export.csv', 'Current account', 100)])
        self.assertEqual(self.analysis['merged']['duplicates'], 97)


class PaydayTest(unittest.TestCase):
    """The next payday steps on from nominal dates, so a month-end payment rolled into the next month is not skipped."""

    def test_rolled_month_end_payment(self):
        rows = ['Date,Description,Type,Amount']
        for day in ['30/06/2026', '31/07/2026', '01/09/2026', '30/09/2026']:
            rows.append(day + ',ALLOWANCE FROM HOME,Standing order,200.00')
        rows += ['%02d/09/2026,CORNER SHOP,Card payment,-3.00' % d for d in (3, 9, 15, 21)]
        analysis = sp.analyse([{'name': 'allowance.csv', 'text': '\n'.join(rows)}], as_of=sp.from_iso('2026-11-10'))
        result = analysis['result']
        self.assertEqual(result['income'][0]['anchor'], 31)
        # October's payment (31 Oct, a Saturday) is due on Monday 2 November, so the next one after
        # the review date is 30 November, not 31 December.
        self.assertEqual(sp.iso(result['payday']['next']), '2026-11-30')
        first_in = [it for it in sp.forecast(result, 60) if it['direction'] == 'in' and not it['late']][0]
        self.assertEqual(first_in['day'], result['payday']['next'])


class SavedReviewTest(unittest.TestCase):
    """Saving and reopening a review."""

    def test_round_trip_keeps_choices(self):
        a = sp.analyse(sample_files())
        decisions = {'IRONWORKS GYM~monthly~1': {'decision': 'cancel', 'decidedOn': 20785, 'noticeDays': 4}}
        text = sp.project_file({'transactions': a['merged']['transactions'], 'result': a['result'],
                                'decisions': decisions, 'accounts': a['merged']['accounts'],
                                'aliases': {'A': 'B'}, 'names': {'X': 'Y'}, 'manual': [{'id': 'Z'}],
                                'overrides': {'IRONWORKS GYM~monthly~1': {'category': 'memberships'}}})
        back = sp.read_project(text)
        self.assertEqual(back['reviewedOn'], a['result']['asOf'])
        self.assertEqual(len(back['transactions']), len(a['merged']['transactions']))
        self.assertEqual(back['decisions']['IRONWORKS GYM~monthly~1'],
                         {'decision': 'cancel', 'note': '', 'decidedOn': 20785, 'noticeDays': 4})
        self.assertEqual(back['overrides'], {'IRONWORKS GYM~monthly~1': {'category': 'memberships'}})
        self.assertEqual((back['aliases'], back['names'], back['manual']), ({'A': 'B'}, {'X': 'Y'}, [{'id': 'Z'}]))

    def test_not_a_review(self):
        self.assertIn('error', sp.read_project('not json'))
        self.assertIn('error', sp.read_project('{"format": "something else"}'))


class CommandLineTest(unittest.TestCase):
    """The commands, run the way a person would run them."""

    def setUp(self):
        """A fresh temporary folder for each test's files."""
        self.tmp = tempfile.mkdtemp(prefix='still-paying-test-')

    def tearDown(self):
        """Remove the temporary folder."""
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        """Run the command line entry point and return the finished process."""
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
        return subprocess.run([sys.executable, os.path.join(COMPANION, 'still_paying.py')] + list(args), cwd=ROOT,
                              capture_output=True, env=env)

    def path(self, *parts):
        """A path inside the temporary folder."""
        return os.path.join(self.tmp, *parts)

    def read(self, *parts):
        """The text of a file in the temporary folder, line ends untouched."""
        with open(self.path(*parts), encoding='utf-8', newline='') as fh:
            return fh.read()

    def test_scan_writes_five_files_that_read_back(self):
        out = self.path('out')
        proc = self.run_cli('scan', DATA, '--out', out, '--as-of', '2026-11-28')
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        printed = proc.stdout.decode('utf-8')
        self.assertIn('Harbour Lettings Rent', printed)
        self.assertIn('Line 26: Could not read the date "32/10/2026"', printed)
        self.assertIn('template.csv was left out', printed)
        self.assertTrue(all(len(line) <= 100 for line in printed.splitlines() if out not in line))
        self.assertEqual(sorted(os.listdir(out)), ['budget-12-months.csv', 'regular-payments.csv', 'report.html',
                                                   'review.json', 'upcoming.ics'])
        register = list(csv.reader(io.StringIO(self.read('out', 'regular-payments.csv').lstrip('\ufeff'))))
        self.assertEqual(register[0][:4], ['Name', 'Category', 'Paid by', 'How often'])
        self.assertEqual(len(register), 23)
        budget = list(csv.reader(io.StringIO(self.read('out', 'budget-12-months.csv').lstrip('\ufeff'))))
        self.assertEqual(budget[0][1], 'Nov 2026')
        self.assertEqual(budget[-1][0], 'Total')
        self.assertEqual(len(budget[0]), 14)
        ics = self.read('out', 'upcoming.ics')
        lines = ics.split('\r\n')
        self.assertEqual(lines[-1], '')
        self.assertTrue(all(len(line.encode('utf-8')) <= 75 for line in lines))
        for kind in ('VCALENDAR', 'VEVENT', 'VALARM'):
            self.assertEqual(lines.count('BEGIN:' + kind), lines.count('END:' + kind), kind)
        self.assertGreater(lines.count('BEGIN:VEVENT'), 40)
        review_text = self.read('out', 'review.json')
        review = sp.read_project(review_text)
        self.assertNotIn('error', review)
        self.assertEqual(sp.iso(review['reviewedOn']), '2026-11-28')
        self.assertEqual(len(review['transactions']), 652)
        report = self.read('out', 'report.html')
        self.assertIn('Files read', report)
        self.assertNotIn('<script', report)
        if NODE:
            self.assertEqual(run_bridge({'projects': [review_text]})['projects'][0], json.loads(json.dumps(review)))

    def test_scan_carries_a_saved_review(self):
        first = self.path('first')
        self.assertEqual(self.run_cli('scan', DATA, '--out', first, '--quiet').returncode, 0)
        with open(os.path.join(first, 'review.json'), encoding='utf-8') as fh:
            saved = json.load(fh)
        saved['decisions'] = {'IRONWORKS GYM~monthly~1': {'decision': 'cancel', 'decidedOn': '2026-11-28'}}
        saved['names'] = {'TUNEWAVE MUSIC~monthly~1': 'Tunewave family plan'}
        with open(os.path.join(first, 'review.json'), 'w', encoding='utf-8') as fh:
            json.dump(saved, fh)
        second = self.path('second')
        proc = self.run_cli('scan', os.path.join(DATA, 'current-account.csv'), '--review',
                            os.path.join(first, 'review.json'), '--out', second, '--quiet')
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertEqual(proc.stdout, b'')
        register = self.read('second', 'regular-payments.csv')
        self.assertIn('Tunewave family plan', register)
        self.assertIn(',Cancel,', register)
        self.assertIn('Streamcrate.tv', register, 'payments kept from the saved review')

    def test_monthly_twice(self):
        october, november, history = self.path('october'), self.path('november'), self.path('history')
        os.makedirs(october)
        os.makedirs(november)
        last = sp.from_iso('2026-10-31')
        for name in SAMPLES:
            text = sample_text(name)
            with open(os.path.join(november, name), 'w', encoding='utf-8', newline='') as fh:
                fh.write(text)
            if name != 'messy-export.csv':
                with open(os.path.join(october, name), 'w', encoding='utf-8', newline='') as fh:
                    fh.write(truncate(text, last))

        proc = self.run_cli('monthly', october, '--history', history, '--as-of', '2026-11-01')
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertIn('this is the first one', proc.stdout.decode('utf-8'))
        self.assertEqual(sorted(os.listdir(history)), ['changes-2026-11-01.md', 'price-history.csv',
                                                       'report-2026-11-01.html', 'review-2026-11-01.json'])
        # Decide in the app: cancel the gym.
        review_path = self.path('history', 'review-2026-11-01.json')
        with open(review_path, encoding='utf-8') as fh:
            saved = json.load(fh)
        saved['decisions'] = {'IRONWORKS GYM~monthly~1': {'decision': 'cancel', 'note': '', 'decidedOn': '2026-10-31',
                                                          'noticeDays': None}}
        with open(review_path, 'w', encoding='utf-8') as fh:
            json.dump(saved, fh, indent=1)

        proc = self.run_cli('monthly', november, '--history', history)
        printed = proc.stdout.decode('utf-8')
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertIn('Last review: review-2026-11-01.json', printed)
        self.assertIn('## Still being charged after you decided to cancel', printed)
        changes = self.read('history', 'changes-2026-11-28.md')
        self.assertIn('Ironworks Gym: \N{POUND SIGN}24.99 on 3 Nov 2026', changes)
        self.assertIn('## Due in the next 31 days', changes)
        self.assertIn('Total: ', changes)
        new_review = sp.read_project(self.read('history', 'review-2026-11-28.json'))
        self.assertEqual(new_review['decisions']['IRONWORKS GYM~monthly~1']['decision'], 'cancel')
        self.assertIn('Since your last review', self.read('history', 'report-2026-11-28.html'))
        history_rows = list(csv.reader(io.StringIO(self.read('history', 'price-history.csv').lstrip('\ufeff'))))
        self.assertEqual(history_rows[0], ['Series id', 'Name', 'Date', 'Amount', 'Change from previous'])
        broadband = [r for r in history_rows if r[0] == 'HILLTOP BROADBAND~monthly~1']
        self.assertEqual(len(broadband), 12)
        self.assertIn(['HILLTOP BROADBAND~monthly~1', 'Hilltop Broadband', '2026-04-20', '26.40', '+2.40'], broadband)

        proc = self.run_cli('monthly', november, '--history', history)
        self.assertIn('from an earlier run for the same date', proc.stdout.decode('utf-8'))
        self.assertIn('## Still being charged', proc.stdout.decode('utf-8'))

    def test_budget_and_template(self):
        proc = self.run_cli('budget', DATA, '--months', '3', '--out', self.path('budget.csv'))
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        rows = list(csv.reader(io.StringIO(self.read('budget.csv').lstrip('\ufeff'))))
        self.assertEqual(rows[0], ['Category', 'Nov 2026', 'Dec 2026', 'Jan 2027', 'Total'])
        to_screen = self.run_cli('budget', os.path.join(DATA, 'current-account.csv'))
        self.assertTrue(to_screen.stdout.decode('utf-8').startswith('\ufeffCategory,'))
        proc = self.run_cli('template', '--out', self.path('template.csv'))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.read('template.csv'), sp.template_csv())
        self.assertEqual(self.run_cli('template').stdout.decode('utf-8'), sp.template_csv())

    def test_nothing_readable_exits_with_2(self):
        folder = self.path('empty-exports')
        os.makedirs(folder)
        open(os.path.join(folder, 'statement.csv'), 'w').close()
        proc = self.run_cli('scan', folder, '--out', self.path('out'))
        self.assertEqual(proc.returncode, 2)
        self.assertIn('The file is empty.', proc.stderr.decode('utf-8'))
        self.assertFalse(os.path.exists(self.path('out')))
        self.assertEqual(self.run_cli('budget', folder).returncode, 2)

    def test_bad_options(self):
        self.assertEqual(self.run_cli('scan', DATA, '--as-of', '2026-02-30').returncode, 2)
        self.assertEqual(self.run_cli('budget', DATA, '--months', '0').returncode, 2)
        bad = self.path('bad.json')
        with open(bad, 'w') as fh:
            fh.write('{"format": "nope"}')
        proc = self.run_cli('scan', DATA, '--review', bad, '--out', self.path('out'))
        self.assertEqual(proc.returncode, 2)
        self.assertIn('not a Still paying review', proc.stderr.decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
