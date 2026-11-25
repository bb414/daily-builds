import math
import unittest

from mislabelled import model as M


class ArithmeticTest(unittest.TestCase):
    def test_ln_and_exp_are_accurate(self):
        for x in [1e-9, 0.001, 0.5, 1, 2, 3.7, 1234.5, 98765]:
            self.assertAlmostEqual(M.ln(x), math.log(x), delta=1e-13 * max(1, abs(math.log(x))))
        for x in [-60, -1.3, 0, 0.7, 5]:
            self.assertAlmostEqual(M.exp(x), math.exp(x), delta=1e-13 * math.exp(x))
        self.assertEqual(M.exp(-800), 0)
        with self.assertRaises(ValueError):
            M.ln(0)

    def test_mulberry32_known_values(self):
        r = M.mulberry32(42)
        self.assertEqual([r(), r(), r()], [0.6011037519201636, 0.44829055899754167, 0.8524657934904099])

    def test_seed_for_differs_by_label(self):
        self.assertNotEqual(M.seed_for(1, "a"), M.seed_for(1, "b"))
        self.assertEqual(M.seed_for(5, "x"), M.seed_for(5, "x"))


class StatementTest(unittest.TestCase):
    def test_reproducible_and_valid(self):
        a = M.generate_statement("graduate", 13, 3)
        self.assertEqual(a, M.generate_statement("graduate", 13, 3))
        self.assertGreater(len(a["tx"]), 150)
        for t in a["tx"]:
            self.assertIsInstance(t["pennies"], int)
            self.assertGreaterEqual(t["pennies"], 50)
            self.assertTrue(0 <= t["cat"] < M.C)
        rent = [t for t in a["tx"] if t["desc"] == "TO J OKAFOR REF RENT"]
        self.assertEqual([t["date"] for t in rent], ["2026-10-01", "2026-11-01", "2026-12-01"])

    def test_unknown_persona(self):
        with self.assertRaises(ValueError):
            M.generate_statement("nobody", 4, 1)

    def test_featurise(self):
        f = M.featurise("PAYWALLET *NOODLENOOK BRIGHTON", 717, 6)
        self.assertEqual(f["feats"], ["c:WALLET", "m:NOODLENOOK", "w:NOODLENOOK", "a:1", "d:we"])
        f = M.featurise("www.munchbox.com ab12cd", 2299, 1)
        self.assertEqual(f["key"], "MUNCHBOX")


class LearningTest(unittest.TestCase):
    def test_correction_teaches_the_merchant(self):
        st = M.generate_statement("graduate", 13, 1)
        s = M.Session(st)
        rent = [i for i, t in enumerate(st["tx"]) if t["desc"] == "TO J OKAFOR REF RENT"]
        bills = M.CATS.index("Bills")
        self.assertTrue(all(s.reported(i) != bills for i in rent))
        before = s.metrics()["misP"]
        s.correct(rent[0], bills)
        self.assertTrue(all(s.reported(i) == bills for i in rent))
        self.assertLess(s.metrics()["misP"], before - 200000)

    def test_incremental_equals_recount(self):
        st = M.generate_statement("student", 5, 8)
        s = M.Session(st, weight=5)
        for t in (1, 4, 12, 30):
            s.correct(t, (st["tx"][t]["cat"] + 3) % M.C)
        for t in range(len(st["tx"])):
            for c in range(M.C):
                self.assertEqual(s.model.feat_sum[t][c], s.model.sum_for(t, c))

    def test_all_checked_means_no_wrong_pot(self):
        st = M.generate_statement("sixthformer", 2, 3)
        for sid in M.STRATEGY_IDS:
            r = M.run_curve(st, sid, checks=len(st["tx"]) + 3)
            self.assertEqual(r["points"][-1]["misPct"], 0)
            self.assertEqual(len(r["points"]), len(st["tx"]) + 1)

    def test_checks_to_target(self):
        self.assertEqual(M.checks_to_target([{"misPct": 7}, {"misPct": 5}], 5), 1)
        self.assertIsNone(M.checks_to_target([{"misPct": 7}], 5))


if __name__ == "__main__":
    unittest.main()
