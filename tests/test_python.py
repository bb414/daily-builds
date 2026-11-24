"""Tests for the Python companion: CSV networks, the command line and repository hygiene."""

import contextlib
import csv
import io
import json
import os
import tempfile
import unittest

from champion_seeding import cli, model, network_io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples")


def run_cli(*args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(list(args))
    return code, buf.getvalue()


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class NetworkFileTest(unittest.TestCase):
    def test_round_trip_keeps_the_network(self):
        p = model.normalise_params({"people": 60, "teams": 5, "seed": 4})
        net = model.build_network(p)
        with tempfile.TemporaryDirectory() as tmp:
            edges, teams = os.path.join(tmp, "e.csv"), os.path.join(tmp, "t.csv")
            network_io.export_network(net, edges, teams)
            loaded, ids, names = network_io.load_network(edges, teams, seed=4)
        self.assertEqual(loaded["adj"], net["adj"])
        self.assertEqual(loaded["team"], net["team"])
        self.assertEqual(ids[0], "P001")
        self.assertEqual(names[0], "Team 01")
        self.assertEqual(loaded["betweenness"], net["betweenness"])

    def test_loader_tidies_messy_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            edges, teams = os.path.join(tmp, "e.csv"), os.path.join(tmp, "t.csv")
            write(edges, "Source,Target\nann,bo\nbo,ann\nann,ann\nbo,cy\n,dee\ncy,eve\n")
            write(teams, "id,team\nann,Red\nbo,Red\ncy,Blue\nfin,Blue\n")
            net, ids, names = network_io.load_network(edges, teams)
        self.assertEqual(ids, ["ann", "bo", "cy", "eve", "fin"])
        self.assertEqual(names, ["Blue", "Red", "Unassigned"])
        self.assertEqual(net["adj"][0], [1])          # duplicate and self-loop dropped
        self.assertEqual(net["adj"][4], [])           # fin is in the teams file only
        self.assertEqual(net["team"][3], 2)           # eve has no team
        self.assertEqual(net["edges"], 3)

    def test_loader_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.csv")
            write(bad, "from,to\na,b\n")
            with self.assertRaisesRegex(ValueError, "source, target"):
                network_io.load_network(bad)
            tiny = os.path.join(tmp, "tiny.csv")
            write(tiny, "source,target\na,b\n")
            with self.assertRaisesRegex(ValueError, "at least three"):
                network_io.load_network(tiny)
            with self.assertRaisesRegex(ValueError, "Could not read"):
                network_io.load_network(os.path.join(tmp, "missing.csv"))

    def test_bundled_example_files_load(self):
        net, ids, names = network_io.load_network(os.path.join(EXAMPLES, "edges.csv"), os.path.join(EXAMPLES, "teams.csv"))
        self.assertEqual(net["size"], 180)
        self.assertEqual(len(names), 12)


class CliTest(unittest.TestCase):
    small = ["--set", "runs=10", "--set", "weeks=20", "--set", "people=60", "--set", "teams=5"]

    def test_compare_text_json_and_csv(self):
        code, out = run_cli("compare", *self.small, "--champions-list")
        self.assertEqual(code, 0)
        self.assertIn("Why:", out)
        for label in model.STRATEGY_LABELS.values():
            self.assertIn(label, out)
        code, out = run_cli("compare", *self.small, "--json")
        data = json.loads(out)
        self.assertEqual(len(data["results"]), 5)
        self.assertNotIn("curveMean", data["results"][0])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "curves.csv")
            run_cli("compare", *self.small, "--csv", path)
            with open(path, encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 5 * 21)

    def test_load_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            edges, teams = os.path.join(tmp, "e.csv"), os.path.join(tmp, "t.csv")
            code, out = run_cli("export-network", "--edges", edges, "--teams", teams, "--set", "people=60", "--set", "teams=5")
            self.assertIn("60 people", out)
            code, out = run_cli("load", "--edges", edges, "--teams", teams, *self.small[:4], "--champions-list")
            self.assertIn("P0", out)
            code, out = run_cli("load", "--edges", edges, *self.small[:4])
            self.assertIn("no teams file", out)

    def test_sweep(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sweep.csv")
            code, out = run_cli("sweep", "--param", "champions", *self.small, "--csv", path)
            with open(path, encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
        self.assertIn("wins", out)
        self.assertIn("*", out)
        self.assertEqual(len(rows), 5 * len(model.SWEEPS["champions"]))
        self.assertEqual(sum(int(r["best"]) for r in rows), len(model.SWEEPS["champions"]))

    def test_bad_arguments_exit_cleanly(self):
        for args in (["compare", "--set", "nonsense=1"], ["compare", "--set", "runs=lots"], ["compare", "--set", "x"],
                     ["compare", "--set", "strategy=magic"], ["compare", "--preset", "nope"],
                     ["load", "--edges", "/nonexistent/e.csv"], ["sweep", "--param", "people"], ["compare", *self.small, "--csv", "/nonexistent/dir/x.csv"]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as ctx:
                with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                    cli.main(list(args))
            self.assertNotEqual(ctx.exception.code, 0)


class HygieneTest(unittest.TestCase):
    def test_no_em_dashes_anywhere(self):
        dash = "\u2014"
        found = []
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for name in files:
                path = os.path.join(folder, name)
                try:
                    with open(path, encoding="utf-8") as fh:
                        if dash in fh.read():
                            found.append(os.path.relpath(path, ROOT))
                except (UnicodeDecodeError, OSError):
                    continue
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
