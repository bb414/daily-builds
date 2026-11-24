import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from crutch_check import model as M
from crutch_check.__main__ import main as cli
from crutch_check.sessions import load_sessions, write_bundle, write_csv

ROOT = Path(__file__).resolve().parents[1]


def answer(verdict, sure=True, ms=1000):
    return {"verdict": verdict, "sure": sure, "ms": ms}


class BankTests(unittest.TestCase):
    def test_bank_is_balanced(self):
        self.assertEqual(len(M.MESSAGES), 36)
        ids = [m["id"] for m in M.MESSAGES]
        self.assertEqual(len(ids), len(set(ids)))
        for truth in ("scam", "genuine"):
            for d in (1, 2, 3):
                cell = [m for m in M.MESSAGES if m["truth"] == truth and m["difficulty"] == d]
                self.assertEqual(len(cell), 6, (truth, d))

    def test_every_tag_is_defined_and_on_the_right_side(self):
        red_flags = {"urgency", "threat", "lookalike_link", "credentials", "unusual_payment",
                     "too_good", "unexpected", "impersonation", "new_number", "secrecy",
                     "avoid_usual_route", "number_in_message", "fee_first", "changed_details",
                     "your_account", "off_platform", "generic_greeting"}
        reassurances = {"expected", "known_domain", "official_route", "no_action", "never_ask",
                        "specific_detail", "verifiable", "realistic", "known_contact"}
        scam_decoys = {"polished", "uses_name", "familiar_brand", "small_amount", "precise_detail",
                       "replies_to_you", "security_words", "saved_contact"}
        genuine_decoys = {"has_link", "mentions_money", "deadline", "unknown_sender", "asks_action",
                          "has_code", "risky_topic", "new_number_topic", "prize"}
        self.assertEqual(set(M.CUES), red_flags | reassurances | scam_decoys | genuine_decoys)
        for m in M.MESSAGES:
            self.assertTrue(m["cues"] and m["decoys"], m["id"])
            if m["truth"] == "scam":
                self.assertLessEqual(set(m["cues"]), red_flags, m["id"])
                self.assertLessEqual(set(m["decoys"]), scam_decoys, m["id"])
            else:
                self.assertLessEqual(set(m["cues"]), reassurances, m["id"])
                self.assertLessEqual(set(m["decoys"]), genuine_decoys, m["id"])
            for field in ("from", "context", "body", "note", "channel"):
                self.assertTrue(m[field].strip(), (m["id"], field))
            self.assertEqual(bool(m["subject"]), m["channel"] == "Email", m["id"])

    def test_every_tag_is_used(self):
        used = set()
        for m in M.MESSAGES:
            used.update(m["cues"])
            used.update(m["decoys"])
        self.assertEqual(used, set(M.CUES))

    def test_web_addresses_use_the_reserved_domain(self):
        import re
        for m in M.MESSAGES:
            text = " ".join([m["from"], m["body"], m["context"]])
            for host in re.findall(r"\b[\w.-]+\.(?:com|co\.uk|org|net|uk|io)\b", text):
                self.fail("%s mentions a real-looking address: %s" % (m["id"], host))


