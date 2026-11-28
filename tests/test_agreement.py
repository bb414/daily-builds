"""Proves the Python companion and the browser model give exactly the same answers.

Every check runs the same inputs through both: the browser model through
tests/js_bridge.js under node, and the Python package directly. The tests are
skipped, with a message, when node is not installed.
"""

import base64
import unittest

from helpers import NODE, OTHER_FORMATS, SAMPLES, first_difference, plain, run_bridge, sample_files, sample_text, sp, truncate
from stillpaying.outputs import ics_fold
from stillpaying.parsing import map_header

DECISIONS = {
    'HARBOUR LETTINGS RENT~monthly~1': {'decision': 'keep', 'note': 'Fixed until August'},
    'IRONWORKS GYM~monthly~1': {'decision': 'cancel', 'decidedOn': '2026-11-28', 'noticeDays': 5,
                                'note': 'Moving to the "campus" gym, it is cheaper'},
    'LINGOLEAP LANGUAGE~monthly~1': {'decision': 'review'},
    'SAVINGS TRANSFER~monthly~1': {'decision': 'ignore'},
    'STREAMCRATE.TV~monthly~1': {'decision': 'cancel', 'decidedOn': 20785},
}

AMOUNTS = [
    '-525.00', '(525.00)', '18.30 DR', '18.30 CR', '\u00a318.00-', '-\u00a324.99', '+18.30', '1,234.56', '1.234,56',
    '12,5', '12,50', '.5', '0.005', '0.004', '0.015', '1,234', '1,23', '12,345,67', 'DR 5.00', 'CR 5.00', '5.00D',
    '5.00 D', '5 C', '5.00 dr.', '5.00 Cr', 'CR5', '\u00a3 1 234.56', 'GBP 12.00', '12.00 GBP', 'EUR 3,50', '$4.20',
    '\u20ac9.99', '\u221212.00', '12.00\u00a0DR', '--5', '-5-', '(-5.00)', '-(5.00)', '+-5', 'abc', '', '   ', 'n/a',
    '1.2.3', '0', '0.00', '-0.00', '999999999.999', '12.345', '12.3456', '(\u00a31,200.00)', '1 200,50', 'DR', '12e3',
    '\u0663\u0664', '\uff11\uff12', '5.00\n', '\t-3.20\t', '1,2345.00', '(5.00) DR', '5.00 DR CR', '\u2009-7.25\u2009',
    '\ufeff-1.50', '1.', '-.75',
]

DATES = [
    '01/02/2026', '13/02/2026', '02/13/2026', '1/2/26', '31/12/69', '01/01/70', '2026-02-29', '2028-02-29',
    '2026-13-01', '2026-1-5', '2026/01/05', '2026.01.05', '20260105', '20260105123045', '20260105.123',
    '20260105[Europe/London]', '5 Jan 2026', '5th January 2026', '05-Jan-26', '5 Sept 2026', 'January 5, 2026',
    'Jan 5 2026', 'Jan. 5th, 2026', 'Monday, 5 January 2026', 'Mon 05/01/2026', '2026-01-05T10:00:00Z',
    '05/01/2026 10:30', '05.01.2026', '32/10/2026', 'TBC', '', '5 Foo 2026', '1st Mar 26', '29/02/2027',
    '\u0660\u0661/\u0660\u0662/\u0662\u0660\u0662\u0666', '2026-01-05\n', 'Tue, 6 Jan 2026', '6 JAN 2026',
    '12/12/2026', '2026-01-05\u00a0', '5 janvier 2026', '1899-12-31', '2201-01-01', '7 March, 2026',
]

