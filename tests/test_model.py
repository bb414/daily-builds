"""Tests for the Python model."""

import unittest

from assurance_mix import model as M

EX = {e["id"]: e for e in M.DATA["examples"]}


class ModelTests(unittest.TestCase):
    def test_probability_mapping(self):
        self.assertEqual(M.to_prob(1), 0.025)
        self.assertEqual(M.to_prob(5), 0.9)
        self.assertEqual(M.to_prob(-1), 0)
        for s in [0.5, 1, 1.7, 2.5, 3, 4.25, 5]:
            self.assertAlmostEqual(M.from_prob(M.to_prob(s)), s, places=12)

    def test_inherent_risk(self):
        r = M.inherent_risk(M.normalise_input({"answers": EX["shortlister"]["answers"]}))
        fair = next(x for x in r if x["id"] == "fairness")
        self.assertEqual((fair["L"], fair["I"], fair["score"], fair["band"]), (4.5, 4.5, 20.25, "Very high"))

    def test_cheapest_plan_needs_every_technique(self):
        for e in M.DATA["examples"]:
            r = M.analyse({"answers": e["answers"]})
            if r["cheapest"]:
                self.assertTrue(r["cheapest"]["meets"])
                for m in r["cheapest"]["marginal"]:
                    self.assertTrue(m["locked"] or not m["meetsWithout"], (e["id"], m["id"]))

    def test_cheapest_is_cheapest(self):
        # Brute force: no feasible plan costs less and still meets appetite.
        inp = {"answers": EX["fraud"]["answers"], "appetite": 6}
        r = M.analyse(inp)
        usable = r["usable"]
        for m in range(1 << len(usable)):
            ids = [t for i, t in enumerate(usable) if (m >> i) & 1]
            p = M.evaluate_plan(inp, ids)
            if p["meets"] and p["fitsDeadline"]:
                self.assertGreaterEqual(p["cost"], r["cheapest"]["cost"])

    def test_dependencies(self):
        r = M.analyse({"answers": EX["fraud"]["answers"], "exclude": ["docs"]})
        conf = next(s for s in r["techniques"] if s["id"] == "conformity")
        self.assertFalse(conf["available"])
        self.assertIn("ruled out", conf["reason"])
        r2 = M.analyse({"answers": EX["fraud"]["answers"], "must": ["aims"], "weeks": 40})
        for t in ("aims", "risk", "aia"):
            self.assertIn(t, r2["cheapest"]["ids"])

    def test_schedule(self):
        s = M.schedule(["risk", "aia", "aims", "docs", "conformity", "monitor"])
        self.assertEqual(s["goLive"], 26)
        rows = {r["id"]: r for r in s["rows"]}
        self.assertEqual((rows["aims"]["start"], rows["aims"]["end"]), (4, 18))

    def test_short_deadline(self):
        r = M.analyse({"answers": EX["shortlister"]["answers"], "weeks": 1})
        self.assertIsNone(r["best"])
        self.assertTrue(any("No plan fits in 1 week:" in n for n in r["notes"]))

    def test_odd_input(self):
        inp = M.normalise_input({"answers": {"stakes": "banana"}, "appetite": "lots", "budget": -5, "weeks": "12",
                                 "must": "risk; nope", "exclude": ["risk"]})
        self.assertEqual(inp["budget"], 0)
        self.assertEqual(inp["weeks"], 12)
        self.assertEqual(inp["must"], ["risk"])
        self.assertEqual(inp["exclude"], [])
        self.assertEqual(len(inp["notes"]), 5)
        self.assertEqual(M.normalise_input({"budget": "1_000"})["budget"], M.DATA["defaults"]["budget"])
        self.assertEqual(M.normalise_input({"budget": True})["budget"], M.DATA["defaults"]["budget"])

    def test_js_number_strings(self):
        self.assertEqual(M.js_num_str(100.0), "100")
        self.assertEqual(M.js_num_str(2.5), "2.5")
        self.assertEqual(M.js_num_str(1e21), "1e+21")
        self.assertEqual(M.js_num_str(1e-7), "1e-7")
        self.assertEqual(M.js_round(2.5), 3)
        self.assertEqual(M.js_round(-2.5), -2)


if __name__ == "__main__":
    unittest.main()
