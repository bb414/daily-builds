"""Unit tests for the Python model."""

import math
import unittest

from fittotrain import model


def mean(xs):
    return sum(xs) / len(xs)


class TestBuildingBlocks(unittest.TestCase):
    def test_random_numbers_are_uniform_and_repeatable(self):
        a = model.mulberry32(5)
        b = model.mulberry32(5)
        xs = [a() for _ in range(20000)]
        self.assertEqual(xs[:10], [b() for _ in range(10)])
        self.assertTrue(all(0 <= x < 1 for x in xs))
        self.assertAlmostEqual(mean(xs), 0.5, delta=0.01)

    def test_sigmoid_is_stable_at_extremes(self):
        self.assertEqual(model.sigmoid(0), 0.5)
        self.assertAlmostEqual(model.sigmoid(800), 1.0)
        self.assertAlmostEqual(model.sigmoid(-800), 0.0)
        self.assertAlmostEqual(model.sigmoid(2) + model.sigmoid(-2), 1.0)

    def test_auc_known_values(self):
        self.assertEqual(model.auc([0.1, 0.2, 0.3, 0.4], [0, 0, 1, 1]), 1.0)
        self.assertEqual(model.auc([0.4, 0.3, 0.2, 0.1], [0, 0, 1, 1]), 0.0)
        self.assertEqual(model.auc([0.5, 0.5, 0.5, 0.5], [0, 1, 0, 1]), 0.5)
        self.assertAlmostEqual(model.auc([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]), 0.75)
        self.assertIsNone(model.auc([0.1, 0.2], [1, 1]))

    def test_solve_matches_a_known_system(self):
        x = model.solve([[2, 1, -1], [-3, -1, 2], [-2, 1, 2]], [8, -11, -3])
        for got, want in zip(x, [2, 3, -1]):
            self.assertAlmostEqual(got, want)

    def test_logistic_fit_recovers_known_coefficients(self):
        r = model.mulberry32(11)
        xs, ys = [], []
        for _ in range(20000):
            a, b = r() * 4 - 2, 1 if r() < 0.5 else 0
            p = model.sigmoid(-0.5 + 1.2 * a - 0.8 * b)
            xs.append([1, a, b])
            ys.append(1 if r() < p else 0)
        beta = model.fit_logistic(xs, ys)["beta"]
        self.assertAlmostEqual(beta[0], -0.5, delta=0.08)
        self.assertAlmostEqual(beta[1], 1.2, delta=0.08)
        self.assertAlmostEqual(beta[2], -0.8, delta=0.08)

    def test_names_normalise_to_the_same_account(self):
        for k in (0, 1, 2, 41, 300):
            name = model.account_name(k)
            for u in (0.1, 0.3, 0.6, 0.9):
                self.assertEqual(model.norm_name(model.twin_name(name, u)), model.norm_name(name))

    def test_account_names_are_unique(self):
        names = [model.account_name(k) for k in range(len(model.STEMS) * len(model.SUFFIXES))]
        self.assertEqual(len(set(model.norm_name(n) for n in names)), len(names))


class TestSettings(unittest.TestCase):
    def test_defaults_and_clamping(self):
        s = model.normalise_settings({})
        self.assertEqual(s, model.DEFAULTS)
        s = model.normalise_settings({"deals": 99999, "zombies": 5, "blanks": -2, "seed": -3.9})
        self.assertEqual(s["deals"], 8000)
        self.assertEqual(s["zombies"], 0.8)
        self.assertEqual(s["blanks"], 0)
        self.assertEqual(s["seed"], 3)
        s = model.normalise_settings({"deals": "nonsense", "retrofill": None, "seed": float("nan")})
        self.assertEqual(s["deals"], 4000)
        self.assertEqual(s["retrofill"], model.DEFAULTS["retrofill"])
        self.assertEqual(s["seed"], model.DEFAULTS["seed"])
        s = model.normalise_settings({"deals": "", "blanks": "0x10", "zombies": " 0.5 ", "retrofill": True,
                                      "recreated": "1e-1", "placeholders": [0.2], "seed": "\u0661\u0662"})
        self.assertEqual((s["deals"], s["blanks"], s["zombies"]), (4000, model.DEFAULTS["blanks"], 0.5))
        self.assertEqual((s["retrofill"], s["recreated"]), (model.DEFAULTS["retrofill"], 0.1))
        self.assertEqual((s["placeholders"], s["seed"]), (model.DEFAULTS["placeholders"], model.DEFAULTS["seed"]))


