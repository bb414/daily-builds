"""Drives the browser app in headless Chromium (skipped if Playwright is not installed)."""

import unittest
from pathlib import Path

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
        page.wait_for_selector("#summary .range")
        return page

    def settle(self, page):
        page.wait_for_timeout(450)

    def test_loads_with_results_and_no_requests(self):
        page = self.open()
        text = page.inner_text("#summary")
        self.assertIn("most likely between", text)
        self.assertIn("chance of clearing", text)
        self.assertEqual(page.locator("#dist-card rect.bar").count() > 10, True)
        self.assertEqual(page.locator("#tornado-card rect.bar").count(), 6)
        self.assertEqual(self.errors, [])
        self.assertTrue(all(u.startswith(("file:", "data:", "blob:")) for u in self.requests), self.requests)
        page.close()

    def test_switching_templates(self):
        page = self.open()
        page.select_option("#template", "ai-assistant")
        self.settle(page)
        self.assertEqual(page.input_value("#f-title"), "An AI assistant for a support team")
        self.assertIn("Net value per year", page.inner_text("#summary"))
        self.assertEqual(page.locator(".term").count(), 3)
        self.assertEqual(page.locator(".term.minus").count(), 2)
        page.close()

    def test_editing_a_range_updates_the_results(self):
        page = self.open()
        before = page.inner_text("#summary .range")
        page.fill(".driver[data-t='0'][data-d='2'] [data-f='high']", "60")
        self.settle(page)
        self.assertNotEqual(page.inner_text("#summary .range"), before)
        self.assertEqual(self.errors, [])
        page.close()

    def test_invalid_input_explains_the_problem(self):
        page = self.open()
        page.fill(".driver[data-t='0'][data-d='0'] [data-f='low']", "40000")
        self.settle(page)
        self.assertTrue(page.is_visible("#problems"))
        self.assertIn("low value must be below the high value", page.inner_text("#problems"))
        self.assertEqual(page.get_attribute(".driver[data-t='0'][data-d='0'] [data-f='low']", "aria-invalid"), "true")
        page.fill(".driver[data-t='0'][data-d='0'] [data-f='low']", "20000")
        self.settle(page)
        self.assertTrue(page.is_hidden("#problems"))
        self.assertIsNone(page.get_attribute(".driver[data-t='0'][data-d='0'] [data-f='low']", "aria-invalid"))
        page.close()

    def test_adding_and_removing_drivers_and_terms(self):
        page = self.open()
        page.click("#add-term")
        self.assertEqual(page.locator(".term").count(), 2)
        self.settle(page)
        self.assertIn("needs a name", page.inner_text("#problems"))
        page.fill(".driver[data-t='1'][data-d='0'] [data-f='name']", "Gift boxes")
        page.select_option("#t1sign", "-1")
        self.settle(page)
        self.assertTrue(page.is_hidden("#problems"))
        self.assertEqual(page.locator(".term.minus").count(), 1)
        page.click(".term[data-t='1'] [data-act='del-driver']")
        self.settle(page)
        self.assertIn("needs at least one driver", page.inner_text("#problems"))
        page.click(".term[data-t='1'] [data-act='del-term']")
        self.settle(page)
        self.assertTrue(page.is_hidden("#problems"))
        page.select_option(".driver[data-t='0'][data-d='5'] [data-f='dist']", "fixed")
        self.settle(page)
        self.assertTrue(page.is_disabled(".driver[data-t='0'][data-d='5'] [data-f='high']"))
        self.assertEqual(page.locator("#tornado-card rect.bar").count(), 5)
        self.assertEqual(self.errors, [])
        page.close()

    def test_what_to_check_first(self):
        page = self.open()
        text = page.inner_text("#voi-card")
        self.assertIn("What to check before deciding", text)
        self.assertIn("go ahead", text)
        self.assertIn("Share who would try a meal kit", page.inner_text("#voi-card tbody tr:first-child"))
        page.fill("#f-threshold", "")
        self.settle(page)
        self.assertIn("Add a threshold", page.inner_text("#voi-card"))
        self.assertNotIn("chance of clearing", page.inner_text("#summary"))
        page.fill("#f-threshold", "5")
        self.settle(page)
        self.assertIn("nothing worth checking first", page.inner_text("#voi-card"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_phone_layout_fits(self):
        page = self.open(390, 844)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        box_results = page.locator(".results").bounding_box()
        box_editor = page.locator(".editor").bounding_box()
        self.assertLess(box_results["y"], box_editor["y"])  # results come first on a phone
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
