"""Proves the browser app (JavaScript) and the Python companion give the same numbers.

Runs the app's own MODEL block in Node.js and compares it with stairstep/model.py
on the synthetic sales, every forecast of every method, and every result.
Skipped if Node.js is not installed.
"""

import unittest

from helpers import NODE, assert_same, node_bridge

from stairstep import data as datafile
from stairstep import model

SCENARIOS = [
    {},
    {"seed": 3, "horizon": 3, "holidays": 1.7, "noise": 0.4, "growth": -0.1},
    {"seed": 12345, "promoLift": 1.5, "overrideRate": 1, "optimism": -0.3, "insight": 1, "buffer": 0.5},
    {"seed": 4294967295, "holidays": 0, "promoLift": 0, "noise": 0, "growth": 0.3, "horizon": 4, "overrideRate": 0},
]


@unittest.skipUnless(NODE, "Node.js is not installed")
class AgreementTests(unittest.TestCase):
    def test_every_number_matches_the_app(self):
        js = node_bridge("run", SCENARIOS)
        for settings, j in zip(SCENARIOS, js):
            r = model.run(settings)
            label = "scenario %r" % settings
            self.assertEqual(j["sales"], r["data"]["sales"], label + ": sales")
            self.assertEqual(j["promo"], r["data"]["promo"], label + ": promotions")
            self.assertEqual(j["events"], r["data"]["events"], label + ": calendar")
            assert_same(self, j["forecasts"], r["forecasts"]["forecasts"], label + ": forecasts")
            self.assertEqual(j["overridden"], r["forecasts"]["overridden"], label + ": overrides")
            assert_same(self, j["coefficients"], r["forecasts"]["coefficients"], label + ": coefficients")
            assert_same(self, j["results"], r["results"], label + ": results")

    def test_forecasts_match_exactly_not_just_closely(self):
        j = node_bridge("run", [{}])[0]
        r = model.run({})
        flat_js = [v for p in j["forecasts"]["ai"] for s in p for v in s]
        flat_py = [v for p in r["forecasts"]["forecasts"]["ai"] for s in p for v in s]
        self.assertEqual(flat_js, flat_py)

    def test_csv_data_runs_the_same_in_both(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sales.csv")
            datafile.write_csv(model.simulate({"seed": 21}), path)
            data = datafile.read_csv(path)
        jobs = [{"data": data, "settings": {"seed": 5, "horizon": 2}}]
        j = node_bridge("data", jobs)[0]
        fc = model.forecast_all(data, jobs[0]["settings"])
        assert_same(self, j["forecasts"], fc["forecasts"])
        assert_same(self, j["results"], model.evaluate(data, fc))

    def test_settings_are_normalised_the_same(self):
        inputs = [{}, None, {"holidays": 9, "noise": -1, "horizon": 2.7, "seed": -5, "optimism": "lots", "insight": True},
                  {"seed": 1e12, "threshold": 0.05, "buffer": 0.25, "horizon": 0}]
        self.assertEqual(node_bridge("settings", inputs), [model.normalise_settings(i) for i in inputs])


if __name__ == "__main__":
    unittest.main()