class SessionTests(unittest.TestCase):
    def test_structure(self):
        s = M.build_session(42)
        self.assertEqual(s["format"], M.FORMAT)
        trials = s["trials"]
        self.assertEqual(len(trials), 28)
        self.assertEqual([sum(t["round"] == r for t in trials) for r in (1, 2, 3)], [8, 12, 8])
        ids = [t["messageId"] for t in trials]
        self.assertEqual(len(ids), len(set(ids)))
        for r in (1, 2, 3):
            ts = [t for t in trials if t["round"] == r]
            self.assertEqual(sum(t["truth"] == "scam" for t in ts), len(ts) // 2)
            self.assertEqual([t["position"] for t in ts], list(range(len(ts))))

    def test_rounds_one_and_three_are_matched(self):
        for seed in range(20):
            trials = M.build_session(seed)["trials"]
            profile = lambda r: sorted((t["truth"], t["difficulty"]) for t in trials if t["round"] == r)
            self.assertEqual(profile(1), profile(3))
            self.assertEqual(profile(1), sorted([("scam", 1), ("scam", 2), ("scam", 2), ("scam", 3),
                                                 ("genuine", 1), ("genuine", 2), ("genuine", 2), ("genuine", 3)]))

    def test_checker_is_wrong_on_the_designed_number(self):
        for w in range(0, M.MAX_CHECKER_WRONG + 1):
            s = M.build_session(7, "checker", {"checkerWrong": w})
            adv = [t for t in s["trials"] if t["checker"]]
            self.assertEqual(len(adv), 12)
            wrong = [t for t in adv if not t["checker"]["correct"]]
            self.assertEqual(len(wrong), w)
            self.assertEqual(sum(t["truth"] == "scam" for t in wrong), (w + 1) // 2)
            for t in adv:
                c = t["checker"]
                self.assertEqual(c["correct"], c["verdict"] == t["truth"])
                lo, hi = (0.78, 0.98) if c["correct"] else (0.6, 0.85)
                self.assertTrue(lo <= c["confidence"] <= hi, c)

    def test_control_arm_has_no_checker_but_same_messages(self):
        a = M.build_session(99, "checker")
        b = M.build_session(99, "control")
        self.assertTrue(all(t["checker"] is None for t in b["trials"]))
        self.assertEqual([t["messageId"] for t in a["trials"]], [t["messageId"] for t in b["trials"]])

    def test_deterministic_and_varied(self):
        self.assertEqual(M.build_session(5), M.build_session(5))
        self.assertNotEqual([t["messageId"] for t in M.build_session(5)["trials"]],
                            [t["messageId"] for t in M.build_session(6)["trials"]])

    def test_invalid_arm(self):
        with self.assertRaises(ValueError):
            M.build_session(1, "placebo")

    def test_design_is_clamped_and_cleaned(self):
        self.assertEqual(M.normalise_design({"checkerWrong": 99})["checkerWrong"], 6)
        self.assertEqual(M.normalise_design({"checkerWrong": -3})["checkerWrong"], 0)
        self.assertEqual(M.normalise_design({"checkerWrong": "2"})["checkerWrong"], 2)
        self.assertEqual(M.normalise_design({"checkerWrong": 2.9})["checkerWrong"], 2)
        for bad in ("abc", "", None, True, float("nan")):
            self.assertEqual(M.normalise_design({"checkerWrong": bad})["checkerWrong"], 3)
        self.assertEqual(M.normalise_design({"extra": 1}), M.default_design())

    def test_checker_reasons_use_cues_or_decoys(self):
        s = M.build_session(3, "checker", {"checkerWrong": 4})
        for t in s["trials"]:
            reasons = M.checker_reasons(t)
            if not t["checker"]:
                self.assertEqual(reasons, [])
                continue
            m = M.BY_ID[t["messageId"]]
            tags = m["cues"] if t["checker"]["correct"] else m["decoys"]
            self.assertEqual(reasons, [M.CUES[x] for x in tags[:3]])

    def test_arm_allocation_is_reproducible_and_roughly_even(self):
        arms = [M.assign_arm("study-a", "P%03d" % i) for i in range(400)]
        self.assertEqual(arms, [M.assign_arm("study-a", "P%03d" % i) for i in range(400)])
        self.assertTrue(160 < arms.count("checker") < 240)


class ScoringTests(unittest.TestCase):
    def scripted(self):
        """A checker-arm session with hand-written answers covering every case."""
        s = M.build_session(11, "checker", {"checkerWrong": 4})
        for t in s["trials"]:
            truth = t["truth"]
            if t["round"] == 1:
                t["final"] = answer(truth, True)
            elif t["round"] == 3:
                t["final"] = answer(truth if t["position"] < 4 else M.other(truth), False)
        r2 = [t for t in s["trials"] if t["round"] == 2]
        right = [t for t in r2 if t["checker"]["correct"]]
        wrong = [t for t in r2 if not t["checker"]["correct"]]
        # Checker right (8): 4 both right, 2 switched to right, 1 stayed wrong, 1 both right then changed.
        plan_right = ["both", "both", "both", "both", "switch", "switch", "stay", "both_change"]
        for t, p in zip(right, plan_right):
            truth = t["truth"]
            if p == "both":
                t["initial"], t["final"] = answer(truth), answer(truth)
            elif p == "switch":
                t["initial"], t["final"] = answer(M.other(truth), False), answer(truth)
            elif p == "stay":
                t["initial"], t["final"] = answer(M.other(truth)), answer(M.other(truth))
            else:
                t["initial"], t["final"] = answer(truth), answer(M.other(truth), False)
        # Checker wrong (4): 2 kept right, 1 switched to wrong, 1 both wrong.
        plan_wrong = ["keep", "keep", "switch", "bothwrong"]
        for t, p in zip(wrong, plan_wrong):
            truth = t["truth"]
            if p == "keep":
                t["initial"], t["final"] = answer(truth), answer(truth)
            elif p == "switch":
                t["initial"], t["final"] = answer(truth), answer(M.other(truth), False)
            else:
                t["initial"], t["final"] = answer(M.other(truth)), answer(M.other(truth))
        return s

    def test_assisted_cases(self):
        res = M.score_session(self.scripted())
        a = res["assisted"]
        self.assertEqual(a["cases"], {"bothRight": 5, "bothWrong": 1, "switchedToRight": 2,
                                      "stayedWrong": 1, "keptRight": 2, "switchedToWrong": 1})
        self.assertEqual(a["n"], 12)
        self.assertEqual(a["checkerCorrect"], 8)
        self.assertEqual(a["initialCorrect"], 5 + 2 + 1)
        self.assertEqual(a["finalCorrect"], 4 + 2 + 2)
        self.assertAlmostEqual(a["rair"], 2 / 3)
        self.assertAlmostEqual(a["rsr"], 2 / 3)
        self.assertEqual(a["followedWrong"], 2)
        self.assertEqual(a["checkerWrong"], 4)
        self.assertAlmostEqual(a["overReliance"], 0.5)
        self.assertEqual(a["rejectedRight"], 2)
        self.assertAlmostEqual(a["underReliance"], 2 / 8)
        self.assertEqual(a["disagreements"], 6)
        self.assertEqual(a["otherChanges"], 1)
        self.assertEqual(a["switches"], 2 + 1 + 1)
        self.assertAlmostEqual(a["complementarity"], 8 / 12 - 8 / 12)
        self.assertEqual(res["profile"], "calibrated")

    def test_round_stats(self):
        res = M.score_session(self.scripted())
        r1, r2, r3 = res["rounds"]
        self.assertEqual((r1["correct"], r1["n"], r1["accuracy"]), (8, 8, 1.0))
        self.assertAlmostEqual(r1["brier"], 0.05 ** 2)
        self.assertAlmostEqual(r1["overconfidence"], 0.95 - 1)
        self.assertEqual((r3["correct"], r3["n"]), (4, 8))
        self.assertAlmostEqual(r3["brier"], (4 * 0.3 ** 2 + 4 * 0.7 ** 2) / 8)
        self.assertAlmostEqual(res["change"]["accuracy"], -0.5)
        self.assertEqual(r3["hits"] + r3["misses"], 4)
        self.assertEqual(r3["sure"]["n"], 0)
        self.assertIsNone(r3["sure"]["accuracy"])
        self.assertEqual(r2["planned"], 12)

    def test_profiles(self):
        def a(**kw):
            base = {"disagreements": 4, "rair": 1.0, "rsr": 1.0}
            base.update(kw)
            return base
        self.assertEqual(M.classify("checker", a(), True), "calibrated")
        self.assertEqual(M.classify("checker", a(rsr=0.0), True), "over_reliant")
        self.assertEqual(M.classify("checker", a(rair=0.0), True), "under_reliant")
        self.assertEqual(M.classify("checker", a(rair=0.0, rsr=0.0), True), "mixed")
        self.assertEqual(M.classify("checker", a(rair=None, rsr=0.4), True), "over_reliant")
        self.assertEqual(M.classify("checker", a(disagreements=1), True), "few_disagreements")
        self.assertEqual(M.classify("control", None, True), "control")
        self.assertEqual(M.classify("checker", a(), False), "incomplete")

    def test_empty_and_partial_sessions(self):
        s = M.build_session(1)
        res = M.score_session(s)
        self.assertFalse(res["complete"])
        self.assertEqual(res["profile"], "incomplete")
        self.assertIsNone(res["assisted"])
        self.assertIsNone(res["rounds"][0]["accuracy"])
        self.assertIsNone(res["change"]["accuracy"])
        s["trials"][0]["final"] = answer(s["trials"][0]["truth"])
        res = M.score_session(s)
        self.assertEqual(res["rounds"][0]["n"], 1)
        self.assertEqual(res["rounds"][0]["accuracy"], 1.0)

    def test_checker_trial_without_initial_is_incomplete(self):
        s = M.simulate_responses(M.build_session(2), M.PERSONAS["calibrated"], 3)
        t = next(t for t in s["trials"] if t["checker"])
        t["initial"] = None
        self.assertFalse(M.score_session(s)["complete"])


class SimulationTests(unittest.TestCase):
    def test_full_reliance_copies_the_checker(self):
        persona = {"skill": 0.7, "sureBias": 0.0, "reliance": 1.0, "learning": 0.0}
        s = M.simulate_responses(M.build_session(8), persona, 1)
        for t in s["trials"]:
            if t["checker"]:
                self.assertEqual(t["final"]["verdict"], t["checker"]["verdict"])
        a = M.score_session(s)["assisted"]
        self.assertEqual(a["finalAccuracy"], a["checkerAccuracy"])

    def test_no_reliance_keeps_first_answers(self):
        persona = {"skill": 0.7, "sureBias": 0.5, "reliance": 0.0, "learning": 0.0}
        s = M.simulate_responses(M.build_session(8), persona, 1)
        for t in s["trials"]:
            if t["checker"]:
                self.assertEqual(t["final"]["verdict"], t["initial"]["verdict"])

    def test_skill_and_learning_move_accuracy(self):
        def mean_acc(persona, rnd):
            total = 0
            for seed in range(150):
                res = M.score_session(M.simulate_responses(M.build_session(seed), persona, seed + 1000))
                total += res["rounds"][rnd - 1]["accuracy"]
            return total / 150
        low = {"skill": 0.6, "sureBias": 0.5, "reliance": 0.5, "learning": 0.0}
        high = dict(low, skill=0.9)
        learner = dict(low, learning=0.2)
        self.assertGreater(mean_acc(high, 1), mean_acc(low, 1) + 0.15)
        self.assertGreater(mean_acc(learner, 3), mean_acc(low, 3) + 0.1)

    def test_demo_personas_show_their_typical_pattern(self):
        base = M.build_session(M.DEMO_SEEDS["session"], "checker", M.default_design())
        expected = {"calibrated": "calibrated", "leaner": "over_reliant", "loner": "under_reliant"}
        for key, profile in expected.items():
            res = M.score_session(M.simulate_responses(base, M.PERSONAS[key], M.DEMO_SEEDS["responses"]))
            self.assertEqual(res["profile"], profile, key)

    def test_simulation_does_not_modify_the_input(self):
        s = M.build_session(4)
        before = json.dumps(s, sort_keys=True)
        M.simulate_responses(s, M.PERSONAS["leaner"], 9)
        self.assertEqual(before, json.dumps(s, sort_keys=True))


class FileTests(unittest.TestCase):
    def test_validation(self):
        good = M.simulate_responses(M.build_session(1), M.PERSONAS["loner"], 2)
        M.validate_session(good)
        bad_cases = [
            {},
            dict(good, format="other"),
            dict(good, arm="placebo"),
            dict(good, trials=[]),
        ]
        broken = json.loads(json.dumps(good))
        broken["trials"][0]["messageId"] = "zz"
        bad_cases.append(broken)
        wrong_key = json.loads(json.dumps(good))
        wrong_key["trials"][0]["truth"] = M.other(wrong_key["trials"][0]["truth"])
        bad_cases.append(wrong_key)
        bad_answer = json.loads(json.dumps(good))
        bad_answer["trials"][0]["final"] = {"verdict": "maybe", "sure": True}
        bad_cases.append(bad_answer)
        for case in bad_cases:
            with self.assertRaises(ValueError):
                M.validate_session(case)

    def test_load_single_bundle_and_folder(self):
        sessions = [M.simulate_responses(M.build_session(i), M.PERSONAS["calibrated"], i) for i in range(3)]
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "one.json").write_text(json.dumps(sessions[0]))
            write_bundle(sessions[1:], d / "two.json")
            loaded = load_sessions([d])
            self.assertEqual(len(loaded), 3)
            self.assertEqual(load_sessions([d / "one.json"])[0], sessions[0])
            (d / "bad.json").write_text("{not json")
            with self.assertRaises(ValueError):
                load_sessions([d / "bad.json"])

    def test_csv(self):
        s = M.simulate_responses(M.build_session(1), M.PERSONAS["calibrated"], 2)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "a.csv"
            write_csv([s], out)
            lines = out.read_text().splitlines()
            self.assertEqual(lines[0].split(","), M.CSV_COLUMNS)
            self.assertEqual(len(lines), 29)


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = cli(list(argv))
        return code, buf.getvalue()

    def test_demo_score_and_csv(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "s.json")
            code, out = self.run_cli("demo", "--persona", "leaner", "--out", path)
            self.assertEqual(code, 0)
            self.assertIn("Pattern:", out)
            code, out = self.run_cli("score", path)
            self.assertEqual(code, 0)
            self.assertIn("Round 2, With the checker", out)
            code, out = self.run_cli("csv", path, "-o", str(Path(d) / "x.csv"))
            self.assertEqual(code, 0)

    def test_bad_file_gives_clean_error(self):
        code, out = self.run_cli("score", "does-not-exist.json")
        self.assertEqual(code, 2)
        self.assertIn("Error:", out)


if __name__ == "__main__":
    unittest.main()
