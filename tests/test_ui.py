"""Browser tests: open the app in headless Chromium and use it like a person would."""

import time
import unittest

from helpers import APP

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

URL = APP.as_uri()


@unittest.skipIf(sync_playwright is None, "Playwright for Python is not installed")
class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as e:  # pragma: no cover
            cls.pw.stop()
            raise unittest.SkipTest("Chromium is not available: %s" % e)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280):
        page = self.browser.new_page(viewport={"width": width, "height": 900})
        self.errors, self.requests = [], []
        page.on("console", lambda m: self.errors.append(m.text) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", lambda r: self.requests.append(r.url) if not r.url.startswith(("file:", "data:")) else None)
        page.goto(URL)
        page.wait_for_selector("#summary .tile")
        return page

    def tearDown(self):
        self.assertEqual(self.errors, [], "console errors")
        self.assertEqual(self.requests, [], "network requests")

    def test_loads_with_the_first_example(self):
        page = self.open()
        self.assertIn("£143k", page.inner_text("#summary"))
        self.assertEqual(page.locator("#risk .risk-row").count(), 5)
        self.assertGreater(page.locator("#frontier svg circle").count(), 5)
        self.assertEqual(page.title(), "Assurance mix")
        page.close()

    def test_every_control_has_a_label(self):
        page = self.open()
        unlabelled = page.evaluate("""() => Array.from(document.querySelectorAll('input, select, button, [role=tab]')).filter(el => {
            if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return false;
            if (el.id && document.querySelector('label[for="' + el.id + '"]')) return false;
            if (el.closest('label')) return false;
            return !(el.textContent || '').trim();
        }).map(el => el.outerHTML.slice(0, 80))""")
        self.assertEqual(unlabelled, [])
        page.close()

    def test_changing_the_example_and_limits(self):
        page = self.open()
        page.select_option("#example", "policy")
        self.assertIn("£6k", page.inner_text("#summary"))
        page.select_option("#q-stage", "scale")
        self.assertEqual(page.input_value("#example"), "custom")
        page.click("#appetite-presets button[data-v='4']")
        self.assertEqual(page.input_value("#appetite"), "4")
        page.fill("#budget", "10")
        page.wait_for_timeout(300)
        self.assertIn("£10k or less", page.inner_text("#summary"))
        page.close()

    def test_unreachable_appetite_and_short_deadline(self):
        page = self.open()
        page.fill("#appetite", "1")
        page.wait_for_timeout(300)
        self.assertIn("Out of reach", page.inner_text("#summary"))
        page.fill("#weeks", "1")
        page.wait_for_timeout(300)
        self.assertIn("No plan fits", page.inner_text("#summary"))
        self.assertIn("No plan fits in 1 week", page.inner_text("#notes"))
        page.close()

    def test_tabs_and_custom_plan(self):
        page = self.open()
        page.click("#tab-custom")
        self.assertEqual(page.get_attribute("#tab-custom", "aria-selected"), "true")
        self.assertTrue(page.is_visible("#custom-list"))
        page.click("#custom-clear")
        # DPIA is required, so it stays ticked and disabled
        self.assertTrue(page.is_checked("#custom-list input[data-t='dpia']"))
        self.assertTrue(page.is_disabled("#custom-list input[data-t='dpia']"))
        page.check("#custom-list input[data-t='conformity']")
        self.assertTrue(page.is_checked("#custom-list input[data-t='docs']"))
        self.assertIn("needs model and data documentation", page.inner_text("#view-note"))
        # keyboard: arrow keys move between tabs
        page.focus("#tab-custom")
        page.keyboard.press("ArrowLeft")
        self.assertEqual(page.get_attribute("#tab-budget", "aria-selected"), "true")
        page.close()

    def test_must_and_rule_out(self):
        page = self.open()
        page.check("input[name='c-biasIndependent'][value='exclude']", force=True)
        self.assertNotIn("Independent bias audit", page.inner_text("#plan-table"))
        page.check("input[name='c-redteam'][value='must']", force=True)
        self.assertIn("Independent red teaming", page.inner_text("#plan-table"))
        page.close()

    def test_phone_width_has_no_sideways_scroll(self):
        page = self.open(390)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        page.close()

    def test_extreme_settings_stay_responsive(self):
        page = self.open()
        page.select_option("#example", "grant")
        page.evaluate("""() => { for (const r of document.querySelectorAll("#catalogue input[value='must']:not(:disabled)")) { r.checked = true; r.dispatchEvent(new Event('change', {bubbles: true})); } }""")
        t = time.time()
        page.fill("#budget", "5000")
        page.fill("#weeks", "104")
        page.fill("#appetite", "0.5")
        page.wait_for_timeout(300)
        self.assertLess(time.time() - t, 3)
        self.assertIn("Out of reach", page.inner_text("#summary"))
        page.close()


if __name__ == "__main__":
    unittest.main()
