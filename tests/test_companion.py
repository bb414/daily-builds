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

EVERYDAY = ['BEAN AND BARLEY', 'GREENGATE SUPERMARKET', 'TOWNHOP BUSES', 'NOODLE NOOK TAKEAWAY', 'CASH WITHDRAWAL',
            'RAILWAY TICKETS ONLINE', 'TO SPENDING APP', 'PARCELWREN MKTPLACE', 'NORTHLINE RAIL', 'PAGEFOLD BOOKS',
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

    def test_scan_writes_six_files_that_read_back(self):
        out = self.path('out')
        proc = self.run_cli('scan', DATA, '--out', out, '--as-of', '2026-11-28')
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        printed = proc.stdout.decode('utf-8')
        self.assertIn('Harbour Lettings Rent', printed)
        self.assertIn('Line 26: Could not read the date "32/10/2026"', printed)
        self.assertIn('template.csv was left out', printed)
        self.assertTrue(all(len(line) <= 100 for line in printed.splitlines() if out not in line))
        self.assertEqual(sorted(os.listdir(out)), ['budget-12-months.csv', 'regular-payments.csv', 'report.html',
                                                   'review.json', 'still-paying.xlsx', 'upcoming.ics'])
        register = list(csv.reader(io.StringIO(self.read('out', 'regular-payments.csv').lstrip('\ufeff'))))
        self.assertEqual(register[0][:4], ['Name', 'Category', 'Paid by', 'How often'])
        self.assertEqual(len(register), 25)  # 22 from the student plus council tax and water from the QIF; with the header
        budget = list(csv.reader(io.StringIO(self.read('out', 'budget-12-months.csv').lstrip('\ufeff'))))
        self.assertEqual(budget[0][1], 'Dec 2026')  # the review is on 28 Nov, so the budget starts with December
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
        self.assertEqual(len(review['transactions']), 703)  # 652 from the CSVs, 23 from the OFX and 28 from the QIF
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
                                                       'report-2026-11-01.html', 'review-2026-11-01.json',
                                                   'workbook-2026-11-01.xlsx'])
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
        self.assertEqual(rows[0], ['Category', 'Dec 2026', 'Jan 2027', 'Feb 2027', 'Total'])
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



