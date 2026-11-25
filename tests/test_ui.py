"""Drives the browser app in headless Chromium. Skipped if Playwright is missing."""

import unittest
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

APP = (Path(__file__).resolve().parent.parent / "app" / "index.html").as_uri()


@unittest.skipIf(sync_playwright is None, "Playwright for Python is not installed")
class TestUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280, height=900, hash_=""):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        self.errors, self.requests = [], []
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", lambda r: self.requests.append(r.url) if not r.url.startswith(("file:", "data:")) else None)
        page.goto(APP + hash_)
        page.wait_for_function("document.querySelector('#cards .num') !== null")
        return page

    def test_loads_cleanly_offline(self):
        page = self.open()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.requests, [])
        self.assertEqual(len(page.query_selector_all("#cards .card")), 4)
        self.assertIn("flatters", page.inner_text("#verdict-title"))
        self.assertEqual(page.get_attribute("[data-preset=typical]", "aria-pressed"), "true")

    def test_presets_and_sliders_update_the_results(self):
        page = self.open()
        before = page.inner_text("#cards")
        page.click("[data-preset=clean]")
        page.wait_for_timeout(400)
        self.assertNotEqual(page.inner_text("#cards"), before)
        self.assertEqual(page.get_attribute("[data-preset=clean]", "aria-pressed"), "true")
        page.fill("#d-zombies", "0.8")
        page.dispatch_event("#d-zombies", "input")
        page.wait_for_timeout(400)
        self.assertEqual(page.inner_text("#o-zombies"), "80%")
        self.assertEqual(page.get_attribute("[data-preset=clean]", "aria-pressed"), "false")
        self.assertEqual(self.errors, [])

    def test_every_control_has_a_label(self):
        page = self.open()
        unlabelled = page.evaluate("""() => Array.from(document.querySelectorAll('input, select, textarea')).filter(el => {
            if (el.getAttribute('aria-label')) return false;
            return !(el.id && document.querySelector('label[for="' + el.id + '"]'));
        }).map(el => el.id || el.outerHTML)""")
        self.assertEqual(unlabelled, [])
        for svg in page.query_selector_all("svg[role=img]"):
            self.assertTrue(svg.get_attribute("aria-label"))

    def test_phone_width_has_no_sideways_scroll(self):
        page = self.open(390, 844)
        width = page.evaluate("document.documentElement.scrollWidth")
        self.assertLessEqual(width, 390)

    def test_extreme_settings_stay_responsive(self):
        page = self.open()
        page.fill("#deals", "8000")
        page.dispatch_event("#deals", "input")
        page.click("[data-preset=chaos]")
        page.wait_for_timeout(1200)
        self.assertEqual(self.errors, [])
        self.assertNotIn("n/a", page.inner_text("#cards"))


    def test_links_restore_settings(self):
        page = self.open(hash_="#seed=7&deals=3000&blanks=0.2&zombies=0.66")
        self.assertEqual(page.input_value("#seed"), "7")
        self.assertEqual(page.inner_text("#deals-out"), "3,000")
        self.assertEqual(page.inner_text("#o-zombies"), "66%")
        page.click("[data-preset=clean]")
        page.wait_for_timeout(300)
        self.assertIn("zombies=0&", page.evaluate("location.hash"))

    def test_save_and_load_settings_files(self):
        import json, tempfile, os
        page = self.browser.new_page(accept_downloads=True)
        page.goto(APP + "#seed=9")
        page.wait_for_function("document.querySelector('#cards .num') !== null")
        with page.expect_download() as dl:
            page.click("#save-file")
        data = json.loads(open(dl.value.path(), encoding="utf-8").read())
        self.assertEqual(data["settings"]["seed"], 9)
        data["settings"]["retrofill"] = 0.7
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "s.json")
            with open(good, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            page.set_input_files("#load-file", good)
            page.wait_for_timeout(300)
            self.assertEqual(page.inner_text("#o-retrofill"), "70%")
            bad = os.path.join(d, "bad.json")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("{oops")
            page.set_input_files("#load-file", bad)
            page.wait_for_timeout(300)
            self.assertIn("not a Fit to train settings file", page.inner_text("#share-note"))
            self.assertEqual(page.inner_text("#o-retrofill"), "70%")

    def test_compare_and_robustness(self):
        page = self.open(hash_="#deals=1000")
        page.click("#pin-a")
        page.click("[data-preset=chaos]")
        page.wait_for_timeout(400)
        self.assertGreaterEqual(len(page.query_selector_all("#compare-table tbody tr")), 9)
        page.click("#run-robust")
        page.wait_for_function("document.querySelector('#robust-out .robust-summary') !== null", timeout=30000)
        self.assertIn("of 12", page.inner_text("#robust-out"))
        page.click("[data-preset=tidy]")
        page.wait_for_timeout(400)
        self.assertIn("changed since the last test", page.inner_text("#robust-out"))
        self.assertEqual(self.errors, [])

if __name__ == "__main__":
    unittest.main()
