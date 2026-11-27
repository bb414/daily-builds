"""Unit tests of the Python model on its own: determinism, ranges, invariants and edge cases."""
import datetime
import math
import unittest

from loadbearing import model
import loadbearing


def season_csv(rows):
    """A small logbook as CSV text from (date, player, minutes, rpe, injury) tuples."""
    return model.to_csv(['date', 'player', 'minutes', 'rpe', 'injury'], [list(r) for r in rows])


class PackageTest(unittest.TestCase):
    def test_public_api(self):
        self.assertEqual('1.0', loadbearing.__version__)
        self.assertEqual(model.VERSION, loadbearing.__version__)
        for name in model.__all__:
            self.assertIs(getattr(model, name), getattr(loadbearing, name))


class MathsTest(unittest.TestCase):
    def test_det_exp_is_close_to_exp(self):
        for k in range(-6900, 6900, 7):
            x = k * 0.1013
            self.assertLess(abs(model.det_exp(x) - math.exp(x)) / math.exp(x), 1e-15)

    def test_det_log_is_close_to_log(self):
        for k in range(-3000, 3000, 7):
            x = 1.37 * 10 ** (k / 10)
            self.assertLess(abs(model.det_log(x) - math.log(x)), 1e-15 * max(1, abs(math.log(x))))
        self.assertAlmostEqual(model.det_log(5e-324), math.log(5e-324), places=12)
        self.assertAlmostEqual(model.det_log(1.7976931348623157e308), math.log(1.7976931348623157e308), places=12)

    def test_special_values(self):
        self.assertTrue(math.isnan(model.det_exp(math.nan)))
        self.assertEqual(math.inf, model.det_exp(800))
        self.assertEqual(0, model.det_exp(-800))
        self.assertEqual(1, model.det_exp(0))
        self.assertEqual(0, model.det_log(1))
        self.assertEqual(-math.inf, model.det_log(0))
        self.assertEqual(math.inf, model.det_log(math.inf))
        self.assertTrue(math.isnan(model.det_log(-1)))

    def test_inv_norm_inverts_norm_cdf(self):
        for k in range(1, 1000):
            p = k / 1000
            self.assertLess(abs(model.norm_cdf(model.inv_norm(p)) - p), 2e-7)
        self.assertEqual(-8.5, model.inv_norm(0))
        self.assertEqual(8.5, model.inv_norm(1))
        self.assertEqual(0, model.inv_norm(0.5))
        self.assertAlmostEqual(0.975, model.norm_cdf(1.959963984540054), delta=7.5e-8)

    def test_clamp_and_round_half_up(self):
        self.assertEqual(3, model.clamp(5, 1, 3))
        self.assertEqual(1, model.clamp(-2, 1, 3))
        self.assertTrue(math.isnan(model.clamp(math.nan, 1, 3)))
        self.assertEqual(3, model.round_half_up(2.5))
        self.assertEqual(-2, model.round_half_up(-2.5))
        self.assertEqual(-1, model.round_half_up(-1.2))
        self.assertIsInstance(model.round_half_up(7.2), int)
        self.assertTrue(math.isnan(model.round_half_up(math.nan)))


class RngTest(unittest.TestCase):
    def test_deterministic(self):
        a, b = model.Rng(5), model.Rng(5)
        self.assertEqual([a.next() for _ in range(100)], [b.next() for _ in range(100)])
        self.assertNotEqual(model.Rng(5).next(), model.Rng(6).next())

    def test_ranges(self):
        r = model.Rng(11)
        for _ in range(5000):
            self.assertTrue(0 <= r.next() < 1)
            self.assertTrue(0 < r.open() < 1)
        self.assertEqual(set(range(7)), {r.int_(7) for _ in range(1000)})

    def test_normal_moments(self):
        r = model.Rng(3)
        xs = [r.normal() for _ in range(20000)]
        self.assertLess(abs(model.mean(xs)), 0.03)
        self.assertLess(abs(model.sd(xs) - 1), 0.03)

    def test_seeds_wrap_like_unsigned_32_bit(self):
        self.assertEqual(4294967295, model.Rng(-1).s)
        self.assertEqual(5, model.Rng(2 ** 32 + 5).s)
        self.assertEqual(3, model.Rng(3.7).s)
        self.assertEqual(0, model.Rng(math.nan).s)

    def test_hash_seed(self):
        h = model.hash_seed(7, 101)
        self.assertEqual(h, model.hash_seed(7, 101))
        self.assertTrue(0 <= h < 2 ** 32)
        self.assertNotEqual(model.hash_seed(1, 2), model.hash_seed(2, 1))
        self.assertEqual(model.hash_seed(-1), model.hash_seed(4294967295))
        self.assertEqual(model.hash_seed(2.9), model.hash_seed(2))
        self.assertEqual(model.hash_seed('15'), model.hash_seed(15))