DESCRIPTIONS = [
    'CARD PAYMENT TO IRONWORKS GYM ON 03 DEC', 'PARCELPOINT PRIME*WLCQG', 'PARCELPOINT MKTPLACE*AB2CD',
    'PAYPAL *SPOTIFY', 'PP*NETFLIX.COM', 'SQ *CORNER CAFE', 'GOOGLE *YouTube Premium', 'AMZN Mktp UK*2X3Y4Z',
    'DIRECT DEBIT PAYMENT TO BRITISH GAS REF 12345678', 'STANDING ORDER TO J SMITH RENT', 'TFR TO SAVINGS ACCOUNT',
    'FASTER PAYMENT TO MR A BLOGGS', 'SAVINGS TRANSFER', 'Top up from current account', 'APPHAVEN.COM/BILL',
    'STREAMCRATE.TV LONDON GB', 'THE DAILY LANTERN DIGITAL', 'Reelhouse+', 'LingoLeap Language',
    'Fold & Press Printing', 'COUNCIL TAX DD', 'OCTOPUS ENERGY 01/12', 'VODAFONE LTD 123456789012',
    'TESCO MOBILE ON 12 JAN 2026', 'NETFLIX.COM 866-579-7172', 'SPOTIFY P1A2B3C4D5', 'AUDIBLE UK*AB1CD2EF3',
    'MICROSOFT*MICROSOFT 365 P', 'APPLE.COM/BILL ITUNES.COM', 'CONTACTLESS PAYMENT PRET A MANGER 12:34',
    'VIS AMAZON PRIME 14JAN', 'DD O2 MOBILE', 'BGC CAMPUS CAFE PAYROLL', 'NS&I PREMIUM BONDS', 'MONEYBOX SAVER',
    'TV LICENCE MBP', 'RNLI DONATION', 'GOUSTO MEAL KIT', 'XBOX GAME PASS', 'BARBERS ON THE CORNER', 'PUREGYM LTD',
    '(no description)', '', '***', 'Caf\u00e9 Nero', 'CAF\u00c9 NERO \u2013 SOHO', 'O\u2019NEILLS BAR', 'E.ON NEXT',
    'HMRC GOV.UK', '12', 'A', 'MANDATE NO 0034 BRITISH GAS', 'INV 2024-001 HOSTING', 'GBP 12.99 SUBSCRIPTION',
    '\u00a35.99 NOW TV', 'xxxx1234 card', 'STO TO LANDLORD SO', 'POS 1234 TESCO STORES 3381 GBR',
    'ZETTLE_*BEANS & CO', 'HELLOFRESH VIA APPLE PAY', 'FPO JANE DOE - THE HALLS', 'UBER   ONE   MEMBERSHIP',
    'VIRGIN MEDIA PYMTS', 'TO - AND +', 'WWW.EXAMPLE.CO.UK', 'GYM 12:30:15 ON 4/5', '-/.LEADING.AND.TRAILING./-',
]

HEADERS = [
    ['Date', 'Description', 'Amount'],
    ['Transaction Date', 'Transaction Description', 'Debit Amount', 'Credit Amount', 'Balance'],
    ['Date', 'Name', 'Description', 'Amount'],
    ['Date', 'Description', 'Merchant', 'Notes', 'Amount'],
    ['Posting Date', 'Details', 'Paid out (\u00a3)', 'Paid in (\u00a3)'],
    ['Started Date', 'Completed Date', 'Description', 'Amount', 'Fee', 'Currency', 'State', 'Balance'],
    ['Date', 'Counter Party', 'Reference', 'Type', 'Amount (GBP)', 'Balance (GBP)', 'Spending Category', 'Notes'],
    ['Value Date', 'Narrative', 'Debit/Credit', 'Amount', 'Local Amount'],
    ['Update date', 'Date', 'Original amount', 'Amount'],
    ['', ' ', '#', 'Payee #'],
    ['Date', 'Payee', 'Merchant name', 'Memo', 'Description'],
    ['Transaction #', 'Date of transaction', 'Particulars', 'Withdrawals', 'Deposits', 'Running balance'],
]

