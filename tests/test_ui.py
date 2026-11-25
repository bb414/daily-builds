"""Drives the browser app in headless Chromium: no errors, no network, the
main interactions work, every control has a name, and nothing is wider than
a phone screen. Skipped when Playwright is not installed."""

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "file://" + os.path.join(ROOT, "app", "index.html")

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

UNNAMED_CONTROLS = """
() => Array.from(document.querySelectorAll('input, select, button, textarea')).filter(e => {
  if (e.closest('[hidden]')) return false;
  const label = e.labels && e.labels.length ? e.labels[0].textContent.trim() : '';
  return !(label || e.getAttribute('aria-label') || (e.tagName === 'BUTTON' && e.textContent.trim()));
}).map(e => e.outerHTML.slice(0, 80))
"""


@unittest.skipIf(sync_playwright is None, "Playwright for Python is not installed")
class UiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280):
        page = self.browser.new_page(viewport={"width": width, "height": 900})
        self.errors = []
        self.requests = []
        page.on("console", lambda m: self.errors.append(m.text) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", lambda r: self.requests.append(r.url) if not r.url.startswith("file:") else None)
        page.goto(URL)
        page.wait_for_selector("#plans .plan")
        return page

    def tearDown(self):
        self.assertEqual(self.errors, [], "console errors")
        self.assertEqual(self.requests, [], "network requests")

    def test_route_flips_the_decision(self):
        page = self.open()
        self.assertIn("Not shortlisted", page.inner_text("#decision"))
        page.click("#plans .plan button")
        self.assertIn("Shortlisted", page.inner_text("#decision"))
        self.assertNotIn("Not shortlisted", page.inner_text("#decision"))
        self.assertIn("nothing to change", page.inner_text("#plans"))
        page.close()

    def test_presets_and_inputs(self):
        page = self.open()
        self.assertEqual(page.locator("#preset option").count(), 8)
        page.select_option("#preset", label="No route within a year")
        self.assertIn("No route within these limits", page.inner_text("#plans"))
        page.select_option("#preset", label="Near miss")
        page.fill("#f-test", "95")
        page.press("#f-test", "Enter")
        page.locator("#f-test").blur()
        self.assertIn("Shortlisted", page.inner_text("#decision"))
        self.assertEqual(page.input_value("#preset"), "")
        page.fill("#f-test", "-40")
        page.locator("#f-test").blur()
        self.assertEqual(page.input_value("#f-test"), "0")
        page.close()

    def test_rules_change_the_routes(self):
        page = self.open()
        before = page.inner_text("#plans")
        page.uncheck("#act-0")
        after = page.inner_text("#plans")
        self.assertNotEqual(before, after)
        self.assertNotIn("Test score:", after)
        page.close()

    def test_tabs_and_keyboard(self):
        page = self.open()
        page.focus("#tab-applicant")
        page.keyboard.press("ArrowRight")
        self.assertEqual(page.get_attribute("#tab-cohort", "aria-selected"), "true")
        self.assertFalse(page.is_hidden("#panel-cohort"))
        self.assertTrue(page.is_hidden("#panel-applicant"))
        self.assertEqual(page.locator("#kpis .kpi").count(), 4)
        self.assertEqual(page.locator("#hist svg rect").count(), 14)
        page.keyboard.press("End")
        self.assertFalse(page.is_hidden("#panel-about"))
        page.close()

    def test_every_control_has_a_name(self):
        page = self.open()
        for tab in ("#tab-applicant", "#tab-cohort", "#tab-about"):
            page.click(tab)
            self.assertEqual(page.evaluate(UNNAMED_CONTROLS), [], tab)
        page.close()

    def test_phone_width_has_no_sideways_scroll(self):
        page = self.open(390)
        for tab in ("#tab-applicant", "#tab-cohort", "#tab-about"):
            page.click(tab)
            page.wait_for_timeout(50)
            width = page.evaluate("document.documentElement.scrollWidth")
            self.assertLessEqual(width, 390, tab)
        page.close()


if __name__ == "__main__":
    unittest.main()
