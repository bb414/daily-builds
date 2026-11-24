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
        self.assertIn("£540.02", page.inner_text("#compare"))
        self.assertIn("10% off today", page.inner_text("#lead"))
        self.assertEqual(page.locator("#map rect").count(), 7 * 30)
        self.assertEqual(self.errors, [])
        self.assertTrue(all(u.startswith("file://") for u in self.requests), self.requests)
        page.close()

    def test_changing_inputs_updates_results(self):
        page = self.open()
        page.select_option("#preset", "mochi")
        self.assertIn("£220.04", page.inner_text("#compare"))
        page.fill("#f-stock", "10")
        page.dispatch_event("#f-stock", "change")
        self.assertNotIn("£220.04", page.inner_text("#compare"))
        page.select_option("#rule-pct", "50")
        page.select_option("#rule-days", "1")
        self.assertIn("50% off with 1 day left", page.inner_text("#compare"))
        page.check("#f-rises")
        page.dispatch_event("#f-rises", "change")
        self.assertIn("chance of selling out", page.inner_text("#leftover-note"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_card_robustness_and_saved_address(self):
        page = self.open()
        self.assertIn("52+", page.inner_text("#card"))
        self.assertIn("exactly what the full plan earns", page.inner_text("#card-note"))
        self.assertEqual(page.locator("#robust td").count(), 15)
        self.assertIn("93%*", page.inner_text("#robust"))
        self.assertIn("marked *", page.inner_text("#robust-note"))
        page.select_option("#preset", "tins")
        url = page.url
        self.assertIn("stock=120", url)
        other = self.browser.new_page()
        other.goto(url)
        self.assertEqual(other.input_value("#f-stock"), "120")
        self.assertEqual(other.input_value("#preset"), "")
        self.assertEqual(other.inner_text("#compare"), page.inner_text("#compare"))
        other.close()
        with page.expect_download() as dl:
            page.click("#card-download")
        self.assertTrue(dl.value.suggested_filename.endswith(".csv"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_out_of_range_values_are_explained(self):
        page = self.open()
        page.fill("#f-stock", "5000")
        page.dispatch_event("#f-stock", "change")
        self.assertIn("Using 300", page.inner_text("#h-stock"))
        page.fill("#f-stock", "")
        page.dispatch_event("#f-stock", "change")
        self.assertIn("Using 60", page.inner_text("#h-stock"))
        page.fill("#f-stock", "45")
        page.dispatch_event("#f-stock", "change")
        self.assertEqual(page.inner_text("#h-stock"), "How many you have to sell.")
        self.assertEqual(self.errors, [])
        page.close()

    def test_every_control_has_a_label(self):
        page = self.open()
        unlabelled = page.evaluate("""() => Array.from(document.querySelectorAll('input, select, button')).filter(e =>
            !((e.labels && e.labels.length && e.labels[0].textContent.trim()) || e.getAttribute('aria-label') ||
              (e.tagName === 'BUTTON' && e.textContent.trim()))).map(e => e.id)""")
        self.assertEqual(unlabelled, [])
        page.close()

    def test_phone_width_has_no_horizontal_scroll(self):
        page = self.open(390, 844)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        page.close()


if __name__ == "__main__":
    unittest.main()