DELIMITED = [
    {'text': 'a,b,c\r\n1,2,3'}, {'text': '"x, y",z\n"he said ""hi""",2\n'}, {'text': 'a;b;c\n1;2;3\n4;5;6'},
    {'text': 'a\tb\n"multi\nline"\tc\r\nd\te'}, {'text': 'lone\rcr\rendings'}, {'text': '  "spaced",x'},
    {'text': 'ab"cd",e'}, {'text': 'a,b,\n,,\n'}, {'text': '"unterminated,x\ny'}, {'text': ''}, {'text': '\n\n'},
    {'text': 'a|b|c\n1|2|3'}, {'text': '"a;b";c;d\n1;2;3', 'delim': ';'},
]

FOLDS = ['', 'A' * 75, 'A' * 76, 'DESCRIPTION:' + 'x' * 200, '\u00a3' * 40, 'SUMMARY:' + '\U0001F600' * 30,
         'SUMMARY:' + 'caf\u00e9 ' * 30]

ACCOUNT_NAMES = ['current-account.csv', 'messy-export.csv', 'Statement_2026-11-28.csv', 'transactions.csv',
                 'download (3).csv', 'Monzo Export 2026 11.csv', '123.csv', 'joint_account_20261128.CSV', '',
                 '\u00dftatement.txt', 'credit-card-statement-2026-11.tsv', 'my.bank.export.csv', '2026.csv']

