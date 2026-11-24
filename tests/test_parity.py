"""Prove the browser app's rules engine and the Python port agree exactly.

Runs the MODEL block from app/index.html in Node.js (through tests/model_bridge.js)
and compares it with the Python package. Skipped if Node.js is not installed.
"""

import csv
import io
import json
import pathlib
import random
import shutil
import subprocess
import unittest

from ai_act_triage import model, register

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

    def test_pivots_match(self):
        answers = random_answers(80, 3) + model.RULES["examples"] + [{"eu": False, "excluded": "military"}]
        calls = [{"fn": "pivots", "args": [a, "2026-11-24" if k % 2 else "2027-12-02"]} for k, a in enumerate(answers)]
        for js, call in zip(call_js(calls), calls):
            self.assertEqual(js, model.pivots(*call["args"]), json.dumps(call["args"]))

    def test_euros_match(self):
        values = [0, 1, 999.5, 360000, 1234567, 1250000, 1255000, 14999999.5, 999995000, 999994999, 1.4e9, 2.125e9, 7e10]
        self.assertEqual(call_js([{"fn": "euros", "args": [v]} for v in values]), [model.euros(v) for v in values])

    def test_register_files_match(self):
        answers = random_answers(40, 4) + [{"name": 'Comma, "quote"\nline', "turnover": 1e-7}, {"name": "x", "turnover": 0.00001}]
        js_csv = call_js([{"fn": "registerCsv", "args": [answers]}])[0]
        self.assertEqual(js_csv, register.to_csv(answers))
        texts = [js_csv, register.to_csv(model.RULES["examples"]), "", "\n\n", "title\nx\n", "name,role\n",
                 "\ufeff Name ,ROLE,profiling,colour,,name\nA,boss,maybe,blue,zz,B\n,,,\n\"C\",provider,YES\n",
                 'name,turnover,prohibited,eu\r\n"open quote,12\r\nD,abc,"csam, madeUp;socialScoring",\r\nE,-1,,No\r\nF,0x10,,maybe\n',
                 'name,annex3,derogation,gpai,deployerType,excluded\nG,credit,improve,systemic,publicService,research\nH,Credit,x,,nope,\n',
                 'a"b,name\n"x"y,z\n"""q""",w\n', "constructor,name,__proto__,toString\nA,B,C,D\n",
                 "name,turnover\nbig," + "9" * 200000 + "\n"]
        js = call_js([{"fn": "readRegisterCsv", "args": [t]} for t in texts] + [{"fn": "csvRows", "args": [t]} for t in texts])
        for t, j in zip(texts, js[:len(texts)]):
            self.assertEqual(j, register.read_csv_text(t), repr(t))
        for t, j in zip(texts, js[len(texts):]):
            self.assertEqual(j, list(csv.reader(io.StringIO(t[1:] if t.startswith("\ufeff") else t, newline=""))), repr(t))

    def test_input_notes_match(self):
        odd = [None, [], "x", {}, {"role": "Deployer", "annex3": "Employment", "profiling": "yes", "prohibited": "csam", "turnover": "lots",
               "colour": 1, "id": "x", "eu": None, "name": 5}, {"2": 1, "b": 2, "1": 3, "name": "n" * 130, "turnover": 1e9},
               {"prohibited": ["csam", 4, None, "made up"], "gpai": ["gpai"], "annex3": "", "derogation": "", "sme": 1.5, "turnover": -2},
               {"turnover": "400\u202f", "takeover": "true", "excluded": None, "deployerType": "publicAuthority"},
               {"turnover": 10 ** 400}, {"turnover": "0x" + "f" * 300}, {"turnover": [1, 2]}, {"turnover": 1e-7},
               {"turnover": 1152921504606846976, "sme": 123456789012345678901234, "name": 2 ** 70, "role": 1e16},
               {"1" * 5000: 1, "4294967294": 1, "4294967295": 2, "01": 3, "-1": 4}] + model.RULES["examples"]
        js = call_js([{"fn": "inputNotes", "args": [a]} for a in odd])
        for a, j in zip(odd, js):
            self.assertEqual(j, model.input_notes(a), repr(a)[:200])

    def test_numbers_and_dates_at_the_edges(self):
        values = ["400\u202f", "\u3000 12 \u2028", "\x1c5", "0x" + "f" * 300, 10 ** 400, "1e400", " -0 ", "0b101", "Infinity"]
        js = call_js([{"fn": "normalise", "args": [{"turnover": v}]} for v in values])
        self.assertEqual([j["turnover"] for j in js], [model.normalise({"turnover": v})["turnover"] for v in values])
        isos = ["0050-01-01", "0099-12-31", "0100-01-01", "1900-02-29", "2000-02-29", "9999-12-31"]
        self.assertEqual(call_js([{"fn": "validIso", "args": [d]} for d in isos]), [model.valid_iso(d) for d in isos])

    def test_number_strings_match(self):
        rng = random.Random(5)
        values = [rng.choice([1, -1]) * rng.random() * 10 ** rng.randint(-12, 30) for _ in range(400)]
        values += [2 ** k for k in range(0, 80, 3)] + [0, 1e21, 1e-6, 1e-7, 123456789012345680000.0]
        js = call_js([{"fn": "registerCsv", "args": [[{"turnover": abs(v)} for v in values]]}])[0]
        self.assertEqual(js, register.to_csv([{"turnover": abs(v)} for v in values]))
        notes = call_js([{"fn": "inputNotes", "args": [{"sme": v}]} for v in values])
        self.assertEqual(notes, [model.input_notes({"sme": v}) for v in values])

    def test_dates_match(self):
        isos = ["2026-02-30", "2028-02-29", "2027-13-01", "2026-1-01", "", None, "2026-11-24"]
        js = call_js([{"fn": "validIso", "args": [s]} for s in isos])
        self.assertEqual(js, [model.valid_iso(s) for s in isos])
        js = call_js([{"fn": "longDate", "args": [d]} for d in ("2027-12-02", "2025-02-02")] +
                     [{"fn": "daysBetween", "args": ["2026-11-24", d]} for d in ("2027-12-02", "2025-02-02")])
        self.assertEqual(js, ["2 December 2027", "2 February 2025", 373, -660])


if __name__ == "__main__":
    unittest.main()
