"""The leaderboard check: reading tables, the statistics, and whether it tells luck from skill."""

import math
import unittest
from pathlib import Path

from leaderboard_luck import check

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def table_of(scores, days=20):
    """A table of Sharpe ratios that give exactly these luck-adjusted scores."""
    factor = math.sqrt(days / 252) * math.sqrt((days - 3) / (days - 1))
    text = "Team,Sharpe ratio\n" + "".join(f"T{i},{z / factor!r}\n" for i, z in enumerate(scores))
    return check.parse_table(text)


class ChiSquareTests(unittest.TestCase):
    def test_quantiles_match_published_tables(self):
        for p, df, expected in ((0.95, 29, 42.557), (0.05, 29, 17.708), (0.95, 10, 18.307),
                                (0.99, 100, 135.807), (0.5, 1, 0.4549), (0.95, 499, 552.075)):
            self.assertAlmostEqual(check.chi_square_quantile(p, df), expected, places=2 if df > 10 else 3)

    def test_tail_and_log_gamma(self):
        self.assertAlmostEqual(check.chi_square_tail(42.557, 29), 0.05, places=4)
        self.assertAlmostEqual(check.chi_square_tail(2, 2), math.exp(-1), places=10)
        self.assertEqual(check.chi_square_tail(0, 5), 1)
        self.assertAlmostEqual(check.log_gamma(5), math.log(24), places=9)
        self.assertAlmostEqual(check.log_gamma(0.5), math.log(math.sqrt(math.pi)), places=9)


class ReadingTablesTests(unittest.TestCase):
    def test_numbers(self):
        read = check.read_number
        self.assertEqual(read("+8.4%"), {"value": 8.4, "percent": True})
        self.assertEqual(read("−3.5"), {"value": -3.5, "percent": False})
        self.assertEqual(read("(2.1)"), {"value": -2.1, "percent": False})
        self.assertEqual(read("12,5"), {"value": 12.5, "percent": False})
        self.assertEqual(read("1,234.5"), {"value": 1234.5, "percent": False})
        self.assertEqual(read("1e-2"), {"value": 0.01, "percent": False})
        for bad in ("", "n/a", "12a", "--3", "٣"):
            self.assertIsNone(read(bad), bad)

    def test_header_units_and_columns(self):
        t = check.parse_table("﻿Rank\tFund\tP&L (%)\tRisk\n1\tAlpha\t8.4\t21\n2\tBeta\t-1.5\t\n3\tGamma\tn/a\t30\n")
        self.assertTrue(t["header"])
        self.assertEqual(t["columns"]["name"], "Fund")
        self.assertEqual(t["columns"]["ret"], "P&L (%)")
        self.assertEqual(t["units"], {"ret": "percent", "vol": "percent"})
        self.assertEqual(t["skipped"], 1)
        self.assertEqual([x["name"] for x in t["teams"]], ["Alpha", "Beta"])
        self.assertAlmostEqual(t["teams"][0]["ret"], 0.084)
        self.assertAlmostEqual(t["teams"][0]["vol"], 0.21)
        self.assertIsNone(t["teams"][1]["vol"])

    def test_fractions_quotes_semicolons_and_no_header(self):
        t = check.parse_table('Team;Return;Volatility\n"Smith, Jones";0,05;0,2\nLee;-0,02;0,3\n')
        self.assertEqual(t["units"], {"ret": "fraction", "vol": "fraction"})
        self.assertEqual(t["teams"][0]["name"], "Smith, Jones")
        self.assertAlmostEqual(t["teams"][0]["ret"], 0.05)
        t = check.parse_table("Oak, 8.4%, 21%\nElm, 4.0%, 23%\n")
        self.assertFalse(t["header"])
        self.assertEqual(len(t["teams"]), 2)
        self.assertAlmostEqual(t["teams"][1]["vol"], 0.23)

    def test_sharpe_only_and_true_skill(self):
        t = check.parse_table("Team,Sharpe,True skill\nA,1.2,0.5\nB,-0.3,0.1\n")
        self.assertEqual(t["rankedOn"], "sharpe")
        self.assertEqual(t["teams"][0]["sharpe"], 1.2)
        self.assertEqual(t["teams"][0]["truth"], 0.5)
        self.assertIsNone(t["teams"][0]["ret"])

    def test_errors(self):
        for text in ("", "Team,Volatility\nA,20\n", "Just names\nA\n"):
            with self.assertRaises(ValueError, msg=text):
                check.check_leaderboard(check.parse_table(text))
        with self.assertRaises(ValueError):
            check.check_leaderboard(check.parse_table("Team,Return\nA,1\nB,2\n"))


