"""End-to-end tests of the command-line companion (python -m loadbearing) and the sample data generator.

Every subcommand runs with small sizes through cli.main, with standard output captured. Run from the
repository root: python3 -m unittest discover -s tests/python -t .
"""
import contextlib
import importlib.util
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from loadbearing import calibrate, cli, experiments, model

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, 'data')
LOGBOOK = os.path.join(DATA, 'club_logbook.csv')
TESTS = os.path.join(DATA, 'jump_tests.csv')
TRUTH = os.path.join(DATA, 'jump_truth.csv')
APP = {'policy': 'rest', 'flag': 'model'}


def load_generator():
    """data/generate_logbook.py as a module (it is a script, not part of the package)."""
    spec = importlib.util.spec_from_file_location('generate_logbook', os.path.join(DATA, 'generate_logbook.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generate_logbook = load_generator()


def run(*argv):
    """(exit code, standard output, standard error) of one command."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


def read_json(path):
    """Strict JSON: NaN and Infinity, which Python would otherwise accept, are errors."""
    def refuse(name):
        raise ValueError(f'{name} is not JSON')
    with open(path, encoding='utf-8') as fh:
        return json.load(fh, parse_constant=refuse)


def read_rows(path):
    with open(path, encoding='utf-8') as fh:
        return model.parse_csv(fh.read())


class CompanionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='loadbearing-')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def ok(self, *argv):
        code, out, err = run(*argv)
        self.assertEqual(0, code, err)
        return out

    # ---------- the simulation commands ----------
    def test_module_entry_point(self):
        done = subprocess.run([sys.executable, '-m', 'loadbearing', '--help'], cwd=ROOT, capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        for command in ('season', 'flags', 'compare', 'pilot', 'trial', 'sweep', 'logbook', 'calibrate', 'report'):
            self.assertIn(command, done.stdout)

    def test_season(self):
        out = self.ok('season', '--seed', 3, '--json', self.path('season', 'season.json'),
                      '--matches-csv', self.path('season', 'matches.csv'), '--logbook', self.path('season', 'lb.csv'))
        for text in ('Light ignored', 'Days lost', 'Cup final', 'Flags raised', 'Final league table'):
            self.assertIn(text, out)
        res = model.run_season(dict(APP, seasonSeed=3))
        base = model.run_season({'policy': 'none', 'flag': 'model', 'seasonSeed': 3})
        doc = read_json(self.path('season', 'season.json'))
        self.assertEqual(res['injuriesTotal'], doc['summary']['injuriesTotal'])
        self.assertEqual(base['daysLost'], doc['baseline']['daysLost'])
        self.assertEqual(res['points'] - base['points'], doc['difference']['points'])
        self.assertEqual(res['flagsRaised'], doc['flags']['actedOn'])
        matches = read_rows(self.path('season', 'matches.csv'))
        self.assertEqual(['week', 'date', 'match', 'opponent', 'venue', 'result', 'margin', 'points', 'our_rating',
                          'opponent_rating', 'first_choice_xv'], matches[0])
        self.assertEqual(len(res['matches']), len(matches) - 1)
        logbook = read_rows(self.path('season', 'lb.csv'))
        self.assertEqual(cli.LOGBOOK_HEADER, logbook[0])
        self.assertGreater(len(logbook), 6000)

    def test_inquest(self):
        out = self.ok('inquest', '--seed', 3, '--policy', 'none', '--json', self.path('inquest', 'inquest.json'))
        for text in ('The inquest', 'Hidden', 'A rest that week', 'Soft-tissue injuries', 'In plain English'):
            self.assertIn(text, out.replace('hidden factors', 'Hidden'))
        doc = read_json(self.path('inquest', 'inquest.json'))
        ref = model.inquest({'policy': 'none', 'flag': 'model', 'seasonSeed': 3}, 3)
        self.assertEqual(ref['summary'], doc['summary'])
        self.assertEqual(len(ref['items']), len(doc['items']))
        self.assertEqual(model.run_season({'policy': 'none', 'flag': 'model'}, 3)['injuriesTotal'], len(doc['items']))

    def test_optimise(self):
        out = self.ok('optimise', '--seasons', 2, '--point-value', 8, '--workers', 1, '--csv', self.path('opt', 'o.csv'),
                      '--json', self.path('opt', 'o.json'))
        for text in ('The trade-off', 'Pays when', 'Best option by the worth of a league point', 'In plain English'):
            self.assertIn(text, out)
        ref = model.tradeoff(dict(APP), [101, 102])
        doc = read_json(self.path('opt', 'o.json'))
        self.assertEqual(len(ref['rows']), len(doc['rows']))
        self.assertEqual([r['dDays'] for r in ref['rows']], [r['dDays'] for r in doc['rows']])
        rows = read_rows(self.path('opt', 'o.csv'))
        self.assertEqual('option', rows[0][0])
        self.assertEqual(len(ref['rows']), len(rows) - 1)
        values = [float(r[4]) for r in rows[1:]]
        self.assertEqual(sorted(values, reverse=True), values)

    def test_optimise_all_lights_shares_the_common_options(self):
        out = experiments.run_optimise(dict(APP), [101], all_lights=True, workers=1)
        policies = [r['policy'] for r in out['rows']]
        self.assertEqual(1, policies.count('none'))
        self.assertEqual(1, policies.count('readiness'))
        self.assertEqual(5, policies.count('rotate'))
        self.assertEqual(set(model.FLAGS), {r['flag'] for r in out['rows'] if r['policy'] == 'rest'})

    def test_robustness(self):
        out = self.ok('robustness', '--seasons', 1, '--map', '--json', self.path('rob', 'r.json'))
        for text in ('The hidden truth', 'How much load spikes cause injury (hidden)', 'Pays below', 'In plain English'):
            self.assertIn(text, out)
        doc = read_json(self.path('rob', 'r.json'))
        ref = model.robustness(dict(APP), [201])
        self.assertEqual(ref['base']['auc'], doc['robustness']['base']['auc'])
        self.assertEqual(len(model.ASSUMPTIONS), len(doc['robustness']['rows']))
        self.assertEqual(15, len(doc['map']['cells']))

    def test_season_without_the_light_has_no_replay(self):
        out = self.ok('season', '--policy', 'none', '--seed', 2)
        self.assertIn('nothing to replay', out)
        self.assertNotIn('Light ignored', out)

    def test_settings_are_validated(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as stop:
                cli.main(['season', '--threshold', '7'])
        self.assertEqual(2, stop.exception.code)
        self.assertIn('outside 1 to 3', err.getvalue())

    def test_flags(self):
        out = self.ok('flags', '--seasons', 3, '--json', self.path('flags.json'))
        ev = model.evaluate_flags(APP, [1, 2, 3])
        for f in ev['flags']:
            self.assertIn(f"{f['auc']:.3f}", out)
        self.assertIn('Contact share', out)
        self.assertIn('Risk model trained on', out)
        doc = read_json(self.path('flags.json'))
        self.assertEqual([f['auc'] for f in ev['flags']], [f['auc'] for f in doc['result']['flags']])
        self.assertEqual(ev['historyRows'], doc['result']['historyRows'])

    def test_compare(self):
        out = self.ok('compare', '--seasons', 2, '--csv', self.path('compare', 'policies.csv'),
                      '--json', self.path('compare', 'policies.json'))
        self.assertIn('95% interval', out)
        rows = read_rows(self.path('compare', 'policies.csv'))
        self.assertEqual(['policy', 'metric', 'mean', 'sd', 'diff', 'lo', 'hi'], rows[0])
        self.assertEqual(len(model.POLICIES) * len(cli.COMPARE_METRICS), len(rows) - 1)
        self.assertEqual(set(model.POLICIES), {r[0] for r in rows[1:]})
        doc = read_json(self.path('compare', 'policies.json'))
        self.assertEqual([101, 102], doc['result']['seeds'])

    def test_pilot(self):
        out = self.ok('pilot', '--pairs', 3, '--json', self.path('pilot.json'))
        for text in ('True effect', 'Pilot looks better', 'Seasons needed', 'League points', "The coach's view",
                     'Followed by a quiet fortnight'):
            self.assertIn(text, out)
        doc = read_json(self.path('pilot.json'))
        ps = model.pilot_study(APP, 3)
        self.assertEqual(ps['trueEffect'], doc['result']['trueEffect'])
        self.assertEqual(ps['measured'], doc['result']['measured'])

    def test_trial_power_rises_with_clubs(self):
        out = self.ok('trial', '--pool-clubs', 8, '--pool-seasons', 2, '--seasons-per-club', 2, '--clubs', '4,8',
                      '--reps', 60, '--history-seasons', 1, '--flag', 'oracle', '--spike', 4, '--budget', 20,
                      '--json', self.path('trial.json'))
        self.assertIn('can never succeed', out)
        doc = read_json(self.path('trial.json'))['result']
        power = {r['clubs']: r['power'] for r in doc['results']}
        self.assertEqual(0, power[4])
        self.assertGreater(power[8], power[4])
        self.assertLess(doc['trueEffect'], 0)

    def test_trial_power_on_a_known_pool(self):
        rng = model.Rng(5)
        clubs = []
        for _ in range(16):
            level = 30 + 3 * rng.normal()
            seasons = []
            for _s in range(2):
                y = level + 2 * rng.normal()
                seasons.append({'none': {'injuriesTotal': y}, 'light': {'injuriesTotal': y - 4}})
            clubs.append(seasons)
        res = experiments.trial_power({'clubs': clubs}, [4, 8, 16], 1, 100, 1)
        power = [r['power'] for r in res['results']]
        self.assertEqual(0, power[0])
        self.assertTrue(power[0] < power[1] < power[2], power)
        self.assertAlmostEqual(-4, res['trueEffect'])
        self.assertTrue(res['results'][1]['exact'])
        self.assertFalse(res['results'][2]['exact'])

    def test_trial_rejects_a_pool_too_small(self):
        code, _, err = run('trial', '--pool-clubs', 4, '--clubs', '4,8')
        self.assertEqual(2, code)
        self.assertIn('needs a pool of at least that many clubs', err)

    def test_permutation_test_is_exact_when_small(self):
        rng = model.Rng(1)
        combos = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
        self.assertAlmostEqual(2 / 6, experiments.permutation_p([1, 2, 10, 11], 2, rng, 99, combos))
        self.assertEqual(1, experiments.permutation_p([5, 5, 5, 5], 2, rng, 99))

    def test_sweep(self):
        out = self.ok('sweep', '--param', 'threshold', '--values', '1.3,1.8', '--seasons', 2, '--flag', 'ewma',
                      '--workers', 1, '--csv', self.path('sweep', 'threshold.csv'),
                      '--json', self.path('sweep', 'threshold.json'))
        self.assertIn('Soft-tissue', out)
        rows = read_rows(self.path('sweep', 'threshold.csv'))
        header = ['param', 'value', 'seasons', 'policy', 'flag']
        for label in ('injuries', 'soft_tissue', 'days_lost', 'points'):
            header += [f'{label}_none', f'{label}_light', f'{label}_diff', f'{label}_lo', f'{label}_hi']
        self.assertEqual(header, rows[0])
        self.assertEqual([1.3, 1.8], [float(r[1]) for r in rows[1:]])
        self.assertEqual({'threshold'}, {r[0] for r in rows[1:]})
        doc = read_json(self.path('sweep', 'threshold.json'))
        self.assertEqual(2, len(doc['result']['rows']))

    def test_sweep_names_and_ranges(self):
        out = self.ok('sweep', '--param', 'rotate-after', '--values', '3', '--seasons', 1, '--workers', 1)
        self.assertIn('rotateAfter only matters under the rotate policy', out)
        code, _, err = run('sweep', '--param', 'spike', '--values', '1,9', '--seasons', 1)
        self.assertEqual(2, code)
        self.assertIn('spike must be between 0 and 4', err)

    # ---------- the logbook ----------
    def test_logbook_matches_the_model(self):
        out = self.ok('logbook', LOGBOOK, '--permutations', 60, '--json', self.path('logbook', 'lb.json'),
                      '--report', self.path('logbook', 'lb.html'), '--ratios-csv', self.path('logbook', 'ratios.csv'))
        with open(LOGBOOK, encoding='utf-8') as fh:
            book = model.read_logbook(model.parse_csv(fh.read()))
        an = model.analyse_logbook(book, {'threshold': 1.5, 'permutations': 60, 'seed': 1})
        doc = read_json(self.path('logbook', 'lb.json'))
        self.assertEqual([r['auc'] for r in an['results']], [r['auc'] for r in doc['result']['results']])
        self.assertEqual([r['p'] for r in an['results']], [r['p'] for r in doc['result']['results']])
        for r in an['results']:
            self.assertIn(f"{r['auc']:.3f}", out)
        self.assertIn('Highest ratios on the last day', out)
        with open(self.path('logbook', 'lb.html'), encoding='utf-8') as fh:
            page = fh.read()
        self.assertIn('<svg', page)
        self.assertNotIn('http://', page)
        self.assertNotIn('https://', page)
        ratios = read_rows(self.path('logbook', 'ratios.csv'))
        self.assertEqual(cli.RATIOS_HEADER, ratios[0])
        self.assertEqual(sum(1 for se in an['series'] for v in se['coupled'] if v == v), len(ratios) - 1)

    def test_logbook_only_all(self):
        out = self.ok('logbook', LOGBOOK, '--only', 'all', '--permutations', 0)
        self.assertIn('(all)', out)

    def test_bad_logbooks_exit_with_code_2(self):
        cases = {
            'no_load.csv': ('date,player\n2026-09-01,A. Player\n', 'Add minutes and rpe columns, or a load column'),
            'no_dates.csv': ('date,player,minutes,rpe\nyesterday,A. Player,60,6\n', 'No rows could be read'),
            'empty.csv': ('', 'The file is empty'),
        }
        for name, (text, message) in cases.items():
            with open(self.path(name), 'w', encoding='utf-8') as fh:
                fh.write(text)
            code, out, err = run('logbook', self.path(name))
            self.assertEqual(2, code, name)
            self.assertIn('error:', err)
            self.assertIn(message, err)
            self.assertEqual('', out)
        code, _, err = run('logbook', self.path('missing.csv'))
        self.assertEqual(2, code)
        self.assertIn('could not read the logbook', err)

    # ---------- calibration ----------
    def test_nelder_mead_minimises_rosenbrock(self):
        def rosenbrock(v):
            return (1 - v[0]) ** 2 + 100 * (v[1] - v[0] ** 2) ** 2
        res = calibrate.nelder_mead(rosenbrock, [-1.2, 1.0], step=0.5, max_evals=5000, xtol=1e-10, ftol=1e-14)
        self.assertTrue(res['converged'])
        self.assertAlmostEqual(1, res['x'][0], places=5)
        self.assertAlmostEqual(1, res['x'][1], places=5)
        self.assertLess(res['f'], 1e-10)

    def test_bounded_transform_round_trips(self):
        for x in (1.5, 7, 24.9):
            self.assertAlmostEqual(x, calibrate.bounded(calibrate.unbounded(x, 1, 25), 1, 25))
        self.assertLess(calibrate.bounded(-800, 1, 25), 25)
        self.assertGreater(calibrate.bounded(800, 1, 25), 1)

    def test_fit_recovers_every_parameter_from_frequent_clean_tests(self):
        """With a test every other day and no noise, all five parameters come back almost exactly."""
        lb = generate_logbook.logbook()
        names = [p['name'] for p in model.prepare({})['squad']['players']]
        loads = generate_logbook.daily_loads(lb['rows'], names, model.TOTAL_DAYS)
        truth = calibrate.read_truth(read_rows(TRUTH))['truth']
        for p in (0, 7, 20):
            t = truth[names[p]]
            clean = generate_logbook.banister(t, loads[p])
            days = list(range(0, model.TOTAL_DAYS, 2))
            fit = calibrate.fit_banister(loads[p], days, [clean[d] for d in days])
            for k in calibrate.PARAMS:
                self.assertAlmostEqual(1, fit[k] / t[k], delta=0.02, msg=f'{names[p]} {k}')

    def test_calibrate_recovers_the_truth(self):
        """Monday-only tests pin down p0, tau1, k1 and the day a hard session turns positive. They pin down fatigue's
        own time constant and gain (tau2, k2) much less well, because every test follows the same weekly pattern
        of loads; those two are held only to looser bounds."""
        out = self.ok('calibrate', '--logbook', LOGBOOK, '--tests', TESTS, '--truth', TRUTH,
                      '--json', self.path('calibrate.json'))
        self.assertIn('Squad median', out)
        self.assertIn('Against the truth (36 players)', out)
        doc = read_json(self.path('calibrate.json'))
        self.assertEqual(36, len(doc['players']))
        err = doc['truth']['params']
        self.assertLess(err['p0']['medianAbsError'], 0.1 * err['p0']['trueSd'])
        for k in ('tau1', 't0'):
            self.assertLess(err[k]['medianAbsError'], 0.75 * err[k]['trueSd'], k)
        self.assertLess(err['k1']['medianAbsError'], err['k1']['trueSd'])
        self.assertLess(err['tau1']['medianRelError'], 0.15)
        self.assertLess(err['k1']['medianRelError'], 0.35)
        self.assertLess(err['tau2']['medianRelError'], 0.6)
        self.assertLess(err['k2']['medianRelError'], 0.9)
        rmse = calibrate.median([p['rmse'] for p in doc['players']])
        self.assertTrue(0.6 < rmse < 0.9, rmse)  # the noise in the data is 0.8 cm
        for p in doc['players']:
            self.assertLess(p['tau2'], p['tau1'])
            self.assertGreaterEqual(p['k1'], 0)
            self.assertGreaterEqual(p['k2'], 0)

    def test_derived_days(self):
        t0, tpeak = calibrate.derived_days(1.0, 2.0, 40.0, 8.0)
        self.assertAlmostEqual(10 * math.log(2), t0)
        self.assertAlmostEqual(10 * math.log(10), tpeak)
        g = [1.0 * math.exp(-t / 40) - 2.0 * math.exp(-t / 8) for t in (t0, tpeak - 0.01, tpeak, tpeak + 0.01)]
        self.assertAlmostEqual(0, g[0])
        self.assertGreater(g[2], g[1])
        self.assertGreater(g[2], g[3])
        self.assertEqual((None, None), calibrate.derived_days(0.0, 2.0, 40.0, 8.0))

    def test_calibrate_bad_tests_file(self):
        with open(self.path('tests_bad.csv'), 'w', encoding='utf-8') as fh:
            fh.write('when,who,what,why\n')
        code, _, err = run('calibrate', '--logbook', LOGBOOK, '--tests', self.path('tests_bad.csv'))
        self.assertEqual(2, code)
        self.assertIn('needs date, player and result columns', err)

    # ---------- the report ----------
    def test_report(self):
        out = self.ok('report', '--out', self.path('report', 'nested', 'report.html'), '--seasons', 2, '--pairs', 2)
        self.assertIn('Wrote', out)
        with open(self.path('report', 'nested', 'report.html'), encoding='utf-8') as fh:
            page = fh.read()
        self.assertTrue(page.startswith('<!doctype html>'))
        self.assertGreaterEqual(page.count('<svg'), 5)
        self.assertNotIn('http://', page)
        self.assertNotIn('https://', page)
        for heading in ('How good is each warning light?', 'Could a one-season pilot tell?',
                        'Five ways to manage the squad', 'Settings used'):
            self.assertIn(heading, page)

    # ---------- the sample data ----------
    def test_generator_reproduces_the_committed_files(self):
        out = self.path('generated')
        done = subprocess.run([sys.executable, os.path.join(DATA, 'generate_logbook.py'), '--out', out],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(0, done.returncode, done.stderr)
        for name in ('club_logbook.csv', 'jump_tests.csv', 'jump_truth.csv'):
            with open(os.path.join(DATA, name), 'rb') as a, open(os.path.join(out, name), 'rb') as b:
                self.assertEqual(a.read(), b.read(), name)

    def test_jump_tests_skip_injured_mondays(self):
        lb = generate_logbook.logbook()
        names = {p['name']: k for k, p in enumerate(model.prepare({})['squad']['players'])}
        rows = read_rows(TESTS)
        self.assertEqual(['date', 'player', 'jump_cm'], rows[0])
        for date, name, _ in rows[1:]:
            day = model.parse_day(date) - model.SEASON_START
            self.assertEqual(0, day % 7)
            self.assertNotEqual(1, lb['season']['status'][names[name]][day])
        mondays = model.TOTAL_DAYS // 7
        self.assertLess(len(rows) - 1, 36 * mondays)

    @unittest.skipIf(shutil.which('node') is None, 'Node.js is not installed')
    def test_sample_logbook_is_the_app_sample(self):
        script = ("const {loadModel} = require('./tests/js/load_model.js'); const M = loadModel();"
                  "const h = ['date', 'player', 'position', 'session', 'minutes', 'rpe', 'injury'];"
                  "const lb = M.seasonLogbook({}, 1);"
                  "process.stdout.write(M.toCSV(h, lb.rows.map(function (r) { return h.map(function (k) "
                  "{ return r[k]; }); })));")
        done = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, timeout=120)
        self.assertEqual(0, done.returncode, done.stderr)
        with open(LOGBOOK, 'rb') as fh:
            self.assertEqual(fh.read(), done.stdout)


if __name__ == '__main__':
    unittest.main()