class TestWorld(unittest.TestCase):
    def test_world_is_plausible(self):
        w = model.generate_world({"seed": 3, "deals": 8000})
        deals = w["deals"]
        self.assertEqual(len(deals), 8000)
        win_rate = mean([1 if d["won"] else 0 for d in deals])
        self.assertTrue(0.22 < win_rate < 0.36, win_rate)
        self.assertTrue(all(d["close"] - d["created"] > model.SCORE_DAY for d in deals))
        self.assertEqual([d["created"] for d in deals], sorted(d["created"] for d in deals))
        self.assertTrue(all(0 <= d["created"] < model.END_DAY for d in deals))

    def test_spotless_crm_matches_the_truth(self):
        crm = model.build_crm(model.generate_world(dict(model.PRESETS["clean"], seed=4)))
        for r in crm["history"] + crm["live"]:
            t = r["truth"]
            self.assertFalse(r["twin"] or r["zombie"] or r["editedAfterClose"])
            for f in model.FIELDS:
                self.assertEqual(r[f], t[f])
            self.assertEqual(r["amount"], t["amount"])

    def test_defect_rates_match_the_settings(self):
        s = {"seed": 8, "deals": 8000, "blanks": 0.4, "retrofill": 0.5, "zombies": 0.5, "recreated": 0.3,
             "placeholders": 0.5, "loggingShift": 0.4}
        crm = model.build_crm(model.generate_world(s))
        t = model.truth_counts(crm)
        self.assertAlmostEqual(t["editedShare"], 0.5, delta=0.04)
        self.assertAlmostEqual(t["zombieShare"], 0.5, delta=0.06)
        self.assertAlmostEqual(t["twinShare"], 0.3, delta=0.04)
        self.assertAlmostEqual(t["placeholderShare"], 0.5, delta=0.03)
        self.assertAlmostEqual(t["meetingsMissed"], 0.4, delta=0.03)
        live_blanks = mean([1 if r[f] is None else 0 for r in crm["live"] for f in model.FIELDS])
        self.assertAlmostEqual(live_blanks, 0.4, delta=0.02)
        # Retro-filling also fills some blanks, so the history looks a little more complete.
        a = model.audit_crm(crm)
        self.assertLess(a["rows"][0]["value"], live_blanks)

    def test_each_defect_only_moves_its_own_stream(self):
        base = model.build_crm(model.generate_world({"seed": 5}))
        other = model.build_crm(model.generate_world({"seed": 5, "zombies": 0}))
        by_id = {r["id"]: r for r in other["history"]}
        for r in base["history"]:
            if r["id"] in by_id:
                self.assertEqual(r["stakeholders"], by_id[r["id"]]["stakeholders"])
                self.assertEqual(r["placeholder"], by_id[r["id"]]["placeholder"])

    def test_retro_fills_only_touch_closed_deals(self):
        crm = model.build_crm(model.generate_world({"seed": 9, "retrofill": 0.8}))
        for r in crm["history"] + crm["live"]:
            if r["editedAfterClose"]:
                self.assertIn(r["status"], ("won", "lost"))
                if r["status"] == "won":
                    self.assertEqual(r["champion"], 1)
                    self.assertGreaterEqual(r["stakeholders"], 4)
        self.assertFalse(any(r["editedAfterClose"] for r in crm["live"]))

    def test_twins_are_closed_lost_copies_of_wins(self):
        crm = model.build_crm(model.generate_world({"seed": 2, "recreated": 0.5}))
        twins = [r for r in crm["history"] if r["twin"]]
        self.assertTrue(twins)
        for tw in twins:
            self.assertEqual(tw["status"], "lost")
            self.assertTrue(tw["truth"]["won"])
            self.assertEqual(tw["close"], tw["truth"]["created"])
            self.assertLessEqual(tw["created"], tw["close"])


