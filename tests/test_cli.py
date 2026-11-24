import contextlib
import io
import json
import unittest

from leaderboard_luck.__main__ import main


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class CommandLineTests(unittest.TestCase):
    def test_simulate_report(self):
        code, out, _ = run(["simulate", "--sims", "200"])
        self.assertEqual(code, 0)
        self.assertIn("Your team is better than 91% of the field.", out)
        self.assertIn("Best chance of winning", out)

    def test_simulate_json_and_options(self):
        code, out, _ = run(["simulate", "--sims", "150", "--rule", "drawdown", "--drawdown-limit", "0.1",
                            "--fat-tails", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["params"]["rule"], "drawdown")
        self.assertTrue(data["params"]["fatTails"])
        self.assertEqual(data["sims"], 150)

    def test_going_for_broke_flags(self):
        code, out, _ = run(["simulate", "--sims", "120", "--catch-up", "--rivals-catch-up", "0.5", "--checkpoint", "0.5"])
        self.assertEqual(code, 0)
        self.assertIn("Going for broke at the checkpoint (day 10)", out)
        self.assertIn("Went for broke", out)

    def test_sample(self):
        code, out, _ = run(["sample", "--index", "3", "--teams", "12"])
        self.assertEqual(code, 0)
        self.assertIn("Challenge number 4", out)
        self.assertIn("Your team", out)

    def test_design(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            out_csv = Path(tmp) / "d.csv"
            out_html = Path(tmp) / "d.html"
            code, out, _ = run(["design", "--sims-each", "8", "--teams", "8", "--workers", "1",
                                "--csv", str(out_csv), "--html", str(out_html)])
            self.assertEqual(code, 0)
            self.assertIn("Chance the most skilled team wins", out)
            self.assertTrue(out_csv.exists() and out_html.exists())
        code, _, err = run(["design", "--sims-each", "0"])
        self.assertEqual(code, 2)

    def test_figures_round_like_the_browser_app(self):
        from leaderboard_luck.report import fixed, pct, signed
        # JavaScript: (6.25).toFixed(1) is "6.3", (1.005).toFixed(2) is "1.00" (1.005 is just below in binary).
        self.assertEqual(pct(0.0625), "6.3%")
        self.assertEqual(fixed(1.005, 2), "1.00")
        self.assertEqual(signed(-0.011), "-1.1%")
        self.assertEqual(signed(0.0004), "0.0%")

    def test_errors(self):
        code, _, err = run(["sample", "--index", "-1"])
        self.assertEqual(code, 2)
        self.assertIn("error:", err)


if __name__ == "__main__":
    unittest.main()
