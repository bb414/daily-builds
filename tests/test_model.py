import copy
import unittest

import helpers  # noqa: F401  (puts the project on the path)

from stairstep import model


class ModelTests(unittest.TestCase):
    def test_methods_on_a_known_series(self):
        y = list(range(160))
        data = {"weeks": 160, "testStart": 108, "skus": [{"id": "a", "name": "A"}], "stores": [{"id": "s", "name": "S"}],
                "sales": [[y]], "promo": [[0] * 160], "events": [], "synthetic": False}
        fc = model.forecast_all(data, {"horizon": 2, "overrideRate": 0})["forecasts"]
        self.assertEqual(fc["naive"][0][0][120], 118)
        self.assertEqual(fc["average"][0][0][120], (111 + 118) / 2)
        self.assertEqual(fc["seasonal"][0][0][120], 68)
        self.assertIsNone(fc["naive"][0][0][79])
        self.assertEqual(fc["naive"][0][0][80], 78)
        self.assertEqual(fc["planner"], fc["ai"])

    def test_no_peeking_at_the_future(self):
        data = model.simulate({"seed": 11})
        base = model.forecast_all(data, {"seed": 11, "horizon": 2})
        t = 140
        changed = copy.deepcopy(data)
        for rows in changed["sales"]:
            for y in rows:
                for k in range(t - 1, data["weeks"]):
                    y[k] = y[k] * 3 + 7
        after = model.forecast_all(changed, {"seed": 11, "horizon": 2})
        for m in ("naive", "average", "seasonal", "smoothing", "ai"):
            for p in range(12):
                for s in range(8):
                    self.assertEqual(after["forecasts"][m][p][s][t], base["forecasts"][m][p][s][t], m)

    def test_ridge_solver(self):
        beta = model.solve_ridge([[4, 2], [0, 3]], [10, 9])
        self.assertAlmostEqual(beta[0], 2)
        self.assertAlmostEqual(beta[1], 1)
        self.assertEqual(model.solve_ridge([[0, 0], [0, 0]], [0, 0]), [0, 0])

    def test_results_are_consistent(self):
        r = model.run({})["results"]
        self.assertEqual([m["id"] for m in r["methods"]], model.METHOD_IDS)
        self.assertTrue(all(m["n"] == 4992 for m in r["methods"]))
        self.assertEqual(sum(r["byWeekType"][k]["naive"]["n"] for k in ("festival", "promo", "ordinary")), 4992)
        self.assertEqual(r["deployOn"], sum(1 for s in r["bySku"] if s["verdict"] == "ai"))
        self.assertLess(r["overrides"]["up"]["improved"], 0)
        self.assertGreater(r["overrides"]["down"]["improved"], 0)

    def test_settings(self):
        s = model.normalise_settings({"horizon": 9, "seed": -1, "noise": float("nan"), "buffer": True})
        self.assertEqual((s["horizon"], s["seed"], s["noise"], s["buffer"]), (4, 0, 0.2, 0.1))
        self.assertEqual(model.normalise_settings("nonsense"), model.normalise_settings({}))


if __name__ == "__main__":
    unittest.main()
