"""Agreement test: the Python port must reproduce the JavaScript model exactly.

Runs ``tests/js/dump_reference.js`` with Node, recomputes every reference value
with ``quiet_cartel.model`` from the same inputs, and requires exact equality
of every number (to the last bit, including the sign of zero), list and dict.

Run from the repository root::

    python -m unittest discover -s tests/python -t .
"""

import json
import math
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quiet_cartel import model as qc  # noqa: E402

NODE = shutil.which('node')
DUMP = os.path.join(ROOT, 'tests', 'js', 'dump_reference.js')
SKIP_REASON = 'node is not on PATH, so the JavaScript reference outputs cannot be produced'

_SPECIAL = {'NaN': math.nan, 'Infinity': math.inf, '-Infinity': -math.inf, '-0': -0.0}


def _decode(obj):
    """JSON object hook: turn the dump's {"__float__": ...} markers back into floats."""
    if len(obj) == 1 and '__float__' in obj:
        return _SPECIAL[obj['__float__']]
    return obj


def _parse_int(text):
    """JSON integers are JavaScript doubles: beyond 2**53 they must be read as doubles too.

    JavaScript writes the double 235385266837019616 as "235385266837019620"
    (its shortest round-trip form); read as an exact int that is a different number.
    """
    value = int(text)
    return value if -2 ** 53 <= value <= 2 ** 53 else float(text)


