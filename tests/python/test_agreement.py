"""Agreement between the JavaScript model and the Python port: every number must match to the last bit.

The reference outputs come from tests/js/dump_reference.js, run once with Node.js. Floats are compared with
exact equality (NaN matches NaN, and the sign of zero must match too).
"""
import json
import math
import os
import re
import shutil
import subprocess
import unittest

from loadbearing import model

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DUMP = os.path.join(ROOT, 'tests', 'js', 'dump_reference.js')
SPECIAL = {'NaN': math.nan, 'Infinity': math.inf, '-Infinity': -math.inf, '-0': -0.0, 'undefined': None}
LOGBOOK_HEADER = ['date', 'player', 'position', 'session', 'minutes', 'rpe', 'injury']


def decode(obj):
    """json object_hook: turns the dump's {"$js": ...} markers back into numbers (undefined becomes None)."""
    if len(obj) == 1 and '$js' in obj:
        return SPECIAL[obj['$js']]
    return obj


def parse_int(text):
    """json parse_int: JavaScript prints integral doubles above 2 ** 53 without a point, so read those as floats."""
    value = int(text)
    return value if abs(value) <= 2 ** 53 else float(text)


def snake(name):
    """The Python name of a JavaScript export, e.g. detExp -> det_exp, parseCSV -> parse_csv."""
    return re.sub(r'(?<=[a-z0-9])([A-Z])', r'_\1', name).lower()


def first_difference(js, py, path):
    """A description of the first difference between a reference value and a Python value, or None."""
    if isinstance(js, bool) or isinstance(py, bool):
        if type(js) is type(py) and js == py:
            return None
        return f'{path}: JavaScript {js!r}, Python {py!r}'
    if isinstance(js, (int, float)) and isinstance(py, (int, float)):
        if js != js and py != py:
            return None
        if js == py and (js != 0 or math.copysign(1, js) == math.copysign(1, py)):
            return None
        return f'{path}: JavaScript {js!r}, Python {py!r}'
    if isinstance(js, str) and isinstance(py, str):
        if js == py:
            return None
        k = next((i for i, (a, b) in enumerate(zip(js, py)) if a != b), min(len(js), len(py)))
        lo = max(0, k - 30)
        return f'{path}: strings differ at character {k}: JavaScript {js[lo:k + 30]!r}, Python {py[lo:k + 30]!r}'
    if js is None and py is None:
        return None
    if isinstance(js, list) and isinstance(py, list):
        if len(js) != len(py):
            return f'{path}: lengths differ: JavaScript {len(js)}, Python {len(py)}'
        for k, (a, b) in enumerate(zip(js, py)):
            found = first_difference(a, b, f'{path}[{k}]')
            if found:
                return found
        return None
    if isinstance(js, dict) and isinstance(py, dict):
        if set(js) != set(py):
            return (f'{path}: keys differ: only in JavaScript {sorted(set(js) - set(py))}, '
                    f'only in Python {sorted(set(py) - set(js))}')
        for k in js:
            found = first_difference(js[k], py[k], f'{path}.{k}')
            if found:
                return found
        return None
    return f'{path}: types differ: JavaScript {type(js).__name__} {js!r:.80}, Python {type(py).__name__} {py!r:.80}'


