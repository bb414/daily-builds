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
VERDICT_LABELS = {"Baseline: no AI", "Helper", "Crutch", "No lift", "Liability"}


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

    def open(self, width=1280, height=900):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        self.errors, self.requests = [], []
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", lambda r: self.requests.append(r.url))
        page.goto(APP)
        page.wait_for_selector("#verdict h2")
        return page

    def settle(self, page):
        """Waits until the app has finished re-running after the last change."""
        before = page.get_attribute("body", "data-runs")
        try:
            page.wait_for_function("b => document.body.getAttribute('data-runs') !== b", arg=before, timeout=600)
        except Exception:  # nothing was pending: the run had already finished
            pass
        page.wait_for_timeout(200)

    def test_loads_without_errors_or_network(self):
        page = self.open()
        self.assertIn(page.inner_text("#verdict h2"), VERDICT_LABELS)
        self.assertEqual(len(page.query_selector_all("#kpis .kpi")), 6)
        self.assertGreater(len(page.query_selector_all("#chart-time polyline")), 1)
        self.assertEqual(self.errors, [])
        external = [u for u in self.requests if not u.startswith(("file:", "data:", "about:"))]
        self.assertEqual(external, [])
        page.close()

    def test_switching_workflow_updates_results(self):
        page = self.open()
        page.check("input[name=workflow][value=ai_first]")
        self.settle(page)
        self.assertEqual(page.inner_text("#verdict h2"), "Crutch")
        page.check("input[name=workflow][value=human_first]")
        self.settle(page)
        self.assertEqual(page.inner_text("#verdict h2"), "Helper")
        self.assertEqual(page.input_value("#preset"), "custom")
        page.check("input[name=workflow][value=none]")
        self.settle(page)
        self.assertEqual(page.inner_text("#verdict h2"), "Baseline: no AI")
        self.assertEqual(self.errors, [])
        page.close()

    def test_preset_and_slider_update_outputs(self):
        page = self.open()
        page.select_option("#preset", "invoice_fraud")
        self.settle(page)
        self.assertEqual(page.input_value("#p-humanAccuracy"), "0.8")
        self.assertEqual(page.inner_text("#o-humanAccuracy"), "80%")
        self.assertTrue(page.is_checked("input[name=workflow][value=human_first]"))
        page.fill("#p-aiAccuracy", "0.6")
        page.dispatch_event("#p-aiAccuracy", "input")
        self.settle(page)
        self.assertEqual(page.inner_text("#o-aiAccuracy"), "60%")
        self.assertEqual(page.input_value("#preset"), "custom")
        self.assertEqual(self.errors, [])
        page.close()

    def test_robustness_check_renders(self):
        page = self.open()
        page.click("#robust-run")
        page.wait_for_selector("#robust-chart .tornado-row", timeout=20000)
        self.assertEqual(len(page.query_selector_all("#robust-chart .tornado-row")), 10)
        self.assertIn("held in", page.inner_text("#robust-summary"))
        page.select_option("#robust-measure", "lift")
        self.assertEqual(len(page.query_selector_all("#robust-chart .tornado-row")), 10)
        page.fill("#p-aiAccuracy", "0.7")
        page.dispatch_event("#p-aiAccuracy", "input")
        self.settle(page)
        self.assertIn("Settings changed", page.inner_text("#robust-summary"))
        self.assertEqual(len(page.query_selector_all("#robust-chart .tornado-row")), 0)
        self.assertEqual(self.errors, [])
        page.close()

    def test_link_restores_settings(self):
        page = self.open()
        page.select_option("#preset", "lead_triage")
        self.settle(page)
        page.fill("#p-driftAt", "100")
        page.dispatch_event("#p-driftAt", "input")
        self.settle(page)
        url = page.url
        self.assertIn("driftAt=100", url)
        other = self.browser.new_page()
        other.goto(url)
        other.wait_for_selector("#verdict h2")
        self.assertEqual(other.input_value("#p-driftAt"), "100")
        self.assertTrue(other.is_checked("input[name=workflow][value=on_request]"))
        self.assertEqual(other.inner_text("#o-driftAt"), "Case 100")
        self.assertFalse(other.is_hidden("#shock-note"))
        other.close()
        page.close()

    def test_download_and_load_settings(self):
        page = self.open()
        page.select_option("#preset", "invoice_fraud")
        self.settle(page)
        with page.expect_download() as info:
            page.click("#download")
        path = info.value.path()
        with open(path, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(saved["app"], "reliance-lab")
        self.assertEqual(saved["params"]["workflow"], "human_first")
        page.select_option("#preset", "scam_teens")
        self.settle(page)
        page.set_input_files("#upload", path)
        self.settle(page)
        self.assertEqual(page.input_value("#preset"), "invoice_fraud")
        self.assertIn("Loaded", page.inner_text("#save-status"))
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{broken")
        try:
            page.set_input_files("#upload", fh.name)
            self.settle(page)
        finally:
            os.unlink(fh.name)
        self.assertIn("not valid JSON", page.inner_text("#save-status"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_audit_regressions(self):
        page = self.open()
        # Choosing "Custom" updates the help text.
        page.select_option("#preset", "custom")
        self.assertEqual(page.inner_text("#preset-help"), "Your own settings.")
        # Sliders announce their formatted value.
        self.assertEqual(page.get_attribute("#p-driftAt", "aria-valuetext"), "Never")
        # Switching workflow from the comparison table keeps keyboard focus on that row.
        page.click("#compare button[data-workflow=human_first]")
        self.settle(page)
        self.assertEqual(page.evaluate("document.activeElement.getAttribute('data-workflow')"), "human_first")
        # The AI cannot get better in the stress test.
        page.fill("#p-aiAccuracy", "0.7")
        page.dispatch_event("#p-aiAccuracy", "input")
        page.fill("#p-driftAccuracy", "0.95")
        page.dispatch_event("#p-driftAccuracy", "input")
        self.settle(page)
        self.assertEqual(page.inner_text("#o-driftAccuracy"), "70%")
        # Focus is only restored if it was still in the table.
        page.click("#compare button[data-workflow=on_request]")
        page.focus("#p-humanAccuracy")
        self.settle(page)
        self.assertEqual(page.evaluate("document.activeElement.id"), "p-humanAccuracy")
        # A link pasted into the same tab is applied.
        page.evaluate("location.hash = 'rounds=125&workflow=none&people=75'")
        self.settle(page)
        self.assertEqual(page.inner_text("#o-rounds"), "125")
        self.assertEqual(page.get_attribute("#p-rounds", "step"), "any")
        self.assertEqual(page.inner_text("#verdict h2"), "Baseline: no AI")
        # Moving that slider returns it to normal steps.
        page.focus("#p-rounds")
        page.keyboard.press("ArrowRight")
        self.settle(page)
        self.assertEqual(page.get_attribute("#p-rounds", "step"), "10")
        self.assertEqual(int(page.inner_text("#o-rounds")) % 10, 0)
        self.assertIn("rounds=" + page.inner_text("#o-rounds"), page.url)
        self.assertEqual(self.errors, [])
        page.close()

    def test_stays_responsive_at_extreme_settings(self):
        import time
        page = self.browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(APP + "#people=1000&rounds=500&driftAt=250&workflow=ai_first")
        page.wait_for_selector("#verdict h2", timeout=30000)
        page.click("#robust-run")
        page.wait_for_function("document.getElementById('robust-summary').textContent.includes('done')", timeout=30000)
        start = time.time()
        page.evaluate("1 + 1")
        self.assertLess(time.time() - start, 1.5, "the page should answer while the check runs")
        page.wait_for_selector("#robust-chart .tornado-row", timeout=120000)
        self.assertEqual(errors, [])
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
        width = page.evaluate("document.documentElement.scrollWidth")
        self.assertLessEqual(width, 390)
        self.assertEqual(self.errors, [])
        page.close()


if __name__ == "__main__":
    unittest.main()
