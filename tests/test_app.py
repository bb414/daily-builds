"""Tests for the browser app: the JavaScript model must agree with the Python model.

The app keeps its model between /* MODEL START */ and /* MODEL END */ markers so these
tests can run exactly the code the browser runs. They need Node.js and are skipped without it.
Run with: python -m unittest discover -s tests
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pilot_purgatory import GOVERNANCE, LEVERS, MOMENTUM, simulate  # noqa: E402
from pilot_purgatory.model import BARRIERS, DEFAULT_ASSUMPTIONS, OUTCOMES, Strategy  # noqa: E402

APP = ROOT / "app" / "index.html"
NODE = shutil.which("node")

# Python field name -> JavaScript field name
STRATEGY_KEYS = {
    "pilots": "pilots",
    "screening": "screening",
    "metrics_upfront": "metricsUpfront",
    "strategy_quarter": "strategyQuarter",
    "scaling_capacity": "scalingCapacity",
    "kill_rule": "killRule",
    "recycle_budget": "recycleBudget",
    "platform_effect": "platformEffect",
    "roi_hurdle": "roiHurdle",
    "abandon_rate": "abandonRate",
}
WORLD_KEYS = {
    "value_median": "valueMedian",
    "value_spread": "valueSpread",
    "scaling_cost_base": "scalingCostBase",
    "scaling_cost_per_complexity": "scalingCostPerComplexity",
    "metrics_boost": "metricsBoost",
    "measurement_noise": "measurementNoise",
    "purgatory_age": "purgatoryAge",
    "launch_cutoff": "launchCutoff",
    "platform_floor": "platformFloor",
}


def model_source() -> str:
    html = APP.read_text(encoding="utf-8")
    match = re.search(r"/\* MODEL START \*/(.*?)/\* MODEL END \*/", html, re.S)
    if not match:
        raise AssertionError("model markers not found in app/index.html")
    return match.group(1)


def run_node(body: str):
    """Run a snippet with the app's model loaded as PP and return its printed JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "run.js"
        script.write_text(model_source() + "\n" + body, encoding="utf-8")
        out = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


class AppIsSelfContained(unittest.TestCase):
    def test_no_external_resources_or_network_calls(self):
        html = APP.read_text(encoding="utf-8")
        self.assertNotRegex(html, r"(src|href)\s*=\s*[\"']https?://")
        self.assertNotRegex(html, r"@import|fetch\(|XMLHttpRequest|WebSocket|navigator\.sendBeacon")

    def test_no_em_dashes(self):
        self.assertNotIn("\u2014", APP.read_text(encoding="utf-8"))

    def test_every_setting_has_a_visible_label(self):
        html = APP.read_text(encoding="utf-8")
        # Inputs are generated from field definitions; every definition must carry a non-empty label.
        definitions = re.findall(r"\{ key: \"(\w+)\"", html)
        labelled = re.findall(r"\{ key: \"(\w+)\", label: \"([^\"]+)\"", html)
        self.assertEqual(len(definitions), 17)
        self.assertEqual([k for k, _ in labelled], definitions)
        self.assertIn('<label for="seed-input">', html)


