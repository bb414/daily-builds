"""Drives the browser app in headless Chromium. Skipped if Playwright for Python is not installed."""

import unittest
from pathlib import Path

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover - depends on the machine
    sync_playwright = None

APP = (Path(__file__).resolve().parent.parent / "app" / "index.html").as_uri()
DONE = "document.getElementById('status-text').textContent.indexOf('Based on') === 0"


@unittest.skipUnless(sync_playwright, "Playwright for Python is not installed")
class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # pragma: no cover - no browser available
            cls.pw.stop()
            raise unittest.SkipTest(f"No Chromium available: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280, height=900, url=APP):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        self.problems = []
        page.on("console", lambda m: self.problems.append(m.text) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: self.problems.append(str(e)))
        page.on("request", lambda r: self.problems.append("network: " + r.url)
                if not r.url.startswith(("file:", "data:", "blob:")) else None)
        page.goto(url)
        page.wait_for_function(DONE, timeout=30000)
        return page

    def wait_for_new_result(self, page):
        page.wait_for_function("document.getElementById('status-text').textContent.indexOf('Based on') !== 0", timeout=5000)
        page.wait_for_function(DONE, timeout=30000)

    def test_opens_with_the_default_answer(self):
        page = self.open()
        tiles = page.inner_text("#tiles")
        self.assertIn("1.5%", tiles)
        self.assertIn("Fair share: 3.3%", tiles)
        self.assertIn("better than 91% of the field", page.inner_text("#insight"))
        self.assertIn("72.0%", page.inner_text("#winner-bars"))
        self.assertEqual(page.locator("#sample-table tbody tr").count(), 10)
        self.assertEqual(self.problems, [])

    def test_changing_the_rule_reruns_the_simulation(self):
        page = self.open()
        page.check("input[name=rule][value=sharpe]", force=True)
        self.wait_for_new_result(page)
        self.assertIn("extra risk buys nothing", page.inner_text("#insight"))
        page.check("input[name=rule][value=drawdown]", force=True)
        self.assertTrue(page.is_visible("#s-drawdownLimit"))
        self.wait_for_new_result(page)
        self.assertIn("knocked out", page.inner_text("#risk-note"))
        self.assertEqual(self.problems, [])

    def test_sliders_work_from_the_keyboard(self):
        page = self.open()
        page.focus("#s-yourVol")
        for _ in range(10):
            page.keyboard.press("ArrowRight")
        self.assertEqual(page.get_attribute("#s-yourVol", "aria-valuetext"), "30%")
        self.wait_for_new_result(page)
        self.assertIn("You: 30%", page.inner_text("#risk-chart"))

    def test_presets_new_luck_and_sample_navigation(self):
        page = self.open()
        page.select_option("#preset", label="A society league of eight")
        self.wait_for_new_result(page)
        self.assertEqual(page.input_value("#s-teams"), "8")
        self.assertIn("Out of 8 teams", page.inner_text("#tiles"))
        before = page.inner_text("#sample-table")
        page.click("#next-sample")
        expect(page.locator("#sample-title")).to_contain_text("number 2 of")
        self.assertNotEqual(page.inner_text("#sample-table"), before)
        page.click("#new-luck")
        self.wait_for_new_result(page)
        self.assertIn("luck number 2", page.inner_text("#status-text"))
        self.assertEqual(self.problems, [])

    def test_clicking_the_risk_curve_sets_the_risk(self):
        page = self.open()
        page.locator("#risk-chart svg").scroll_into_view_if_needed()
        box = page.locator("#risk-chart svg").bounding_box()
        page.mouse.click(box["x"] + box["width"] - 20, box["y"] + box["height"] / 2)
        self.assertEqual(page.get_attribute("#s-yourVol", "aria-valuetext"), "100%")

    def test_skill_card_and_settings_link(self):
        page = self.open()
        page.wait_for_function("document.getElementById('skill-note').textContent.length > 0", timeout=30000)
        self.assertEqual(page.locator("#skill-table tbody tr").count(), 7)
        self.assertIn("four-week challenges", page.inner_text("#skill-note"))
        page.select_option("#preset", label="Knocked out at a 10% drawdown")
        self.wait_for_new_result(page)
        url = page.url
        self.assertIn("rule=drawdown", url)
        self.assertIn("drawdownLimit=0.1", url)
        other = self.open(url=url)
        self.assertTrue(other.is_checked("input[name=rule][value=drawdown]"))
        self.assertEqual(other.input_value("#s-drawdownLimit"), "0.1")
        other.close()
        self.assertEqual(self.problems, [])

    def test_sortino_and_return_over_drawdown_rules(self):
        page = self.open()
        page.check("input[name=rule][value=sortino]", force=True)
        self.wait_for_new_result(page)
        self.assertIn("Ranked on Sortino ratio, extra risk buys nothing", page.inner_text("#insight"))
        page.check("input[name=rule][value=calmar]", force=True)
        self.wait_for_new_result(page)
        self.assertIn("Highest return over worst drawdown", page.inner_text("#risk-rule"))
        self.assertIn("rule=calmar", page.url)
        page.wait_for_function("document.getElementById('skill-note').textContent.indexOf('return over worst drawdown') >= 0",
                               timeout=60000)
        self.assertEqual(page.locator("#skill-table thead th").count(), 6)
        self.assertEqual(self.problems, [])

    def test_volatility_cap_preset(self):
        page = self.open()
        page.select_option("#preset", label="Volatility capped at 30%")
        self.wait_for_new_result(page)
        self.assertIn("the most the cap allows", page.inner_text("#insight"))
        self.assertTrue(page.is_checked("#leverage-cap"))
        self.assertEqual(page.input_value("#s-volCap"), "0.3")
        self.assertIn("Above the 30% cap", page.inner_text("#risk-chart"))
        self.assertIn("leverageCap=1", page.url)
        self.assertIn("41.2%", page.inner_text("#winner-bars"))
        self.assertEqual(self.problems, [])

    def test_wording_follows_the_numbers(self):
        page = self.open(url=APP + "#rule=drawdown&drawdownLimit=0.1")
        self.assertIn("knock your team out of 63% of challenges", page.inner_text("#insight"))
        page.close()
        page = self.open(url=APP + "#rule=sharpe&catchUp=1")
        self.assertNotIn("same at any volatility", page.inner_text("#insight"))
        self.assertIn("Less risk would help", page.inner_text("#insight"))
        page.close()
        page = self.open(url=APP + "#days=250&teams=8")
        insight = page.inner_text("#insight")
        self.assertIn("year-long challenges, against a fair share of 12.5%", insight)
        self.assertIn("Trading days: about a year.", page.inner_text("#rules-form"))
        page.close()
        self.assertEqual(self.problems, [])

    def test_checks_a_real_leaderboard(self):
        page = self.open()
        page.click("#check-example-year")
        expect(page.locator("#check-verdict")).to_contain_text("Possibly some skill")
        self.assertEqual(page.locator("#check-table tbody tr").count(), 30)
        self.assertEqual(page.input_value("#check-days"), "250")
        self.assertIn("65%", page.inner_text("#check-tiles"))
        page.select_option("#check-team", label="2nd Team Fir")
        expect(page.locator("#check-team-note")).to_contain_text("Team Fir finished 2nd of 30")
        self.assertEqual(page.locator("#check-table tr.picked").count(), 1)
        # Changing the length reruns the check: a year's gains made in four weeks would be no luck.
        page.fill("#check-days", "20")
        page.dispatch_event("#check-days", "change")
        expect(page.locator("#check-verdict")).to_contain_text("Real skill shows")
        # A table with too few teams is explained rather than checked.
        page.fill("#check-text", "Team,Return\nA,1%\nB,2%\n")
        page.click("#check-run")
        expect(page.locator("#check-status")).to_contain_text("At least three teams")
        self.assertTrue(page.locator("#check-results").is_hidden())
        # A team that lost everything is left out and named, and nothing about true skill is shown.
        rows = "".join(f"T{i},{r}%,20%\n" for i, r in enumerate((4, 2, 1, -1, -3, -5)))
        page.fill("#check-text", "Team,Return,Volatility\n" + rows + "Bust,-100%,80%\n")
        page.click("#check-run")
        expect(page.locator("#check-warning")).to_contain_text("Bust lost everything, so it was left out")
        expect(page.locator("#check-verdict")).to_contain_text("Luck alone could easily have produced this table")
        self.assertTrue(page.locator("#check-truth-key").is_hidden())
        self.assertTrue(page.locator("#check-team-note").is_hidden())
        self.assertEqual(self.problems, [])

    def test_opens_a_csv_file(self):
        page = self.open(390, 844)
        page.set_input_files("#check-file", str(Path(__file__).resolve().parent.parent / "examples" / "four-week-challenge.csv"))
        expect(page.locator("#check-verdict")).to_contain_text("Luck alone could easily have produced this table")
        self.assertIn("Team Cedar", page.input_value("#check-text"))
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        self.assertLessEqual(page.evaluate("document.querySelector('#check-table').scrollWidth"),
                             page.evaluate("document.querySelector('#check-table').parentElement.clientWidth"))
        self.assertEqual(self.problems, [])

    def test_fits_a_phone(self):
        page = self.open(390, 844)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        self.assertEqual(self.problems, [])

    def test_keeps_its_dark_theme_whatever_the_system_theme(self):
        def theme(scheme):
            page = self.browser.new_page(viewport={"width": 1280, "height": 900}, color_scheme=scheme)
            page.goto(APP)
            page.wait_for_function(DONE, timeout=30000)
            rgb = page.evaluate("getComputedStyle(document.body).backgroundColor")
            declared = page.evaluate("getComputedStyle(document.documentElement).colorScheme")
            page.close()
            return sum(int(v) for v in rgb[rgb.index("(") + 1:rgb.index(")")].split(",")[:3]), declared
        for scheme in ("light", "dark"):
            background, declared = theme(scheme)
            self.assertLess(background, 150)
            self.assertEqual(declared, "dark")


if __name__ == "__main__":
    unittest.main()
