import csv
import io
import json
import os
import tempfile
import unittest

from mislabelled import cli
from mislabelled import model as M


def run(argv):
    out = io.StringIO()
    code = cli.main(argv, out=out)
    return code, out.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, name):
        return os.path.join(self.dir, name)

    def test_sample_writes_a_labelled_statement(self):
        code, text = run(["sample", "--persona", "sixthformer", "--weeks", "4", "-o", self.path("s.csv")])
        self.assertEqual(code, 0)
        with open(self.path("s.csv"), newline="") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), len(M.generate_statement("sixthformer", 4, 1)["tx"]))
        self.assertIn(rows[0]["category"], M.CATS)
        self.assertIn("invented payments", text)

    def test_compare_writes_outputs(self):
        code, text = run(["compare", "--persona", "graduate", "--seeds", "2", "--weeks", "4", "--checks", "15",
                          "--out", self.path("out")])
        self.assertEqual(code, 0)
        for name in ("curves.csv", "summary.csv", "report.html"):
            self.assertTrue(os.path.exists(os.path.join(self.path("out"), name)), name)
        with open(os.path.join(self.path("out"), "summary.csv"), newline="") as fh:
            summary = list(csv.DictReader(fh))
        self.assertEqual(len(summary), 5)
        self.assertAlmostEqual(sum(float(r["fastest_on"]) for r in summary), 2.0, places=6)
        self.assertIn("Sam, graduate", text)
        with open(os.path.join(self.path("out"), "curves.csv"), newline="") as fh:
            self.assertEqual(sum(1 for _ in fh), 1 + 2 * 5 * 16)

    def test_categorise_learns_from_labelled_rows(self):
        st = M.generate_statement("graduate", 13, 1)
        with open(self.path("mine.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Date", "Description", "Amount", "Category"])
            labelled = False
            for t in st["tx"]:
                d = t["date"]
                uk_date = d[8:10] + "/" + d[5:7] + "/" + d[0:4]
                label = ""
                if t["desc"] == "TO J OKAFOR REF RENT" and not labelled:
                    label, labelled = M.CATS[t["cat"]], True
                w.writerow([uk_date, t["desc"], "-%.2f" % (t["pennies"] / 100), label])
        code, text = run(["categorise", self.path("mine.csv"), "-o", self.path("done.csv")])
        self.assertEqual(code, 0, text)
        with open(self.path("done.csv"), newline="") as fh:
            rows = list(csv.DictReader(fh))
        rent = [r for r in rows if r["description"] == "TO J OKAFOR REF RENT"]
        self.assertEqual(rent[0]["source"], "you")
        self.assertTrue(all(r["pot"] == "Bills" for r in rent))
        self.assertTrue(all(r["app_day_one_guess"] == "Transfers" for r in rent))
        self.assertIn("1 with your own category", text)

    def test_replay_matches_the_model(self):
        run(["sample", "--persona", "student", "--weeks", "6", "--seed", "3", "-o", self.path("s.csv")])
        code, text = run(["categorise", self.path("s.csv"), "--replay", "--checks", "20", "--seed", "3",
                          "-o", self.path("r.html")])
        self.assertEqual(code, 0, text)
        st = M.generate_statement("student", 6, 3)
        res = M.compare_strategies(st, checks=20)
        for r in res:
            self.assertIn("%.1f%% after 20" % r["points"][-1]["misPct"], text)
        self.assertTrue(os.path.exists(self.path("r.html")))

    def test_bad_inputs_are_reported(self):
        with open(self.path("bad.csv"), "w") as fh:
            fh.write("date,description\n2026-01-01,SHOP\n")
        code, text = run(["categorise", self.path("bad.csv")])
        self.assertEqual(code, 2)
        self.assertIn("missing column(s): amount", text)
        with open(self.path("bad2.csv"), "w") as fh:
            fh.write("date,description,amount,category\n2026-01-01,SHOP,3.20,Snacks\n")
        code, text = run(["categorise", self.path("bad2.csv")])
        self.assertIn("unknown category 'Snacks'", text)
        with open(self.path("bad3.csv"), "w") as fh:
            fh.write("date,description,amount,category\n2026-01-01,SHOP,3.20,\n")
        code, text = run(["categorise", self.path("bad3.csv"), "--replay"])
        self.assertEqual(code, 2)
        self.assertIn("needs a category on every row", text)
        with self.assertRaises(SystemExit):
            run(["compare", "--weeks", "0"])
        with self.assertRaises(SystemExit):
            run(["compare", "--persona", "nobody"])

    def test_weekly_prints_months_and_writes_csv(self):
        code, text = run(["weekly", "--persona", "student", "--seeds", "2", "--weeks", "9", "--per-week", "2",
                          "--out", self.path("w.csv")])
        self.assertEqual(code, 0)
        self.assertIn("Never checks", text)
        self.assertIn("Sep*", text)
        self.assertIn("Habits change in week 7", text)
        with open(self.path("w.csv"), newline="") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 2 * 6 * 3)  # seeds x (strategies + never) x months
        self.assertEqual({r["part_month"] for r in rows}, {"yes", "no"})
        with self.assertRaises(SystemExit):
            run(["weekly", "--per-week", "-1"])

    def test_weekly_table_skips_empty_months(self):
        rows = [{"persona": "student", "strategy": sid, "month": "2026-12", "name": "Dec", "partial": True,
                 "misPct": 0, "n": 0} for sid in ["none"] + M.STRATEGY_IDS]
        text = cli.format_weekly(rows, ["student"], 3)
        self.assertIn("Never checks", text)
        self.assertNotIn("0.0%", text)
        self.assertIn("-", text.splitlines()[-3])

    def test_seed_list_forms(self):
        self.assertEqual(cli._seed_list("3"), [1, 2, 3])
        self.assertEqual(cli._seed_list("5-7"), [5, 6, 7])
        self.assertEqual(cli._seed_list("2,9"), [2, 9])

    def test_quantile(self):
        self.assertEqual(M.quantile([1, 2, 3, 4], 0.5), 2.5)
        self.assertEqual(M.quantile([5], 0.9), 5)
        self.assertIsNone(M.quantile([], 0.5))

    def test_settings_file_from_the_app(self):
        settings = {"persona": "sixthformer", "weeks": 5, "seed": 9, "weight": 12, "target": 8, "checks": 20,
                    "slip": 0, "perweek": 2}
        with open(self.path("saved.json"), "w") as fh:
            json.dump({"app": "mislabelled", "version": 1, "settings": settings, "checks": []}, fh)
        code, text = run(["compare", "--settings", self.path("saved.json"), "--seeds", "2"])
        self.assertEqual(code, 0)
        self.assertIn("Alex, sixth-former", text)
        self.assertNotIn("Jess", text)
        self.assertIn("5 weeks each, up to 20 checks", text)
        self.assertIn("8% target", text)
        code, text = run(["weekly", "--settings", self.path("saved.json"), "--seeds", "1", "--per-week", "4"])
        self.assertIn("4 checks a week", text)
        with open(self.path("not.json"), "w") as fh:
            fh.write("{}")
        with self.assertRaises(SystemExit):
            run(["compare", "--settings", self.path("not.json")])


if __name__ == "__main__":
    unittest.main()
