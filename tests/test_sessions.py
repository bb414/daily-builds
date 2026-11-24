import contextlib
import io
import json
import random
import tempfile
import unittest
from pathlib import Path

from reliance_lab.__main__ import main
from reliance_lab.report import class_csv, class_report, model_report, session_report
from reliance_lab.html_report import class_html
from reliance_lab.sessions import (SessionError, auroc, bootstrap, bootstrap_mean, classify_trial, counterfactuals,
                                   estimate_params, load_session, score_session)
from reliance_lab.synthetic import HABITS, make_class, simulate_session

TOY = [
    {"truth": "fraud", "initial": "genuine", "initialConfidence": 0.55, "ai": "fraud", "aiConfidence": 0.9, "final": "fraud"},
    {"truth": "fraud", "initial": "fraud", "initialConfidence": 0.95, "ai": "genuine", "aiConfidence": 0.6, "final": "fraud"},
    {"truth": "genuine", "initial": "genuine", "initialConfidence": 0.7, "ai": "fraud", "aiConfidence": 0.8, "final": "fraud"},
    {"truth": "genuine", "initial": "fraud", "initialConfidence": 0.85, "ai": "fraud", "aiConfidence": 0.7, "final": "fraud"},
]


class ScoringTests(unittest.TestCase):
    def test_hand_made_session(self):
        s = score_session(TOY)
        self.assertEqual((s["initialAccuracy"], s["aiAccuracy"], s["finalAccuracy"]), (0.5, 0.25, 0.5))
        self.assertEqual((s["aiOnlyRight"], s["switchedToAI"], s["rair"]), (1, 1, 1.0))
        self.assertEqual((s["youOnlyRight"], s["keptOwn"], s["rsr"]), (2, 1, 0.5))
        self.assertEqual(s["overRelianceRate"], 0.5)
        self.assertEqual(s["underRelianceRate"], 0.0)
        self.assertEqual((s["helpfulSwitches"], s["harmfulSwitches"]), (1, 1))
        self.assertAlmostEqual(s["meanConfidence"], 0.7625)
        self.assertEqual(s["complementarity"], 0.0)
        self.assertEqual(s["outcomes"], {"agreedRight": 0, "sharedMiss": 1, "goodSwitch": 1, "underRelied": 0,
                                         "heldFirm": 1, "overRelied": 1, "changedAfterAgreeing": 0})
        # Right answers had confidence 0.95 and 0.7; wrong ones 0.55 and 0.85.
        self.assertEqual(s["confidenceAuroc"], 0.75)

    def test_outcomes_cover_every_case(self):
        rng = random.Random(5)
        for habit in HABITS:
            trials = simulate_session(rng, habit=habit)["trials"]
            s = score_session(trials)
            self.assertEqual(sum(s["outcomes"].values()), s["n"])
            self.assertEqual(s["outcomes"]["goodSwitch"], s["switchedToAI"])
            self.assertEqual(s["outcomes"]["heldFirm"], s["keptOwn"])

    def test_changing_your_mind_after_agreeing_is_its_own_outcome(self):
        t = {"truth": "fraud", "initial": "fraud", "ai": "fraud", "final": "genuine"}
        self.assertEqual(classify_trial(t), "changedAfterAgreeing")

    def test_counterfactuals_line_up_with_the_scores(self):
        cfs = {c["key"]: c for c in counterfactuals(TOY, 0.8)}
        s = score_session(TOY)
        self.assertEqual(cfs["you"]["accuracy"], s["initialAccuracy"])
        self.assertEqual(cfs["ai"]["accuracy"], s["aiAccuracy"])
        self.assertEqual(cfs["final"]["accuracy"], s["finalAccuracy"])
        # Follow at 80%+: trials 1 and 3 go to the AI -> fraud(right), fraud(wrong); 2, 4 keep own.
        self.assertEqual(cfs["threshold"]["accuracy"], 0.5)
        # Surer: only trial 1 (0.9 > 0.55) and 3 (0.8 > 0.7) switch: same as above.
        self.assertEqual(cfs["surer"]["accuracy"], 0.5)

    def test_hidden_confidence_makes_some_replays_unavailable(self):
        hidden = [dict(t, aiConfidence=None) for t in TOY]
        cfs = {c["key"]: c for c in counterfactuals(hidden)}
        self.assertFalse(cfs["threshold"]["available"])
        self.assertIsNone(cfs["surer"]["accuracy"])
        self.assertIsNone(score_session(hidden)["aiConfidenceAuroc"])

    def test_auroc(self):
        self.assertEqual(auroc([0.9, 0.8, 0.2], [True, True, False]), 1.0)
        self.assertEqual(auroc([0.5, 0.5], [True, False]), 0.5)
        self.assertIsNone(auroc([0.6, 0.7], [True, True]))

    def test_rejects_bad_trials(self):
        with self.assertRaises(SessionError):
            score_session([])
        for bad in [{"truth": "maybe"}, dict(TOY[0], initialConfidence=0.3), dict(TOY[0], aiConfidence=1.2),
                    dict(TOY[0], initialConfidence=True)]:
            with self.assertRaises(SessionError):
                score_session([bad])

    def test_estimate_params_reflects_the_session(self):
        p = estimate_params(TOY)
        self.assertEqual(p["human"], 0.5)
        self.assertEqual(p["ai"], 0.5)  # 25% is below the model's floor of 50%
        # Three disagreements, the AI's answer was taken in two of them.
        self.assertAlmostEqual(p["deferRate"], 2 / 3)
        hidden = estimate_params([dict(t, aiConfidence=None) for t in TOY])
        self.assertEqual(hidden["aiSignal"], 0.0)
        self.assertEqual(hidden["aiBias"], 0.0)