class AgreementTest(unittest.TestCase):
    """Builds the same outputs in Python and compares them with the JavaScript reference."""

    @classmethod
    def setUpClass(cls):
        node = shutil.which('node')
        if node is None:
            raise unittest.SkipTest('node was not found on PATH, so the JavaScript reference outputs cannot be built')
        done = subprocess.run([node, DUMP], cwd=ROOT, capture_output=True, encoding='utf-8', check=True)
        cls.ref = json.loads(done.stdout, object_hook=decode, parse_int=parse_int)

    def assertSame(self, js, py, path):
        found = first_difference(js, py, path)
        if found:
            self.fail(found)

    def test_constants(self):
        for name, value in self.ref['constants'].items():
            self.assertSame(value, getattr(model, name), name)

    def test_pure_functions(self):
        for group in self.ref['calls']:
            fn_name = group['fn']
            with self.subTest(fn=fn_name):
                fn = getattr(model, snake(fn_name))
                problems = []
                for k, (args, out) in enumerate(group['cases']):
                    found = first_difference(out, fn(*args), f'{fn_name} case {k}')
                    if found:
                        problems.append(found)
                if problems:
                    self.fail(f'{len(problems)} of {len(group["cases"])} cases differ, first: {problems[0]}')

    def test_rng(self):
        ref = self.ref['rng']
        for seed, values in zip(ref['seeds'], ref['next']):
            r = model.Rng(seed)
            self.assertSame(values, [r.next() for _ in values], f'Rng({seed}).next')
        for case in ref['weird']:
            r = model.Rng(case['seed'])
            self.assertSame(case['values'], [r.next() for _ in case['values']], f'Rng({case["seed"]!r})')
        mixed = ref['mixed']
        r = model.Rng(mixed['seed'])
        self.assertSame(mixed['open'], [r.open() for _ in mixed['open']], 'open')
        self.assertSame(mixed['normal'], [r.normal() for _ in mixed['normal']], 'normal')
        for case in mixed['ints']:
            self.assertSame(case['values'], [r.int_(case['n']) for _ in case['values']], f'int({case["n"]})')

    def test_seasons(self):
        for case in self.ref['seasons']:
            py = model.run_season(case['settings'], case.get('seed'), case.get('opts'))
            self.assertSame(case['out'], py, f'runSeason({case["settings"]}, {case.get("seed")})')

    def test_prepare(self):
        for case in self.ref['prepared']:
            ctx = model.prepare(case['settings'])
            py = {k: ctx[k] for k in ('model', 'cutoffs', 'historyRows', 'historyInjuries')}
            self.assertSame(case['out'], py, f'prepare({case["settings"]})')

    def test_player_series(self):
        ref = self.ref['series']
        res = model.run_season(ref['settings'], ref['seed'], {'keepDaily': True})
        players = model.prepare(ref['settings'])['squad']['players']
        py = [model.player_series(res, players[k]) for k in ref['players']]
        self.assertSame(ref['out'], py, 'playerSeries')

    def test_evaluate_flags(self):
        for case in self.ref['evaluations']:
            py = model.evaluate_flags(case['settings'], case['seeds'])
            self.assertSame(case['out'], py, 'evaluateFlags')

    def test_compare_policies(self):
        for case in self.ref['comparisons']:
            py = model.compare_policies(case['settings'], case['seeds'], case['policies'])
            self.assertSame(case['out'], py, f'comparePolicies({case["settings"]}, {case["seeds"]})')

    def test_pilot_study(self):
        for case in self.ref['pilots']:
            py = model.pilot_study(case['settings'], case['pairs'])
            self.assertSame(case['out'], py, f'pilotStudy({case["settings"]}, {case["pairs"]})')

    def test_inquest(self):
        for case in self.ref['inquests']:
            py = model.inquest(case['settings'], case['seed'])
            self.assertSame(case['out'], py, f'inquest({case["settings"]}, {case["seed"]})')

    def test_tradeoff(self):
        for case in self.ref['tradeoffs']:
            py = model.tradeoff(case['settings'], case['seeds'])
            self.assertSame(case['out'], py, f'tradeoff({case["settings"]}, {case["seeds"]})')
            self.assertSame(case['best'], [model.best_option(py['rows'], lam) for lam in (0, 5, 12, 40)], 'bestOption')
            pairs = [(-10, -2), (-10, 0), (0, 0), (5, 1), (5, -1), (0, 1)]
            self.assertSame(case['breakEvens'], [model.break_even(a, b) for a, b in pairs], 'breakEven')

    def test_robustness(self):
        ref = self.ref['robust']
        self.assertSame(ref['assumptions'], model.ASSUMPTIONS, 'ASSUMPTIONS')
        self.assertSame(ref['out'], model.robustness(ref['settings'], ref['seeds']), 'robustness')
        self.assertSame(ref['map'], model.robustness_map({'flag': 'model'}, [203], [0, 3], [0.6, 1.4]), 'robustnessMap')

    def test_calibration(self):
        ref = self.ref['calibration']
        rows = model.season_logbook({}, 2)['rows']
        book = model.read_logbook(model.parse_csv(model.to_csv(LOGBOOK_HEADER, [[r[k] for k in LOGBOOK_HEADER] for r in rows])))
        self.assertSame(ref['rowsHead'], model.hazard_rows(book)['rows'][:50], 'hazardRows')
        self.assertSame(ref['fit'], model.fit_spike_effect(book, {'truth': 2}), 'fitSpikeEffect')
        self.assertSame(ref['fitAll'], model.fit_spike_effect(book, {'only': 'all'}), 'fitSpikeEffect all')
        tiny = model.read_logbook(model.parse_csv('date,player,load\n2026-09-01,A,300\n'))
        self.assertSame(ref['tiny'], model.fit_spike_effect(tiny, {}), 'fitSpikeEffect tiny')

    def test_season_logbook(self):
        ref = self.ref['logbook']
        lb = model.season_logbook(ref['settings'], ref['seed'])
        self.assertEqual(ref['rowCount'], len(lb['rows']))
        self.assertSame(ref['firstRows'], lb['rows'][:len(ref['firstRows'])], 'seasonLogbook rows')
        csv = model.to_csv(LOGBOOK_HEADER, [[r[k] for k in LOGBOOK_HEADER] for r in lb['rows']])
        self.assertSame(ref['csv'], csv, 'toCSV of the season logbook')
        season = {k: lb['season'][k] for k in ref['season']}
        self.assertSame(ref['season'], season, 'seasonLogbook season')

    def test_analyse_logbook(self):
        ref = self.ref['logbook']
        book = model.read_logbook(model.parse_csv(ref['csv']))
        self.assertSame(ref['book'], book, 'readLogbook')
        for case in ref['analyses']:
            self.assertSame(case['out'], model.analyse_logbook(book, case['opts']), f'analyseLogbook({case["opts"]})')

    def test_messy_logbooks(self):
        for k, case in enumerate(self.ref['logbooks']):
            book = model.read_logbook(model.parse_csv(case['csv']))
            self.assertSame(case['book'], book, f'logbook {k}')
            if 'analysis' in case:
                py = model.analyse_logbook(book, case['analysis']['opts'])
                self.assertSame(case['analysis']['out'], py, f'logbook {k} analysis')


if __name__ == '__main__':
    unittest.main()
