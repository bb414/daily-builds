"""The browser model (run in Node from app/index.html) and the Python companion must give identical answers.

Every case compares the whole analysis (fills, trades, matches, breaches, statistics, breakdowns, weekly
reviews and their text) and requires the CSV and journal files to be byte for byte the same.
Skipped when Node is not installed.
"""

import os
import random
import subprocess
import sys
import unittest

import helpers as h

HEAD = 'Date,Time,Account,Symbol,Side,Quantity,Price,Commission,Order ID'


def rt_day(iso):
    return h.rt.from_iso(iso)


def fuzz_export(seed, rows=160):
    """A random but valid fills export: several symbols, partial fills, scaling, reversals, odd quantities and prices."""
    rng = random.Random(seed)
    lines = [HEAD]
    sec = 9 * 3600 + 30 * 60
    day = 0
    pos = {}
    for i in range(rows):
        sec += rng.randint(1, 900)
        if sec > 16 * 3600:
            sec = 9 * 3600 + 30 * 60 + rng.randint(0, 600)
            day += 1 + (1 if rng.random() < 0.2 else 0)
        sym = rng.choice(['QX', 'ZYV', 'LKFZ6', 'MLKZ6'])
        acct = rng.choice(['A', 'B'])
        key = acct + sym
        p = pos.get(key, 0)
        if p != 0 and rng.random() < 0.55:
            side = 'Sell' if p > 0 else 'Buy'
            qty = rng.choice([abs(p), max(1, abs(p) // 2), abs(p) + rng.randint(1, 5)])
        else:
            side = rng.choice(['Buy', 'Sell'])
            qty = rng.randint(1, 40)
        if rng.random() < 0.15:
            qty = qty + rng.choice([0.5, 0.25, 0.125])
        pos[key] = p + (qty if side == 'Buy' else -qty)
        price = rng.choice([rng.uniform(5, 300), rng.uniform(4000, 6000)])
        price_text = ('%.' + str(rng.choice([2, 2, 3, 4])) + 'f') % price
        fee = '%.2f' % (rng.random() * 6)
        stamp = 20 + day
        date = '2026-%02d-%02d' % (10 + stamp // 31, stamp % 31 + 1)
        lines.append(','.join([date, '%02d:%02d:%02d' % (sec // 3600, sec // 60 % 60, sec % 60), acct, sym, side, str(qty), price_text, fee, 'o%d' % rng.randint(1, 60)]))
    return '\n'.join(lines) + '\n'


EDGE = {
    'reversal-and-signed.csv': 'Date,Symbol,Quantity,Price,Fees\n2026-11-23,QX,10,5,-1.00\n2026-11-23,QX,-15,6,-1.50\n2026-11-24,QX,5,4,-0.50\n2026-11-24,QX,3,4.5,-0.30\n',
    'semicolon.csv': 'Datum;Zeit;Symbol;Side;Qty;Price;Fee\n23.11.2026;09:00;ABC;Buy;10;12,50;1,00\n23.11.2026;10:00;ABC;Sell;10;13,25;1,00\n',
    'no-times.csv': 'Trade date,Ticker,Action,Shares,Price\n24/11/2026,WMRU,Sell,5,4.20\n23/11/2026,WMRU,Buy,5,4.00\n23/11/2026,CPFB,Buy,10,1.86\n',
    'sectioned.csv': ('Statement,Header,Field Name,Field Value\nStatement,Data,Period,November 2026\n'
                      'Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,Comm/Fee,Code\n'
                      'Trades,Data,Order,Stocks,USD,ZYV,"2026-11-23, 10:01:02",100,20.5,-1,O\n'
                      'Trades,Data,Order,Stocks,USD,ZYV,"2026-11-23, 11:01:02",-100,21.25,-1,C\n'
                      'Trades,SubTotal,,Stocks,USD,ZYV,,0,,-2,\n'),
    'messy-bits.csv': ('Account,Date,Time,Symbol,Side,Qty,Price,Fees,Status,Type\nX,2026-11-23,09:30:00,QX,Buy,5,10,$1.00,Filled,Trade\n'
                       'X,2026-11-23,09:30:01,QX,,,,$0.50,,Commission\nX,2026-11-23,09:31:00,QX,,,,,,Dividend\nX,2026-11-23,09:40:00,QX,Sell,5,9,$1.00,Filled,Trade\n'
                       'X,2026-11-23,09:45:00,QX,Buy,5,abc,$1.00,Filled,Trade\nX,2026-11-23,09:46:00,QX,Buy,5,9,$1.00,Rejected,Trade\nTotal,,,,,10,,$3.50,,\n'),
    'pence.csv': 'Date,Symbol,Buy/Sell,Quantity,Price,Currency,Commission\n2026-11-23 10:00,BRSK,Buy,100,73.4,GBX,5.95\n2026-11-25 11:00,BRSK,Sell,100,80.1,GBX,5.95\n',
}


@unittest.skipIf(h.NODE is None, 'Node is not installed')
class AgreementTest(unittest.TestCase):
    maxDiff = None

    def compare_case(self, case, label):
        js = h.run_bridge({'cases': [case]})['cases'][0]
        py = h.run_case(case)
        for key in ['reports', 'result', 'stats', 'breakdowns', 'weekly', 'histogram', 'reviews', 'days']:
            diff = h.first_difference(h.plain(py[key]), js[key], '$.' + key)
            self.assertIsNone(diff, '%s: %s' % (label, diff))
        for key in ['tradesCsv', 'breachesCsv', 'fillsCsv', 'projectFile']:
            self.assertEqual(py[key], js[key], '%s: %s differs' % (label, key))
        return py

    def test_the_sample(self):
        py = self.compare_case(h.sample_case(), 'sample')
        self.assertEqual(len(py['result']['closed']), 237)
        self.assertEqual(len(py['reviews']), 40)  # ten weeks, for all accounts and each of the three

    def test_the_sample_with_edits_and_other_settings(self):
        case = h.sample_case(edits=[
            {'id': 'KES-EQ-0417|GLBM|2026-11-27T12:41:07', 'fields': {'setup': 'Breakout', 'stop': '10.05', 'risk': '', 'mistakes': ['Oversized'], 'notes': 'Weekend\r\nhold  '}},
            {'id': 'KES-FUT-0233|LKFZ6|2026-11-27T09:37:09', 'fields': {'setup': 'Reversal', 'risk': '300', 'mistakes': [], 'notes': ''}},
        ], settings={'base': 'GBP', 'fx': [{'currency': 'USD', 'rate': '0.79'}],
                     'rules': {'maxRiskPct': {'on': True, 'value': '0.5'}, 'maxDailyLoss': {'on': True, 'value': '900', 'unit': 'money'},
                               'maxTradesPerDay': {'on': True, 'value': '3'}, 'noAddingToLoser': {'on': False}, 'maxLossR': {'on': True, 'value': '1'},
                               'needPlannedRisk': {'on': False}}})
        self.compare_case(case, 'edited sample')

    def test_a_missing_exchange_rate(self):
        case = h.sample_case(settings={'fx': []})
        py = self.compare_case(case, 'no fx')
        self.assertTrue(any(w['kind'] == 'fx' for w in py['result']['warnings']))

    def test_team_members_and_weekly_exports(self):
        for member in ['priya', 'tom', 'kasia']:
            self.compare_case({'project': h.sample_text('team/%s/journal.json' % member), 'files': [{'name': 'fills.csv', 'text': h.sample_text('team/%s/fills.csv' % member)}]}, member)
        self.compare_case({'files': h.sample_files(['weekly/export-2026-11-20.csv', 'weekly/export-2026-11-27.csv', 'weekly/export-2026-11-27.csv'])}, 'weekly')

    def test_edge_cases(self):
        for name, text in EDGE.items():
            self.compare_case({'files': [{'name': name, 'text': text}], 'settings': {'accounts': [{'name': 'No times', 'start': '1000', 'longOnly': True}]}}, name)
        self.compare_case({'files': [{'name': 'template.csv', 'text': h.sample_text('template.csv')}]}, 'template')

    def test_chosen_columns_and_typed_in_openings(self):
        text = 'Exported by desk\nWhen,Code,Way,Lots,At,Charge\n23/11/2026 09:00,QX,B,2,10.00,0.50\n23/11/2026 10:00,QX,S,3,10.40,0.50\n'
        cols = {'date': 'When', 'symbol': 'Code', 'side': 'Way', 'qty': 'Lots', 'price': 'At', 'fees': 'Charge'}
        self.compare_case({'files': [{'name': 'odd.csv', 'text': text, 'columns': cols}, {'name': 'odd2.csv', 'text': text, 'columns': {'date': 'Nope'}},
                                     {'name': 'odd3.csv', 'text': text}]}, 'chosen columns')
        uk = h.sample_case(carry=[{'account': 'Dealing account', 'symbol': 'WMRU', 'side': 'B', 'q': 150000000, 'price': 3950000, 'day': rt_day('2026-09-01'),
                                   'fee': 0, 'currency': 'GBP'}])
        py = self.compare_case(uk, 'carry')
        self.assertEqual(len(py['result']['unmatched']), 0)
        u = {'account': 'X', 'symbol': 'QX', 'side': 'S', 'q': 1000000, 'price': 1, 'day': rt_day('2026-11-23'), 'currency': 'USD'}
        tries = [('2026-01-01', '1.5'), ('2099-01-01', '1'), ('', '1'), ('2026-11-23', 'x')]
        js = h.run_bridge({'carries': [{'u': u, 'date': d, 'price': p} for d, p in tries]})
        self.assertEqual(h.plain([h.rt.make_carry(u, d, p) for d, p in tries]), js['carries'])

    def test_random_exports(self):
        for seed in range(12):
            text = fuzz_export(seed)
            case = {'files': [{'name': 'fuzz%d.csv' % seed, 'text': text}],
                    'settings': {'multipliers': [{'symbol': 'LKF', 'value': '20'}, {'symbol': 'MLKZ6', 'value': '2.5'}],
                                 'accounts': [{'name': 'A', 'start': '25000', 'longOnly': False}, {'name': 'B', 'start': '7500.5', 'longOnly': False}]}}
            self.compare_case(case, 'fuzz %d' % seed)

    def test_the_small_pieces(self):
        job = {
            'numbers': ['$1,234.50', '-$2.04', '(12.345)', '12.34-', 'GBP 5.95', '1 234,5', '412.5p', '0.005', '0.0049999', '-0', '.5', '5.', 'abc', '',
                        '1,23', '1,2345', '9007199254740993', '£1,000,000.999', '\u221212.5', '+3', '€ 7'],
            'dates': ['2026-10-07', '07/10/2026 09:31', '10/07/2026 9:31:04 PM', '2026-10-07, 14:05:00', '20261007;140500', 'Wed 7 Oct 2026 12:00 AM', 'Oct 7, 2026',
                      '7th October 26', '31/02/2026', '2026-10-07T14:05:00.250Z', '13/01/2026', '1/13/26 3:04 pm', '07.10.2026', '2026/10/07 07:05', 'not a date', '0931', '9.31'],
            'sides': ['Buy', 'SLD', 'Sell Short', 'Buy to Cover', 'Bought', 'Market sell', 'Dividend', 'BTC', 'sto', 'B', 's', 'Long', ''],
            'headers': ['Price (p)', 'Order #', 'B/S', 'T. Price', 'Comm/Fee', 'Time (ET)', '  Filled Qty  '],
            'roots': ['LKFZ6', 'LKF Z26', 'LKF DEC26', 'HGRB', 'ESZ6', '6EZ6', 'Z6'],
            'accountNames': ['trade-history-2026-11-27.csv', '2026-11-27.csv', 'fills_wk47.txt', 'KES export.CSV'],
            'projects': [h.sample_text('sample-journal.json'), 'not json', '{"app":"round-trips","fills":[{"key":"k","day":1,"side":"X","q":1,"price":1}]}'],
            'sizing': [{'equity': '100000', 'riskPct': '1', 'entry': '41.20', 'stop': '40.85', 'fee': '0.01'},
                       {'equity': '50000', 'riskPct': '1', 'entry': '5112.25', 'stop': '5120.25', 'mult': '20', 'allowance': '250'},
                       {'equity': '1000', 'riskPct': '0.5', 'entry': '1.2345', 'stop': '1.2001', 'step': '0.1', 'currency': 'GBP'},
                       {'equity': '1000', 'riskPct': '1', 'entry': '100', 'stop': '50'}, {'equity': '', 'riskPct': '1', 'entry': '1', 'stop': '2'}],
            'delimited': ['a,"b, c","say ""hi"""\r\n1,"two\nlines",3', 'x;y\n1;2\n', '"unterminated,1\n2,3', ''],
            'formats': [0, 5, -5, 123456, -9999999, 50, 150, 2500, 99999999],
            'exports': [{'name': n, 'text': t} for n, t in EDGE.items()],
        }
        js = h.run_bridge(job)
        py = {
            'numbers': [{'read': h.rt.read_number(s, False), 'comma': h.rt.read_number(s, True), 'cents': h.rt.parse_cents(s), 'micro': h.rt.parse_micro(s),
                         'float': h.rt.parse_float_text(s)} for s in job['numbers']],
            'dates': [{'shape': h.rt.date_shape(s), 'dmy': h.rt.parse_date_time(s, 'DMY'), 'mdy': h.rt.parse_date_time(s, 'MDY'), 'time': h.rt.parse_time(s)} for s in job['dates']],
            'dateOrder': h.rt.detect_date_order(job['dates']),
            'sides': [h.rt.classify_side(s) for s in job['sides']],
            'headers': [h.rt.norm_header(s) for s in job['headers']],
            'roots': [h.rt.symbol_root(s) for s in job['roots']],
            'accountNames': [h.rt.clean_account_name(s) for s in job['accountNames']],
            'projects': [h.rt.read_project(t) for t in job['projects']],
            'sizing': [h.rt.position_size(s) for s in job['sizing']],
            'delimited': [{'delim': h.rt.sniff_delimiter(t), 'parsed': h.rt.parse_delimited(t, h.rt.sniff_delimiter(t))} for t in job['delimited']],
            'formats': [{'money': h.rt.money(x, 'USD'), 'sign': h.rt.money(x, 'GBP', sign=True), 'whole': h.rt.money(x, 'EUR', whole=True), 'num': h.rt.fmt_num(x / 7, 2),
                         'pct': h.rt.fmt_pct(x / 100000, 1), 'r': h.rt.fmt_r(x / 1000), 'price': h.rt.fmt_price(x * 1000), 'qty': h.rt.fmt_qty(x * 10000),
                         'dur': h.rt.fmt_duration(abs(x)), 'date': h.rt.fmt_date(20000 + abs(x) % 3000)} for x in job['formats']],
            'exports': [h.rt.read_export(e['name'], e['text'], {}) for e in job['exports']],
            'template': h.rt.template_csv(),
        }
        for key in py:
            diff = h.first_difference(h.plain(py[key]), js[key], '$.' + key)
            self.assertIsNone(diff, diff)

    def test_the_built_app_is_current(self):
        proc = subprocess.run([sys.executable, os.path.join(h.ROOT, 'tools', 'build_app.py'), '--check'], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == '__main__':
    unittest.main()
