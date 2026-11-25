"""Drives the browser app in headless Chromium. Skipped if Playwright is not installed."""

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = "file://" + os.path.join(ROOT, "app", "index.html")

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

UNLABELLED_JS = """
() => Array.from(document.querySelectorAll('input, select, textarea, button')).filter(el => {
  if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return false;
  if (el.tagName === 'BUTTON') return !el.textContent.trim();
  if (el.id && document.querySelector('label[for="' + el.id + '"]')) return false;
  return !el.closest('label');
}).map(el => el.outerHTML.slice(0, 80))
"""


@unittest.skipUnless(sync_playwright, "Playwright is not installed")
class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as e:  # pragma: no cover
            cls.pw.stop()
            raise unittest.SkipTest("no headless browser: %s" % e)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280, height=900):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        self.problems, self.requests = [], []
        page.on("console", lambda m: self.problems.append(m.text) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: self.problems.append(str(e)))
        page.on("request", lambda r: self.requests.append(r.url) if not r.url.startswith(("file:", "data:")) else None)
        page.goto(APP)
        page.wait_for_selector("#tiles .tile")
        return page

    def test_loads_cleanly_offline(self):
        page = self.open()
        self.assertEqual(page.title(), "Clean hours")
        self.assertEqual(page.locator("#tiles .tile").count(), 4)
        self.assertIn("does more good than the report shows", page.inner_text("#verdict"))
        self.assertEqual(self.problems, [])
        self.assertEqual(self.requests, [])

    def test_every_control_is_labelled(self):
        page = self.open()
        self.assertEqual(page.evaluate(UNLABELLED_JS), [])

    def test_switching_grid_changes_the_story(self):
        page = self.open()
        page.check("input[name=preset][value=coal]")
        page.wait_for_function("document.getElementById('verdict').innerText.includes('raises real emissions')")
        page.check("input[name=preset][value=sunny]")
        page.wait_for_function("document.getElementById('verdict').innerText.includes('overstates its benefit')")
        self.assertEqual(self.problems, [])

    def test_invalid_job_shows_an_error_and_recovers(self):
        page = self.open()
        field = page.locator(".job[data-i='1'] input[data-k='window']")
        field.fill("2")
        page.wait_for_selector("#errors.show")
        self.assertIn("window", page.inner_text("#errors"))
        field.fill("14")
        page.wait_for_selector("#errors:not(.show)", state="attached")
        self.assertEqual(self.problems, [])

    def test_fits_a_phone_screen(self):
        page = self.open(390, 844)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)

    def test_extreme_settings_stay_responsive(self):
        page = self.open()
        for sel, value in [("#windScale", "3"), ("#solarScale", "3"), ("#slack", "3"), ("#forecastError", "3")]:
            page.fill(sel, value)
        page.wait_for_timeout(400)
        self.assertEqual(page.locator("#tiles .tile").count(), 4)
        self.assertEqual(self.problems, [])


if __name__ == "__main__":
    unittest.main()
