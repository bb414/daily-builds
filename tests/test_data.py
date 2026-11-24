import os
import tempfile
import unittest

import helpers  # noqa: F401  (puts the project on the path)

from stairstep import data as datafile
from stairstep import model


class CsvTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def path(self, name):
        return os.path.join(self.dir.name, name)

    def write(self, name, text):
        with open(self.path(name), "w", encoding="utf-8") as f:
            f.write(text)
        return self.path(name)

    def test_round_trip_gives_identical_numbers(self):
        original = model.simulate({"seed": 9})
        datafile.write_csv(original, self.path("sales.csv"))
        loaded = datafile.read_csv(self.path("sales.csv"))
        self.assertEqual(loaded["sales"], original["sales"])
        self.assertEqual(loaded["promo"], original["promo"])
        self.assertEqual([e["flags"] for e in loaded["events"]], [e["flags"] for e in original["events"]])
        a = model.evaluate(original, model.forecast_all(original, {"seed": 9}))
        b = model.evaluate(loaded, model.forecast_all(loaded, {"seed": 9}))
        self.assertEqual(a["methods"], b["methods"])
        self.assertEqual(a["overrides"], b["overrides"])

    def test_minimal_file_without_promotions_or_events(self):
        lines = ["week,store,product,units"]
        for t in range(1, 113):
            for store in ("north", "south"):
                lines.append("%d,%s,fudge,%d" % (t, store, 10 + (t % 7)))
        data = datafile.read_csv(self.write("min.csv", "\n".join(lines) + "\n"))
        self.assertEqual((data["weeks"], data["testStart"]), (112, 60))
        self.assertEqual(data["events"], [])
        r = model.evaluate(data, model.forecast_all(data, {}))
        self.assertEqual(r["methods"][0]["n"], 2 * 52)

    def test_helpful_errors(self):
        cases = {
            "no_columns.csv": ("a,b\n1,2\n", "needs these columns"),
            "empty.csv": ("week,store,product,units\n", "no rows"),
            "short.csv": ("week,store,product,units\n1,a,b,3\n", "at least 112"),
            "bad_units.csv": ("week,store,product,units\n1,a,b,lots\n", "should be a number"),
            "negative.csv": ("week,store,product,units\n1,a,b,-2\n", "whole number"),
            "week_zero.csv": ("week,store,product,units\n0,a,b,2\n", "start at 1"),
            "blank_store.csv": ("week,store,product,units\n1,,b,2\n", "cannot be empty"),
            "duplicate.csv": ("week,store,product,units\n1,a,b,2\n1,a,b,3\n", "second row"),
        }
        for name, (text, message) in cases.items():
            with self.assertRaises(datafile.DataError) as ctx:
                datafile.read_csv(self.write(name, text))
            self.assertIn(message, str(ctx.exception), name)
        gap = ["week,store,product,units"] + ["%d,a,b,5" % t for t in range(1, 121) if t != 50]
        with self.assertRaises(datafile.DataError) as ctx:
            datafile.read_csv(self.write("gap.csv", "\n".join(gap)))
        self.assertIn("no gaps", str(ctx.exception))
        missing = ["week,store,product,units"] + ["%d,a,b,5" % t for t in range(1, 121)] + ["1,c,b,4"]
        with self.assertRaises(datafile.DataError) as ctx:
            datafile.read_csv(self.write("missing.csv", "\n".join(missing)))
        self.assertIn("rows are missing", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