def load_reference():
    proc = subprocess.run([NODE, DUMP], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError('dump_reference.js failed:\n' + proc.stderr.decode('utf-8', 'replace'))
    return json.loads(proc.stdout.decode('utf-8'), object_hook=_decode, parse_int=_parse_int)


# ------------------------------------------------------------ exact comparison

def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _show(v):
    text = repr(v)
    return text if len(text) <= 80 else text[:77] + '...'


def differences(expected, actual, path='ref', limit=12):
    """Every place (up to ``limit``) where ``actual`` is not exactly ``expected``."""
    found = []

    def walk(e, a, p):
        if len(found) >= limit:
            return
        if _is_num(e):
            if not _is_num(a):
                found.append('%s: expected the number %r, got %s %s' % (p, e, type(a).__name__, _show(a)))
            elif e != e:
                if a == a:
                    found.append('%s: expected NaN, got %r' % (p, a))
            elif a != e:
                found.append('%s: expected %r, got %r (difference %r)' % (p, e, a, a - e))
            elif e == 0 and math.copysign(1.0, e) != math.copysign(1.0, a):
                found.append('%s: expected %r, got %r (sign of zero)' % (p, float(e), float(a)))
            return
        if e is None or isinstance(e, (bool, str)):
            if type(a) is not type(e) or a != e:
                found.append('%s: expected %s, got %s' % (p, _show(e), _show(a)))
            return
        if isinstance(e, list):
            if not isinstance(a, list):
                found.append('%s: expected a list, got %s %s' % (p, type(a).__name__, _show(a)))
                return
            if len(a) != len(e):
                found.append('%s: expected %d items, got %d' % (p, len(e), len(a)))
            for i in range(min(len(e), len(a))):
                walk(e[i], a[i], '%s[%d]' % (p, i))
            return
        if isinstance(e, dict):
            if not isinstance(a, dict):
                found.append('%s: expected a dict, got %s %s' % (p, type(a).__name__, _show(a)))
                return
            missing = [k for k in e if k not in a]
            extra = [k for k in a if k not in e]
            if missing:
                found.append('%s: missing keys %s' % (p, missing))
            if extra:
                found.append('%s: unexpected keys %s' % (p, extra))
            for k in e:
                if k in a:
                    walk(e[k], a[k], '%s.%s' % (p, k))
            return
        found.append('%s: unexpected reference value %s' % (p, _show(e)))

    walk(expected, actual, path)
    return found


# ------------------------------------------------------------ Python versions of the dump's helpers

def loop_sum(xs):
    s = 0
    for x in xs:
        s += x
    return s


def market_view(mk, full):
    keys = ('n', 'm', 'nJoint', 'quality', 'cost', 'outside', 'mu', 'pN', 'pM', 'piN', 'piM',
            'csN', 'csM', 'grids', 'levels', 'nashIdx', 'monoIdx')
    out = {k: mk[k] for k in keys}
    out['profitSums'] = [[loop_sum(p) for p in lv] for lv in mk['profit']]
    if full or mk['levels'] * mk['n'] * mk['nJoint'] <= 4000:
        out['profit'] = mk['profit']
    else:
        sample = []
        for lv in range(mk['levels']):
            for i in range(mk['n']):
                for j in range((lv * 7 + i * 3) % 97, mk['nJoint'], 97):
                    sample.append([lv, i, j, mk['profit'][lv][i][j]])
        out['profitSample'] = sample
    return out


def trainer_state(tr):
    return {
        'cfg': tr.cfg, 'errors': tr.errors, 't': tr.t, 'converged': tr.converged, 'done': tr.done,
        'eps': tr.eps, 'last': tr.last, 'stable': tr.stable, 'learn': tr.learn, 'stateSize': tr.state_size,
        'stateTab': tr.state_tab, 'ruleTab': tr.rule_tab, 'best': tr.best, 'bestV': tr.best_v, 'Q': tr.Q,
        'qSum': [None if q is None else loop_sum(q) for q in tr.Q],
        'qFirst': [None if q is None else q[0] for q in tr.Q],
        'qLast': [None if q is None else q[-1] for q in tr.Q],
        'history': tr.history, 'acc': tr._acc, 'rngState': tr.rng.a, 'epsF': tr.eps_f, 'adoptAt': tr.adopt_at,
    }


def analyse(tr):
    mk = tr.market
    n = mk['n']
    nj = mk['nJoint']
    out = trainer_state(tr)
    out['market'] = market_view(mk, False)
    lc = qc.limit_cycle(tr)
    out['limitCycle'] = lc
    out['limitCycleFrom'] = [qc.limit_cycle(tr, j) for j in (0, nj - 1, nj // 3)]
    joints = (0, 1, nj - 1, tr.last)
    out['greedy'] = [tr.greedy_actions(j) for j in joints]
    out['greedyNext'] = [tr.greedy_next(j) for j in joints]
    out['nextAdopt'] = [tr.next_adopt(t) for t in (0, 1, 30000, 50000, 70001, 123457)]
    out['staticBR'] = [[qc.static_best_response(mk, i, j) for j in (0, tr.last, lc['states'][0])] for i in range(n)]
    out['outcome'] = qc.outcome_of(mk, lc['states'])
    out['outcomeAll'] = qc.outcome_of(mk, [0, 1, 2, nj - 1])
    out['summary'] = qc.summarise(tr)
    out['impulse'] = [qc.impulse_response(tr, {'deviator': d}) for d in range(n)]
    out['impulseCustom'] = qc.impulse_response(tr, {'deviator': n - 1, 'price': 0, 'horizon': 8})
    out['impulseBest'] = qc.impulse_response(tr, {'deviator': 0, 'price': 'best', 'horizon': 30,
                                                  'cycle': [lc['states'][0], 0]})
    out['impulseShort'] = qc.impulse_response(tr, {'deviator': 1, 'horizon': 1})
    out['impulseHorizons'] = [qc.impulse_response(tr, {'deviator': 0, 'horizon': h})
                              for h in (0, 2.7, 1000, math.nan, '7', -3, math.inf)]
    out['bestResponse'] = [qc.best_response_check(tr, i, lc['states']) for i in range(n)]
    out['bestResponseNoCycle'] = qc.best_response_check(tr, n - 1)
    prices = qc.observe(tr, {'days': 120})
    prices_alt = qc.observe(tr, {'days': 60, 'experiment': 0.2, 'seed': 5})
    out['prices'] = prices
    out['pricesAlt'] = prices_alt
    out['screens'] = qc.screens(prices, {'cost': mk['cost'], 'detail': True})
    out['screensAlt'] = qc.screens(prices_alt, {'cost': mk['cost'], 'detail': True, 'tol': 0.02, 'window': 5})
    out['screensPlain'] = qc.screens(prices_alt)
    out['perm'] = qc.permutation_test(prices, {'reps': 99, 'cost': mk['cost']})
    out['permAlt'] = qc.permutation_test(prices_alt, {'reps': 99, 'seed': 8, 'window': 5})
    return out


# ------------------------------------------------------------ the test

@unittest.skipIf(NODE is None, SKIP_REASON)
class AgreementTest(unittest.TestCase):
    """Every output of the Python port equals the JavaScript reference exactly."""

    maxDiff = None
    ref = None

    @classmethod
    def setUpClass(cls):
        cls.ref = load_reference()

    def same(self, expected, actual, path):
        found = differences(expected, actual, path)
        if found:
            self.fail('Python and JavaScript disagree:\n  ' + '\n  '.join(found))

    def test_constants(self):
        self.same(self.ref['constants'], {
            'LIMITS': qc.LIMITS, 'FIRM_TYPES': qc.FIRM_TYPES, 'MEMORY': qc.MEMORY, 'SHOCKS': qc.SHOCKS,
            'SCENARIOS': qc.SCENARIOS, 'CASE_MIX': qc.CASE_MIX, 'CASE_MU': qc.CASE_MU,
            'SCREEN_LIST': qc.SCREEN_LIST, 'defaultConfig': qc.default_config(),
        }, 'constants')

    def test_det_exp_and_det_log(self):
        self.same(self.ref['detExp'], [[x, qc.det_exp(x)] for x, _ in self.ref['detExp']], 'detExp')
        self.same(self.ref['detLog'], [[x, qc.det_log(x)] for x, _ in self.ref['detLog']], 'detLog')

    def test_round(self):
        self.same(self.ref['round'], [[x, d, qc.round_(x, d)] for x, d, _ in self.ref['round']], 'round')

    def test_rng(self):
        actual = []
        for case in self.ref['rng']:
            r = qc.Rng(case['seed'])
            values = [r.next() for _ in range(50)]
            ints = [r.int(k + 1) for k in range(20)]
            actual.append({'seed': case['seed'], 'values': values, 'ints': ints, 'state': r.a})
        self.same(self.ref['rng'], actual, 'rng')

    def test_stats(self):
        actual = []
        for case in self.ref['stats']:
            xs = case['xs']
            srt = qc.sorted_copy(xs)
            actual.append({'xs': xs, 'mean': qc.mean(xs), 'sd': qc.sd(xs), 'sorted': srt,
                           'quantiles': [[q, qc.quantile(srt, q)] for q, _ in case['quantiles']]})
        self.same(self.ref['stats'], actual, 'stats')

    def test_prices(self):
        actual = []
        for case in self.ref['prices']:
            p = case['input']
            q, c, o, mu = p['quality'], p['cost'], p['outside'], p['mu']
            pn = qc.nash_prices(q, c, o, mu)
            pm = qc.monopoly_prices(q, c, o, mu)
            mid = [(x + pm[i]) / 2 for i, x in enumerate(pn)]
            actual.append({
                'input': p, 'nash': pn, 'monopoly': pm,
                'sharesNash': qc.shares(pn, q, o, mu),
                'profitsNash': qc.profits_at(pn, q, c, o, mu),
                'profitsMid': qc.profits_at(mid, q, c, o, mu),
                'csNash': qc.consumer_surplus(pn, q, o, mu),
                'csMonopoly': qc.consumer_surplus(pm, q, o, mu),
            })
        self.same(self.ref['prices'], actual, 'prices')

    def test_markets(self):
        actual = []
        for case in self.ref['markets']:
            mk = qc.build_market(qc.validate_config(case['input'])['config'])
            n, m, nj = mk['n'], mk['m'], mk['nJoint']
            joints = (0, 1, nj - 1, nj // 2)
            actual.append({
                'input': case['input'], 'market': market_view(mk, False),
                'decoded': [qc.decode_joint(j, n, m) for j in joints],
                'encoded': [qc.encode_joint(qc.decode_joint(j, n, m), m) for j in joints],
                'nearest': [[qc.nearest_index(g, p) for p in (g[0] - 1, g[2] + 1e-9, (g[3] + g[4]) / 2, 100)]
                            for g in mk['grids']],
            })
        self.same(self.ref['markets'], actual, 'markets')

    def test_validate_config(self):
        actual = []
        for case in self.ref['validate']:
            v = qc.validate_config(case['input'])
            actual.append({'input': case['input'], 'config': v['config'], 'errors': v['errors']})
        self.same(self.ref['validate'], actual, 'validate')

    def test_training(self):
        for i, case in enumerate(self.ref['train']):
            with self.subTest(case=case['name']):
                out = analyse(qc.train(case['input']))
                out['name'] = case['name']
                out['input'] = case['input']
                self.same(case, out, 'train[%d:%s]' % (i, case['name']))

    def test_general_loop_matches_for_two_sellers(self):
        # The specialised two-seller loop is the one normally used; check the general loop too.
        keys = ('cfg', 't', 'converged', 'eps', 'epsF', 'learn', 'last', 'stable', 'best', 'bestV', 'Q', 'history',
                'acc', 'rngState')
        wanted = ('shared-vendor', 'learn-undercut', 'undercut-learn', 'demand-noise', 'adopt-nash', 'adopt-at-zero',
                  'adopt-late')
        for case in self.ref['train']:
            if case['name'] not in wanted:
                continue
            with self.subTest(case=case['name']):
                tr = qc.Trainer(case['input'])
                tr._fast = False
                tr.run_to_end()
                state = trainer_state(tr)
                self.same({k: case[k] for k in keys}, {k: state[k] for k in keys}, 'general[%s]' % case['name'])

    def test_stepwise_training(self):
        ref = self.ref['stepwise']
        tr = qc.Trainer(ref['input'])
        marks = []
        while not tr.run(7777):
            marks.append([tr.t, tr.eps, tr.stable, tr.last])
        out = trainer_state(tr)
        out['name'] = ref['name']
        out['input'] = ref['input']
        out['marks'] = marks
        out['summary'] = qc.summarise(tr)
        self.same(ref, out, 'stepwise')

    def test_adoption_setup(self):
        # Freshly built trainers: who learns, who has a Q table and a rule, and when the next adoption is.
        actual = []
        for case in self.ref['adoption']:
            tr = qc.Trainer(case['input'])
            actual.append({
                'name': case['name'], 'input': case['input'], 'eps': tr.eps, 'epsF': tr.eps_f, 'learn': tr.learn,
                'adoptAt': tr.adopt_at, 'hasQ': [q is not None for q in tr.Q],
                'hasRule': [r is not None for r in tr.rule_tab],
                'nextAdopt': [tr.next_adopt(t) for t in (0, 1, 29999, 30000, 30001, 40000, 50000, 60000, 60001, 1e7)],
            })
        self.same(self.ref['adoption'], actual, 'adoption')

    def test_stepwise_training_across_adoption(self):
        ref = self.ref['stepwiseAdopt']
        for fast in (True, False):
            with self.subTest(fast=fast):
                tr = qc.Trainer(ref['input'])
                tr._fast = fast
                marks = []
                while not tr.run(7777):
                    marks.append([tr.t, tr.eps, tr.stable, tr.last, list(tr.learn), list(tr.eps_f)])
                out = trainer_state(tr)
                out['name'] = ref['name']
                out['input'] = ref['input']
                out['marks'] = marks
                out['summary'] = qc.summarise(tr)
                self.same(ref, out, 'stepwiseAdopt')

    def test_pilot_runs(self):
        ref = self.ref['pilot']
        base = qc.validate_config(ref['baseInput'])['config']
        after, seed = ref['adoptAfter'], ref['seed']
        actual = {
            'baseInput': ref['baseInput'], 'adoptAfter': after, 'seed': seed, 'rules': qc.PILOT_RULES,
            'configs': [qc.pilot_config(base, rule, after, seed) for rule in qc.PILOT_RULES],
            'together': qc.together_config(base, seed),
            'defaults': [qc.pilot_config({}, 'match', 5, 9), qc.together_config({}, 9)],
            'runs': [qc.pilot_run(base, rule, after, seed) for rule in qc.PILOT_RULES],
        }
        self.same(ref, actual, 'pilot')

    def test_robustness_settings(self):
        ref = self.ref['robustness']
        bases = [qc.default_config(), dict(qc.default_config(), maxPeriods=7000000)]
        actual = {
            'TORNADO': qc.TORNADO, 'MAP_MU': qc.MAP_MU, 'MAP_DELTA': qc.MAP_DELTA, 'bases': bases,
            'settings': [[{'key': t['key'], 'low': qc.with_setting(base, t['key'], t['low'], 3),
                           'high': qc.with_setting(base, t['key'], t['high'], 4)} for t in qc.TORNADO]
                         for base in bases],
            'seedOnly': qc.with_setting(bases[0], 'seed', 5, 5),
            'mapCell': qc.with_setting(qc.with_setting(bases[0], 'mu', 0.05, 2), 'delta', 0.95, 2),
            'edges': [qc.with_setting({}, 'beta', 2.5e-6, 1), qc.with_setting({'maxPeriods': 0}, 'beta', 1e-6, 1),
                      qc.with_setting(bases[0], 'beta', 4e-6, 1), qc.with_setting(bases[1], 'beta', 3.9e-6, 0)],
        }
        self.same(ref, actual, 'robustness')
        # The slow-fading case really does get more rounds, and the base is never changed in place.
        self.assertEqual(ref['settings'][0][3]['low']['maxPeriods'], 6000000)
        self.assertEqual(ref['settings'][1][3]['low']['maxPeriods'], 7000000)
        self.assertEqual(bases[0], qc.default_config())

    def test_short_run(self):
        # No 10,000-period block yet, so the realised gain falls back on the cycle's gain.
        ref = self.ref['short']
        tr = qc.Trainer(ref['input'])
        finished = tr.run(ref['steps'])
        out = trainer_state(tr)
        out['name'] = ref['name']
        out['input'] = ref['input']
        out['steps'] = ref['steps']
        out['finished'] = finished
        out['summary'] = qc.summarise(tr)
        out['bestResponse'] = qc.best_response_check(tr, 0, out['summary']['cycle'])
        self.same(ref, out, 'short')

    def test_value_iteration_cap(self):
        # A discount factor raised after training keeps value iteration from settling in 5,000 sweeps.
        ref = self.ref['unsettled']
        cfg, steps, delta = ref['spec']
        tr = qc.Trainer(cfg)
        tr.run(steps)
        tr.cfg['delta'] = delta
        self.same(ref, {'spec': ref['spec'], 'out': qc.best_response_check(tr, 0)}, 'unsettled')

    def test_bootstrap_and_roc(self):
        self.same(self.ref['bootstrap'],
                  [{'args': c['args'], 'out': qc.bootstrap_mean(*c['args'])} for c in self.ref['bootstrap']],
                  'bootstrap')
        self.same(self.ref['roc'],
                  [{'scores': c['scores'], 'labels': c['labels'], 'out': qc.roc_curve(c['scores'], c['labels'])}
                   for c in self.ref['roc']], 'roc')
        self.same(self.ref['confusion'],
                  [{'args': c['args'], 'out': qc.confusion(*c['args'])} for c in self.ref['confusion']],
                  'confusion')
        ids = ('margin', 'stability', 'retaliation', 'snapBack', 'punishReturn', 'other')
        self.same(self.ref['screenScore'],
                  [{'sc': c['sc'], 'out': [qc.screen_score(c['sc'], i) for i in ids]} for c in self.ref['screenScore']],
                  'screenScore')

    def test_screens_on_fixed_prices(self):
        actual = []
        for case in self.ref['syntheticScreens']:
            p = case['prices']
            actual.append({
                'prices': p,
                'screens': qc.screens(p, {'detail': True, 'cost': [1, 1]}),
                'screensTight': qc.screens(p, {'tol': 0, 'window': 3}),
                'perm': qc.permutation_test(p, {'reps': 50, 'seed': 1}),
            })
        self.same(self.ref['syntheticScreens'], actual, 'syntheticScreens')

    def test_sorting(self):
        # Long arrays with ties, both zeros and both infinities: both sorts are stable, so they must agree.
        self.same(self.ref['sorting'], [{'xs': c['xs'], 'sorted': qc.sorted_copy(c['xs'])} for c in self.ref['sorting']],
                  'sorting')

    def test_aggregate(self):
        ref = self.ref
        with_nan = []
        for i, c in enumerate(ref['train'][:6]):
            s = dict(c['summary'])
            if i % 2:
                s['realisedGain'] = math.nan
            with_nan.append(s)
        all_nan = [dict(c['summary'], realisedGain=math.nan) for c in ref['train'][:3]]
        actual = {
            'fromTraining': qc.aggregate([c['summary'] for c in ref['train'][:6]]),
            'withNaN': qc.aggregate(with_nan),
            'allNaN': qc.aggregate(all_nan),
            'withShort': qc.aggregate([ref['short']['summary'], ref['train'][0]['summary'],
                                       ref['train'][1]['summary']]),
            'empty': qc.aggregate([]),
            'single': qc.aggregate([ref['train'][0]['summary']]),
            'fromScenarios': qc.aggregate(ref['scenarios']['runs']),
        }
        self.same(ref['aggregate'], actual, 'aggregate')

    def test_scenarios(self):
        ref = self.ref['scenarios']
        base = qc.validate_config(self.ref['cases']['baseInput'])['config']
        actual = {
            'base': base,
            'applied': [{'id': sc['id'], 'onDefault': qc.apply_scenario(qc.default_config(), sc['id']),
                         'onBase': qc.apply_scenario(base, sc['id'])} for sc in qc.SCENARIOS],
            'sparseBase': ref['sparseBase'], 'sparseIds': ref['sparseIds'],
            'onSparse': [qc.apply_scenario(ref['sparseBase'], i) for i in ref['sparseIds']],
            'byId': [qc.scenario_by_id(i) for i in ('own', 'nope')],
            'unknown': None,
            'runSpecs': ref['runSpecs'],
            'runs': [qc.run_scenario(base, i, seed) for i, seed in ref['runSpecs']],
        }
        try:
            qc.apply_scenario(base, 'nope')
        except ValueError as e:
            actual['unknown'] = str(e)
        self.same(ref, actual, 'scenarios')

    def test_cases(self):
        ref = self.ref['cases']
        base = qc.validate_config(ref['baseInput'])['config']
        cases = [qc.make_case(base, k, ref['seed'], ref['opts']) for k in ref['ks']]
        actual = {
            'baseInput': ref['baseInput'], 'seed': ref['seed'], 'ks': ref['ks'], 'opts': ref['opts'],
            'metas': [qc.case_config(base, k, ref['seed']) for k in ref['ks']],
            'cases': cases,
            'extraMetaSpecs': ref['extraMetaSpecs'],
            'extraMetas': [qc.case_config(base, k, seed) for k, seed in ref['extraMetaSpecs']],
            'evaluate': {'coordinated': qc.evaluate_screens(cases, 'coordinated'),
                         'highPrice': qc.evaluate_screens(cases, 'highPrice')},
        }
        self.same(ref, actual, 'cases')


class ComparisonHelperTest(unittest.TestCase):
    """The comparison itself must be strict, or the agreement test proves nothing."""

    def test_detects_differences(self):
        self.assertEqual(differences([1, 0.5, {'a': True}], [1.0, 0.5, {'a': True}]), [])
        self.assertTrue(differences(0.1 + 0.2, 0.3))
        self.assertTrue(differences(-0.0, 0.0))
        self.assertTrue(differences(0, -0.0))
        self.assertTrue(differences(math.nan, 1.0))
        self.assertEqual(differences(math.nan, math.nan), [])
        self.assertTrue(differences(True, 1))
        self.assertTrue(differences(1, True))
        self.assertTrue(differences(None, 0))
        self.assertTrue(differences([1, 2], [1, 2, 3]))
        self.assertTrue(differences({'a': 1}, {'a': 1, 'b': 2}))
        self.assertTrue(differences({'a': 1}, {}))

    def test_math_round_is_javascript_round(self):
        # math.floor(x + 0.5) gets these wrong; JavaScript's Math.round does not.
        self.assertEqual(qc.round_(0.49999999999999994, 0), 0)
        self.assertEqual(qc.round_(4503599627370497.0, 0), 4503599627370497)
        self.assertEqual(math.copysign(1.0, qc.round_(-0.4, 0)), -1.0)


if __name__ == '__main__':
    unittest.main()
