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
        self.errors = []
        self.requests = []
        page.on("console", lambda m: m.type == "error" and self.errors.append(m.text))
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", lambda r: self.requests.append(r.url))
        page.goto(APP_URL)
        return page

    def take_test(self, page, key="1"):
        page.click("#start-btn")
        for _ in range(3):
            page.wait_for_selector("#screen-break:not([hidden])")
            page.click("#break-go")
            page.wait_for_selector("#screen-trial:not([hidden])")
            while page.is_visible("#screen-trial"):
                page.wait_for_timeout(260)
                page.keyboard.press(key)
                if page.is_visible("#checker-block"):
                    page.wait_for_timeout(360)
                    page.keyboard.press(key)
                if page.is_visible("#screen-break") or page.is_visible("#screen-results"):
                    break

    def test_full_run_by_keyboard(self):
        page = self.open()
        self.take_test(page, "1")
        page.wait_for_selector("#screen-results:not([hidden])")
        self.assertIn("Your results", page.inner_text("#results-title"))
        # Always answering "definitely a scam" gets exactly the scams right.
        tiles = page.locator(".tile-value").all_inner_texts()
        self.assertEqual([t.split()[0] for t in tiles], ["4", "6", "4"])
        self.assertEqual(page.locator(".review details").count(), 28)
        self.assertEqual(self.errors, [])
        self.assertTrue(all(u.startswith("file:") or u.startswith("blob:") or u.startswith("data:")
                            for u in self.requests), self.requests)
        page.close()

    def test_checker_panel_shows_verdict_and_reasons(self):
        page = self.open()
        page.click("#start-btn")
        page.click("#break-go")
        for _ in range(8):
            page.wait_for_timeout(260)
            page.keyboard.press("3")
        page.click("#break-go")
        page.wait_for_timeout(260)
        page.keyboard.press("2")
        page.wait_for_selector("#checker-block:not([hidden])")
        text = page.inner_text("#checker-panel")
        self.assertRegex(text, r"Likely (a scam|genuine)")
        self.assertRegex(text, r"\d+% sure")
        self.assertGreaterEqual(page.locator("#checker-panel li").count(), 1)
        self.assertTrue(page.locator("#answers-first .answer.chosen").count() == 1)
        self.assertEqual(self.errors, [])
        page.close()

    def test_demo_results_render_on_a_phone(self):
        page = self.open(390, 844)
        page.select_option("#demo-persona", "leaner")
        page.click("#demo-btn")
        page.wait_for_selector("#screen-results:not([hidden])")
        self.assertIn("Example", page.inner_text("#results"))
        width = page.evaluate("document.documentElement.scrollWidth")
        self.assertLessEqual(width, 390)
        self.assertEqual(self.errors, [])
        page.close()

    def test_every_control_has_a_name(self):
        page = self.open()
        unnamed = page.evaluate("""() => [...document.querySelectorAll('button, select, input')]
            .filter(el => el.offsetParent !== null)
            .filter(el => {
              const label = el.labels && el.labels.length ? el.labels[0].textContent : '';
              return !(el.getAttribute('aria-label') || el.textContent.trim() || label.trim());
            }).map(el => el.outerHTML)""")
        self.assertEqual(unnamed, [])
        page.close()


if __name__ == "__main__":
    unittest.main()
