"""Proves the browser app (JavaScript) and the Python toolkit agree exactly.

Runs the app's own model block in Node.js and compares it with the Python code on
the item design, on session building and on scoring. Skipped if Node.js is missing.
"""

import copy
import math
import random
import unittest

from helpers import NODE, fill, node_bridge, other

from second_opinion.cohort import _session_from_csv_rows
from second_opinion.design import ITEMS, build_session
from second_opinion.metrics import score, validate_session
from second_opinion.synth import simulate_cohort


def assert_same(test, a, b, path="result"):
    """Deep comparison allowing for floating-point noise only."""
    if isinstance(a, dict) and isinstance(b, dict):
        test.assertEqual(sorted(a), sorted(b), "keys differ at %s" % path)
        for k in a:
            assert_same(test, a[k], b[k], path + "." + k)
    elif isinstance(a, list) and isinstance(b, list):
        test.assertEqual(len(a), len(b), "lengths differ at %s" % path)
        for i, (x, y) in enumerate(zip(a, b)):
            assert_same(test, x, y, "%s[%d]" % (path, i))
    elif isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str):
        test.assertEqual(a, b, "values differ at %s" % path)
    else:
        test.assertTrue(math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12), "%s: %r != %r" % (path, a, b))


def varied_sessions():
    """Synthetic people under every condition, plus hand-made edge cases."""
    sessions = []
    for k, advice in enumerate(("verdict", "confidence", "reason")):
        for feedback in (False, True):
            sessions += simulate_cohort(25, seed=100 + k * 10 + feedback, condition={"advice": advice, "feedback": feedback})
    rng = random.Random(5)
    # Random answers, including unfinished sessions cut off at every possible point.
    for i in range(60):
        s = fill(build_session(rng.randrange(2 ** 32)),
                 lambda t, stage: (rng.choice(["scam", "genuine"]), rng.choice([50, 60, 70, 80, 90, 100])))
        cut = rng.randrange(0, 29)
        for t in s["trials"][cut:]:
            t["initial"] = None
            if t["phase"] == "with":
                t["final"] = None
        if i % 3 == 0 and cut > 6 and cut < 23:
            s["trials"][cut - 1]["final"] = None  # first answer given, final missing
        sessions.append(s)
    sessions.append(fill(build_session(9), lambda t, stage: (t["truth"], 100)))
    sessions.append(fill(build_session(10), lambda t, stage: (other(t["truth"]), 50)))
    sessions.append(fill(build_session(11), lambda t, stage: (t["ai"]["verdict"] if t["phase"] == "with" else t["truth"], 70)))
    sessions.append(build_session(12))
    sessions.append({"trials": []})
    return sessions


@unittest.skipUnless(NODE, "Node.js is not installed")
class AgreementTests(unittest.TestCase):
    def test_item_design_matches_the_app(self):
        self.assertEqual(node_bridge("items"), ITEMS)

    def test_session_building_matches_the_app(self):
        args = [{"seed": s, "condition": {"advice": a, "feedback": f}}
                for s in list(range(0, 120)) + [2 ** 32 - 1, 2 ** 31, 987654321, 42.7]
                for a, f in [("reason", False), ("verdict", True)]]
        js = node_bridge("build", args)
        py = [build_session(a["seed"], a["condition"]) for a in args]
        self.assertEqual(js, py)

    def test_scores_match_the_app(self):
        sessions = varied_sessions()
        self.assertGreater(len(sessions), 200)
        js = node_bridge("score", sessions)
        for i, (j, p) in enumerate(zip(js, [score(s) for s in sessions])):
            assert_same(self, j, p, "session %d" % i)

    def test_validation_matches_the_app(self):
        good = fill(build_session(5), lambda t, stage: (t["truth"], 70))
        cases = [good, build_session(6), {}, {"format": "x"},
                 {"format": "second-opinion-session", "version": 2, "trials": good["trials"]},
                 {"format": "second-opinion-session", "version": 1, "trials": []}]
        bad = copy.deepcopy(good)
        bad["trials"][0]["initial"]["confidence"] = 55
        bad["trials"][1]["phase"] = "during"
        bad["trials"][7]["ai"] = None
        bad["trials"][8]["final"]["answer"] = "maybe"
        bad["trials"][9]["truth"] = "unknown"
        bad["trials"][10]["initial"] = "scam"
        cases.append(bad)
        self.assertEqual(node_bridge("validate", cases), [validate_session(c) for c in cases])

    def test_csv_from_the_app_loads_into_python_unchanged(self):
        sessions = simulate_cohort(5, seed=3, condition={"advice": "verdict", "feedback": True})
        for s in sessions:
            for t in s["trials"]:
                t["initial"]["ms"] = 1234
                if t["phase"] == "with":
                    t["final"]["ms"] = 987
        csvs = node_bridge("csv", sessions)
        import csv
        import io
        for s, text in zip(sessions, csvs):
            rows = list(csv.DictReader(io.StringIO(text)))
            back = _session_from_csv_rows(rows)
            self.assertEqual(back["condition"], s["condition"])
            self.assertEqual(back["trials"], s["trials"])
            assert_same(self, score(back), score(s))


if __name__ == "__main__":
    unittest.main()