EDGE_FILES = {
    'xml.ofx': ('<?xml version="1.0" encoding="UTF-8"?>\n<?OFX OFXHEADER="200" VERSION="220"?>\n<OFX><CREDITCARDMSGSRSV1><CCSTMTTRNRS>'
                '<CCSTMTRS><CURDEF>GBP</CURDEF><CCACCTFROM><ACCTID>1</ACCTID></CCACCTFROM><BANKTRANLIST>'
                + ''.join('<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>2026%02d14120000.000[0:GMT]</DTPOSTED><TRNAMT>-7.99</TRNAMT>'
                          '<NAME>NOTEBOOK APP &amp; SYNC</NAME><MEMO>Monthly plan</MEMO></STMTTRN>' % m for m in range(1, 8))
                + '<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><TRNAMT>-1.00</TRNAMT><NAME>NO DATE</NAME></STMTTRN>'
                + '<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260230</DTPOSTED><TRNAMT>-1.00</TRNAMT><NAME>BAD DATE</NAME></STMTTRN>'
                + '<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260301</DTPOSTED><TRNAMT>abc</TRNAMT><NAME>BAD AMOUNT</NAME></STMTTRN>'
                '</BANKTRANLIST></CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1></OFX>'),
    'us-dates.qif': ('!Type:CCard\n' + ''.join('D%d/%d/2026\nU-12.50\nT-12.50\nPSTREAMING CO\nMMonthly\nLEntertainment\n^\n' % (m, 15) for m in range(1, 7))
                     + 'D13/45/2026\nT-1\nPBROKEN\n^\nD1/2/2026\nPNO AMOUNT\n^\nT-3.00\nPNO DATE\n^\n'),

    'headerless.csv': '03/09/2026,NETFLIX.COM,-10.99,412.10\n05/09/2026,GREENGATE SUPERMARKET,-23.10,389.00\n'
                      '03/10/2026,NETFLIX.COM,-10.99,378.01\n12/10/2026,CAMPUS CAFE PAYROLL,412.50,790.51\n'
                      '03/11/2026,NETFLIX.COM,-10.99,779.52\n20/11/2026,GREENGATE SUPERMARKET,-18.45,761.07\n'
                      '03/12/2026,NETFLIX.COM,-10.99,750.08\n',
    'semicolons.csv': 'Date;Description;Amount;Balance\r\n01.09.2026;"SPOTIFY P1A2B3C4";-10,99;1.234,56\r\n'
                      '02.09.2026;BAKERY;-3,50;1.231,06\r\n01.10.2026;"SPOTIFY P9Z8Y7X6";-10,99;1.220,07\r\n'
                      '15.10.2026;SALARY ACME LTD;1.050,00;2.270,07\r\n'
                      '01.11.2026;"SPOTIFY Q1W2E3R4";-11,99;2.258,08\r\n'
                      '01.12.2026;"SPOTIFY T5Y6U7I8";-11,99;2.246,09\r\n',
    'card-positive.csv': 'Transaction Date,Description,Amount\n2026-08-14,AUDIBLE UK*AB1CD2EF3,7.99\n'
                         '2026-08-20,THE BOOK NOOK,12.50\n2026-09-14,AUDIBLE UK*ZX9YW8VU7,7.99\n'
                         '2026-09-25,PAYMENT THANK YOU,-20.49\n2026-10-14,AUDIBLE UK*QQ1RR2SS3,7.99\n'
                         '2026-11-14,AUDIBLE UK*LM4NO5PQ6,7.99\n2026-11-15,CAFE,3.20\n',
    'status.csv': 'Date,Description,Amount,Currency,Status\n2026-09-02,Reelhouse+,-5.99,GBP,COMPLETED\n'
                  '2026-09-03,Reelhouse+,-5.99,GBP,REVERTED\n2026-10-02,Reelhouse+,-5.99,GBP,COMPLETED\n'
                  '2026-10-05,Corner Deli,-3.20,GBP,DECLINED\n2026-11-02,Reelhouse+,-5.99,GBP,COMPLETED\n'
                  '2026-11-20,Ski Hire,-40.00,EUR,COMPLETED\n2026-11-27,Corner Deli,-4.10,GBP,PENDING\n'
                  '2026-11-28,Top up,50.00,GBP,Completed\n',
    'line-breaks.csv': 'Date,Description,Reference,Amount\n01/10/2026,"GYM\nMEMBERSHIP","REF 1\nLINE 2",-30.00\n'
                       '05/10/2026,"He said ""hello""",X,-1.00\nbad date,"multi\nline\nrow",,-2.00\n'
                       '01/11/2026,"GYM MEMBERSHIP",,-30.00\n,,,\n01/12/2026,GYM MEMBERSHIP,,(30.00)\n'
                       '02/12/2026,TOTAL,,-99.00\n,Closing balance,,\n03/12/2026,,,\n04/12/2026,Nothing,,0.00\n',
    'tabs-and-markers.tsv': 'Booking date\tPayee\tAmount\tDebit/Credit\tType\n'
                            '05/09/2026\tCOUNCIL TAX\t120.00\tDebit\tDD\n'
                            '05/10/2026\tCOUNCIL TAX\t120.00\tDebit\tDD\n12/10/2026\tREFUND\t9.99\tCredit\tBGC\n'
                            '05/11/2026\tCOUNCIL TAX\t120.00\tD\tDD\n05/12/2026\tCOUNCIL TAX\t125.00\tdr\tDD\n',
    'us-dates.csv': 'Date,Description,Amount\n09/13/2026,GYM,-20.00\n10/13/2026,GYM,-20.00\n11/13/2026,GYM,-20.00\n'
                    '12/01/2026,SHOP,-5.00\n',
    'conflicting.csv': 'Date,Description,Amount\n13/01/2026,A,-1.00\n01/13/2026,B,-2.00\n05/05/2026,C,-3.00\n',
    'ambiguous.csv': 'Date,Description,Amount\n01/02/2026,A,-1.00\n03/04/2026,B,-2.00\n',
    'columns.csv': 'Date,Description,Money out,Money in\n01/09/2026,ROCK CLIMBING CLUB,25.00,\n'
                   '01/10/2026,ROCK CLIMBING CLUB,25.00,\n02/10/2026,BROKEN,abc,\n03/10/2026,FRIEND,,15.00\n'
                   '04/10/2026,BOTH,,x\n05/10/2026,NONE,,\n01/11/2026,ROCK CLIMBING CLUB,25.00,\n',
    'empty.csv': '',
    'saved.json': '{"format": "still-paying-review"}',
    'document.pdf.csv': '%PDF-1.7 binary',
    'sheet.csv': 'PK\x03\x04 zipped',
    'nonsense.csv': 'hello,world\nfoo,bar\n',
}

