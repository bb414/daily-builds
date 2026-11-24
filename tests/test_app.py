"""Checks that the browser app's model (run in Node.js) agrees exactly with the Python package."""

import csv
import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from crutch_check import model as M
from crutch_check.sessions import write_csv

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "index.html"
NODE = shutil.which("node")


def js(calls):
    """Run a list of calls against the app's model in Node and return the results."""
    proc = subprocess.run([NODE, str(ROOT / "tests" / "run_model.js")], input=json.dumps(calls),
                          capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def jsonable(x):
    return json.loads(json.dumps(x))


@unittest.skipUnless(NODE, "Node.js is not installed")
class AppAgreesWithPython(unittest.TestCase):
    def test_message_bank_is_identical(self):
        (bank,) = js([{"get": "BANK"}])
        self.assertEqual(bank, M.BANK)

    def test_constants(self):
        got = js([{"get": "PROFILES"}, {"get": "PERSONAS"}, {"get": "DEMO_SEEDS"}, {"get": "CSV_COLUMNS"},
                  {"get": "CONF_SURE"}, {"get": "CONF_UNSURE"}, {"fn": "defaultDesign"}])
        self.assertEqual(got, [M.PROFILES, M.PERSONAS, M.DEMO_SEEDS, M.CSV_COLUMNS, M.CONF_SURE, M.CONF_UNSURE,
                               M.default_design()])

    def test_hash_and_allocation(self):
        texts = ["", "a", "P001", "study|P001", "Zoë", "李明", "smile \U0001F600", "x" * 300]
        got = js([{"fn": "hashString", "args": [t]} for t in texts])
        self.assertEqual(got, [M.hash_string(t) for t in texts])
        pairs = [("pilot", "P%03d" % i) for i in range(60)] + [("", ""), ("Étude", "Zoë")]
        got = js([{"fn": "assignArm", "args": list(p)} for p in pairs]
                 + [{"fn": "participantSeed", "args": list(p)} for p in pairs])
        self.assertEqual(got, [M.assign_arm(*p) for p in pairs] + [M.participant_seed(*p) for p in pairs])

    def test_sessions_are_identical(self):
        cases = []
        for seed in [0, 1, 2, 42, 2026, 123456789, 4294967295]:
            for arm in ("checker", "control"):
                for w in (0, 1, 3, 4, 6):
                    cases.append((seed, arm, {"checkerWrong": w, "showReasons": w % 2 == 0,
                                              "showConfidence": True}, "P1", "s"))
        got = js([{"fn": "buildSession", "args": list(c)} for c in cases])
        for c, g in zip(cases, got):
            self.assertEqual(g, jsonable(M.build_session(*c)), c)

    def test_design_cleaning_is_identical(self):
        designs = [None, {}, {"checkerWrong": 99}, {"checkerWrong": -2}, {"checkerWrong": "2"},
                   {"checkerWrong": 2.9}, {"checkerWrong": "abc"}, {"checkerWrong": ""},
                   {"checkerWrong": None}, {"checkerWrong": True}, {"showReasons": 0, "extra": 5},
                   {"checkerWrong": "0x5"}, {"checkerWrong": "1_0"}, {"checkerWrong": " 4 "},
                   {"checkerWrong": "2e0"}, {"checkerWrong": "-1.5"}, {"checkerWrong": [3]},
                   {"showReasons": [], "showConfidence": {}}, {"showReasons": False, "showConfidence": "no"}]
        got = js([{"fn": "normaliseDesign", "args": [d]} for d in designs])
        self.assertEqual(got, [M.normalise_design(d) for d in designs])

    def test_simulation_and_scoring_are_identical(self):
        calls, expected = [], []
        personas = list(M.PERSONAS.values()) + [
            {"skill": 0.5, "sureBias": 0.0, "reliance": 1.0, "learning": 0.3},
            {"skill": 1.0, "sureBias": 1.0, "reliance": 0.3, "learning": -0.4},
        ]
        for seed in range(12):
            for k, persona in enumerate(personas):
                arm = "control" if (seed + k) % 3 == 0 else "checker"
                design = {"checkerWrong": (seed + k) % 5, "showReasons": True, "showConfidence": seed % 2 == 0}
                session = M.build_session(seed * 7919, arm, design)
                filled = M.simulate_responses(session, persona, seed + 100 * k)
                calls.append({"fn": "simulateResponses", "args": [session, persona, seed + 100 * k]})
                expected.append(jsonable(filled))
                calls.append({"fn": "scoreSession", "args": [filled]})
                expected.append(jsonable(M.score_session(filled)))
        got = js(calls)
        self.assertEqual(len(got), len(expected))
        for g, e in zip(got, expected):
            self.assertEqual(g, e)

    def test_partial_sessions_score_identically(self):
        filled = M.simulate_responses(M.build_session(77), M.PERSONAS["leaner"], 5)
        partials = []
        for cut in (0, 3, 8, 15, 27):
            p = json.loads(json.dumps(filled))
            for t in p["trials"][cut:]:
                t["initial"] = None
                t["final"] = None
            partials.append(p)
        got = js([{"fn": "scoreSession", "args": [p]} for p in partials])
        self.assertEqual(got, [jsonable(M.score_session(p)) for p in partials])

    def test_rounding_to_points_is_identical(self):
        xs = [0.625, -0.125, 0.125, 0.375, -0.375, 0.005, -0.005, 0, 1, -1, 2 / 3, -1 / 3]
        got = js([{"fn": "points", "args": [x]} for x in xs])
        self.assertEqual(got, [M.points(x) for x in xs])

    def test_inverse_normal_is_identical(self):
        ps = [1e-9, 0.001, 0.02, 0.02425, 0.1, 0.3, 0.5, 0.77, 0.9, 0.97576, 0.99, 0.999999]
        got = js([{"fn": "invNorm", "args": [p]} for p in ps])
        for p, g in zip(ps, got):
            self.assertAlmostEqual(g, M.inv_norm(p), delta=1e-12 * max(1, abs(g)))

    def test_validation_gives_the_same_verdicts_and_messages(self):
        good = M.simulate_responses(M.build_session(3), M.PERSONAS["leaner"], 4)

        def broken(fn):
            x = json.loads(json.dumps(good))
            fn(x)
            return x

        t0 = 0
        t2 = next(i for i, t in enumerate(good["trials"]) if t["checker"])
        cases = [
            good, None, [], "text", {}, dict(good, format="nope"), dict(good, arm="placebo"),
            dict(good, trials=[]), dict(good, trials="x"),
            broken(lambda x: x["trials"].__setitem__(t0, 5)),
            broken(lambda x: x["trials"][t0].__setitem__("messageId", "zz")),
            broken(lambda x: x["trials"][t0].__setitem__("messageId", "__proto__")),
            broken(lambda x: x["trials"][t0].__setitem__("messageId", 7)),
            broken(lambda x: x["trials"][t0].__setitem__("round", 4)),
            broken(lambda x: x["trials"][t0].__setitem__("round", True)),
            broken(lambda x: x["trials"][t0].__setitem__("round", "1")),
            broken(lambda x: x["trials"][t0].__setitem__("truth", M.other(x["trials"][t0]["truth"]))),
            broken(lambda x: x["trials"][t0].__setitem__("final", {"verdict": "maybe", "sure": True})),
            broken(lambda x: x["trials"][t0].__setitem__("final", {"verdict": "scam", "sure": 1})),
            broken(lambda x: x["trials"][t0].__setitem__("final", "scam")),
            broken(lambda x: x["trials"][t2]["checker"].__setitem__("confidence", 1.5)),
            broken(lambda x: x["trials"][t2]["checker"].__setitem__("confidence", True)),
            broken(lambda x: x["trials"][t2]["checker"].__setitem__("correct", not x["trials"][t2]["checker"]["correct"])),
            broken(lambda x: x["trials"][t2].__setitem__("checker", "scam")),
            broken(lambda x: x["trials"][t2].__setitem__("initial", {"verdict": "genuine"})),
            broken(lambda x: x.__setitem__("seed", -1)),
            broken(lambda x: x.__setitem__("seed", "12")),
            broken(lambda x: x.__setitem__("seed", 2 ** 32)),
            broken(lambda x: x.pop("seed")),
            broken(lambda x: x.__setitem__("participant", 12)),
            broken(lambda x: x.__setitem__("study", {"a": 1})),
            broken(lambda x: x["trials"][t0].__setitem__("difficulty", 7)),
            broken(lambda x: x["trials"][t0].__setitem__("channel", "Fax")),
            broken(lambda x: x["trials"][t0].__setitem__("position", -2)),
            broken(lambda x: x["trials"][t0].pop("position")),
            broken(lambda x: x.__setitem__("participant", None)),
            broken(lambda x: x["trials"][t0].__setitem__("final", None)),
        ]

        def py(case):
            try:
                M.validate_session(case)
                return {"ok": True}
            except ValueError as exc:
                return {"error": str(exc)}

        got = js([{"fn": "validateSession", "args": [c], "catchErrors": True} for c in cases])
        self.assertEqual(got, [py(c) for c in cases])
        self.assertEqual(got[0], {"ok": True})
        self.assertEqual(got[-1], {"ok": True})
        self.assertEqual(got[-2], {"ok": True})
        self.assertEqual(sum("error" in g for g in got), len(cases) - 3)

    def test_checker_reasons_are_identical(self):
        s = M.build_session(9, "checker", {"checkerWrong": 4})
        got = js([{"fn": "checkerReasons", "args": [t]} for t in s["trials"]])
        self.assertEqual(got, [M.checker_reasons(t) for t in s["trials"]])

    def test_csv_export_is_identical(self):
        s = M.simulate_responses(M.build_session(31, "checker"), M.PERSONAS["calibrated"], 4)
        c = M.simulate_responses(M.build_session(32, "control"), M.PERSONAS["loner"], 4)
        c["participant"] = 'P "quoted", here'
        s["study"] = "line\rbreak"
        (text,) = js([{"fn": "toCSV", "args": [[s, c]]}])
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "x.csv"
            write_csv([s, c], out)
            self.assertEqual(text, out.read_bytes().decode("utf-8"))
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 56)
        self.assertEqual(rows[-1]["participant"], 'P "quoted", here')