class BootstrapTests(unittest.TestCase):
    def test_intervals_contain_the_estimate_and_are_reproducible(self):
        trials = make_class(1, seed=4)[0]["trials"]
        s = score_session(trials)
        ci = bootstrap(trials, reps=500, seed=2)
        self.assertEqual(ci, bootstrap(trials, reps=500, seed=2))
        for key in ("initialAccuracy", "finalAccuracy", "complementarity"):
            lo, hi = ci[key]
            self.assertLessEqual(lo, s[key] + 1e-12)
            self.assertGreaterEqual(hi, s[key] - 1e-12)

    def test_unanimous_session_has_zero_width_and_missing_measures(self):
        trials = [dict(TOY[0], initial="fraud", ai="fraud", final="fraud") for _ in range(10)]
        ci = bootstrap(trials, reps=200)
        self.assertEqual(ci["finalAccuracy"], (1.0, 1.0))
        self.assertIsNone(ci["rair"])
        self.assertIsNone(bootstrap_mean([0.1]))
        lo, hi = bootstrap_mean([0.0, 0.1, 0.2, 0.3], reps=500)
        self.assertTrue(0.0 <= lo <= 0.15 <= hi <= 0.3)


class FileAndReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        path = self.dir / name
        path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return path

    def test_load_session_checks_the_file(self):
        good = self.write("good.json", {"format": "reliance-lab-session", "trials": TOY})
        self.assertEqual(load_session(good)["label"], "good")
        for name, data in [("bad.json", "{not json"), ("other.json", {"format": "something", "trials": TOY}),
                           ("empty.json", {"format": "reliance-lab-session", "trials": []}),
                           ("broken.json", {"format": "reliance-lab-session", "trials": [{"truth": "x"}]})]:
            with self.assertRaises(SessionError):
                load_session(self.write(name, data))

    def test_synthetic_class_is_reproducible_and_habits_differ(self):
        a = make_class(16, seed=3)
        b = make_class(16, seed=3)
        self.assertEqual(a, b)
        follow = {}
        for s in make_class(80, seed=9):
            dis = [t for t in s["trials"] if t["initial"] != t["ai"]]
            if dis:
                follow.setdefault(s["habit"], []).append(sum(t["final"] == t["ai"] for t in dis) / len(dis))
        mean = {k: sum(v) / len(v) for k, v in follow.items()}
        self.assertGreater(mean["rubber-stamper"], 0.8)
        self.assertLess(mean["sceptic"], 0.3)

    def test_mistakes_on_tricky_payments_overlap_with_the_person(self):
        shared = {}
        for mistakes in ("hard", "random", "easy"):
            rng = random.Random(8)
            total = 0
            for _ in range(60):
                trials = simulate_session(rng, habit="weigher", mistakes=mistakes)["trials"]
                total += sum(t["initial"] != t["truth"] and t["ai"] != t["truth"] for t in trials)
            shared[mistakes] = total
        self.assertGreater(shared["hard"], shared["random"])
        self.assertGreater(shared["random"], shared["easy"])
        with self.assertRaises(ValueError):
            simulate_session(random.Random(1), habit="weigher", mistakes="sometimes")

    def test_reports(self):
        sessions = make_class(8, seed=1)
        text = session_report(sessions[0])
        self.assertIn("Same cases, other strategies", text)
        self.assertIn("(synthetic)", text)
        summary = class_report(sessions)
        self.assertIn("Class summary: 8 sessions", summary)
        self.assertIn("honest confidence", summary)
        rows = class_csv(sessions).strip().splitlines()
        self.assertEqual(len(rows), 9)
        self.assertTrue(rows[0].startswith("label,habit,aiStyle,n,"))
        self.assertIn("Best possible rule", model_report())
        page = class_html(sessions)
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertIn("8 of these 8 sessions are synthetic", page)
        self.assertEqual(page.count("<tr><td>"), 8)
        self.assertNotIn("http", page.replace('xmlns="http://www.w3.org/2000/svg"', ""))

    def test_command_line(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["model", "--human", "0.8", "--ai", "0.8"]), 0)
        self.assertIn("Person alone 80.0%", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["model", "--json"]), 0)
        self.assertIn('"ceiling"', out.getvalue())
        folder = self.dir / "class"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["demo-class", "--out", str(folder), "--participants", "6"]), 0)
        files = sorted(str(p) for p in folder.glob("*.json"))
        self.assertEqual(len(files), 6)
        csv_path = self.dir / "class.csv"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["score", *files, "--csv", str(csv_path), "--html", str(self.dir / "r.html")]), 0)
        self.assertTrue((self.dir / "r.html").exists())
        self.assertIn("Class summary: 6 sessions", out.getvalue())
        self.assertTrue(csv_path.exists())
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["score", str(self.dir / "missing.json")]), 2)
            self.assertEqual(main(["model", "--human", "nan"]), 2)
        self.assertIn("error:", err.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["sweep", "--csv", str(self.dir / "sweep.csv")]), 0)
        self.assertIn("Sweep: 3888 combinations", out.getvalue())
        self.assertTrue((self.dir / "sweep.csv").exists())


if __name__ == "__main__":
    unittest.main()
