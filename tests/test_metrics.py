import copy
import unittest

from helpers import fill, other

from second_opinion.design import ITEMS, build_session, make_rng
from second_opinion.metrics import profile_for, score, validate_session


class DesignTests(unittest.TestCase):
    def test_item_design(self):
        self.assertEqual(len(ITEMS), 28)
        checker = [i for i in ITEMS if i["role"] == "checker"]
        self.assertEqual(len(checker), 16)
        self.assertEqual(sum(i["ai_verdict"] == i["truth"] for i in checker), 12)

    def test_rng_is_in_unit_interval_and_repeatable(self):
        a, b = make_rng(42), make_rng(42)
        values = [a() for _ in range(1000)]
        self.assertEqual(values, [b() for _ in range(1000)])
        self.assertTrue(all(0 <= v < 1 for v in values))
        self.assertAlmostEqual(sum(values) / len(values), 0.5, delta=0.05)

    def test_build_session_shape(self):
        s = build_session(2026)
        self.assertEqual(s, build_session(2026))
        self.assertEqual([t["phase"] for t in s["trials"]], ["before"] * 6 + ["with"] * 16 + ["after"] * 6)
        self.assertEqual(len({t["item"] for t in s["trials"]}), 28)
        self.assertEqual(s["id"], "so-1ka")
        self.assertEqual(build_session(float("nan"))["seed"], 1)
        self.assertEqual(build_session(True)["seed"], 1)
        self.assertEqual(build_session(-7.9)["seed"], 7)


class ScoreTests(unittest.TestCase):
    def test_perfect_and_independent(self):
        r = score(fill(build_session(9), lambda t, stage: (t["truth"], 100)))
        self.assertEqual(r["accuracy"]["withFinal"], 1)
        self.assertEqual(r["accuracy"]["checker"], 0.75)
        self.assertIsNone(r["reliance"]["rair"])
        self.assertEqual(r["reliance"]["rsr"], 1)
        self.assertEqual(r["profile"]["key"], "holds-firm")
        self.assertTrue(r["profile"]["tentative"])
        self.assertEqual(r["complementarity"], 0)

    def test_always_follow(self):
        def pick(t, stage):
            if t["phase"] != "with":
                return (t["truth"], 80)
            return (other(t["ai"]["verdict"]), 60) if stage == "initial" else (t["ai"]["verdict"], 90)
        r = score(fill(build_session(4), pick))
        self.assertEqual(r["accuracy"]["withFinal"], 0.75)
        self.assertEqual(r["reliance"]["rair"], 1)
        self.assertEqual(r["reliance"]["rsr"], 0)
        self.assertEqual(r["profile"]["key"], "over")
        self.assertEqual(r["reliance"]["switchRate"], 1)

    def test_hand_built_counts(self):
        s = fill(build_session(77), lambda t, stage: (t["truth"], 80))
        w = [t for t in s["trials"] if t["phase"] == "with"]
        right = [t for t in w if t["ai"]["verdict"] == t["truth"]]
        wrong = [t for t in w if t["ai"]["verdict"] != t["truth"]]
        right[0]["initial"] = {"answer": other(right[0]["truth"]), "confidence": 60}
        right[1]["initial"] = {"answer": other(right[1]["truth"]), "confidence": 90}
        right[1]["final"] = {"answer": other(right[1]["truth"]), "confidence": 90}
        wrong[0]["final"] = {"answer": wrong[0]["ai"]["verdict"], "confidence": 60}
        r = score(s)
        cells = r["reliance"]["cells"]
        self.assertEqual(cells["checkerRight"], {"n": 2, "corrected": 1})
        self.assertEqual(cells["checkerWrong"], {"n": 4, "heldFirm": 3})
        self.assertEqual(r["reliance"]["rsr"], 0.75)
        self.assertEqual(r["reliance"]["followWhenWrong"], 0.25)
        self.assertEqual(r["profile"]["key"], "calibrated")

    def test_partial_and_empty(self):
        s = build_session(3)
        for t in s["trials"][:6]:
            t["initial"] = {"answer": t["truth"], "confidence": 70}
        r = score(s)
        self.assertEqual(r["n"]["before"], 6)
        self.assertIsNone(r["accuracy"]["withFinal"])
        self.assertFalse(r["complete"])
        self.assertEqual(score({})["n"]["total"], 0)
        self.assertEqual(score(None)["n"]["total"], 0)

    def test_profiles(self):
        self.assertEqual(profile_for(None, None, 0, 0)["key"], "untested")
        self.assertEqual(profile_for(0, 0, 2, 2)["key"], "misplaced")
        self.assertEqual(profile_for(0.4, 0.9, 5, 5)["key"], "under")
        self.assertFalse(profile_for(0.4, 0.9, 5, 5)["tentative"])


class ValidateTests(unittest.TestCase):
    def test_valid_and_invalid(self):
        s = fill(build_session(5), lambda t, stage: (t["truth"], 70))
        self.assertEqual(validate_session(s), [])
        self.assertTrue(validate_session([]))
        self.assertTrue(validate_session({"format": "x"}))
        bad = copy.deepcopy(s)
        bad["trials"][0]["initial"]["confidence"] = 55
        bad["trials"][1]["phase"] = "during"
        bad["trials"][7]["ai"] = None
        self.assertEqual(len(validate_session(bad)), 3)


if __name__ == "__main__":
    unittest.main()