@unittest.skipUnless(NODE, "Node.js is not installed")
class AppOnlyHelpers(unittest.TestCase):
    def test_next_participant_id(self):
        ids = ["P001", "P009", "P099", "P999", "S12", "anna", "", "x0"]
        got = js([{"fn": "nextParticipantId", "args": [i]} for i in ids])
        self.assertEqual(got, ["P002", "P010", "P100", "P1000", "S13", "anna-2", "P001", "x1"])

    def test_bundle_matches_python_format(self):
        from crutch_check.sessions import bundle
        s = M.simulate_responses(M.build_session(5), M.PERSONAS["loner"], 6)
        (got,) = js([{"fn": "makeBundle", "args": [[s]]}])
        self.assertEqual(got, jsonable(bundle([s])))


class AppFileChecks(unittest.TestCase):
    def setUp(self):
        self.html = APP.read_text(encoding="utf-8")

    def test_no_external_requests(self):
        self.assertIsNone(re.search(r"""(src|href)\s*=\s*["']?https?:""", self.html))
        self.assertNotIn("@import", self.html)
        self.assertNotIn("fetch(", self.html)
        self.assertNotIn("XMLHttpRequest", self.html)

    def test_model_markers_present_once(self):
        self.assertEqual(self.html.count("/* MODEL START */"), 1)
        self.assertEqual(self.html.count("/* MODEL END */"), 1)
        self.assertLess(self.html.index("/* MODEL START */"), self.html.index("/* MODEL END */"))


if __name__ == "__main__":
    unittest.main()