SAVED_TEXTS = [
    '{', '[]', 'NaN', '{"format":"still-paying-review","version":2}',
    '\ufeff{"format":"still-paying-review","version":"1"}',
    '{"format":"still-paying-review","version":1,"reviewedOn":"2026-02-30","transactions":'
    '[["2026-01-01",-500,"A"],["bad",1],["2026-01-02","x"],["2026-01-03",12.5,null,0,false,"",""],'
    '"2026-01-04",["2026-01-05",1e400]],"decisions":{"a":{"decision":"maybe"},'
    '"b":{"decision":"cancel","decidedOn":"2026-01-01","noticeDays":4,"note":5},"10":{"decision":"keep"},'
    '"c":null},"known":[],"aliases":{"2":"X","1":"Y"},"overrides":{"x":{"method":"card"}}}',
]

# A month-end standing order that rolls into the next month, checked a week after it was due.
ALLOWANCE = '\n'.join(['Date,Description,Type,Amount']
                      + [d + ',ALLOWANCE FROM HOME,Standing order,200.00'
                         for d in ['30/06/2026', '31/07/2026', '01/09/2026', '30/09/2026']]
                      + ['%02d/09/2026,CORNER SHOP,Card payment,-3.00' % d for d in (3, 9, 15, 21)])

EARLIER_REVIEW_DAY = '2026-11-01'


def earlier_files():
    """The samples as they would have been exported a month ago (up to 31 October)."""
    last = sp.from_iso('2026-10-31')
    return [{'name': n, 'text': truncate(sample_text(n), last)} for n in SAMPLES[:3]]


def analysis_jobs(earlier_project):
    """Every analysis compared between the two versions, as (label, job) pairs."""
    jobs = [(name, {'files': sample_files([name]), 'decisions': DECISIONS}) for name in SAMPLES]
    jobs.append(('all four samples', {'files': sample_files(), 'decisions': DECISIONS}))
    for name in OTHER_FORMATS:
        jobs.append((name, {'files': sample_files([name]), 'decisions': DECISIONS}))
    jobs.append(('all six samples', {'files': sample_files(SAMPLES + OTHER_FORMATS), 'decisions': DECISIONS}))
    jobs.append(('all four, no decisions, later date', {'files': sample_files(), 'asOf': '2027-01-20',
                                                        'budgetMonths': 3, 'icsDays': 200, 'icsIncludeIncome': True}))
    jobs.append(('choices carried', {
        'files': sample_files(), 'decisions': DECISIONS,
        'details': {'name': 'Alex Holder', 'account': 'alex@example.com'},
        'aliases': {'REELHOUSE+': 'STREAMCRATE.TV'},
        'names': {'IRONWORKS GYM~monthly~1': 'The gym', 'CAMPUS CAFE PAYROLL~monthly~1': 'Wages'},
        'manual': [{'id': 'FENWICK MUTUAL INSURANCE~single~2026-02-18', 'cadence': 'yearly'},
                   {'id': 'QUILLHOST ANNUAL PLAN~single~2026-03-09'}, {'id': 'NOT THERE~single~2026-01-01'}],
        'overrides': {'APPHAVEN.COM/BILL~monthly~1': {'category': 'software', 'method': 'card'},
                      'LINGOLEAP LANGUAGE~monthly~1': {'method': 'card'},
                      'TIDYUP CLEANING~fortnightly~1': {'category': 'not-a-category', 'method': 'cash'},
                      'CAMPUS BIKE HIRE~four-weekly~1': {'cadence': 'monthly'},
                      'IRONWORKS GYM~monthly~1': {'cadence': 'not-a-cadence'}},
        'added': [{'name': 'TV Licence', 'amount': 1453, 'cadence': 'monthly', 'next': '2026-12-01',
                   'method': 'direct debit', 'category': 'tv', 'account': 'Current account'},
                  {'name': 'Termly fees', 'amount': 120000, 'cadence': 'quarterly', 'next': '2026-10-05',
                   'method': 'card', 'category': 'learning', 'account': ''},
                  {'name': 'Gym (second site)', 'amount': 1999.6, 'cadence': 'weekly', 'next': '2027-01-31',
                   'method': 'nonsense', 'category': 'income'},
                  {'name': '', 'amount': 500, 'cadence': 'monthly', 'next': '2026-12-01'},
                  {'name': 'No date', 'amount': 500, 'cadence': 'monthly', 'next': 'soon'}]}))
    jobs.append(('a month later, with the earlier review', {
        'files': sample_files(), 'extra': earlier_project, 'saved': earlier_project,
        'decisions': {'IRONWORKS GYM~monthly~1': {'decision': 'cancel', 'decidedOn': '2026-10-31'},
                      'HARBOUR LETTINGS RENT~monthly~1': {'decision': 'keep'}}}))
    for name in EDGE_FILES:
        jobs.append((name, {'files': [{'name': name, 'text': EDGE_FILES[name]}]}))
    jobs.append(('every edge file together', {
        'files': [{'name': n, 'text': t} for n, t in EDGE_FILES.items()], 'asOf': '2026-12-10',
        'decisions': {'COUNCIL TAX~monthly~1': {'decision': 'cancel'}}}))
    jobs.append(('rolled month-end income', {'files': [{'name': 'allowance.csv', 'text': ALLOWANCE}],
                                             'asOf': '2026-11-10', 'icsIncludeIncome': True}))
    jobs.append(('named account', {'files': [{'name': 'messy-export.csv', 'text': sample_text('messy-export.csv'),
                                              'account': 'Old current account'}] + sample_files(SAMPLES[:1])}))
    return jobs