class StatisticsTests(unittest.TestCase):
    def test_identical_results_are_all_luck(self):
        r = check.check_leaderboard(table_of([0.5] * 10), {"sims": 1000})
        self.assertEqual(r["pSpread"], 1)
        self.assertEqual(r["luckShare"], 1)
        self.assertEqual(r["verdict"], "luck")
        self.assertEqual(r["skillSpread"], 0)
        self.assertTrue(all(row["edge"] == 0 for row in r["rows"]))

    def test_spread_test_matches_the_formula(self):
        scores = [2.5, 1.9, 1.1, 0.4, 0.0, -0.3, -0.8, -1.5, -2.2, -3.0]
        r = check.check_leaderboard(table_of(scores), {"correlation": 0.3, "sims": 1000})
        mean = sum(scores) / len(scores)
        ss = sum((z - mean) ** 2 for z in scores)
        self.assertAlmostEqual(r["spread"], ss / 9)
        self.assertAlmostEqual(r["pSpread"], check.chi_square_tail(ss / 0.7, 9))
        self.assertAlmostEqual(r["luckShare"], 0.7 / (ss / 9))
        k2 = 20 / 252
        self.assertAlmostEqual(r["skillSpread"], math.sqrt((ss / 9 - 0.7) / k2))
        self.assertEqual(r["verdict"], "skill")
        self.assertLess(r["skillSpreadLow"], r["skillSpread"])
        self.assertGreater(r["skillSpreadHigh"], r["skillSpread"])
        # Edges keep the order of the luck-adjusted leads, pulled towards zero.
        leads = [row["lead"] for row in r["rows"]]
        edges = [row["edge"] for row in r["rows"]]
        self.assertEqual(sorted(range(10), key=lambda i: leads[i]), sorted(range(10), key=lambda i: edges[i]))
        self.assertEqual(r["rows"][r["best"]]["name"], "T0")

    def test_log_returns_and_assumed_volatility(self):
        t = check.parse_table("Team,Return\nA,10%\nB,0%\nC,-10%\n")
        r = check.check_leaderboard(t, {"days": 60, "assumedVol": 0.2, "sims": 1000})
        self.assertEqual(r["basis"], {"sharpe": 0, "vol": 0, "assumed": 3})
        sd = 0.2 * math.sqrt(60 / 252)
        self.assertAlmostEqual(r["rows"][0]["z"], (math.log(1.1) + sd * sd / 2) / sd)
        # A team that lost everything still gets a finite score.
        t = check.parse_table("Team,Return,Volatility\nA,5%,20%\nB,-100%,90%\nC,1%,15%\n")
        self.assertTrue(math.isfinite(check.check_leaderboard(t, {"sims": 1000})["rows"][2]["z"]))

    def test_best_lead_chance_is_reproducible(self):
        t = table_of([1.5, 0.2, -0.4, -1.0, 0.6])
        a = check.check_leaderboard(t, {"sims": 2000, "seed": 7})
        b = check.check_leaderboard(t, {"sims": 2000, "seed": 7})
        self.assertEqual(a["pBest"], b["pBest"])
        self.assertTrue(0 < a["pBest"] < 1)


class DoesItWorkTests(unittest.TestCase):
    """The check run on simulated challenges whose true skill is known."""

    def test_fair_when_nobody_has_skill(self):
        res = [check.calibration_job({"skillSpread": 0, "yourSharpe": 0}, k, 200) for k in range(200)]
        flagged = sum(1 for r in res if r[0] < 0.05) / len(res)
        self.assertLess(flagged, 0.11)
        self.assertGreater(flagged, 0.005)
        self.assertTrue(0.3 < sum(r[0] for r in res) / len(res) < 0.7)

    def test_finds_skill_over_a_year(self):
        res = [check.calibration_job({"days": 250}, k, 200) for k in range(100)]
        self.assertGreater(sum(1 for r in res if r[0] < 0.05) / len(res), 0.5)
        self.assertGreater(sum(r[4] for r in res) / len(res), 0.5)
        self.assertTrue(0.5 < sum(r[2] for r in res) / len(res) < 0.95)


class ExampleTests(unittest.TestCase):
    def test_shipped_examples_are_the_simulated_ones(self):
        for kind, name in (("month", "four-week-challenge.csv"), ("year", "year-long-league.csv")):
            self.assertEqual((EXAMPLES / name).read_text(encoding="utf-8"), check.example_table(kind)["text"])

    def test_examples_check_as_described(self):
        month = check.example_table("month")
        r = check.check_leaderboard(check.parse_table(month["text"]), {"days": month["days"]})
        self.assertEqual(r["verdict"], "luck")
        self.assertEqual(r["teams"], 30)
        year = check.example_table("year")
        r = check.check_leaderboard(check.parse_table(year["text"]), {"days": year["days"]})
        self.assertNotEqual(r["verdict"], "luck")
        self.assertGreater(r["truthCorrelation"], 0.5)


if __name__ == "__main__":
    unittest.main()
