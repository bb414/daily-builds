"""Drive the browser app in headless Chromium. Skipped without Playwright for Python."""

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_URL = (ROOT / "app" / "index.html").as_uri()

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@unittest.skipUnless(sync_playwright, "Playwright for Python is not installed")
class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # pragma: no cover
            cls.pw.stop()
            raise unittest.SkipTest("No browser available for Playwright: %s" % exc)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280, height=900):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        self.errors, self.requests = [], []
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", lambda r: self.requests.append(r.url))
        page.goto(APP_URL)
        return page

    def test_default_product_shows_the_plan(self):
        page = self.open()
        self.assertIn("£570.90", page.inner_text("#compare"))
        self.assertIn("10% off today", page.inner_text("#lead"))
        self.assertEqual(page.locator("#map rect").count(), 7 * 30)
        self.assertEqual(self.errors, [])
        self.assertTrue(all(u.startswith("file://") for u in self.requests), self.requests)
        page.close()

    def test_changing_inputs_updates_results(self):
        page = self.open()
        page.select_option("#preset", "mochi")
        self.assertIn("£236.03", page.inner_text("#compare"))
        page.fill("#f-stock", "10")
        page.dispatch_event("#f-stock", "change")
        self.assertNotIn("£236.03", page.inner_text("#compare"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_every_control_has_a_label(self):
        page = self.open()
        unlabelled = page.evaluate("""() => Array.from(document.querySelectorAll('input, select, button')).filter(e =>
            !((e.labels && e.labels.length && e.labels[0].textContent.trim()) || e.getAttribute('aria-label'))).map(e => e.id)""")
        self.assertEqual(unlabelled, [])
        page.close()

    def test_phone_width_has_no_horizontal_scroll(self):
        page = self.open(390, 844)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        page.close()


if __name__ == "__main__":
    unittest.main()