def python_analysis(job):
    """The Python side of the bridge's runAnalysis()."""
    as_of = sp.from_iso(job['asOf']) if job.get('asOf') else None
    extra = sp.read_project(job['extra'])['transactions'] if job.get('extra') else None
    a = sp.analyse(job.get('files', []), as_of=as_of, extra=extra, aliases=job.get('aliases'), names=job.get('names'),
                   manual=job.get('manual'), overrides=job.get('overrides'), added=job.get('added'))
    r = a['result']
    decisions = job.get('decisions') or {}
    pl = sp.plan(r, decisions, job.get('details'))
    return {
        'summary': sp.summary(r), 'statements': a['statements'], 'merged': a['merged'], 'result': r,
        'registerCsv': sp.register_csv(r, decisions), 'budgetCsv': sp.budget_csv(r, decisions, job.get('budgetMonths')),
        'ics': sp.build_ics(r, decisions, days=job.get('icsDays'), include_income=bool(job.get('icsIncludeIncome')),
                            details=job.get('details')),
        'projectText': sp.project_file({'transactions': a['merged']['transactions'], 'result': r,
                                        'decisions': decisions, 'accounts': a['merged']['accounts'],
                                        'aliases': job.get('aliases'), 'names': job.get('names'),
                                        'manual': job.get('manual'), 'overrides': job.get('overrides'),
                                        'added': job.get('added'), 'details': job.get('details')}),
        'plan': {'totals': pl['totals'], 'actions': pl['actions']},
        'forecast': sp.forecast(r, 92, decisions),
        'monthTotals': sp.month_totals(sp.forecast(r, 365, decisions), False),
        'suggestions': {s['id']: sp.suggest(s) for s in r['series']},
        'since': sp.since_last_review(r, sp.read_project(job['saved'])) if job.get('saved') else None,
        'xlsx': (lambda x: {'bytes': base64.b64encode(x['bytes']).decode('ascii'), 'parts': x['parts']})(
            sp.build_xlsx(r, decisions, {'transactions': a['merged']['transactions'], 'accounts': a['merged']['accounts']})),
        'runways': [sp.runway(r, decisions, {'account': acc['account'], 'balance': acc['closing']['balance'],
                                             'everyday': r['everyday'][acc['account']]['perDay'] if acc['account'] in r['everyday'] else 0,
                                             'overdraft': 50000, 'leaveOutCancelled': True, 'days': 60,
                                             'extraIn': [{'day': r['asOf'] + 20, 'amount': 12345, 'name': 'Loan'}]})
                    for acc in a['merged']['accounts'] if acc['closing']],
    }