class SettingsTest(unittest.TestCase):
    def test_defaults(self):
        S = model.with_defaults()
        self.assertEqual(model.DEFAULTS, S)
        S['policy'] = 'rest'
        self.assertEqual('none', model.DEFAULTS['policy'])

    def test_out_of_range_values_are_clamped(self):
        S = model.with_defaults({'threshold': 9, 'budget': 0, 'intensity': 2, 'rotateAfter': 2.7, 'restTraining': -1,
                                 'spike': 9, 'contactScale': -1, 'historySeasons': 99})
        self.assertEqual((3.0, 1, 1.3, 2, 0, 4, 0, 6), (S['threshold'], S['budget'], S['intensity'], S['rotateAfter'],
                                                     S['restTraining'], S['spike'], S['contactScale'],
                                                     S['historySeasons']))
        S = model.with_defaults({'threshold': 0.2, 'budget': 99, 'rotateAfter': 50, 'historySeasons': 0})
        self.assertEqual((1.0, 50, 10, 1), (S['threshold'], S['budget'], S['rotateAfter'], S['historySeasons']))

    def test_invalid_choices_are_replaced(self):
        S = model.with_defaults({'policy': 'bogus', 'flag': 'nope', 'preseason': 'STEEP'})
        self.assertEqual(('none', 'ewma', 'gradual'), (S['policy'], S['flag'], S['preseason']))

    def test_values_are_coerced_like_javascript(self):
        S = model.with_defaults({'threshold': '1.7', 'budget': ' 12 ', 'squadSeed': -1, 'seasonSeed': 3.9,
                                 'gradedReturn': 0, 'unknown': 5, 'spike': None})
        self.assertEqual(1.7, S['threshold'])
        self.assertEqual(12, S['budget'])
        self.assertEqual(4294967295, S['squadSeed'])
        self.assertEqual(3, S['seasonSeed'])
        self.assertIs(False, S['gradedReturn'])
        self.assertEqual(2.0, S['spike'])
        self.assertNotIn('unknown', S)
        self.assertIs(True, model.with_defaults({'gradedReturn': 'false'})['gradedReturn'])
        self.assertEqual(model.DEFAULTS['threshold'], model.with_defaults({'threshold': 'abc'})['threshold'])
        self.assertEqual(model.DEFAULTS['spike'], model.with_defaults({'spike': float('inf')})['spike'])


class SquadTest(unittest.TestCase):
    def test_squad(self):
        squad = model.make_squad(7)
        players = squad['players']
        self.assertEqual(36, len(players))
        self.assertEqual(list(range(36)), [p['id'] for p in players])
        self.assertEqual(36, len({p['name'] for p in players}))
        for g in model.GROUPS:
            group = [p for p in players if p['group'] == g['id']]
            self.assertEqual(g['count'], len(group))
            self.assertEqual(list(range(1, g['count'] + 1)), [p['depth'] for p in group])
            self.assertEqual(sorted((p['ability'] for p in group), reverse=True), [p['ability'] for p in group])
        for p in players:
            self.assertTrue(56 <= p['ability'] <= 86)
            self.assertTrue(19 <= p['age'] <= 33)
            self.assertTrue(40 <= p['offLoad'] <= 180)
            self.assertTrue(0.85 <= p['rpeBias'] <= 1.15)
            self.assertTrue(0 <= p['prior'] <= 4)
            self.assertGreater(p['frailty'], 0)
        self.assertEqual(11, len(squad['opponents']))
        self.assertTrue(all(64 <= o['rating'] <= 77 for o in squad['opponents']))
        self.assertEqual(15, len(set(squad['bestXV'])))
        for slot, pid in zip(model.SLOTS, squad['bestXV']):
            self.assertEqual(slot[1], players[pid]['group'])

    def test_deterministic_and_seeded(self):
        self.assertEqual(model.make_squad(3), model.make_squad(3))
        self.assertNotEqual(model.make_squad(3)['players'][0]['name'], model.make_squad(4)['players'][0]['name'])


class SeasonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = model.run_season({}, 1)
        cls.daily = model.run_season({'policy': 'rest', 'flag': 'model'}, 2, {'keepDaily': True})

    def test_injury_totals(self):
        for res in (self.res, self.daily):
            injuries = res['injuries']
            self.assertEqual(res['injuriesTotal'], res['nc'] + res['contact'])
            self.assertEqual(res['injuriesTotal'], len(injuries))
            self.assertEqual(res['inMatch'], len([i for i in injuries if i['setting'] != 'training']))
            self.assertGreaterEqual(res['daysLost'], 0)
            self.assertEqual(res['daysLost'], sum(min(i['days'], model.SEASON_DAYS - 1 - i['day']) for i in injuries))
            for inj in injuries:
                self.assertTrue(2 <= inj['days'] <= 120)
                self.assertTrue(0 <= inj['day'] < model.SEASON_DAYS)
            self.assertTrue(5 <= res['injuriesTotal'] <= 120)

    def test_matches_and_points(self):
        res = self.res
        league = [m for m in res['matches'] if m['type'] == 'L']
        self.assertEqual(24, len(res['matches']))
        self.assertEqual(22, len(league))
        self.assertEqual(['League round %d' % k for k in range(1, 23)], [m['label'] for m in league])
        cup = [m for m in res['matches'] if m['type'] == 'C']
        self.assertEqual('Cup semi-final', cup[0]['label'])
        self.assertEqual('Cup final' if cup[0]['margin'] > 0 else 'Third-place play-off', cup[1]['label'])
        self.assertEqual(res['finalWon'], cup[1]['stage'] == 'final' and cup[1]['result'] == 'W')
        self.assertEqual(res['points'], sum(m['points'] for m in league))
        self.assertEqual(22, res['wins'] + res['draws'] + res['losses'])
        self.assertTrue(all(league.count(m) == 1 for m in league))
        self.assertTrue(all([m['opponent'] for m in league].count(k) == 2 for k in range(11)))
        final = res['matches'][-1]
        self.assertEqual(res['finalStage'], final['stage'])
        self.assertEqual(res['finalBestXV'], final['bestXVPlaying'])
        for m in res['matches']:
            self.assertEqual(15, len(m['starters']))
            self.assertEqual(8, len(m['bench']))
            self.assertEqual({'W': m['margin'] > 0, 'D': m['margin'] == 0, 'L': m['margin'] < 0}[m['result']], True)
        self.assertTrue(40 < res['meanRating'] < 90)

    def test_league_table(self):
        res = self.res
        table = res['table']
        self.assertEqual(list(range(1, 13)), [r['position'] for r in table])
        ours = [r for r in table if r['us']]
        self.assertEqual(1, len(ours))
        self.assertEqual(model.CLUB, ours[0]['name'])
        self.assertEqual(res['points'], ours[0]['points'])
        self.assertEqual(res['position'], ours[0]['position'])
        self.assertEqual(0, sum(r['diff'] for r in table))
        self.assertEqual(sorted((r['points'] for r in table), reverse=True), [r['points'] for r in table])

    def test_weekly_flags(self):
        for res in (self.res, self.daily):
            self.assertEqual(model.WEEKS, len(res['weekly']))
            self.assertEqual(res['flagsRaised'], sum(len(w['flags']) for w in res['weekly']))
            self.assertEqual(res['flagWeeks'], sum(w['available'] for w in res['weekly']))
            for wk in res['weekly']:
                self.assertTrue(wk['available'] <= 36)
                self.assertTrue(set(wk['flags']) <= set(range(36)))
        self.assertGreater(self.daily['rests'], 0)

    def test_daily_arrays(self):
        res = self.daily
        for name in ('load', 'minutes', 'kinds', 'status'):
            self.assertEqual(36, len(res[name]))
            self.assertTrue(all(len(row) == model.TOTAL_DAYS for row in res[name]))
        for p in range(36):
            for i in range(model.TOTAL_DAYS):
                self.assertGreaterEqual(res['load'][p][i], 0)
                self.assertEqual(res['minutes'][p][i] > 0, res['load'][p][i] > 0)
                self.assertIn(res['kinds'][p][i], range(6))
                self.assertIn(res['status'][p][i], range(4))
        for inj in res['injuries']:
            day = inj['day'] + model.HIST + 1
            if day < model.TOTAL_DAYS:
                self.assertEqual(1, res['status'][inj['player']][day])

    def test_deterministic_and_independent_of_the_cache(self):
        self.assertEqual(self.res, model.run_season({}, 1))
        ctx = model.prepare({})
        self.assertIs(ctx, model.prepare({'policy': 'rest', 'threshold': 2}))
        model._CACHE.clear()
        self.assertIsNot(ctx, model.prepare({}))
        self.assertEqual(ctx['model'], model.prepare({})['model'])
        self.assertEqual(self.res, model.run_season({}, 1))

    def test_cache_key_and_size(self):
        self.assertIsNot(model.prepare({}), model.prepare({'budget': 20}))
        saved = dict(model._CACHE)
        try:
            model._CACHE.clear()
            for k in range(41):
                model._CACHE['filler %d' % k] = {'n': k}
            model.prepare({})
            self.assertEqual(41, len(model._CACHE))
            self.assertNotIn('filler 0', model._CACHE)
        finally:
            model._CACHE.clear()
            model._CACHE.update(saved)

    def test_season_seed_setting(self):
        self.assertEqual(model.run_season({}, 2), model.run_season({'seasonSeed': 2}))

    def test_player_series(self):
        players = model.prepare({'policy': 'rest', 'flag': 'model'})['squad']['players']
        series = model.player_series(self.daily, players[4])
        for name in ('fitness', 'fatigue', 'ewma', 'coupled'):
            self.assertEqual(model.TOTAL_DAYS, len(series[name]))
        self.assertEqual(model.TOTAL_DAYS // 7, len(series['weekly']))
        self.assertTrue(all(math.isnan(v) for v in series['coupled'][:28]))
        self.assertFalse(any(math.isnan(v) for v in series['coupled'][28:]))
        self.assertAlmostEqual(sum(self.daily['load'][4]), sum(series['weekly']), places=6)


class StatsTest(unittest.TestCase):
    def test_auc_hand_checked(self):
        self.assertEqual(1, model.auc([1, 2, 3, 4], [0, 0, 1, 1]))
        self.assertEqual(0, model.auc([4, 3, 2, 1], [0, 0, 1, 1]))
        self.assertEqual(0.5, model.auc([1, 1, 1, 1], [0, 1, 0, 1]))
        self.assertEqual(0.75, model.auc([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]))
        self.assertEqual(0.875, model.auc([1, 2, 2, 3], [0, 1, 0, 1]))
        self.assertTrue(math.isnan(model.auc([1, 2, 3], [0, 0, 0])))
        self.assertTrue(math.isnan(model.auc([1, 2, 3], [1, 1, 1])))

    def test_roc_and_confusion(self):
        pts = model.roc_curve([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1])
        self.assertEqual([0, 0], pts[0])
        self.assertEqual([1, 1], pts[-1])
        c = model.confusion([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1], 0.35)
        self.assertEqual((2, 1, 0, 1, 3), (c['tp'], c['fp'], c['fn'], c['tn'], c['flagged']))
        self.assertEqual((0.75, 2 / 3, 1), (c['share'], c['precision'], c['recall']))
        self.assertTrue(math.isnan(model.confusion([1], [0], 5)['precision']))

    def test_summaries(self):
        self.assertEqual(2.5, model.quantile([1, 2, 3, 4], 0.5))
        self.assertEqual(4, model.quantile([1, 2, 3, 4], 1))
        self.assertTrue(math.isnan(model.quantile([], 0.5)))
        self.assertTrue(math.isnan(model.quantile([1, 2], 1.5)))
        self.assertEqual([-1, 0.5, 2], model.sort_numbers([2, -1, 0.5]))
        self.assertEqual(2.5, model.mean([1, 2, 3, 4]))
        self.assertTrue(math.isnan(model.mean([])))
        self.assertAlmostEqual(math.sqrt(5 / 3), model.sd([1, 2, 3, 4]), places=15)
        self.assertEqual(0, model.sd([5]))

    def test_boot_mean(self):
        lo, hi = model.boot_mean([1, 2, 3, 4, 5], 11)
        self.assertTrue(1 <= lo <= 3 <= hi <= 5)
        self.assertEqual([lo, hi], model.boot_mean([1, 2, 3, 4, 5], 11))
        self.assertTrue(all(math.isnan(v) for v in model.boot_mean([], 1)))

    def test_power_is_monotone_in_seasons(self):
        for delta, sigma in ((-2, 1.8), (-1, 3), (0.5, 2)):
            power = [model.power_two_sample(delta, sigma, n) for n in range(1, 400)]
            self.assertTrue(all(a <= b for a, b in zip(power, power[1:])))
            self.assertGreater(power[-1], 0.8)
            needed = model.seasons_for(delta, sigma, 0.8)
            self.assertGreaterEqual(model.power_two_sample(delta, sigma, needed), 0.8)
            self.assertLess(model.power_two_sample(delta, sigma, needed - 1), 0.8)
        self.assertAlmostEqual(0.05, model.power_two_sample(0, 3, 10), places=6)
        self.assertEqual(1, model.power_two_sample(2, 0, 10))
        self.assertEqual(0.05, model.power_two_sample(0, 0, 10))
        self.assertEqual(math.inf, model.seasons_for(0, 3, 0.8))


class CsvTest(unittest.TestCase):
    def test_parse_csv_edge_cases(self):
        self.assertEqual([['x, y', 'z'], ['he said "hi"', '2']], model.parse_csv('"x, y",z\n"he said ""hi""",2\n'))
        self.assertEqual([['a', 'b'], ['1', '2']], model.parse_csv('a,b\r\n1,2\r\n'))
        self.assertEqual([['date', 'player'], ['2026-01-01', 'A']],
                         model.parse_csv('\ufeffdate;player\n2026-01-01;A\n'))
        self.assertEqual([['a', 'b', 'c', 'd']], model.parse_csv('a;b,c\td'))
        self.assertEqual([['multi\nline', '2']], model.parse_csv('"multi\nline",2\n'))
        self.assertEqual([[' a ']], model.parse_csv('\n\n  \n a \n'))
        self.assertEqual([['', '']], model.parse_csv('a\n,\n')[1:])
        self.assertEqual([['unterminated,1\n2']], model.parse_csv('"unterminated,1\n2'))
        self.assertEqual([['a"b', 'c']], model.parse_csv('a"b,c'))
        self.assertEqual([], model.parse_csv(''))
        self.assertEqual([], model.parse_csv('\ufeff'))

    def test_to_csv_formats_numbers_like_javascript(self):
        text = model.to_csv(['v'], [[4.0], [6.5], [1e21], [1e-7], [-0.0], [math.nan], [math.inf], [True], [None],
                                    [123456789012.0], [0.1 + 0.2], ['say "hi"'], ['a,b'], ['a;b'], ['two\nlines']])
        self.assertEqual('v\n4\n6.5\n1e+21\n1e-7\n0\nNaN\nInfinity\ntrue\n\n123456789012\n0.30000000000000004\n'
                         '"say ""hi"""\n"a,b"\n"a;b"\n"two\nlines"\n', text)

    def test_round_trip(self):
        rows = [['2026-01-01', 'A. Ashworth', 'say "hi", then; go', '60'], ['2026-01-02', 'B', '', 'x\ny']]
        header = ['date', 'player', 'note', 'n']
        self.assertEqual([header] + rows, model.parse_csv(model.to_csv(header, rows)))


class LogbookTest(unittest.TestCase):
    def test_errors(self):
        self.assertEqual('The file is empty.', model.read_logbook([])['error'])
        self.assertIn('date column', model.read_logbook([['date', 'minutes']])['error'])
        self.assertIn('rpe columns', model.read_logbook([['date', 'player', 'minutes']])['error'])
        unreadable = model.parse_csv('date,player,load\nbad,A,1\n')
        self.assertIn('No rows could be read', model.read_logbook(unreadable)['error'])
        long = model.parse_csv('date,player,load\n2020-01-01,A,10\n2026-01-01,A,10\n')
        self.assertIn('more than three years', model.read_logbook(long)['error'])

    def test_warnings(self):
        one = model.read_logbook(model.parse_csv('date,player,load\n2026-01-01,A,10\nnope,A,10\n'))
        self.assertEqual('1 row was skipped (unreadable date, empty player or load).', one['warnings'][0])
        self.assertIn('Less than five weeks', one['warnings'][1])
        two = model.read_logbook(model.parse_csv('date,player,load\n2026-01-01,A,10\n2026-01-02,,10\n'
                                                 '2026-01-03,A,9000\n2026-01-04,A,-1\n'))
        self.assertEqual('3 rows were skipped (unreadable date, empty player or load).', two['warnings'][0])

    def test_columns_dates_and_loads(self):
        book = model.read_logbook(model.parse_csv('Date;Athlete;Duration;sRPE\n05/09/2026;Ann;60;5\n'
                                                  '2026-09-05;Ann;30;4\n2026-09-07;Bo;10;2\n'))
        self.assertEqual(['Ann', 'Bo'], book['names'])
        self.assertEqual(model.parse_day('2026-09-05'), book['start'])
        self.assertEqual(3, book['span'])
        self.assertEqual([420.0, 0.0, 0.0], book['loads'][0])
        self.assertEqual([0.0, 0.0, 20.0], book['loads'][1])
        mixed = model.read_logbook(model.parse_csv('date,player,load,minutes,rpe\n2026-01-01,A,,30,4\n'
                                                   '2026-01-02,A,0x10,,\n2026-01-03,A,7,30,4\n'))
        self.assertEqual([120.0, 16.0, 7.0], mixed['loads'][0])

    def test_injuries(self):
        text = season_csv([('2026-01-01', 'A', 60, 5, 'no'), ('2026-01-02', 'A', 60, 5, 'hamstring'),
                           ('2026-01-04', 'A', 60, 5, 'hamstring again'), ('2026-01-09', 'A', 60, 5, 'Contact knee'),
                           ('2026-01-09', 'B', 60, 5, '0'), ('2026-01-10', 'B', 60, 5, 'none')])
        book = model.read_logbook(model.parse_csv(text))
        self.assertEqual([{'player': 0, 'day': 1, 'type': 'non-contact'}, {'player': 0, 'day': 8, 'type': 'contact'}],
                         book['injuries'])

    def test_analyse_season_logbook(self):
        lb = model.season_logbook({}, 2)
        header = ['date', 'player', 'position', 'session', 'minutes', 'rpe', 'injury']
        csv = model.to_csv(header, [[r[k] for k in header] for r in lb['rows']])
        book = model.read_logbook(model.parse_csv(csv))
        self.assertEqual([], book['warnings'])
        self.assertEqual(36, len(book['names']))
        self.assertEqual(model.TOTAL_DAYS - 1, book['span'])  # the final Sunday has no sessions
        self.assertEqual(model.SEASON_START, book['start'])
        self.assertTrue(all(1 <= r['rpe'] <= 10 and r['minutes'] >= 1 for r in lb['rows']))
        out = model.analyse_logbook(book, {'permutations': 10})
        self.assertEqual('non-contact', out['only'])
        self.assertEqual(10, out['permutations'])
        self.assertGreater(out['rows'], 0)
        self.assertEqual(['coupled', 'uncoupled', 'ewma'], [r['id'] for r in out['results']])
        for r in out['results']:
            self.assertTrue(0 < r['p'] <= 1)
            self.assertTrue(0 <= r['auc'] <= 1)
        ewma = [x['ewma'] for x in out['latest']]
        self.assertEqual(sorted(ewma, reverse=True), ewma)

    def test_too_few_injuries_skip_the_permutation_test(self):
        rows = [(model.format_day(model.parse_day('2026-08-03') + d), 'A', 60, 5, 'calf' if d == 50 else '')
                for d in range(70)]
        out = model.analyse_logbook(model.read_logbook(model.parse_csv(season_csv(rows))))
        self.assertEqual(0, out['permutations'])
        self.assertNotIn('p', out['results'][0])
        self.assertEqual(1, out['positives'])


class DatesTest(unittest.TestCase):
    def test_round_trips(self):
        for z in range(-800000, 800000, 997):
            self.assertEqual(z, model.days_from_civil(*model.civil_from_days(z)))
        for z in range(model.days_from_civil(1000, 1, 1), model.days_from_civil(9999, 12, 31), 3011):
            self.assertEqual(z, model.parse_day(model.format_day(z)))

    def test_agrees_with_datetime(self):
        epoch = datetime.date(1970, 1, 1)
        for z in range(-719162, 2932896, 1009):
            day = epoch + datetime.timedelta(days=z)
            self.assertEqual([day.year, day.month, day.day], model.civil_from_days(z))

    def test_parse_day(self):
        self.assertEqual(model.parse_day('2026-09-05'), model.parse_day('05/09/2026'))
        self.assertEqual(model.parse_day('2026-09-05'), model.parse_day(' 2026-9-5\t'))
        for bad in ('2026-02-29', '31/04/2026', '2026-13-01', '2026-00-10', 'abc', '', '2026-09-05 x',
                    '\u0662\u0660\u0662\u0666-09-05', None):
            self.assertIsNone(model.parse_day(bad), bad)
        self.assertIsNotNone(model.parse_day('2024-02-29'))

    def test_season_start(self):
        self.assertEqual('2026-06-22', model.format_day(model.SEASON_START))
        self.assertEqual(0, (datetime.date(1970, 1, 1) + datetime.timedelta(days=model.SEASON_START)).weekday())


class AnalysesTest(unittest.TestCase):
    def test_evaluate_flags(self):
        ev = model.evaluate_flags({}, [1])
        self.assertEqual(model.FLAGS, [f['id'] for f in ev['flags']])
        self.assertTrue(0 < ev['baseRate'] < 0.1)
        for f in ev['flags']:
            self.assertTrue(0 <= f['auc'] <= 1)
            self.assertEqual(ev['rows'], f['atRule']['tp'] + f['atRule']['fp'] + f['atRule']['fn'] + f['atRule']['tn'])
            self.assertTrue(0.05 < f['atBudget']['share'] < 0.15)

    def test_coupling_demo(self):
        demo = model.coupling_demo(3)
        self.assertEqual(400, len(demo['points']))
        self.assertGreater(demo['corrCoupled'], 0.3)
        self.assertLess(abs(demo['corrUncoupled']), 0.15)

    def test_compare_policies(self):
        out = model.compare_policies({}, [1], ['none', 'rest'])
        self.assertEqual('none', out['reference'])
        self.assertEqual(['none', 'rest'], [r['policy'] for r in out['table']])
        for metric in out['table'][0]['metrics'].values():
            self.assertEqual(0, metric['diff'])

    def test_pilot_study(self):
        out = model.pilot_study({}, 1)
        self.assertEqual('rest', out['policy'])
        power = [p['power'] for p in out['power']]
        self.assertEqual(100, len(power))
        self.assertTrue(all(a <= b for a, b in zip(power, power[1:])))
        self.assertEqual(out['measured'], [out['after'][0] - out['before'][0]])


if __name__ == '__main__':
    unittest.main()
