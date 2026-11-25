"""Drives the browser app in headless Chromium. Skipped if Playwright is not installed."""

import os
import unittest

import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from cleanhours import jobs_csv, model  # noqa: E402

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

    def test_weather_years_and_one_run(self):
        page = self.open()
        page.wait_for_selector("#yearsChart svg")
        self.assertEqual(page.locator("#yearsTable tbody tr").count(), 5)
        self.assertIn("of 10", page.inner_text("#yearsTable"))
        self.assertEqual(page.locator("#runTable tbody tr").count(), 6)
        page.select_option("#runJob", "0")
        self.assertIn("no slack", page.inner_text("#runHint"))
        page.wait_for_selector("#curveWind svg")
        self.assertEqual(self.problems, [])

    def test_save_and_load(self):
        page = self.open()
        with page.expect_download() as dl:
            page.click("#saveCsv")
        path = dl.value.path()
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(jobs_csv.parse_jobs(text), model.DEFAULT_JOBS)
        page.set_input_files("#loadCsv", files=[{"name": "two.csv", "mimeType": "text/csv", "buffer": (
            "name,mw,hours,every_days,first_day,release_hour,window,pausable\n"
            "A,4,6,7,0,9,48,yes\nB,1,2,1,0,20,10,no\n").encode()}])
        page.wait_for_function("document.querySelectorAll('.job').length === 2")
        self.assertIn("Loaded 2 jobs", page.inner_text("#fileMsg"))
        page.set_input_files("#loadCsv", files=[{"name": "bad.csv", "mimeType": "text/csv", "buffer": b"name,mw\nA,4\n"}])
        page.wait_for_function("document.getElementById('fileMsg').innerText.includes('Missing column')")
        with page.expect_download() as dl:
            page.click("#saveSettings")
        with open(dl.value.path(), encoding="utf-8") as fh:
            settings = fh.read()
        page.check("input[name=preset][value=coal]")
        page.set_input_files("#loadSettings", files=[{"name": "s.json", "mimeType": "application/json", "buffer": settings.encode()}])
        page.wait_for_function("document.getElementById('fileMsg').innerText.includes('Loaded settings')")
        self.assertTrue(page.is_checked("input[name=preset][value=windy]"))
        self.assertEqual(page.locator(".job").count(), 2)
        self.assertEqual(self.problems, [])

    def test_invalid_jobs_do_not_break_other_controls(self):
        # Regression: with a job removed and another invalid, moving the week or
        # changing the highlighted scheduler used to read jobs that no longer existed.
        page = self.open()
        page.click("button[data-remove='5']")
        page.locator(".job[data-i='1'] input[data-k='window']").fill("1")
        page.wait_for_selector("#errors.show")
        page.fill("#week", "30")
        page.select_option("#focus", "spare")
        page.select_option("#runJob", "4")
        self.assertEqual(self.problems, [])
        self.assertIn("stale", page.get_attribute("#results", "class"))

    def test_bad_settings_files_are_refused(self):
        page = self.open()
        cases = [
            ("not json", "not valid JSON"),
            ('{"app": "other"}', "not a Clean hours settings file"),
            ('{"app": "clean-hours", "slack": 1.1}', "multiple of 0.25"),
            ('{"app": "clean-hours", "preset": "toString"}', "unknown grid"),
            ('{"app": "clean-hours", "jobs": [null]}', "not a job"),
        ]
        for text, expect in cases:
            page.set_input_files("#loadSettings", files=[{"name": "s.json", "mimeType": "application/json", "buffer": text.encode()}])
            page.wait_for_function("t => document.getElementById('fileMsg').innerText.includes(t)", arg=expect)
        self.assertEqual(self.problems, [])

    def test_fits_a_phone_screen(self):
        page = self.open(390, 844)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)

    def test_extreme_settings_stay_responsive(self):
        page = self.open()
        for sel, value in [("#windScale", "3"), ("#solarScale", "3"), ("#slack", "3"), ("#forecastError", "3")]:
            page.fill(sel, value)
        page.wait_for_function("document.querySelector('#slackOut').textContent.startsWith('3')")
        # The heaviest legal job: 336 hours in one block, every day, with a four-week window.
        page.locator(".job[data-i='0'] input[data-k='window']").fill("672")
        page.locator(".job[data-i='0'] input[data-k='hours']").fill("336")
        start = page.evaluate("performance.now()")
        page.wait_for_function("document.getElementById('verdict').innerText.length > 0 && !document.getElementById('errors').classList.contains('show')")
        page.wait_for_timeout(300)
        elapsed = page.evaluate("performance.now()") - start
        self.assertLess(elapsed, 8000)
        self.assertEqual(page.locator("#tiles .tile").count(), 4)
        self.assertEqual(self.problems, [])


if __name__ == "__main__":
    unittest.main()