class TestLab(unittest.TestCase):
    def test_clean_back_test_is_fair_on_average(self):
        gaps = [model.run_lab(dict(model.PRESETS["clean"], seed=s))["illusion"] for s in range(1, 9)]
        self.assertLess(abs(mean(gaps)), 0.03)

    def test_messy_crm_flatters_the_pilot(self):
        for s in range(1, 5):
            r = model.run_lab(dict(model.PRESETS["typical"], seed=s))
            self.assertGreater(r["illusion"], 0.08)
            self.assertGreater(r["debt"], 0.02)

    def test_retro_fill_inflates_the_champion_signal(self):
        a = model.run_lab({"seed": 6, "retrofill": 0, "blanks": 0, "zombies": 0, "recreated": 0, "placeholders": 0, "loggingShift": 0})
        b = model.run_lab({"seed": 6, "retrofill": 0.8, "blanks": 0, "zombies": 0, "recreated": 0, "placeholders": 0, "loggingShift": 0})
        self.assertGreater(b["model"]["dirty"][3], a["model"]["dirty"][3] + 0.5)
        self.assertGreater(b["backtest"]["auc"], a["backtest"]["auc"])
        self.assertLess(b["live"]["auc"], a["live"]["auc"])

    def test_zombies_inflate_predicted_win_rates(self):
        off = dict(model.PRESETS["clean"], seed=12)
        on = dict(off, zombies=0.8)
        a, b = model.run_lab(off), model.run_lab(on)
        self.assertGreater(b["live"]["meanPredicted"], a["live"]["meanPredicted"] + 0.04)

    def test_logging_shift_shows_in_the_audit(self):
        r = model.run_lab({"seed": 3, "loggingShift": 0.6})
        drift = [row for row in r["audit"]["rows"] if row["key"] == "loggingShift"][0]
        self.assertGreater(drift["value"], 0.5)
        self.assertEqual(drift["light"], "red")

    def test_evaluate_handles_one_class(self):
        ev = model.evaluate([0.2, 0.4], [0, 0], [1, 1], [1, 1])
        self.assertIsNone(ev["auc"])
        self.assertIsNone(ev["capture20"])
        self.assertIsNone(ev["forecastError"])

    def test_deciles_cover_every_deal(self):
        r = model.run_lab({"seed": 1, "deals": 1000})
        self.assertEqual(sum(d["n"] for d in r["live"]["deciles"]), r["live"]["n"])
        preds = [d["predicted"] for d in r["live"]["deciles"]]
        self.assertEqual(preds, sorted(preds))
        self.assertTrue(all(math.isfinite(x) for x in preds))


class TestRemedies(unittest.TestCase):
    def test_fixing_everything_reaches_the_clean_ceiling_exactly(self):
        r = model.run_lab({"seed": 21, "deals": 2000})
        self.assertEqual(len(r["fixes"]["rows"]), 6)
        self.assertEqual(len(r["fixes"]["path"]), 7)
        self.assertAlmostEqual(r["fixes"]["path"][-1]["liveAuc"], r["ceiling"]["auc"], places=12)
        self.assertAlmostEqual(r["fixes"]["path"][0]["liveAuc"], r["live"]["auc"], places=12)

    def test_fix_rows_are_ranked_and_skip_habits_already_at_zero(self):
        r = model.run_lab({"seed": 4, "deals": 2000, "zombies": 0, "recreated": 0})
        keys = [row["key"] for row in r["fixes"]["rows"]]
        self.assertNotIn("zombies", keys)
        self.assertNotIn("recreated", keys)
        gains = [row["gain"] for row in r["fixes"]["rows"]]
        self.assertEqual(gains, sorted(gains, reverse=True))
        clean = model.run_lab(dict(model.PRESETS["clean"], seed=4, deals=1000))
        self.assertEqual(clean["fixes"]["rows"], [])
        self.assertIsNone(model.run_lab({"seed": 4, "deals": 1000}, fixes=False)["fixes"])

    def test_retro_fills_drive_the_illusion(self):
        r = model.run_lab(dict(model.PRESETS["typical"], seed=5))
        top = max(r["fixes"]["rows"], key=lambda row: row["illusionDrop"])
        self.assertEqual(top["key"], "retrofill")
        self.assertGreater(top["illusionDrop"], 0.08)

    def test_repairs_make_the_back_test_honest_and_the_model_better(self):
        raw_gap, rep_gap, raw_live, rep_live = [], [], [], []
        for seed in range(1, 7):
            r = model.run_lab(dict(model.PRESETS["typical"], seed=seed), fixes=False)
            raw_gap.append(r["illusion"])
            rep_gap.append(r["repaired"]["backtest"]["auc"] - r["repaired"]["live"]["auc"])
            raw_live.append(r["live"]["auc"])
            rep_live.append(r["repaired"]["live"]["auc"])
        self.assertGreater(mean(raw_gap), 0.1)
        self.assertLess(abs(mean(rep_gap)), 0.05)
        self.assertGreater(mean(rep_live), mean(raw_live))

    def test_repair_steps_find_the_planted_problems(self):
        s = dict(model.PRESETS["clean"], seed=13, recreated=0.4, zombies=0.5, retrofill=0.5)
        crm = model.build_crm(model.generate_world(s))
        rep = model.repair_crm(crm, model.GO_LIVE)
        twins = sum(1 for r in crm["history"] if r["twin"])
        self.assertGreater(rep["steps"]["duplicates"], 0.8 * twins)
        self.assertLess(rep["steps"]["duplicates"], 1.3 * twins)
        kept_edited = sum(1 for r in rep["history"] if r["editedAfterClose"] and model.labelled(r))
        self.assertEqual(rep["steps"]["edited"], kept_edited)
        self.assertGreater(kept_edited, 0.9 * sum(1 for r in crm["history"] if r["editedAfterClose"]))
        for r in rep["history"]:
            if r["editedAfterClose"] and model.labelled(r):
                for f in model.EDITABLE:
                    self.assertIsNone(r[f])
        self.assertEqual(len(rep["history"]), len(crm["history"]) - rep["steps"]["duplicates"])
        zombies = sum(1 for r in crm["history"] if r["zombie"] and r["close"] < model.GO_LIVE - 30)
        self.assertEqual(rep["steps"]["zombies"], zombies)

    def test_repair_leaves_the_original_records_alone(self):
        crm = model.build_crm(model.generate_world({"seed": 3, "deals": 1000}))
        before = [dict(r) for r in crm["history"]]
        model.repair_crm(crm, model.GO_LIVE)
        self.assertEqual(before, crm["history"])

    def test_blank_account_names_are_never_duplicates(self):
        base = {"twin": False, "editedAfterClose": False, "seg": 0, "src": 0, "amount": 12000, "stakeholders": None,
                "meetings": None, "champion": None, "competitor": None, "discount": None, "daysToFirst": None}
        h = [dict(base, id=i, account="  ", created=i, close=i + 30, status="won" if i % 2 else "lost") for i in range(6)]
        crm = {"history": h, "live": []}
        dup = [r for r in model.audit_crm(crm)["rows"] if r["key"] == "recreated"][0]
        self.assertEqual(dup["value"], 0)
        self.assertEqual(model.repair_crm(crm, 100)["steps"]["duplicates"], 0)

    def test_truth_reports_blanks_at_entry(self):
        r = model.run_lab({"seed": 3, "blanks": 0.4, "retrofill": 0.8})
        self.assertAlmostEqual(r["truth"]["blanksAtEntry"], 0.4, delta=0.03)
        self.assertEqual(r["model"]["features"][0], "Intercept")
        self.assertEqual(len(r["model"]["features"]), len(r["model"]["dirty"]))

    def test_median_and_round_amounts(self):
        self.assertEqual(model.median([5, 1, 3]), 3)
        self.assertEqual(model.median([4, 1, 3, 2]), 3)
        self.assertTrue(model.is_round(50000))
        self.assertFalse(model.is_round(50100))

