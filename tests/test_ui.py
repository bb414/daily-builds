"""Drives the browser app in headless Chromium (skipped if Playwright is not installed)."""

import unittest
from pathlib import Path

from saveorsink import model as M

ROOT = Path(__file__).resolve().parents[1]
APP_URL = (ROOT / "app" / "index.html").as_uri()

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@unittest.skipUnless(sync_playwright, "Playwright for Python is not installed")
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # pragma: no cover
            cls.pw.stop()
            raise unittest.SkipTest("Chromium is not available: %s" % exc)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280, height=900):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        self.errors, self.requests = [], []
        page.on("console", lambda m: m.type == "error" and self.errors.append(m.text))
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", lambda r: self.requests.append(r.url))
        page.goto(APP_URL)
        page.wait_for_selector("#table-card table")
        return page

    def settle(self, page):
        page.wait_for_timeout(400)

    def test_loads_with_results_and_no_requests(self):
        page = self.open()
        self.assertIn("The verdict", page.inner_text("#verdict-card"))
        self.assertEqual(page.locator("#table-card tbody tr").count(), len(M.RULES))
        self.assertTrue(page.locator("#year-card path.bal").count() == 1)
        self.assertEqual(self.errors, [])
        self.assertTrue(all(u.startswith(("file:", "data:", "blob:")) for u in self.requests), self.requests)
        page.close()

    def test_changing_a_setting_updates_the_results(self):
        page = self.open()
        before = page.inner_text("#table-card tbody")
        page.select_option("#c-rescue", "never")
        self.settle(page)
        after = page.inner_text("#table-card tbody")
        self.assertNotEqual(before, after)
        page.locator("#c-rent").fill("900")
        self.settle(page)
        self.assertIn("£900", page.inner_text("#c-rent-out"))
        self.assertNotEqual(after, page.inner_text("#table-card tbody"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_presets_and_the_year_view(self):
        page = self.open()
        page.select_option("#preset", "tight")
        self.settle(page)
        self.assertEqual(page.input_value("#c-loanPerTerm"), "3600")
        page.click("[data-view='weekly']")
        self.assertEqual(page.get_attribute("[data-view='weekly']", "aria-pressed"), "true")
        first = page.inner_text("#year-card .facts")
        page.click("#next-year")
        self.assertIn("Year 2 of", page.inner_text("#year-desc"))
        self.assertNotEqual(first, page.inner_text("#year-card .facts"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_phone_layout_fits(self):
        page = self.open(390, 844)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        self.assertLess(page.locator(".results").bounding_box()["y"], page.locator(".settings").bounding_box()["y"])
        page.close()

    def test_every_control_has_a_name(self):
        page = self.open()
        unnamed = page.evaluate("""() => [...document.querySelectorAll('button, select, input')]
            .filter(el => {
              const label = el.labels && el.labels.length ? el.labels[0].textContent : '';
              return !(el.getAttribute('aria-label') || el.textContent.trim() || label.trim());
            }).map(el => el.outerHTML)""")
        self.assertEqual(unnamed, [])
        page.close()


if __name__ == "__main__":
    unittest.main()
