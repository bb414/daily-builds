"""Prove the browser app's rules engine and the Python port agree exactly.

Runs the MODEL block from app/index.html in Node.js (through tests/model_bridge.js)
and compares it with the Python package. Skipped if Node.js is not installed.
"""

import json
import pathlib
import random
import shutil
import subprocess
import unittest

from ai_act_triage import model

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def call_js(calls):
    result = subprocess.run([NODE, str(ROOT / "tests" / "model_bridge.js")], input=json.dumps({"calls": calls}),
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def random_answers(n, seed):
    rng = random.Random(seed)
    areas = [""] + [x["id"] for x in model.RULES["annex3"]]
    derogations = [""] + [x["id"] for x in model.RULES["derogations"]]
    bans = [x["id"] for x in model.RULES["prohibitions"]]
    out = []
    for _ in range(n):
        out.append({
            "name": rng.choice(["", "A system", "Système d’essai"]),
            "role": rng.choice(model.ROLES), "takeover": rng.random() < 0.3, "eu": rng.random() < 0.9,
            "excluded": rng.choice(model.EXCLUSIONS + ["none"] * 4),
            "prohibited": rng.sample(bans, rng.choice([0, 0, 0, 0, 1, 2])),
            "annex1": rng.random() < 0.2, "annex3": rng.choice(areas + [""] * 3), "derogation": rng.choice(derogations + [""] * 2),
            "profiling": rng.random() < 0.4, "interacts": rng.random() < 0.4, "generates": rng.random() < 0.3,
            "generatedBefore": rng.random() < 0.5, "emotionBiocat": rng.random() < 0.2, "deepfake": rng.random() < 0.2,
            "gpai": rng.choice(model.GPAI + ["none"] * 3), "gpaiBefore": rng.random() < 0.4, "gpaiOpen": rng.random() < 0.4,
            "deployerType": rng.choice(model.DEPLOYER_TYPES), "workplace": rng.random() < 0.4,
            "turnover": rng.choice([0, 3.5, 12, 60, 400, 2500, 90000]), "sme": rng.random() < 0.4,
        })
    return out


@unittest.skipUnless(NODE, "Node.js is not installed")
class ParityTests(unittest.TestCase):
    def test_rules_and_constants_match(self):
        js = call_js([{"fn": k} for k in ("RULES", "TIERS", "TIER_ORDER", "ROLES", "EXCLUSIONS", "GPAI", "DEPLOYER_TYPES")])
        self.assertEqual(js[0], model.RULES, "Run python tools/sync_rules.py after editing rules.json")
        self.assertEqual(js[1:], [model.TIERS, model.TIER_ORDER, model.ROLES, model.EXCLUSIONS, model.GPAI, model.DEPLOYER_TYPES])

    def test_classifications_match(self):
        dates = ["2026-11-24", "2025-01-01", "2026-12-02", "2027-12-01", "2028-08-02", "2030-01-01", "bad", None]
        answers = random_answers(400, 1)
        calls = [{"fn": "classify", "args": [a, dates[k % len(dates)]]} for k, a in enumerate(answers)]
        for js, call in zip(call_js(calls), calls):
            self.assertEqual(js, model.classify(*call["args"]), json.dumps(call["args"]))

    def test_odd_answers_are_read_the_same_way(self):
        odd = [None, [], "text", 7, {}, {"role": "Provider", "eu": 0, "prohibited": "csam", "turnover": "1e3"},
               {"role": "both", "eu": None, "prohibited": ["csam", "csam", 5, None], "annex3": "toString", "turnover": [40]},
               {"turnover": "-5", "gpai": "systemic", "takeover": "yes", "sme": 1, "name": 42},
               {"turnover": "0x10", "deployerType": "publicService", "annex3": "credit", "name": "x" * 300}]
        js = call_js([{"fn": "normalise", "args": [a]} for a in odd])
        for a, j in zip(odd, js):
            self.assertEqual(j, model.normalise(a), repr(a))

    def test_roadmaps_match(self):
        answers = random_answers(60, 2)
        for as_of in ("2026-11-24", "2027-12-02", "2025-06-01"):
            results = [model.classify(a, as_of) for a in answers]
            js = call_js([{"fn": "roadmap", "args": [results]}, {"fn": "roadmap", "args": [results[:1]]},
                          {"fn": "roadmap", "args": [[]]}])
            self.assertEqual(js, [model.roadmap(results), model.roadmap(results[:1]), model.roadmap([])])

    def test_dates_match(self):
        isos = ["2026-02-30", "2028-02-29", "2027-13-01", "2026-1-01", "", None, "2026-11-24"]
        js = call_js([{"fn": "validIso", "args": [s]} for s in isos])
        self.assertEqual(js, [model.valid_iso(s) for s in isos])
        js = call_js([{"fn": "longDate", "args": [d]} for d in ("2027-12-02", "2025-02-02")] +
                     [{"fn": "daysBetween", "args": ["2026-11-24", d]} for d in ("2027-12-02", "2025-02-02")])
        self.assertEqual(js, ["2 December 2027", "2 February 2025", 373, -660])


if __name__ == "__main__":
    unittest.main()
