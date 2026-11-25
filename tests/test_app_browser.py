"""Drives the browser app in headless Chromium.

Skipped when Playwright for Python (or its browser) is not available.
"""

import json
import pathlib
import tempfile
import unittest
import urllib.parse

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

    def test_background_analyses_finish(self):
        page = self.open()
        page.wait_for_selector("#tornado .wf-row", timeout=30000)
        page.wait_for_selector("#options .wf-row", timeout=30000)
        self.assertIn("different runs of luck", page.inner_text("#robust"))
        self.assertIn("People cut at", page.inner_text("#bank"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_save_then_open_restores_the_setup(self):
        page = self.open()
        page.fill("#ai-check", "12")
        with page.expect_download() as dl:
            page.click("#save")
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "setup.json"
            dl.value.save_as(str(path))
            saved = json.loads(path.read_text())
            self.assertEqual(saved["config"]["ai"]["checkMinutes"], 12)
            page.select_option("#preset", "complaints")
            page.wait_for_function("document.querySelector('#ai-check').value === '4'")
            page.set_input_files("#file", str(path))
            page.wait_for_function("document.querySelector('#ai-check').value === '12'")
        self.assertIn("Opened", page.inner_text("#tool-status"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_link_restores_the_setup(self):
        cfg = {"name": "Linked", "arrivalsPerDay": 25, "steps": [
            {"name": "Desk A", "kind": "team", "staff": 2, "minutes": 20, "cv": 0.5},
            {"name": "Desk B", "kind": "team", "staff": 2, "minutes": 25, "cv": 0.5}],
            "ai": {"step": 1, "saving": 0.3, "adoption": 0.6, "checkMinutes": 2}}
        page = self.browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(APP.as_uri() + "#setup=" + urllib.parse.quote(json.dumps({"seed": 77, "config": cfg})))
        page.wait_for_selector(".wf-row.total")
        self.assertEqual(page.input_value("#seed"), "77")
        self.assertEqual(page.input_value("#arrivals"), "25")
        self.assertIn("Desk B", page.inner_text("#results"))
        page.close()

    def test_every_control_has_a_label(self):
        page = self.open()
        page.click("#steps-edit summary")
        page.wait_for_selector("#s0-name")
        missing = page.evaluate("""() => Array.from(document.querySelectorAll('input, select, button')).filter(el => {
            if (el.type === 'file' || el.getAttribute('aria-hidden') === 'true') return false;
            if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return false;
            if (el.tagName === 'BUTTON') return !el.textContent.trim();
            if (el.closest('label')) return false;
            return !(el.id && document.querySelector('label[for="' + el.id + '"]'));
        }).map(el => el.id || el.outerHTML.slice(0, 60))""")
        self.assertEqual(missing, [])
        page.close()

    def test_extreme_settings_stay_responsive(self):
        page = self.open()
        page.select_option("#preset", "complaints")
        page.wait_for_function("document.querySelector('#results').innerText.includes('Team leader sign-off')")
        page.fill("#arrivals", "200")
        page.wait_for_selector(".wf-row.total", timeout=20000)
        page.wait_for_function("!document.querySelector('#results').classList.contains('busy')", timeout=20000)
        # The page still reacts to input while the extra checks run or wait.
        page.fill("#arrivals", "30")
        page.wait_for_function("document.querySelector('#results').innerText.includes('sign-off')", timeout=20000)
        self.assertEqual(self.errors, [])
        page.close()

    def test_phone_width_has_no_sideways_scroll(self):
        page = self.open(390)
        width = page.evaluate("document.documentElement.scrollWidth")
        self.assertLessEqual(width, 390)
        page.close()


if __name__ == "__main__":
    unittest.main()
