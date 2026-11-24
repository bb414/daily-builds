"""Drives the browser app in headless Chromium. Skipped if Playwright for Python is not installed."""

import json
import os
import tempfile
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

    def test_picking_champions(self):
        page = self.open()
        self.assertTrue(page.is_disabled("input[name=strategy][value=custom]"))
        page.check("#pick-mode")
        page.click("#net circle[data-i='0']")
        self.settle(page)
        self.assertEqual(page.input_value("#picks"), "1")
        self.assertTrue(page.is_checked("input[name=strategy][value=custom]"))
        self.assertIn("Your picks", page.inner_text("#compare"))
        page.fill("#picks", "1, 19, 999, abc")
        page.dispatch_event("#picks", "change")
        self.settle(page)
        self.assertIn("Ignored 999, abc", page.inner_text("#picks-status"))
        self.assertEqual(page.input_value("#picks"), "1, 19")
        page.click("#picks-clear")
        self.settle(page)
        self.assertNotIn("Your picks", page.inner_text("#compare"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_other_organisations(self):
        page = self.open()
        page.click("#robust-run")
        page.wait_for_function("document.getElementById('robust-summary').textContent.includes('was best in')", timeout=60000)
        self.assertEqual(len(page.query_selector_all("#robust-table tbody tr")), 5)
        page.fill("#p-lapse", "0.2")
        page.dispatch_event("#p-lapse", "input")
        self.settle(page)
        self.assertIn("Settings changed", page.inner_text("#robust-summary"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_link_and_file_restore_settings(self):
        page = self.open()
        page.select_option("#preset", "silos")
        self.settle(page)
        page.fill("#picks", "3, 30")
        page.dispatch_event("#picks", "change")
        self.settle(page)
        self.assertIn("custom=2,29", page.url)
        other = self.open(page.url)
        self.assertEqual(other.input_value("#preset"), "custom")
        self.assertEqual(other.input_value("#picks"), "3, 30")
        self.assertEqual(other.inner_text("#o-tiesOrg"), "0.1")
        other.evaluate("location.hash = 'people=60&teams=5&strategy=spread'")
        self.settle(other)
        self.assertIn("of 60 people", other.inner_text("#net-note"))
        other.close()
        with page.expect_download() as info:
            page.click("#download")
        with open(info.value.path(), encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(saved["params"]["custom"], [2, 29])
        page.select_option("#preset", "plugin")
        self.settle(page)
        page.set_input_files("#upload", info.value.path())
        self.settle(page)
        self.assertEqual(page.input_value("#picks"), "3, 30")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{broken")
        try:
            page.set_input_files("#upload", fh.name)
            page.wait_for_timeout(300)
        finally:
            os.unlink(fh.name)
        self.assertIn("not valid JSON", page.inner_text("#save-status"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_audit_regressions(self):
        page = self.open(APP + "#departments=2&teams=30&people=300&runs=10")
        box = page.evaluate("(() => { const r = document.getElementById('net').getBoundingClientRect(); return [r.width, r.height]; })()")
        self.assertLessEqual(box[1], 561, "the network drawing is capped in height")
        circles = page.evaluate("""() => Array.from(document.querySelectorAll('#net circle'))
            .filter(c => !c.hasAttribute('data-i')).map(c => [+c.getAttribute('cx'), +c.getAttribute('cy'), +c.getAttribute('r')])""")
        overlaps = [(a, b) for i, a in enumerate(circles) for b in circles[i + 1:]
                    if ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 < a[2] + b[2] - 0.5]
        self.assertEqual(overlaps, [], "team outlines never overlap")
        page.close()
        for url in (APP, APP + "#people=300&teams=2&departments=1&runs=10", APP + "#people=40&teams=13&departments=6&runs=10"):
            page = self.open(url)
            dots = page.evaluate("""() => Array.from(document.querySelectorAll('#net circle[data-i]'))
                .map(c => [+c.getAttribute('cx'), +c.getAttribute('cy'), +c.getAttribute('r')])""")
            touching = sum(1 for i, a in enumerate(dots) for b in dots[i + 1:]
                           if ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 < a[2] + b[2])
            self.assertEqual(touching, 0, "people never overlap: " + url)
            page.close()
        page = self.open()
        # Sliders show the value the model actually uses.
        page.fill("#p-teams", "30")
        page.dispatch_event("#p-teams", "input")
        self.assertEqual(page.input_value("#p-teams"), "30")
        page.fill("#p-people", "40")
        page.dispatch_event("#p-people", "input")
        self.settle(page)
        self.assertEqual(page.input_value("#p-teams"), "30")
        self.assertEqual(page.inner_text("#o-teams"), "13 (limited)")
        self.assertIn("of 13", page.inner_text("#kpis"))
        # Moving back up restores the earlier setting: nothing is thrown away on the way.
        page.fill("#p-people", "180")
        page.dispatch_event("#p-people", "input")
        self.settle(page)
        self.assertEqual(page.inner_text("#o-teams"), "30")
        # Fewer champions than picks: the picks are kept, only the first ones are used, and it says so.
        page.fill("#picks", "1, 2, 3, 4, 5, 6")
        page.dispatch_event("#picks", "change")
        self.settle(page)
        self.assertEqual(page.inner_text("#picks-status"), "6 of 8 champions picked.")
        page.fill("#p-champions", "3")
        page.dispatch_event("#p-champions", "input")
        self.settle(page)
        self.assertEqual(page.input_value("#picks"), "1, 2, 3, 4, 5, 6")
        self.assertIn("6 picked, but only 3 can be used", page.inner_text("#picks-status"))
        self.assertIn("custom=0,1,2&", page.url + "&")
        page.fill("#p-champions", "8")
        page.dispatch_event("#p-champions", "input")
        self.settle(page)
        self.assertEqual(page.inner_text("#picks-status"), "6 of 8 champions picked.")
        self.assertEqual(self.errors, [])
        page.close()

    def test_stays_responsive_at_extreme_settings(self):
        import time
        page = self.open(APP + "#people=300&runs=100&weeks=104&teams=30&departments=6")
        page.click("#sweep-run")
        page.wait_for_function("document.getElementById('sweep-summary').textContent.includes('1 of')", timeout=60000)
        start = time.time()
        page.evaluate("1 + 1")
        self.assertLess(time.time() - start, 1.0, "the page answers while the what-if runs")
        page.select_option("#preset", "plugin")
        self.settle(page)
        self.assertIn("Settings changed", page.inner_text("#sweep-summary"))
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
