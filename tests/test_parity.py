"""The browser app's model (run in Node.js) and the Python port must agree exactly."""

import json
import random
import unittest

from assurance_mix import model as M

from helpers import APP, NODE, first_difference, run_js
import sys
sys.path.insert(0, str(APP.parent.parent / "tools"))
import sync_catalogue  # noqa: E402

TECH_IDS = [t["id"] for t in M.DATA["techniques"]]


def random_input(rng):
    inp = {"answers": {q["id"]: rng.choice(q["options"])["id"] for q in M.DATA["questions"]}}
    if rng.random() < 0.8:
        inp["appetite"] = rng.choice([2, 3.5, 4, 6, 8, 10, 12, round(rng.uniform(0.5, 25), 2)])
    if rng.random() < 0.8:
        inp["budget"] = rng.choice([0, 20, 60, 100, 150, 250, rng.randint(0, 400)])
    if rng.random() < 0.7:
        inp["weeks"] = rng.choice([0, 3, 6, 10, 14, 20, 30, rng.randint(0, 40)])
    if rng.random() < 0.3:
        inp["legalMust"] = rng.random() < 0.5
    if rng.random() < 0.3:
        inp["must"] = rng.sample(TECH_IDS, rng.randint(1, 2))
    if rng.random() < 0.3:
        inp["exclude"] = rng.sample(TECH_IDS, rng.randint(1, 3))
    if rng.random() < 0.2:
        inp["done"] = rng.sample(TECH_IDS, rng.randint(1, 3))
    if rng.random() < 0.2:
        p = rng.choice(M.PRINCIPLES)
        inp["overrides"] = {"L": {p: rng.choice([1, 2.5, 5, "3"])}, "I": {rng.choice(M.PRINCIPLES): rng.uniform(1, 5)}}
    if rng.random() < 0.1:
        # odd values that both versions must repair the same way
        inp[rng.choice(["appetite", "budget", "weeks"])] = rng.choice(["abc", "1e3", " 7 ", -4, 1e9, "", None, "0x10", "2.5"])
        inp["answers"][rng.choice(list(inp["answers"]))] = rng.choice(["nope", 3, ""])
        inp["must"] = rng.choice(["risk;docs", "made-up", ["aims", "aims"], 7])
    return inp


@unittest.skipIf(NODE is None, "Node.js is not installed")
class ParityTests(unittest.TestCase):
    def test_catalogue_copies_match(self):
        html = APP.read_text(encoding="utf-8")
        self.assertEqual(sync_catalogue.embedded(html), M.DATA,
                         "app/index.html has an old catalogue: run python3 tools/sync_catalogue.py")
        js = run_js([{"kind": "catalogue"}])[0]
        self.assertIsNone(first_difference(js, M.DATA))

    def test_probability_mapping(self):
        vals = [i / 37 for i in range(0, 37 * 6)]
        js = run_js([{"kind": "toProb", "values": vals}, {"kind": "fromProb", "values": [v / 6 for v in vals]}])
        self.assertEqual(js[0], [M.to_prob(v) for v in vals])
        self.assertEqual(js[1], [M.from_prob(v / 6) for v in vals])

    def test_examples_and_random_systems(self):
        rng = random.Random(20261125)
        inputs = [{"answers": e["answers"]} for e in M.DATA["examples"]]
        inputs += [random_input(rng) for _ in range(150)]
        js = run_js([{"kind": "analyse", "input": i} for i in inputs])
        for inp, j in zip(inputs, js):
            py = json.loads(json.dumps(M.analyse(inp)))
            diff = first_difference(j, py)
            self.assertIsNone(diff, "input %s: %s" % (json.dumps(inp), diff))

    def test_pilot_to_scale_ladder(self):
        rng = random.Random(42)
        inputs = [{"answers": e["answers"]} for e in M.DATA["examples"]] + [random_input(rng) for _ in range(30)]
        js = run_js([{"kind": "ladder", "input": i} for i in inputs])
        for inp, j in zip(inputs, js):
            diff = first_difference(j, json.loads(json.dumps(M.ladder(inp))))
            self.assertIsNone(diff, "input %s: %s" % (json.dumps(inp), diff))

    def test_hand_built_plans(self):
        rng = random.Random(7)
        jobs = []
        for _ in range(200):
            jobs.append({"kind": "evaluate", "input": random_input(rng),
                         "ids": rng.sample(TECH_IDS + ["unknown"], rng.randint(0, 8))})
        js = run_js(jobs)
        for job, j in zip(jobs, js):
            py = json.loads(json.dumps(M.evaluate_plan(job["input"], job["ids"])))
            diff = first_difference(j, py)
            self.assertIsNone(diff, "job %s: %s" % (json.dumps(job), diff))


if __name__ == "__main__":
    unittest.main()
