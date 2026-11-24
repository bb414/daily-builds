import contextlib
import io
import json
import os
import tempfile
import unittest

import helpers  # noqa: F401  (puts the project on the path)

from stairstep.__main__ import main


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def test_run_with_every_output(self):
        with tempfile.TemporaryDirectory() as d:
            paths = [os.path.join(d, n) for n in ("r.html", "f.csv", "r.json")]
            code, out, _ = run("run", "--html", paths[0], "--csv", paths[1], "--json", paths[2])
            self.assertEqual(code, 0)
            self.assertIn("The AI model cuts forecast error", out)
            self.assertIn("By product", out)
            self.assertIn("Pushed down", out)
            self.assertIn("Chosen in advance on the 28 weeks", out)
            self.assertIn("Keeping only downward overrides", out)
            with open(paths[0], encoding="utf-8") as f:
                page = f.read()
            self.assertIn("<svg", page)
            self.assertNotIn("http", page)
            with open(paths[1], encoding="utf-8") as f:
                self.assertEqual(len(f.read().strip().splitlines()), 1 + 4992)
            with open(paths[2], encoding="utf-8") as f:
                self.assertEqual(len(json.load(f)["methods"]), 6)

    def test_simulate_then_run_on_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            sales = os.path.join(d, "sales.csv")
            code, out, _ = run("simulate", "--out", sales, "--seed", "4", "--holidays", "0.5")
            self.assertEqual(code, 0)
            self.assertIn("156 weeks", out)
            code, from_file, _ = run("run", "--data", sales, "--seed", "4")
            code2, direct, _ = run("run", "--seed", "4", "--holidays", "0.5")
            self.assertEqual(code, 0)
            # Same numbers either way: only the source line and product labels differ.
            self.assertEqual(from_file.splitlines()[2], direct.splitlines()[2])

    def test_settings_are_applied_and_errors_are_friendly(self):
        code, out, _ = run("run", "--holidays", "0", "--promo-lift", "0")
        self.assertEqual(code, 0)
        self.assertIn("keep moving average", out)
        code, _, err = run("run", "--data", "missing.csv")
        self.assertEqual(code, 2)
        self.assertIn("Error", err)
        code, _, _ = run("run", "--horizon", "two")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
