"""Drives the browser app in headless Chromium. Skipped if Playwright for Python is not installed."""

import unittest
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - depends on the machine
    sync_playwright = None

APP = (Path(__file__).resolve().parent.parent / "app" / "index.html").as_uri()


@unittest.skipIf(sync_playwright is None, "Playwright for Python is not installed")
class UiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as err:  # pragma: no cover - depends on the machine
            cls.pw.stop()
            raise unittest.SkipTest("Chromium for Playwright is not installed: %s" % err)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, url=APP, width=1280, height=900):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        self.errors, self.requests = [], []
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", lambda r: self.requests.append(r.url))
        page.goto(url)
        page.wait_for_selector("#headline h2", timeout=30000)
        return page

    def settle(self, page):
        """Waits until the app has re-rendered after the last change."""
        before = page.get_attribute("body", "data-runs")
        try:
            page.wait_for_function("b => document.body.getAttribute('data-runs') !== b", arg=before, timeout=3000)
        except Exception:  # nothing was pending
            pass
        page.wait_for_timeout(100)

    def test_loads_without_errors_or_network(self):
        page = self.open()
        self.assertIn("One per team", page.inner_text("#headline"))
        self.assertEqual(len(page.query_selector_all("#kpis .kpi")), 4)
        self.assertEqual(len(page.query_selector_all("#compare tbody tr")), 5)
        self.assertGreater(len(page.query_selector_all("#net circle")), 100)
        self.assertEqual(self.errors, [])
        self.assertEqual([u for u in self.requests if not u.startswith(("file:", "data:", "about:"))], [])
        page.close()

    def test_strategy_and_week_controls(self):
        page = self.open()
        page.check("input[name=strategy][value=spread]")
        self.settle(page)
        self.assertIn("best strategy here", page.inner_text("#headline h2"))
        self.assertEqual(page.input_value("#preset"), "custom")
        page.fill("#week", "0")
        page.dispatch_event("#week", "input")
        self.assertEqual(page.inner_text("#week-out"), "0")
        self.assertIn("Week 0: 8 of 180", page.inner_text("#net-note"))
        page.click("#play")
        page.wait_for_timeout(500)
        self.assertNotEqual(page.inner_text("#week-out"), "0")
        page.click("#play")
        self.assertEqual(self.errors, [])
        page.close()

    def test_preset_and_slider(self):
        page = self.open()
        page.select_option("#preset", "plugin")
        self.settle(page)
        self.assertEqual(page.inner_text("#o-socialProof"), "0%")
        self.assertIn("It is close", page.inner_text("#headline"))
        page.fill("#p-people", "60")
        page.dispatch_event("#p-people", "input")
        self.settle(page)
        self.assertIn("of 60 people", page.inner_text("#net-note"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_what_if_sweep(self):
        page = self.open()
        page.click("summary:has-text('Simulation')")
        page.fill("#p-runs", "10")
        page.dispatch_event("#p-runs", "input")
        self.settle(page)
        page.select_option("#sweep-key", "champions")
        page.click("#sweep-run")
        page.wait_for_function("document.getElementById('sweep-summary').textContent.includes('wins')", timeout=60000)
        self.assertEqual(len(page.query_selector_all("#sweep-chart polyline")), 5)
        self.assertIn("Number of champions", page.inner_text("#sweep-summary"))
        page.fill("#p-lapse", "0.2")
        page.dispatch_event("#p-lapse", "input")
        self.settle(page)
        self.assertIn("Settings changed", page.inner_text("#sweep-summary"))
        self.assertEqual(len(page.query_selector_all("#sweep-chart polyline")), 0)
        self.assertEqual(self.errors, [])
        page.close()

    def test_every_control_has_an_accessible_name(self):
        page = self.open()
        unnamed = page.evaluate("""() => Array.from(document.querySelectorAll('input, select, button'))
            .filter(e => !(e.labels && e.labels.length) && !e.getAttribute('aria-label') && !e.closest('label')
                && !(e.tagName === 'BUTTON' && e.textContent.trim()))
            .map(e => e.id || e.name || e.outerHTML.slice(0, 60))""")
        self.assertEqual(unnamed, [])
        page.close()

    def test_fits_a_phone_screen(self):
        page = self.open(width=390, height=844)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        self.assertEqual(self.errors, [])
        page.close()


if __name__ == "__main__":
    unittest.main()
