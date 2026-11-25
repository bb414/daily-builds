import contextlib
import io
import json
import unittest
import unittest.mock

from leaderboard_luck.__main__ import main


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


def table_rows(text):
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith("Place"))
    return [line for line in lines[start + 1:] if line.strip()]


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
        # The top ten, then your team in 11th place; --top 0 shows all twelve teams.
        self.assertEqual(len(table_rows(out)), 11)
        self.assertTrue(table_rows(out)[-1].strip().startswith("11th   Your team"))
        code, out, _ = run(["sample", "--index", "3", "--teams", "12", "--top", "0"])
        self.assertEqual(len(table_rows(out)), 12)

    def test_flat_risk_curve_is_described_as_flat(self):
        code, out, _ = run(["simulate", "--sims", "150", "--rule", "sharpe"])
        self.assertIn("Your chance of winning is the same at every level of risk", out)
        self.assertIn("ranked on: highest Sharpe ratio", out)
        self.assertNotIn("Best chance of winning", out)

    def test_volatility_cap_and_cost(self):
        code, out, _ = run(["simulate", "--sims", "200", "--vol-cap", "0.3", "--cost", "0.1", "--your-vol", "0.5"])
        self.assertEqual(code, 0)
        self.assertIn("Risk rules: volatility capped at 30%; costs of 10% a year per 100% volatility", out)
        self.assertIn("at 50% volatility (held to 30% by the cap)", out)
        code, out, _ = run(["simulate", "--sims", "200", "--json"])
        self.assertFalse(json.loads(out)["params"]["leverageCap"])

    def test_out_of_range_settings_are_pulled_back_with_a_note(self):
        code, out, err = run(["simulate", "--sims", "100", "--gamblers", "20", "--json"])
        self.assertEqual(code, 0)
        self.assertIn("--gamblers 20 is outside 0 to 0.8, so 0.8 was used", err)
        self.assertEqual(json.loads(out)["params"]["gamblers"], 0.8)

    def test_commands_offer_only_the_settings_they_use(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for args in (["sample", "--sims", "100"], ["design", "--days", "60"], ["design", "--rule", "sharpe"]):
                with self.assertRaises(SystemExit):
                    main(args)

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
            self.assertIn("every length from 1 week to 1 year, every scoring rule (drawdown limit 15%)", out)
            self.assertNotIn("trading days", out)
            self.assertTrue(out_csv.exists() and out_html.exists())
            page = out_html.read_text(encoding="utf-8")
            self.assertIn("Your team: true Sharpe 1.00", page)
            self.assertIn("Return, 15% drawdown limit", page)
        code, _, err = run(["design", "--sims-each", "0"])
        self.assertEqual(code, 2)

    def test_check_a_table_file_and_the_examples(self):
        code, out, err = run(["check", "examples/year-long-league.csv", "--days", "250"])
        self.assertEqual(code, 0, err)
        self.assertIn("Possibly some skill", out)
        self.assertIn("Team Fir (2nd)", out)
        self.assertIn("True skill", out)
        self.assertEqual(len(table_rows(out)) - 4, 30)  # thirty teams, then four lines of notes
        code, example, _ = run(["check", "--example", "year"])
        self.assertEqual(example.split("\n")[1:], out.split("\n")[1:])
        code, out, _ = run(["check", "--example", "month", "--json", "--sims", "1000"])
        data = json.loads(out)
        self.assertEqual(data["result"]["verdict"], "luck")
        self.assertEqual(data["result"]["options"]["sims"], 1000)

    def test_check_from_standard_input_with_assumed_risk(self):
        text = "Team,Return\nA,9%\nB,2%\nC,-4%\nD,-7%\n"
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                unittest.mock.patch("sys.stdin", io.StringIO(text)):
            code = main(["check", "-", "--assume-vol", "0.3", "--correlation", "2"])
        self.assertEqual(code, 0)
        self.assertIn("an assumed 30% volatility for 4 teams", out.getvalue())
        self.assertIn("--correlation 2 is outside 0 to 0.9, so 0.9 was used", err.getvalue())

    def test_check_errors(self):
        for args in (["check"], ["check", "x.csv", "--example", "year"], ["check", "no-such-file.csv"]):
            code, _, err = run(args)
            self.assertEqual(code, 2, args)
            self.assertIn("error:", err)

    def test_calibrate(self):
        code, out, _ = run(["calibrate", "--challenges", "4", "--sims", "100", "--workers", "1"])
        self.assertEqual(code, 0)
        self.assertIn("No skill anywhere, four weeks", out)
        self.assertIn("Default field, a year", out)

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
