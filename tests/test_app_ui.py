"""Drives the browser app in headless Chromium with Playwright.

Skipped if Playwright for Python or a Chromium browser is not available
(pip install -r requirements-dev.txt, then python -m playwright install chromium).
"""

import os
import pathlib
import tempfile
import unittest

from helpers import APP

from stairstep import model, report

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

URL = pathlib.Path(APP).as_uri()


@unittest.skipUnless(sync_playwright, "Playwright for Python is not installed")
class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # pragma: no cover
            cls.pw.stop()
            raise unittest.SkipTest("No Chromium browser available: %s" % exc)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280, height=900):
        context = self.browser.new_context(viewport={"width": width, "height": height}, accept_downloads=True)
        self.addCleanup(context.close)
        page = context.new_page()
        self.problems = []
        page.on("console", lambda m: m.type == "error" and self.problems.append("console: " + m.text))
        page.on("pageerror", lambda e: self.problems.append("page error: %s" % e))
        page.on("request", lambda r: r.url.startswith(("file:", "data:", "blob:")) or self.problems.append("network: " + r.url))
        page.goto(URL)
        page.wait_for_selector(".stairs")
        return page

    def unlabelled(self, page):
        return page.evaluate("""() => [...document.querySelectorAll('button, input, select, a[href]')].filter((el) => {
            const name = (el.getAttribute('aria-label') || '') + (el.labels && el.labels.length ? el.labels[0].textContent : '') + el.textContent;
            return !name.trim();
          }).map((el) => el.outerHTML.slice(0, 80))""")

    def test_loads_and_matches_the_python_numbers(self):
        page = self.open()
        r = model.run({})["results"]
        self.assertIn(report.headline(r), page.locator(".headline").inner_text())
        values = page.locator(".step-value").all_inner_texts()
        self.assertEqual(values, [report.pct1(m["wape"]) for m in r["methods"]])
        self.assertIn("Worth using on %d of 12 products" % r["deployOn"], page.locator("main").inner_text())
        self.assertEqual(page.locator("#sku-title ~ .scroll tbody tr").count(), 12)
        self.assertEqual(self.unlabelled(page), [])
        with tempfile.TemporaryDirectory() as d:
            with page.expect_download() as info:
                page.get_by_role("button", name="Download forecasts (CSV)").click()
            app_csv = os.path.join(d, "app.csv")
            info.value.save_as(app_csv)
            run = model.run({})
            py_csv = os.path.join(d, "py.csv")
            report.forecasts_csv(run["data"], run["forecasts"], py_csv)
            with open(app_csv, encoding="utf-8") as a, open(py_csv, encoding="utf-8") as b:
                self.assertEqual(a.read(), b.read(), "the app's CSV should match the Python export exactly")
            with page.expect_download() as info:
                page.get_by_role("button", name="Download results (JSON)").click()
            self.assertTrue(info.value.suggested_filename.endswith(".json"))
        self.assertEqual(self.problems, [])

    def test_settings_change_the_answer(self):
        page = self.open()
        before = page.locator(".headline").inner_text()
        page.locator("#in-holidays").focus()
        page.keyboard.press("Home")
        page.locator("#in-promoLift").focus()
        page.keyboard.press("Home")
        page.wait_for_function("document.getElementById('status').textContent.startsWith('Updated')")
        page.wait_for_timeout(300)
        self.assertEqual(page.locator("#out-holidays").inner_text(), "0%")
        self.assertNotEqual(page.locator(".headline").inner_text(), before)
        expected = model.run({"holidays": 0, "promoLift": 0})["results"]
        self.assertIn(report.headline(expected), page.locator(".headline").inner_text())
        page.get_by_role("button", name="Reset all settings").click()
        page.wait_for_timeout(400)
        self.assertEqual(page.locator(".headline").inner_text(), before)
        page.fill("#in-seed", "42")
        page.wait_for_timeout(400)
        self.assertIn(report.headline(model.run({"seed": 42})["results"]), page.locator(".headline").inner_text())
        self.assertEqual(self.problems, [])

    def test_explorer(self):
        page = self.open()
        page.select_option("#ex-sku", label="Gummy bears")
        page.select_option("#ex-store", label="Orchard")
        page.locator("input[data-method=naive]").check()
        summary = page.locator("#ex-summary").inner_text()
        self.assertIn("Naive error", summary)
        self.assertEqual(page.locator("#ex-chart path[stroke='var(--c-naive)']").count(), 1)
        page.locator("input[data-method=ai]").uncheck()
        self.assertNotIn("AI model error", page.locator("#ex-summary").inner_text())
        self.assertEqual(self.problems, [])

    def test_phone_layout(self):
        page = self.open(390, 844)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        self.assertEqual(self.problems, [])


if __name__ == "__main__":
    unittest.main()
