import math
import unittest

from leaderboard_luck.model import (DEFAULTS, VOL_GRID, Rng, Run, competition_seed, norm_cdf, normalise,
                                    sample_competition, simulate, skill_percentile)

SMALL = {"sims": 300}


class RandomNumberTests(unittest.TestCase):
    def test_first_draws_match_mulberry32(self):
        # Reference values from the JavaScript mulberry32 used in the browser app (seed 1).
        g = Rng(1)
        self.assertAlmostEqual(g.uniform(), 0.6270739405881613, places=15)
        self.assertAlmostEqual(g.uniform(), 0.002735721180215478, places=15)

    def test_normals_have_mean_zero_and_variance_one(self):
        g = Rng(42)
        zs = [g.normal() for _ in range(20000)]
        mean = sum(zs) / len(zs)
        var = sum(z * z for z in zs) / len(zs)
        self.assertLess(abs(mean), 0.03)
        self.assertLess(abs(var - 1), 0.04)

    def test_competition_seeds_stay_32_bit(self):
        self.assertEqual(competition_seed(4294967295, 5), (4294967295 * 1000003 + 5) % 4294967296)

    def test_norm_cdf(self):
        for x in (-6, -1, 0, 0.5, 2.5):
            self.assertAlmostEqual(norm_cdf(x), 0.5 * math.erfc(-x / math.sqrt(2)), places=14)


class SimulationTests(unittest.TestCase):
    def test_reproducible_and_chunkable(self):
        a = simulate(SMALL)
        self.assertEqual(a, simulate(SMALL))
        run = Run(SMALL)
        while not run.advance(11):
            pass
        self.assertEqual(run.result(), a)
        self.assertNotEqual(simulate({**SMALL, "seed": 9})["curve"], a["curve"])

    def test_sharpe_ranking_makes_risk_irrelevant(self):
        r = simulate({"sims": 300, "rule": "sharpe"})
        self.assertEqual(len({c["pWin"] for c in r["curve"]}), 1)

    def test_return_ranking_rewards_risk_in_a_short_challenge(self):
        r = simulate({"sims": 600})
        self.assertGreater(r["curve"][-1]["pWin"], r["curve"][3]["pWin"] + 0.1)
        self.assertEqual(r["bestVol"], 1.0)

    def test_drawdown_limit_caps_the_gamble(self):
        r = simulate({"sims": 300, "rule": "drawdown", "drawdownLimit": 0.1})
        self.assertGreater(r["curve"][-1]["pOut"], r["curve"][3]["pOut"])
        self.assertLess(r["bestVol"], 1.0)

    def test_more_skill_wins_more_over_a_long_challenge(self):
        weak = simulate({"sims": 200, "days": 250, "yourSharpe": 0})["you"]["pWin"]
        strong = simulate({"sims": 200, "days": 250, "yourSharpe": 2.5})["you"]["pWin"]
        self.assertGreater(strong, weak + 0.1)

    def test_shares_add_up(self):
        r = simulate({"sims": 200, "rule": "drawdown", "drawdownLimit": 0.05, "gamblers": 0.5})
        w = r["winners"]
        self.assertAlmostEqual(w["you"] + w["gambler"] + w["steady"] + w["none"], 1, places=12)
        self.assertEqual(w["you"], r["you"]["pWin"])
        self.assertEqual(len(r["curve"]), len(VOL_GRID))
        for c in r["curve"]:
            self.assertLessEqual(c["pWin"], c["pTop3"])

    def test_skill_percentile(self):
        self.assertAlmostEqual(skill_percentile(normalise({})), norm_cdf(1 / 0.75))
        self.assertEqual(skill_percentile(normalise({"skillSpread": 0, "yourSharpe": 0})), 0.5)
        self.assertEqual(skill_percentile(normalise({"skillSpread": 0, "yourSharpe": 0.1})), 1.0)


class GoingForBrokeTests(unittest.TestCase):
    def test_switching_to_the_same_risk_changes_nothing(self):
        off = simulate({"sims": 200})["you"]
        same = simulate({"sims": 200, "catchUp": True, "catchUpVol": 0.2})["you"]
        self.assertEqual((same["pWin"], same["meanRank"]), (off["pWin"], off["meanRank"]))
        self.assertGreater(same["pSwitched"], 0.5)

    def test_going_for_broke_lifts_a_podium_finish(self):
        off = simulate({"sims": 400})["you"]
        on = simulate({"sims": 400, "catchUp": True})["you"]
        self.assertGreater(on["pTop3"], off["pTop3"] + 0.1)

    def test_rivals_switch_only_at_the_checkpoint_and_never_gamblers(self):
        from leaderboard_luck.model import checkpoint_day
        teams = sample_competition({"rivalsCatchUp": 1, "teams": 20}, 3)
        cp = checkpoint_day(normalise({"teams": 20}))
        switched = [t for t in teams if t["switchDay"] is not None and not t["you"]]
        self.assertTrue(switched)
        for t in switched:
            self.assertEqual(t["switchDay"], cp)
            self.assertFalse(t["gambler"])


class SampleTests(unittest.TestCase):
    def test_sample_is_ranked_and_matches_the_simulation(self):
        p = {"sims": 100, "teams": 10, "days": 12}
        r = simulate(p)
        you_wins = 0
        for k in range(100):
            teams = sample_competition(p, k)
            self.assertEqual([t["rank"] for t in teams], list(range(1, 11)))
            self.assertEqual(len(teams[0]["path"]), 13)
            you_wins += teams[0]["you"]
        self.assertEqual(you_wins / 100, r["winners"]["you"])

    def test_blown_up_accounts_are_out(self):
        p = {"fieldVol": 0.5, "gamblerMultiple": 4, "gamblers": 0.8, "fatTails": True, "days": 250}
        busts = [t for k in range(10) for t in sample_competition(p, k) if t["bust"]]
        self.assertTrue(busts)
        for t in busts:
            self.assertTrue(t["out"])
            self.assertEqual(t["ret"], -1)
            self.assertEqual(t["score"], -math.inf)


class NormaliseTests(unittest.TestCase):
    def test_clamps_rounds_and_rejects(self):
        p = normalise({"teams": 2.6, "days": 1000, "yourVol": 0, "sims": 100.5})
        self.assertEqual((p["teams"], p["days"], p["yourVol"], p["sims"]), (3, 250, 0.02, 101))
        self.assertEqual(normalise(None), {**DEFAULTS})
        for bad in ({"rule": "luck"}, {"teams": math.nan}, {"fatTails": "yes"}, {"days": True}):
            with self.assertRaises(ValueError):
                normalise(bad)


if __name__ == "__main__":
    unittest.main()