class TestRobustness(unittest.TestCase):
    def test_summary_and_counts(self):
        rb = model.robustness(dict(model.PRESETS["typical"], deals=1000, seed=40), 3)
        self.assertEqual([w["seed"] for w in rb["worlds"]], [41, 42, 43])
        lives = [w["live"] for w in rb["worlds"]]
        self.assertAlmostEqual(rb["summary"]["live"]["mean"], sum(lives) / 3)
        self.assertEqual(rb["summary"]["live"]["low"], min(lives))
        self.assertEqual(rb["overpromised"], sum(1 for w in rb["worlds"] if w["illusion"] > 0.05))
        self.assertEqual(len(model.robustness({"seed": 1, "deals": 1000}, 0)["worlds"]), 12)
        self.assertEqual(len(model.robustness({"seed": 4294967295, "deals": 1000}, 1)["worlds"]), 1)
        self.assertEqual(model.robustness({"seed": 4294967295, "deals": 1000}, 1)["worlds"][0]["seed"], 0)

    def test_summarise_ignores_missing_values(self):
        sm = model.summarise([0.3, None, 0.1, float("nan"), 0.2])
        self.assertEqual((sm["n"], sm["low"], sm["high"], sm["median"]), (3, 0.1, 0.3, 0.2))
        self.assertIsNone(model.summarise([])["mean"])

    def test_sweep_levels_and_means(self):
        from fittotrain import batch
        res = batch.sweep({"seed": 2, "deals": 1000}, "retrofill", levels=3, n_worlds=2)
        self.assertEqual(res["levels"], [0.0, 0.4, 0.8])
        self.assertEqual(len(res["rows"]), 6)
        self.assertLess(res["means"][0]["illusion"], res["means"][-1]["illusion"])
        with self.assertRaises(ValueError):
            batch.sweep({}, "nonsense")

if __name__ == "__main__":
    unittest.main()