@unittest.skipUnless(NODE, "Node.js is needed to run the app's JavaScript model")
class JavaScriptMatchesPython(unittest.TestCase):
    RUNS = 3000

    @classmethod
    def setUpClass(cls):
        cls.js = run_node(
            f"""
            var out = {{}};
            [["momentum", PP.MOMENTUM], ["governance", PP.GOVERNANCE]].forEach(function (pair) {{
              var s = PP.simulate(pair[1], {cls.RUNS}, 12, 7, PP.DEFAULT_WORLD);
              out[pair[0]] = {{ outcomeShare: s.outcomeShare, barrierShare: s.barrierShare, net: s.netValue.mean,
                              launched: s.pilotsLaunched, payback: s.paybackQuarter,
                              timeline: s.timeline.map(function (t) {{ return t.netValue; }}) }};
            }});
            out.presets = {{ momentum: PP.MOMENTUM, governance: PP.GOVERNANCE }};
            out.world = PP.DEFAULT_WORLD;
            out.levers = PP.LEVERS.map(function (l) {{ return l[0]; }});
            out.outcomes = PP.OUTCOMES; out.barriers = PP.BARRIERS;
            console.log(JSON.stringify(out));
            """
        )
        cls.py = {
            "momentum": simulate(MOMENTUM, cls.RUNS, 12, 7),
            "governance": simulate(GOVERNANCE, cls.RUNS, 12, 7),
        }

    def test_presets_match(self):
        for name, strategy in (("momentum", MOMENTUM), ("governance", GOVERNANCE)):
            for py_key, js_key in STRATEGY_KEYS.items():
                self.assertEqual(getattr(strategy, py_key), self.js["presets"][name][js_key], f"{name}.{py_key}")
        self.assertEqual(set(STRATEGY_KEYS), {f.name for f in fields(Strategy)} - {"name"})

    def test_world_defaults_match(self):
        for py_key, js_key in WORLD_KEYS.items():
            self.assertEqual(getattr(DEFAULT_ASSUMPTIONS, py_key), self.js["world"][js_key], py_key)
        self.assertEqual(set(WORLD_KEYS), {f.name for f in fields(DEFAULT_ASSUMPTIONS)})

    def test_labels_and_levers_match(self):
        self.assertEqual(self.js["levers"], list(LEVERS))
        self.assertEqual(self.js["outcomes"], list(OUTCOMES))
        self.assertEqual(self.js["barriers"], list(BARRIERS))

    def test_outcome_and_barrier_shares_agree(self):
        for name, py in self.py.items():
            js = self.js[name]
            for o in OUTCOMES:
                self.assertAlmostEqual(js["outcomeShare"][o], py.outcome_share[o], delta=0.025, msg=f"{name} {o}")
            for b in BARRIERS:
                self.assertAlmostEqual(js["barrierShare"][b], py.barrier_share[b], delta=0.03, msg=f"{name} {b}")

    def test_money_and_timing_agree(self):
        for name, py in self.py.items():
            js = self.js[name]
            tolerance = max(400.0, 0.08 * abs(py.net_value.mean))
            self.assertAlmostEqual(js["net"], py.net_value.mean, delta=tolerance, msg=name)
            self.assertAlmostEqual(js["launched"], py.pilots_launched, delta=0.03 * py.pilots_launched, msg=name)
            for q, value in enumerate(js["timeline"]):
                self.assertAlmostEqual(value, py.timeline[q].net_value, delta=max(400.0, 0.1 * abs(value)), msg=f"{name} Q{q + 1}")
            if py.payback_quarter is None:
                self.assertIsNone(js["payback"])
            else:
                self.assertLessEqual(abs(js["payback"] - py.payback_quarter), 1)


@unittest.skipUnless(NODE, "Node.js is needed to run the app's JavaScript model")
class JavaScriptEdgeCases(unittest.TestCase):
    def test_extreme_settings_never_break_the_model(self):
        result = run_node(
            """
            var cases = [
              [{pilots: 1}, 1], [{pilots: 40, screening: 0.8}, 12], [{scalingCapacity: 0}, 12],
              [{abandonRate: 1}, 12], [{roiHurdle: 1, platformEffect: 0.3, recycleBudget: true}, 20],
              [{strategyQuarter: 12, killRule: true}, 4]
            ];
            var out = cases.map(function (c) {
              var s = PP.extend(PP.MOMENTUM, c[0]);
              var r = PP.simulateOnce(s, PP.makeRng(5), c[1], PP.DEFAULT_WORLD);
              var sum = PP.simulate(s, 50, c[1], 3, PP.DEFAULT_WORLD);
              var total = PP.OUTCOMES.reduce(function (t, o) { return t + r.outcomes[o]; }, 0);
              return { pilots: r.pilots, total: total, finite: isFinite(sum.netValue.mean),
                       scaled: r.outcomes[PP.SCALED], timeline: r.timeline.length };
            });
            console.log(JSON.stringify(out));
            """
        )
        quarters = [1, 12, 12, 12, 20, 4]
        for case, q in zip(result, quarters):
            self.assertEqual(case["total"], case["pilots"])
            self.assertTrue(case["finite"])
            self.assertEqual(case["timeline"], q)
        self.assertEqual(result[2]["scaled"], 0)  # no capacity, nothing goes live

    def test_same_seed_same_answer(self):
        a, b = run_node(
            """
            var x = PP.simulate(PP.GOVERNANCE, 100, 12, 99, PP.DEFAULT_WORLD).netValue.mean;
            var y = PP.simulate(PP.GOVERNANCE, 100, 12, 99, PP.DEFAULT_WORLD).netValue.mean;
            console.log(JSON.stringify([x, y]));
            """
        )
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
