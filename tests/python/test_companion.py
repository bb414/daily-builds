"""Tests for the Python companion: experiments, screening, calibration, the report and the command line.

Training runs use fast settings (quick exploration decay and a short limit) and
run in this process (jobs=1), so the whole file takes well under a minute. Run
from the repository root::

    python -m unittest discover -s tests/python -t .
"""

import contextlib
import csv
import io
import json
import math
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quiet_cartel import calibrate, cli, experiments, model, report, screening  # noqa: E402

FAST = {'beta': 1e-4, 'maxPeriods': 150000, 'stableWindow': 10000}
FAST_SET = ['beta=1e-4', 'maxPeriods=150000', 'stableWindow=10000']
DATA = os.path.join(ROOT, 'data', 'markets.csv')
TRUTH = os.path.join(ROOT, 'data', 'markets_truth.csv')


def run_cli(argv):
    """Run the command line in this process; returns (status, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        status = cli.main(argv)
    return status, out.getvalue(), err.getvalue()


def write_csv(path, header, rows):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def price_rows(days=40, market=None):
    """Simple valid rows: day, price_a, price_b (with a market column when market is given)."""
    rows = []
    for d in range(1, days + 1):
        row = [d, 1.5 + 0.01 * (d % 3), 1.6 - 0.01 * (d % 4)]
        rows.append(([market] if market is not None else []) + row)
    return rows


# ------------------------------------------------------------ experiments

class BatchTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rows = experiments.run_batch(FAST, ['own'], [1, 2, 3], jobs=1)

    def test_batch_runs_baseline_first_in_order(self):
        self.assertEqual([(r['scenario'], r['seed']) for r in self.rows],
                         [('baseline', 1), ('baseline', 2), ('baseline', 3), ('own', 1), ('own', 2), ('own', 3)])
        keys = {'scenario', 'seed', 'converged', 'periods', 'avgGain', 'realisedGain', 'harm', 'punished',
                'collusive', 'cycleLength', 'meanPrice', 'brGapA', 'brGapB'}
        for r in self.rows:
            self.assertEqual(set(r), keys)
            self.assertGreaterEqual(r['brGapA'], 0)

    def test_run_one_matches_model_run_scenario(self):
        base = model.validate_config(FAST)['config']
        s = model.run_scenario(base, 'own', 2)
        r = self.rows[4]
        for k in ('avgGain', 'realisedGain', 'harm', 'punished', 'periods', 'converged'):
            self.assertEqual(r[k], s[k])

    def test_rule_seller_has_no_gap(self):
        r = experiments.run_one(model.validate_config(FAST)['config'], 'fixedrival', 1)
        self.assertIsNone(r['brGapB'])
        self.assertIsNotNone(r['brGapA'])

    def test_summary_uses_model_aggregate(self):
        s = experiments.summarise_batch(self.rows)
        self.assertEqual(s['order'], ['baseline', 'own'])
        self.assertEqual(s['scenarios']['own']['agg'], model.aggregate(self.rows[3:]))
        self.assertIsNone(s['scenarios']['baseline']['vsBaseline'])
        cmp_ = s['scenarios']['own']['vsBaseline']['realisedGain']
        diffs = [self.rows[3 + k]['realisedGain'] - self.rows[k]['realisedGain'] for k in range(3)]
        self.assertAlmostEqual(cmp_['diff'], sum(diffs) / 3, places=12)
        self.assertTrue(cmp_['exact'])
        self.assertLessEqual(cmp_['lo'], cmp_['diff'])
        self.assertGreaterEqual(cmp_['hi'], cmp_['diff'])
        self.assertEqual(cmp_['pairs'], 3)

    def test_scenario_against_itself(self):
        twin = [dict(r, scenario='own') for r in self.rows[:3]]
        s = experiments.summarise_batch(self.rows[:3] + twin)
        for key in ('realisedGain', 'harm'):
            c = s['scenarios']['own']['vsBaseline'][key]
            self.assertEqual(c['diff'], 0)
            self.assertEqual((c['lo'], c['hi']), (0, 0))
            self.assertEqual(c['pValue'], 1)
            self.assertEqual(c['pHolm'], 1)

    def test_batch_errors(self):
        with self.assertRaisesRegex(ValueError, 'unknown scenario'):
            experiments.run_batch(FAST, ['nope'], [1], jobs=1)
        with self.assertRaisesRegex(ValueError, 'must not repeat'):
            experiments.run_batch(FAST, ['own'], [1, 1], jobs=1)
        with self.assertRaisesRegex(ValueError, 'base settings'):
            experiments.run_batch({'mu': 9}, ['own'], [1], jobs=1)
        with self.assertRaisesRegex(ValueError, "'vendor' does not fit"):
            experiments.run_batch(dict(FAST, firmTypes=['learn', 'nash']), ['vendor'], [1], jobs=1)


class StatisticsTest(unittest.TestCase):

    def test_sign_flip_exact_hand_example(self):
        # Signed totals of (1, 2, 3): +-6, +-4, +-2, 0, 0. Two of eight reach |6|.
        r = experiments.sign_flip_test([1, 2, 3])
        self.assertEqual(r['pValue'], 0.25)
        self.assertTrue(r['exact'])
        self.assertEqual(r['reps'], 8)
        # |4| or more: +-6 and +-4.
        self.assertEqual(experiments.sign_flip_test([-1, 2, 3])['pValue'], 0.5)
        self.assertEqual(experiments.sign_flip_test([1, -1])['pValue'], 1)
        self.assertEqual(experiments.sign_flip_test([0, 0, 0])['pValue'], 1)
        self.assertTrue(math.isnan(experiments.sign_flip_test([])['pValue']))

    def test_sign_flip_random_when_many_pairs(self):
        r = experiments.sign_flip_test([1.0] * 20)
        self.assertFalse(r['exact'])
        self.assertEqual(r['pValue'], 1 / 10000)      # (1 + 0) / (1 + 9999)
        self.assertEqual(experiments.sign_flip_test([1.0] * 20, reps=99)['pValue'], 0.01)

    def test_holm_known_example(self):
        # sorted 0.005 x4 = 0.02, 0.01 x3 = 0.03, 0.03 x2 = 0.06, 0.04 x1 = 0.04 -> kept at 0.06
        adj = experiments.holm([0.01, 0.04, 0.03, 0.005])
        for got, want in zip(adj, [0.03, 0.06, 0.06, 0.02]):
            self.assertAlmostEqual(got, want, places=12)
        adj = experiments.holm([0.5, None, 0.4])
        self.assertTrue(math.isnan(adj[1]))
        self.assertEqual([adj[0], adj[2]], [0.8, 0.8])

    def test_benjamini_hochberg_known_example(self):
        # m = 5; sorted p * m / rank: 0.025, 0.025, 0.05, 0.05, 0.2, then the running minimum from the top.
        q = screening.benjamini_hochberg([0.01, 0.04, 0.03, 0.005, 0.20])
        for got, want in zip(q, [0.025, 0.05, 0.05, 0.025, 0.2]):
            self.assertAlmostEqual(got, want, places=12)
        # A missing p-value counts as 1 in m but has no q-value of its own.
        q = screening.benjamini_hochberg([0.01, None, 0.5])
        self.assertAlmostEqual(q[0], 0.03, places=12)
        self.assertTrue(math.isnan(q[1]))
        self.assertAlmostEqual(q[2], 0.75, places=12)


class SweepTest(unittest.TestCase):

    def test_grid_shape(self):
        res = experiments.sweep(FAST, 'mu', [0.1, 0.5], 'delta', [0.5, 0.8, 0.95], [1], jobs=1)
        self.assertEqual(len(res['cells']), 3)
        self.assertTrue(all(len(line) == 2 for line in res['cells']))
        self.assertEqual(res['cells'][2][1]['x'], 0.5)
        self.assertEqual(res['cells'][2][1]['y'], 0.95)
        for line in res['cells']:
            for c in line:
                self.assertEqual(set(c), {'x', 'y', 'runs', 'gain', 'harm', 'punishedShare', 'convergedShare'})
                self.assertIn(c['punishedShare'], (0, 1))
        self.assertEqual(len(res['runs']), 6)

    def test_sweep_validation(self):
        with self.assertRaisesRegex(ValueError, 'numeric setting'):
            experiments.sweep(FAST, 'memory', [1], 'mu', [0.1], [1], jobs=1)
        with self.assertRaisesRegex(ValueError, 'numeric setting'):
            experiments.sweep(FAST, 'quality', [1], 'mu', [0.1], [1], jobs=1)
        with self.assertRaisesRegex(ValueError, 'must differ'):
            experiments.sweep(FAST, 'mu', [0.1], 'mu', [0.2], [1], jobs=1)
        with self.assertRaisesRegex(ValueError, 'between'):
            experiments.sweep(FAST, 'mu', [5], 'delta', [0.5], [1], jobs=1)
        with self.assertRaisesRegex(ValueError, 'fixes delta'):
            experiments.sweep(FAST, 'mu', [0.1], 'delta', [0.5], [1], scenario='myopic', jobs=1)
        with self.assertRaisesRegex(ValueError, 'not valid'):
            experiments.sweep(FAST, 'stableWindow', [200000], 'mu', [0.1], [1], jobs=1)   # above maxPeriods


# ------------------------------------------------------------ screening

class ReadPanelTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def path(self, name='p.csv'):
        return os.path.join(self.dir, name)

    def test_reads_and_sorts_by_day(self):
        rows = list(reversed(price_rows(35, market=7))) + price_rows(30, market=2)
        write_csv(self.path(), ['Market', 'Day', 'price_a', 'price_b', 'cost_a', 'cost_b'],
                  [r + [1, 1.2] for r in rows])
        panel = screening.read_panel(self.path())
        self.assertEqual(list(panel), [2, 7])
        self.assertEqual(panel[7]['day'], list(range(1, 36)))
        self.assertEqual(panel[7]['prices'][0][0], 1.51)
        self.assertEqual(panel[7]['cost'], [1, 1.2])
        self.assertNotIn('units', panel[7])

    def test_single_market_file(self):
        write_csv(self.path(), ['day', 'price_a', 'price_b'], price_rows(30))
        panel = screening.read_panel(self.path())
        self.assertEqual(list(panel), [1])
        self.assertIsNone(panel[1]['cost'])
        self.assertEqual(len(panel[1]['prices'][1]), 30)

    def test_sales_columns(self):
        rows = [r + [1000, 300, 280] for r in price_rows(30)]
        write_csv(self.path(), ['day', 'price_a', 'price_b', 'shoppers', 'units_a', 'units_b'], rows)
        panel = screening.read_panel(self.path())
        self.assertEqual(panel[1]['shoppers'][0], 1000)
        self.assertEqual(panel[1]['units'], [[300] * 30, [280] * 30])

    def assertBad(self, header, rows, pattern):
        write_csv(self.path(), header, rows)
        with self.assertRaisesRegex(ValueError, pattern):
            screening.read_panel(self.path())

    def test_missing_required_column(self):
        self.assertBad(['market', 'day', 'price_a'], [r[:3] for r in price_rows(30, 1)],
                       'missing required column price_b')

    def test_non_numeric_value(self):
        rows = price_rows(30, 1)
        rows[4][2] = 'cheap'
        self.assertBad(['market', 'day', 'price_a', 'price_b'], rows, r'row 6: price_a is not a number')

    def test_price_not_above_zero(self):
        rows = price_rows(30, 1)
        rows[9][3] = 0
        self.assertBad(['market', 'day', 'price_a', 'price_b'], rows, r'row 11: price_b must be above zero')

    def test_duplicate_day(self):
        rows = price_rows(31, 1)
        rows[30][1] = 12
        self.assertBad(['market', 'day', 'price_a', 'price_b'], rows, r'market 1 has day 12 twice \(rows 13 and 32\)')

    def test_too_few_days(self):
        rows = price_rows(30, 1) + price_rows(12, 2)
        self.assertBad(['market', 'day', 'price_a', 'price_b'], rows, r'market 2 has only 12 days \(row 32 onwards\)')

    def test_sales_problems(self):
        rows = [r + [100, 60, 50] for r in price_rows(30)]
        self.assertBad(['day', 'price_a', 'price_b', 'shoppers', 'units_a', 'units_b'], rows,
                       r'row 2: units_a \+ units_b \(110\) is more than shoppers \(100\)')
        self.assertBad(['day', 'price_a', 'price_b', 'shoppers'], [r + [100] for r in price_rows(30)],
                       'must be given together')

    def test_read_truth(self):
        truth = screening.read_truth(TRUTH)
        self.assertEqual(len(truth), 40)
        self.assertIs(truth[1]['coordinated'], True)
        self.assertEqual(truth[1]['mu'], 0.5)
        write_csv(self.path(), ['market', 'coordinated'], [[1, 1]])
        with self.assertRaisesRegex(ValueError, 'high_price'):
            screening.read_truth(self.path())


class EvaluateTest(unittest.TestCase):

    def test_hand_made_results(self):
        # Retaliation ranks the two coordinated markets first; margin gets them exactly backwards.
        def market(m, ret, margin, flag):
            return {'market': m, 'flag': flag, 'scores': {'retaliation': ret, 'margin': margin}}
        results = {'markets': [market(1, 0.9, 0.1, True), market(2, 0.8, 0.2, True), market(3, 0.1, 0.8, True),
                               market(4, 0.0, 0.9, False), market(5, 0.5, 0.5, False)]}
        truth = {1: {'coordinated': True, 'high_price': True}, 2: {'coordinated': True, 'high_price': False},
                 3: {'coordinated': False, 'high_price': True}, 4: {'coordinated': False, 'high_price': False}}
        ev = screening.evaluate(results, truth)
        self.assertEqual(ev['markets'], 4)
        self.assertEqual(ev['missing'], [5])
        coord = ev['targets'][0]
        self.assertEqual(coord['id'], 'coordinated')
        auc = {s['id']: s['auc'] for s in coord['screens']}
        self.assertEqual(auc, {'margin': 0.0, 'retaliation': 1.0})
        self.assertEqual((coord['flag']['caught'], coord['flag']['falseAlarms'], coord['flag']['missed'],
                          coord['flag']['cleared']), (2, 1, 0, 1))
        high = ev['targets'][1]
        # High prices in markets 1 and 3, not 2 and 4. On retaliation, market 1 (0.9) outscores both
        # innocent markets and market 3 (0.1) outscores only market 4: 3 of 4 pairs.
        self.assertEqual({s['id']: s['auc'] for s in high['screens']}['retaliation'], 0.75)
        self.assertEqual((high['flag']['caught'], high['flag']['falseAlarms']), (2, 1))

    def test_excess_screen_and_no_flags(self):
        results = {'markets': [{'market': 1, 'scores': {'excessPrice': 0.9}},
                               {'market': 2, 'scores': {'excessPrice': None}},
                               {'market': 3, 'scores': {'excessPrice': 0.1}}]}
        truth = {1: {'coordinated': 1, 'high_price': 1}, 2: {'coordinated': 1, 'high_price': 0},
                 3: {'coordinated': 0, 'high_price': 0}}
        ev = screening.evaluate(results, truth)
        coord, high = ev['targets']
        self.assertEqual([s['id'] for s in coord['screens']], ['excessPrice'])
        self.assertEqual(coord['screens'][0]['auc'], 0.5)   # the unusable fit ranks last
        self.assertEqual(high['screens'][0]['auc'], 1.0)
        self.assertIsNone(coord['flag'])
        with self.assertRaisesRegex(ValueError, 'none of the screened markets'):
            screening.evaluate(results, {9: {'coordinated': 1, 'high_price': 1}})


# ------------------------------------------------------------ calibration

class CalibrateTest(unittest.TestCase):

    def noise_free(self, quality, mu, days=60, shoppers=1000):
        rng = model.Rng(7)
        pa = [1.1 + rng.next() for _ in range(days)]
        pb = [1.1 + rng.next() for _ in range(days)]
        ua, ub = [], []
        for a, b in zip(pa, pb):
            sa, sb = model.shares([a, b], quality, 0, mu)
            ua.append(sa * shoppers)
            ub.append(sb * shoppers)
        return pa, pb, ua, ub, [shoppers] * days

    def test_recovers_known_mu_and_quality(self):
        for quality, mu in (([2, 2], 0.25), ([2, 1.8], 0.3), ([2.2, 2], 0.1)):
            fit = calibrate.fit_market(*self.noise_free(quality, mu))
            self.assertTrue(fit['usable'])
            self.assertAlmostEqual(fit['mu'], mu, delta=1e-9)
            self.assertAlmostEqual(fit['quality'][0], quality[0], delta=1e-8)
            self.assertAlmostEqual(fit['quality'][1], quality[1], delta=1e-8)
            self.assertAlmostEqual(fit['r2'], 1, delta=1e-12)
            self.assertLess(fit['muSe'], 1e-9)
            self.assertEqual((fit['days'], fit['dropped']), (60, 0))

    def test_benchmark_on_known_market(self):
        fit = calibrate.fit_market(*self.noise_free([2, 2], 0.25))
        bm = calibrate.benchmark(fit, [1, 1])
        for got, want in zip(bm['competitive'], model.nash_prices([2, 2], [1, 1], 0, 0.25)):
            self.assertAlmostEqual(got, want, delta=1e-8)
        for got, want in zip(bm['monopoly'], model.monopoly_prices([2, 2], [1, 1], 0, 0.25)):
            self.assertAlmostEqual(got, want, delta=1e-8)
        pn, pm = bm['competitive'][0], bm['monopoly'][0]
        self.assertAlmostEqual(bm['excess'][0], (fit['meanPrice'][0] - pn) / (pm - pn), places=12)
        self.assertIsNone(calibrate.benchmark(fit, None)['excessPrice'])

    def test_competitive_prices_for_unequal_sellers(self):
        # model.nash_prices ends in a two-day cycle here; the checked version must find the equilibrium.
        q, c = [2, 2.2], [1, 1]
        self.assertGreater(calibrate.nash_residual(model.nash_prices(q, c, 0, 0.25), q, c, 0, 0.25), 1)
        p, method = calibrate.competitive_prices(q, c, 0, 0.25)
        self.assertEqual(method, 'best response')
        self.assertLess(calibrate.nash_residual(p, q, c, 0, 0.25), 1e-9)
        p, method = calibrate.competitive_prices([2, 2], c, 0, 0.25)
        self.assertEqual(method, 'model')

    def test_unusable_fits(self):
        pa, pb, ua, ub, n = self.noise_free([2, 2], 0.25)
        fit = calibrate.fit_market(pa, pb, ub, ua, n)       # each seller's sales follow the other's price
        self.assertFalse(fit['usable'])
        self.assertIn('do not fall', fit['problem'])
        self.assertGreater(fit['slope'], 0)
        self.assertIsNone(fit['mu'])
        fit = calibrate.fit_market([1.5] * 30, [1.6] * 30, [300] * 30, [280] * 30, [1000] * 30)
        self.assertFalse(fit['usable'])
        self.assertIn('never change', fit['problem'])
        fit = calibrate.fit_market(pa, pb, [0] * 60, ub, n)
        self.assertFalse(fit['usable'])
        self.assertIn('only 0 days', fit['problem'])

    def test_calibrate_panel_with_truth(self):
        panel = screening.read_panel(DATA)
        small = {m: panel[m] for m in (1, 4, 11)}
        out = calibrate.calibrate_panel(small, screening.read_truth(TRUTH))
        self.assertEqual(len(out['markets']), 3)
        self.assertEqual(out['truth']['compared'], 3)
        self.assertLess(out['truth']['muMae'], 0.02)
        self.assertIsNotNone(out['markets'][2]['fit']['note'])    # most days have nobody buying nothing
        ev = out['truth']['evaluation']
        self.assertEqual([s['id'] for s in ev['targets'][0]['screens']], ['excessPrice'])
        with self.assertRaisesRegex(ValueError, 'no sales data'):
            calibrate.calibrate_panel({1: {'prices': [[1.0], [1.0]], 'cost': None}})


# ------------------------------------------------------------ command line and report

class CommandLineTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        # A small panel cut from the bundled data: three markets, every column.
        with open(DATA, newline='', encoding='utf-8') as f:
            rows = [r for r in csv.reader(f)]
        keep = {'1', '4', '27'}
        cls.panel = os.path.join(cls.dir, 'small.csv')
        write_csv(cls.panel, rows[0], [r for r in rows[1:] if r[0] in keep])
        with open(TRUTH, newline='', encoding='utf-8') as f:
            rows = [r for r in csv.reader(f)]
        cls.truth = os.path.join(cls.dir, 'truth.csv')
        write_csv(cls.truth, rows[0], [r for r in rows[1:] if r[0] in keep])
        cls.screen_json = os.path.join(cls.dir, 'screen.json')
        cls.screen = run_cli(['screen', cls.panel, '--truth', cls.truth, '--reps', '49', '--jobs', '1',
                              '--json', cls.screen_json, '--csv', os.path.join(cls.dir, 'screen.csv')])
        cls.remedies_json = os.path.join(cls.dir, 'remedies.json')
        cls.remedies = run_cli(['remedies', '--runs', '2', '--scenarios', 'baseline,own', '--jobs', '1', '--set']
                               + FAST_SET + ['--json', cls.remedies_json, '--csv', os.path.join(cls.dir, 'runs.csv')])
        cls.sweep_json = os.path.join(cls.dir, 'sweep.json')
        cls.sweep = run_cli(['sweep', '--x', 'mu=0.1,0.5', '--y', 'delta=0.5,0.95', '--runs', '1', '--jobs', '1',
                             '--set'] + FAST_SET + ['--json', cls.sweep_json])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def test_train(self):
        status, out, err = run_cli(['train', '--set'] + FAST_SET + ['--seed', '2'])
        self.assertEqual(status, 0, err)
        for text in ('Competitive price', 'Monopoly price', 'Profit gain', 'Shoppers\' loss', 'The cycle',
                     'Impulse response', 'Punished:', 'Best-response check', 'seller B'):
            self.assertIn(text, out)
        self.assertIn('Took', err)

    def test_train_preset_and_json(self):
        path = os.path.join(self.dir, 'train.json')
        status, out, err = run_cli(['train', '--preset', 'matcher', '--set'] + FAST_SET + ['--json', path])
        self.assertEqual(status, 0, err)
        self.assertIn('fixed rule: matches the cheapest rival', out)
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['kind'], 'train')
        self.assertEqual(data['config']['firmTypes'][1], 'match')

    def test_screen(self):
        status, out, err = self.screen
        self.assertEqual(status, 0, err)
        self.assertIn('excess price screen is included', out)
        self.assertIn('How well each screen ranks', out)
        with open(self.screen_json, encoding='utf-8') as f:
            data = json.load(f)
        res = data['results']
        self.assertEqual([r['market'] for r in res['markets']], [1, 4, 27])
        self.assertIn('excessPrice', res['markets'][0]['scores'])
        self.assertEqual(res['settings']['reps'], 49)
        self.assertEqual(len(res['calibration']['markets']), 3)
        self.assertEqual(res['evaluation']['markets'], 3)

    def test_calibrate(self):
        csv_path = os.path.join(self.dir, 'fits.csv')
        status, out, err = run_cli(['calibrate', self.panel, '--truth', self.truth, '--csv', csv_path])
        self.assertEqual(status, 0, err)
        self.assertIn('true mu', out)
        self.assertIn('fitted mu off by', out)
        with open(csv_path, newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(float(rows[0]['mu']), 0.5, delta=0.02)

    def test_calibrate_needs_sales(self):
        path = os.path.join(self.dir, 'prices_only.csv')
        write_csv(path, ['day', 'price_a', 'price_b'], price_rows(30))
        status, out, err = run_cli(['calibrate', path])
        self.assertEqual(status, 2)
        self.assertIn('no sales', err)

    def test_remedies(self):
        status, out, err = self.remedies
        self.assertEqual(status, 0, err)
        self.assertIn('Both learn and see all prices', out)
        self.assertIn('Rivals’ prices banned as an input', out)
        with open(self.remedies_json, encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['summary']['order'], ['baseline', 'own'])
        self.assertEqual(len(data['runs']), 4)
        own = data['summary']['scenarios']['own']['vsBaseline']['realisedGain']
        self.assertEqual(own['pairs'], 2)
        self.assertIn(own['pValue'], (0.5, 1.0))     # two pairs: exact p is 2/4 or 4/4

    def test_report(self):
        self.assertEqual(self.sweep[0], 0, self.sweep[2])
        path = os.path.join(self.dir, 'report.html')
        status, out, err = run_cli(['report', '--out', path, '--remedies', self.remedies_json,
                                    '--sweep', self.sweep_json, '--screen', self.screen_json])
        self.assertEqual(status, 0, err)
        with open(path, encoding='utf-8') as f:
            page = f.read()
        for bad in ('http://', 'https://', '<script', chr(0x2014)):   # chr: no em dash in this file
            self.assertNotIn(bad, page)
        for title in report.SECTION_TITLES.values():
            self.assertIn(report.e(title), page)
        self.assertIn('Quiet cartel: companion report', page)
        self.assertIn('prefers-color-scheme: dark', page)
        self.assertIn('synthetic', page)
        self.assertIn('legal advice', page)
        self.assertEqual(page.count('<svg'), 3)      # bar chart, heat map, scatter

    def test_report_escapes_text(self):
        with open(self.remedies_json, encoding='utf-8') as f:
            data = json.load(f)
        data['command'] = 'python -m quiet_cartel remedies <b>&'
        data['summary']['scenarios']['own']['label'] = '<img src=x onerror=alert(1)>'
        page = report.build_report(remedies=data, command='<script>')
        self.assertNotIn('<img', page)
        self.assertNotIn('<script', page)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', page)
        self.assertIn('remedies &lt;b&gt;&amp;', page)

    def test_error_exits(self):
        cases = [
            (['screen', os.path.join(self.dir, 'missing.csv')], 'No such file'),
            (['train', '--set', 'mu=abc'], 'mu must be a number'),
            (['train', '--set', 'nope=1'], "unknown setting 'nope'"),
            (['train', '--set', 'mu'], 'needs key=value'),
            (['train', '--preset', 'nope'], 'invalid choice'),
            (['report', '--out', os.path.join(self.dir, 'r.html'), '--remedies', self.screen_json],
             'is not saved remedies results'),
            (['sweep', '--x', 'mu=0.1', '--y', 'memory=1'], 'numeric setting'),
            (['remedies', '--scenarios', 'nope', '--runs', '1'], 'unknown scenario'),
        ]
        for argv, message in cases:
            status, out, err = run_cli(argv)
            self.assertEqual(status, 2, argv)
            self.assertIn(message, err, argv)
            self.assertNotIn('Traceback', err)
            self.assertEqual(len(err.strip().splitlines()), 1, err)

    def test_bad_csv_exit(self):
        path = os.path.join(self.dir, 'bad.csv')
        write_csv(path, ['day', 'price_a', 'price_b'], price_rows(30) + [[31, 'x', 1]])
        status, out, err = run_cli(['screen', path])
        self.assertEqual(status, 2)
        self.assertIn('row 32: price_a is not a number', err)

    def test_parse_value(self):
        self.assertEqual(cli.parse_value('learn,nash'), ['learn', 'nash'])
        self.assertEqual(cli.parse_value('2,2.5'), [2, 2.5])
        self.assertIs(cli.parse_value('True'), True)
        self.assertEqual(cli.parse_value('5e-5'), 5e-5)
        self.assertEqual(cli.parse_value('15'), 15)
        self.assertEqual(cli.parse_value('own'), 'own')


if __name__ == '__main__':
    unittest.main()
