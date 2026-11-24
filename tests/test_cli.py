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

    def test_sample(self):
        code, out, _ = run(["sample", "--index", "3", "--teams", "12"])
        self.assertEqual(code, 0)
        self.assertIn("Challenge number 4", out)
        self.assertIn("Your team", out)

    def test_errors(self):
        code, _, err = run(["sample", "--index", "-1"])
        self.assertEqual(code, 2)
        self.assertIn("error:", err)


if __name__ == "__main__":
    unittest.main()
