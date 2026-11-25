"""Drives the browser app in headless Chromium.

Skipped when Playwright for Python (or its browser) is not available.
"""

import os
import pathlib
import unittest

APP = pathlib.Path(__file__).resolve().parent.parent / "app" / "index.html"

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@unittest.skipUnless(sync_playwright, "Playwright for Python is not installed")
class BrowserApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # pragma: no cover
            cls.pw.stop()
            raise unittest.SkipTest("No headless browser: %s" % exc)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280):
        page = self.browser.new_page(viewport={"width": width, "height": 900})
        self.errors, self.requests = [], []
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", lambda r: None if r.url.startswith(("file:", "data:", "blob:")) else self.requests.append(r.url))
        page.goto(APP.as_uri())
        page.wait_for_selector(".wf-row.total")
        return page

    def test_loads_without_errors_or_network(self):
        page = self.open()
        self.assertIn("Where the minutes went", page.inner_text("#results"))
        self.assertEqual(self.errors, [])
        self.assertEqual(self.requests, [])
        page.close()

    def test_switching_preset_and_moving_a_slider_updates_results(self):
        page = self.open()
        page.select_option("#preset", "loans")
        page.wait_for_function("document.querySelector('#results').innerText.includes('Credit committee')")
        before = page.inner_text(".wf-row.total")
        page.fill("#ai-check", "40")
        page.wait_for_function("t => document.querySelector('.wf-row.total').innerText !== t", arg=before)
        self.assertEqual(self.errors, [])
        page.close()

    def test_invalid_input_shows_a_message(self):
        page = self.open()
        page.fill("#arrivals", "0")
        page.wait_for_selector(".errors")
        self.assertIn("Cases per day", page.inner_text(".errors"))
        page.fill("#arrivals", "40")
        page.wait_for_selector(".wf-row.total")
        page.close()

    def test_phone_width_has_no_sideways_scroll(self):
        page = self.open(390)
        width = page.evaluate("document.documentElement.scrollWidth")
        self.assertLessEqual(width, 390)
        page.close()


if __name__ == "__main__":
    unittest.main()