class RunwayTest(unittest.TestCase):
    """Will the money last? The balance walk and its command."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_balances_come_from_the_exports(self):
        a = sp.analyse(sample_files(['current-account.csv', 'savings-account.ofx']))
        closing = {acc['account']: acc['closing'] for acc in a['merged']['accounts']}
        self.assertEqual(closing['Current account'], {'day': sp.from_iso('2026-11-27'), 'balance': 54499})
        self.assertEqual(sp.iso(closing['Savings account']['day']), '2026-11-27')
        self.assertGreater(closing['Savings account']['balance'], 0)
        self.assertEqual(a['result']['everyday']['Current account']['days'], 91)

    def test_walk_counts_every_payment_and_one_off_money_in(self):
        a = sp.analyse(sample_files(['current-account.csv']))
        r = a['result']
        rw = sp.runway(r, {}, {'account': 'Current account', 'balance': 100000, 'everyday': 1000, 'days': 30})
        out = sum(it['amount'] for it in sp.forecast(r, 30, {}) if it['direction'] == 'out')
        income = sum(it['amount'] for it in sp.forecast(r, 30, {}) if it['direction'] == 'in')
        self.assertEqual(rw['days'][-1]['balance'], 100000 - out + income - 30 * 1000)
        self.assertEqual(sp.iso(rw['nextIn']['day']), '2026-12-24')
        boosted = sp.runway(r, {}, {'account': 'Current account', 'balance': 100000, 'everyday': 1000, 'days': 30,
                                    'extraIn': [{'day': r['asOf'] + 3, 'amount': 50000, 'name': 'Refund'}]})
        self.assertEqual(boosted['days'][-1]['balance'], rw['days'][-1]['balance'] + 50000)
        self.assertEqual(boosted['nextIn']['name'], 'Campus Cafe Payroll', 'a one-off does not replace payday')

    def test_runway_command(self):
        out = os.path.join(self.tmp.name, 'runway.csv')
        code = subprocess.run([sys.executable, os.path.join(COMPANION, 'still_paying.py'), 'runway', DATA,
                               '--account', 'Current account', '--overdraft', '1000',
                               '--extra', '2027-01-12:3514.67:Loan', '--out', out],
                              capture_output=True, text=True)
        self.assertEqual(code.returncode, 0, code.stderr)
        self.assertIn('goes past the limit', code.stdout)
        with open(out, encoding='utf-8-sig') as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], ['Date', 'Balance', 'Change', 'Payments and money in'])
        self.assertEqual(len(rows), 61)
        self.assertTrue(any('+3514.67 Loan' in r[3] for r in rows))
        bad = subprocess.run([sys.executable, os.path.join(COMPANION, 'still_paying.py'), 'runway', DATA,
                              '--extra', 'tomorrow:lots'], capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn('YYYY-MM-DD:AMOUNT:NAME', bad.stderr)


class AddedByHandTest(unittest.TestCase):
    """Payments added by hand and schedules set by hand travel in the saved review."""

    def test_scan_carries_a_hand_added_payment_from_the_review(self):
        a = sp.analyse(sample_files(['current-account.csv']))
        added = [{'id': 'added~railcard', 'name': 'Railcard', 'amount': 3500, 'cadence': 'yearly',
                  'next': sp.from_iso('2027-02-03'), 'method': 'card', 'category': 'transport', 'account': ''}]
        text = sp.project_file({'transactions': a['merged']['transactions'], 'result': a['result'], 'decisions': {},
                                'accounts': a['merged']['accounts'], 'added': added,
                                'overrides': {'CAMPUS BIKE HIRE~four-weekly~1': {'cadence': 'monthly'}}})
        with tempfile.TemporaryDirectory() as tmp:
            review = os.path.join(tmp, 'review.json')
            with open(review, 'w', encoding='utf-8') as f:
                f.write(text)
            out = os.path.join(tmp, 'out')
            run = subprocess.run([sys.executable, os.path.join(COMPANION, 'still_paying.py'), 'scan', '--quiet',
                                  '--review', review, '--out', out], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            with open(os.path.join(out, 'regular-payments.csv'), encoding='utf-8-sig') as f:
                rows = {r['Name']: r for r in csv.DictReader(f)}
        self.assertEqual(rows['Railcard']['Next due'], '2027-02-03')
        self.assertEqual(rows['Railcard']['Yearly cost'], '35.00')
        self.assertEqual(rows['Campus Bike Hire']['How often'], 'Monthly')


class WorkbookTest(unittest.TestCase):
    """The .xlsx workbook opens in spreadsheet software and its formulas give the plan's totals."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        a = sp.analyse(sample_files(SAMPLES + ['savings-account.ofx']))
        r = a['result']
        ids = {s['name']: s['id'] for s in r['series']}
        cls.decisions = {ids['Ironworks Gym']: {'decision': 'cancel'}, ids['Savings Transfer']: {'decision': 'ignore'}}
        cls.plan = sp.plan(r, cls.decisions)
        book = sp.build_xlsx(r, cls.decisions, {'transactions': a['merged']['transactions'], 'accounts': a['merged']['accounts']})
        cls.path = os.path.join(cls.tmp.name, 'review.xlsx')
        with open(cls.path, 'wb') as f:
            f.write(book['bytes'])
        cls.book, cls.result = book, r

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_is_a_valid_zip_of_xml_parts(self):
        import zipfile
        import xml.dom.minidom
        with zipfile.ZipFile(self.path) as z:
            self.assertIsNone(z.testzip())
            names = z.namelist()
            self.assertIn('xl/workbook.xml', names)
            for n in names:
                xml.dom.minidom.parseString(z.read(n))
        self.assertEqual(self.book['sheets'], ['Regular payments', 'Next 12 months', 'Calendar', 'Transactions',
                                               'Balance day by day'])

    def test_opens_in_openpyxl_with_typed_cells(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest('openpyxl is not installed')
        wb = openpyxl.load_workbook(self.path)
        ws = wb['Regular payments']
        self.assertEqual(ws['A1'].value, 'Name')
        self.assertEqual(ws['E2'].value, 525)
        self.assertEqual(ws['E2'].number_format, '"\N{POUND SIGN}"#,##0.00;[Red]\\-"\N{POUND SIGN}"#,##0.00')
        self.assertEqual(ws['K2'].value.date().isoformat(), '2026-12-01')
        self.assertTrue(str(ws.cell(row=len(self.result['series']) + 3, column=6).value).startswith('=SUMIF('))
        self.assertEqual(wb['Balance day by day']['D6'].value, '=D5+B6+C6')

    def test_libreoffice_calculates_the_same_totals(self):
        soffice = shutil.which('soffice') or shutil.which('libreoffice')
        if not soffice:
            self.skipTest('LibreOffice is not installed')
        out = os.path.join(self.tmp.name, 'csv')
        subprocess.run([soffice, '--headless', '--convert-to', 'csv:Text - txt - csv (StarCalc):44,34,76,1,,0,false,true,false,false,false,-1',
                        '--outdir', out, self.path], capture_output=True, timeout=180)
        with open(os.path.join(out, 'review-Regular payments.csv'), encoding='utf-8') as f:
            rows = list(csv.reader(f))
        committed = next(r for r in rows if r[0].startswith('Committed'))
        cancel = next(r for r in rows if r[0] == 'Marked to cancel')
        self.assertEqual(round(float(committed[5]) * 100), self.plan['totals']['monthly'])
        self.assertEqual(round(float(cancel[6]) * 100), self.plan['totals']['cancelAnnual'])
        with open(os.path.join(out, 'review-Balance day by day.csv'), encoding='utf-8') as f:
            walk = list(csv.reader(f))
        rw = sp.runway(self.result, self.decisions, {'account': 'Current account', 'balance': 54499,
                                                     'everyday': self.result['everyday']['Current account']['perDay'],
                                                     'days': 60, 'leaveOutCancelled': True})
        self.assertEqual(round(float(walk[-1][3]) * 100), rw['days'][-1]['balance'])


class AppReviewNameTest(unittest.TestCase):
    """The monthly job finds a review saved from the browser app as well as its own."""

    def test_both_names_are_found(self):
        from stillpaying.cli import find_reviews
        with tempfile.TemporaryDirectory() as tmp:
            for name in ['review-2026-10-01.json', 'still-paying-review-2026-11-28.json', 'notes.json']:
                with open(os.path.join(tmp, name), 'w', encoding='utf-8') as f:
                    f.write('{}')
            self.assertEqual([n for _, n in find_reviews(tmp)],
                             ['review-2026-10-01.json', 'still-paying-review-2026-11-28.json'])

if __name__ == '__main__':
    unittest.main()