class AgreementTest(unittest.TestCase):
    """The Python package against the browser model, on the same inputs."""

    @classmethod
    def setUpClass(cls):
        """Run every job through both versions once; the tests then compare the answers."""
        if not NODE:
            raise unittest.SkipTest('node is not installed, so the Python and JavaScript versions cannot be compared')
        earlier = {'files': earlier_files(), 'asOf': EARLIER_REVIEW_DAY,
                   'decisions': {'IRONWORKS GYM~monthly~1': {'decision': 'cancel', 'decidedOn': '2026-10-31'}}}
        cls.earlier_js = run_bridge({'analyses': [earlier]})['analyses'][0]
        cls.earlier_py = python_analysis(earlier)
        cls.jobs = analysis_jobs(cls.earlier_js['projectText'])
        cls.js = run_bridge({
            'analyses': [job for _, job in cls.jobs], 'amounts': AMOUNTS, 'dates': DATES, 'descriptions': DESCRIPTIONS,
            'headers': HEADERS, 'delimited': DELIMITED, 'folds': FOLDS, 'holidays': list(range(2010, 2041)),
            'accountNames': ACCOUNT_NAMES,
            'projects': [cls.earlier_js['projectText']] + SAVED_TEXTS,
        })
        cls.py = [python_analysis(job) for _, job in cls.jobs]

    def assertSame(self, py, js, what):
        """Fail with the path of the first difference when two answers are not the same."""
        diff = first_difference(plain(py), js)
        self.assertIsNone(diff, '%s differs at %s' % (what, diff))

    def js_for(self, label):
        """The browser model's answers for one labelled analysis."""
        return self.js['analyses'][[name for name, _ in self.jobs].index(label)]

    def each(self):
        """Each analysis as (label, Python answers, JavaScript answers), inside a subtest."""
        for (label, _), py, js in zip(self.jobs, self.py, self.js['analyses']):
            with self.subTest(label):
                yield label, py, js

    def test_counted_enough(self):
        self.assertGreaterEqual(len(AMOUNTS), 40)
        self.assertGreaterEqual(len(DATES), 30)
        self.assertGreaterEqual(len(DESCRIPTIONS), 40)

    def test_earlier_review_is_the_same_file(self):
        self.assertEqual(self.earlier_py['projectText'], self.earlier_js['projectText'])

    def test_summaries(self):
        for label, py, js in self.each():
            self.assertSame(py['summary'], js['summary'], label + ' summary')

    def test_every_field_of_every_series(self):
        for label, py, js in self.each():
            self.assertSame(py['result'], js['result'], label + ' result')

    def test_statements_and_merging(self):
        for label, py, js in self.each():
            self.assertSame(py['statements'], js['statements'], label + ' statements')
            self.assertSame(py['merged'], js['merged'], label + ' merged')

    def test_register_csv_is_byte_identical(self):
        for label, py, js in self.each():
            self.assertEqual(py['registerCsv'], js['registerCsv'], label)

    def test_budget_csv_is_byte_identical(self):
        for label, py, js in self.each():
            self.assertEqual(py['budgetCsv'], js['budgetCsv'], label)

    def test_calendar_is_byte_identical(self):
        for label, py, js in self.each():
            self.assertEqual(py['ics']['text'], js['ics']['text'], label)
            self.assertEqual(py['ics']['events'], js['ics']['events'], label)

    def test_project_file_text_is_identical(self):
        for label, py, js in self.each():
            self.assertEqual(py['projectText'], js['projectText'], label)

    def test_plan_totals_and_actions(self):
        for label, py, js in self.each():
            self.assertSame(py['plan']['totals'], js['plan']['totals'], label + ' totals')
            self.assertSame(py['plan']['actions'], js['plan']['actions'], label + ' actions')

    def test_forecast_month_totals_and_suggestions(self):
        for label, py, js in self.each():
            self.assertSame(py['forecast'], js['forecast'], label + ' forecast')
            self.assertSame(py['monthTotals'], js['monthTotals'], label + ' month totals')
            self.assertSame(py['suggestions'], js['suggestions'], label + ' suggestions')

    def test_since_last_review(self):
        for label, py, js in self.each():
            self.assertSame(py['since'], js['since'], label + ' since last review')

    def test_workbook_is_byte_identical(self):
        for label, py, js in self.each():
            self.assertSame(py['xlsx']['parts'], js['xlsx']['parts'], label + ' workbook parts')
            self.assertEqual(py['xlsx']['bytes'], js['xlsx']['bytes'], label + ' workbook bytes')

    def test_balance_runways(self):
        compared = 0
        for label, py, js in self.each():
            self.assertSame(py['runways'], js['runways'], label + ' runways')
            compared += len(js['runways'])
        self.assertGreater(compared, 5, 'the samples should give several accounts with a balance')
        later = self.js_for('a month later, with the earlier review')
        self.assertEqual([c['id'] for c in later['since']['stillCharging']], ['IRONWORKS GYM~monthly~1'])

    def test_the_decisions_made_a_difference(self):
        together = self.js_for('all four samples')
        self.assertIn('Cancel', together['registerCsv'])
        self.assertIn('(you plan to cancel)', together['ics']['text'])
        self.assertGreater(together['plan']['totals']['cancelMonthly'], 0)

    def test_amounts(self):
        for raw, js in zip(AMOUNTS, self.js['amounts']):
            with self.subTest(raw=raw):
                self.assertEqual(sp.parse_amount(raw), js)

    def test_dates_both_orders(self):
        for raw, js in zip(DATES, self.js['dates']):
            with self.subTest(raw=raw):
                self.assertSame({'shape': sp.date_shape(raw), 'dmy': sp.parse_date(raw, 'DMY'),
                                 'mdy': sp.parse_date(raw, 'MDY')}, js, repr(raw))
        self.assertSame(sp.detect_date_order(DATES), self.js['dateOrder'], 'date order')

    def test_descriptions(self):
        for raw, js in zip(DESCRIPTIONS, self.js['descriptions']):
            with self.subTest(raw=raw):
                key = sp.payee_key(raw)
                self.assertSame({'key': key, 'name': sp.display_name(key), 'clean': sp.clean_description(raw),
                                 'category': sp.categorise(raw), 'method': sp.payment_method('', raw)}, js, repr(raw))

    def test_headers(self):
        for cells, js in zip(HEADERS, self.js['headers']):
            self.assertSame(map_header(cells), js, repr(cells))

    def test_delimited_text(self):
        for d, js in zip(DELIMITED, self.js['delimited']):
            delim = d.get('delim') or sp.sniff_delimiter(d['text'])
            self.assertSame({'sniffed': sp.sniff_delimiter(d['text']), 'parsed': sp.parse_delimited(d['text'], delim)},
                            js, repr(d['text']))

    def test_calendar_folding(self):
        for line, js in zip(FOLDS, self.js['folds']):
            self.assertEqual(ics_fold(line), js)

    def test_bank_holidays(self):
        for year, js in zip(range(2010, 2041), self.js['holidays']):
            self.assertEqual(sp.bank_holidays(year), js, year)

    def test_account_names(self):
        for name, js in zip(ACCOUNT_NAMES, self.js['accountNames']):
            self.assertEqual(sp.default_account(name), js, repr(name))

    def test_reading_saved_reviews(self):
        for text, js in zip([self.earlier_js['projectText']] + SAVED_TEXTS, self.js['projects']):
            self.assertSame(sp.read_project(text), js, text[:40])

    def test_template(self):
        self.assertEqual(sp.template_csv(), self.js['template'])


if __name__ == '__main__':
    unittest.main()
